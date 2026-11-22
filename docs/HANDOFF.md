# Handoff (`v185b`)

Where the project stands as of **22 November 2026 (`v185b`)**, what works on real hardware, what is
open next, and the rules/workflows that save time. Read [ARCHITECTURE.md](ARCHITECTURE.md) for the
underlying pipeline details.

---

## Current state (`v185b`)

- **Default mode**: `1440p 24p 10b` (`1920×1440`, `1:1`, `ImgMode 1`).
- **Full-width modes**: `Wide 1800 10b` (`1728×1800` `1:3`, `lclk = 640`), `Wide 1440 12b` (true 12-bit 24p), `Wide 1440 10b`.
- **14-bit mode**: `24p 2K 14b` (`2048×1076`) & `24p 1920 14b` in Canon's ×5 magnifier.
- **Hardware-validated**:
  - `1440p 24p 10b`: multi-minute continuous takes (`2000+` frames, 2 GiB chunk rolling), `0` drops, `0` head errors, ~16 fps live colour REC preview, instant half-press `1:1` focus zoom + peaking.
  - `Wide 1800 10b`: `542` continuous frames (`22.6 s`), `drops = 0`, `he_n = 0`, `LJ err = 0`, `24.000 fps`, ~21 fps live `3×` desqueezed REC preview (`ren_avg = 13 ms`), and `v185b` fixed Standby `x_lo` (`37600 µs`), overlay sentinel `(358, 21)`, and `WBInteg` profile-exit guard.
- **Host regression suite**: **42+ offline unit + ASan/UBSan C tests** covering `v167`, `hefix`, `v182`, `v183`, `v184` (576 bit-identity preview combos), and `v185/v185b` (144 Wide preview & dflush runs).

---

## Open next branches

### 1. In-camera Audio (`AUDF` / AK4957 I2S)
- Currently video-only. The M10's audio codec (`AK4957` over I2S) is idle in `ImgMode 1` (`Photo M`),
  meaning we can potentially capture 48 kHz 16-bit PCM directly into MLV `AUDF` blocks (and explore
  whether the codec supports an external mic / line input or internal stereo mics only).

### 2. Long-take qualification of `Wide 1800 10b` & `Wide 1440 12b`
- `Wide 1800 10b` has ~2 ms encoder headroom (`39.7 ms` avg / `41.67 ms` period; `M10_0043` had 1 busy-kick
  collision in 302 frames, `M10_0044` had `0` in 542 frames). Qualify multi-minute takes with 2 GiB roll
  on detailed outdoor scenes, and test `Wide 1440 12b` (`~36.6 ms` encoder) IRL as a potential default
  full-width profile.

### 3. Focus Pixel Map for `1440p` (`1:1`)
- `Wide 1:3` now has exact 8-site `.fpm` maps (`card/fpm/M10_wide_1728x1800.fpm`, `1728x1440.fpm`) and
  automatic interpolation in `tools/m10export.py`.
- `1440p` (`1920×1440` `1:1`) has a subtler `30×24` Hybrid CMOS AF II grid (mapped in `v183` probes)
  that can be given its own optional `.fpm` map if bright flat highlights ever show it.

### 4. Smaller quality-of-life items
- Takes are capped at `XR_MAX = 3000` frames (`125 s` @ 24p); raising `XR_MAX` only requires checking BSS
  headroom (must stay safely under ~340 KiB CHDK heap).
- On-screen shell messages (`sh_say()`) are currently in French.
- Optional higher-res Ximr / native Canon focus loupe (`536×400`) remains researched in reserve if the
  half-press `1:1` overlay zoom ever feels insufficient.

---

## Already tried — do not repeat

- **Wide `1:3` vertical stripes**: NEVER set `CMOS[3] = 0xf08` in `ImgMode 1` — it breaks the sensor OB
  clamp (`3.7–4.5 ADU` stripes, black drops `127 → 96`). Use only `CMOS[2] = 0x742` + `CMOS[5] = 0x020`.
- **Wide `1:3` `lclk = 521` or `PPP` direct Film writes in `ImgMode 1`**: `lclk = 521` causes H-sync wrap;
  direct `PPP` writes blank the frame. Use `lclk = 640` (`1800p`) or `732` (`1440p`) with `CDS = 0x0247`.
- **Continuous AF / STM lens moves inside `ImgMode 1`**: `EFLensCom.MoveFocus` is a silent no-op while
  `ImgSens == 1` (`AFTask` stopped), and Hybrid CMOS AF II phase signal does not survive `3×3` binning.
- **JpCore precision / bursts / unpacker**: precision `12/10`, unpacker `!= 0`, 4-component mode, and
  RD1 bursts `> 2 B` are all rejected or stall the encoder.
- **SD overclock**: the M10 already runs at Canon's max divider (speed 8, div 1 → `73–80 MB/s`).
- **Height wall in Film (`1190`) / ×5 (`1108`)**: permanently bypassed by using `ImgMode 1` instead.
- **Forbidden TG registers**: never touch `8170/8176/802c/8047/8079` or `x_dc = 13`.

---

## Development workflow

### Host setup

```sh
pip install pyusb numpy scipy capstone      # unicorn only for tools/rom/emu_commit.py
brew install libusb ffmpeg arm-none-eabi-gcc
mkdir -p /tmp/ljc && cc -O2 -o /tmp/ljc/lj92d tools/lj92d.c
```

### Building & verifying `m10cine.flt`

```sh
module/build.sh /path/to/chdk               # compiles with -mword-relocations, checks relocs
python3 -B -m unittest discover -s tools -p 'test_*.py'
```

- **Always build with `-mword-relocations`**: `PV_HOT` enables `-O2` on preview functions; without
  `-mword-relocations`, GCC emits `R_ARM_THM_MOVW_ABS_NC` (reloc 47) which CHDK's `.flt` loader rejects.
- **Keep BSS under ~340 KiB**: CHDK heap has ~362 KiB free; above that `module_run` returns `-1`.
- **Deploy & pull logs over USB** (camera plugged in, shell not running):
  ```sh
  python3 tools/standalone/deploy_m1.py --flt /path/to/m10cine.flt
  python3 tools/standalone/pull_logs.py
  ```
- Always verify uploaded `.flt` byte-for-byte, keep `Autostart = OFF` (`config 1053 = 0`) during dev,
  and read `ROMLOG.LOG` after any unexpected shutdown.

---

## Files on the SD card

| File | Direction | Role |
|---|---|---|
| `CHDK/MODULES/m10cine.flt` | read | The CHDK RAW video module |
| `CHDK/SCRIPTS/M10SHELL.LUA` | read | Standalone launcher & RAM-IPC helper for `ImgMode 1` / `Film 1×3` |
| `A/M10HUF.BIN`, `M10HUF12.BIN`, `M10HUF14.BIN` | read | Tuned 10/12/14-bit lossless Huffman tables |
| `A/M10SH.CFG` | read | Created automatically by `M10SHELL.LUA` (tells `m10cine.flt` to enter shell mode) |
| `A/M10USB.OK` | read | Optional dev marker: allows running the shell while USB is plugged in |
| `A/M10_NNNN.MLV`, `.M00`… | write | Recorded RAW takes (auto-split at `1900 MiB`) |
| `A/M10CINE.LOG` | write | Text telemetry log (RAM-buffered during takes, flushed after) |
| `A/M10TLF.BIN`, `M10CAP.BIN`, `M10HE.BIN` | write | Optional per-frame timing & head-error diagnostics |

---

## What is intentionally NOT in this repository

Canon ROM dumps, Ghidra databases, raw `.MLV`/`.BIN` captures, and notes containing decompiled
Canon code stay private. ROM tools (`tools/rom/`, `scripts/*.java`) expect your own ROM dump in
`dumps/` and Ghidra project in `ghidra/`.
