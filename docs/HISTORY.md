# History

Two weeks of work (31 October to 13 November 2026), compressed. Session tags (`probeNN`,
`liveNN`) match the file names in the private capture archive and the version notes at the
top of `module/m10_cine.c`. The dead ends are here on purpose: most of them took a day.

## 1. Getting CHDK running and finding the RAW (probe1-probe24)

- The camera is a 1.10d (MakerNote tag `0x001e` = `0x01100400`). The ROM studied in Ghidra
  is 1.10f; most addresses match, not all.
- A card of 64 GB or more formatted exFAT by the camera won't autoboot `DISKBOOT.BIN`.
  Reformat FAT32 (MBR).
- The first live-view captures looked like Bayer data and weren't. Every crossbar port that
  carries the live view is UYVY 4:2:2. A port scan of `0x00-0x7f` found one linear source
  (port `0x36`), and it turned out to be two colour planes (G | R) side by side, never blue.
- The real RAW comes from PACK32 on crossbar port `0x00`, which is only active while PACK32
  is switched on, following the order in Canon's `CaptureSystem.c`. In the ×5 magnifier this gave
  full RGGB at 2592 px per line (probe24), and the first DNG rendered a colour chart correctly.

## 2. From one frame to a stream (probe25-probe52)

- Early runs shut the camera down. Rules came out of it: a capture longer than one frame
  leaves the DMA armed; each EDMAC block must be under 4 MiB; re-arming needs full
  reprogramming; 4-byte transfers are needed for the mosaic; only CH12 under Canon's resource
  lock is safe in the magnifier.
- probe37: one 2-D transfer (two blocks of ~554 lines) copies a full 5.7 MB frame.
- probe38-39: the first C module, `m10cine.flt`. Running in the CHDK menu task killed the
  camera; a dedicated task survived 642 frames.
- probe40: PACK32 outputs 10 and 12 bits natively, keeping the high bits.
- probe43-46: Canon's CR2 lossless encoder (`LosslessEncode.c` / `JpCore.c`) works from the
  module. With PACK32 pack mode 2 the output decodes bit-exact with `tools/lj92d.c`.
- probe48-52: three tasks (capture, encode, write). 240/240 frames of 2592 × 924 14-bit
  lossless at 24 fps (probe52). That was in the magnifier, with no frame sync yet.

## 3. Full field of view in Film mode (probe53-live107)

The magnifier is a crop. The goal moved to the full sensor width in Film mode.

- Normal live view delivered data in bursts and shut the camera down at the end of passes
  (`ShutdownReason 9 / ErrorNo 16`: ImgSens restarting the sensor and getting no TG answer).
  The module was releasing PACK32 before restoring its registers. Fixed, but the shutdowns
  kept coming.
- live63: an SIO hook on `*(0x9b50)` logs every sensor and TG write. This is the tool most later
  work relies on.
- live65: TG `0x800c` = 0 during Canon's Film commit makes the sensor read every line: the
  Magic Lantern "1×3" mode (full width, columns binned by 3, no line skipping).
- live80: CMOS register 7 moves the vertical readout window. live100: leaving it at Canon's
  `0x800` with all lines read superimposes a second sensor region (the "ghost" and the magenta
  cast). `0x280` fixes it.
- live84: syncing CH12 on the DFE `8830` write gave 20 clean consecutive frames.
- live86-93: series still died at random, 1-3 % per frame. Holding PACK32 across frames, other
  write channels, Canon's own capture service (`EvfCaptureSystem`) and memory-bandwidth tests
  all failed the same way. Canon's own service fails too when chained, so it is a platform limit
  under FHD readout, not our code.
- live92: a regression hid for days. Diagnostic code copying 3 KiB of registers at each DMA
  start was the cause. Lesson: re-run a control after changing instrumentation.
- live94: Magic Lantern never runs its own RAW DMA on DIGIC 6/7/8. It asks Canon (`lv_save_raw`),
  which the M10 ROM doesn't have.
- live95: the fatal error is a head error (IRQ `HEAD_ERR`, status `0x40`).
- live97: replacing the head-error callback with a counting stub. One error no longer kills
  the camera: 214 frames, then 300/300 in manual focus (live98). Continuous AF caused most of
  the errors.
- live100-101: two more shutdown causes handled from the module. WBInteg waits for statistics
  that never come after some errors (`ASSERT WBInteg.c 3491`): the module sets the event flag
  itself. TgCtrl state is left at −1 by an ImgSens stop: the module resets it. 0 shutdowns over
  55 takes.
- live102: the grain was 3-4 stops of underexposure, not noise. AF pixels show as a 12-cells-per-
  10 × 8 grid after the first head error; fixed in post (`fix_af`).
- live103-107: trying to read more than 1190 lines. A coherent commit with a taller head passes
  (worked out by emulating Canon's commit in unicorn, `tools/rom/emu_commit.py`), but the sensor
  stream freezes after line 1190 whatever CMOS, TG or DFE registers say. The magnifier hits the
  same wall at 1108. Still open.

## 4. Film 3×3 at 25 fps (live108-live114b)

- live108: Canon's normal Film mode (`800c = 2`) already reads the whole 3:2 sensor one line in
  three: 1728 × 1156 active, square pixels, no hacks needed.
- live109: 25 fps capture holds without card writes (600/600). With card writes and the encoder,
  head errors come back. The encoder takes ~30 ms for a full frame and there are only ~21 ms
  between readouts. JpCore refuses any precision but 14; the reader accepts 10-bit input
  directly, which removed a 200 ms CPU conversion. Custom Huffman tables: 1.95 MB per frame.
- No Canon mode reads a sensor line faster than 16.25 µs. Changing the line time alone shuts
  the camera down.
- live110: clearing LvMovOptimus bit 3 (`MOVOFF=8`) stops Canon reprogramming its 1080p YUV
  channel each frame, which removes ~11.5 MB of DRAM traffic per frame. Combined with starting
  the encoder right at the end of our DMA and waiting up to 8 ms for the previous encode:
  595/600 frames to the card.
- live111: on a cool camera, 600/600 at 24.9 fps, 0 head errors, twice.
- live112: keeping frames that had a head error (v148) instead of pausing 150 ms. The kept frame
  loses ~230 rows and later frames shift by 12 px once; the reader repairs both.
- live112b-113: the remaining drops came every 640 ms exactly. A 1 ms DryOS task sampler (v153)
  pointed at `WBCtrl`: every 6th 100 ms cycle requests white-balance statistics, whose EDMAC
  writes starve CH12. The cycle is set by a RAM threshold (`0x133c88`); raising it from 5 to 50
  removed those drops.
- live114b: the last 120 ms gaps were our own log. One `open/write/close` on the card from the
  capture task cost two frames. Buffered in RAM: 1500/1500 frames at 24.97 fps.

## 5. Back to the magnifier, for image quality (live115-live122)

- live115: the 3×3 minute looked bad. Line skipping makes moiré, and after the first head error
  Canon applies a digital gain that clips at 948 and leaves gaps in the code values (banding).
  Decision: modes with no line skipping only, so the ×5 magnifier at 1:1.
- The magnifier runs at 30 fps and the encoder needs 33.6 ms for 2592 × 1080: too slow.
- live116: slowed to 25 fps by copying Canon's TgPixelRes record to RAM with a longer frame and
  letting Canon program it at magnifier entry. No register written by hand.
- live117: 1500/1500 frames of 2592 × 1104 at 24.98 fps, 0 drops, 0 head errors, ~73 MB/s to the
  card. In the magnifier, encoder plus capture fit in the frame, and Canon's background load is
  much lighter than in Film. Height: +32 lines still hits the wall at 25 fps.
- live118: stand-alone shell (v160-v161). The module installs its hooks itself and takes the
  REC key away from Canon with its own GUI handler. No computer needed.
- live119: drops on detailed scenes are the SD interface. Canon already runs it at the fastest
  divider. Crop to 2400, then 2304 wide (v162-v163). The shell exits cleanly when USB is
  plugged in (autostart plus USB used to shut the camera down).
- live120-121: trying to make the LCD show the whole recorded frame. The magnifier window size
  is an immediate constant in ROM code with no RAM hook on its path. Closed.
- v164-v166: an on-screen thumbnail built from our own RAW instead.
- live122: export tools for editing apps (`tools/m10export.py`: CinemaDNG, or ProRes 4444
  LogC3 / ARRI Wide Gamut 3).

## 6. True 14-bit in the magnifier (v167-v176, 2026-11-14 to 11-17)

- v167: 24p profiles (24.000 fps by lengthening the TgPixelRes copy), RAW zebras, tail drain at
  stop, split MLV headers.
- r125-r126: the pre-processor tap selects what PACK32 sends. `0x12` (DEFOE, used so far) and
  `0x22` (PREFIFO) carry a digital gain with missing codes; `0x10` (HEAD) gives unity 14-bit data.
  Canon's encoder already crops a 14-bit source natively, so a 1920- or 2048-wide crop keeps its
  input under 4 MiB (two CH12 blocks). First continuous 14-bit take: 1920 × 1104, 25p, 100/100.
- v171: a 14-bit Huffman table (`M10HUF14.BIN`) instead of the 10-bit one: −25 % per frame
  (the 10-bit table produced long codes and `0xff 0x00` stuffing). Black 2048 in RAWI.
- r127-r128: `0x10` HEAD at 24.000p: 150/150 frames at 1920 and at 2048 wide, 0 drops,
  ~2.2 MB per frame, encoder 39.4 ms of the 41.7 ms frame.
- v172-v173: in-camera head-error repair. A frame hit by a head error is replaced by the previous
  frame's payload with no copy (logical→physical slot map); only the writer patches the MLV frame
  number and timestamp. Validated on 4 × 150 frames 2048 × 1104 14-bit, 0 drops.
- v174-v176: shell UI rebuilt: HUD with timer, card minutes and battery, manual ISO / Tv /
  aperture, 14-bit profiles first (`24p 2K 14b` default), HUD redrawn during REC, exit by holding
  MENU 1 s (gives the keys back to Canon).
- r135-r136: the `0x10` tap in Film 1×3 still gives short frames with a head error per pass.
  14-bit stays a magnifier feature for now.
