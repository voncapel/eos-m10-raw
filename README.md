# EOS M10 RAW Video

Turn a **Canon EOS M10** (firmware `1.10d`) into a **standalone cinema RAW camera** — recording lossless 10-bit, 12-bit, and 14-bit `.MLV` video directly to the SD card with live colour preview, focus peaking, zebras, and full manual exposure controls.

**No computer is needed to shoot**, and **nothing is ever flashed to the camera** (everything runs in RAM via a CHDK module and disappears completely when you turn the camera off).

[![Canon EOS M10 - RAW video test](https://img.youtube.com/vi/bDyuFj6pS3c/hqdefault.jpg)](https://www.youtube.com/watch?v=bDyuFj6pS3c)

> **Status (`v185b`)**: One-person open-source R&D project on one camera (`1.10d` only). Continuous multi-minute takes work reliably on fast SD cards, with **zero line-skipping** and **zero dropped frames** in tested modes. Read [Safety](#safety--faq) before putting it on a card.

---

## What It Can Shoot

Pick your format directly on the camera (`◄ / ►` on the **Profile** field). All modes record lossless-compressed RAW (Canon's own hardware lossless JPEG encoder, wrapped in Magic Lantern `.MLV` files).

| Profile | Captured Sensor Area | Effective Aspect / FOV | Bit Depth & FPS | Live Preview | Best For |
|---|---|---|---|---|---|
| **`1440p 24p 10b`** *(default)* | `1920 × 1440` (`1:1` crop) | `4:3` — crisp 1:1 pixels, no binning | 10-bit · `24.00p` | Colour + peaking + `1:1` zoom | Everyday sharp cinema look, long takes |
| **`1440p 24p 12b`** | `1920 × 1440` (`1:1` crop) | `4:3` — crisp 1:1 pixels, no binning | 12-bit · `24.00p` | Colour + peaking + `1:1` zoom | Extra grading latitude in `4:3` |
| **`Wide 1800 10b`** | `1728 × 1800` (`1:3` horiz. binning) | **100% APS-C width** · `2.88:1` native / `2.39:1` scope *(desqueezed `5184×1800`)* | 10-bit · `24.00p` | **Live `3×` desqueezed** + `2.39:1` guides + `1:1` zoom | **Full-width cinema widescreen** with no crop |
| **`Wide 1440 12b`** | `1728 × 1440` (`1:3` horiz. binning) | **100% APS-C width** *(desqueezed `5184×1440`)* | **True 12-bit** · `24.00p` | **Live `3×` desqueezed** + `2.39:1` guides + `1:1` zoom | **Full-width 12-bit RAW** |
| **`Wide 1440 10b`** | `1728 × 1440` (`1:3` horiz. binning) | **100% APS-C width** *(desqueezed `5184×1440`)* | 10-bit · `24.00p` | **Live `3×` desqueezed** + `2.39:1` guides + `1:1` zoom | Full-width with lower SD bitrate |
| **`24p 2K 14b`** *(×5 loupe)* | `2048 × 1076` (`1:1` crop) | `1.90:1` 2K DCI (×5 magnifier) | **True 14-bit** · `24.00p` | B&W thumbnail + zebras | Maximum 14-bit dynamic range |
| **`24p 1920 14b`** *(×5 loupe)* | `1920 × 1076` (`1:1` crop) | `16:9` (×5 magnifier) | **True 14-bit** · `24.00p` | B&W thumbnail + zebras | Safer 14-bit margin |

*(Legacy `25p` / `10-bit` ×5 magnifier profiles and `Film 1×3` are also kept further down the profile list.)*

### What does "Wide `1:3` desqueezed" mean?

Think of it like shooting with a **3× anamorphic lens** — except done inside the sensor itself. To capture **100% of the APS-C width** at 24 fps with **zero vertical line-skipping** (no moiré, no stair-stepping), the sensor merges 3 horizontal pixels into 1 (`5184 → 1728` wide) while reading every single vertical line (`1440` or `1800` tall).

- **On the camera screen**, the shell stretches the preview `3×` live so framing looks completely normal, with subtle `2.39:1` cinemascope guide marks.
- **In post**, `tools/m10export.py` (or MLVApp) stretches the width back `3×` automatically — giving you true full-width APS-C widescreen with tall vertical resolution.

---

## Shooting On-Camera (Controls Cheat Sheet)

Once launched, the shell takes over the screen with a clean cinema HUD:
- **Top bar**: `REC` dot + timer, active profile, remaining recording minutes on the card, battery meter.
- **Bottom bar**: `ISO` · `Shutter` · `Aperture` · `Profile` · `Zebras / Focus Peaking` · `View` (`4:3` / `WIDE` / `1:1` / `OFF`).

| Control | Action |
|---|---|
| **Mode dial → `M`** | Required for `1440p` and `Wide` modes (Photo Manual mode) |
| **▲ / ▼** | Select a setting on the bottom bar |
| **◄ / ►** | Change the selected value (including switching live between `1440p`, `Wide 1800`, and `Wide 1440`) |
| **Half-press shutter** | **Instant `1:1` focus zoom with green Focus Peaking** — works in Standby **and** while recording! |
| **REC** *(or **SET**)* | Start / stop recording (`M10_0001.MLV`, auto-splits into 2 GB chunks for continuous takes) |
| **Hold MENU (1 s)** *(or **MENU + SET**)* | Exit the shell cleanly and return all buttons to Canon |
| **Plug in USB cable** | Automatically stops and exits the shell so you can copy files to your computer |

---

## 5-Minute Setup

### Requirements

- **Canon EOS M10** running firmware **`1.10d`** *(other firmware versions will not work — addresses are specific to `1.10d`)*.
- **Fast FAT32 SD card** (UHS-I V30/V60/V90 capable of ~65–75 MB/s sustained write; cards ≥ 64 GB must be formatted FAT32/MBR for CHDK autoboot).
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
├── M10HUF14.BIN             ← card/M10HUF14.BIN    (14-bit compression table)
└── CHDK/
    ├── MODULES/
    │   └── m10cine.flt      ← built in step 1
    └── SCRIPTS/
        └── M10SHELL.LUA     ← card/CHDK/SCRIPTS/M10SHELL.LUA
```

*(The three `M10HUF*.BIN` files are tuned lossless Huffman tables. Skipping them makes files ~25% larger and can cause dropped frames on high-bitrate profiles.)*

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

`m10export.py` automatically detects **10-bit, 12-bit, and 14-bit** takes, crops optical black only on modes that have it, and for **Wide `1:3`** takes:
- automatically removes the sensor's autofocus pixel micro-lines (Hybrid CMOS AF II focus pixels),
- writes the `3:1` anamorphic scale tag (`DefaultScale` in DNG / `setsar=3/1` in ProRes) so editors desqueeze it automatically. *(Pass `FPM=0` or `DESQ=1` to disable.)*

### Option B — MLVApp

You can open `.MLV` files directly in [MLVApp](https://mlv.app/):
- For **`1440p`** and **`2K 14b`** takes: open and grade directly.
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

Want to understand how we bypassed Canon's 1108-line height wall, drove `ImgMode 1` continuously at 24.000 fps, achieved zero-stripe `1:3` horizontal binning, or built a 16 fps live colour preview on a Cortex-R4? Everything is documented in `docs/`:

| Document | Contents |
|---|---|
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Full technical pipeline: `ImgMode 1` (`1440p` & `Wide 1:3`), PACK32/EDMAC CH12, JpCore lossless encoder, RAM IPC (`siohook6`), `M10WB` watchdog, live preview renderer, and Hybrid CMOS AF II focus pixel map |
| **[docs/HISTORY.md](docs/HISTORY.md)** | Full R&D log from day 1 through `v185b`, including every dead end and breakthrough |
| **[docs/HANDOFF.md](docs/HANDOFF.md)** | Current state (`v185b`), open next branches (audio `AUDF`, Wide tuning), host dev workflow, and card file reference |
| **[docs/TOOLS.md](docs/TOOLS.md)** | Index of every Python / Lua / C tool and how to run the offline test suite (`python3 -B -m unittest discover -s tools -p 'test_*.py'`) |

---

## Credits & License

Built on top of **[CHDK](https://chdk.fandom.com/wiki/CHDK)** (EOS M10 `1.10d` port and `.flt` module loader), with deep inspiration from **[Magic Lantern](https://magiclantern.fm/)** (the `.MLV` container format, DIGIC 6 notes, and `crop_rec`), plus `reyalp`'s DIGIC 6 SD research on the CHDK forum.

Licensed under **GPL v2** (same as CHDK — see [`LICENSE`](LICENSE)).
