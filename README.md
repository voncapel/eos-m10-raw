# EOS M10 RAW video

Lossless RAW video on a Canon EOS M10 (firmware 1.10d), recorded to the SD card by a
CHDK module. No host computer is needed once the card is set up.

What works today: 2304 × 1076, 10-bit Bayer, 25 fps, lossless-compressed MLV, read 1:1
from the sensor (no line skipping) in Canon's ×5 magnifier. One-minute takes complete with
0 dropped frames on ordinary scenes. You start and stop takes with the camera's REC button.
`tools/m10export.py` turns a take into CinemaDNG or ProRes 4444 LogC3 for Resolve. Third-party
MLV players have not been tested much on these LJ92 files; one failed at the end of a
multi-chunk take.

This is a one-person research project on one camera. It is not a polished release, and there
is no installer that hides the risk. Read [Safety](#safety) before you put it on a card.

<iframe width="560" height="315" src="https://youtube.com" title="Canon EOS M10 - RAW video test" frameborder="0" allowfullscreen></iframe>


## How it works, briefly

The DIGIC 6 has a block (PACK32) that can send the sensor's RAW stream to an EDMAC channel.
Canon only uses it for occasional stills-pipeline captures. The module (`module/m10_cine.c`)
borrows it once per sensor frame, synced to a TG/DFE serial write (`8830`) that marks the end
of each readout, and copies the frame to RAM through EDMAC channel 12. Canon's own hardware
lossless-JPEG encoder (the one behind CR2 files) then compresses the frame, and a third task
writes it to the card in Magic Lantern's MLV format.

Three RAM patches make this possible without touching any engine register by hand:

- the magnifier's TgPixelRes record is copied and lengthened so Canon itself programs a
  25 fps frame (stock is 30 fps, and the encoder needs 35 ms per frame);
- a hook on Canon's SIO send pointer (`*(0x9b50)`) logs every sensor/TG write, which gives
  the frame sync;
- a stub replaces the head-error callback, so a sensor read hiccup is counted instead of
  shutting the camera down.

All three are removed when the shell exits, and none survive a power cycle.

## Status

| | |
|---|---|
| Camera / firmware | EOS M10, 1.10d only (addresses are hard-coded for 1.10d) |
| Mode | ×5 magnifier, 2592 × 1104 read, 2304 × 1076 recorded (centre crop of 2520 × 1076 active) |
| Depth / codec | 10-bit sensor data in a 14-bit lossless JPEG (LJ92) container, MLV class `0x21` |
| Rate | 25.0 fps steady, ~2.4-3.0 MB per frame, ~73-76 MB/s to the card |
| Longest clean take | 1500/1500 frames (60 s) at 2592 wide, 0 drops, 0 head errors |
| Known losses | ~3 frames missing at the start of every take; very detailed scenes exceed the card bus and drop about 1 frame in 8 while they last |
| Module version | v166 |

Full-sensor Film mode (1808 × 1184, 3×3 line skipping) also reaches 25 fps for a minute,
but the moiré and highlight banding made it unusable, so that path is frozen. See
[docs/HISTORY.md](docs/HISTORY.md).

## Quick start

You need: an EOS M10 on firmware 1.10d, a CHDK 1.7 build for `m10-110d` on a FAT32 card,
macOS or Linux with `arm-none-eabi-gcc`, Python 3 with `numpy` and `scipy`, and `ffmpeg`.

1. Build the module against a CHDK trunk checkout:

   ```sh
   git clone https://github.com/petabyt/chdk.git chdk   # mirror of CHDK SVN
   (cd chdk && git checkout ad402e1b)
   module/build.sh                                      # -> chdk/trunk/modules/.o4/m10cine.flt
   ```

2. Copy to the card: `m10cine.flt` into `CHDK/MODULES/`, `card/CHDK/SCRIPTS/M10SHELL.LUA`
   into `CHDK/SCRIPTS/`, and `card/M10HUF.BIN` to the card root (Huffman tables tuned on our
   footage; without it the encoder uses Canon's tables and the files get about 10 % bigger).
3. In CHDK, enable Lua native calls, load `M10SHELL.LUA` as the script, and run it (or set it
   to autostart). Leave the USB cable unplugged: the shell refuses to run with USB power.
4. Put the camera in M (photo) mode and touch the screen to open the ×5 magnifier. The shell
   shows a small RAW preview in the corner. REC starts a take, REC again stops it. Takes are
   `A/M10_0001.MLV` (+ `.M00`, `.M01` chunks under 4 GB), 3000 frames (2 min) at most.
   MENU + SET quits the shell.
5. On the computer:

   ```sh
   cc -O2 -o /tmp/ljc/lj92d tools/lj92d.c
   python3 tools/m10ljmlv.py --check M10_0001.MLV          # decode every frame
   python3 tools/m10export.py dng    M10_0001.MLV out_dng/  # CinemaDNG
   python3 tools/m10export.py prores M10_0001.MLV out.mov   # ProRes 4444, LogC3 / AWG3
   ```

## Safety

Things that went wrong during development and are now rules:

- Never read an MMIO register (`0xC0xxxxxx`, `0xC0E0xxxx`, `0xD0xxxxxx`) directly over PTP or
  from Lua. The camera freezes and needs the battery pulled. Read Canon's shadow copy instead
  (`Cam.shadow()` in `tools/m10ptp.py`).
- Do not change the shooting mode over PTP while a host session is open (`ASSERT OperTrns.c 649`).
  Use the dial.
- Do not upload files over USB while the magnifier is open (`ASSERT CtrlSrv.c 1035`).
- If the camera shuts down, read `ROMLOG.LOG` (CHDK debug menu) before anything else.
  `ShutdownReason 9 / ErrorNo 16` means ImgSens lost the sensor; it was always our DMA.
- Everything here is RAM-only and goes away on power-off. Nothing writes to flash, and no
  Canon code is in this repository. You still run unofficial code that drives DMA on your
  camera; a bug can make it shut down mid-take and lose that take.

## Repository map

| Path | What |
|---|---|
| `module/` | The CHDK module source, the Makefile patch and `build.sh` |
| `card/` | Files that go on the SD card besides the module |
| `tools/` | Host tools: PTP client, hooks, capture drivers, MLV decode/repair/export. Index in [docs/TOOLS.md](docs/TOOLS.md) |
| `tools/rom/`, `scripts/*.java` | ROM study helpers (need your own ROM dump and Ghidra project) |
| `scripts/*.LUA` | Early CHDK Lua probes (PACK32, crossbar, zoom capture), kept for reference |
| `docs/HANDOFF.md` | Start here to continue the work: open problems, ruled-out ideas, procedures |
| `docs/ARCHITECTURE.md` | The capture pipeline and the firmware facts it rests on |
| `docs/HISTORY.md` | How we got here, in order, including dead ends |

## Credits

CHDK (the port to the M10 and the module loader this runs in), Magic Lantern (the MLV format,
the DIGIC 6 interrupt and register notes on its wiki, and `crop_rec`, which pointed at most
of the sensor registers), and reyalp's DIGIC 6 SD overclocking thread on the CHDK forum.

## License

GPL v2, same as CHDK (see `LICENSE`). The module links against CHDK and is distributed under
its terms.
