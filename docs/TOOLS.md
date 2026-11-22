# Tools

Every Python script has its exact usage in the docstring at the top of the file. Read it before
running a tool without arguments — some capture drivers (`m10x3raw.py`) start a capture immediately
with defaults.

## Everyday workflow (export & deploy)

| Tool | What it does |
|---|---|
| `m10export.py` | **Main export tool**: converts `.MLV` (+ `.M00`… chunks) to **CinemaDNG** or **ProRes 4444 (ARRI LogC3 / AWG3)**. Auto-handles 10/12/14-bit, `ImgMode 1` active area, and for Wide `1:3`: automatic 8-site PDAF focus-pixel cleanup (`FPM=1`) and `3:1` desqueeze metadata (`DefaultScale` / `setsar=3/1`). |
| `m10wide_fpm.py` | Generates standard MLVApp `.fpm` Focus Pixel Maps for Wide `1:3` (`1728×1800` / `1728×1440`, 8 exact R/B PDAF sites) and verifies before/after noise reduction on an `.MLV`. |
| `m10ljmlv.py` | Compressed `.MLV` inspector & decoder: `--check` (verify every frame), `--dng`, `--mp4` preview, head-error repair. |
| `m10ljmp4.py` | Full-resolution H.264 preview from one or several `.MLV`/`.M00` chunks. |
| `lj92d.c` | Fast baseline lossless JPEG decoder used by all readers (`cc -O2 -o /tmp/ljc/lj92d tools/lj92d.c`). |
| `standalone/deploy_m1.py` | Uploads `m10cine.flt`, `M10SHELL.LUA`, and Huffman tables over USB with bit-exact readback verification. |
| `standalone/pull_logs.py` | Pulls `M10CINE.LOG`, `ROMLOG.LOG`, and diagnostics from the camera into `captures/diag_<timestamp>/`. |

## Camera control & host-driven capture (USB / PTP)

| Tool | What it does |
|---|---|
| `m10ptp.py` | CHDK PTP client over USB (`pyusb`). `Cam().read/shadow/call/lua/upload/download`. Always use `shadow()` for engine registers, never `read()`. |
| `m10wake.py` | Unlocks the shooting screen after power-on and installs `siohook6` (`M10HOOK=install6`). |
| `m10sio.py` / `m10siodec.py` | Installs/streams the SIO hook on `*(0x9b50)`, programs CMOS/TG overrides, decodes traces (`off` = panic button). |
| `m10hetrap.py` | Installs the timestamped head-error callback trap (`install2`). |
| `m10zfps.py` | Arms 25p/24p in the ×5 magnifier via a RAM copy of `TgPixelRes[46]`. |
| `m10x3raw.py` | Host-driven capture harness (`A/M10X3.CFG` → `module_run()` → pull results). |
| `m10huff.py` | Builds optimal 15-symbol Huffman tables from sample takes (`M10HUF*.BIN`). |
| `m10x3fix.py` | Legacy post-processor for slow-line `Film 1×3` column stripes (not needed for `ImgMode 1` Wide `1:3`). |
| `m10mlv.py` / `m10raw2dng.py` | MLV reader/writer, chunk repair (`--fix`, `--fps`), and single-frame DNG writer with EOS M10 colour matrix. |
| `m10settings.py` | Read-only snapshot/check of Canon settings that affect captures (AF, IS, ISO mode). |
| `m10tasks.py` / `m10tasktrace.py` | DryOS task table snapshot and 1 ms task-sampler trace decoder. |
| `m10lvx3dec.py` / `m10lvx3s.py` | Decodes single-pass `LVX3.BIN` raw dumps and `LVX3S.BIN` SIO/DMA chronologies. |

## Host regression tests (offline, no camera needed)

```sh
python3 -B -m unittest discover -s tools -p 'test_*.py'
cc -std=c11 -Wall -Wextra -Werror tools/test_m10tasktrace_device.c -o /tmp/t && /tmp/t
```

| Test suite | What it verifies |
|---|---|
| `test_m10_v185.py` | Wide `1:3` profiles, CMOS `2/5/7` (never `CMOS[3]`), `[0xfc3c]` IPC (`+0x280`), 144 ASan+UBSan Wide preview/dflush runs, `v185b` Standby `x_lo`/sentinel/`WBInteg` contracts |
| `test_m10_v184.py` | 576 bit-identical `1440p` preview combos (`v184b`/`v184c`), LUTs, async Standby/REC tasks, half-press toggle, stability guards |
| `test_m10_v183.py` | Focus peaking, pre-roll, µs timestamps, `M10SHELL.LUA` IPC |
| `test_m10_v182.py` | `ImgMode 1` RAM tables, opaque overlay mask, `M10WB` watchdog, `hostlua` IPC simulation |
| `test_m10hefix.py` | Zero-copy in-camera `HEAD_ERR` slot replacement worker |
| `test_m10_v167.py` | Legacy ×5 profile table, MLV chunking, and LJ drain |
| `test_m10task*.py` | DryOS task table parser & 1 ms task-sampler config |

## Investigation scripts & ROM helpers

Early R&D tools kept for reference: `m10zoomtall.py`, `m10tall*.py`, `m10head.py`, `m10extract.py`,
`m10commit.py`, `m10cmos*.py`, `m10expo.py`, `m10tg*.py`, `m10heseries.py`, `m10afclear.py`,
`m10lv*.py`, `x3diag/`, `siohook/` (ARM assembly sources v1–v6), `tools/rom/` (xrefs, 110f source
index, unicorn commit emulator — requires your own ROM dump in `dumps/`), and `scripts/` (early
CHDK Lua probes, `install_m10_chdk.py`, and headless Ghidra scripts).
