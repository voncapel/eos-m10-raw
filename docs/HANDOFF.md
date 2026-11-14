# Handoff

Where the work stopped (module v166, 13 November 2026), what is still open, and what has
already been tried, so you don't spend a week re-testing it. Read
[ARCHITECTURE.md](ARCHITECTURE.md) first if the register names below mean nothing yet.

## State of the camera and card

The card holds CHDK 1.7 for 110d, `CHDK/MODULES/m10cine.flt` (v166),
`CHDK/SCRIPTS/M10SHELL.LUA` set to autostart, `A/M10SH.CFG` (shell marker) and
`A/M10HUF.BIN`. The shell installs everything it needs at start and removes it on exit or
when a USB cable is plugged in, so the camera boots like a stock camera with CHDK.

What v164-v166 added after the last host-driven tests:

- v164: a "radar" in the magnifier showing the recorded window against what the LCD shows.
  Replaced in v166.
- v165-v166: a live preview made from our own RAW capture (no encoder, no card), 172 × 80 B&W
  thumbnail in the bottom-right corner, about 10 fps. Canon's live view stays visible for
  focusing. MENU toggles it. The preview only runs between takes.

Field log of four v165/v166 takes (2304 × 1076):

| take | frames | dropped | avg size | encoder |
|---|---:|---:|---:|---:|
| 1 | 332 | 37 | 3.03 MB | 31.1 ms |
| 2 | 589 | 172 | 3.55 MB | 31.1 ms |
| 3 | 689 | 11 | 2.81 MB | 31.1 ms |
| 4 | 1062 | 0 | 2.09 MB | 31.0 ms |

The encoder keeps up every time. Drops track frame size: above about 3 MB per frame
(75 MB/s) the card falls behind and the 9-slot compressed ring overflows. This is the main
open problem.

## Open problems, in the order I would attack them

### 1. Card bandwidth on detailed scenes

The SD bus tops out around 73-80 MB/s, and Canon already runs it at its fastest clock setting
(see live119 in HISTORY). The encoder output is inflated by the hardware: 10-bit samples are
coded as 14-bit values << 4, which costs about 40 % of the file. Options not yet tried:

- A bigger compressed ring. EXMEM is capped at 48 MiB by the config parser. The allocator
  can go lower than we use (FIRMUP pool down to `0x59158000`); more slots only buy seconds,
  though, not throughput.
- An adaptive crop: drop to a narrower `EW` when the backlog passes a threshold, and record the
  change in the MLV. Ugly for editing.
- The Magic Lantern digital-gain trick. ML fakes lower bit depths by reducing the
  pre-processing digital gain and capturing 14 bits, so the top bits are zero. Here the encoder
  is bounded by bytes read (RD1), so 14-bit input would be slower than the frame period.
  Probably dead, but nobody measured 12-bit + gain in the magnifier.
- Huffman tables tuned per scene. Worth about 4 %, and cheap.
- Deliberate frame skipping: drop every Nth frame cleanly when the backlog is high and write
  a duplicate-frame marker, instead of losing frames in bursts.

### 2. Lines beyond 1104 in the magnifier (the height wall)

The magnifier gives 1104 usable lines (1076 after OB). +32 lines through a coherent Canon
commit (Extract record 36, ImgSens cache 41, TG `8172/8178/82f8/82b6`) gives a head error on
15 of 16 frames, at 30 and 25 fps. The same wall exists in Film mode at 1190 lines. CMOS 1-8,
TG, DFE and engine registers have been swept without moving it. Unexplored: the SIO writers
`ppp`/CDS that were never decoded, CMOS 2/3/6, and how ML's `crop_rec` handles the EOS M
(same sensor family) on DIGIC 5. `tools/m10zoomtall.py` and `tools/m10tall3.py` are the
test harnesses.

### 3. Framing in the magnifier

The LCD shows 1032 × 688 of the 2592 × 1104 being recorded. Canon computes that window from
immediate constants in ROM (`fc22c7f2`, index 3 = ×5, index 4 = ×10, anything else asserts),
then copies the rectangle into a heap job record. There is no RAM function pointer on that
path to hook (live120-121). Left: a high-priority task racing Canon's recalculation (fragile),
or keep improving our own preview (v166).

### 4. Start-of-take gap

Every take misses about 3 frames (≈160 ms) right after the start. It shows up in the MLV frame
numbers but in none of the module's drop counters. Probably Canon or the sensor settling after
the first PACK32 take. Not investigated.

### 5. Smaller things

- Takes are capped at 3000 frames (`XR_MAX`, 2 min).
- File timestamps were 1 January 2000 on the first take after a battery change: check the
  camera clock. The MLV has its own timestamps.
- Shell messages on screen are in French (`sh_say()` strings in `m10_cine.c`).
- `m10export.py` uses a bilinear demosaic for ProRes. The DNG path leaves demosaicing to the app.

## Already tried, don't repeat

Encoder and compression:

- JpCore precision 12/10, point transform, `0x84`/`0x90`/`0x9c` pokes: all refused (`st 1`).
- Unpacker `0xc0f371fc` other than 0: `0x002` and `0x30` freeze the camera, `0x001` reads raw
  16-bit and overflows.
- RD1 bursts of 4, 8, 16 bytes, aligned or not: encoder stalls (900 ms, size 0).
- Two-slice or 4/8-slice encoding: no speed gain, more overhead.
- Four-component encoder layout: refused.

Card:

- SD overclock: the M10 already runs speed 8 (divider 1), which is what reyalp's overclock
  reaches on other DIGIC 6 cameras. Beyond that is an undocumented clock source.
- Windowed / chunked card writes during the sensor readout: either too slow or no effect.

Film mode (frozen, but in case you go back):

- Head errors in Film come from DRAM contention between CH12, the encoder, the card and Canon's
  1080p pipeline. `MOVOFF=8` (LvMovOptimus bit 3) is what made 25 fps possible.
- Film *manual* exposure mode doubles head errors versus Film auto, whatever the shutter speed.
- Continuous AF causes most head errors. Use MF.
- The 640 ms periodic DMA stretch is Canon's `WBCtrl` heavy cycle; `POKE=0x133c88=50` spaces it.
  A fixed white balance does not remove it.
- The line time (`0xc0f06008`) cannot be changed alone: the camera shuts down at once.
- Masking the head-error IRQ, changing EDMAC priority bits, cutting Canon crossbar channels,
  switching off the display: no effect, or shutdown.

## How to work on it

### Host setup

```sh
pip install pyusb numpy scipy capstone      # unicorn too, only for tools/rom/emu_commit.py
brew install libusb ffmpeg arm-none-eabi-gcc
cc -O2 -o /tmp/ljc/lj92d tools/lj92d.c      # the decoders expect it at this path
```

`tools/m10ptp.py` is a small CHDK PTP client. On macOS it kills `ptpcamerad`, which grabs the
camera otherwise. Most tools write their output to `captures/<session>/` next to `tools/`;
that folder is ignored by git.

### Host-driven tests (faster iteration than the shell)

The shell must not be running (unplug USB starts nothing; quit it with MENU + SET). Then:

```sh
M10HOOK=install6 python3 tools/m10wake.py   # after power-on: unlock the shooting screen, install SIO hook v6
python3 tools/m10hetrap.py install2         # head-error trap (re-run after every magnifier entry/exit)
python3 tools/m10zfps.py arm 1747 cache fld # 25 fps copy, BEFORE entering the magnifier
# user touches the screen to open the magnifier, then:
UNPK=0 CSH=0 ENC=11 EXM=48 HBN=16 HER=1 SKICK=1 NS="1 0 2" KW=8000 NORAW=1 \
  python3 tools/m10x3raw.py zoom 1500 1104 10 0 0 0x21000980 0 0x80000003 5000 11000 6 0 0 12 4 99
python3 tools/m10ljmlv.py --check captures/live71/<tag>_M10X3.MLV
```

`m10x3raw.py` writes `A/M10X3.CFG`, starts the module through CHDK's `module_run()`
(`0x3e8c71` in the running core, checked by prologue), and downloads the results.
The module reads its config as one line of space-separated fields (57 of them, some taking two values); the parser in
`lv_x3()` in `m10_cine.c` is the reference. `SH_RECIPE` in the same file is the shell's
built-in config.

To add a config field: parse it at the end of the field list in `m10_cine.c` and add it to
`cfg_tail()` in `tools/m10x3raw.py` with its default.

### Building and deploying a module

```sh
module/build.sh /path/to/chdk                # prints text/data/bss sizes
```

- Keep BSS under ~340 KiB. The module gets its BSS from the CHDK heap (~362 KiB free);
  above that, `module_run` returns −1.
- Keep a copy of the previous `.flt` and source before each change. Upload with
  `Cam(timeout=60000).upload(local, 'A/CHDK/MODULES/m10cine.flt')`, download it back and
  compare byte for byte. Never upload while the magnifier is open.
- The source at v166 rebuilds byte-identical against CHDK `ad402e1b` with
  arm-none-eabi-gcc 16.2.

### Habits that saved time

- Re-run a control take after every batch of instrumentation changes. A 3 KiB register diff at
  each DMA start once halved the stable run length without anyone noticing (live92).
- Read `ROMLOG.LOG` after every shutdown. The assert file and line usually name the culprit.
- Cold and warm cameras behave differently in Film mode. Note the sensor temperature and the
  battery voltage (`stat_get_vbatt`) with each result.
- The camera's USB often stops answering after a long take or a multi-GB download. Power-cycle
  it; nothing is lost but the RAM patches.
- `msleep(1)` sleeps about 10 ms on this camera. Use `SetHPTimerAfterNow` for real 1 ms timing
  (see `m10_tasktrace.h`).
- After a CHDK script changes its parameters, CHDK keeps the old ones in `CHDK/DATA/<script>.0`.

## Files the module reads and writes on the card

| File | Direction | What |
|---|---|---|
| `A/M10SH.CFG` | read | present = start in shell mode |
| `A/M10X3.CFG` | read | host-driven config |
| `A/M10Z.CFG` | read | present = allow capture in the magnifier (host tools) |
| `A/M10HUF.BIN` | read | custom Huffman tables, 2 × (BITS[16] + HUFFVAL[32]) |
| `A/M10_NNNN.MLV`, `.M00`... | write | shell takes |
| `A/M10X3.MLV`, `.M00`... | write | host-driven takes |
| `A/M10CINE.LOG` | write | text log, buffered in RAM during a take |
| `A/M10TLF.BIN`, `M10X3T.BIN`, `M10CAP.BIN`, `M10HE.BIN` | write | per-frame timelines, per-pass records, head-error list |
| `A/LVX3.BIN`, `LVX3S.BIN` | write | single-pass captures and their SIO/DMA chronology |

The binary formats are described where they are written in `m10_cine.c` (search for the
four-letter magic: `TLF1`, `CAP1`, `VHE1`, `1X3S`, `M10LVX03`).

## What's not in this repository

The ROM dump, the Ghidra project, the raw captures (about 33 GB) and the session notes with
decompiled Canon functions stay private: they contain Canon code or are too big. Tools that
need them (`tools/rom/`, `scripts/m10dis.py`, `scripts/decomp.sh`) expect `dumps/`, `ghidra/`
and `chdk/` next to `tools/`. You can dump your own ROM with CHDK.
