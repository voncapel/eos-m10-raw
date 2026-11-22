# History

The complete R&D story of EOS M10 RAW video (31 October to 22 November 2026), including the dead
ends so nobody has to rediscover them. Session tags (`probeNN`, `liveNN`, `rNNN`) match the notes
at the top of `module/m10_cine.c`.

---

## 1. Getting CHDK running and finding the RAW (`probe1–probe24`)

- The camera is an EOS M10 `1.10d` (MakerNote `0x001e = 0x01100400`). Cards ≥ 64 GB formatted exFAT
  won't autoboot `DISKBOOT.BIN`; FAT32/MBR is required.
- Live-view crossbar ports carry UYVY 4:2:2 (and port `0x36` only G|R). True RGGB RAW comes from
  `PACK32` on crossbar port `0x00`, activated following Canon's `CaptureSystem.c` sequence.
- In the ×5 magnifier (`2592 × 1108`, 1:1 readout), `probe24` produced the first accurate colour-chart DNG.

## 2. From one frame to a 3-task stream (`probe25–probe52`)

- Learned hardware DMA rules: each EDMAC block `< 4 MiB`, 4-byte transfers for full RGGB, full
  reprogramming per frame, explicit `ctl = 2` stop, restore PACK32 before releasing sem #6, run in a
  dedicated DryOS task (not CHDK menu task).
- `probe43–46`: Canon's hardware CR2 lossless JPEG encoder (`LosslessEncode.c` / `JpCore.c`) works
  from our module with PACK32 pack mode 2 and decodes bit-exact with `tools/lj92d.c`.
- `probe48–52`: 3-task pipeline (capture, encode, write) hit 240/240 frames in ×5 magnifier.

## 3. Full field of view in Film mode (`probe53–live114b`)

- `live63`: built the SIO send hook on `*(0x9b50)` (`siohook`) to log and override TG/DFE/CMOS writes.
- `live65–107`: Film `1×3` (`TG 0x800c = 0`, `CMOS[7]` vertical window) and `3×3` (`1808×1190`).
  Solved `HEAD_ERR` shutdowns (`[0xfa80]` counting stub), `WBInteg.c:3491` asserts, `WBCtrl` 640 ms
  stalls (`0x133c88 = 50`), `LvMovOptimus` DRAM contention (`MOVOFF=8`), and RAM-buffered logs →
  `1500/1500` frames at `24.97 fps`.
- **Wall discovered (`live103–107`)**: neither Film (`1190`) nor ×5 (`1108`) allows taller frames;
  above those heights the sensor stream freezes or head-errors continuously.
- **Quality verdict (`live115`)**: Film `3×3` line-skipping had bad moiré and digital gain banding.

## 4. ×5 Magnifier at 25p/24p & true 14-bit (`live116–v176`)

- `live116–119`: copied `TgPixelRes[46]` to RAM to slow the ×5 magnifier from 30 fps to 25p/24p without
  poking live registers; built the first standalone shell (`v160–v167`) and `m10export.py` (CinemaDNG + ProRes 4444 LogC3).
- `r125–r128` (`v170–v176`): discovered the `0x10` (`HEAD`) unity-gain 14-bit tap (no missing codes),
  tuned `M10HUF14.BIN` (−25% size), added zero-copy in-camera head-error replacement (`v173`), and
  rebuilt the HUD with live ISO / Tv / Aperture (`2K DCI 2048×1076 14-bit @ 24.000p`, 0 drops).

## 5. Film `1×3` 12-bit (`r135–r147`, `v177–v178e`)

- Stretched Film's `TgPixelRes[41]` line clock to `640` (`2000` lines @ 25p) so full-width `1×3`
  12-bit RAW (`M10HUF12.BIN`, `CMOS[7] = 0x140`) fit the encoder (`120/120` frames). However, slow-line
  Film `1×3` still suffered from `5.9 ADU` periodic column stripes requiring heavy host repair (`m10x3fix.py`).

## 6. Breaking the height wall: `ImgMode 1` `1440p` (`r150–r159`, `v180–v181c`)

- Audited Canon's Still/Capture path (`r150–r155`, `DrvType 9`, `Extract[3]`) and proved that
  **`ImgMode 1`** runs continuously without the 1108/1190 height limit!
- `r156–r159` solved every remaining piece for clean `1920×1440` `1:1` @ `24.000 fps`:
  - `CMOS[5] = 0x300` + `CMOS[7] = 0xae9` centred the sensor window and removed the horizontal step.
  - `CdsWritePair` (`0xfc414d25`) setting `c03a..c044 = 0x0247` restored clean OB `127.5` with zero stripes.
  - Syncing CH12 on `CMOS[0]` (V-blank) instead of DFE `8830` locked frames with `< 100 µs` jitter.
  - Patching `HivShdManLeo` `[0xfc3c] = 2073` eliminated the mysterious 1-in-3 head error.
  - `MotionVector_Stop` freed EDMAC `0x23` for `JpCore`.

## 7. Standalone `1440p` shell, live colour preview & focus peaking (`v182–v184c`, 22 Nov 2026)

- **`v182`**: unified standalone shell (`m10cine.flt` + `M10SHELL.LUA`) with RAM-only IPC (`siohook6 +0x220/+0x224`,
  zero SD polling during REC), `ContinuousAF` stop (`0xfc0fa287`, fixing the +10 s `ContinuousAF.c:1354` crash),
  independent `M10WB` watchdog (`prio 0x18`), `LockMainPower`, opaque `360×240` RGBA overlay mask, and
  validated 2 GiB file rolling (`1261` continuous frames, `drops=0`, `drops_at_roll=0`).
- **`v183–v183d`**: added real-time green focus peaking, pre-roll 2 frames (eliminating the start-of-take gap),
  true sensor-period `mlv_fps1000`, and tested Canon Hybrid AF dip + STM motor (`EFLensCom.MoveFocus` proved
  relative-pulse in Photo M and silent no-op in `ImgMode 1`; PDAF continuous AF ruled `NO-GO` in `1:1` binning).
- **`v184a–v184c`**: pivoted to **manual focus + fast live preview**:
  - Compiled hot preview path with `PV_HOT` (`-O2 -fschedule-insns2` + **`-mword-relocations`**), pre-shifted
    u32 Rec.709/WB LUTs, and 44-instruction inner loop.
  - Async 8-slot Standby preview (`M10PvS`, `torn=0`) + continuous **~16 fps live REC preview** (`M10Pv`,
    `ren_avg = 20–22 ms`, `0` drops over 2006 frames).
  - Half-press shutter = instant **`4:3 ↔ 1:1` focus punch-in** in both Standby and REC.
  - Hardened stability: `SetAutoShutdownTime(0)`, `ReEVF`/`[0xfc3c]` guard, and `WBInteg` keepalive on `MENU` exit.

## 8. Full-width APS-C **Wide `1:3`** inside `ImgMode 1` (`r160`, `v185–v185b`, 22 Nov 2026)

- **Hardware breakthrough (`r160`)**: discovered that the `3.7–4.5 ADU` vertical stripes in earlier `1:3`
  attempts came solely from writing **`CMOS[3] = 0xf08`** alongside `CMOS[2] = 0x742`. Writing **only
  `CMOS[2] = 0x742` + `CMOS[5] = 0x020`** inside `ImgMode 1` (keeping Still `CMOS[3] = 0x900`, `x0 = 0x30`,
  `W = 1728`, `CDS = 0x0247`) produces **100% APS-C horizontal FOV with `0.03–0.06 ADU` column FPN** —
  100× cleaner than Film `1×3`, with zero vertical stripes!
- **`v185`**: integrated **`Wide 1800 10b`** (`1728×1800`, `lclk = 640`, `fl = 2080`, `2.88:1` native /
  `2.39:1` = 83% APS-C), **`Wide 1440 12b`** (true continuous 12-bit 24p!), and **`Wide 1440 10b`** right
  behind `1440p` (default), with dynamic `[0xfc3c]` IPC (`+0x280`) and a dedicated live `3×` desqueezed
  preview (`pv_render_m1_wide`) with `2.39:1` guides and desqueezed `1:1` focus zoom.
  - First real-world take (`M10_0044.MLV`): **542 frames `Wide 1800 10b` @ `24.000 fps`, `drops=0`, `he_n=0`, `LJ err=0`, `rec preview n=481 ren_avg=13 ms` (~21 fps live REC preview!)**.
- **`v185b`**: fixed three field bugs from the first `v185` test:
  1. Applied `x_lo = 37600` and `x_need = pr->h - 4` in **Standby** as well as REC (`Wide 1800` readout ends at `37,018 µs`).
  2. Moved the overlay wipe sentinel from `(2, 30)` (which collided with the yellow `%` clip text at `(2, 22)`) to `(358, 21)` / `(358, 1)` and cleared `pv_has_img` on geometry switches.
  3. Wrapped `sh_m1_leave()` on `ImgMode 1 → non-ImgMode 1` profile switches with `wb_wd_force` (`WBInteg.c:3491`).
  4. Mapped the remaining subtle horizontal lines on bright flat areas to the exact **8-site `(y % 30, x % 8)` Hybrid CMOS AF II focus pixel lattice** (`3.33%` R/B, `0%` Green) and added `tools/m10wide_fpm.py` + MLVApp `.fpm` maps + automatic cleanup/desqueeze in `tools/m10export.py`.
