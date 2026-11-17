# Tools

Every Python tool has its usage in the docstring at the top of the file. Read it rather than
running a tool without arguments: some of them (`m10x3raw.py`) start a capture with defaults. Docstrings mention the session (`liveNN`)
where the tool was written; [HISTORY.md](HISTORY.md) has the context.

## Use these first

| Tool | What |
|---|---|
| `m10ptp.py` | CHDK PTP client over USB (pyusb). `Cam().read/shadow/call/lua/upload/download`. Use `shadow()` for engine registers, never `read()` |
| `m10wake.py` | After power-on: wake the shooting screen, install the SIO hook (`M10HOOK=install6`) |
| `m10sio.py` | SIO hook on `*(0x9b50)`: install, dump, stream, CMOS/TG overrides, `off` = panic button |
| `m10siodec.py` | Decode a saved SIO trace into register writes |
| `m10hetrap.py` | Head-error callback trap (`install2` = timestamped stub the module expects) |
| `m10zfps.py` | Magnifier at 25 fps through a RAM copy of TgPixelRes 46 (`arm 1747 cache fld`, `restore`) |
| `m10x3raw.py` | Host-driven capture: writes `A/M10X3.CFG`, runs the module, downloads results. Modes `zoom`, `film`, `x3` |
| `m10settings.py` | Save/check Canon settings that affect a test (AF, IS, ISO mode...). Read-only |
| `m10ljmlv.py` | Compressed MLV: `--check` (decode all), `--dng`, `--mp4` preview; head-error repair |
| `m10ljmp4.py` | Full-resolution H.264 from one or several chunks |
| `m10export.py` | CinemaDNG sequence or ProRes 4444 LogC3 / AWG3 for grading |
| `m10huff.py` | Optimal Huffman tables from sample captures -> `M10HUF.BIN` |
| `test_m10_v167.py`, `test_m10hefix.py` | Host unit tests of the module source (profiles, MLV chunking, drain, head-error replacement); need `cc` |
| `lj92d.c` | Lossless JPEG decoder used by all the readers (build to `/tmp/ljc/lj92d`) |
| `m10mlv.py` | MLV writer/reader, DNG with focus-pixel fix, chunk repair (`--fix`, `--fps`) |
| `m10raw2dng.py` | Single-frame DNG writer, with the EOS M10 colour matrix |
| `m10tasks.py`, `m10tasktrace.py` | DryOS task table snapshot (read-only) and the 1 ms task-sampler analysis |
| `m10lvx3dec.py`, `m10lvx3s.py` | Decode single-pass captures (`LVX3.BIN`) and their chronology (`LVX3S.BIN`) |
| `shell/USBPROBE.LUA` | Logs USB power and `physw_status` for 30 s (how the USB bit was found) |

## Investigations (useful as examples, not part of the workflow)

| Tool | Session | What |
|---|---|---|
| `m10zoomtall.py`, `m10tall*.py`, `m10head.py`, `m10holdan.py`, `m10tgcal.py`, `m10tgdiff.py` | live67-107, live117 | Taller head windows: Film and magnifier height tests |
| `m10extract.py`, `m10x3.py`, `m10commit.py`, `m10state.py`, `m10shadowdump.py` | live66-70 | Mode commits, Extract record, engine shadow dumps |
| `m10zoompan.py`, `m10cmos*.py`, `m10auto.py` | live63-66 | CMOS register discovery |
| `m10expo.py`, `m10level.py` | live109 | Exposure path: shutter/ISO as sent to the sensor |
| `m10tgfast.py` | live109 | Line-time test (shuts the camera down; kept as a warning) |
| `m10heseries.py`, `m10afclear.py` | live100 | Head-error rate vs DMA start; AF pixel defect |
| `m10zoomdisp.py`, `lvcb/` | live120-121 | Magnifier display window, callback probe |
| `m10lvn.py`, `m10lvm*.py`, `m10lvmap.py`, `m10lvw.py`, `m10cont.py` | probe53-109 | Normal live-view and Film pass analysis |
| `m10bpp.py`, `m10vid.py`, `m10cine2dng.py`, `m10x3dng.py`, `m10x3preview.py`, `m10dng2mp4.py`, `m10fpm.py` | probe40-live102 | Readers for older module output formats |
| `m10lvgrab.py` | | Live view snapshot over PTP |
| `x3diag/` | live83-86 | Decoders for Film-mode pass logs (own README) |
| `ljrec.sh` | live110-114 | Film 3×3 REC driver with the recipe of that time |
| `siohook/` | live63-82 | Sources of the SIO hook blobs v1-v6 (`.S`, assembled `.bin` loaded by `m10sio.py`) |
| `rom/` | | ROM helpers: xrefs, source-file index of the 110f ROM, unicorn emulation of a Film commit. Need your own ROM dump in `dumps/` |

## scripts/

`install_m10_chdk.py` checks a card (firmware sub-version from the photos, FAT32) and unzips
a CHDK build. The `*.LUA` files are the first CHDK Lua probes, before the C module existed:
`M10PK32.LUA` / `M10PKFR.LUA` / `M10PKYN.LUA` are the PACK32 zoom captures of probe21-37,
`M10PORTS.LUA` + `analyze_ports.py` the crossbar scan. `Decomp.java`, `ImportChdkLabels.java`
and `decomp.sh` drive headless Ghidra (paths assume Homebrew and a `ghidra/` project).

## Tests

```sh
python3 -B -m unittest discover -s tools -p 'test_*.py'        # 61 offline tests, no USB
cc -std=c11 -Wall -Wextra -Werror tools/test_m10tasktrace_device.c -o /tmp/t && /tmp/t
```
