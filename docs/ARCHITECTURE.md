# Architecture (`v185b`)

How a RAW frame gets from the Canon EOS M10 sensor to an `.MLV` file — covering both the
**`ImgMode 1` continuous pipeline** (`1440p 1:1`, `Wide 1800`, `Wide 1440` — `v180–v185b`) and
the **×5 magnifier 14-bit pipeline** (`2K DCI` — `v160–v176`).

All firmware addresses below are for **EOS M10 `1.10d`** unless marked `110f`.

---

## Glossary

- **Head**: DIGIC 6 sensor front-end (`0xc0f06xxx` / `0xc0f07xxx`). `0xc0f06804` holds
  `(end_line << 16) | end_col`. In `ImgMode 1` `1440p` it reads `0x05cf0214` (1456 lines, 1920 px);
  in `Wide 1800` it reads `0x073701e0` (1816 lines, 1728 px); in ×5 magnifier it reads `0x045702a6`.
- **TG / DFE**: timing generator and analog front-end, programmed by Canon over SIO channel 4.
  DFE write `8830` marks the end of each sensor readout in ×5 / Film; in `ImgMode 1` (`1440p` / `Wide`)
  we sync on **CMOS register 0** (V-blank start).
- **CMOS registers**: 12-bit sensor registers sent on SIO channel 6 (`(reg << 12) | val`).
- **PACK32**: packs sensor front-end output to 10/12/14 bits onto crossbar port `0x00`.
  Tap `0x10` (`HEAD`, register `0xc0f37014`) delivers unity-gain RAW with no missing codes.
- **EDMAC**: DIGIC 6 DMA engine. Write channels 0–24, read channels 25–47 (`0xfc6d87b8`).
  We capture on write channel 12 (`0xc0f26500`).
- **Shadow**: Canon's RAM mirror of engine registers (`EngDrvOut`), at `*(0x28dbc) + (reg & 0x7ffff)`.
  **Never read `0xC0xxxxxx` / `0xD0xxxxxx` directly over PTP or Lua** (freezes the camera).
- **`ImgMode 1`**: Canon's continuous photo burst / high-res sensor mode (`DrvType 9`,
  `Extract[3]`). Unlike live-view (`727` lines), Film (`1190` lines), or ×5 magnifier (`1108` lines),
  `ImgMode 1` has **no 1108/1190 height wall** and reads arbitrary windows up to `1800+` lines at `24.000 fps`.

---

## High-level pipeline

```text
Sensor (ImgMode 1 or x5)
   │
   ▼
Head (0x10 tap) ──> PACK32 ──> Crossbar 0x00 ──> EDMAC CH12 ──> EXMEM raw ring (5 slots)
                                                                     │
                                            ┌────────────────────────┴───────────────────────┐
                                            ▼                                                ▼
                                Canon JpCore / LosslessEncode                   M10Pv / M10PvS (prio 0x1E)
                                (hardware CR2 LJ92 compressor)                  cached dflush + RGGB LUTs
                                            │                                   -> PV_RGBA (360×240 LCD)
                                            ▼
                                Compressed ring (6–8 slots) ──> M10XR writer ──> A/M10_NNNN.MLV (+ .M00...)
```

### DryOS tasks created by `m10cine.flt`

| Task | Priority | Responsibility |
|---|---|---|
| `M10WB` | `0x18` | Independent `WBInteg` watchdog: keeps Canon's WB statistics task alive across mode switches, 2 GiB file rolls, and end-of-take flushes (`ASSERT WBInteg.c:3491` prevention). |
| `M10Shell` / `M10Cine` | `0x1A` | Shell state machine, frame-sync capture loop (PACK32 + EDMAC CH12), and standby ring capture. |
| `M10LJ` | `0x1B` | Drives Canon's hardware lossless-JPEG encoder (`JpCore`), packages `VIDF` blocks, handles in-camera `HEAD_ERR` slot reuse (`x_he_fix`). |
| `M10XR` | `0x1C` | Streams compressed frames to FAT32 SD card and rolls cleanly to `.M00`, `.M01` at 1900 MiB. |
| `M10Key` | `0x1D` | Key watcher during Standby/REC: REC stop, `MENU` 1 s quit, half-press `4:3/WIDE ↔ 1:1` view toggle, 1 Hz HUD redraw during REC. |
| `M10Pv` / `M10PvS` | `0x1E` | Lowest-priority colour live preview (runs strictly on idle CPU so it can never starve capture or encoding). |

---

## 1. Breaking the height wall: `ImgMode 1` (`1440p 1:1` & `Wide 1:3`)

Live View (`1808×727`), Film (`1808×1190`), and the ×5 magnifier (`2592×1108`) all hit a hard
sensor/LVDS height wall above their stock heights. **`ImgMode 1`** (`DrvType 9`, `Extract` slot 3)
uses Canon's full-sensor readout path and has no such wall.

### How the shell enters `ImgMode 1` (`M10SHELL.LUA` + `m10_cine.c`)

1. **RAM table copies** (`sh_m1_arm_tables()` in `m10_cine.c`):
   Copies `Extract[3]` (`0xfc72f27c`), `TgPixelRes[9]` (`0xfc72fd0c`), `FldSpec[9]`, and `CACHE[1]`
   (`0x575b0 + 36`) into aligned RAM buffers, patching width `W`, head height `HH = H + 16`,
   `X0`, `Y0 = 32`, line clock `LC`, frame length `FL`, and period `PER`, then swaps the RAM
   table pointers atomically through `siohook6`'s `poke32`.
2. **SIO overrides** (`sh_expo_apply()` via `siohook6`):
   - **1:1 `1440p`** (`1920×1440`, `X0=0x34`, `LC=732`, `FL=1819`, `PER=41666 µs`):
     `CMOS[5] = 0x300` (centres vertical readout), `CMOS[7] = 0xae9` (eliminates horizontal step),
     `TG 0x8006 = Gray(732)`, plus live manual ISO (`CMOS[0]`) and shutter (`TG 0x805f/0x8061`).
   - **Wide `1:3`** (`1728×1800` & `1728×1440`, `X0=0x30`, `W=1728`):
     Sets **only `CMOS[2] = 0x742` + `CMOS[5] = 0x020`** — **leaving Still `CMOS[3] = 0x900` untouched**.
     *(Writing `CMOS[3] = 0xf08` alongside `CMOS[2] = 0x742` breaks the sensor's OB/column clamp and
     creates `3.7–4.5 ADU` vertical stripes. Leaving `CMOS[3]` untouched yields `0.03–0.06 ADU` per-channel
     column FPN — 100× cleaner than Film 1×3 — with native black `127.5` and zero `TgWrite`/`DfeWrite`/`PPP` hacks.)*
     For `Wide 1800`, `LC = 640`, `FL = 2080` (`24.001 fps`), `CMOS[7] = 0xac6` (`1949` rows ≤ `2080`).
3. **RAM IPC to Lua** (`siohook6` header `+0x220` req / `+0x224` ack / `+0x280` arg):
   Mode switches (`ChangeMode`) must run from CHDK's kbd/Lua task (calling them from a module task
   asserts). Zero filesystem I/O occurs during normal operation:
   - Stops `ContinuousAF`/`MovieAF` (`0xfc0fa287`) if active (`[0x85b8] ∈ {7, 8}`) — prevents `ASSERT ContinuousAF.c:1354` at +10 s.
   - Calls `MotionVector_Stop` (`0xfc0dc01d`) to free EDMAC channel `0x23` for `JpCore`.
   - Calls `StopMode` (`0xfc1efc0d`) + `ChangeMode(1)` (`0xfc1efb33`).
   - Programs analog CDS clamping (`CdsWritePair` `0xfc414d25`: `c03a..c044 = 0x0247`) → clean black `127.5`, zero stripes.
   - Patches `HivShdManLeo` `[0xfc3c] = (7058 - 2 * HH) / 2` (`2073` for `1440p`, `1713` for `1800p`),
     passed from C via `SH_IPC_ARG_OFF = 0x280` — fixes the 1-in-3 head error caused by `ChangeMode`
     resetting `[0xfc3c]` to `24`.

### `ImgMode 1` profiles (`v185b`)

| Profile | `W × H` | `HH` | `X0` | `LCLK` | `FL` | `PER (µs)` | `CMOS[2/5/7]` | `[0xfc3c]` | `x_lo (µs)` | Raw Frame |
|---|---|---|---|---|---|---|---|---|---|---|
| `1440p 24p 10b` | `1920×1440` | `1456` | `0x34` | `732` | `1819` | `41666` | `— / 0x300 / 0xae9` | `2073` | `35166` | `3.30 MiB` |
| `1440p 24p 12b` | `1920×1440` | `1456` | `0x34` | `732` | `1819` | `41666` | `— / 0x300 / 0xae9` | `2073` | `35166` | `3.96 MiB` |
| `Wide 1800 10b` | `1728×1800` | `1816` | `0x30` | `640` | `2080` | `41665` | `0x742 / 0x020 / 0xac6` | `1713` | `37600` | `3.71 MiB` |
| `Wide 1440 12b` | `1728×1440` | `1456` | `0x30` | `732` | `1819` | `41666` | `0x742 / 0x020 / 0xae9` | `2073` | `35166` | `3.56 MiB` |
| `Wide 1440 10b` | `1728×1440` | `1456` | `0x30` | `732` | `1819` | `41666` | `0x742 / 0x020 / 0xae9` | `2073` | `35166` | `2.97 MiB` |

Every raw frame fits inside a **single `< 4 MiB` EDMAC CH12 transfer**. In `Wide 1800`, active readout
ends at `(32 + 1816) × 641 / 32 = 37,018 µs`, so both Standby and REC arm CH12 at `x_lo = 37,600 µs`
(safely inside V-blank before `hi = 40,465 µs`).

---

## 2. Live Colour Preview (`v184c` / `v185b`)

In `ImgMode 1`, Canon's own YUV display pipeline has broken geometry (showing magenta/green bars).
The module covers the entire `360×240` RGBA overlay (`PV_RGBA`, `0xAARRGGBB`) with an opaque black mask
and renders our own colour preview directly from the captured RAW ring:

- **Compiled hot path**: `PV_HOT = __attribute__((optimize("O2","schedule-insns2")))` built with
  **`-mword-relocations`** (prevents ARM `MOVW/MOVT` reloc 47 errors in CHDK `.flt` files).
- **Pre-shifted u32 LUTs**: `pv_lut_r/g/b[1024]` bake black level (`127`), Rec.709 S-curve, and
  daylight WB (`R×1.75`, `B×1.50`) straight into `0xAARRGGBB` lanes (`px = lr[R] | lg[G] | lb[B]`).
- **Cached reads + selective `dcache_flush_range` (`0xfc1267af`)**: only the sampled row pairs are
  invalidated before reading, yielding `fl_avg = 0–1 ms`.
- **Two dedicated renderers**:
  - `pv_render_m1` (`1:1` `1440p`): `268×200` (`4:3`) or `1:1` centre `536×400` punch-in with green
    focus peaking and zebras.
  - `pv_render_m1_wide` (`Wide 1:3`): `360×124` (`1800p`) or `360×100` (`1440p`) horizontally desqueezed `3×`
    with `2.39:1` cinemascope framing ticks, or `360×200` desqueezed `1:1` centre focus zoom with peaking.
- **Standby (`M10PvS`)**: async 8-slot EXMEM ring (`ns = 8`, ~350 ms wrap margin → `torn = 0`).
- **REC (`M10Pv`)**: reads `xr_prod - 1` under seqlock (`hr = 1` half-res in full frame, `13–22 ms`,
  ~16–21 fps live REC preview; automatically upgrades to full-res `1:1` + peaking on half-press when encoder backlog `< 2`).
- **Overlay wipe sentinel**: checks `PV_RGBA[21 * PV_BW + 358]` (top-right corner of mask, clear of
  the clip-percentage text at `(2, 22)`) and `PV_RGBA[1 * PV_BW + 358]` in full-height Wide `1:1` view.

---

## 3. Hybrid CMOS AF II Focus Pixel Lattice (`Wide 1:3`)

The EOS M10 uses Canon's 18 MP **Hybrid CMOS AF II** sensor with physical half-shielded PDAF
photodiodes embedded on specific red and blue rows (never green). In `Wide 1:3` horizontal binning
(`x0 = 0x30`, `y0 = 32`, `W = 1728`), these land deterministically on **8 exact `(y % 30, x % 8)` sites**
(`3.333%` of pixels, `0%` of Green):

- **Red (`R`)**: `(6, 0)`, `(18, 4)`, `(20, 2)`, `(20, 6)`
- **Blue (`B`)**: `(3, 7)`, `(21, 3)`, `(25, 1)`, `(25, 5)`

Interpolating only these 8 sites from their 4 clean same-channel neighbours (`tools/m10wide_fpm.py` /
`tools/m10export.py` / MLVApp `.fpm` maps in `card/fpm/`) drops `row_hp_std` on flat areas from
`0.440 → 0.146 ADU` (B) and `0.395 → 0.158 ADU` (R), matching the untouched Green shot-noise floor (`0.18 ADU`).

---

## 4. Taking PACK32, Compression & Card Writes

### PACK32 + EDMAC CH12 (per frame)

1. Lock Canon resources `{0x61 (CH12), 0x5f (CH10), 0x84}` (`0xfc373f9e`) and PACK32 sem #6 (`0xfc22f738`).
2. `0xfc22f73e(bpp, 0)`: tap `0x10` (HEAD) in `0xc0f37014`, depth in `0xc0f08094`, pack mode 2, enable `0xc0f08090 = 1`.
3. `ConnectWriteEDmac(12, 0)` (`0xc0f05210`), program CH12 2-D geometry (< 4 MiB per block), start (`ctl = 1`).
4. Wait completion, send `ctl = 2` until `ctl = 0`, restore PACK32 registers **before** releasing sem #6 and resources.

### Hardware Lossless JPEG (`JpCore` / `LosslessEncode`)

- Entry points (`1.10d`): init `0xfc58183e`, CBR `0xfc581828`, setup `0xfc581eec`, start `0xfc582066`, stop `0xfc5820f4`.
- `JpCore` always encodes at precision `14`. For 10-bit and 12-bit takes, RD1 (`0xf0`) reads packed 10b/12b directly
  with unpacker `0xc0f371fc = 0` (left-aligned `<< 4` / `<< 2`, bit-exact).
- Custom 15-symbol Huffman tables (`A/M10HUF.BIN`, `A/M10HUF12.BIN`, `A/M10HUF14.BIN`) cut file size by 25–33%.
- Speed bound: RD1 input bandwidth (~100 MB/s). Measured encode times at `24.000 fps` (`41.67 ms` budget):
  - `1440p 10b`: `~35.2 ms` (~60 MB/s)
  - `Wide 1440 12b`: `~36.6 ms` (~62 MB/s)
  - `Wide 1800 10b`: `~39.7 ms` (~63 MB/s)
  - `2K DCI 14b` (×5): `~39.4 ms` (~53 MB/s)
- **Head-error repair (`x_he_fix = 1`)**: head-error callback `[0xfa80]` is replaced by a counting stub; any hit
  frame reuses the previous healthy compressed slot with zero copy while `M10XR` patches MLV frame number and µs timestamp.
- **Card writes**: SD controller runs at Canon's max clock (speed 8, div 1 → ~73–80 MB/s). Logs are buffered in RAM
  (`SLOG_BUF = 8192`) during takes; MLV chunks roll cleanly at `1900 MiB` (`drops_at_roll = 0`).

---

## Key `1.10d` Firmware Addresses

| Address (`1.10d`) | Role |
|---|---|
| `0x9b50` | SIO send pointer (Canon `0x121`) — `siohook6` installed here (`+0x220` req, `+0x224` ack, `+0x280` arg) |
| `0xfa80` / `0xfa84` | Head-error callback pointer (Canon `0xfc1ee9a9`) & counter |
| `0x28dbc` | Engine register shadow base (`shadow = *(0x28dbc) + (reg & 0x7ffff)`) |
| `0x2cd24` | `Extract` pointer table (`slot 3` = `ImgMode 1`, ROM `0xfc72f27c`) |
| `0x2cdc0` | `TgPixelRes` pointer table (`DrvType 9` = `ImgMode 1`, `41` = Film, `46` = ×5); `FldSpec` at `+0xe4` |
| `0x575b0` | `ImgSens` mode cache (`36 B/mode`); current mode at `[0x865c]`, TG state at `[0xe664]` |
| `0xfc3c` | `HivShdManLeo` vertical height offset (`7058 - 2 * [0xfc3c]`) |
| `0x85b8` | ContinuousAF / MovieAF state (`7`/`8` stopped via `0xfc0fa287` before `ImgMode 1`) |
| `0xfc0dc01d` / `0xfc0dbfc9` | `MotionVector_Stop` / `MotionVector_Start` (frees EDMAC `0x23`) |
| `0xfc414d25` | `CdsWritePair` (analog CDS clamping `c03a..c044 = 0x0247`) |
| `0xfc1fb48d` / `0xfc1fb425` / `0xfc1fb4dd` | `LockMainPower` / `UnlockMainPower` / `SetAutoShutdownTime` |
| `0xfc1267af` / `0xfc1267cb` | `dcache_flush_range` / `dcache_clean_range` |
| `0x56bec + 8` | `physw_status[2]` (bit 28 = USB VBUS power) |
