# Architecture

How a RAW frame gets from the EOS M10 sensor to an MLV file, and the firmware facts each step
depends on. Addresses are for firmware 1.10d unless marked 110f (the ROM we disassembled
first; most code is at the same address, not all of it).

## Words used here

- **Head**: the sensor readout front end of the DIGIC 6 (registers `0xc0f06xxx`/`0xc0f07xxx`).
  `0xc0f06804` holds lines << 16 | columns. In the ×5 magnifier it reads `0x045702a6`.
- **TG / DFE**: timing generator and front-end chip, programmed by Canon over SIO channel 4.
  The DFE write to register `8830` happens once per frame and is our frame clock.
- **CMOS registers**: 12-bit sensor registers sent on SIO channel 6 (`reg << 12 | val`).
- **PACK32**: the block that packs head output to 10/12/14 bits and feeds the crossbar port `0x00`.
- **EDMAC**: DMA channels. Write channels 0-24, read channels 25-47 (ROM table `0xfc6d87b8`).
  We use write channel 12 (`0xc0f26500`).
- **Shadow**: Canon keeps a RAM copy of every engine register it writes (`EngDrvOut`),
  at `*(0x28dbc) + (reg & 0x7ffff)`. This is the only safe way to read engine registers.
- **OB**: optical black, masked pixels. 72 columns on the left and 28 rows at the top in
  the magnifier (84/28 in Film mode). Black level is 127.5 in 10-bit units, 2048 in 14-bit (`0x10` HEAD tap, v171+).
- **Film 3×3 / 1×3**: Canon's movie mode reads every third line and bins columns by 3 (3×3).
  1×3 is the Magic Lantern-style variant that reads every line (TG `0x800c` = 0).
- **Magnifier**: the ×5 focus loupe. It reads a 2592 × 1108 window at 1:1, no skipping.

## The pipeline

```
sensor ── head ── PACK32 ── crossbar port 0x00 ── EDMAC CH12 ──> raw ring (RAM, 3 frames)
                                                                       │
                       LosslessEncode / JpCore (Canon's CR2 encoder) <─┘
                                         │
                                  compressed ring (9-13 slots) ──> writer task ──> A/M10_NNNN.MLV
```

Three DryOS tasks, all created by the module:

| task | priority | job |
|---|---|---|
| capture (`M10Cine` / `M10Shell`) | 0x1A | waits for the frame sync, takes PACK32 + resources, arms CH12, waits for the end of the DMA, releases, starts the encoder |
| encoder (`M10LJ`) | 0x1B | collects the encoder result, wraps it in a VIDF block |
| writer | 0x1C | writes compressed frames to the card, rolls to `.M00`, `.M01` before 4 GB |

Priority 0x19 for the encoder starves the capture task. Don't.

### 1. Frame sync

`8830` is written once per frame by Canon. The SIO hook keeps a ring of every SIO frame with a
microsecond timestamp, and the capture task waits for a new `8830` plus 5-6 ms before arming
CH12. In the magnifier at 25 fps, the readout then runs from about `8830 + 14 ms` to `+ 34 ms`.
Arming outside that window loses lines or overlaps the next frame. The timestamps are a 20-bit
µs counter that wraps every 1.048 s. Unwrap it before sorting, or you get fake "two syncs per
frame" (see live115b).

### 2. Taking PACK32 for one frame

Per frame, the module replays what Canon's `CaptureSystem.c` does for a single capture:

1. lock Canon resources `{0x61 (CH12), 0x5f (CH10), 0x84}` with `0xfc373f9e`;
2. take PACK32 semaphore #6 (`0xfc22f738`);
3. `0xfc22f73e(bpp, 0)`: RAW type `0x12` in `0xc0f37014`, depth in `0xc0f08094`, enable
   `0xc0f08090 = 1`. Pack mode 2 is the one the encoder can read;
4. `ConnectWriteEDmac(12, 0)` (crossbar `0xc0f05210`);
5. program CH12 as a 2-D transfer (address, x/y sizes) and start it (`ctl = 1`);
6. at the end: `ctl = 2`, wait for `ctl = 0`, restore PACK32 registers, then release the
   semaphore and the resources.

Rules learned the hard way:

- One EDMAC block must stay under 4 MiB. A 2-D geometry with two blocks of ~550 lines
  copies a whole 5.7 MB frame in one transfer.
- Restarting a channel without reprogramming address and sizes completes at once and writes nothing.
- Restore the hardware state before releasing the semaphore. Doing it in the other order
  overwrote registers Canon had just written and caused `ErrorNo 16` shutdowns (probe56).
- A pending CH12 completion from a previous frame is consumed by the next start. Send an
  explicit stop (`ctl = 2`) before re-arming.
- Holding PACK32 across frames does not work: the next frame gets no lines and the camera
  shuts down (live86). Canon needs the semaphore between frames.
- 4-byte transfers are required for the full RGGB mosaic; 2-byte transfers deliver only the
  R/G lines, de-interleaved (probe26).
- In the magnifier, only CH12 under the resource lock is reliably clocked. A channel that looks
  idle (CH8) is used by Canon's live view a few ms later.

### 3. Head errors

When the head FIFO under-runs, the head IRQ handler (`Head.c`, `0xfc17b61c`) calls the
callback at `[0xfa80]`. Canon's callback (`0xfc1ee9a9`) treats status bits 5/6 as fatal and
shuts the camera down 300 ms later. `tools/m10hetrap.py` and the shell replace it with a stub
that counts and timestamps the error. The pointer is reset by Canon at every magnifier
entry/exit, so the shell re-installs it on every loop.

With `HER=1` (no-pause recovery), a frame with a head error is kept. It loses ~230 rows
at the bottom, and every later frame in the take is shifted by 12 px once (the shift does not
accumulate). `tools/m10ljmlv.py` measures the shift on the OB edge, undoes it, and patches
damaged rows from the previous frame. In the magnifier we have not seen a head error in any
recorded take; in Film mode they were about 1 frame in 30 when warm.

### 4. 25 fps in the magnifier

The magnifier runs at 30 fps (33.3 ms) by default. The encoder needs ~35 ms per 2592-wide
frame, so 30 fps is impossible. Writing the frame-length register directly shuts the camera
down. Instead:

- TgPixelRes is a RAM table of pointers to ROM records, `0x2cdc0[DrvType]`. The magnifier is
  DrvType 46 (ROM `0xfc73045c`).
- We copy that record to RAM, set the frame length to 1747 lines (`+0x0c`, `+0x10`),
  `+0x80` = 1747 − 57 and the period `+0xc8` = 40017 µs, copy FldSpec 46 (`0xfc7308e8`) with
  the same period, patch the ImgSens cache entry for mode 41 (`0x575b0 + 36 × 41 + 0x1c`),
  and point the table at the copies.
- When the user next enters the magnifier, Canon programs the head, TG and exposure from
  the copy itself. Nothing touches an engine register.

`tools/m10zfps.py` does this from the host; `sh_arm_25p()` in the module does it in the shell.

### 5. Compression

`LosslessEncode.c` drives `JpCore.c` (registers `0xc0e00000`, write-only: reading them
freezes the camera). Entry points on 110d: init `0xfc58183e`, CBR `0xfc581828`, setup
`0xfc581eec`, start `0xfc582066`, stop `0xfc5820f4`.

- JpCore only accepts precision 14 in lossless mode. Precision 12, 10, and point transform
  changes are rejected at once (`st 1`).
- The input reader (RD1, connection `0xf0`) accepts 10-bit packed data. We set up the encoder
  in 14 bits, then redo RD1 at 10 bits and set the unpacker `0xc0f371fc = 0`. The unpacker
  left-aligns: decoded samples are the 10-bit values << 4, bit-exact.
- Those 4 empty low bits cost about 40 % of file size. There is no known way to remove them in
  hardware (unpacker values other than 0 freeze the camera or overflow).
- v170+: true 14-bit input avoids the problem. PACK32 is fed from the `0x10` (HEAD) tap at 14
  bits, RD1 stays at 14 bits, and the encoder's native crop (`args[0]`/`args[3]`, source stride
  2592) reads only 1920 or 2048 columns. 2048 × 1104 × 14 bits = 3.96 MB of input (< 4 MiB,
  two CH12 blocks), ~39.4 ms per frame: fits 24.000 fps, not 25.
- Use `A/M10HUF14.BIN` for 14-bit takes (loaded automatically when the depth is 14). The 10-bit
  table gives 12-13-bit codes to common categories and heavy `0xff 0x00` stuffing (+33 %).
- RD1 only works with 2-byte bursts. 4/8/16-byte bursts stall the encoder.
- Encoder speed is bounded by RD1 reads: ~100 MB/s of input, ~35 ms for 2592 × 1104.
- Custom Huffman tables (`A/M10HUF.BIN`, made by `tools/m10huff.py`) must have exactly 15
  symbols (categories 0-14). 16 symbols are refused.

### 6. Card writes

- The SD controller already runs at Canon's highest clock setting (speed 8, divider 1).
  We measured ~73-80 MB/s in camera; going higher would mean an undocumented clock source.
- Never write to the card from the capture task, not even a log line. One `open/write/close`
  of a log file costs 60-80 ms and two frames (live114b). The module buffers its log in RAM
  during a take and flushes it afterwards.
- MLV files are split ML-style below 4000 MiB (FAT32).

## Other firmware facts worth knowing

| Address (110d) | What |
|---|---|
| `0x9b50` | SIO send function pointer (Canon value `0x121`). Our hook goes here. |
| `0xfa80` | head-error callback pointer (Canon `0xfc1ee9a9`) |
| `0x28dbc` | pointer to the engine register shadow |
| `0x2cdc0` | TgPixelRes pointer table, 57 entries; FldSpec table at `+0xe4` |
| `0x575b0` | ImgSens mode cache, 36 bytes per mode; current mode index at `[0x865c]` |
| `0x57d20` | magnifier rectangle struct (`+0x18`: cx, cy, x0, y0, x1, y1 in readout coordinates) |
| `0x133c88` | WBSmth threshold (Canon sets 5 in Film). Raising it to 50 spaces out the heavy WB statistics cycle that stretched our DMA every 640 ms in Film mode |
| `0x35d60 + 0x1c` | LvMovOptimus flags. Clearing bit 3 stops Canon's per-frame 1080p YUV channel (CH24) in Film mode, which was the decisive bandwidth lever there. Clearing bit 4 asserts `LiveImageTask.c 261` |
| `0x803c` | current DryOS task (TCB), validated on 110d by signature |
| `0x56bec + 8` | `physw_status[2]`; bit 28 = USB power |
| `0x010e1000` | SD driver code, copied to RAM from ROM `0xfceb18d0` at boot |

Sensor modes (LVDSSpec table, RAM `0x2cd24`): Film 1808 × 1190 at 25 fps, normal live view
1808 × 727, magnifier 2592 × 1108, full sensor 5280 × 3529. The line time is 16.25 µs in every
mode except the magnifier (22.9 µs) and 1:1 stills; no Canon mode reads a line faster.

## The height wall

Neither Film mode nor the magnifier gives more lines than Canon's default. In Film, a
coherent commit with a taller head passes, every geometry register follows, but the sensor
stream freezes after line 1190. In the magnifier, +32 or +64 lines give a head error on
almost every frame, at 30 and at 25 fps. No SIO register written at live-view start carries
the limit. Our guess is a limit inside the sensor's mode or the LVDS receiver. This is open;
see the handoff.
