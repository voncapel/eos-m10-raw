# EOS M10 RAW Video

Turn a **Canon EOS M10** (firmware `1.10d`) into a **standalone 14-bit cinema RAW camera** — recording lossless **14-bit, 12-bit, and 10-bit** `.MLV` video directly to the SD card at **24p & 30p**, with live colour preview, focus peaking, zebras, and a Magic Lantern-style on-camera HUD.

**No computer is needed to shoot**, and **nothing is ever flashed to the camera** (everything runs in RAM via a CHDK module and disappears completely when you turn the camera off).

[![Canon EOS M10 - RAW video test](https://img.youtube.com/vi/bDyuFj6pS3c/hqdefault.jpg)](https://www.youtube.com/watch?v=bDyuFj6pS3c)

> **Status (`v186`)**: One-person open-source R&D project on one camera (`1.10d` only). Using Canon's own **`LCLK_HOLD0`** turbo-clock API (`3.3×` faster hardware lossless encoder: **325–339 MB/s** in 14-bit!) and 2-block sensor DMA (`> 4 MiB`), all 10 modes run natively inside `ImgMode 1` with **zero line-skipping**, **true optical centring**, and **0 dropped frames** on fast SD cards. Read [Safety](#safety--faq) before putting it on a card.

---

## What It Can Shoot (`v186`)

On the camera, pick a **SIZE** (10 hardware-qualified formats) and a **BIT DEPTH** (**`14b` / `12b` / `10b`**) independently — just like Magic Lantern's `mlv_rec` selector. Unsupported bit depths are greyed out automatically.

All modes record lossless-compressed RAW (Canon's hardware CR2 lossless JPEG encoder, wrapped in Magic Lantern `.MLV` files) with **live colour preview**, **green Focus Peaking**, and **half-press `1:1` zoom** in Standby and REC.

| Size (on HUD) | Resolution | Sensor Readout | Aspect / FOV | Bit Depths | FPS | Typical SD Rate (`14b` / `10b`) | Best For |
|---|---|---|---|---|---|---|---|
| **`1440 4:3`** *(default)* | `1920 × 1440` | `1:1` pixel-accurate (centred) | `4:3` | **`14b`** · `12b` · `10b` | `24.00p` | `70` / `58 MB/s` | Everyday sharp 14-bit cinema & C-mount lenses |
| **`2K 4:3`** | `2048 × 1536` | `1:1` pixel-accurate (centred) | `4:3` *(+14% area)* | **`14b`** · `12b` · `10b` | `24.00p` | `75` / `69 MB/s` | Maximum `4:3` 14-bit resolution |
| **`2.2K 3:2`** | `2160 × 1440` | `1:1` pixel-accurate (centred) | `3:2` *(native APS-C ratio)* | **`14b`** · `12b` · `10b` | `24.00p` | `76` / `69 MB/s` | Native `3:2` 14-bit framing |
| **`2.3K 169`** | `2304 × 1296` | `1:1` pixel-accurate (centred) | `16:9` | **`14b`** · `12b` · `10b` | `24.00p` | `74` / `68 MB/s` | Pure 2.3K `16:9` 14-bit |
| **`2.6K 2.4`** | `2592 × 1088` | `1:1` pixel-accurate (50% APS-C) | `2.38:1` scope | **`14b`** · `12b` · `10b` | `24.01p` | `71` / `60 MB/s` | Ultra-wide `1:1` cinemascope in true 14-bit |
| **`Wide1800`** | `1728 × 1800` | `1:3` horiz. binning *(0 stripes)* | **100% APS-C width** (`2.88:1` / `2.39:1` desqueezed `5184×1800`) | **`14b`** · `12b` · `10b` | `24.00p` | `70` / `68 MB/s` | **Full-width APS-C 14-bit cinema**, zero horizontal crop |
| **`Wide1440`** | `1728 × 1440` | `1:3` horiz. binning *(0 stripes)* | **100% APS-C width** *(desqueezed `5184×1440`)* | **`14b`** · `12b` · `10b` | `24.00p` | `57` / `54 MB/s` | Full-width 14-bit with lower SD bitrate |
| **`1080 30p`** | `1920 × 1080` | `1:1` pixel-accurate (centred) | `16:9` | **`14b`** · `12b` · `10b` | **`30.00p`** | `57` / `52 MB/s` | Smooth **30 fps true 14-bit RAW** |
| **`2.3K 3:2`** | `2304 × 1536` | `1:1` pixel-accurate (centred) | `3:2` | `10b` only *(14b/12b greyed)* | `24.00p` | — / `81 MB/s` | Max `3:2` `1:1` area (requires fast V60/V90 card) |
| **`2.6K 1.8`** | `2592 × 1440` | `1:1` pixel-accurate (50% APS-C) | `1.80:1` (`3.73 Mpx`) | `10b` only *(14b/12b greyed)* | `24.01p` | — / `81 MB/s` | Max `1:1` sensor area (requires fast V60/V90 card) |

> **Why is `14-bit` both better AND lighter on the SD card than `12-bit`?**
> Canon's lossless encoder runs natively in 14-bit. Our `12-bit` path shifts samples left by 2 bits into the 14-bit container (adding 2 bits of entropy noise per pixel), whereas native `14-bit` with `M10HUF14.BIN` encodes directly at unity gain (`~1.00 B/px` compressed vs `~1.07 B/px` for 12-bit) — **higher dynamic range AND smaller files**!

### What does "Wide `1:3` desqueezed" mean?

Think of it like shooting with a **3× anamorphic lens** — except done inside the sensor itself. To capture **100% of the APS-C width** at 24 fps with **zero vertical line-skipping** (no moiré, no stair-stepping), the sensor merges 3 horizontal pixels into 1 (`5184 → 1728` wide) while reading every single vertical line (`1440` or `1800` tall).

- **On the camera screen**, the shell stretches the preview `3×` live so framing looks completely normal, with subtle `2.39:1` cinemascope guide marks.
- **In post**, `tools/m10export.py` (or MLVApp) stretches the width back `3×` automatically — giving you full-width APS-C widescreen in true 14-bit RAW.

---

## Shooting On-Camera (Controls Cheat Sheet)

Once launched, the shell takes over the screen with a Magic Lantern-inspired cinema HUD:
- **Top bar**: `REC` dot + timer, active `SIZE + BIT` (`1920x1440 24p 14b`), real-time remaining card minutes, battery meter.
- **Bottom bar** (7 fields): `ISO` · `Shutter` · `Aperture` · **`SIZE`** · **`BIT`** · `Z+P` *(Zebras / Focus Peaking)* · `VIEW` (`FIT` / `WIDE` / `1:1` / `OFF`).
- **Magic Lantern `BIT` bar**: selecting **`BIT`** pops up an opaque **`14b  12b  10b`** strip directly above the bottom bar — active depth highlighted, supported depths in white, unsupported depths greyed out. Changing bit depth is **instant** (no sensor re-arm).

| Control | Action |
|---|---|
| **Mode dial → `M`** | Required for `ImgMode 1` (Photo Manual mode) |
| **▲ / ▼** | Select a setting on the bottom bar (`ISO`, `Tv`, `F`, `SIZE`, `BIT`, `Z+P`, `VIEW`) |
| **◄ / ►** | Change the selected value (or pick `14b / 12b / 10b` on `BIT`) |
| **Half-press shutter** | **Instant `1:1` focus zoom (`720×400` centred) with green Focus Peaking** — works in Standby **and** while recording! |
| **REC** *(or **SET**)* | Start / stop recording (`M10_0001.MLV`, auto-splits into 2 GB chunks for continuous takes) |
| **Hold MENU (1 s)** *(or **MENU + SET**)* | Exit the shell cleanly and return all buttons to Canon |
| **Plug in USB cable** | Automatically stops and exits the shell so you can copy files to your computer |

---

## 5-Minute Setup

### Requirements

- **Canon EOS M10** running firmware **`1.10d`** *(other firmware versions will not work — addresses are specific to `1.10d`)*.
- **Fast FAT32 SD card** (UHS-I V30/V60/V90 capable of ~70–80 MB/s sustained write; cards ≥ 64 GB must be formatted FAT32/MBR for CHDK autoboot).
- **[CHDK 1.7](https://chdk.fandom.com/wiki/CHDK)** build for `m10-110d` installed on the card.
- **To compile the module** (macOS or Linux): `arm-none-eabi-gcc`, `git`, `make`.
- **To export footage**: Python 3 (`numpy`, `scipy`), a C compiler (`cc`), and `ffmpeg`.

### 1. Build `m10cine.flt`

```sh
git clone https://github.com/petabyt/chdk.git chdk   # mirror of CHDK SVN
(cd chdk && git checkout ad402e1b)
module/build.sh                                      # outputs chdk/trunk/modules/.o4/m10cine.flt
```

### 2. Copy 5 files to your SD card

```text
SD Card (FAT32)
├── M10HUF.BIN               ← card/M10HUF.BIN      (10-bit compression table)
├── M10HUF12.BIN             ← card/M10HUF12.BIN    (12-bit compression table)
├── M10HUF14.BIN             ← card/M10HUF14.BIN    (14-bit compression table — essential!)
└── CHDK/
    ├── MODULES/
    │   └── m10cine.flt      ← built in step 1
    └── SCRIPTS/
        └── M10SHELL.LUA     ← card/CHDK/SCRIPTS/M10SHELL.LUA
```

*(The three `M10HUF*.BIN` files are tuned lossless Huffman tables. Skipping `M10HUF14.BIN` makes 14-bit files ~33% larger and will cause dropped frames.)*

### 3. Launch on the camera

1. Unplug the USB cable and turn the mode dial to **`M`**.
2. Open the CHDK menu → **Miscellaneous Stuff → Enable Lua Native Calls** (`ON`).
3. Open **Scripting Parameters → Load Script from File** → pick **`M10SHELL.LUA`**.
4. Exit the CHDK menu (still in `<ALT>` mode) and press the **Shutter** button to start the shell.
   *(Once you are comfortable with it, you can enable CHDK **Autostart** if you want it to boot straight into the cinema shell — leave it `OFF` while testing.)*

---

## Editing & Grading Your Footage

Takes are saved at the root of the SD card as `M10_0001.MLV` (plus `.M00`, `.M01`, … for long takes — the export tools automatically stitch chunks together).

### Option A — One-command export (`tools/m10export.py`)

Compile the tiny lossless JPEG decoder once:

```sh
mkdir -p /tmp/ljc && cc -O2 -o /tmp/ljc/lj92d tools/lj92d.c
```

Then export directly to **CinemaDNG** (true RAW for DaVinci Resolve's Camera RAW tab) or **ProRes 4444 in ARRI LogC3 / AWG3** (ready for Resolve, Premiere, or Final Cut):

```sh
# True RAW CinemaDNG sequence (DaVinci Resolve)
FPS=24 python3 tools/m10export.py dng    M10_0001.MLV out_dng/

# ProRes 4444 LogC3 (in Resolve: set input Color Space Transform to ARRI LogC3 / AWG3)
FPS=24 python3 tools/m10export.py prores M10_0001.MLV out.mov
```

`m10export.py` automatically detects **10-bit, 12-bit, and 14-bit** takes and all 10 `v186` `ImgMode 1` zero-OB geometries (while keeping backward compatibility with legacy ×5 / Film takes). For **Wide `1:3`** takes it also:
- automatically removes the sensor's autofocus pixel micro-lines (Hybrid CMOS AF II focus pixels),
- writes the `3:1` anamorphic scale tag (`DefaultScale` in DNG / `setsar=3/1` in ProRes) so editors desqueeze it automatically. *(Pass `FPM=0` or `DESQ=1` to disable.)*

### Option B — MLVApp

You can open `.MLV` files directly in [MLVApp](https://mlv.app/):
- For all **`1:1`** modes (`1440 4:3`, `2K 4:3`, `2.2K 3:2`, `2.3K 16:9`, `2.6K 2.4`, `1080 30p`): open and grade directly.
- For **`Wide 1800`** / **`Wide 1440`** takes:
  1. Set **Aspect Ratio / Stretch** to **`3:1`** (or `2.39:1` crop).
  2. Copy [`card/fpm/M10_wide_1728x1800.fpm`](card/fpm/M10_wide_1728x1800.fpm) and [`card/fpm/M10_wide_1728x1440.fpm`](card/fpm/M10_wide_1728x1440.fpm) into MLVApp's focus-pixel map folder (or regenerate with `tools/m10wide_fpm.py`).
     *Why?* The EOS M10 sensor has physical autofocus (PDAF) pixels embedded on 8 exact repeating red/blue positions (`3.33%` of pixels, `0%` of green). Canon's normal photo processor hides them automatically; in Wide `1:3` RAW they appear as faint horizontal micro-lines on bright flat surfaces until the `.fpm` map interpolates them out.

---

## Safety & FAQ

- **Can this brick my camera?** No. Everything runs strictly in RAM. Nothing is written to flash, and no Canon firmware code is included in this repository. Power off the camera (or pull the battery) and it is 100% stock Canon again.
- **Does it record sound?** Not yet — video only for now. Use an external audio recorder and sync in post.
- **Why does the camera occasionally shut down if I experiment with host scripts?** You are still running unofficial code driving hardware DMA on the sensor. A bug during development can trigger a Canon assert and shut down mid-take (losing that take). If it ever shuts down, save `ROMLOG.LOG` from CHDK's Debug menu — it tells you the exact file and line that asserted.
- **Developer USB/PTP safety rules**:
  - Never read hardware MMIO registers (`0xC0xxxxxx`, `0xC0E0xxxx`, `0xD0xxxxxx`) directly over PTP or Lua — it freezes the camera. Always read Canon's RAM shadow copy (`Cam.shadow()` in `tools/m10ptp.py`).
  - Never switch shooting modes over PTP during a host session (`ASSERT OperTrns.c 649`) — use the physical dial.
  - Never upload files over USB while Canon's ×5 magnifier is open (`ASSERT CtrlSrv.c 1035`).

---

## Under the Hood & Developer Docs

Want to understand how we unlocked **`3.3×` faster JpCore encoding (`339 MB/s`)** via `LCLK_HOLD0`, bypassed Canon's 1108-line height wall, pushed **true 14-bit** into `ImgMode 1` with 2-block CH12 DMA, achieved zero-stripe `1:3` horizontal binning, or built a live 14-bit colour preview on a Cortex-R4? Everything is documented in `docs/`:

| Document | Contents |
|---|---|
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Full technical pipeline: `ImgMode 1` (`1:1` & `Wide 1:3`), **`LCLK_HOLD0` / `ClockSave` turbo clock holds**, 2-block CH12 `> 4 MiB` DMA, optical centring (`x0`), Magic Lantern-style HUD, live 10/12/14-bit colour preview, and Hybrid CMOS AF II focus pixel map |
| **[docs/HISTORY.md](docs/HISTORY.md)** | Full R&D log from day 1 through `v186`, including every dead end and breakthrough |
| **[docs/HANDOFF.md](docs/HANDOFF.md)** | Current state (`v186`), open next branches (audio `AUDF`, `XR_MAX`), host dev workflow, and card file reference |
| **[docs/TOOLS.md](docs/TOOLS.md)** | Index of every Python / Lua / C tool and how to run the offline ASan/UBSan test suite (`python3 -B -m unittest discover -s tools -p 'test_*.py'`) |

---

## Credits & License

Built on top of **[CHDK](https://chdk.fandom.com/wiki/CHDK)** (EOS M10 `1.10d` port and `.flt` module loader), with deep inspiration from **[Magic Lantern](https://magiclantern.fm/)** (the `.MLV` container format, `mlv_rec` Size × Bit-Depth UX, DIGIC 6 notes, and `crop_rec`), plus `reyalp`'s DIGIC 6 SD research on the CHDK forum.

Licensed under **GPL v2** (same as CHDK — see [`LICENSE`](LICENSE)).
