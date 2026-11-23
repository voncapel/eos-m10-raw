# Handoff (`v186`)

Where the project stands as of **23 November 2026 (`v186`)**, what works on real hardware, what is
open next, and the rules/workflows that save time. Read [ARCHITECTURE.md](ARCHITECTURE.md) for the
underlying pipeline details.

---

## Current state (`v186`)

- **100% `ImgMode 1` unified cinema shell** with **Magic Lantern-style Size × Bit-Depth HUD** (`ISO | Tv | F | SIZE | BIT | Z+P | VIEW`).
- **Default mode**: `1920×1440 24p 14b` (`4:3`, `1:1`, optically centred `x0 = 0x84`, `14.9 ms` encode, `70.6 MB/s` SD).
- **10 hardware-qualified sizes** (`1440 4:3`, `2K 4:3` `2048×1536`, `2.2K 3:2` `2160×1440`, `2.3K 16:9` `2304×1296`, `2.6K 2.4` `2592×1088`, `Wide 1800` `1728×1800`, `Wide 1440` `1728×1440`, `1080 30p` `1920×1080`, plus 10b-only `2.3K 3:2` `2304×1536` and `2.6K 1.8` `2592×1440`).
- **Major breakthrough (`r161b`/`r161c`)**:
  - **`LCLK_HOLD0` (`0xfc1803f3` / `0xfc180429`)** + **`ClockSave` (`0xfc1ec6d7` / `0xfc1ec6ed`)** accelerate `JpCore` **`2.4×–3.4×`** (`238 MB/s` in 10-bit, **`325–339 MB/s`** in 14-bit — `11.0–16.9 ms/frame`), eliminating the encoder bottleneck permanently.
  - **2-block CH12 DMA (`> 4 MiB` up to `8 MiB`)** verified seam-free (`0` drops, `0` HE, `6/6` MLV decoded) on `1920×1440 14b` through `Wide 1800 14b` and `2592×1440 10b`.
  - **True 14-bit (`A/M10HUF14.BIN`)** is both higher dynamic range AND lighter on SD (`~1.00 B/px`) than 12-bit (`~1.07 B/px`).
  - **Live 10/12/14-bit colour preview** (`FIT` aspect ratio + `720×400` `1:1` focus zoom + peaking + zebras) verified under ASan/UBSan across all 10 profiles × 26 bit-depth combinations.
- **Host regression suite**: **117 offline unit + ASan/UBSan C tests** (`test_m10_v186.py` + `v167..v185`, `hefix`, `m10export`, `task*`).

---

## Open next branches

### 1. In-camera Audio (`AUDF` / AK4957 I2S)
- Currently video-only. The M10's audio codec (`AK4957` over I2S) is idle in `ImgMode 1` (`Photo M`),
  meaning we can potentially capture 48 kHz 16-bit PCM directly into MLV `AUDF` blocks (and explore
  whether the codec supports an external mic / line input or internal stereo mics only).

### 2. Higher-framerate (`30p` / `48p` / `60p`) & SD-card-friendly 14-bit options
- With `JpCore` running at `330 MB/s`, `1920×1080 14b @ 30.004p` takes only `11.0 ms` (`57 MB/s` SD).
  Smaller heights (e.g. `1920×816` scope or `1600×900` @ `48p` / `60p`) are now mechanically feasible
  subject to sensor `fl` / readout limits.

### 3. Focus Pixel Map for `1:1` modes
- `Wide 1:3` has exact 8-site `.fpm` maps (`card/fpm/M10_wide_1728x1800.fpm`, `1728x1440.fpm`) and
  automatic interpolation in `tools/m10export.py`.
- `1:1` modes have a subtler `30×24` Hybrid CMOS AF II grid that can get an optional `.fpm` map if
  bright flat highlights ever show it.

### 4. Smaller quality-of-life items
- Takes are capped at `XR_MAX = 3000` frames (`125 s` @ 24p); raising `XR_MAX` only requires checking BSS
  headroom (must stay safely under ~340 KiB CHDK heap; currently `181 KiB` BSS).
- On-screen shell toasts (`sh_say()`) are currently in French.
- Persistent user preferences (remember last `SIZE`, `BIT`, `ISO`, `Tv` across power cycles).

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
