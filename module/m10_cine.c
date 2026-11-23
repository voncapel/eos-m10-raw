/*
 * v185b (2026-11-22): Wide 1800 Standby + REC both arm at x_lo 37600 (V-blank after the 37018 us readout), Standby
 *   x_need = h - 4; overlay sentinel moved from (30, 2) (overwritten by the yellow clip % -> mask/HUD/refresh storm)
 *   to the mask corner (21, 358), Wide focus view: top HUD bar (1, 358); one pv_m1_mask(0) per M10PvS pass;
 *   sh_m1_enter clears pv_has_img (full wipe after enter / geometry switch); 1440p -> non-1440p profile switch
 *   under wb_wd_force + 400 ms settle (WBInteg.c:3491 assert).
 * v185 (2026-11-22): ImgMode 1 profiles Wide 1800 10b (1728x1800, LCLK 640, FL 2080) and Wide 1440 12b/10b
 *   (1728x1440, X0 0x30): sh_prof_t h/lclk/m1_wide, parameterized Extract/TgPixelRes/FldSpec/cache, wide CMOS 2/5/7
 *   overrides, [0xfc3c] value handed to M10SHELL.LUA via siohook6 +0x280, geometry change -> full ImgMode 1 re-enter.
 * v184c (2026-11-22): stability + standby speed. sh_pwr_lock(1) also calls SetAutoShutdownTime(0) (0xfc1fb4dd:
 *   Canon Display-Off / idle timer cannot fire in long standby); key=5 diagnostic slog (0x865c, 0xe664, DSS_FLAGS,
 *   mode_rec); SH_IPC_REC under wb_wd_force + M1_OFF first if 0x865c is still 1; pre-take [0xfc3c] != 2073 (Canon
 *   ReEVF ran, MotionVector awake) -> log + full sh_m1_enter() instead of a blind poke; exit: wb_wd_force around
 *   sh_m1_leave + 400 ms settle (WBInteg.c:3491 assert on MENU exit), MENU release wait (<= 3 s) before exit_alt
 *   (no PressMenuButton leak). pv_render_m1: dedicated 10-bit full-res rows (fast: no peak / st == 2 state;
 *   peak: own loop), p1 = p0 + 1200, branchless clip test, n counted per row (bit-identical to v184b).
 * v184b (2026-11-22): pv_render_m1 fast path: PV_HOT back to O2 (module built with -mword-relocations), pre-shifted
 *   u32 LUTs (px = lr[R] | lg[G] | lb[B], subtle cinema S-curve baked in), no 2-quad average / saturation pass,
 *   per-column word / shift tables, one inner loop per bit depth (no bpp test per pixel); standby ring up to 8 EXMEM
 *   slots (torn 297 -> 0), dflush timed apart (fl_avg), M10PvS msleep(5) per frame; REC 4:3 always 134 x 100,
 *   1:1 punch-in full res + peaking while the encoder keeps up, 30 ms pace.
 * v184a (2026-11-22): ImgMode 1 preview: fixed REC-view R/G/B LUTs + saturation x1.35, 4:3 2-quad average,
 *   output-grid peaking (no unpack), sampled-row dflush; REC preview renders the newest captured frame (no 1 s
 *   wait, 40 ms pace, half res on encoder lag); standby async render task M10PvS on a 3-slot capture ring;
 *   half-press toggles 4:3 <-> 1:1 in standby and REC (Canon AF dip removed).
 * v183d (2026-11-22): pv_render_m1 precomputes col_x[] (53,600 __aeabi_uidiv out of the inner loop) and builds each
 *   row in a cached row_px[] flushed to uncached PV_RGBA by burst memcpy (ren=150 ms); M10SHELL do_af waits for
 *   Canon idle Photo M (ImgSens 3, TG 3, !shooting) after the half-press release (M1_ON mid-CancelPre ->
 *   WBInteg.c:2197 ASSERT).
 * v183c (2026-11-22): WB watchdog keepalive across the half-press AF dip (wb_wd_force + wb_kick_now: ROMLOG
 *   WBInteg.c:3491 ASSERT power-off when 0x865c 1 -> 3 stopped M10WB during PressSwOne); standby preview flushes
 *   only the sampled rows (1:1 281 KB, 4:3 960 KB instead of 3.45 MB), sleep 15 -> 5 ms, frame-1 ms breakdown log.
 * v183b (2026-11-22): x_pbl 220 -> 350 (13 v62 dfe_miss on take 32); instant half-press AF latch (sh_af_req, keywatch);
 *   standby 1440p preview from the CACHED frame (FN_DFLUSH invalidate, was 0x40000000 uncached: ~380 ms/frame),
 *   fused 2-sample reads, 4:3 peaking on a true 2-photosite gradient (c-2 / c+2), mean EMA, HUD 1/8, sleep 15 ms.
 * v183 (2026-11-22): x_pbl 560 -> 220 (SH_RECIPE_M1 field 55); focus peaking in pv_render_m1 (pv_peak, HUD Z+P/PK/ZEB/---);
 *   one-shot Canon hybrid AF dip (half-press in the 1440p preview -> SH_IPC_AF 5, then re-arm ImgMode 1);
 *   24.00p cadence: 2 pre-roll captures, VIDF timestamps = (k + drops before k) * x_per (64-bit), mlv_fps1000 from
 *   slots; early-drop fixes: WB readout kick held for fr 0..7 (<= 1 s) and while the encoder is >= 2 behind (<= 900 ms),
 *   REC preview starts 1 s in, every 500 ms, only with no encoder backlog and no ring drop in the last 500 ms.
 * v182 (2026-11-22, work/v182_audit_spec.md): unified stand-alone 1440p shell.
 *   A.5: independent WB watchdog task M10WB (prio 0x18): kicks WBIntegTask when WB_S+0x5c is stale (> 1.2 s in REC,
 *        > 0.6 s idle) in ImgMode 1; wb_kick_due() also on the ring-full drop path; deferred log kept through the
 *        whole REC report (SLOG_BUF 8192, one flush); heartbeat skipped in the shell; xr_roll time/count; TLF/CAP
 *        rings circular (TLF2 when wrapped); mlv_finalize without stdio; 12b LL unpacker reset; LockMainPower held
 *        while the shell runs; M10Shell/M10Cine/M10XR stacks 0x2000.
 *   C: profile kind (0 x5, 1 Film 1x3, 2 ImgMode 1 1440p, default); SH_RECIPE_M1; ImgMode 1 RAM tables
 *        (Extract[3], TgPixelRes[9], FldSpec[9], cache[1]) and siohook6 overrides (CMOS 0/5/7, TG 8006/805f/8061)
 *        owned by C; RAM IPC with the Lua (hook +0x220 request / +0x224 ack: 1 m1_on, 2 m1_off, 3 rec, 4 play,
 *        0xE0 quit), no more A/M10X3.REQ/ACK; automatic ImgMode 1 arming in photo M, never re-switched after a take.
 *   B: opaque overlay mask + opaque HUD in ImgMode 1 (Canon's YUV bars never show), HDMI guard, view 4:3 / 1:1 /
 *        OFF, RGGB colour preview 10b/12b with fixed black 127, live preview task M10Pv during the take (2.8 Hz).
 * v181c (2026-11-21): A/M10RUN.ASY -> _run returns at once (stand-alone Lua keeps the kbd task alive, so the
 *        half-press / SET stop of flag 0x2000000 works); A/M10X3.END (msg) written when the take is over.
 * v181b (2026-11-21): log RD1 (encoder read channel) registers +0x00..+0x20 as programmed (geometry tests).
 * v181 (2026-11-21, r159/Fable A1): ImgMode 1 REC: asynchronous encoder collect/re-kick (lj_poll) from the CH12
 *        readout loop and wait_dfe_w; raw ring 5 (was 3); compressed slots stop before WR2 (x_exsz - 0xC0000).
 * v180f (2026-11-21, r159): ImgMode 1 REC: arm window hi = per - 1.2 ms; WB kick deferred to right after the CH12
 *        start (inside the readout); 32 MiB warm-up write (FAT) + removal of the old take before opening the MLV.
 * m10_cine.flt - EOS M10 (fw 1.10d) RAW video.
 *
 * v179 (2026-11-18, r153): A/M10TRG.CFG = hex address of a RAM trigger block: TG/DFE/CDS/CMOS writes before the
 *   8830 sync of the first pass (pre) and right after its CH12 start (go), one-shot (Still readout test).
 * v177 (2026-11-17): 12-bit compressed REC (Film 1x3, r137: 12b + MOVOFF=8 = full 1184 lines):
 *   lj_on accepts lvn_bpp 12 (< 4 MiB encoder window), RD1 depth code 1 + LL unpacker 0x10 (<< 2 into
 *   the 14-bit JpCore container), A/M10HUF12.BIN, compressed slots sized from the frame. MLV RAWI
 *   stays 14-bit (black 2048, white 16383): samples are 12-bit << 2. 10/14-bit paths unchanged.
 * v176 (2026-11-16): Aperture field (F): CHDK shooting_set_av96_direct + Canon MoveIrisWithAv
 *   (0xfc43f6b9, CAM_AV_OVERRIDE_IRIS_FIX path), AUTO = untouched. Exit = hold MENU 1 s (MENU+SET
 *   kept); SET/REC ignored while MENU is down. On exit: exit_alt() so Canon gets the keys back and
 *   A/M10SH.END written so the autostart script ends.
 * v175 (2026-11-16): HUD kept during a take: M10Key redraws the whole HUD (bars + timer) at 1 Hz
 *   instead of the timer alone, and logs once if the overlay RAM was found erased.
 * v174 (2026-11-16): Shell UI revamp. CHDK OSD off in the shell; one top status bar (REC dot +
 *   timer, profile, card minutes, battery) and one bottom bar (ISO / Tv / profile / zebras /
 *   preview size), centre toasts. Pad: UP/DOWN field, LEFT/RIGHT value. Manual ISO / shutter forced
 *   at the sensor through the SIO hook (CMOS 0 gain, TG 805f/8061 end line), magnifier-safe (r133).
 *   Preview thumbnail or full frame. Recipe = r132 qualified 2K 14-bit HEFIX line.
 * v173 (2026-11-16): Zero-copy HEFIX: logical frame-to-compressed-slot map,
 *   retain preceding payload, scan outstanding maps before encode allocation,
 *   writer alone stamps shared VIDF header before SD write. Avoids the measured
 *   563 ms uncached memcpy per repaired frame in r130 (59 frames / 91 drops).
 * v172b (2026-11-16): Correct duplicate queue ordering, single-owner collection,
 *   late-error discard, bounded mixed tail drain and pin-on-timeout. Host C regressions.
 *   NOT hardware qualified yet; supersedes the first v172 build.
 * v172 (2026-11-16): In-camera HEAD_ERR frame replacement + 14-bit 0x10 shell profiles:
 *   - x_he_fix (59th CFG field HEFIX, always on in shell REC): when HEAD_ERR fires on frame fr,
 *     skip JpCore on the torn raw frame; if fr == 0 drop it, else lj_task duplicates the
 *     previous healthy compressed VIDF slot with updated timestamp/frameNumber (0-stall in capture).
 *   - sh_profs[]: add bpp and rsel fields; include 24p 2K 14b (2048x1104 0x10), 24p 1920 14b,
 *     and 25p 1920 14b alongside 10-bit profiles (live preview remains 10-bit).
 * v171 (2026-11-16): 14-bit Huffman table (A/M10HUF14.BIN) + 14-bit black level:
 *   - Load A/M10HUF14.BIN when lvn_bpp == 14 (avoids ~33% bloat / 0xff stuffing from 10b M10HUF.BIN).
 *   - Fix RAWI black level to 128u << (bpp - 10) (2048 at 14-bit).
 * v170 (2026-11-16): 14-bit cropped lossless REC + 2-block CH12 (yn=1) + args[3] stride.
 *
 * v167 (2026-11-14): REC timing + tail drain + split MLV headers + 24p/framing profiles + RAW zebras:
 *   - Gate ea_take(0)/hs_take on x_diag (no 120 ms frame-4 stall) and keep pre-capture xr_tick in lj_on mode.
 *   - Drain remaining captured frames (lj_cnt < xr_prod) in lj_drain() on REC stop before xr_stop = 1.
 *   - Patch MLVI GUID, fileCount, and per-chunk videoFrameCount on .MLV/.M00.. splits (mlv_finalize).
 *   - Set SH_RECIPE x_need = 1102 so incomplete st == 3 short frames never pass REC or preview.
 *   - Shell presets cycled via LEFT/RIGHT (24.000 fps fl=1819 per=41666 us: 2304/2512/2048/1920, plus 25p 2304),
 *     adaptive pv_render()/sh_radar(), and UP-toggled channel clipping zebras (>= 1020) in preview.
 * v166 (2026-11-13): preview = 172 x 80 thumbnail bottom right (Canon LV kept for focus), radar removed.
 * v165 (2026-11-13): shell live preview in the x5 magnifier: our own 10-bit capture (no encoder, no card),
 *   recorded window 2304 x 1076 sampled 2x2 to B&W on the CHDK overlay (360 x 168), ~10 fps, auto levels.
 *   REC/SET -> take, MENU -> preview off/on. Function sh_preview(), called from lv_x3 when sh_pv.
 * v164 (2026-11-13): shell "radar" in the x5 magnifier: bottom-right box = active area 2520 x 1080,
 *   red = recorded 2304 x 1076, yellow = what the LCD shows (magnifier rect 0x57d38), redrawn on move.
 * v156 (2026-11-13): lv_x3 in the x5 magnifier (head 045702a6): frame width 2592 (x_w), frame period from the
 *   8830 spacing (x_per, 33.3 ms in zoom), no WBInteg kick; passes only until the encoder path is qualified.
 * v155 (2026-11-13): slog() buffered in RAM during the REC loop (each card log line cost 2 sensor frames).
 * v163 (2026-11-13): shell recipe EW=2304 EOFF=240 (columns 192-2495, 2304 x 1076, -9 % vs 2520):
*   take 4 (v162) lost 1 frame in 8 on its 3.15 MB/frame stretch (~79 MB/s, card ceiling ~76).
 * v162 (2026-11-13): shell recipe EW=2400 EOFF=160 (columns 128-2527, 2400 x 1076 active, -5 % data);
*   USB power (physw_status[2] bit 28) -> stop take, remove hook / trap / 25p copy, quit shell.
 * v161 (2026-11-13): shell keeps REC/SET/MENU... from Canon with its own gui_handler (kbd_process -> 1),
*   re-asserted every 50 ms (ALT toggling or the script end replace it); no ALT mode needed.
* v160 (2026-11-13): stand-alone shell: resident task, self-install (SIO hook v6, head-error trap,
*   25 fps TgPixelRes copy), built-in recipe (no A/M10X3.CFG), REC key (fallback SET) start / stop,
*   numbered takes A/M10_NNNN.MLV / .M00..., status on screen, no host needed. Old paths unchanged.
* v159 (2026-11-13): zoom: MLV active area y1 = 28 (optical black rows), encoder window up to x_w (EW)
*   with the MLV geometry following it (EW/EH/EOFF crop, e.g. 1920 x 1076 of the active area).
* v158 (2026-11-13): REC in the x5 magnifier: frame period from the ImgSens cache (25 fps via m10zfps.py),
*   encoder / MLV at x_w, compressed slots sized from the raw frame, RAWC 1:1, 40 ms constants -> x_per.
* v157 (2026-11-13): ENC= encoder test at the real frame width (x_w, 2592 in the x5 magnifier);
*   CPU 10->14 conversion (ENC=10) refused in zoom (would overlap the output slot).
* v154 (2026-11-13): A/M10CAP.BIN per-pass record (entry/start/return us, sync path, result, st, 8830 misses).
 * v153 (2026-11-12): optional read-only DryOS task trace (57th CFG field TSK,
 * period us, 0 off); runtime kernel signature gate, bounded EXMEM, drained timer.
 * Names include the boot-copied kernel TCM region (validated on live 110d).
 * v152 (2026-11-12): arming window end (hi) accepted up to 15000 us (was 12000).
 * v151 (2026-11-12): 56th CFG field = 1: kick the encoder on kept short frames (st 3) as on full ones.
 * v150 (2026-11-12): 55th CFG field = busy-poll the last N lines of each readout (DMA end seen late -> lost frame).
 * v149 (2026-11-12): 54th CFG field = EXMEM size in MiB (16-48) for lv_x3: compressed ring absorbs SD write stalls.
 * v148 (2026-11-12): 53rd CFG field = 1: no-pause head-error recovery (frame kept, IRQ re-armed,
 *   no 150 ms wait); every error listed in A/M10HE.BIN ('VHE1', n, her, late, n x (fr<<8|st)).
 * v116 (2026-11-11): 35th-37th CFG fields = SD write window (us after 8830) and chunk KiB (LJ REC).
 * v115 (2026-11-11): 34th CFG field = 1: each LJ slice starts in its own (new) 8830 window.
 * v113 (2026-11-11): up to 32 slices, 33rd CFG field = busy gap between slices (us).
 * v112 (2026-11-11): 32nd CFG field = LJ92 slices per frame (VIDF frameSpace: M10S n sizes).
 * v111 (2026-11-11): 31st CFG field = engine pokes after the encoder setup; RD1/WR1 flags logged.
 * v110 (2026-11-11): 29th/30th CFG fields = encoder WR2 preview size (args[13]/[14]).
 * v107 (2026-11-11): 28th CFG field = encoder lines in LJ REC (test).
 * v106 (2026-11-11): 27th CFG field = encoder read EDMAC channel (25-47).
 * v105 (2026-11-11): 25th/26th CFG fields = encoder start window (us after 8830); phases logged.
 * v104 (2026-11-11): 24th CFG field = encoder WR2 channel (CR2.c uses 9, busy in Film).
 * v103 (2026-11-11): LJ REC + flag 0x200: encoder starts only while our capture is idle.
 * v102 (2026-11-11): LJ REC: 4th field wms = KiB written per frame (0 = whole frame).
 * v101 (2026-11-11): REC + ENC 11 -> compressed MLV (LJ92 14-bit container, class 0x21):
 * capture task -> raw ring (3) -> encoder task M10LJ (prio 0x1B) -> compressed ring -> writer.
 * v100 (2026-11-11): A/M10HUF.BIN present -> custom lossless Huffman tables (args[18]).
 * v99 (2026-11-11): 23rd field = JpCore c0e00000+off pokes after setup (OO:VV,...).
 * v98 (2026-11-11): precision -> 0xc0e00084 (0xc0e00010 held the marker codes), 23rd field = c0e0009c.
 * v96 (2026-11-11): CSH >> 4 = JpCore precision written to 0xc0e00010 after setup (ENC 11).
 * v95 (2026-11-11): ENC 11 = encoder reads the 10-bit pass itself (RD1 EDMAC + unpacker
 * redone at 10 bits after the 14-bit setup), CSH = unpacker code.
 * v94 (2026-11-11): faster 10->14 converter (O3, 32-bit I/O), 21st CFG field = shift (0 or 4).
 * v93 (2026-11-11): ENC 10 = 10-bit pass converted to 14 bits by the CPU, then encoded.
 * v92 (2026-11-11): 20th CFG field 12/14: lossless encoder test on pass 0
 * (out A/M10LL.BIN, header ENC2 size us st cbsize bpp h w).
 * v91 (2026-11-11): 19th CFG field N: REC chained (xo 2) leaves one sensor frame
 * to Canon after every N captured frames (25 fps x N/(N+1)).
 * v90 (2026-11-11): 18th CFG field = MLV RAWC skipping_y (0 = 1x3, 2 = Film 3x3),
 * so MLV App shows the native Film 3:2 without the x3 stretch.
 *
 * v73 (2026-11-08): option 0x10 (8th CFG field, needs the 8830 sync flag
 * 0x20000000): persistent PACK32 / CH12 pipeline in lv_x3 (passes and REC).
 * Lock + PK_TAKE + PK_ON + crossbar once; per frame only (in the 8830 window
 * that follows our own DMA) a PACK32 datapath reset pulse (0xc0f08090 =
 * 0x80000000 then 1, as PK_ON does; option 0x20 = pulse only after an
 * incomplete frame, i.e. a short frame or L < 1184), CH12 reprogrammed
 * (buffer address) and started; a short frame (st 3) is aborted without
 * disconnecting the crossbar. Full teardown (CH12 stop, PK_OFF writes, masked
 * restore, PK_GIVE(6), unlock) only at the end, on error, on a drop / late
 * window, before a gap, and every M frames (11th CFG field, default 6 =
 * 240 ms, 0 = never) so a Canon task waiting on semaphore #6 (FldCreat /
 * TgCtrl, 1 s assert, 300 ms TG callback) gets it in time.
 * 12th CFG field = min lines of an accepted short frame (0 = legacy L - 32;
 * below it a short frame is dropped, REC counts it, the pipeline stays open).
 *
 * v72 (2026-11-08): 8th CFG field (hex options) + 9th/10th (window lo/hi us
 * after DFE 8830): 1 = CPU-friendly 8830 sync (msleep until the last few ms,
 * start/restore anywhere in [8830+lo, 8830+hi]), 2 = chain the next pass in
 * the same quiet window as our restore, 4 = PACK32 pack 4 + CH12 flag 0x1000.
 *
 * v60 (2026-11-08): LV-end sync needs the LV EDMAC still for 2 ms (a pause
 * inside the FHD readout armed a pass mid-frame), late limit 3.5 ms.
 * v59 (2026-11-08): SIO hook v4, v5 or v6 accepted (ring at +0x300, v6 +0x500).
 * v58 (2026-11-08): synced passes: if PK_TAKE (PACK32 semaphore) waited > 1 ms
* (Canon was using PACK32), give it back and skip the frame (REC: counted as a drop).
* v57 (2026-11-08): MLV split into ML-style chunks (A/M10X3.MLV, .M00, .M01 ...)
* below 4000 MiB each (FAT32 card: the 60 s+ recording failed at 4 GiB).
* v56 (2026-11-08): flag 0x2000000: REC stops on SET / half-press (N = max).
* v55 (2026-11-08): flag 0x1000000: REC writes A/M10X3.MLV (MLVI/RAWI/RAWC/
* IDNT header, VIDF blocks with 480-byte frameSpace + NULL padding, one aligned
* write per frame; raw payload = PACK32 pack 2 = ML MLV bit layout).
* v54 (2026-11-08): LV-end sync rejects a stop seen > 1.5 ms late.
* v53 (2026-11-08): flag 0x800000: sync on the end of Canon's LV EDMAC
* (c0f04300) transfer = end of the sensor readout (FHD 1x3), instead of SIO bursts.
* v51 (2026-11-08): calibration timeline (flag 0x20) records Canon EDMAC
* current addresses c0f26908, c0f04008, c0f26a08, c0f04108.
* v50 (2026-11-08): flag 0x400000: sync only on the 2nd CMOS burst of a pair
* (FHD 1x3: the 1190-line readout ends ~2 ms before it, next one starts ~18 ms after).
* v49 (2026-11-08): flag 0x200000: sync only on the first CMOS burst of a pair
* (FHD 1x3: bursts come in pairs 8.6 ms apart; the full readout follows the first).
* v48 (2026-11-08): sync delay = (flags >> 16) * 100 us when set.
* v47 (2026-11-08): flag bit15 = arm 9 ms after the burst (FHD 1x3: the
* burst comes single or in pairs; the readout starts ~11 ms after the last).
* v46 (2026-11-08): burst timestamps masked to 20 bits; entries > 30 ms old
* ignored (could match a stale pair on the first scan).
* v45 (2026-11-08): flag bit15: sync on the 2nd CMOS burst of a pair (FHD 1x3:
* the 1190-line readout starts ~11 ms after it and lasts ~29 ms).
* v44 (2026-11-08): predictive sleep: msleep(1) is a 10 ms tick, so only sleep
* while the next burst (40 ms after the first of the last pair) is > 14 ms away.
* v43 (2026-11-08): wait_eof with sleep only sleeps while the next burst is
* > 4 ms away (busy-poll at the frame end), so the sync stays < 1 ms late.
* v42 (2026-11-08): sync lateness (us after Canon's CMOS burst) stored in
* stg[k][0][3]; flag bit12 sleep in wait_eof, bit13 busy sync in REC, bit14
* skip bursts seen > 1.5 ms late.
* v41 (2026-11-08): REC 4th field = KiB written per frame (0 = whole frame),
* flag bit11 = 2 MiB chunks.
* v40 (2026-11-08): flag bit10: REC without capture (synced card writes of
* the EXMEM slots only) to separate the card write from the capture.
* v39 (2026-11-08): flag bit9: REC writer gated: 128 KiB chunks, started only
* while no CH12/PACK32 transfer is in progress (card DMA in the blanking).
* v38 (2026-11-08): REC writer at prio 0x1C (below capture), wait_eof sleeps
* 1 ms between ring checks, LVX3S snapshot on a REC stall.
* v37 (2026-11-08): flag bit8: continuous recording (synced back-to-back
* capture into EXMEM slots + writer task -> A/M10X3.RAW, drops counted,
* timings -> A/M10X3T.BIN).
* v36 (2026-11-08): flag bit7: back-to-back synced passes (single idle check,
* no gap) -> one pass per sensor frame.
* v35 (2026-11-08): flag bit6: frame sync, each pass waits for Canon's
* end-of-readout CMOS burst (v4 hook ring) before PACK32/CH12 -> one whole
* frame per pass, restore in the vertical blanking.
* v34 (2026-11-08): flag bit5: calibration, busy-poll pass with a 250 us
* timeline (absolute timer, comparable with the SIO ring timestamps).
* v33 (2026-11-08): flag bit4: wait 8 ms after the DMA end before ch12_stop /
* PACK32 restore (the 727-line DMA always ends at the sensor EOF, when Canon's
* frame handler runs); SIO ring snapshot also on success.
* v32 (2026-11-08): A/M10X3.CFG 6th field = flags: bit0 no card I/O during
* the passes (log buffered), bit1 3 s TG watch after the last pass before any
* file write (A/LVX3W.BIN), bit2 do not write the image data, bit3 ch12_idle
* 2 polls instead of 20.
* v31 (2026-11-07): stage trace: lvn_cap records (us, TG state, ImgSens word,
 * SIO index) at 12 points of each pass (entry ... unlock) for 16 passes, and
 * lv_x3 adds the gap; appended to A/LVX3S.BIN, which is now always written.
 *
 * v30 (2026-11-07): diagnosis of the stalled pass: per-ms timeline inside each
 * lvn_cap poll (TG task state, TgCtrl/ImgSens words, SIO index) and, on a
 * stall, an immediate copy of the v4 SIO hook ring (who restarted the TG,
 * with return addresses) -> A/LVX3S.BIN, written before the shutdown.
 *
 * v29 (2026-11-07): 5th config field G = gap between passes in ms (default 500).
 *
 * v28 (2026-11-07): lv_x3 4th config field W (ms): after pass 0, watch W ms
 * (1 ms) TG task state [0xe664], TgCtrl/ImgSens state words and the SIO
 * hook ring index -> A/LVX3W.BIN; one record per change (+ SIO every 20 ms).
 *
 * v27 (2026-11-07): lv_x3 runs in any non-zoom LV when A/M10X3.CFG exists.
 *
 * v26 (2026-11-07): lv_x3 bit depth from A/M10X3.CFG ("N L BPP", 10/12/14):
 * test of the bandwidth hypothesis (Film/photo LV keep Canon's 1080p YUV
 * path on EDMAC ch16/ch0 busy, zoom does not).
 *
 * v25 (2026-11-07): Film / 1x3 probe. When the head reads 1190 lines (Film,
 * normal or 1x3 via TG 0x800c = 0 set by the host hook), run lv_x3(): N
 * isolated CH12 passes of L lines (A/M10X3.CFG: "N L", default 1 256),
 * 14-bit pack 2, width 1808, then a 3 s TG/heartbeat watch -> A/LVX3.BIN
 * (lvm2_hdr layout, magic M10LVX03). Started from the menu or over USB
 * (core module_run). Other LV modes still go to lv_multi2, zoom to grab().
 *
 * v24 (2026-11-07): back to lv_multi2 (v22 settings) + Canon raw-routing
 * state at start (0xc0f37014/37074, [0xe558]/[0xe55c]); meant for movie mode.
 *
 * v23 (2026-11-07): normal LV -> lv_watch(): passive 6 s watch of CH12,
 * its crossbar and the TG state (no lock, no PACK32, no DMA) -> A/LVW.BIN.
 *
 * v22 (2026-11-07): real transfers again, polled with msleep(1) (no busy
 * loop), as in the zoom pipeline.
 *
 * v21 (2026-11-07): no-DMA passes held 70 ms (= longest real pass); TG and
 * ImgSens state logged per pass (cbr[k][1..2] reused).
 *
 * v20 (2026-11-07): bisection: lv_multi2 with lvm_nodma = 1 (everything but
 * the CH12 start), to tell whether the transfer itself triggers the fatal.
 *
 * v19 (2026-11-07): lvn_cap restores 0xc0f37014/37074/PACK32 (masked) BEFORE
 * giving PACK32 semaphore #6 back (probe56: ImgSens fatal 0x100000).
 *
 * v18 (2026-11-07): normal LV -> lv_multi2(): 16 isolated 256-line passes
 * (short PACK32 holds), CH12 CBR entry logged, 3 s heartbeat -> A/LVM2.BIN.
 *
 * v17 (2026-11-07): normal LV -> lv_multi(): Canon EVF state dump + 8
 * re-armed 256-line passes (EvfCaptureSystem captures in passes).
 *
 * v16 (2026-11-07): LVN probe with single-block transfers, repeat test,
 * DMA pointer trace; files A/L<head lines>_<step>.RAW.
 *
 * v15 (2026-11-07): outside zoom x5, lv_probe() captures the Canon normal
 * live view readout (3x3) in growing steps, then compresses one frame.
 *
 * v14 (2026-11-07): v13 (phase search in the capture stage, us timings) +
 * file pre-allocation before the loop; message shows the steady-state rate.
 *
 * v12 (2026-11-07): three stages in parallel (capture / encoder task /
 * writer task), 2 input buffers, 3 output slots: see the v12 block.
 *
 * v11 (2026-11-07): pipelined loop, see grab(): capture + phase + encode in
 * this task, card writes in a second task (M10Wr) from a ring of 3 output
 * slots; per-frame idle polling removed (probe48: ~800 ms/frame lost).
 * NF from A/M10V.CFG (default 60, max 240). Output A/M10CINE.VID (M10VID02).
 *
 * v10 (2026-11-07): continuous loop capture (PACK32 pack 2, 14-bit, CH12)
 * -> hardware lossless (LosslessEncode/JpCore) -> card write, NF frames
 * (A/M10V.CFG, default 20), 2592 x 924. Output A/M10CINE.VID, timings in
 * the header and A/M10CINE.LOG. See grab() / cap_frame() / enc_frame().
 *
 * v5 (2026-11-07): capture one 12-bit frame (segment, A/M10C_12.RAW), then
 * run Canon's LosslessEncode/JpCore path on it 3 times (input bit phases
 * 0/4/8), output A/M10LL.BIN (see ll_test below). Stages in A/M10CINE.LOG.
 *
 * Validated path (Lua probes 28-37, module v3 / probe39: 642 frames, no stall):
 *   CH12 write EDMAC (0xc0f26500, crossbar 0xc0f05210) on port 0,
 *   Canon resource lock {0x61, 0x5f, 0x84} (0xfc373f9e / 0xfc375588),
 *   PACK32 take/on/off (0xfc22f738 / 0xfc22f73e(bpp,0) / 0xfc22f7dc),
 *   4-byte transfers (flags 0x40000000), each EDMAC block < 4 MiB,
 *   re-arm = ctl 2 (abort), wait ctl 0, reprogram, ctl 1.
 * Zoom x5 readout: 2592 x 1107, 16-bit = u16 LE (14-bit << 2), RGGB.
 *
 * v4 (2026-11-07): bit-depth test. One session = 3 segments on the same
 * scene: bpp 16 (2 frames, reference), 12 (3 frames), 10 (3 frames).
 * ROM: PACK32 on -> 0xfc34d5b6 -> 0xfc34d54a writes 0xc0f08094 =
 * 0x000 (10) / 0x010 (12) / 0x020 (14) / 0x120 (16).
 * Each segment is a full setup/teardown (lock, take, on(bpp), frames, off,
 * restore, unlock) then writes A/M10C_<bpp>.RAW. Line size = 2592*bpp/8.
 * Questions answered on the host: packing order, which bits are kept
 * (top or bottom of the 16-bit value), and the DMA time per frame.
 * The first stall ends the session (stalls are irreversible).
 */

#include "camera_info.h"
#include "gui.h"
#include "gui_draw.h"
#include "clock.h"
#include "exmem.h"
#include "callfunc.h"
#include "module_load.h"
#include "keyboard.h"
#include "simple_module.h"
#include "task.h"
#include "semaphore.h"
#include "battery.h"
#include "sd_card.h"
#include "debug_led.h"
#include "stdio.h"
#include "shooting.h"   // v178: shooting_set_playrec_mode, shooting_set_mode_chdk
#include "modes.h"

// ---- firmware 1.10d addresses (Thumb, +1) ----
#define FN_RES_LOCK    0xfc373f9f
#define FN_RES_UNLOCK  0xfc375589
#define FN_PK_TAKE     0xfc22f739
#define FN_PK_ON       0xfc22f73f
#define FN_PK_OFF      0xfc22f7dd
#define FN_PK_GIVE     0xfc34d489   // (sem index): PreProCommon give, PACK32 = 6
#define FN_ENGDRV_OUT  0xfc38d28b   // (reg, val): shadow + MMIO
#define FN_ENGDRV_READ 0xfc38d2b9   // (reg): shadow
#define FN_ENGDRV_MASK 0xfc38d2c5   // (reg, and, or): shadow + MMIO, masked

// v81: write channel configurable (default 12); names kept for history
static unsigned ch_base = 0xc0f26500, ch_xbar = 0xc0f05210, ch_idx = 12;
#define CH12_BASE      ch_base
#define CH12_XBAR      ch_xbar
#define USEC_TIMER     0xc0242014   // 20-bit microsecond counter
#define DSS_FLAGS      0x00028738
#define PACK32_MODE    0xc0f08094

#define FRAME_W        2592
#define FRAME_H        1107
#define BLOCK_LINES    554          // 2 blocks per frame, each < 4 MiB

#define EXMEM_TYPE     5
#define EXMEM_SIZE     0x01000000   // 16 MB
#define MAX_FRAMES     4

typedef unsigned (*fn0)(void);
typedef unsigned (*fn1)(unsigned);
typedef unsigned (*fn2)(unsigned, unsigned);
typedef unsigned (*fn3)(unsigned, unsigned, unsigned);

// v186a: Canon zero-arg refcounted clock holds (1.10d, Thumb): LCLK hold/release + clock-save take/release
#define FN_LCLK_HOLD0   0xfc1803f3
#define FN_LCLK_REL0    0xfc180429
#define FN_CLKSAVE_TAKE 0xfc1ec6d7
#define FN_CLKSAVE_REL  0xfc1ec6ed
#ifdef M10_HOST_TEST
static unsigned m10_fw0_stub(unsigned a) { (void)a; return 0; }   // host tests: never call ROM addresses
#define FW0(a) m10_fw0_stub(a)
#else
#define FW0(a) (((fn0)(a))())
#endif

#define REG(a) (*(volatile unsigned *)(a))

static void eng_out(unsigned reg, unsigned val) { ((fn2)FN_ENGDRV_OUT)(reg, val); }
static unsigned shamem(unsigned reg) { return ((fn1)FN_ENGDRV_READ)(reg); }
static unsigned usec(void) { return REG(USEC_TIMER) & 0xfffff; }
static unsigned udiff(unsigned a, unsigned b) { return (b - a) & 0xfffff; }

static unsigned reslist[4] = { 0x61, 0x5f, 0x84, 0 };
static const unsigned chregs[] = {0x04,0x08,0x0c,0x10,0x14,0x18,0x1c,0x20,0x24,0x28,0x40};
#define NCHREGS (sizeof(chregs)/sizeof(chregs[0]))
static unsigned chsaved[NCHREGS];

static int running = 0;
static char msg[96];

typedef struct {
    char     magic[8];      // "M10CINE2"
    unsigned width, height, bpp, black, white;
    unsigned nframes;
    unsigned line_bytes, frame_bytes;
    unsigned pack_mode;     // 0xc0f08094 after PACK32 on
    unsigned frame_us[MAX_FRAMES];   // DMA duration of each frame
    unsigned gap_us[MAX_FRAMES];     // end of previous frame -> start of this one
    unsigned status[MAX_FRAMES];
} cine_hdr;
static cine_hdr hdr;

/* v155: while slog_defer is set (REC capture loop), lines go to a RAM buffer
 * instead of the card: every open/write/close of A/M10CINE.LOG from the
 * capture task cost ~60-80 ms and two sensor frames (live114: 133/133 lines
 * logged during REC were followed by a 2-slot gap). slog_flush() writes the
 * buffer once REC is over. Overflow is counted, never blocks. */
#define SLOG_BUF 8192   // v182: 4096 -> 8192 (REC report deferred too)
static char slog_buf[SLOG_BUF];
static unsigned slog_len = 0, slog_lost = 0, slog_defer = 0;
static volatile unsigned sh_on = 0, sh_stop_req = 0;   // v160 shell
static volatile unsigned sh_rec_on = 0;                // v182: moved up (WB watchdog idle rule)
static volatile unsigned sh_quit_req = 0;              // v176: MENU held 1 s
static volatile unsigned sh_pv = 0, sh_pv_key = 0, sh_pv_n = 0, sh_pv_off = 0;   // v165: live preview from our RAW (shell, x5)
// v167: zoom REC recipe base (r116_m1 + x_need=1102 guard against short/empty frames); width/crop overridden by sh_profs
// v174: = r132 qualified line (m10x3raw.py zoom ... HEFIX=1 RSEL=10 CSH=0 ENC=11 EXM=48 HBN=16 HER=1 SKICK=1 NS='1 0 2'
//   KW=8000), with 3000 frames, x_need=1102 kept (short-frame guard), CSH 0 (14-bit), HBN 16.
// v178: Film 1x3 12-bit PREFIFO recipe (= r147 run F / r149 deliverable: line 640, EW 1536, EH 1156, EOFF 76140, RSEL 22)
#define SH_RECIPE_X3 "3000 1184 12 0 0 562039168 0 80000003 5000 11000 6 0 0 12 4 99 0 0 11 0 0 a0:0 9 0 0 35 1156 0 0 0:0 1 0 2 0 0 256 1 1 0 0 1536 0 0 8000 76140 0 16 0 0 0 0 1 48 0 1 0 22\n"
// v182: ImgMode 1 1920x1440 recipe (= M10M1.LUA mlv_cfg minus bit 0x2000000: shell keywatch owns STOP; per 41666: lo 35166, hi 39166 -> per - 1200)
#define SH_RECIPE_M1 "3000 1440 10 0 0 553650560 0 80000003 35166 39166 6 1436 0 12 4 99 0 0 11 0 0 a0:0 9 0 0 35 1440 0 0 0:0 1 0 2 0 0 256 1 1 0 0 0 0 0 8000 0 0 16 0 0 0 0 1 48 350 1 0 10 1\n"
#define SH_RECIPE "3000 1104 14 0 0 553650560 0 80000003 5000 11000 6 1102 0 12 4 99 0 0 11 0 0 a0:0 9 0 0 35 0 0 0 0:0 1 0 2 0 0 256 1 1 0 0 2048 0 0 8000 532 0 16 0 0 0 0 1 48 0 1 0 10 1\n"
static void slog(const char *fmt, unsigned a, unsigned b)
{
    char t[96];
    int n = sprintf(t, "%d ", get_tick_count());
    n += sprintf(t + n, fmt, a, b);
    t[n++] = '\n';
    if (slog_defer) {
        if (slog_len + n <= SLOG_BUF) { memcpy(slog_buf + slog_len, t, n); slog_len += n; }
        else slog_lost++;
        return;
    }
    int fd = open("A/M10CINE.LOG", O_WRONLY | O_CREAT | O_APPEND, 0777);
    if (fd >= 0) { write(fd, t, n); close(fd); }
}
static void slog_flush(void)
{
    unsigned lost = slog_lost;
    slog_defer = 0;
    if (slog_len) {
        int fd = open("A/M10CINE.LOG", O_WRONLY | O_CREAT | O_APPEND, 0777);
        if (fd >= 0) { write(fd, slog_buf, slog_len); close(fd); }
    }
    slog_len = 0; slog_lost = 0;
    slog("  v155 deferred log lost=%d", lost, 0);
}

static int idle_polls = 20;     // v32: configurable (lv_x3 flag bit3 -> 2)
static int ch12_idle(void)
{
    int k;
    for (k = 0; k < (idle_polls ? idle_polls : 1); k++) {
        if (shamem(CH12_XBAR) != 0x80000000 || REG(CH12_BASE) != 0) return 0;
        if (idle_polls) msleep(5);              // v36: idle_polls 0 = one check, no sleep
    }
    return 1;
}

static int ch12_stop(void)
{
    int t = get_tick_count();
    eng_out(CH12_BASE, 2);
    while (REG(CH12_BASE) != 0 && get_tick_count() - t < 300) eng_out(CH12_BASE, 2);
    eng_out(CH12_XBAR, 0x80000000);
    return REG(CH12_BASE) == 0;
}

// program one frame (2-D geometry: 1 block of BLOCK_LINES + a last block)
static unsigned ch12_flags = 0x40000000;
static void ch12_program(unsigned phys, unsigned lb)
{
    unsigned last = FRAME_H - BLOCK_LINES;   // 554 + 553 lines
    int off;
    eng_out(CH12_BASE + 0x40, 0);
    eng_out(CH12_BASE + 0x04, ch12_flags);
    eng_out(CH12_BASE + 0x08, phys);
    eng_out(CH12_BASE + 0x0c, 1 << 16);
    eng_out(CH12_BASE + 0x14, ((BLOCK_LINES - 1) << 16) | lb);
    eng_out(CH12_BASE + 0x10, ((last - 1) << 16) | lb);
    for (off = 0x18; off <= 0x28; off += 4) eng_out(CH12_BASE + off, 0);
}

// returns 0 ok, 1 stall
static unsigned u_start, u_end;
static int cap_sleep = 0;       // v12: sleep while the DMA runs (no 27 ms busy-poll)
static int ch12_run(unsigned *dt)
{
    unsigned u0 = usec(), lastp = 0xffffffff, tmove = get_tick_count();
    u_start = u0;
    eng_out(CH12_BASE, 1);
    for (;;) {
        unsigned p;
        if (REG(CH12_BASE) == 0) { u_end = usec(); break; }
        p = REG(CH12_BASE + 8);
        if (p != lastp) { lastp = p; tmove = get_tick_count(); }
        else if (get_tick_count() - tmove > 60) { *dt = udiff(u0, usec()); return 1; }
        if (cap_sleep) msleep(1);
    }
    *dt = udiff(u0, usec());
    return 0;
}

// one segment at a given bit depth. returns 1 ok, 0 stall, -1 setup error
// PACK32 sub-registers written by 0xfc34d5b6 (pack mode) and not reset by PK_OFF
static const unsigned pk_regs[] = { 0xc0f08094, 0xc0f08264, 0xc0f08268, 0xc0f082bc, 0xc0f08bf0 };
#define NPK (sizeof(pk_regs) / sizeof(pk_regs[0]))
static unsigned pk_saved[NPK];

static unsigned seg_pack = 0;   // PACK32 pack mode (Canon: 2 -> EDMAC 0x40000000, 4 -> 0x1000)
static int segment(char *buf, unsigned phys, unsigned bpp, unsigned nfr, char *res)
{
    unsigned lb = FRAME_W * bpp / 8, fb = lb * FRAME_H;
    unsigned i, s14, s74, s8094, prev_end = 0, st, nrun = 0, tw;
    int fd, ok = 1;
    char name[20];

    if (nfr > MAX_FRAMES) nfr = MAX_FRAMES;
    while (nfr > 1 && nfr * fb > EXMEM_SIZE) nfr--;
    if (!ch12_idle()) { sprintf(res, "%d:CH12 occupe ", bpp); return -1; }
    memset(buf, 0xee, nfr * fb);        // untouched bytes stay 0xee

    ((fn1)FN_RES_LOCK)((unsigned)reslist);
    for (i = 0; i < NCHREGS; i++) chsaved[i] = shamem(CH12_BASE + chregs[i]);
    if (((fn0)FN_PK_TAKE)() != 0) {
        ((fn1)FN_RES_UNLOCK)((unsigned)reslist);
        sprintf(res, "%d:PACK32 occupe ", bpp);
        return -1;
    }
    s14 = shamem(0xc0f37014);
    s74 = shamem(0xc0f37074);
    s8094 = shamem(PACK32_MODE);
    for (i = 0; i < NPK; i++) pk_saved[i] = shamem(pk_regs[i]);
    ch12_flags = (seg_pack == 4) ? 0x1000 : 0x40000000;
    ((fn2)FN_PK_ON)(bpp, seg_pack);
    slog("  pack %d: 8264=%08x", seg_pack, shamem(0xc0f08264));
    slog("  8bf0=%08x 82bc=%08x", shamem(0xc0f08bf0), shamem(0xc0f082bc));

    memset(&hdr, 0, sizeof(hdr));
    memcpy(hdr.magic, "M10CINE2", 8);
    hdr.width = FRAME_W; hdr.height = FRAME_H; hdr.bpp = bpp;
    hdr.black = 2048 << 2; hdr.white = 16383 << 2;      // 16-bit scale
    hdr.line_bytes = lb; hdr.frame_bytes = fb;
    hdr.pack_mode = shamem(PACK32_MODE);
    slog("seg bpp=%d 8094=%08x", bpp, hdr.pack_mode);
    slog("  s14=%08x s74=%08x", s14, s74);

    eng_out(CH12_XBAR, 0x00);
    for (i = 0; i < nfr; i++) {
        unsigned dt;
        if (i) {   // re-arm: abort, wait idle
            int t = get_tick_count();
            eng_out(CH12_BASE, 2);
            while (REG(CH12_BASE) != 0 && get_tick_count() - t < 50) ;
            if (REG(CH12_BASE) != 0) { ok = 0; break; }
        }
        ch12_program(phys + i * fb, lb);
        st = ch12_run(&dt);
        nrun = i + 1;
        hdr.frame_us[i] = dt;
        hdr.status[i] = st;
        if (i) hdr.gap_us[i] = udiff(prev_end, u_start);
        prev_end = u_end;
        slog("  frame %d dt=%d", i, dt);
        if (st) { ok = 0; break; }
        msleep(1);
    }
    hdr.nframes = nrun;
    if (!ch12_stop()) ok = -1;

    ((fn0)FN_PK_OFF)();
    eng_out(0xc0f37014, s14);
    eng_out(0xc0f37074, s74);
    eng_out(PACK32_MODE, s8094);        // PK_OFF leaves the bit depth set
    for (i = 0; i < NPK; i++) eng_out(pk_regs[i], pk_saved[i]);
    ch12_flags = 0x40000000;
    for (i = 0; i < NCHREGS; i++) eng_out(CH12_BASE + chregs[i], chsaved[i]);
    ((fn1)FN_RES_UNLOCK)((unsigned)reslist);
    slog("  restored 8094=%08x ok=%d", shamem(PACK32_MODE), ok);

    tw = get_tick_count();
    if (seg_pack) sprintf(name, "A/M10P%d_%02d.RAW", seg_pack, bpp);
    else sprintf(name, "A/M10C_%02d.RAW", bpp);
    fd = open(name, O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (fd >= 0) {
        write(fd, &hdr, sizeof(hdr));
        write(fd, buf, nfr * fb);       // all buffers, even unfilled ones
        close(fd);
    }
    slog("  written %d bytes in %d ms", nfr * fb, get_tick_count() - tw);
    sprintf(res, "%d:%s %d/%d %dus ", bpp, ok > 0 ? "ok" : (ok == 0 ? "STALL" : "BLOQ"),
            nrun, nfr, hdr.frame_us[0]);
    return ok;
}

// ---------------------------------------------------------------------------
// v5 "LL1": Canon hardware lossless encoder on one captured 12-bit frame.
// ROM 1.10d, call order copied from CR2.c (0xfc498852 / 0xfc49821e):
//   LosslessEncode init 0xfc58183e(cfg)      cfg = {rd 0x23, wr1 0, wr2 9, 0,0,0,0, 1, 0}
//   register CBR        0xfc581828(cbr, ctx)
//   CR2 clock lock      0xfc498200 -> lock {0xd, 0xe}
//   setup + res lock    0xfc581eec(args)
//   start               0xfc582066()
//   wait for the CBR    (Canon: semaphore, 3 s)
//   stop + unlock       0xfc5820f4()
//   CR2 clock unlock    0xfc498328
// args layout reconstructed from 0xfc49821e / 0xfc581eec (words):
//   0 w, 1 h, 2 input addr, 3 stride px, 4 x0, 5 y0, 6 bits (1 = 12, 2 = 14;
//   10-bit asserts in 0xfc58228a), 7 WR2 (preview) addr, 8 CBR flavour 0,
//   9 n output chunks, 10 -> {addr, size}..., 11..14 WR2 resize (unused,
//   [0x4f9f0+0x4c] = 0), 15 WR2 decimation 5, 16 0, 17 CFA order 0,
//   18 Huffman tables (0xfc6d8de4, as 0xfc511afc(.., 2, 0)).
// The input starts at an unknown bit phase (0/4/8 bits per stream): the
// encoder is run at address offsets 0, 4, 8 bytes; the right phase gives
// the smallest output. Input height 1078 lines: one EDMAC block < 4 MiB.
// ---------------------------------------------------------------------------
#define FN_LL_PARAM    0xfc5818a3
#define FN_LL_INIT     0xfc58183f
#define FN_LL_CBR      0xfc581829
#define FN_LL_SETUP    0xfc581eed
#define FN_LL_START    0xfc582067
#define FN_LL_STOP     0xfc5820f5
#define FN_CR2_LOCK    0xfc498201
#define FN_CR2_UNLOCK  0xfc498329
#define LL_HUFF        0xfc6d8de4
// image-path routing (0xfc205c94(row)): 5 slots, each an engio list index;
// cache of applied indices at RAM 0xc210, list table {ptr, n} at 0xfc62b0bc,
// clock lock {0x83, end} at 0xfc62b050, list writer 0xfc36f380(ptr, n)
#define FN_ROUTE_SET   0xfc205c95
#define FN_ENGIO_LIST  0xfc36f381
#define ROUTE_CACHE    0x0000c210
#define ROUTE_TAB      0xfc62b0bc
#define ROUTE_LOCK     0xfc62b050

#define LL_H           1078         // 12-bit: 3888 B/line, one block < 4 MiB
#define LL_H14         924          // 14-bit: 4536 B/line, one block < 4 MiB
#define LL_W           FRAME_W
#define LL_NRUN        3
#define LL_WR2_OFF     0x00500000
#define LL_WR2_SIZE    0x00040000
#define LL_OUT_OFF     0x00540000
#define LL_OUT_SIZE    0x00380000

typedef struct {
    char     magic[8];      // "M10LL003"
    unsigned w, h, bits, nruns;
    unsigned off[LL_NRUN], st[LL_NRUN], size[LL_NRUN], us[LL_NRUN];
    unsigned word0[LL_NRUN], done[LL_NRUN], end_ptr[LL_NRUN];
    unsigned ndiff, nrestored, out_size_max;
    unsigned jp_st[LL_NRUN], jp20[LL_NRUN], jp44[LL_NRUN], rd_end[LL_NRUN], wr2_end[LL_NRUN];
} ll_hdr;
static ll_hdr llh;

static volatile unsigned cb_done, cb_st, cb_size, cb_x, cb_us;
static int sem_enc = 0;         // v12: given by the CBR (Canon CR2.c does the same)
static void ll_cbr(unsigned ctx, unsigned st, unsigned size, unsigned x)
{
    (void)ctx;
    cb_st = st; cb_size = size; cb_x = x; cb_us = usec(); cb_done = 1;
    if (sem_enc) GiveSemaphore(sem_enc);
}

// engine registers the encoder path may rewrite (shadow snapshot/restore)
static const unsigned snap_rng[][2] = {
    {0xc0f12000, 64}, {0xc0f13000, 64}, {0xc0f37000, 768}, {0xc0f08060, 12}, {0xc0f08ba0, 4},
    {0xc0f45000, 8},
};
#define NSNAP (64 + 64 + 768 + 12 + 4 + 8)
static unsigned snap[NSNAP];
static int snap_quiet = 0;      // v10 loop: no per-register logging
static int snap_skip(unsigned r)
{
    return r == 0xc0f12000 || r == 0xc0f13060 || r == 0xc0f375a0 || r == 0xc0f375a4
        || (r >= 0xc0f370b0 && r <= 0xc0f370ec);
}
static void snap_take(void)
{
    unsigned k, i, n = 0;
    for (k = 0; k < sizeof(snap_rng) / sizeof(snap_rng[0]); k++)
        for (i = 0; i < snap_rng[k][1]; i++) snap[n++] = shamem(snap_rng[k][0] + i * 4);
}
static void snap_restore(void)
{
    unsigned k, i, n = 0, nd = 0, nr = 0;
    for (k = 0; k < sizeof(snap_rng) / sizeof(snap_rng[0]); k++)
        for (i = 0; i < snap_rng[k][1]; i++, n++) {
            unsigned r = snap_rng[k][0] + i * 4, v = shamem(r);
            if (v == snap[n]) continue;
            nd++;
            if (nd <= 24 && !snap_quiet) slog("  diff %08x", r, 0), slog("    %08x -> %08x", snap[n], v);
            if (!snap_skip(r)) { eng_out(r, snap[n]); nr++; }
        }
    llh.ndiff = nd; llh.nrestored = nr;
}

static int ch_idle(unsigned base)
{
    int k;
    for (k = 0; k < 20; k++) {
        if (REG(base) != 0) return 0;
        msleep(5);
    }
    return 1;
}

static void ll_test(char *buf, char *res, unsigned bits)
{
    unsigned ll_h = (bits == 14) ? LL_H14 : LL_H, bcode = (bits == 14) ? 2 : 1;
    static unsigned cfg[9] = { 0x23, 0, 9, 0, 0, 0, 0, 1, 0 };
    static unsigned args[19];
    static unsigned list[2];
    unsigned phys = (unsigned)buf & 0x3fffffff, r, t;
    int fd;
    char *p = res + strlen(res);

    memset(&llh, 0, sizeof(llh));
    memcpy(llh.magic, "M10LL003", 8);
    llh.w = LL_W; llh.h = ll_h; llh.bits = bits; llh.out_size_max = LL_OUT_SIZE;

    {
        unsigned x0 = shamem(0xc0f05000), x9 = shamem(0xc0f05204), xr = shamem(0xc0f050f0);
        slog("LL ch23=%08x ch0=%08x", REG(0xc0f26c00), REG(0xc0f04000));
        slog("LL ch9=%08x xbar0=%08x", REG(0xc0f26200), x0);
        slog("LL xbar9=%08x rd_f0=%08x", x9, xr);
        slog("LL 37628=%08x 3763c=%08x", shamem(0xc0f37628), shamem(0xc0f3763c));
        // a connection register holding a channel (bit 31 clear, non-zero) is in use
        if (((x0 & 0x80000000) == 0 && x0) || ((x9 & 0x80000000) == 0 && x9)
            || ((xr & 0x80000000) == 0 && xr)
            || !ch_idle(0xc0f26c00) || !ch_idle(0xc0f04000) || !ch_idle(0xc0f26200)) {
            strcpy(p, "LL: canaux occupes");
            return;
        }
    }
    memset(buf + LL_WR2_OFF, 0, LL_WR2_SIZE);   // v5: WR2 held stale memory
    memset(buf + LL_OUT_OFF, 0, LL_NRUN * LL_OUT_SIZE);
    snap_take();
    ((fn1)FN_LL_INIT)((unsigned)cfg);
    ((fn2)FN_LL_CBR)((unsigned)ll_cbr, 0);
    slog("LL init done", 0, 0);

    for (r = 0; r < LL_NRUN; r++) {
        unsigned out = phys + LL_OUT_OFF + r * LL_OUT_SIZE, u0;
        // run 0: no routing change (v5 behaviour, diagnostic); runs 1-2: Canon
        // CR2 routing row 0 (0xfc205c94(0), as CR2Path does), restored after
        int route = r > 0;
        unsigned char old_route[5];
        llh.off[r] = (r == 0) ? 0 : (r - 1) * 4;
        if (route) {
            memcpy(old_route, (void *)ROUTE_CACHE, 5);
            slog("LL route cache %08x %08x", *(volatile unsigned *)ROUTE_CACHE,
                 *(volatile unsigned char *)(ROUTE_CACHE + 4));
            ((fn1)FN_ROUTE_SET)(0);
            slog("LL route row 0 set, cache %08x", *(volatile unsigned *)ROUTE_CACHE, 0);
        }
        list[0] = out; list[1] = LL_OUT_SIZE;
        memset(args, 0, sizeof(args));
        args[0] = LL_W; args[1] = ll_h; args[2] = phys + llh.off[r];
        args[3] = LL_W; args[4] = 0; args[5] = 0; args[6] = bcode;
        args[7] = phys + LL_WR2_OFF; args[8] = 0; args[9] = 1; args[10] = (unsigned)list;
        args[11] = 0x54; args[12] = 0x3e; args[13] = LL_W; args[14] = ll_h;
        args[15] = 5; args[16] = 0; args[17] = 0; args[18] = LL_HUFF;
        cb_done = 0; cb_st = cb_size = cb_x = 0;

        ((fn0)FN_CR2_LOCK)();
        {   // CR2Path -> 0xfc155352 -> 0xfc427500 -> 0xfc5818a2: Canon constants,
            // per-channel offsets 0 (Canon: clamped values from 0xfc4116a2)
            static unsigned char prm[16] = { 8, 8, 8, 8, 4, 4, 4, 4, 0, 0, 0, 0, 0, 0, 0, 0 };
            static unsigned pa[4];
            pa[0] = 0; pa[1] = (unsigned)prm; pa[2] = 0; pa[3] = 0;
            ((fn1)FN_LL_PARAM)((unsigned)pa);
        }
        slog("LL run %d off %d: setup", r, llh.off[r]);
        ((fn1)FN_LL_SETUP)((unsigned)args);
        slog("LL setup ok, rd 08=%08x", REG(0xc0f26c08), 0);
        u0 = usec();
        ((fn0)FN_LL_START)();
        t = get_tick_count();
        while (!cb_done && get_tick_count() - t < 3000) msleep(2);
        llh.done[r] = cb_done;
        llh.us[r] = cb_done ? udiff(u0, cb_us) : udiff(u0, usec());
        llh.st[r] = cb_st; llh.size[r] = cb_size;
        llh.end_ptr[r] = REG(0xc0f04008);
        llh.jp_st[r] = cb_x;
        llh.jp20[r] = REG(0xc0e00020);
        llh.jp44[r] = REG(0xc0e00044);
        llh.rd_end[r] = REG(0xc0f26c08);
        llh.wr2_end[r] = REG(0xc0f26208);
        slog("   jp cbr code=%08x c0e00020=%08x", cb_x, llh.jp20[r]);
        slog("   c0e00044=%08x c0e00000=%08x", llh.jp44[r], REG(0xc0e00000));
        slog("   rd end=%08x wr2 end=%08x", llh.rd_end[r], llh.wr2_end[r]);
        ((fn0)FN_LL_STOP)();
        ((fn0)FN_CR2_UNLOCK)();
        if (route) {    // re-apply the lists that were active before (cache index per slot)
            unsigned k;
            ((fn1)FN_RES_LOCK)((unsigned)ROUTE_LOCK);
            for (k = 0; k < 5; k++) {
                unsigned o = old_route[k];
                if (o != 0xff && o != *(volatile unsigned char *)(ROUTE_CACHE + k)) {
                    unsigned *e = (unsigned *)(ROUTE_TAB + o * 8);
                    ((fn2)FN_ENGIO_LIST)(e[0], e[1]);
                    *(volatile unsigned char *)(ROUTE_CACHE + k) = (unsigned char)o;
                }
            }
            ((fn1)FN_RES_UNLOCK)((unsigned)ROUTE_LOCK);
            slog("LL route restored, cache %08x", *(volatile unsigned *)ROUTE_CACHE, 0);
        }
        llh.word0[r] = *(volatile unsigned *)(buf + LL_OUT_OFF + r * LL_OUT_SIZE);
        slog("LL done=%d st=%d", llh.done[r], llh.st[r]);
        slog("   size=%d us=%d", llh.size[r], llh.us[r]);
        slog("   word0=%08x wr1 end=%08x", llh.word0[r], llh.end_ptr[r]);
        p += sprintf(p, "LL%d:%s %dK %dms ", r, cb_done ? (cb_st == 0 ? "ok" : "st") : "TMO",
                     llh.size[r] / 1024, llh.us[r] / 1000);
        llh.nruns = r + 1;
        if (!cb_done) break;            // a hung encoder ends the session
        msleep(100);
    }
    snap_restore();
    slog("LL regs diff %d restored %d", llh.ndiff, llh.nrestored);

    fd = open("A/M10LL.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (fd >= 0) {
        write(fd, &llh, sizeof(llh));
        for (r = 0; r < llh.nruns; r++) {
            unsigned n = llh.size[r];
            if (n == 0 || n > LL_OUT_SIZE) n = LL_OUT_SIZE;
            write(fd, buf + LL_OUT_OFF + r * LL_OUT_SIZE, n);
        }
        write(fd, buf + LL_WR2_OFF, LL_WR2_SIZE);
        close(fd);
    }
    slog("LL file written", 0, 0);
}

// ---------------------------------------------------------------------------
// v8: which 14-bit packing does the encoder read? (probe43: real PACK32 frame
// -> 6.6 MB of JPEG for 4.2 MB in, i.e. it saw noise.) A smooth synthetic
// Bayer gradient is packed in NLAY candidate layouts; the right layout gives
// a tiny output. Output buffer per run 3 MB (no wrap), EOI-terminated.
// ---------------------------------------------------------------------------
#define SY_H        256
#define SY_IN_OFF   0x00000000
#define SY_WR2_OFF  0x00180000
#define SY_OUT_OFF  0x00200000
#define SY_OUT_SIZE 0x00300000
#define NLAY        4

static unsigned sy_val(unsigned x, unsigned y)
{
    // per Bayer channel smooth ramps, 14-bit, black ~2048
    unsigned c = ((y & 1) << 1) | (x & 1);
    return 2048 + c * 700 + (x >> 1) * 2 + (y >> 1) * 3;
}

// write w*h samples of n bits in layout lay at dst
//  0: PACK32 2-stream (even u16 words = even px, odd = odd px), MSB first
//  1: single stream, MSB first inside u16 little-endian words (ML DIGIC 5)
//  2: single stream, MSB first byte order (big-endian bitstream)
//  3: single stream, LSB first (little-endian bitstream)
static void sy_pack(unsigned char *dst, unsigned lay, unsigned w, unsigned h, unsigned n)
{
    unsigned y, x, s;
    if (lay == 0) {
        unsigned short *o = (unsigned short *)dst;
        for (s = 0; s < 2; s++) {
            unsigned acc = 0, nb = 0, wi = 0;
            for (y = 0; y < h; y++)
                for (x = s; x < w; x += 2) {
                    acc = (acc << n) | sy_val(x, y); nb += n;
                    while (nb >= 16) { nb -= 16; o[2 * wi + s] = (unsigned short)(acc >> nb); wi++; }
                }
            if (nb) o[2 * wi + s] = (unsigned short)(acc << (16 - nb));
        }
    } else if (lay == 1 || lay == 2) {
        unsigned acc = 0, nb = 0, wi = 0;
        for (y = 0; y < h; y++)
            for (x = 0; x < w; x++) {
                acc = (acc << n) | sy_val(x, y); nb += n;
                while (nb >= 16) {
                    unsigned v;
                    nb -= 16; v = (acc >> nb) & 0xffff;
                    if (lay == 1) { dst[2 * wi] = v & 0xff; dst[2 * wi + 1] = v >> 8; }
                    else          { dst[2 * wi] = v >> 8;   dst[2 * wi + 1] = v & 0xff; }
                    wi++;
                }
            }
    } else {
        unsigned long long acc = 0; unsigned nb = 0, bi = 0;
        for (y = 0; y < h; y++)
            for (x = 0; x < w; x++) {
                acc |= (unsigned long long)sy_val(x, y) << nb; nb += n;
                while (nb >= 8) { dst[bi++] = (unsigned char)acc; acc >>= 8; nb -= 8; }
            }
        if (nb) dst[bi] = (unsigned char)acc;
    }
}

typedef struct {
    char     magic[8];      // "M10SYN01"
    unsigned w, h, bits, nlay;
    unsigned size[NLAY], st[NLAY], us[NLAY], done[NLAY], wr1_end[NLAY], rd_end[NLAY];
    unsigned jp20[NLAY], pack_ms[NLAY];
} sy_hdr;
static sy_hdr syh;

static void __attribute__((unused)) syn_test(char *buf, char *res)
{
    static unsigned cfg[9] = { 0x23, 0, 9, 0, 0, 0, 0, 1, 0 };
    static unsigned args[19];
    static unsigned list[2];
    unsigned phys = (unsigned)buf & 0x3fffffff, lay, t, bits = 14, lb = FRAME_W * 14 / 8;
    char *p = res;
    int fd;

    memset(&syh, 0, sizeof(syh));
    memcpy(syh.magic, "M10SYN01", 8);
    syh.w = FRAME_W; syh.h = SY_H; syh.bits = bits; syh.nlay = NLAY;
    if (!ch_idle(0xc0f26c00) || !ch_idle(0xc0f04000) || !ch_idle(0xc0f26200)) {
        strcpy(p, "SY: canaux occupes"); return;
    }
    memset(buf + SY_WR2_OFF, 0, SY_OUT_OFF - SY_WR2_OFF);
    memset(buf + SY_OUT_OFF, 0, NLAY * SY_OUT_SIZE);
    snap_take();
    ((fn1)FN_LL_INIT)((unsigned)cfg);
    ((fn2)FN_LL_CBR)((unsigned)ll_cbr, 0);
    slog("SY init done", 0, 0);

    for (lay = 0; lay < NLAY; lay++) {
        unsigned out = phys + SY_OUT_OFF + lay * SY_OUT_SIZE, u0;
        t = get_tick_count();
        memset(buf + SY_IN_OFF, 0, lb * SY_H + 16);
        sy_pack((unsigned char *)buf + SY_IN_OFF, lay, FRAME_W, SY_H, bits);
        syh.pack_ms[lay] = get_tick_count() - t;
        list[0] = out; list[1] = SY_OUT_SIZE;
        memset(args, 0, sizeof(args));
        args[0] = FRAME_W; args[1] = SY_H; args[2] = phys + SY_IN_OFF;
        args[3] = FRAME_W; args[6] = 2;
        args[7] = phys + SY_WR2_OFF; args[9] = 1; args[10] = (unsigned)list;
        args[11] = 0x54; args[12] = 0x3e; args[13] = FRAME_W; args[14] = SY_H;
        args[15] = 5; args[18] = LL_HUFF;
        cb_done = 0; cb_st = cb_size = cb_x = 0;

        ((fn0)FN_CR2_LOCK)();
        {
            static unsigned char prm[16] = { 8, 8, 8, 8, 4, 4, 4, 4, 0, 0, 0, 0, 0, 0, 0, 0 };
            static unsigned pa[4];
            pa[0] = 0; pa[1] = (unsigned)prm; pa[2] = 0; pa[3] = 0;
            ((fn1)FN_LL_PARAM)((unsigned)pa);
        }
        ((fn1)FN_LL_SETUP)((unsigned)args);
        u0 = usec();
        ((fn0)FN_LL_START)();
        t = get_tick_count();
        while (!cb_done && get_tick_count() - t < 3000) msleep(2);
        syh.done[lay] = cb_done;
        syh.us[lay] = cb_done ? udiff(u0, cb_us) : udiff(u0, usec());
        syh.st[lay] = cb_st; syh.size[lay] = cb_size;
        syh.wr1_end[lay] = REG(0xc0f04008) - out;
        syh.rd_end[lay] = REG(0xc0f26c08) - (phys + SY_IN_OFF);
        syh.jp20[lay] = REG(0xc0e00020);
        ((fn0)FN_LL_STOP)();
        ((fn0)FN_CR2_UNLOCK)();
        slog("SY lay %d done=%d", lay, cb_done);
        slog("   st=%d size=%d", cb_st, cb_size);
        slog("   us=%d pack_ms=%d", syh.us[lay], syh.pack_ms[lay]);
        slog("   wr1=%x rd=%x", syh.wr1_end[lay], syh.rd_end[lay]);
        p += sprintf(p, "L%d:%s %dK ", lay, cb_done ? (cb_st == 2 ? "ok" : "st") : "TMO", cb_size / 1024);
        if (!cb_done) break;
        msleep(100);
    }
    snap_restore();
    slog("SY regs diff %d restored %d", llh.ndiff, llh.nrestored);

    fd = open("A/M10SYN.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (fd >= 0) {
        write(fd, &syh, sizeof(syh));
        for (lay = 0; lay < NLAY; lay++) {
            unsigned n = syh.size[lay];
            if (n == 0 || n > SY_OUT_SIZE) n = SY_OUT_SIZE;
            write(fd, &n, 4);
            write(fd, buf + SY_OUT_OFF + lay * SY_OUT_SIZE, n);
        }
        close(fd);
    }
    slog("SY file written", 0, 0);
}

// ---------------------------------------------------------------------------
// v10 "VID": continuous loop capture -> hardware lossless -> card write.
// Each frame repeats the proven probe46 sequence exactly (PACK32 pack 2,
// 14-bit, CH12 2-D capture; then one encoder pass, snap/restore per frame).
// Window 2592 x VID_H (924 lines, one encoder block < 4 MiB, ~2.39 Mpx).
// Writes a container A/M10CINE.VID: 64-byte global header, then per frame
// a 20-byte record {"VIDF", size, cap_us, enc_us, phase | phase_us << 8}
// + the JPEG bytes. The input bit phase is found per frame (find_phase).
// Measures cap/enc/write per frame and the sustained + pipelined rate.
// NF frames read from A/M10V.CFG (default 20, max 120).
// ---------------------------------------------------------------------------
#define VID_W      FRAME_W
#define VID_H      924
#define VID_BITS   14
#define VID_LB     (VID_W * VID_BITS / 8)       // 4536
#define VID_BLK    462                          // 2 blocks of 462 lines, < 4 MiB
#define VID_IN_OFF   0x00000000
#define VID_WR2_OFF  0x00480000
#define VID_WR2_SIZE 0x00080000
#define VID_OUT_OFF  0x00500000
#define VID_OUT_SIZE 0x00300000                 // 3 MB per frame, guarded
#define VID_NF_DEF   20
#define VID_NF_MAX   120

typedef struct {
    char     magic[8];      // "M10VID01"
    unsigned w, h, bits, nf_planned;
    unsigned fb_in;                     // input frame bytes
    unsigned nf_done, total_ms;
    unsigned sum_cap, sum_enc, sum_wr;  // microseconds summed
    unsigned cap_min, cap_max, enc_min, enc_max, wr_min, wr_max;
    unsigned real_fps_x100;             // nf_done / total wall
    unsigned pipe2_fps_x100;            // 1 / max(cap, enc+wr)   (2 workers)
    unsigned pipe3_fps_x100;            // 1 / max(cap, enc, wr)  (3 workers)
    unsigned pad[2];        // [0] frames with phase != 0, [1] max phase-search us
} vid_hdr;
static vid_hdr vhd;

// capture one VID_H-line 14-bit pack-2 frame into buf+VID_IN_OFF.
// returns 1 ok, 0 stall, -1 setup error. CH12 fully released on return.
static unsigned last_cap;
static unsigned cap_in_off = VID_IN_OFF;        // v12: input buffer offset
static int cap_frame(char *buf, unsigned phys)
{
    unsigned i, last = VID_H - VID_BLK, dt, st, off, s14, s74;
    int ok = 1;

    // v11: full idle check (ch12_idle, ~200 ms) only before the loop; here a
    // single read (probe48: per-frame polling cost ~800 ms per frame)
    if (shamem(CH12_XBAR) != 0x80000000 || REG(CH12_BASE) != 0) return -1;
    ((fn1)FN_RES_LOCK)((unsigned)reslist);
    for (i = 0; i < NCHREGS; i++) chsaved[i] = shamem(CH12_BASE + chregs[i]);
    if (((fn0)FN_PK_TAKE)() != 0) { ((fn1)FN_RES_UNLOCK)((unsigned)reslist); return -1; }
    s14 = shamem(0xc0f37014);
    s74 = shamem(0xc0f37074);
    for (i = 0; i < NPK; i++) pk_saved[i] = shamem(pk_regs[i]);
    ch12_flags = 0x40000000;
    ((fn2)FN_PK_ON)(VID_BITS, 2);               // pack 2 -> single stream

    eng_out(CH12_XBAR, 0x00);
    // one 2-D transfer, two blocks (VID_BLK + last), each < 4 MiB
    eng_out(CH12_BASE + 0x40, 0);
    eng_out(CH12_BASE + 0x04, ch12_flags);
    eng_out(CH12_BASE + 0x08, phys + cap_in_off);
    eng_out(CH12_BASE + 0x0c, 1 << 16);
    eng_out(CH12_BASE + 0x14, ((VID_BLK - 1) << 16) | VID_LB);
    eng_out(CH12_BASE + 0x10, ((last - 1) << 16) | VID_LB);
    for (off = 0x18; off <= 0x28; off += 4) eng_out(CH12_BASE + off, 0);
    st = ch12_run(&dt);
    last_cap = dt;
    vhd.sum_cap += dt;
    if (dt < vhd.cap_min) vhd.cap_min = dt;
    if (dt > vhd.cap_max) vhd.cap_max = dt;
    if (st) ok = 0;
    if (!ch12_stop()) ok = -1;

    ((fn0)FN_PK_OFF)();
    // v12: masked restore of the fields PACK32 on writes (0x37014[5:0],
    // 0x37074[27:24]); the encoder, possibly running, owns other bits
    ((fn3)FN_ENGDRV_MASK)(0xc0f37014, ~0x3fu, s14 & 0x3f);
    ((fn3)FN_ENGDRV_MASK)(0xc0f37074, ~0x0f000000u, s74 & 0x0f000000);
    for (i = 0; i < NPK; i++) eng_out(pk_regs[i], pk_saved[i]);   // incl. 8094 (bpp)
    for (i = 0; i < NCHREGS; i++) eng_out(CH12_BASE + chregs[i], chsaved[i]);
    ((fn1)FN_RES_UNLOCK)((unsigned)reslist);
    return ok;
}

// The DMA starts anywhere in the PACK32 stream: with 32-bit units the first
// 14-bit sample begins at a bit offset multiple of 16 (mod 112 = 8 samples),
// i.e. at one of 7 byte offsets 0, 4, ... 24 (probe46: 0, probe47: 8).
// The right offset makes neighbouring same-colour samples smooth: score =
// sum |s[i+2] - s[i]| over 256 samples of a middle line, smallest wins.
static unsigned vid_score[7];
static unsigned find_phase_at(const char *buf, unsigned off);
static unsigned enc_in_off = VID_IN_OFF;       // v12: input buffer of the encoder / phase search
static unsigned get14(const unsigned char *d, unsigned bit)
{
    unsigned k = (bit >> 4) << 1, sh = bit & 15;
    unsigned v = ((unsigned)(d[k] | (d[k + 1] << 8)) << 16) | (d[k + 2] | (d[k + 3] << 8));
    return (v >> (18 - sh)) & 0x3fff;
}
static unsigned find_phase_at(const char *buf, unsigned off)
{
    const unsigned char *d = (const unsigned char *)buf + off;
    unsigned j, i, best = 0, base = VID_LB * (VID_H / 2) * 8;   // bit, multiple of 112
    for (j = 0; j < 7; j++) {
        unsigned b0 = base + 32 * j, prev2 = get14(d, b0), prev1 = get14(d, b0 + 14), sc = 0;
        for (i = 2; i < 258; i++) {
            unsigned s = get14(d, b0 + 14 * i);
            sc += (s > prev2) ? s - prev2 : prev2 - s;
            prev2 = prev1; prev1 = s;
        }
        vid_score[j] = sc;
        if (sc < vid_score[best]) best = j;
    }
    return best * 4;
}

// compress buf+VID_IN_OFF+in_off (VID_H lines) -> buf+VID_OUT_OFF. one pass,
// no routing (probe46: pass 0 works). returns JPEG size, 0 on error/timeout.
static unsigned enc_out_off = VID_OUT_OFF;     // v11: output slot offset
static unsigned enc_out_size = VID_OUT_SIZE;   // v12: output slot size
static unsigned enc_wr2_off = VID_WR2_OFF;     // v12: WR2 (preview) area
static unsigned enc_w = VID_W, enc_h = VID_H;   // v15: encoder geometry
static int enc_no_snap = 0;                    // v12: no per-frame snap (capture may run)
static unsigned enc_bits = 2;                  // v92: encoder input depth code (1 = 12-bit, 2 = 14-bit)
// v95: LosslessEncode's own RD1 EDMAC / unpacker accept a 10-bit input (depth code 0: 0xfc581e30
// uses 10 bits, unpacker 0xc0f371fc = depth << 4), only JpCore (0xfc58228a) insists on 12/14.
// enc_rd10: set up as 14-bit, then redo the RD1 EDMAC (0xfc581e30, depth 0) and the unpacker.
static unsigned enc_rd10 = 0, enc_unpk = 0, enc_prec = 0, enc_9c = 0;
static unsigned enc_rd12 = 0;   // v177: RD1 depth code 1 (12-bit source) in REC
static unsigned enc_mode = 1;   // v130
static unsigned lj_rdf = 0;    // v147: 52nd field = RD1 transfer-size flag bits (hex)
static unsigned lj_ebits = 0;   // v146: 51st field = encoder depth code override (1 = P12, 2 = P14), 0 = default
static unsigned lj_u371 = 0;   // v145: 50th field = raw c0f371fc value written last in enc_begin (REC), 0 = keep
static unsigned enc_prm_a = 0, enc_prm_b = 0, enc_wov = 0, enc_rdb = 0, enc_wstride = 0;   // v134, v135: stride = width (timing test)   // v133: enc_wov = encoder width override (px)   // v132: FN_LL_PARAM bytes (0 = Canon 8/4)
static unsigned x_rowm = 1;     // v131: CH12 lines per EDMAC row (39th field): cfg[7] (1 = Taiwan path, CR2.c)
static unsigned x_jpn = 0, x_jpo[12], x_jpv[12];   // v99 (v129: 12 pokes)
static unsigned enc_wr1 = 0, enc_wr2 = 9, enc_rd = 0x23, lj_eh = 0, enc_w2w = 0, enc_w2h = 0;   // v110
static unsigned x_epn = 0, x_epa[4], x_epv[4], x_epm[4], enc_f_rd = 0, enc_f_wr = 0;   // v111: engine pokes after setup (addr, value, mode 0 = set, 1 = OR)   // v107: lj_eh = encoder lines (test, 0 = frame)   // v104, v106: read channel (0x23 = c0f26c00, Canon-armed in Film): encoder write channels (CR2.c: 0 and 9; CH9 is busy in Film LV)
static unsigned enc_huff[24] __attribute__((aligned(32))), enc_huff_ok = 0;   // v100: A/M10HUF.BIN (2 x BITS[16] + HUFFVAL[32])   // v96: enc_prec != 0 -> JpCore precision reg c0e00010 (SOF3 P)
typedef unsigned (*fn7)(unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned);
#define FN_LL_RD1      0xfc581e31
#define LL_UNPACK_REG  0xc0f371fc
static unsigned rd_base(unsigned ch)   // v106: read EDMAC index (25..47) -> base
{
    static const unsigned rb[23] = { 0xc0f04800, 0xc0f04900, 0xc0f04a00, 0xc0f04b00, 0xc0f04c00, 0xc0f04d00,
        0xc0f26800, 0xc0f26900, 0xc0f26a00, 0xc0f26b00, 0xc0f26c00, 0xc0f26d00,
        0xc0f30800, 0xc0f30900, 0xc0f30a00, 0xc0f30b00, 0xc0f30c00, 0xc0f30d00,
        0xc0f57800, 0xc0f57900, 0xc0f57a00, 0xc0f58800, 0xc0f58900 };
    return (ch >= 25 && ch <= 47) ? rb[ch - 25] : 0xc0f26c00;
}
static unsigned x_w;   // v157: tentative (defined with the lv_x3 state below): source stride of the 10-bit reader
static unsigned enc_frame(char *buf, unsigned phys, unsigned in_off, unsigned *enc_us)
{
    static unsigned cfg[9] = { 0x23, 0, 9, 0, 0, 0, 0, 1, 0 };
    cfg[0] = enc_rd; cfg[1] = enc_wr1; cfg[2] = enc_wr2; cfg[7] = enc_mode;   // v104, v106, v130
    static unsigned args[19];
    static unsigned list[2];
    static unsigned char prm[16] = { 8, 8, 8, 8, 4, 4, 4, 4, 0, 0, 0, 0, 0, 0, 0, 0 };
    if (enc_prm_a) { unsigned q; for (q = 0; q < 4; q++) { prm[q] = enc_prm_a; prm[4 + q] = enc_prm_b; } }   // v132
    static unsigned pa[4];
    unsigned out = phys + enc_out_off, u0, t, sz;

    (void)buf;
    // full ch_idle() check done once before the loop (v11)
    if (REG(rd_base(enc_rd)) != 0 || REG(0xc0f04000 + 0x100 * enc_wr1) != 0 || (enc_wr2 == 9 && REG(0xc0f26200) != 0)) return 0;   // v104, v106
    if (!enc_no_snap) snap_take();
    ((fn1)FN_LL_INIT)((unsigned)cfg);
    ((fn2)FN_LL_CBR)((unsigned)ll_cbr, 0);

    list[0] = out; list[1] = enc_out_size;
    memset(args, 0, sizeof(args));
    args[0] = enc_w; args[1] = enc_h; args[2] = phys + enc_in_off + in_off;
    args[3] = (enc_wov && !enc_wstride) ? x_w : enc_w; args[6] = enc_bits;
    args[7] = phys + enc_wr2_off; args[9] = 1; args[10] = (unsigned)list;
    args[11] = 0x54; args[12] = 0x3e; args[13] = enc_w2w ? enc_w2w : enc_w; args[14] = enc_w2h ? enc_w2h : enc_h;   // v110: WR2 (preview) size
    args[15] = 5; args[18] = enc_huff_ok ? (unsigned)enc_huff : LL_HUFF;   // v100
    cb_done = 0; cb_st = cb_size = cb_x = 0;

    ((fn0)FN_CR2_LOCK)();
    pa[0] = 0; pa[1] = (unsigned)prm; pa[2] = 0; pa[3] = 0;
    ((fn1)FN_LL_PARAM)((unsigned)pa);
    ((fn1)FN_LL_SETUP)((unsigned)args);
    if (enc_rd10) {                     // v95: hardware 10-bit unpack
        static unsigned geo[6];
        geo[0] = 0; geo[1] = enc_w; geo[2] = 0; geo[3] = 0; geo[4] = enc_h; geo[5] = 0;
        ((fn7)FN_LL_RD1)((unsigned)geo, (enc_wov && !enc_wstride) ? x_w : enc_w, enc_h, 0, 0, enc_rd12 ? 1 : 0, phys + enc_in_off + in_off);   // v177: depth code 1 = 12-bit source   // v133: source stride
        if (enc_rdb == 1) ((fn1)0xfc3759ab)(enc_rd); else if (enc_rdb == 2) ((fn1)0xfc3759c3)(enc_rd); else if (enc_rdb == 3) ((fn1)0xfc3759db)(enc_rd);
        if (lj_rdf) { unsigned fa = rd_base(enc_rd) + 4; eng_out(fa, (shamem(fa) & ~0x60001000u) | lj_rdf); }   // v147: raw RD1 transfer-size bits (0x20001000 = 8 B, 0x40001000 = 16 B)   // v134: Canon burst setters (4 B / 0x1000 / 16 B), after RD1 programming
        eng_out(LL_UNPACK_REG, enc_unpk);
        if (enc_prec) *(volatile unsigned *)0xc0e00084 = 0x200 | enc_prec;   // v98: JpCore precision (0xfc511e58: c0e00084 = P | 0x200; c0e00010 = marker codes)
        { unsigned i; for (i = 0; i < x_jpn; i++) *(volatile unsigned *)(0xc0e00000 + x_jpo[i]) = x_jpv[i]; }   // v99: JpCore register pokes (23rd field)
    }
    enc_f_rd = shamem(rd_base(enc_rd) + 4); enc_f_wr = shamem(0xc0f04000 + 0x100 * enc_wr1 + 4);   // v111
    { unsigned i; for (i = 0; i < x_epn; i++) eng_out(x_epa[i], x_epm[i] ? (shamem(x_epa[i]) | x_epv[i]) : x_epv[i]); }   // v111
    {
    }
    u0 = usec();
    ((fn0)FN_LL_START)();
    t = get_tick_count();
    if (sem_enc) {
        while (!cb_done && get_tick_count() - t < 3000) TakeSemaphore(sem_enc, 100);
    } else {
        while (!cb_done && get_tick_count() - t < 3000) msleep(2);
    }
    *enc_us = cb_done ? udiff(u0, cb_us) : udiff(u0, usec());
    sz = cb_size;
    ((fn0)FN_LL_STOP)();
    ((fn0)FN_CR2_UNLOCK)();
    if (!enc_no_snap) snap_restore();
    if (!cb_done || cb_st != 0 || sz == 0 || sz > enc_out_size) return 0;
    return sz;
}
static unsigned enc_u0;   // v125
static unsigned enc_rdg[9];   // v181b
static unsigned enc_begin(char *buf, unsigned phys, unsigned in_off)
{
    static unsigned cfg[9] = { 0x23, 0, 9, 0, 0, 0, 0, 1, 0 };
    cfg[0] = enc_rd; cfg[1] = enc_wr1; cfg[2] = enc_wr2; cfg[7] = enc_mode;   // v104, v106, v130
    static unsigned args[19];
    static unsigned list[2];
    static unsigned char prm[16] = { 8, 8, 8, 8, 4, 4, 4, 4, 0, 0, 0, 0, 0, 0, 0, 0 };
    if (enc_prm_a) { unsigned q; for (q = 0; q < 4; q++) { prm[q] = enc_prm_a; prm[4 + q] = enc_prm_b; } }   // v132
    static unsigned pa[4];
    unsigned out = phys + enc_out_off;

    (void)buf;
    // full ch_idle() check done once before the loop (v11)
    if (REG(rd_base(enc_rd)) != 0 || REG(0xc0f04000 + 0x100 * enc_wr1) != 0 || (enc_wr2 == 9 && REG(0xc0f26200) != 0)) return 0;   // v104, v106
    if (!enc_no_snap) snap_take();
    ((fn1)FN_LL_INIT)((unsigned)cfg);
    ((fn2)FN_LL_CBR)((unsigned)ll_cbr, 0);

    list[0] = out; list[1] = enc_out_size;
    memset(args, 0, sizeof(args));
    args[0] = enc_w; args[1] = enc_h; args[2] = phys + enc_in_off + in_off;
    args[3] = (enc_wov && !enc_wstride) ? x_w : enc_w; args[6] = enc_bits;
    args[7] = phys + enc_wr2_off; args[9] = 1; args[10] = (unsigned)list;
    args[11] = 0x54; args[12] = 0x3e; args[13] = enc_w2w ? enc_w2w : enc_w; args[14] = enc_w2h ? enc_w2h : enc_h;   // v110: WR2 (preview) size
    args[15] = 5; args[18] = enc_huff_ok ? (unsigned)enc_huff : LL_HUFF;   // v100
    cb_done = 0; cb_st = cb_size = cb_x = 0;

    ((fn0)FN_CR2_LOCK)();
    pa[0] = 0; pa[1] = (unsigned)prm; pa[2] = 0; pa[3] = 0;
    ((fn1)FN_LL_PARAM)((unsigned)pa);
    ((fn1)FN_LL_SETUP)((unsigned)args);
    if (enc_rd10) {                     // v95: hardware 10-bit unpack
        static unsigned geo[6];
        geo[0] = 0; geo[1] = enc_w; geo[2] = 0; geo[3] = 0; geo[4] = enc_h; geo[5] = 0;
        ((fn7)FN_LL_RD1)((unsigned)geo, (enc_wov && !enc_wstride) ? x_w : enc_w, enc_h, 0, 0, enc_rd12 ? 1 : 0, phys + enc_in_off + in_off);   // v177: depth code 1 = 12-bit source   // v133: source stride
        if (enc_rdb == 1) ((fn1)0xfc3759ab)(enc_rd); else if (enc_rdb == 2) ((fn1)0xfc3759c3)(enc_rd); else if (enc_rdb == 3) ((fn1)0xfc3759db)(enc_rd);
        if (lj_rdf) { unsigned fa = rd_base(enc_rd) + 4; eng_out(fa, (shamem(fa) & ~0x60001000u) | lj_rdf); }   // v147: raw RD1 transfer-size bits (0x20001000 = 8 B, 0x40001000 = 16 B)   // v134: Canon burst setters (4 B / 0x1000 / 16 B), after RD1 programming
        eng_out(LL_UNPACK_REG, enc_unpk);
        if (enc_prec) *(volatile unsigned *)0xc0e00084 = 0x200 | enc_prec;   // v98: JpCore precision (0xfc511e58: c0e00084 = P | 0x200; c0e00010 = marker codes)
        { unsigned i; for (i = 0; i < x_jpn; i++) *(volatile unsigned *)(0xc0e00000 + x_jpo[i]) = x_jpv[i]; }   // v99: JpCore register pokes (23rd field)
    }
    enc_f_rd = shamem(rd_base(enc_rd) + 4); enc_f_wr = shamem(0xc0f04000 + 0x100 * enc_wr1 + 4);   // v111
    { unsigned i; for (i = 0; i < x_epn; i++) eng_out(x_epa[i], x_epm[i] ? (shamem(x_epa[i]) | x_epv[i]) : x_epv[i]); }   // v111
    if (enc_rd10 && lj_u371) eng_out(LL_UNPACK_REG, lj_u371);   // v145: raw unpacker value for REC encodes
    { unsigned i, b = rd_base(enc_rd); for (i = 0; i < 9; i++) enc_rdg[i] = shamem(b + 4 * i); }   // v181b: RD1 geometry as programmed (+0x00..+0x20)
    enc_u0 = usec();
    ((fn0)FN_LL_START)();
    return 1;
}
static unsigned enc_end(unsigned *enc_us)   // v125: wait for the CBR, stop, unlock
{
    unsigned t = get_tick_count(), sz;
    while (!cb_done && get_tick_count() - t < 3000) msleep(1);
    *enc_us = cb_done ? udiff(enc_u0, cb_us) : udiff(enc_u0, usec());
    sz = cb_size;
    ((fn0)FN_LL_STOP)();
    ((fn0)FN_CR2_UNLOCK)();
    if (!enc_no_snap) snap_restore();
    if (!cb_done || cb_st != 0 || sz == 0 || sz > enc_out_size) return 0;
    return sz;
}

static void __attribute__((unused)) grab_v10(void)   // v10 sequential loop (probe48)
{
    exmem_alloc_info ai;
    char *buf;
    unsigned phys, nf = VID_NF_DEF, i, t_wall;
    int fd, cfd, ok = 1;
    char hdrb[24];

    msg[0] = 0;
    slog("v10 start 6804=%08x 8094=%08x", shamem(0xc0f06804), shamem(PACK32_MODE));
    if (shamem(0xc0f06804) == 0 || *(volatile unsigned *)DSS_FLAGS == 0) { sprintf(msg, "LV inactive"); return; }
    if (shamem(0xc0f06804) != 0x045702a6) { sprintf(msg, "pas en zoom x5"); return; }

    cfd = open("A/M10V.CFG", O_RDONLY, 0777);
    if (cfd >= 0) { char c[8]; int n = read(cfd, c, 7); close(cfd); if (n > 0) { c[n] = 0; nf = strtol(c, 0, 10); } }
    if (nf < 1) nf = VID_NF_DEF;
    if (nf > VID_NF_MAX) nf = VID_NF_MAX;

    buf = exmem_alloc_uncached(EXMEM_TYPE, EXMEM_SIZE, &ai);
    if (!buf) { sprintf(msg, "EXMEM refuse"); return; }
    phys = (unsigned)buf & 0x3fffffff;

    memset(&vhd, 0, sizeof(vhd));
    memcpy(vhd.magic, "M10VID01", 8);
    vhd.w = VID_W; vhd.h = VID_H; vhd.bits = VID_BITS; vhd.nf_planned = nf;
    vhd.fb_in = VID_LB * VID_H;
    vhd.cap_min = vhd.enc_min = vhd.wr_min = 0xffffffff;

    fd = open("A/M10CINE.VID", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (fd < 0) { exmem_free_uncached(EXMEM_TYPE); sprintf(msg, "VID open err"); return; }
    write(fd, &vhd, sizeof(vhd));           // placeholder, rewritten at end

    snap_quiet = 1;
    t_wall = get_tick_count();
    for (i = 0; i < nf; i++) {
        unsigned enc_us = 0, wr_us, tw, sz, ph, ph_us;
        int r = cap_frame(buf, phys);
        if (i < 3) slog("v10 f%d cap=%d", i, last_cap);
        if (r <= 0) { ok = 0; sprintf(msg, "cap %s f%d", r == 0 ? "STALL" : "err", i); break; }
        tw = usec();
        ph = find_phase_at(buf, enc_in_off);
        ph_us = udiff(tw, usec());
        if (ph) vhd.pad[0]++;
        if (ph_us > vhd.pad[1]) vhd.pad[1] = ph_us;
        sz = enc_frame(buf, phys, ph, &enc_us);
        if (sz == 0) { ok = 0; sprintf(msg, "enc err f%d st=%d", i, cb_st); break; }
        vhd.sum_enc += enc_us;
        if (enc_us < vhd.enc_min) vhd.enc_min = enc_us;
        if (enc_us > vhd.enc_max) vhd.enc_max = enc_us;

        tw = usec();
        memcpy(hdrb, "VIDF", 4);
        *(unsigned *)(hdrb + 4) = sz;
        *(unsigned *)(hdrb + 8) = last_cap;
        *(unsigned *)(hdrb + 12) = enc_us;
        *(unsigned *)(hdrb + 16) = ph | (ph_us << 8);
        write(fd, hdrb, 20);
        write(fd, buf + VID_OUT_OFF, sz);
        wr_us = udiff(tw, usec());
        vhd.sum_wr += wr_us;
        if (wr_us < vhd.wr_min) vhd.wr_min = wr_us;
        if (wr_us > vhd.wr_max) vhd.wr_max = wr_us;
        vhd.nf_done = i + 1;
        if (i < 3) {
            slog("   phase=%d (%d us)", ph, ph_us);
            slog("   enc=%d sz=%d", enc_us, sz);
            slog("   wr=%d us ndiff=%d", wr_us, llh.ndiff);
        }
        if (shamem(0xc0f06804) != 0x045702a6) { sprintf(msg, "zoom perdu f%d", i); break; }
    }
    vhd.total_ms = get_tick_count() - t_wall;
    snap_quiet = 0;

    if (vhd.nf_done) {
        unsigned nd = vhd.nf_done;
        unsigned mc = vhd.sum_cap / nd, me = vhd.sum_enc / nd, mw = vhd.sum_wr / nd;
        unsigned p2 = (me + mw > mc) ? (me + mw) : mc;
        unsigned p3 = mc; if (me > p3) p3 = me; if (mw > p3) p3 = mw;
        if (vhd.total_ms) vhd.real_fps_x100 = nd * 100000 / vhd.total_ms;
        if (p2) vhd.pipe2_fps_x100 = 100000000 / p2;
        if (p3) vhd.pipe3_fps_x100 = 100000000 / p3;
        slog("v10 cap=%d enc=%d", mc, me);
        slog("v10 wr=%d real=%d", mw, vhd.real_fps_x100);
        slog("v10 pipe2=%d pipe3=%d", vhd.pipe2_fps_x100, vhd.pipe3_fps_x100);
        sprintf(msg, "%d/%d %s real=%d.%02d pipe=%d.%02d i/s", nd, nf, ok ? "ok" : "arret",
                vhd.real_fps_x100 / 100, vhd.real_fps_x100 % 100,
                vhd.pipe2_fps_x100 / 100, vhd.pipe2_fps_x100 % 100);
    }
    lseek(fd, 0, SEEK_SET);
    write(fd, &vhd, sizeof(vhd));
    close(fd);
    exmem_free_uncached(EXMEM_TYPE);
    slog("v10 done nf=%d ms=%d", vhd.nf_done, vhd.total_ms);
}

// ---------------------------------------------------------------------------
// v11: producer (this task) = capture -> phase -> encode into one of NSLOT
// output slots; writer task (higher priority, mostly blocked in write())
// writes slots in order. Ring of 3 slots x 3 MB after the input buffer.
// File A/M10CINE.VID, format M10VID02 (all sector aligned):
//   2048-byte header block (v11_hdr, per-frame tick_ms[] and wr_us[]),
//   then per frame a 512-byte record header {"VIDF", size, cap_us, enc_us,
//   phase, phase_us, tick_ms, index} + JPEG padded to a multiple of 512.
// ---------------------------------------------------------------------------
#define V11_NSLOT    3
#define V11_SLOT_OFF 0x00500000
#define V11_SLOT_SZ  0x00300000                 // 0x500000 + 3 * 3 MB = 0xe00000 < 16 MB
#define V11_NF_DEF   60
#define V11_NF_MAX   240
#define V11_HDR_BLK  4096                       // v12 (v11 files: 2048, read from header)
#define V11_REC_BLK  512

typedef struct {
    char     magic[8];      // "M10VID02"
    unsigned w, h, bits, nf_planned, fb_in;
    unsigned nf_done, nf_written, total_ms, prod_ms;
    unsigned sum_cap, sum_enc, sum_wr;
    unsigned cap_min, cap_max, enc_min, enc_max, wr_min, wr_max;
    unsigned real_fps_x100, prod_fps_x100;
    unsigned nslot, max_backlog, werr, nphase_nz, ph_us_max, wait_ms;
    unsigned hdr_blk, rec_blk;
    unsigned tick_ms[V11_NF_MAX];   // capture start of each frame (ms, from loop start)
    unsigned wr_us[V11_NF_MAX];     // write duration of each frame
    // v12 additions
    unsigned version, nf_encoded, cap_wait_ms, ndiff, nrestored, enc_st;
    // v13 additions
    unsigned ivl_us[V11_NF_MAX];    // capture start N-1 -> capture start N (us)
    unsigned stage_us[V11_NF_MAX];  // encoder stage: setup + encode + stop (us)
    unsigned prealloc_ms, steady_ivl_us, steady_n;   // v14
} v11_hdr;
static v11_hdr h11;
typedef char v11_hdr_fits[(sizeof(v11_hdr) <= V11_HDR_BLK) ? 1 : -1];
static char h11_blk[V11_HDR_BLK];

static volatile unsigned w_produced, w_written, w_stop, w_done, w_err;
static int w_fd, sem_full, sem_free;
static char *w_buf;
static unsigned w_nslot = V11_NSLOT, w_slot_off = V11_SLOT_OFF, w_slot_sz = V11_SLOT_SZ;
static unsigned s_sz[V11_NSLOT], s_cap[V11_NSLOT], s_enc[V11_NSLOT], s_ph[V11_NSLOT],
                s_phus[V11_NSLOT], s_tick[V11_NSLOT], s_idx[V11_NSLOT];

static void wr_task(void)
{
    static unsigned rec[V11_REC_BLK / 4];
    for (;;) {
        if (w_written < w_produced && !w_err) {
            unsigned k = w_written % w_nslot, n, t0, dt;
            char *p = w_buf + w_slot_off + k * w_slot_sz;
            memset(rec, 0, sizeof(rec));
            memcpy(rec, "VIDF", 4);
            rec[1] = s_sz[k]; rec[2] = s_cap[k]; rec[3] = s_enc[k];
            rec[4] = s_ph[k]; rec[5] = s_phus[k]; rec[6] = s_tick[k]; rec[7] = s_idx[k];
            n = (s_sz[k] + V11_REC_BLK - 1) & ~(V11_REC_BLK - 1);
            t0 = usec();
            if (write(w_fd, rec, V11_REC_BLK) != V11_REC_BLK || write(w_fd, p, n) != (int)n) w_err = 1;
            dt = udiff(t0, usec());
            if (s_idx[k] < V11_NF_MAX) h11.wr_us[s_idx[k]] = dt;
            h11.sum_wr += dt;
            if (dt < h11.wr_min) h11.wr_min = dt;
            if (dt > h11.wr_max) h11.wr_max = dt;
            w_written++;
            GiveSemaphore(sem_free);
            continue;
        }
        if (w_stop && (w_written >= w_produced || w_err)) break;
        TakeSemaphore(sem_full, 50);
    }
    w_done = 1;
    ExitTask();
}

static void __attribute__((unused)) grab_v11(void)   // v11 pipelined loop (probe49)
{
    exmem_alloc_info ai;
    char *buf;
    unsigned phys, nf = V11_NF_DEF, i, t_wall, t_prod;
    int cfd, ok = 1;

    msg[0] = 0;
    slog("v11 start 6804=%08x 8094=%08x", shamem(0xc0f06804), shamem(PACK32_MODE));
    if (shamem(0xc0f06804) == 0 || *(volatile unsigned *)DSS_FLAGS == 0) { sprintf(msg, "LV inactive"); return; }
    if (shamem(0xc0f06804) != 0x045702a6) { sprintf(msg, "pas en zoom x5"); return; }

    cfd = open("A/M10V.CFG", O_RDONLY, 0777);
    if (cfd >= 0) { char c[8]; int n = read(cfd, c, 7); close(cfd); if (n > 0) { c[n] = 0; nf = strtol(c, 0, 10); } }
    if (nf < 1) nf = V11_NF_DEF;
    if (nf > V11_NF_MAX) nf = V11_NF_MAX;

    // full idle checks once (v10 did them every frame)
    if (!ch12_idle() || !ch_idle(0xc0f26c00) || !ch_idle(0xc0f04000) || !ch_idle(0xc0f26200)) {
        sprintf(msg, "canaux occupes"); return;
    }
    buf = exmem_alloc_uncached(EXMEM_TYPE, EXMEM_SIZE, &ai);
    if (!buf) { sprintf(msg, "EXMEM refuse"); return; }
    phys = (unsigned)buf & 0x3fffffff;

    memset(&h11, 0, sizeof(h11));
    memcpy(h11.magic, "M10VID02", 8);
    h11.w = VID_W; h11.h = VID_H; h11.bits = VID_BITS; h11.nf_planned = nf;
    h11.fb_in = VID_LB * VID_H; h11.nslot = V11_NSLOT;
    h11.hdr_blk = V11_HDR_BLK; h11.rec_blk = V11_REC_BLK;
    h11.cap_min = h11.enc_min = h11.wr_min = 0xffffffff;

    w_fd = open("A/M10CINE.VID", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (w_fd < 0) { exmem_free_uncached(EXMEM_TYPE); sprintf(msg, "VID open err"); return; }
    memset(h11_blk, 0, sizeof(h11_blk));
    write(w_fd, h11_blk, V11_HDR_BLK);          // placeholder, rewritten at end

    sem_full = CreateBinarySemaphore("M10Full", 0);
    sem_free = CreateBinarySemaphore("M10Free", 0);
    w_buf = buf; w_produced = w_written = w_stop = w_done = w_err = 0;
    CreateTask("M10Wr", 0x19, 0x1000, wr_task);

    vhd.sum_cap = 0; vhd.cap_min = 0xffffffff; vhd.cap_max = 0;
    snap_quiet = 1;
    t_wall = get_tick_count();
    for (i = 0; i < nf; i++) {
        unsigned enc_us = 0, tw, sz, ph, ph_us, k, tick, bl;
        int r;
        // wait for a free output slot
        tw = get_tick_count();
        while (w_produced - w_written >= V11_NSLOT && !w_err) TakeSemaphore(sem_free, 50);
        h11.wait_ms += get_tick_count() - tw;
        if (w_err) { ok = 0; sprintf(msg, "ecriture err f%d", i); break; }
        k = i % V11_NSLOT;

        tick = get_tick_count() - t_wall;
        r = cap_frame(buf, phys);
        if (r <= 0) { ok = 0; sprintf(msg, "cap %s f%d", r == 0 ? "STALL" : "err", i); break; }
        tw = usec();
        ph = find_phase_at(buf, enc_in_off);
        ph_us = udiff(tw, usec());
        enc_out_off = V11_SLOT_OFF + k * V11_SLOT_SZ;
        sz = enc_frame(buf, phys, ph, &enc_us);
        enc_out_off = VID_OUT_OFF;
        if (sz == 0) { ok = 0; sprintf(msg, "enc err f%d st=%d", i, cb_st); break; }
        {   // zero the padding up to the next 512 bytes (written by wr_task)
            unsigned n = (sz + V11_REC_BLK - 1) & ~(V11_REC_BLK - 1);
            if (n > sz) memset(buf + V11_SLOT_OFF + k * V11_SLOT_SZ + sz, 0, n - sz);
        }
        s_sz[k] = sz; s_cap[k] = last_cap; s_enc[k] = enc_us; s_ph[k] = ph;
        s_phus[k] = ph_us; s_tick[k] = tick; s_idx[k] = i;
        h11.tick_ms[i] = tick;
        h11.sum_enc += enc_us;
        if (enc_us < h11.enc_min) h11.enc_min = enc_us;
        if (enc_us > h11.enc_max) h11.enc_max = enc_us;
        if (ph) h11.nphase_nz++;
        if (ph_us > h11.ph_us_max) h11.ph_us_max = ph_us;
        w_produced = i + 1;
        bl = w_produced - w_written;
        if (bl > h11.max_backlog) h11.max_backlog = bl;
        GiveSemaphore(sem_full);
        h11.nf_done = i + 1;
        if (shamem(0xc0f06804) != 0x045702a6) { sprintf(msg, "zoom perdu f%d", i); break; }
    }
    t_prod = get_tick_count() - t_wall;
    snap_quiet = 0;

    // drain: let the writer finish, then rewrite the header
    w_stop = 1;
    GiveSemaphore(sem_full);
    {
        unsigned t = get_tick_count();
        while (!w_done && get_tick_count() - t < 20000) msleep(20);
    }
    h11.total_ms = get_tick_count() - t_wall;
    h11.prod_ms = t_prod;
    h11.nf_written = w_written;
    h11.werr = w_err;
    h11.sum_cap = vhd.sum_cap; h11.cap_min = vhd.cap_min; h11.cap_max = vhd.cap_max;
    if (h11.nf_done && h11.prod_ms) h11.prod_fps_x100 = h11.nf_done * 100000 / h11.prod_ms;
    if (h11.nf_written && h11.total_ms) h11.real_fps_x100 = h11.nf_written * 100000 / h11.total_ms;
    slog("v11 nf=%d wr=%d", h11.nf_done, h11.nf_written);
    slog("v11 prod_ms=%d total_ms=%d", h11.prod_ms, h11.total_ms);
    slog("v11 fps prod=%d real=%d", h11.prod_fps_x100, h11.real_fps_x100);
    slog("v11 backlog=%d wait_ms=%d", h11.max_backlog, h11.wait_ms);
    if (w_done) {
        memcpy(h11_blk, &h11, sizeof(h11));
        lseek(w_fd, 0, SEEK_SET);
        write(w_fd, h11_blk, V11_HDR_BLK);
        close(w_fd);
        DeleteSemaphore(sem_full);
        DeleteSemaphore(sem_free);
        exmem_free_uncached(EXMEM_TYPE);
    } else {
        // writer stuck: leave memory and file alone (battery pull)
        strcpy(msg, "ecriture bloquee - retirer la batterie");
        slog("v11 writer stuck", 0, 0);
        return;
    }
    if (h11.nf_done)
        sprintf(msg + strlen(msg), " %d/%d %s %d.%02d i/s (prod %d.%02d)", h11.nf_written, nf,
                ok && !w_err ? "ok" : "arret", h11.real_fps_x100 / 100, h11.real_fps_x100 % 100,
                h11.prod_fps_x100 / 100, h11.prod_fps_x100 % 100);
    slog("v11 done", 0, 0);
}

// ---------------------------------------------------------------------------
// v12: three stages in parallel.
//   this task      : capture frame N into input buffer N % 2 (CH12, PACK32)
//   task M10Enc    : phase search + hardware lossless of frame N-1
//   task M10Wr     : card write of frame N-2 (wr_task from v11)
// Capture (CH12 / port 0, res {0x61,0x5f,0x84}, PACK32) and encoder (ch 0x23 /
// 0 / 9, JpCore, Taiwan, Rabbit, res {0xd,0xe,0x84}) use different EDMAC
// channels and engine blocks; the Canon resource lock is reference counted
// (0xfc372c56: count++ and enable only on 0 -> 1). PACK32 on/off writes
// 0xc0f37014[5:0], 0xc0f37074[27:24], 0xc0f370d4, 0xc0f08090 and the PACK32
// block; the encoder's MemifWrap slots are 0xc0f371f0.. / 0xc0f37218.., but
// both write 0xc0f37074 / 0xc0f37014 neighbours through the shadow, so
// cap_frame and enc_frame each restore only what they saved. snap_restore()
// is NOT used in v12 while a capture may run (it would rewrite 0xc0f37000
// range under CH12): the encoder registers are restored once at the end.
// Safety: a capture stall or an encoder failure stops all three stages.
// Memory (16 MB): in0 0x000000, in1 0x400000 (4.19 MB each), WR2 0x800000
// (0x40000), out slots 0x840000 + k * 0x290000, k = 0..2 (2.56 MiB each;
// frames measured 2.2-2.43 MB; a larger one wraps inside its slot and stops
// the run cleanly: size > slot).
// File format M10VID02 (same as v11); cap_wait_ms in the header pad slot.
// ---------------------------------------------------------------------------
#define V12_IN0      0x00000000                 // 924 x 4536 = 0x3ff420
#define V12_IN1      0x00400000
#define V12_WR2      0x00800000                 // probe46: WR2 uses 0x185d0
#define V12_SLOT_OFF 0x00840000
#define V12_SLOT_SZ  0x00290000                 // 2.56 MiB, 3 slots end at 0xff0000
#define V12_NSLOT    3
typedef char v12_mem_fits[(V12_SLOT_OFF + V12_NSLOT * V12_SLOT_SZ <= EXMEM_SIZE
                           && V12_IN1 + VID_LB * VID_H <= V12_WR2) ? 1 : -1];

static volatile unsigned e_captured, e_encoded, e_stop, e_done, e_err;
static int sem_cap, sem_inf;      // capture -> encoder (new frame), encoder -> capture (input free)
static char *e_buf;
static unsigned e_phys, e_cap_us[2], e_tick[2], e_ph[2], e_phus[2];

static void enc_task(void)
{
    for (;;) {
        if (e_encoded < e_captured && !e_err && !w_err) {
            unsigned n = e_encoded, b = n & 1, k = n % V12_NSLOT, tw, ph, ph_us, sz, enc_us = 0;
            tw = get_tick_count();
            while (n - w_written >= V12_NSLOT && !w_err) TakeSemaphore(sem_free, 50);
            h11.wait_ms += get_tick_count() - tw;
            if (w_err) break;
            enc_in_off = b ? V12_IN1 : V12_IN0;
            ph = e_ph[b]; ph_us = e_phus[b];        // v13: found by the capture task
            enc_out_off = V12_SLOT_OFF + k * V12_SLOT_SZ;
            enc_out_size = V12_SLOT_SZ;
            tw = usec();
            sz = enc_frame(e_buf, e_phys, ph, &enc_us);
            if (n < V11_NF_MAX) h11.stage_us[n] = udiff(tw, usec());
            if (sz == 0) { e_err = cb_done ? 2 : 3; h11.enc_st = cb_st | (cb_size & 0xfffffff0); break; }
            {
                unsigned np = (sz + V11_REC_BLK - 1) & ~(V11_REC_BLK - 1);
                if (np > sz) memset(e_buf + enc_out_off + sz, 0, np - sz);
            }
            s_sz[k] = sz; s_cap[k] = e_cap_us[b]; s_enc[k] = enc_us; s_ph[k] = ph;
            s_phus[k] = ph_us; s_tick[k] = e_tick[b]; s_idx[k] = n;
            h11.sum_enc += enc_us;
            if (enc_us < h11.enc_min) h11.enc_min = enc_us;
            if (enc_us > h11.enc_max) h11.enc_max = enc_us;
            if (ph) h11.nphase_nz++;
            if (ph_us > h11.ph_us_max) h11.ph_us_max = ph_us;
            e_encoded = n + 1;
            GiveSemaphore(sem_inf);         // input buffer b is free again
            w_produced = n + 1;
            {
                unsigned bl = w_produced - w_written;
                if (bl > h11.max_backlog) h11.max_backlog = bl;
            }
            GiveSemaphore(sem_full);
            continue;
        }
        if ((e_stop && e_encoded >= e_captured) || e_err || w_err) break;
        TakeSemaphore(sem_cap, 50);
    }
    e_done = 1;
    GiveSemaphore(sem_inf);
    ExitTask();
}

static void grab(void)   // v12 three-stage pipeline
{
    exmem_alloc_info ai;
    char *buf;
    unsigned phys, nf = V11_NF_DEF, i, t_wall, t_prod, cap_wait = 0, u_prev = 0;
    int cfd, ok = 1;

    msg[0] = 0;
    slog("v14 start 6804=%08x 8094=%08x", shamem(0xc0f06804), shamem(PACK32_MODE));
    if (shamem(0xc0f06804) == 0 || *(volatile unsigned *)DSS_FLAGS == 0) { sprintf(msg, "LV inactive"); return; }
    if (shamem(0xc0f06804) != 0x045702a6) { sprintf(msg, "pas en zoom x5"); return; }

    cfd = open("A/M10V.CFG", O_RDONLY, 0777);
    if (cfd >= 0) { char c[8]; int n = read(cfd, c, 7); close(cfd); if (n > 0) { c[n] = 0; nf = strtol(c, 0, 10); } }
    if (nf < 1) nf = V11_NF_DEF;
    if (nf > V11_NF_MAX) nf = V11_NF_MAX;

    if (!ch12_idle() || !ch_idle(0xc0f26c00) || !ch_idle(0xc0f04000) || !ch_idle(0xc0f26200)) {
        sprintf(msg, "canaux occupes"); return;
    }
    buf = exmem_alloc_uncached(EXMEM_TYPE, EXMEM_SIZE, &ai);
    if (!buf) { sprintf(msg, "EXMEM refuse"); return; }
    phys = (unsigned)buf & 0x3fffffff;
    memset(buf + V12_WR2, 0, V12_SLOT_OFF + V12_NSLOT * V12_SLOT_SZ - V12_WR2);

    memset(&h11, 0, sizeof(h11));
    memcpy(h11.magic, "M10VID02", 8);
    h11.w = VID_W; h11.h = VID_H; h11.bits = VID_BITS; h11.nf_planned = nf;
    h11.fb_in = VID_LB * VID_H; h11.nslot = V12_NSLOT;
    h11.hdr_blk = V11_HDR_BLK; h11.rec_blk = V11_REC_BLK;
    h11.cap_min = h11.enc_min = h11.wr_min = 0xffffffff;
    h11.version = 14;

    w_fd = open("A/M10CINE.VID", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (w_fd < 0) { exmem_free_uncached(EXMEM_TYPE); sprintf(msg, "VID open err"); return; }
    memset(h11_blk, 0, sizeof(h11_blk));
    write(w_fd, h11_blk, V11_HDR_BLK);
    {   // v14: pre-allocate ~3 frames (probe50/51: first writes 86-106 ms)
        unsigned t0 = get_tick_count();
        write(w_fd, buf + V12_SLOT_OFF, V12_SLOT_SZ * V12_NSLOT);   // zeroed slots
        lseek(w_fd, V11_HDR_BLK, SEEK_SET);
        h11.prealloc_ms = get_tick_count() - t0;
    }

    sem_full = CreateBinarySemaphore("M10Full", 0);
    sem_free = CreateBinarySemaphore("M10Free", 0);
    sem_cap = CreateBinarySemaphore("M10Cap", 0);
    sem_inf = CreateBinarySemaphore("M10InF", 0);
    sem_enc = CreateBinarySemaphore("M10Enc", 0);
    w_buf = buf; w_nslot = V12_NSLOT; w_slot_off = V12_SLOT_OFF; w_slot_sz = V12_SLOT_SZ;
    w_produced = w_written = w_stop = w_done = w_err = 0;
    e_buf = buf; e_phys = phys;
    e_captured = e_encoded = e_stop = e_done = e_err = 0;
    enc_wr2_off = V12_WR2;
    snap_take();                        // engine registers before any encoder run
    CreateTask("M10Wr", 0x19, 0x1000, wr_task);
    CreateTask("M10Enc", 0x18, 0x1000, enc_task);   // preempts the capture busy-poll

    vhd.sum_cap = 0; vhd.cap_min = 0xffffffff; vhd.cap_max = 0;
    snap_quiet = 1; enc_no_snap = 1; cap_sleep = 1;
    t_wall = get_tick_count();
    for (i = 0; i < nf; i++) {
        unsigned b = i & 1, tw;
        int r;
        // input buffer b must have been encoded (frame i-2)
        tw = get_tick_count();
        while (i - e_encoded >= 2 && !e_err && !w_err && !e_done) TakeSemaphore(sem_inf, 50);
        cap_wait += get_tick_count() - tw;
        if (e_err || w_err || e_done) { ok = 0; sprintf(msg, "%s f%d", w_err ? "ecriture err" : "enc err", i); break; }
        e_tick[b] = get_tick_count() - t_wall;
        if (i < V11_NF_MAX) h11.tick_ms[i] = e_tick[b];
        {
            unsigned u = usec();
            if (i && i < V11_NF_MAX) h11.ivl_us[i] = udiff(u_prev, u);
            u_prev = u;
        }
        cap_in_off = b ? V12_IN1 : V12_IN0;
        r = cap_frame(buf, phys);
        if (r <= 0) { ok = 0; sprintf(msg, "cap %s f%d", r == 0 ? "STALL" : "err", i); break; }
        e_cap_us[b] = last_cap;
        {   // v13: phase search here (the encoder stage is the bottleneck)
            unsigned u = usec();
            e_ph[b] = find_phase_at(buf, cap_in_off);   // own offset: no shared global
            e_phus[b] = udiff(u, usec());
            if (e_phus[b] > h11.ph_us_max) h11.ph_us_max = e_phus[b];
        }
        e_captured = i + 1;
        GiveSemaphore(sem_cap);
        h11.nf_done = i + 1;
        if (shamem(0xc0f06804) != 0x045702a6) { sprintf(msg, "zoom perdu f%d", i); break; }
    }
    t_prod = get_tick_count() - t_wall;

    // drain: encoder, then writer
    e_stop = 1;
    GiveSemaphore(sem_cap);
    {
        unsigned t = get_tick_count();
        while (!e_done && get_tick_count() - t < 10000) msleep(20);
    }
    w_stop = 1;
    GiveSemaphore(sem_full);
    {
        unsigned t = get_tick_count();
        while (!w_done && get_tick_count() - t < 20000) msleep(20);
    }
    if (e_done) snap_restore();         // encoder idle: put the engine registers back
    snap_quiet = 0; enc_no_snap = 0; cap_sleep = 0;
    enc_wr2_off = VID_WR2_OFF; enc_in_off = VID_IN_OFF; cap_in_off = VID_IN_OFF;
    enc_out_off = VID_OUT_OFF; enc_out_size = VID_OUT_SIZE;
    h11.total_ms = get_tick_count() - t_wall;
    h11.prod_ms = t_prod;
    h11.nf_written = w_written;
    h11.nf_encoded = e_encoded;
    h11.werr = w_err | (e_err << 4);
    h11.cap_wait_ms = cap_wait;
    h11.ndiff = llh.ndiff; h11.nrestored = llh.nrestored;
    h11.sum_cap = vhd.sum_cap; h11.cap_min = vhd.cap_min; h11.cap_max = vhd.cap_max;
    if (h11.nf_done && h11.prod_ms) h11.prod_fps_x100 = h11.nf_done * 100000 / h11.prod_ms;
    if (h11.nf_written && h11.total_ms) h11.real_fps_x100 = h11.nf_written * 100000 / h11.total_ms;
    {
        unsigned k, sum = 0, n = 0;
        for (k = 10; k < h11.nf_done && k < V11_NF_MAX; k++) { sum += h11.ivl_us[k]; n++; }
        if (n) { h11.steady_ivl_us = sum / n; h11.steady_n = n; }
    }
    slog("v14 cap=%d enc=%d", h11.nf_done, e_encoded);
    slog("v14 wr=%d err=%x", h11.nf_written, h11.werr);
    slog("v14 prod_ms=%d total_ms=%d", h11.prod_ms, h11.total_ms);
    slog("v14 fps prod=%d real=%d", h11.prod_fps_x100, h11.real_fps_x100);
    slog("v14 backlog=%d wait_ms=%d", h11.max_backlog, h11.wait_ms);
    slog("v14 cap_wait_ms=%d regs restored=%d", cap_wait, llh.nrestored);
    if (e_done && w_done) {
        memcpy(h11_blk, &h11, sizeof(h11));
        lseek(w_fd, 0, SEEK_SET);
        write(w_fd, h11_blk, V11_HDR_BLK);
        close(w_fd);
        {
            int se = sem_enc;
            sem_enc = 0;
            DeleteSemaphore(se);
        }
        DeleteSemaphore(sem_full); DeleteSemaphore(sem_free);
        DeleteSemaphore(sem_cap); DeleteSemaphore(sem_inf);
        exmem_free_uncached(EXMEM_TYPE);
    } else {
        strcpy(msg, "tache bloquee - retirer la batterie");
        slog("v14 stuck enc_done=%d wr_done=%d", e_done, w_done);
        return;
    }
    if (h11.nf_done)
        sprintf(msg + strlen(msg), " %d/%d %s %d.%02d i/s (prod %d.%02d)", h11.nf_written, nf,
                ok && !w_err && !e_err ? "ok" : "arret", h11.real_fps_x100 / 100, h11.real_fps_x100 % 100,
                h11.prod_fps_x100 / 100, h11.prod_fps_x100 % 100);
    if (h11.steady_ivl_us) {
        unsigned f = 100000000 / h11.steady_ivl_us;
        sprintf(msg + strlen(msg), " regime %d.%02d", f / 100, f % 100);
    }
    slog("v14 done", 0, 0);
}

static void __attribute__((unused)) grab_v9(void)
{
    exmem_alloc_info ai;
    char *buf;
    unsigned phys;
    int r;

    msg[0] = 0;
    slog("v9 start 6804=%08x 8094=%08x", shamem(0xc0f06804), shamem(PACK32_MODE));
    if (shamem(0xc0f06804) == 0 || *(volatile unsigned *)DSS_FLAGS == 0) { sprintf(msg, "LV inactive"); return; }
    if (shamem(0xc0f06804) != 0x045702a6) { sprintf(msg, "pas en zoom x5"); return; }
    buf = exmem_alloc_uncached(EXMEM_TYPE, EXMEM_SIZE, &ai);
    if (!buf) { sprintf(msg, "EXMEM refuse"); return; }
    phys = (unsigned)buf & 0x3fffffff;
    // v9: Canon photo RAW path passes pack mode 2 to PACK32 on (0xfc22f73e(bpp, 2)):
    // 0xc0f08264 = 1 + EDMAC 4-byte flag. We used pack 0 (two interleaved
    // streams). Pack 2 is expected to give the single-stream layout the
    // encoder reads (probe44). 14-bit frame + encoder, then a 12-bit frame.
    seg_pack = 2;
    r = segment(buf, phys, 14, 1, msg);     // -> A/M10P2_14.RAW
    if (r > 0) {
        msleep(300);
        ll_test(buf, msg, 14);              // -> A/M10LL.BIN
        msleep(300);
        if (shamem(0xc0f06804) == 0x045702a6) {
            char *p = msg + strlen(msg);
            segment(buf, phys, 12, 1, p);   // -> A/M10P2_12.RAW
        }
    }
    seg_pack = 0;
    exmem_free_uncached(EXMEM_TYPE);
    slog("done", 0, 0);
}

static void __attribute__((unused)) grab_v7(void)
{
    exmem_alloc_info ai;
    char *buf;
    unsigned phys;
    int r;

    msg[0] = 0;
    slog("v7 start 6804=%08x 8094=%08x", shamem(0xc0f06804), shamem(PACK32_MODE));
    if (shamem(0xc0f06804) == 0 || *(volatile unsigned *)DSS_FLAGS == 0) { sprintf(msg, "LV inactive"); return; }
    if (shamem(0xc0f06804) != 0x045702a6) { sprintf(msg, "pas en zoom x5"); return; }

    buf = exmem_alloc_uncached(EXMEM_TYPE, EXMEM_SIZE, &ai);
    if (!buf) { sprintf(msg, "EXMEM refuse"); return; }
    phys = (unsigned)buf & 0x3fffffff;

    // v7: 14-bit input (Canon CR2 depth); probe41/42 failed in 12-bit with
    // JpCore error 0x041c001c after reading 512 bytes
    r = segment(buf, phys, 14, 1, msg);     // one 14-bit frame -> A/M10C_14.RAW
    if (r > 0) {
        msleep(300);
        ll_test(buf, msg, 14);
    }
    exmem_free_uncached(EXMEM_TYPE);
    slog("done", 0, 0);
}

// ---------------------------------------------------------------------------
// v15 "LVN": first look at the Canon normal live view readout (3x3 over the
// whole sensor), run automatically when the camera is NOT in zoom x5.
// probe25 (old Lua, pack 0, 16-bit, 726 x 3616 B): DMA froze at 676 lines,
// held 1 s, camera switched off after cleanup. Here:
//   - PACK32 14-bit pack 2 (the format validated in zoom), width W_LV = 1808
//     (probe21-23 line), 3164 B/line;
//   - growing transfers 256, 512, 768, 1024, 1280 lines (each < 4 MiB, one
//     2-D transfer, separate full setup/teardown), abort after 60 ms without
//     progress (ch12_run), and STOP at the first stall: no retry;
//   - each successful transfer saved to A/LVN_<lines>.RAW (hdr M10LVN01:
//     6800/6804/6008/6014, DSS w/h + flags, dt, status);
//   - then, only if the 1024-line transfer worked: one lossless encoder pass
//     on it (w 1808, h 1024) with phase search -> A/LVN_LL.BIN.
// ---------------------------------------------------------------------------
#define LVN_W       1808
#define LVN_LB      (LVN_W * 14 / 8)           // 3164
#define LVN_NSTEP   6
typedef char lvn_fits[(1280 * LVN_LB <= 0x00400000) ? 1 : -1];
// v16: 256 twice (does a 2nd capture work at all?), then growing sizes;
// every transfer is ONE block (probe53: 256 lines one block OK, 512 lines as
// 2 blocks of 256 = 0 byte written)
static const unsigned lvn_lines[LVN_NSTEP] = { 256, 256, 384, 512, 727, 1024 };
#define LVN_NTR     96              // DMA pointer samples per transfer (1 per ms)
static unsigned lvn_tr[LVN_NTR];

typedef struct {
    char     magic[8];      // "M10LVN01"
    unsigned w, lines, lb, bits;
    unsigned r6800, r6804, r6008, r6014, dss_w, dss_h, dss_flags;
    unsigned dt_us, status, end_ptr, phase;
    unsigned pad[3];
    unsigned step, ntr;
    unsigned tr[LVN_NTR];       // v16: (pointer - start) every ~1 ms from the start
} lvn_hdr;

// one 2-D CH12 transfer of n lines (blocks of <= 512 lines), 14-bit pack 2.
// returns 1 ok, 0 stall, -1 setup error. end_ptr = last DMA address.
// v20 bisection (probe57: v19 still crashed, ImgSens fatal 0x100000 at the
// end of pass 6): 1 = everything (locks, PACK32 on, CH12 programmed, masked
// restore, release) EXCEPT starting the CH12 transfer, held 10 ms.
static int lvm_nodma = 0;     // v22: real transfer again
// v21: hold time of the no-DMA pass = the longest real pass (probe55-57:
// up to 70 ms), to separate "the transfer" from "holding PACK32 long".
static int lvm_hold_ms = 70;
// v22: the only remaining difference with the (never crashing) zoom capture:
// the LV probe busy-polls CH12 for up to 70 ms at prio 0x1A, the zoom
// pipeline sleeps (cap_sleep). 1 = msleep(1) in the poll loop.
static int lvm_sleep = 1;
static unsigned lvn_bpp = 14, lvn_lb = LVN_LB;  // v26: lv_x3 bit depth
// v168z (2026-11-15): the x5 magnifier with a taller head (m10zoomtall.py: 6804 = H<<16 | 0x2a6, H 1111..1300)
// counts as zoom in lv_x3 (width 2592, lines up to H - 7) so the hold-line position can be measured.
static int zoom_head(unsigned h) { unsigned hh = h >> 16; return (h & 0xffff) == 0x2a6 && hh >= 1111 && hh <= 1300; }
static unsigned x_w = LVN_W, x_per = 40000, x_zoom = 0, x_m1 = 0;   // v156/v180: frame width, period us, zoom flag, ImgMode 1 flag
static unsigned lvn_post_ms = 0;    // v33: wait after the DMA end before stop/restore
static unsigned tl_step = 1000;     // v34: timeline spacing (us); calibration: 250 us, busy poll
// v30: per-ms timeline of the current pass
#define TL_N 160
typedef struct { unsigned us, ptr, tg, sio, w[6]; } tl_rec;
static tl_rec tl[TL_N];
static unsigned tl_n;
#define STG_N 12
static unsigned stg[16][STG_N][4];
static unsigned stg_k = 0;
static unsigned sio_base(void);
static unsigned x_diag = 0;      // v80: heavy diagnostics (shadow diff, RAM watch) only if xo & 0x20000000
static void wr_poll(void);
static unsigned wr_stage;
static void STG(unsigned i)
{
    unsigned sb = sio_base();
    wr_stage = (stg_k << 16) | i; wr_poll();
    if (stg_k >= 16 || i >= STG_N) return;
    stg[stg_k][i][0] = usec();
    stg[stg_k][i][1] = *(volatile unsigned *)0x0000e664;
    stg[stg_k][i][2] = (*(volatile unsigned *)0x00008654 << 16) | (*(volatile unsigned *)0x00008658 & 0xffff);
    stg[stg_k][i][3] = sb ? *(volatile unsigned *)(sb + 0x204) : 0;
}
static unsigned sio_ring = 0x300;   // v59: ring offset (v4/v5 0x300, v6 0x500)
static unsigned sio_base(void)
{
    unsigned p = *(volatile unsigned *)0x00009b50, b, m;
    if (p == 0x121) return 0;
    b = (p & ~1u) - 0x10;
    m = *(volatile unsigned *)(b + 0x200);
    if (m == 0x344f4953 || m == 0x354f4953) { sio_ring = 0x300; return b; }
    if (m == 0x364f4953) { sio_ring = 0x500; return b; }
    return 0;
}
// v35: frame sync. Canon programs the CMOS (SIO ch6, CMOSAccs LR 0xfc1bec0f,
// register 0 first) ~0.5 ms after the end of each sensor readout. Wait for a
// NEW such entry in the v4 hook ring -> we are at the start of the vertical
// blanking (~27 ms before the next readout, VGA 25p). 0 = timeout.
static unsigned lvn_sync = 0, sync_wait_us = 0, wait_sleep = 0, sync_late_us = 0, sync_late_max = 0, sync_skips = 0;
static unsigned sync_last = 0, sync_per = 0, sync_prev = 0;   // v43/v44: last CMOS bursts
static unsigned sync_second = 0;   // v45: FHD 1x3: readout starts after the 2nd burst of a pair
static unsigned sync_delay_us = 0; // v47: busy delay after the burst before arming
static unsigned sync_first = 0;    // v49: only the first burst of a pair
static unsigned pk_late = 0;       // v58: frames skipped because PACK32 was busy
static volatile unsigned xr_gate = 1;   // v39: 0 while our CH12/PACK32 transfer runs (no card write)
static int *lj_sem_p = 0;   // v121
static void (*x_kick)(unsigned fr) = 0;   // v125
static void (*x_poll)(void) = 0;           // v181: async encoder collect / re-kick from the capture task's wait loops (m1 REC)
static unsigned lj_chase = 0, lj_chased = 0, lj_chase_n = 0, lj_chase_miss = 0;   // v144: 49th field = start the encoder on the frame being read, at this CH12 line (0 = at DMA end)
static volatile unsigned lj_kicked;   // v144: forward (defined with the LJ state)
static unsigned x_dr[3];   // v126: drop reasons (ring full, he, PACK32 busy)
static volatile unsigned lj_cnt = 0;   // v124
static unsigned lj_on = 0, x_he_fix = 0;   // v172: forward for lvn_cap
// v140: per-frame timeline (20-bit us, bit 31 = set): 0 CH12 armed, 1 first line moved, 2 DMA end, 3 encoder start, 4 encoder CBR, 5 SD write start, 6 SD write end
#include "m10_tasktrace.h"
#define TLF_N 640
/* v154: per-pass record (CAP1), index = pass number k (not the frame number):
 * [0] us at lvn_cap entry, [1] us at CH12 start, [2] us at return,
 * [3] path<<28 | lvn_cap result+8 <<24 | st<<20 | dfe_miss delta<<12 | late ms (8 bits)
 *     path: 1 reuse, 2 chained, 3 wait_dfe_w, 4 other, 5 wait failed; 0 = drop branch
 * [4] fr at entry. */
#define CAP_N 640
#define CAP_BYTES (CAP_N * 5 * 4)   // kept in the REC EXMEM reserve (after the task trace), not in the BSS
static unsigned (*capl)[5] = 0, cap_k = 0xffffffff, cap_n = 0;
static unsigned cap_path = 0, cap_miss0 = 0;
static unsigned tlf[TLF_N][8];
// v182: TLF and CAP are rings (row = frame % TLF_N, record = pass % CAP_N) so the ~740th frame (xr_roll) is traced;
// rows are cleared when their frame / pass starts. Export order is chronological (TLF2 + first frame when wrapped).
#define TLF_ROW(fr) tlf[(fr) % TLF_N]
static void tlf_set(unsigned fr, unsigned i, unsigned v) { TLF_ROW(fr)[i] = v | 0x80000000u; if (!fr && i == 1) ts_first_readout(v); }
static unsigned x_skick = 0, x_skick_n = 0;   // v151: 56th field = 1: kick the encoder on kept short frames too
static unsigned x_pbl = 0;   // v150: 55th field = busy-poll the last N lines of a readout (0 = last quarter)
static volatile unsigned x_dma_live = 0, x_dma_t1 = 0, x_early = 0, x_early_fr = 0, x_ready = 0;   // v121: early publish of a complete frame at DMA end   // v119: CH12 lines moving (readout in progress); usec of the last DMA end
static int wait_eof(unsigned tmo_ms)
{
    unsigned sb = sio_base(), i0, i, t0 = get_tick_count(), u0 = usec(), nm1;
    if (!sb) return 0;
    nm1 = *(volatile unsigned *)(sb + 0x210);
    i0 = *(volatile unsigned *)(sb + 0x204);
    while (get_tick_count() - t0 < tmo_ms) {
        unsigned i1 = *(volatile unsigned *)(sb + 0x204);
        for (i = i0; i != i1; i++) {
            volatile unsigned *e = (volatile unsigned *)(sb + sio_ring + 64 * (i & nm1));
            if (e[4] == 0xfc1bec0f && ((e[5] >> 12) & 0xf) == 0) {
                // only the FIRST burst after a readout: the second one comes 8.6 ms later
                sync_wait_us = udiff(u0, usec());
                unsigned ts = e[0] & 0xfffff;            // v46: hook stores the raw timer
                sync_late_us = udiff(ts, usec());     // v42: how long after the burst we react
                sync_prev = sync_last; sync_last = ts;       // v44: last two bursts
                // v47: sync_second -> arm a fixed delay after ANY burst (pairs are not always present)
                if (sync_first && sync_prev && udiff(sync_prev, sync_last) < 20000) continue;   // v49: skip the 2nd of a pair
                if (sync_second && !(sync_prev && udiff(sync_prev, sync_last) < 20000)) continue;   // v50: only the 2nd of a pair
                if (sync_late_us > 30000) continue;      // v46: stale entry (first scan of the ring)
                if (sync_late_max && sync_late_us > sync_late_max) { sync_skips++; continue; }
                if (sync_delay_us) while (udiff(ts, usec()) < sync_delay_us) ;   // v47
                return 1;
            }
        }
        i0 = i1;
        // v43: sleep only while the next CMOS burst is > 4 ms away (period
        // known from the last burst), busy-poll the last 4 ms
        // v44: msleep(1) = one 10 ms tick. Next burst expected 40 ms after the
        // first of the last pair (bursts come single or in pairs 8.6 ms apart).
        if (wait_sleep) {
            unsigned now = usec(), nxt, togo;
            if (!sync_last) msleep(1);
            else {
                unsigned base = (sync_prev && udiff(sync_prev, sync_last) < 20000) ? sync_prev : sync_last;
                nxt = base + 40000 + (sync_second ? 8600 : 0);
                togo = udiff(now, nxt & 0xfffff);
                if (togo < 0x80000 && togo > 14000) msleep(1);
            }
        }
    }
    return 0;
}
// v53: sync on the end of Canon's LV EDMAC transfer (FHD: c0f04300, 720x408
// YUV, runs during the sensor readout). Returns 1 just after the pointer stops
// moving (readout over, start of the vertical blanking), 0 on timeout.
static unsigned lv_edmac = 0xc0f04308, lv_last_end = 0;
// v61: FHD precise timing. msleep(1) = one 10 ms tick: in FHD (readout 20 ms,
// blanking 20 ms) a late DMA-end detection put our PACK32 restore inside the
// NEXT readout (r83a-e: truncated frame, then Canon's chain dies).
//  x_prec: sleep only until the readout starts, then busy-poll the DMA; after
//          the DMA end, busy-wait until the sensor readout is over (head H lines).
//  x_chain: the pass ending OK at the readout end puts us in the blanking: arm
//          the next pass at once (no LV EDMAC resync) -> one pass per frame.
static unsigned x_prec = 0, x_chain = 0, x_post_us = 0, x_prev_end = 0, x_prev_ok = 0, x_chained = 0;
static unsigned x_short = 0, x_short_min = 0;   // v61: frames that ended a few lines short
// v66: per-pass DMA profile (same ring layout as stg): first move, last move,
// longest stall between two moves, line count at that stall (us from DMA start)
static unsigned x_pm[16][4];
static unsigned x_chf = 0;     // v68
// v71: engine shadow ranges compared between DMA start and DMA end (what does
// Canon rewrite while our transfer runs?). x_df[k] = { n diffs, then up to
// 24 x (reg, before, after) }.
static const unsigned df_rng[3][2] = { { 0xc0f37000, 0x400 }, { 0xc0f08000, 0xc00 }, { 0xc0f05000, 0x600 } };
#define DF_W ((0x400 + 0xc00 + 0x600) / 4)
static unsigned df_sh[DF_W];
static unsigned x_df[16][1 + 3 * 24];
static void df_take(void)
{
    unsigned b = *(volatile unsigned *)0x00028dbc, r, j, k = 0;
    for (r = 0; r < 3; r++)
        for (j = 0; j < df_rng[r][1]; j += 4)
            df_sh[k++] = *(volatile unsigned *)(b + ((df_rng[r][0] + j) & 0x7ffff));
}
static void df_cmp(unsigned slot)
{
    unsigned b = *(volatile unsigned *)0x00028dbc, r, j, k = 0, *o;
    if (slot >= 16) return;
    o = x_df[slot]; o[0] = 0;
    for (r = 0; r < 3; r++)
        for (j = 0; j < df_rng[r][1]; j += 4, k++) {
            unsigned reg = df_rng[r][0] + j, v = *(volatile unsigned *)(b + (reg & 0x7ffff));
            if (v != df_sh[k]) {
                if (o[0] < 24) { o[1 + 3 * o[0]] = reg; o[2 + 3 * o[0]] = df_sh[k]; o[3 + 3 * o[0]] = v; }
                o[0]++;
            }
        }
}
static int wait_lvend(unsigned tmo_ms)
{
    unsigned t0 = get_tick_count(), p = REG(lv_edmac), tchg = usec(), moving = 0, u;
    while (get_tick_count() - t0 < tmo_ms) {
        unsigned q = REG(lv_edmac);
        u = usec();
        if (q != p) { p = q; if (!moving) moving = u; tchg = u; }
        else if (moving && udiff(moving, tchg) > 5000 && udiff(tchg, u) > 2000) {   // v60: 2 ms still
            sync_late_us = udiff(tchg, u);
            lv_last_end = tchg;
            if (sync_late_us < 3500) return 1;
            moving = 0; sync_skips++;          // v54: seen too late (preempted): wait the next frame
        }
        if (wait_sleep && !moving && lv_last_end) {        // sleep only just after an end
            unsigned since = udiff(lv_last_end, u);
            if (since < 6000) msleep(1);
        }
    }
    return 0;
}
// v75c: change log of Canon's ImgSens / TG state words (polled in every wait
// and DMA loop): finds when, relative to our passes, the fatal restart begins.
static const unsigned wr_addr[] = { 0x8650, 0x8654, 0x8658, 0x865c, 0x8660, 0x8664, 0x8668, 0x866c,
                                    0x8694, 0x8698, 0x8688, 0x868c, 0xe660, 0xe664, 0xe668, 0x28738,   // v75h: 8694 = vBLK/head state
                                    0xe440, 0xe444, 0x4ac04, 0x4ac08, 0x4ac0c, 0x2cd0c, 0x8694, 0 };   // v89p: ImagePower, EvfFunc, ImagePowerSub; last = ImgSens flag value
#define WR_NA 24
#define WR_N 480
static unsigned wr_last[WR_NA], wr_n = 0, wr_on = 0, wr_force = 0;   // v89o: wr_force = log in REC without x_diag
static unsigned wr_log[WR_N][3];     // usec | (idx << 24), new value, stg_k << 16 | stage
static void wr_poll(void)
{
    unsigned i;
    if (!wr_on || !(x_diag || wr_force)) return;
    for (i = 0; i < WR_NA; i++) {
        unsigned v;
        if (!wr_addr[i]) { v = 0; ((fn2)0xfc314b44)(*(volatile unsigned *)(0x8650 + 0x3c), (unsigned)&v); }   // v89p: ImgSens event flag
        else v = *(volatile unsigned *)wr_addr[i];
        if (v != wr_last[i]) {
            wr_last[i] = v;
            if (wr_n < WR_N) { wr_log[wr_n][0] = usec() | (i << 24); wr_log[wr_n][1] = v; wr_log[wr_n][2] = wr_stage; wr_n++; }
        }
    }
}
static void wr_init(void)
{
    unsigned i;
    for (i = 0; i < WR_NA; i++) wr_last[i] = wr_addr[i] ? *(volatile unsigned *)wr_addr[i] : 0xffffffff;   // v89p
    wr_n = 0; wr_on = 1;
    if (wr_n < WR_N) { wr_log[0][0] = usec() | (0xff << 24); wr_log[0][1] = 0; wr_log[0][2] = 0; wr_n = 1; }
}
// v62: anchor on Canon's per-frame DFE write 0x8830 (TgCtrl ch4, LR 0xfc1bd4e3):
// one per frame, ~1.8 ms after the end of the FHD sensor readout (r83/r84:
// readout = burst + 0.9 .. + 20.4 ms, 8830 at burst + 22.2). Returns 1 at
// 8830 + dly_us (busy), 0 on timeout. An entry seen later than dly + 3 ms
// (we were preempted) is skipped.
static unsigned x_dly_us = 6000, x_dfe_ts = 0, x_dfe_miss = 0, x_dma_sio = 0;
// from = ring index to scan from (0: now); post = 1: an entry already past
// its delay is accepted at once (restore after our DMA end).
static int is_sync_evt(volatile unsigned *e)   // v180: DFE 8830 in LV/Zoom, CMOS 0 in ImgMode 1
{
    if (x_m1) return e[4] == 0xfc1bec0f && ((e[5] >> 12) & 0xf) == 0;
    return e[4] == 0xfc1bd4e3 && e[5] == 0x8830;
}
static int wait_dfe(unsigned tmo_ms, unsigned dly_us, unsigned from, int post)
{
    unsigned sb = sio_base(), i0, i, t0 = get_tick_count(), nm1;
    if (!sb) return 0;
    nm1 = *(volatile unsigned *)(sb + 0x210);
    i0 = from ? from : *(volatile unsigned *)(sb + 0x204);
    while (get_tick_count() - t0 < tmo_ms) {
        unsigned i1 = *(volatile unsigned *)(sb + 0x204);
        wr_poll();
        for (i = i0; i != i1; i++) {
            volatile unsigned *e = (volatile unsigned *)(sb + sio_ring + 64 * (i & nm1));
            if (is_sync_evt(e)) {
                unsigned ts = e[0] & 0xfffff, late = udiff(ts, usec());
                if (late > 30000) continue;               // stale
                if (!post && late > dly_us + 3000) { x_dfe_miss++; continue; }
                while (udiff(ts, usec()) < dly_us) ;
                sync_late_us = late; x_dfe_ts = ts;
                return 1;
            }
        }
        i0 = i1;
        if (wait_sleep && x_dfe_ts) {             // sleep only while the next 8830 is > 14 ms away
            unsigned togo = udiff(usec(), (x_dfe_ts + x_per) & 0xfffff);
            if (togo < 0x80000 && togo > 14000) msleep(1);
        }
    }
    return 0;
}
// v69: has this frame's DFE 8830 (readout over) been written since ring index
// `from`, at least `age` us ago? -> our DMA will get no more lines.
static int dfe_seen(unsigned from, unsigned age)
{
    unsigned sb = sio_base(), i, i1, nm1;
    if (!sb) return 0;
    nm1 = *(volatile unsigned *)(sb + 0x210);
    i1 = *(volatile unsigned *)(sb + 0x204);
    for (i = from; i != i1; i++) {
        volatile unsigned *e = (volatile unsigned *)(sb + sio_ring + 64 * (i & nm1));
        if (is_sync_evt(e) && udiff(e[0] & 0xfffff, usec()) >= age) return 1;
    }
    return 0;
}
static unsigned last_8830(void)   // v109: timestamp (20-bit us) of the most recent DFE 8830 (or CMOS 0 in m1) in the SIO ring, 0 = none
{
    unsigned sb = sio_base(), i, i1, nm1, n;
    if (!sb) return 0;
    nm1 = *(volatile unsigned *)(sb + 0x210);
    i1 = *(volatile unsigned *)(sb + 0x204);
    for (i = i1, n = 0; n < 400 && n <= nm1; n++) {
        volatile unsigned *e;
        i--;
        e = (volatile unsigned *)(sb + sio_ring + 64 * (i & nm1));
        if (is_sync_evt(e)) return (e[0] & 0xfffff) | 0x80000000;
    }
    return 0;
}
static unsigned x_abort = 0;    // v69: passes cut at the frame's 8830
// v72 (8th CFG field, hex): 1 = CPU-friendly 8830 window (sleep, busy <= ~3.5 ms),
// 2 = chain: restore + next start inside the same 8830 window (one pass per frame),
// 4 = PACK32 pack 4 + CH12 flag 0x1000.
static unsigned x_xo = 0, x_lo = 1000, x_hi = 7000, x_hi_post = 30000;
// v179 (r153): one-shot trigger around the CH12 start of the first pass. RAM block (host-written):
//   [0] 'TRG1' magic, [1] n_pre, [2] n_go, then (n_pre + n_go) pairs {kind, reg | val << 16}
//   kind 0 TgWrite, 1 DfeWrite, 2 CdsWrite, 3 CMOS (0xfc1bebfb), 4 wait val ms (busy, usec)
//   pre-list before CH12 start, go-list right after it; ring index re-read after the go-list
//   (our DFE writes must not look like this frame's 8830).
static unsigned *x_trg = 0, x_trg_done = 0, x_trg_us = 0;
static unsigned trg_busy = 0, trg_skip = 0;
static int trg_open_pair(void)   // last ch4 frame in the SIO ring = an address frame (Canon pair still open)?
{
    unsigned sb = sio_base(), i1, nm1;
    volatile unsigned *e;
    if (!sb) return 0;
    nm1 = *(volatile unsigned *)(sb + 0x210);
    i1 = *(volatile unsigned *)(sb + 0x204);
    e = (volatile unsigned *)(sb + sio_ring + 64 * ((i1 - 1) & nm1));
    return (e[4] == 0xfc231323 || e[4] == 0xfc1bd4e3 || e[4] == 0xfc414d41 || e[4] == 0xfc35b5e9) &&
           udiff(e[0] & 0xfffff, usec()) < 3000;
}
static void trg_run(const unsigned *e, unsigned n)
{
    unsigned i;
    for (i = 0; i < n; i++, e += 2) {
        unsigned k = e[0], r = e[1] & 0xffff, v = e[1] >> 16, ps, u;
        if (k == 4) { msleep(v > 500 ? 500 : v); continue; }
        u = usec();
        while (trg_open_pair()) { if (udiff(u, usec()) > 4000) { trg_skip++; break; } }
        if (trg_open_pair()) trg_busy++;
        __asm__ volatile("mrs %0, cpsr\n\tcpsid i" : "=r"(ps) :: "memory");
        if (k == 0) ((fn2)0xfc231309)(r, v);
        else if (k == 1) ((fn2)0xfc1bd4c9)(r, v);
        else if (k == 2) { unsigned w = e[1]; ((fn1)0xfc414d25)((unsigned)&w); }
        else if (k == 3) ((fn2)0xfc1bebfb)(r, v & 0xfff);
        __asm__ volatile("msr cpsr_c, %0" :: "r"(ps) : "memory");
    }
}
static unsigned x_busy_max = 0, x_busy_tot = 0, x_waits = 0, x_ref_tick = 0, x_late_acc = 0;
static int sdiff(unsigned a, unsigned b) { return (int)(((b - a + 0x80000) & 0xfffff)) - 0x80000; }
// Returns 1 at a time in [ts + lo, ts + hi] of a NEW 8830 (ring scanned from
// `from`, 0 = now), 0 on timeout. msleep(1) wakes on the next 10 ms tick, whose
// phase is fixed relative to the 40 ms frame: sleep while the end of the next
// predicted window is > 10.5 ms away, busy-poll only the last few ms.
static void tg_fix(unsigned fr);   // v89q
static unsigned x_he_n;
static int wait_dfe_w(unsigned tmo_ms, unsigned from, unsigned hi, unsigned acc)
{
    unsigned sb = sio_base(), i0, i, t0 = get_tick_count(), nm1, ub = 0;
    if (!sb) return 0;
    nm1 = *(volatile unsigned *)(sb + 0x210);
    i0 = from ? from : *(volatile unsigned *)(sb + 0x204);
    while (get_tick_count() - t0 < tmo_ms) {
        unsigned i1 = *(volatile unsigned *)(sb + 0x204), now;
        wr_poll();
        if (x_poll) x_poll();   // v181
        if (x_he_n) tg_fix(0);   // v89q: ~1 ms latency
        for (i = i0; i != i1; i++) {
            volatile unsigned *e = (volatile unsigned *)(sb + sio_ring + 64 * (i & nm1));
            if (is_sync_evt(e)) {
                unsigned ts = e[0] & 0xfffff, late = udiff(ts, usec());
                if (late > (x_m1 ? 48000u : 30000u)) continue;               // stale (v180d: m1 restore at +34 ms)
                x_dfe_ts = ts; x_ref_tick = get_tick_count();
                if (late > acc) { x_dfe_miss++; continue; } // window gone: next frame
                for (;;) { unsigned el = udiff(ts, usec()); if (el >= x_lo) break; if (x_m1 && x_lo - el > 14500) msleep(1); }
                sync_late_us = late; x_late_acc += late;
                if (ub) { unsigned bt = udiff(ub, usec()); x_busy_tot += bt; if (bt > x_busy_max) x_busy_max = bt; }
                x_waits++;
                return 1;
            }
        }
        i0 = i1;
        now = usec();
        if (x_dfe_ts && get_tick_count() - x_ref_tick < 400) {
            int d = sdiff(x_dfe_ts, now);                 // now - last 8830
            while (d >= (int)hi) d -= (int)x_per;         // relative to the next predicted one (v156: x_per)
            if ((int)x_lo - d > (x_m1 ? 14500 : 10500)) { if (ub) { x_busy_tot += udiff(ub, now); ub = 0; } msleep(1); continue; }   // v72b/v180c: wake before the window START (m1: 14.5 ms tick guard)
            if (!ub) ub = now;
            if (!x_m1 && x_early && !x_kick && lj_cnt < x_ready && (int)x_lo - d > 3000) { msleep(1); continue; }   // v124: an early frame is waiting for the encoder: sleep (10 ms tick) so the encoder task can start, if the window is > 3 ms away
        } else if (!x_m1) msleep(1);                      // no reference yet (v180b: busy-poll first CMOS 0 in m1)
    }
    return 0;
}
// ---------------------------------------------------------------------------
// v73: persistent PACK32 / CH12 pipeline (x_xo & 0x10, lvn_sync 4 only).
// px_open = everything lvn_cap did before the DMA (lock, PK_TAKE, save,
// PK_ON, crossbar), px_close = everything after it (CH12 stop + crossbar
// release, PK_OFF writes, masked restore, PK_GIVE(6), CH12 regs, unlock).
// While px_on, a pass only re-arms CH12 inside the 8830 window that follows
// our own DMA end. PACK32 stays enabled, so it must never see a sensor
// readout with CH12 idle: whenever the next frame will not be armed in this
// window (drop, gap, stop, error, late), the caller / lvn_cap closes first.
// ---------------------------------------------------------------------------
static unsigned px_s274 = 0, x_heads = 0;   // v83
static unsigned x_he_pass = 0, x_he_val = 0;   // v84
static unsigned x_he_mode = 0, x_he_at[32];
static unsigned x_he_n = 0;
// v88: shadow snapshot (EngDrvRead) of the pre-processing blocks around the first REC head error
static const unsigned hs_rng[][2] = { {0xc0f07000, 0x400}, {0xc0f08000, 0x1000}, {0xc0f09000, 0x200}, {0xc0f37000, 0xc00}, {0xc0f45000, 0x400} };   // v88b: + 37400-37bff, 45000-453ff (DefMark)
#define HS_WORDS ((0x400 + 0x1000 + 0x200 + 0xc00 + 0x400) / 4)
static unsigned hs_buf[3][HS_WORDS], hs_n = 0, hs_after = 0;
static unsigned x_r450a0 = 0xffffffff, x_r450_fix = 0;   // v89f
static unsigned x_he_frz = 0;   // v89g
// v89i: WBInteg watchdog. WBIntegTask (0xfc2ca3e2) waits 3 s for flag 0x20050 on [0xc6f0+0x20]:
// 0x40 = Wombat IRQ 0x34 (copies +0x54 -> +0x58), 0x20000 = CH15 end, 0x10 = CH16 end (+0x54 -> +0x5c);
// the frame callback 0xfc2c9f4e (0x2400) copies +0x50 -> +0x54. Track when each pointer last moved.
#define WB_S 0xc6f0
static unsigned wb_last[4], wb_tick[4], wb_max[4], wb_logged = 0, wb_kick_n = 0;   // v89j: kicks
static unsigned wb_defer = 0, wb_due = 0, wb_late_n = 0;   // v180f: m1 REC defers the WB kick into the readout
static unsigned x_warm = 32;                               // v180f: MiB pre-written before an m1 take (0 = off)
static volatile unsigned wb_last_kick_ms = 0;              // v182: last WBIntegTask kick from any path (wb_mon, wb_kick_due, M10WB)
static volatile unsigned xr_prod;   // v183: forward (defined with the XR state below)
static void wb_kick_due(unsigned fr)   // v180f: called right after eng_out(CH12, 1)
{
    unsigned fv = 0, now;
    if (!wb_due) return;
    now = get_tick_count();
    if (x_m1 && wb_defer) {   // v183: no kick in the first 8 frames, nor while the encoder is >= 2 behind (safety 1 s / 900 ms)
        if (fr < 8 && now - wb_last_kick_ms <= 1000) return;
        if (fr >= 8 && lj_on && (int)(xr_prod - lj_cnt) >= 2 && now - wb_last_kick_ms <= 900) return;
    }
    wb_due = 0;
    ((fn2)0xfc314b44)(*(volatile unsigned *)(WB_S + 0x20), (unsigned)&fv);
    ((fn2)0xfc314c94)(*(volatile unsigned *)(WB_S + 0x20), 0x20050);
    if (wb_kick_n < 8) slog("v180f wb kick (readout) fr=%d flag=%x", fr, fv);
    wb_kick_n++; wb_late_n++; wb_tick[3] = now; wb_tick[2] = now; wb_last_kick_ms = now;
}
/* v182 (spec A.5-1): WBInteg watchdog, independent task M10WB (prio 0x18, above the capture 0x1A).
 * In the stand-alone shell nothing else feeds WBIntegTask (the host daemon of the USB runs is gone):
 * any window of ~3 s without WB statistics in ImgMode 1 = ASSERT WBInteg.c:3491 then power-off.
 * The task tracks WB_S+0x58 / +0x5c itself; it kicks only when +0x5c has been frozen > 1200 ms and no
 * kick came from anywhere for > 900 ms (REC: the deferred in-readout kick, ~every 450 ms, keeps it
 * silent), or frozen > 600 ms / no kick > 500 ms while the shell idles outside a take. */
static volatile unsigned wb_wd_stop = 0, wb_wd_done = 1, wb_wd_on = 0, wb_wd_kicks = 0;
static volatile unsigned wb_wd_force = 0;                 // v183c: keep M10WB kicking while 0x865c != 1 (AF dip)
static void wb_kick_now(void)                             // v183c: immediate WBIntegTask kick (before the AF dip)
{
    unsigned flag = *(volatile unsigned *)(WB_S + 0x20), fv = 0;
    if (!flag) return;
    ((fn2)0xfc314b44)(flag, (unsigned)&fv);
    ((fn2)0xfc314c94)(flag, 0x20050);
    wb_last_kick_ms = get_tick_count();
    wb_wd_kicks++;
}
static void wb_wd_task(void)
{
    unsigned l58 = 0, l5c = 0, t5c = 0, t58 = 0;
    while (!wb_wd_stop) {
        unsigned now = get_tick_count();
        if (*(volatile unsigned *)0x865c == 1 || wb_wd_force) {   // v183c: + forced across the AF dip
            unsigned v58 = *(volatile unsigned *)(WB_S + 0x58), v5c = *(volatile unsigned *)(WB_S + 0x5c);
            unsigned flag = *(volatile unsigned *)(WB_S + 0x20);
            int rec = !sh_on || sh_rec_on;
            unsigned lim = rec ? 1200 : 600, gap = rec ? 900 : 500;
            if (v58 != l58 || !t58) { l58 = v58; t58 = now; }
            if (v5c != l5c || !t5c) { l5c = v5c; t5c = now; }
            if (flag && (now - t5c > lim || now - t58 > lim) && now - wb_last_kick_ms > gap) {
                unsigned fv = 0;
                ((fn2)0xfc314b44)(flag, (unsigned)&fv);
                ((fn2)0xfc314c94)(flag, 0x20050);
                wb_last_kick_ms = now;
                wb_wd_kicks++;
            }
        } else { t5c = 0; t58 = 0; }
        msleep(100);
    }
    wb_wd_done = 1;
    ExitTask();
}
static void wb_wd_start(void)
{
    if (wb_wd_on) return;
    wb_wd_stop = 0; wb_wd_done = 0; wb_wd_on = 1;
    CreateTask("M10WB", 0x18, 0x800, wb_wd_task);
}
static void wb_wd_end(void)
{
    unsigned t = get_tick_count();
    if (!wb_wd_on) return;
    wb_wd_stop = 1;
    while (!wb_wd_done && get_tick_count() - t < 1000) msleep(20);
    if (wb_wd_done) wb_wd_on = 0;   // else stays "on": _module_can_unload refuses (task code still in use)
}
// v89q: TG freeze after a head error (r101f/g): ImgSens restarts the imager while the TG is still
// streaming (state 3); TgCtrl stop 0xfc230a74 then leaves [0xe664] = -1 instead of 1, TgCtrl start
// (0xfc230a36: 1 -> 2, 0xfc230b1a: 2 -> 3) refuses, no TG callback 0x40000 in 300 ms -> 0x100000.
// Put the state back to 1 (what the same stop writes from state 4) so the restart can go through.
static unsigned tg_fix_n = 0;
static void tg_fix(unsigned fr)
{
    if (*(volatile unsigned *)0x0000e664 == 0xffffffff && tg_fix_n < 8) {
        *(volatile unsigned *)0x0000e664 = 1;
        tg_fix_n++;
        slog("v89q tg -1 -> 1 fr=%d n=%d", fr, tg_fix_n);
    }
}
static void wb_mon(unsigned fr)
{
    unsigned i, now = get_tick_count();
    wr_poll();   // v89o
    if (x_he_n) tg_fix(fr);   // v89q
    for (i = 0; i < 4; i++) {
        unsigned v = *(volatile unsigned *)(WB_S + 0x50 + 4 * i);
        if (v != wb_last[i] || !wb_tick[i]) { wb_last[i] = v; wb_tick[i] = now; }
        else if (now - wb_tick[i] > wb_max[i]) wb_max[i] = now - wb_tick[i];
    }
    // v89j: after a head error the WB stats chain (CH15/CH16 ends -> +0x5c, Wombat IRQ -> +0x58) can stop for good
    // (r100v_4: flag stuck at 0x2c00, WBInteg 3491 3 s later). Kick WBIntegTask: set 0x20050 so it re-programs
    // Wombat + CH15/CH16 for the next frame (one frame of stale WB stats).
    // v89s (live103): with a taller head (H = 1254) the WB stats chain stalls without any head error
    // (WBInteg tables still sized for 1190): kick on staleness alone, no limit (each kick = 1 stale WB frame).
    if (!x_zoom && (x_he_n || (shamem(0xc0f06804) >> 16) != 0x4a6) && (wb_kick_n < 32 || (shamem(0xc0f06804) >> 16) != 0x4a6) && now - wb_tick[3] > 400) {
        unsigned fv = 0;
        if (x_m1 && wb_defer) { wb_due = 1; goto wb_log; }   // v180f: m1 REC: kick later, right after CH12 start (inside the readout, not before the arm window)
        ((fn2)0xfc314b44)(*(volatile unsigned *)(WB_S + 0x20), (unsigned)&fv);
        ((fn2)0xfc314c94)(*(volatile unsigned *)(WB_S + 0x20), 0x20050);   // j_SetEventFlag (ARM thunk)
        if (wb_kick_n < 8) slog("v89j wb kick fr=%d flag=%x", fr, fv);
        wb_kick_n++; wb_tick[3] = now; wb_tick[2] = now; wb_last_kick_ms = now;
    }
wb_log:
    if (wb_logged < 6 && i && (now - wb_tick[1] > 700 || now - wb_tick[2] > 700 || now - wb_tick[3] > 700)) {
        unsigned fv = 0;
        ((fn2)0xfc314b44)(*(volatile unsigned *)(WB_S + 0x20), (unsigned)&fv);   // j_GetEventFlagValue (ARM thunk: even address)
        slog("v89i wb stale fr=%d flag=%x", fr, fv);
        slog("  v89i age 54=%d 58=%d", now - wb_tick[1], now - wb_tick[2]);
        slog("  v89i age 5c=%d 50=%d", now - wb_tick[3], now - wb_tick[0]);
        wb_logged++;
        for (i = 1; i < 4; i++) if (i != 3 || !wb_due) wb_tick[i] = now;   // re-arm (log again only if still stale); v182: never while a kick is due (+0x5c age drives it)
    }
}   // 0: before the error, 1: right after, 2: 2nd good frame after
// v89b: EDMAC activity sampled for 120 ms, ONLY on channels already read without
// incident (v63 edmac_map list + CH21/22/24 + CH12): v89 read all 48 slots of the
// 3 blocks, including slots that may not exist, and the camera died (r100i).
// per channel = ctl at start, first addr, number of address changes, last addr
static const unsigned ea_base[] = {
    0xc0f04000, 0xc0f04100, 0xc0f04300, 0xc0f04400, 0xc0f04600,
    0xc0f26000, 0xc0f26100, 0xc0f26200, 0xc0f26300, 0xc0f26500, 0xc0f26600,
    0xc0f26800, 0xc0f26900, 0xc0f26a00, 0xc0f26b00, 0xc0f26c00, 0xc0f26d00,
    0xc0f30100, 0xc0f30200, 0xc0f30300, 0xc0f30600,
    0xc0f57000, 0xc0f58000, 0xc0f58200 };
#define EA_N (sizeof(ea_base) / sizeof(ea_base[0]))
static unsigned ea_buf[3][24][4], ea_n = 0;
static void ea_take(unsigned slot)
{
    unsigned ch, t0 = get_tick_count(), last[24];
    for (ch = 0; ch < EA_N; ch++) {
        unsigned b = ea_base[ch];
        ea_buf[slot][ch][0] = REG(b); ea_buf[slot][ch][1] = last[ch] = REG(b + 8); ea_buf[slot][ch][2] = 0; ea_buf[slot][ch][3] = last[ch];
    }
    while (get_tick_count() - t0 < 120) {
        for (ch = 0; ch < EA_N; ch++) {
            unsigned a = REG(ea_base[ch] + 8);
            if (a != last[ch]) { ea_buf[slot][ch][2]++; last[ch] = a; ea_buf[slot][ch][3] = a; }
        }
        msleep(1);
    }
    if (slot + 1 > ea_n) ea_n = slot + 1;
}
static void hs_take(unsigned slot)
{
    unsigned r, o, k = 0;
    for (r = 0; r < sizeof(hs_rng) / sizeof(hs_rng[0]); r++)
        for (o = 0; o < hs_rng[r][1]; o += 4) hs_buf[slot][k++] = shamem(hs_rng[r][0] + o);
    if (slot + 1 > hs_n) hs_n = slot + 1;
}
static unsigned char x_hst[512];
static unsigned x_dc = 99, x_dc_saved = 0;   // v86: Canon write channel disconnected from the crossbar during our pass (99 = none)   // v85c: live c0f070dc low byte after each pass   // v85: 1 = keep going, count trapped head errors
static char *x_mcsrc = 0;
static unsigned x_start_us = 0;  // v79: CH12 start time after 8830 (xo 0x10000000), from the 13th CFG field      // v77: memcpy source (second half of EXMEM)
static unsigned x_px = 0, px_on = 0, px_n = 0, px_cycle = 6, px_s14 = 0, px_s74 = 0;
static unsigned x_rsel = 0, px_s40 = 0;   // v169: 58th CFG field RSEL = raw selector for 37014/37040/37074 (0 = Canon PK_ON 0x12; 0x2e = photo path, r124)
static unsigned px_cfg[NPK];        // PACK32 sub-registers as set by PK_ON (re-written by the reset pulse)
static unsigned px_dirty = 0;       // last frame cut short: PACK32 may hold a partial frame
static unsigned px_opens = 0, px_frames = 0, px_late = 0, px_rearm_err = 0, px_pulses = 0;
static unsigned x_need = 0;         // v73: min lines of an accepted frame (0 = legacy: any short frame)
static unsigned x_rx = 0, x_short_bad = 0;
static unsigned x_flines = 0;       // v73: lines of the CH12 frame (Film 1x3: 1185), 0 = unknown
// 1 ok, 2 PACK32 busy (frame skipped, nothing held), -1 error (nothing held)
static int px_open(void)
{
    unsigned i, ut;
    ((fn1)FN_RES_LOCK)((unsigned)reslist);
    for (i = 0; i < NCHREGS; i++) chsaved[i] = shamem(CH12_BASE + chregs[i]);
    STG(2);
    ut = usec();
    if (((fn0)FN_PK_TAKE)() != 0) { ((fn1)FN_RES_UNLOCK)((unsigned)reslist); return -1; }
    // v58: PACK32 was busy (Canon uses it, e.g. AE integration): the frame
    // window is gone. Give everything back untouched and skip this frame.
    if (lvn_sync && udiff(ut, usec()) > 1000) {
        ((fn1)FN_PK_GIVE)(6);
        ((fn1)FN_RES_UNLOCK)((unsigned)reslist);
        pk_late++;
        return 2;
    }
    STG(3);
    px_s14 = shamem(0xc0f37014);
    px_s74 = shamem(0xc0f37074);
    for (i = 0; i < NPK; i++) pk_saved[i] = shamem(pk_regs[i]);
    ch12_flags = x_chf ? x_chf : ((x_xo & 4) ? 0x1000 : 0x40000000);   // v68, v72 pack 4
    ((fn2)FN_PK_ON)(lvn_bpp, (x_xo & 4) ? 4 : 2);
    if (x_xo & 0x8000000) ((fn3)FN_ENGDRV_MASK)(0xc0f37014, ~0x3fu, 0x10);   // v78: RAW from the HEAD output (ML lv_select_raw 0x10)
    if (x_rsel) {                      // v169: Canon photo values seen in r124: 37014[5:0]=0x2e, 37040 = 2e2e....(bits 16-21, 24-29), 37074[5:0]=0x2e, [13:8]=0x2f
        px_s40 = shamem(0xc0f37040);
        ((fn3)FN_ENGDRV_MASK)(0xc0f37014, ~0x3fu, x_rsel & 0x3f);
        if (x_rsel == 0x2e) {
            ((fn3)FN_ENGDRV_MASK)(0xc0f37040, 0xc0c0ffffu, 0x2e2e0000);
            ((fn3)FN_ENGDRV_MASK)(0xc0f37074, ~0x3f3fu, 0x2f2e);
        }
    }
    if (x_xo & 0x10000) {           // v75i: EvfCaptureSystem start = PK_ON, 0xfc34d580(bpp), 0xfc34ed7a(1): 37274 bit 8
        px_s274 = shamem(0xc0f37274);
        ((fn3)FN_ENGDRV_MASK)(0xc0f37274, ~0x100u, 0x100);
    }
    if (x_xo & 0x2000) ((fn3)FN_ENGDRV_MASK)(0xc0f37074, ~0x0f000000u, px_s74 & 0x0f000000);   // v75e: keep Canon's 37074[27:24]
    if (x_xo & 0x4000) ((fn3)FN_ENGDRV_MASK)(0xc0f37014, ~0x3fu, px_s14 & 0x3f);              // v75e: keep Canon's 37014[5:0]
    for (i = 0; i < NPK; i++) px_cfg[i] = shamem(pk_regs[i]);
    STG(4);
    eng_out(CH12_XBAR, 0x00);
    if (x_dc <= 24) {                  // v86: cut one Canon consumer of the pre-processing output for this pass
        unsigned xa = x_dc < 8 ? 0xc0f05000 + 4 * x_dc : 0xc0f051e0 + 4 * x_dc;
        x_dc_saved = shamem(xa);
        eng_out(xa, 0x80000000);
    }
    if (x_xo & 0x40000000) {           // v83: head error causes bit 5/6 masked during our pass (Extract 0xfc1572ba)
        eng_out(0xc0f072c8, 0); eng_out(0xc0f072cc, 0); eng_out(0xc0f072d0, 0); eng_out(0xc0f072d4, 0);
    }
    px_on = 1; px_n = 0; px_dirty = 0; px_opens++;
    return 1;
}
// 1 ok, -1 CH12 did not stop. Idempotent.
static int px_close(void)
{
    unsigned i;
    int ok = 1;
    if (!px_on) return 1;
    if (!ch12_stop()) ok = -1;
    STG(7);
    // v19: restore everything BEFORE giving the PACK32 semaphore back.
    // probe56: ROMLOG "ShutdownReason[9] ErrorNo[16]" = ImgSens.c fatal
    // 0x100000 (0xfc1eec74): the sensor/TG restart (ImgSens -> FldCreat,
    // which takes PACK32 sem #6 then writes 0xc0f37014...) did not get its
    // TG callback within 300 ms. The old order (PK_OFF = give sem #6, then
    // write the saved 0xc0f37014/37074/PACK32 values) could overwrite the
    // values FldCreat had just written. Now: PK_OFF's register writes
    // (0xc0f370d4, 0xc0f08090 = 0x80000000), masked restore of only the
    // fields PK_ON touched, PACK32 sub-registers, and only then give sem #6.
    eng_out(0xc0f370d4, 0x80000000);
    eng_out(0xc0f08090, 0x80000000);
    if (!(x_xo & 0x800)) {      // v75: 0x800 = exactly Canon's PK_OFF (no 37014/37074/sub-register restore)
    ((fn3)FN_ENGDRV_MASK)(0xc0f37014, ~0x3fu, px_s14 & 0x3f);
    ((fn3)FN_ENGDRV_MASK)(0xc0f37074, ~0x0f000000u, px_s74 & 0x0f000000);
    for (i = 0; i < NPK; i++) eng_out(pk_regs[i], pk_saved[i]);
    }
    if (x_rsel == 0x2e) {              // v169: restore the extra fields we touched (also with xo 0x800)
        ((fn3)FN_ENGDRV_MASK)(0xc0f37014, ~0x3fu, px_s14 & 0x3f);
        ((fn3)FN_ENGDRV_MASK)(0xc0f37040, 0xc0c0ffffu, px_s40 & 0x3f3f0000);
        ((fn3)FN_ENGDRV_MASK)(0xc0f37074, ~0x3f3fu, px_s74 & 0x3f3f);
    }
    if (x_xo & 0x10000) ((fn3)FN_ENGDRV_MASK)(0xc0f37274, ~0x100u, px_s274 & 0x100);   // v75i
    if (x_xo & 0x40000000) {           // v83: re-arm Canon's head error detection (Extract 0xfc157280)
        unsigned he = *(volatile unsigned *)(0x0000fa68 + 0x1c);
        if (he) x_heads++;
        eng_out(0xc0f072c8, 0x20); eng_out(0xc0f072cc, 0x20); eng_out(0xc0f072d0, 0x40); eng_out(0xc0f072d4, 0x40);
    }
    if (x_dc <= 24) eng_out(x_dc < 8 ? 0xc0f05000 + 4 * x_dc : 0xc0f051e0 + 4 * x_dc, x_dc_saved);   // v86
    STG(8);
    ((fn1)FN_PK_GIVE)(6);
    STG(9);
    for (i = 0; i < NCHREGS; i++) eng_out(CH12_BASE + chregs[i], chsaved[i]);
    ((fn1)FN_RES_UNLOCK)((unsigned)reslist);
    STG(10);
    px_on = 0;
    return ok;
}
// v74 per-pass record of the persistent path (appended to LVX3S.BIN after x_df):
// [0] path (1 open, 2 reuse) | flags, [1..7] shadow 8090 8264 8268 82bc 8bf0 37014 37074
// right before ch12_arm, [8] REG(CH12) before start, [9] us start -> CH12 idle,
// [10] bytes received, [11] shadow 8090 after the DMA end.
static const unsigned px_rr[] = { 0xc0f08090, 0xc0f08264, 0xc0f08268, 0xc0f082bc, 0xc0f08bf0, 0xc0f37014, 0xc0f37074 };
static unsigned x_pr[16][12];
// abort a still-armed CH12 transfer (short frame) WITHOUT releasing the crossbar
// v74 (x_xo & 0x40): always write the stop command, as ch12_stop() does, even
// when the channel already reads idle (a completed transfer may leave a
// pending end that the next start consumes at once -> empty pass).
static int ch12_abort(void)
{
    unsigned u = usec();
    if (REG(CH12_BASE) == 0 && !(x_xo & 0x40)) return 1;
    eng_out(CH12_BASE, 2);
    while (REG(CH12_BASE) != 0 && udiff(u, usec()) < 5000) ;
    return REG(CH12_BASE) == 0;
}
// one frame into phys (CH12 must be idle): 1 block if <= 4 MiB, 2 blocks (yn=1) if > 4 MiB
static void ch12_arm(unsigned phys, unsigned n)
{
    unsigned off, tot = n * lvn_lb;
    eng_out(CH12_BASE + 0x40, 0);
    eng_out(CH12_BASE + 0x04, ch12_flags);
    eng_out(CH12_BASE + 0x08, phys);
    if (tot > 0x00400000) {
        unsigned b1 = n / 2, b2 = n - b1;
        eng_out(CH12_BASE + 0x0c, 1 << 16);
        eng_out(CH12_BASE + 0x14, ((b1 - 1) << 16) | lvn_lb);
        eng_out(CH12_BASE + 0x10, ((b2 - 1) << 16) | lvn_lb);
    } else {
        eng_out(CH12_BASE + 0x0c, 0);
        eng_out(CH12_BASE + 0x14, 0);
        if (x_rowm > 1 && !(n % x_rowm)) eng_out(CH12_BASE + 0x10, ((n / x_rowm - 1) << 16) | (lvn_lb * x_rowm));   // v131: m lines per EDMAC row (8/16-byte burst alignment)
        else eng_out(CH12_BASE + 0x10, ((n - 1) << 16) | lvn_lb);
    }
    for (off = 0x18; off <= 0x28; off += 4) eng_out(CH12_BASE + off, 0);
}
// PACK32 datapath reset in the blanking, as PK_ON / 0xfc34d5b6 do it (bit 31
// set then cleared, sub-registers, enable) but without touching 0xc0f37014 /
// 37074 / 370d4 or semaphore #6: drops any line left over from the last frame.
static void px_pulse(void)
{
    unsigned i;
    eng_out(0xc0f08090, 0x80000000);
    eng_out(0xc0f08090, 0);
    for (i = 0; i < NPK; i++) eng_out(pk_regs[i], px_cfg[i]);
    eng_out(0xc0f08090, 1);
    px_pulses++;
}

static int lvn_cap(char *buf, unsigned phys, unsigned n, unsigned *dt, unsigned *endp)
{
    unsigned st = 0, reuse = 0, bad = 0;
    int ok = 1;
    if (cap_k < CAP_N) { capl[cap_k][0] = usec() | 0x80000000u; cap_path = 4; cap_miss0 = x_dfe_miss; }   // v154
    STG(0);
    if (x_trg && !x_trg_done && x_trg[0] == 0x31475254 && x_trg[1] + x_trg[2] <= 120 && !px_on) trg_run(x_trg + 3, x_trg[1]);   // v179: pre-list before the 8830 sync (PACK32 still closed)
    if (px_on) {                        // v73: persistent pipeline still open from the last pass
        int d = x_dfe_ts ? sdiff(x_dfe_ts, usec()) : -1;
        if (d >= 0 && d < (int)x_hi) { reuse = 1; x_chained++; sync_late_us = d; }
        else { px_late++; px_close(); }  // window gone: never keep PACK32 on into a readout
    }
    if (reuse) cap_path = 1;
    else if (!ch12_idle()) return -1;
    else if (((x_xo & 2) || x_px) && x_prev_ok && x_dfe_ts && sdiff(x_dfe_ts, usec()) >= (x_m1 ? (int)x_lo : 0) && sdiff(x_dfe_ts, usec()) < (int)x_hi) {
        x_chained++;                    // v72: same 8830 window as our restore (v73: also after a periodic px release)
        sync_late_us = udiff(x_dfe_ts, usec()); cap_path = 2;
    } else if (lvn_sync == 4 && (x_xo & 1)) {
        cap_path = 5;
        if (!wait_dfe_w(200, 0, x_hi, x_hi)) return -1;
        cap_path = 3;
        if (x_xo & 0x8000) { if (!wait_dfe_w(200, 0, x_hi, x_hi)) return -1; }   // v75f: skip one frame (12.5 fps test)
    } else if (lvn_sync >= 3 && x_chain && x_prev_ok && udiff(x_prev_end, usec()) < 3000) {
        x_chained++;                    // v61: still in the blanking after our own readout end
        sync_late_us = udiff(x_prev_end, usec());
    } else if (lvn_sync == 4) {         // v62: 8830 + delay
        if (!wait_dfe(200, x_dly_us, 0, 0)) return -1;
    } else if (lvn_sync == 3) {         // v53
        if (!wait_lvend(200)) return -1;
    } else if (lvn_sync) {              // v35: arm in the blanking (first CMOS burst of a pair)
        if (!wait_eof(200)) return -1;
        if (lvn_sync == 2) { msleep(2); if (!wait_eof(30)) return -1; }   // skip to 2nd burst of the pair? (test)
    }
    if (stg_k < 16) stg[stg_k][0][3] = sync_late_us;   // v42 (overwrites the SIO index of STG 0)
    xr_gate = 0;
    STG(1);
    if (!reuse) {                       // lock, PK_TAKE, PK_ON, crossbar (v16: always one block)
        int r = px_open();
        if (r != 1) { xr_gate = 1; x_prev_ok = 0; return r; }   // v73: no re-chain into the same busy window
    } else {                            // v73: CH12 idle (ended or aborted in the last window)
        if (x_xo & 0x200) {             // v74b: px_close + px_open minus sem #6 / resource lock
            unsigned i;
            ch12_stop();                // CH12 <- 2, crossbar released
            eng_out(0xc0f370d4, 0x80000000);
            eng_out(0xc0f08090, 0x80000000);
            ((fn3)FN_ENGDRV_MASK)(0xc0f37014, ~0x3fu, px_s14 & 0x3f);
            ((fn3)FN_ENGDRV_MASK)(0xc0f37074, ~0x0f000000u, px_s74 & 0x0f000000);
            for (i = 0; i < NPK; i++) eng_out(pk_regs[i], pk_saved[i]);
            for (i = 0; i < NCHREGS; i++) eng_out(CH12_BASE + chregs[i], chsaved[i]);
            ((fn2)FN_PK_ON)(lvn_bpp, (x_xo & 4) ? 4 : 2);
            eng_out(CH12_XBAR, 0x00);
            px_pulses++;
        } else if (x_xo & 0x80) {       // v74: Canon's own PACK32 enable (no semaphore inside)
            ((fn2)FN_PK_ON)(lvn_bpp, (x_xo & 4) ? 4 : 2);
            px_pulses++;
        } else if (!(x_xo & 0x20) || px_dirty) px_pulse();   // 0x20: pulse only after a short frame
        if (x_xo & 0x100) { eng_out(CH12_XBAR, 0x80000000); eng_out(CH12_XBAR, 0x00); }   // v74: re-connect
        px_dirty = 0;
    }
    if (stg_k < 16) {                   // v74 instrumentation
        unsigned i;
        x_pr[stg_k][0] = (reuse ? 2 : 1) | (x_xo & 0x3c0) << 4;
        for (i = 0; i < 7; i++) x_pr[stg_k][1 + i] = shamem(px_rr[i]);
        x_pr[stg_k][8] = REG(CH12_BASE);
    }
    ch12_arm(phys, n);
    if (x_xo & 0x20000) {          // v75j: PACK32 + crossbar on, CH12 armed but never started (no DRAM writes)
        unsigned sb = sio_base(), u0;
        STG(5);
        x_dma_sio = sb ? *(volatile unsigned *)(sb + 0x204) : 0;
        u0 = usec();
        if (x_xo & 0x1000000) {    // v77: same DRAM traffic from the CPU: copy n lines (uncached) in 64 KiB steps
            unsigned tot = n * lvn_lb, o = 0;   // v77b: word copy, stop after 34 ms (stay inside the frame)
            if (x_mcsrc) {
                volatile unsigned *d = (volatile unsigned *)buf, *sr = (volatile unsigned *)x_mcsrc;
                while (o < tot / 4 && udiff(u0, usec()) < 34000) {
                    unsigned e = o + 1024;
                    for (; o < e; o += 4) { d[o] = sr[o]; d[o+1] = sr[o+1]; d[o+2] = sr[o+2]; d[o+3] = sr[o+3]; }
                }
            }
            if (stg_k < 16) x_pr[stg_k][10] = o * 4;
        } else if (x_xo & 0x4000000) {   // v77c: cached-alias memset (write-back bursts to DRAM), <= 34 ms
            unsigned tot = n * lvn_lb, o = 0;
            char *cb = (char *)(phys & 0x3fffffff);
            while (o + 0x4000 <= tot && udiff(u0, usec()) < 34000) { memset(cb + o, (int)(o >> 14), 0x4000); o += 0x4000; }
            if (stg_k < 16) x_pr[stg_k][10] = o;
        }
        *dt = udiff(u0, usec()); st = 0;
    } else
    if (lvm_nodma) { msleep(lvm_hold_ms); *dt = 0; st = 0; } else
    {   // ch12_run with a pointer trace (1 sample per ~1 ms, busy loop)
        unsigned u0 = usec(), lastp = 0xffffffff, tmove = get_tick_count(), nt = 0, ulast = u0;
        unsigned sb = sio_base(), uacc = 0, utl = 0, uprev = u0, umove = u0, x_live_sio = 0;
        memset(lvn_tr, 0, sizeof(lvn_tr));
        if (stg_k < 16) memset(x_pm[stg_k], 0, sizeof(x_pm[0]));   // v66
        tl_n = 0;
        st = 0;
        STG(5);
        x_dma_sio = sb ? *(volatile unsigned *)(sb + 0x204) : 0;   // v62
        if (x_diag) df_take();                                     // v71 (v80: diag only)
        if ((x_xo & 0x10000000) && lvn_sync == 4 && x_dfe_ts) {   // v79: start CH12 late (8830 + x_hi_post/... field: x_lo2)
            while (sdiff(x_dfe_ts, usec()) < (int)x_start_us && sdiff(x_dfe_ts, usec()) >= 0) ;
        }
        eng_out(CH12_BASE, 1);
        if (cap_k < CAP_N) capl[cap_k][1] = usec() | 0x80000000u;   // v154
        if (wb_due) wb_kick_due(lj_on ? xr_prod : cap_k);   // v180f (v183: frame index, not pass ring index)
        if (x_trg && !x_trg_done && x_trg[0] == 0x31475254 && x_trg[1] + x_trg[2] <= 120) {   // v179
            trg_run(x_trg + 3 + 2 * x_trg[1], x_trg[2]);
            x_trg_done = 1; x_trg_us = udiff(u0, usec());
            x_dma_sio = sb ? *(volatile unsigned *)(sb + 0x204) : 0;
        }

        for (;;) {
            unsigned pp, u = usec();
            if (x_diag) wr_poll();
            if (x_poll) x_poll();   // v181: previous encode ended during this readout -> start the next one now
            if (REG(CH12_BASE) == 0) break;
            pp = REG(CH12_BASE + 8);
            if (pp != phys && !x_dma_live) { x_dma_live = 1; x_live_sio = sb ? *(volatile unsigned *)(sb + 0x204) : 0; if (x_early) { tlf_set(x_early_fr, 1, u); TLF_ROW(x_early_fr)[7] = REG(0xc0f58908); } }   // v119/v180d: readout has started (m1: record SIO index AFTER this frame's CMOS 0)
            if (lvn_sync == 4 && pp != phys && dfe_seen(x_m1 ? x_live_sio : x_dma_sio, 500)) {   // v69/v180d: frame over, lines lost
                if (REG(CH12_BASE) == 0) break;
                x_abort++; st = 3; break;
            }
            uacc += udiff(uprev, u); uprev = u;
            if (tl_n < TL_N && (tl_n == 0 || uacc - utl >= tl_step)) {
                tl_rec *t = &tl[tl_n++];
                utl = uacc;
                t->us = u; t->ptr = pp - phys;     // v34: absolute timer (same as the SIO ring)
                t->tg = *(volatile unsigned *)0x0000e664;
                t->sio = sb ? *(volatile unsigned *)(sb + 0x204) : 0;
                t->w[0] = *(volatile unsigned *)0x0000e660; t->w[1] = *(volatile unsigned *)0x0000e668;
                if (tl_step == 250 || (x_xo & 0x400)) {   // v51: Canon EDMAC current addresses (v75: xo 0x400 = always)
                    t->w[2] = REG(0xc0f04308); t->w[3] = REG(0xc0f04108);   // v70: Canon resizer outputs
                    t->w[4] = REG(0xc0f26608); t->w[5] = REG(0xc0f04608);
                } else {
                t->w[2] = *(volatile unsigned *)0x00008650; t->w[3] = *(volatile unsigned *)0x00008654;
                t->w[4] = *(volatile unsigned *)0x00008658; t->w[5] = *(volatile unsigned *)0x0000865c;
                }
            }
            if (nt < LVN_NTR && udiff(ulast, u) >= 1000) { lvn_tr[nt++] = pp - phys; ulast = u; }
            if (pp != lastp) {
                if (stg_k < 16 && lastp != 0xffffffff) {     // v66 profile
                    unsigned g = udiff(umove, u);
                    if (lastp == phys) x_pm[stg_k][0] = udiff(u0, u);
                    else if (g > x_pm[stg_k][2]) { x_pm[stg_k][2] = g; x_pm[stg_k][3] = (lastp - phys) / lvn_lb; }
                    x_pm[stg_k][1] = udiff(u0, u);
                }
                lastp = pp; tmove = get_tick_count(); umove = u;
            }
            else if (get_tick_count() - tmove > 60) { st = 1; break; }
            else if ((x_prec || lvn_sync == 4) && pp != phys) {   // v61/v67: the readout is over but some lines never came
                unsigned nthr = (x_need && x_need < n - 32) ? x_need : n - 32;   // v73
                int nearend = (pp - phys >= nthr * lvn_lb);
                if (udiff(umove, u) > (nearend ? 1500u : 30000u)) { st = nearend ? 3 : 1; break; }
            }
            if (lj_chase && x_early && x_kick && pp != phys && !lj_chased && (pp - phys) >= lj_chase * lvn_lb) {   // v144: chase start: kick the encoder on THIS frame once CH12 is lj_chase lines in (the encoder, 43 l/ms, never catches the sensor, 61.6 l/ms)
                lj_chased = 1; x_ready = x_early_fr + 1; x_kick(x_early_fr); lj_chase_n++;
                if (lj_kicked != x_early_fr + 1) lj_chase_miss++;
            }
            if (x_prec) { if (pp == phys) msleep(1); }   // v61: sleep only before the readout starts
            else if (lj_chase && x_early && x_kick && !lj_chased && pp != phys) ;   // v144: busy-poll until the chase start line
            else if (x_early && pp - phys >= (x_pbl ? (n > x_pbl ? n - x_pbl : 0) : n * 3 / 4) * lvn_lb) ;   // v122: busy-poll the last quarter (~5 ms) so the DMA end is seen at once (v150: last x_pbl lines: a 10 ms msleep tick started before 3/4 can overrun the DMA end -> missed 8830 window)
            else if (lvm_sleep) msleep(1);   // v22: yield like the zoom pipeline
        }
        *dt = udiff(u0, usec());
        x_dma_live = 0; x_dma_t1 = usec();   // v119
        if (x_early) { tlf_set(x_early_fr, 2, x_dma_t1); TLF_ROW(x_early_fr)[0] = REG(0xc0f58908); }   // v140 (v141: slot 0 = ch47 address at DMA end)
        if (x_early && st == 0) {
            if (x_he_fix && lj_on && *(volatile unsigned *)(0x0000fa68 + 0x1c)) ;   // v172: HEAD_ERR handled in lv_x3 (skip JpCore)
            else { x_ready = x_early_fr + 1; if (x_kick && !lj_chased) x_kick(x_early_fr); if (lj_sem_p) GiveSemaphore(*lj_sem_p); }
        }   // v121: frame complete in DRAM (v125: encoder started right here; v144: unless already chased)
    }
    if (lvn_sync == 4 && (x_xo & 1) && (st == 0 || st == 3)) { if (!wait_dfe_w(80, x_dma_sio, x_hi, x_hi_post)) st = 1; }   // v72 (restore: any delay accepted)
    else if (lvn_sync == 4 && (st == 0 || st == 3)) { if (!wait_dfe(60, x_dly_us, x_dma_sio, 1)) st = 1; }   // v64: short frames too   // v62: restore at this frame's 8830 + delay
    else if (x_prec) { unsigned ue = usec(); while (udiff(ue, usec()) < x_post_us) ; }   // v61: rest of the readout
    else if (lvn_post_ms) msleep(lvn_post_ms);   // v33: restore in the vertical blanking, not at EOF
    if (x_diag) df_cmp(stg_k);                                     // v71 (v80: diag only)
    STG(6);
    *endp = REG(CH12_BASE + 8);
    x_rx = (st == 0) ? n * lvn_lb : *endp - phys;   // v73: bytes received
    if (stg_k < 16) { x_pr[stg_k][9] = *dt; if (!(x_xo & 0x5000000)) x_pr[stg_k][10] = x_rx | (st << 28); x_pr[stg_k][11] = shamem(0xc0f08090); }   // v74 (v77b: keep copied bytes)
    if (st == 3) {                                  // v61: short frame, keep going
        x_short++; if (x_short_min == 0 || x_rx < x_short_min) x_short_min = x_rx;
        if (x_need && x_rx < x_need * lvn_lb) { x_short_bad++; bad = 1; }   // v73: below the accepted height
        px_dirty = 1;
        if (x_skick && x_early && !bad) {   // v151: a kept short frame was never kicked at the DMA end (st == 3): the encoder fell one frame behind for good -> raw ring full -> drop bursts
            if (x_he_fix && lj_on && *(volatile unsigned *)(0x0000fa68 + 0x1c)) ;   // v172
            else {
                x_ready = x_early_fr + 1; x_skick_n++;
                if (x_kick && !lj_chased) x_kick(x_early_fr);
                if (lj_sem_p) GiveSemaphore(*lj_sem_p);
            }
        }
    }
    else if (st) ok = 0;
    else if (x_flines && n < x_flines) px_dirty = 1;   // v73: the frame tail went into PACK32 with CH12 done
    px_frames++;
    if (x_px && ok > 0 && !(px_cycle && ++px_n >= px_cycle)) {
        // v73: keep PACK32 / crossbar / sem #6; the next pass re-arms in this window
        if (!ch12_abort()) { px_rearm_err++; ok = -1; px_close(); }
        STG(7);
    } else if (px_close() < 0) ok = -1;   // v73: px_cycle frames reached -> full release (Canon may wait on sem #6)
    xr_gate = 1;
    x_prev_end = usec(); x_prev_ok = (ok > 0);   // v61
    if (ok > 0 && bad) ok = 2;                   // v73: counted as a drop, pipeline kept
    if (cap_k < CAP_N) {                         // v154
        unsigned dm = x_dfe_miss - cap_miss0, lm = sync_late_us / 1000;
        capl[cap_k][2] = usec() | 0x80000000u;
        capl[cap_k][3] = (cap_path << 28) | (((unsigned)(ok + 8) & 0xf) << 24) | ((st & 0xf) << 20) | ((dm > 255 ? 255 : dm) << 12) | (lm > 255 ? 255 : lm);
    }
    return ok;
}

// phase search on any line length: 7 candidates at a middle line (bit offset
// multiple of 112: lb * 8 * line is a multiple of 112 when lb is a multiple of 14)
static unsigned find_phase_lb(const char *buf, unsigned off, unsigned lb, unsigned h)
{
    const unsigned char *d = (const unsigned char *)buf + off;
    unsigned j, i, best = 0, base = lb * (h / 2) * 8, sc[7];
    for (j = 0; j < 7; j++) {
        unsigned b0 = base + 32 * j, prev2 = get14(d, b0), prev1 = get14(d, b0 + 14), t = 0;
        for (i = 2; i < 258; i++) {
            unsigned v = get14(d, b0 + 14 * i);
            t += (v > prev2) ? v - prev2 : prev2 - v;
            prev2 = prev1; prev1 = v;
        }
        sc[j] = t;
        if (t < sc[best]) best = j;
    }
    return best * 4;
}

static void __attribute__((unused)) lv_probe(void)
{
    exmem_alloc_info ai;
    static lvn_hdr lh;
    char *buf, name[24], *p = msg;
    unsigned phys, k, best = 0, stalled = 0;
    unsigned hl = (shamem(0xc0f06804) >> 16) & 0xffff;      // head lines (727 / 1190 ...)
    char mode = hl < 0x0300 ? 'A' : 'B';   // A: ~727-line LV, B: ~1190-line LV
    int fd;

    msg[0] = 0;
    slog("v16 LVN start 6804=%08x 6800=%08x", shamem(0xc0f06804), shamem(0xc0f06800));
    slog("  mode %c", mode, 0);
    slog("  6008=%08x 6014=%08x", shamem(0xc0f06008), shamem(0xc0f06014));
    slog("  dss %dx%d", *(volatile unsigned *)0x001beb5c, *(volatile unsigned *)0x001beb60);
    if (!ch12_idle()) { strcpy(msg, "LVN: CH12 occupe"); return; }
    buf = exmem_alloc_uncached(EXMEM_TYPE, EXMEM_SIZE, &ai);
    if (!buf) { strcpy(msg, "EXMEM refuse"); return; }
    phys = (unsigned)buf & 0x3fffffff;

    for (k = 0; k < LVN_NSTEP; k++) {
        unsigned n = lvn_lines[k], dt = 0, endp = 0;
        int r;
        if (shamem(0xc0f06804) == 0 || *(volatile unsigned *)DSS_FLAGS == 0) { p += sprintf(p, "LV perdue "); break; }
        memset(buf, 0xee, n * LVN_LB + 64);
        r = lvn_cap(buf, phys, n, &dt, &endp);
        memset(&lh, 0, sizeof(lh));
        memcpy(lh.magic, "M10LVN01", 8);
        lh.w = LVN_W; lh.lines = n; lh.lb = LVN_LB; lh.bits = 14;
        lh.r6800 = shamem(0xc0f06800); lh.r6804 = shamem(0xc0f06804);
        lh.r6008 = shamem(0xc0f06008); lh.r6014 = shamem(0xc0f06014);
        lh.dss_w = *(volatile unsigned *)0x001beb5c; lh.dss_h = *(volatile unsigned *)0x001beb60;
        lh.dss_flags = *(volatile unsigned *)DSS_FLAGS;
        lh.dt_us = dt; lh.status = (unsigned)r; lh.end_ptr = endp - phys;
        lh.step = k; lh.ntr = LVN_NTR;
        memcpy(lh.tr, lvn_tr, sizeof(lh.tr));
        slog("LVN %d lines r=%d", n, r);
        slog("   dt=%d end=+%x", dt, lh.end_ptr);
        sprintf(name, "A/L%04d_%d.RAW", hl, k);
        fd = open(name, O_WRONLY | O_CREAT | O_TRUNC, 0777);
        if (fd >= 0) { write(fd, &lh, sizeof(lh)); write(fd, buf, n * LVN_LB); close(fd); }
        p += sprintf(p, "%d:%s ", n, r > 0 ? "ok" : (r == 0 ? "STALL" : "err"));
        if (r <= 0) { stalled = 1; break; }     // one stall ends the session
        best = n;
        msleep(200);
    }
    if (best && !stalled) {
        // recapture the largest size that worked, then one encoder pass on it
        unsigned dt = 0, endp = 0, ph, sz, enc_us = 0;
        int r = lvn_cap(buf, phys, best, &dt, &endp);
        if (r > 0) {
            enc_in_off = 0;
            ph = find_phase_lb(buf, 0, LVN_LB, best);
            enc_out_off = 0x00500000; enc_out_size = 0x00300000;
            enc_wr2_off = 0x00400000;
            memset(buf + 0x00400000, 0, 0x00100000);
            enc_w = LVN_W; enc_h = best;
            sz = enc_frame(buf, phys, ph, &enc_us);
            enc_w = VID_W; enc_h = VID_H;
            enc_out_off = VID_OUT_OFF; enc_out_size = VID_OUT_SIZE; enc_wr2_off = VID_WR2_OFF;
            enc_in_off = VID_IN_OFF;
            slog("LVN LL phase=%d sz=%d", ph, sz);
            slog("   enc_us=%d st=%d", enc_us, cb_st);
            p += sprintf(p, "LL:%s %dK %dms ", sz ? "ok" : "err", sz / 1024, enc_us / 1000);
            sprintf(name, "A/L%04d_LL.BIN", hl);
            fd = open(name, O_WRONLY | O_CREAT | O_TRUNC, 0777);
            if (fd >= 0) {
                unsigned hd[8] = { 0x4e564c4d, LVN_W, best, ph, sz, enc_us, cb_st, cb_size };  // "MLVN"
                write(fd, hd, sizeof(hd));
                if (sz) write(fd, buf + 0x00500000, sz);
                close(fd);
            }
        } else p += sprintf(p, "LL-cap:%s ", r == 0 ? "STALL" : "err");
    }
    exmem_free_uncached(EXMEM_TYPE);
    slog("v15 LVN done", 0, 0);
}


// ---------------------------------------------------------------------------
// v17 "LVM": ROM EvfCaptureSystem.c (0xfc145266..) captures the normal LV raw
// in k passes: each pass = one CH12 run (xb = line bytes, yb = lines-1,
// off1a = line bytes * (k-1): one line every k lines), restarted by its CBR
// (0xfc1451dc counts passes up to [job+0x14]) at the next start offset from
// a table ([job+0x24]). So the head delivers the frame in pieces, which is
// what probe53/54 saw (~270 coherent lines, then other bands, stall > 384).
// v17: (1) dump Canon's EVF job/state (RAM 0x697e0 and 0xc8f0, 0x60 words
// each) to learn k, sizes and offsets of its last run; (2) LVM_PASS
// consecutive 256-line passes, re-armed immediately (abort, reprogram, start),
// each written to its own slot, stop at the first stall -> A/LVM.BIN.
// ---------------------------------------------------------------------------
#define LVM_PASS   8
#define LVM_LINES  256
typedef struct {
    char     magic[8];      // "M10LVM01"
    unsigned w, lines, lb, npass, ndone;
    unsigned r6804, r6800, r6008, r6014;
    unsigned dt[LVM_PASS], st[LVM_PASS], endp[LVM_PASS], gap[LVM_PASS];
    unsigned evf_job[0x60], evf_st[0x60];
} lvm_hdr;
static lvm_hdr lmh;

static void __attribute__((unused)) lv_multi(void)
{
    exmem_alloc_info ai;
    char *buf, *p = msg;
    unsigned phys, i, k, s14, s74, off, prev_end = 0;
    int fd, ok = 1;

    msg[0] = 0;
    memset(&lmh, 0, sizeof(lmh));
    memcpy(lmh.magic, "M10LVM01", 8);
    lmh.w = LVN_W; lmh.lines = LVM_LINES; lmh.lb = LVN_LB; lmh.npass = LVM_PASS;
    lmh.r6804 = shamem(0xc0f06804); lmh.r6800 = shamem(0xc0f06800);
    lmh.r6008 = shamem(0xc0f06008); lmh.r6014 = shamem(0xc0f06014);
    memcpy(lmh.evf_job, (void *)0x000697e0, sizeof(lmh.evf_job));
    memcpy(lmh.evf_st, (void *)0x0000c8f0, sizeof(lmh.evf_st));
    slog("v17 LVM start 6804=%08x", lmh.r6804, 0);
    if (!ch12_idle()) { strcpy(msg, "LVM: CH12 occupe"); return; }
    buf = exmem_alloc_uncached(EXMEM_TYPE, EXMEM_SIZE, &ai);
    if (!buf) { strcpy(msg, "EXMEM refuse"); return; }
    phys = (unsigned)buf & 0x3fffffff;
    memset(buf, 0xee, LVM_PASS * LVM_LINES * LVN_LB);

    ((fn1)FN_RES_LOCK)((unsigned)reslist);
    for (i = 0; i < NCHREGS; i++) chsaved[i] = shamem(CH12_BASE + chregs[i]);
    if (((fn0)FN_PK_TAKE)() != 0) {
        ((fn1)FN_RES_UNLOCK)((unsigned)reslist);
        exmem_free_uncached(EXMEM_TYPE); strcpy(msg, "LVM: PACK32 occupe"); return;
    }
    s14 = shamem(0xc0f37014);
    s74 = shamem(0xc0f37074);
    for (i = 0; i < NPK; i++) pk_saved[i] = shamem(pk_regs[i]);
    ch12_flags = 0x40000000;
    ((fn2)FN_PK_ON)(14, 2);
    eng_out(CH12_XBAR, 0x00);
    for (k = 0; k < LVM_PASS; k++) {
        unsigned dt = 0, st;
        if (k) {
            int t = get_tick_count();
            eng_out(CH12_BASE, 2);
            while (REG(CH12_BASE) != 0 && get_tick_count() - t < 50) ;
            if (REG(CH12_BASE) != 0) { ok = 0; break; }
        }
        eng_out(CH12_BASE + 0x40, 0);
        eng_out(CH12_BASE + 0x04, ch12_flags);
        eng_out(CH12_BASE + 0x08, phys + k * LVM_LINES * LVN_LB);
        eng_out(CH12_BASE + 0x0c, 0);
        eng_out(CH12_BASE + 0x14, 0);
        eng_out(CH12_BASE + 0x10, ((LVM_LINES - 1) << 16) | LVN_LB);
        for (off = 0x18; off <= 0x28; off += 4) eng_out(CH12_BASE + off, 0);
        st = ch12_run(&dt);
        lmh.dt[k] = dt; lmh.st[k] = st;
        lmh.endp[k] = REG(CH12_BASE + 8) - (phys + k * LVM_LINES * LVN_LB);
        if (k) lmh.gap[k] = udiff(prev_end, u_start);
        prev_end = u_end;
        lmh.ndone = k + 1;
        if (st) { ok = 0; break; }
    }
    if (!ch12_stop()) ok = -1;
    ((fn0)FN_PK_OFF)();
    eng_out(0xc0f37014, s14);
    eng_out(0xc0f37074, s74);
    for (i = 0; i < NPK; i++) eng_out(pk_regs[i], pk_saved[i]);
    for (i = 0; i < NCHREGS; i++) eng_out(CH12_BASE + chregs[i], chsaved[i]);
    ((fn1)FN_RES_UNLOCK)((unsigned)reslist);
    for (k = 0; k < lmh.ndone; k++) slog("LVM pass %d dt=%d", k, lmh.dt[k]), slog("   st=%d end=+%x", lmh.st[k], lmh.endp[k]);
    fd = open("A/LVM.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (fd >= 0) { write(fd, &lmh, sizeof(lmh)); write(fd, buf, LVM_PASS * LVM_LINES * LVN_LB); close(fd); }
    exmem_free_uncached(EXMEM_TYPE);
    p += sprintf(p, "LVM %d/%d passes %s", lmh.ndone, LVM_PASS, ok > 0 ? "ok" : (ok == 0 ? "STALL" : "BLOQ"));
    slog("v17 LVM done ok=%d", ok, 0);
}

// ---------------------------------------------------------------------------
// v18 "LVM2": ROM study (EvfCaptureSystem.c, Imager.c, PreProCommon.c):
//  - Canon runs EVF raw captures only as one-shot jobs (AE on clock change,
//    still / test / flash / WB / defect captures), never continuously in LV;
//  - the PACK32 semaphore (#6, 0xfc34d472) is taken with a 1000 ms timeout
//    and an assert (PreProCommon.c 0x163) by many Canon blocks (FldCreat,
//    TgCtrl, BadDefect, SusieDarkShading, PreProMem2Mem);
//  - CH12 completion interrupts are dispatched through the EDMAC CBR table
//    0x1bf018 (3 words per channel: cbr, arg, armed), installed by
//    0xfc376066 and removed by 0xfc3760a4; a Canon CBR left armed would run
//    on each of our completions.
// v18 therefore: each pass is an isolated capture (full take/release of
// resources and PACK32, hold < 70 ms, ch12_idle ~100 ms between), the CH12
// CBR entry is logged before/after every pass, and a 3 s heartbeat after
// the run dates a possible power-off. LVM2_PASS x 256 lines -> A/LVM2.BIN.
// ---------------------------------------------------------------------------
#define LVM2_PASS  16
#define CBR_TAB    0x001bf018
#define CBR_CH12   (CBR_TAB + 12 * 12)
typedef struct {
    char     magic[8];      // "M10LVM02"
    unsigned w, lines, lb, npass, ndone;
    unsigned r6804, r6800, r6008, r6014, dss_w, dss_h;
    unsigned cbr0[3];       // CH12 CBR entry before the run
    unsigned dt[LVM2_PASS], st[LVM2_PASS], endp[LVM2_PASS], tick[LVM2_PASS];
    unsigned cbr[LVM2_PASS][3];     // after each pass
} lvm2_hdr;
static lvm2_hdr lm2;

static void lv_multi2(void)
{
    exmem_alloc_info ai;
    char *buf;
    unsigned phys, k, i;
    int fd, ok = 1;

    msg[0] = 0;
    memset(&lm2, 0, sizeof(lm2));
    memcpy(lm2.magic, "M10LVM02", 8);
    lm2.w = LVN_W; lm2.lines = LVM_LINES; lm2.lb = LVN_LB; lm2.npass = LVM2_PASS;
    lm2.r6804 = shamem(0xc0f06804); lm2.r6800 = shamem(0xc0f06800);
    lm2.r6008 = shamem(0xc0f06008); lm2.r6014 = shamem(0xc0f06014);
    lm2.dss_w = *(volatile unsigned *)0x001beb5c; lm2.dss_h = *(volatile unsigned *)0x001beb60;
    memcpy(lm2.cbr0, (void *)CBR_CH12, 12);
    slog("v24 LVM2 start 6804=%08x sleep=%d", shamem(0xc0f06804), lvm_sleep);
    slog("  37014=%08x 37074=%08x", shamem(0xc0f37014), shamem(0xc0f37074));
    slog("  e558=%d e55c=%d", *(volatile unsigned *)0x0000e558, *(volatile unsigned *)0x0000e55c);
    slog("  tg=%d is=%08x", *(volatile unsigned *)0x0000e664, (*(volatile unsigned *)0x00008654 << 16) | (*(volatile unsigned *)0x00008658 & 0xffff));
    slog("  cbr12 %08x %08x", lm2.cbr0[0], lm2.cbr0[1]);
    slog("  cbr12 armed=%d", lm2.cbr0[2], 0);
    buf = exmem_alloc_uncached(EXMEM_TYPE, EXMEM_SIZE, &ai);
    if (!buf) { strcpy(msg, "EXMEM refuse"); return; }
    phys = (unsigned)buf & 0x3fffffff;
    memset(buf, 0xee, LVM2_PASS * LVM_LINES * LVN_LB);

    for (k = 0; k < LVM2_PASS; k++) {
        unsigned dt = 0, endp = 0, off = k * LVM_LINES * LVN_LB;
        int r;
        if (shamem(0xc0f06804) == 0 || *(volatile unsigned *)DSS_FLAGS == 0) { ok = -2; break; }
        r = lvn_cap(buf + off, phys + off, LVM_LINES, &dt, &endp);   // isolated hold
        lm2.dt[k] = dt; lm2.st[k] = (unsigned)r; lm2.endp[k] = endp - (phys + off);
        lm2.tick[k] = get_tick_count();
        memcpy(lm2.cbr[k], (void *)CBR_CH12, 12);
        // v21: Canon sensor-chain state after each pass: TG state
        // ([0xe664], 3 = running), ImgSens task state (0x8654, 0x8658)
        lm2.cbr[k][1] = *(volatile unsigned *)0x0000e664;
        lm2.cbr[k][2] = (*(volatile unsigned *)0x00008654 << 16) | (*(volatile unsigned *)0x00008658 & 0xffff);
        lm2.ndone = k + 1;
        if (r <= 0) { ok = r; break; }              // one stall ends the session
        msleep(20);
    }
    for (k = 0; k < lm2.ndone; k++) slog("LVM2 pass %d dt=%d", k, lm2.dt[k]), slog("   st=%d tg=%d", lm2.st[k], lm2.cbr[k][1]);
    fd = open("A/LVM2.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (fd >= 0) { write(fd, &lm2, sizeof(lm2)); write(fd, buf, LVM2_PASS * LVM_LINES * LVN_LB); close(fd); }
    exmem_free_uncached(EXMEM_TYPE);
    sprintf(msg, "LVM2 %d/%d %s", lm2.ndone, LVM2_PASS, ok > 0 ? "ok" : (ok == 0 ? "STALL" : (ok == -2 ? "LV perdue" : "err")));
    slog("v24 LVM2 done ok=%d", ok, 0);
    // heartbeat: dates a power-off relative to the end of the run
    for (i = 0; i < 12; i++) {
        msleep(250);
        slog("  hb 6804=%08x dss=%x", shamem(0xc0f06804), *(volatile unsigned *)DSS_FLAGS);
    }
    slog("  hb end cbr12=%08x", *(volatile unsigned *)CBR_CH12, 0);
}

// ---------------------------------------------------------------------------
// v23 "LVW": passive watch, NO lock, NO PACK32, NO DMA. probe56-60: the
// fatal (ImgSens 0x100000, TG restart not acknowledged) needs a real CH12
// transfer; probe18: Canon powers CH12 in normal LV (not in zoom x5). Is
// Canon itself using CH12 (or its crossbar) in normal LV, and when does it
// restart the sensor? For 6 s, every ~1 ms: CH12 ctl/addr/size, crossbar,
// TG state [0xe664], ImgSens flags; one record per change -> A/LVW.BIN.
// ---------------------------------------------------------------------------
#define LVW_N 4000
typedef struct { unsigned t_us, tick, ctl, addr, xbar, tg, sz; } lvw_rec;
static lvw_rec lvw[LVW_N];
static void __attribute__((unused)) lv_watch(void)
{
    unsigned n = 0, k, t0 = get_tick_count(), u0 = usec(), uacc = 0, ulast = u0;
    lvw_rec cur, prev;
    int fd;
    memset(&prev, 0xff, sizeof(prev));
    slog("v23 LVW start 6804=%08x", shamem(0xc0f06804), 0);
    while (get_tick_count() - t0 < 6000 && n < LVW_N) {
        unsigned u = usec();
        uacc += udiff(ulast, u); ulast = u;
        cur.ctl = REG(CH12_BASE);
        cur.addr = REG(CH12_BASE + 8);
        cur.sz = REG(CH12_BASE + 0x10);
        cur.xbar = shamem(CH12_XBAR);
        cur.tg = *(volatile unsigned *)0x0000e664;
        if (cur.ctl != prev.ctl || cur.addr != prev.addr || cur.xbar != prev.xbar
            || cur.tg != prev.tg || cur.sz != prev.sz) {
            cur.t_us = uacc; cur.tick = get_tick_count();
            lvw[n++] = cur; prev = cur;
        }
        msleep(1);
    }
    fd = open("A/LVW.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (fd >= 0) { write(fd, "M10LVW01", 8); write(fd, &n, 4); write(fd, lvw, n * sizeof(lvw_rec)); close(fd); }
    for (k = 0; k < n && k < 40; k++) slog("  %d tg=%d", lvw[k].tick, lvw[k].tg), slog("    ctl=%x addr=%08x", lvw[k].ctl, lvw[k].addr);
    sprintf(msg, "LVW %d changements", n);
    slog("v23 LVW done n=%d", n, 0);
}

// v28: watch after a pass
#define XW_N 64                    // v180e: 3000 -> 64 (-185 KiB BSS : module chargeable depuis un script Lua autonome)
typedef struct { unsigned tick, us, sio, tg, tgc[4], is[8]; } xw_rec;
static xw_rec xw[XW_N];
static unsigned xw_n;
static unsigned sio_idx(void)
{
    unsigned p = *(volatile unsigned *)0x00009b50, b;
    if (p == 0x121) return 0;
    b = (p & ~1u) - 0x10;
    return sio_base() ? *(volatile unsigned *)(b + 0x204) : 0;   // v59
}
static void x3_watch(unsigned ms)
{
    unsigned t0 = get_tick_count(), u0 = usec(), uacc = 0, ulast = u0, tsio = 0, j;
    xw_rec cur, prev;
    memset(&prev, 0xff, sizeof(prev));
    xw_n = 0;
    while (get_tick_count() - t0 < ms && xw_n < XW_N) {
        unsigned u = usec(), ch;
        uacc += udiff(ulast, u); ulast = u;
        cur.tg = *(volatile unsigned *)0x0000e664;
        for (j = 0; j < 4; j++) cur.tgc[j] = *(volatile unsigned *)(0x0000e660 + 4 * j);
        for (j = 0; j < 8; j++) cur.is[j] = *(volatile unsigned *)(0x00008650 + 4 * j);
        cur.sio = sio_idx();
        ch = memcmp(cur.tgc, prev.tgc, sizeof(cur.tgc)) || memcmp(cur.is, prev.is, sizeof(cur.is)) || cur.tg != prev.tg;
        if (ch || uacc - tsio >= 20000) {
            tsio = uacc;
            cur.tick = get_tick_count() - t0; cur.us = uacc;
            xw[xw_n++] = cur; prev = cur;
        }
        msleep(1);
    }
}

// ---------------------------------------------------------------------------
// v25 "LVX3": Film / 1x3 raw probe (see header). Same isolated pass as
// lv_multi2 (lvn_cap: lock, PACK32 on, one CH12 block, masked restore,
// release) but the pass count / size come from A/M10X3.CFG, and a 3 s watch
// of the TG state after the last pass dates any ImgSens shutdown.
// ---------------------------------------------------------------------------
// v37: continuous recording. Capture (this task, synced, one pass per sensor
// frame) fills EXMEM slots; xr_task (prio 0x19) writes them to A/M10X3.RAW
// (512-byte lvm2_hdr then raw frames). Slot busy -> frame dropped (counted).
#define XR_MAX 3000
static volatile unsigned xr_prod, xr_wr, xr_stop, xr_done, xr_err;
static int xr_fd, xr_sem;
static char *xr_buf;
static unsigned xr_chunk = 0x20000, xr_gated = 0, xr_wlen;
static unsigned xr_fb, xr_nslot, xr_slot[XR_MAX], xr_wus[XR_MAX], xr_tick[XR_MAX];
static volatile unsigned xr_last_drop_ms = 0;   // v183: last ring-full drop (REC preview backs off 500 ms)
static unsigned short xr_drop_at[XR_MAX];       // v183: ring drops before captured frame k (6 KiB)
static unsigned long long xr_vidf_us(unsigned k)   // v183: m1 VIDF timestamp on the 24.00p slot grid
{
    if (x_m1 && lj_on && k < XR_MAX) return (unsigned long long)(k + xr_drop_at[k]) * (unsigned long long)(x_per ? x_per : 41666u);
    return (unsigned long long)(k < XR_MAX ? xr_tick[k] : 0) * 1000ULL;
}
// v55: MLV output. Slot layout in EXMEM: [512: VIDF header + frameSpace]
// [frame][NULL block up to the next 512] -> one aligned write per frame.
static unsigned xr_mlv = 0, xr_stride, xr_nullsz, xr_t0us, xr_us_acc, xr_us_last;
static unsigned char mlv_hdr[512];
static void put16(unsigned char *p, unsigned v) { p[0] = v; p[1] = v >> 8; }
static void put32(unsigned char *p, unsigned v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }
static unsigned char *mlv_blk(unsigned char *p, const char *t, unsigned size)
{
    memcpy(p, t, 4); put32(p + 4, size); put32(p + 8, 0); put32(p + 12, 0);
    return p + 16;
}
static unsigned mlv_fps1000 = 25000;    // v89r: measured at the end (frames / wall ms), 25000 until then
static unsigned x_skipn = 0, x_skips = 0, x_skip_fr = 0;
// v93: PACK32 pack-2 10-bit stream (MSB-first u16 words) -> same layout at 14 bits (sample << 4).
// 8 samples = 5 words in, 7 words out. n = samples, multiple of 8.
static void conv_10_14(const unsigned short *src, unsigned short *dst, unsigned n)
{
    unsigned i;
    for (i = 0; i < n; i += 8) {
        unsigned w0 = src[0], w1 = src[1], w2 = src[2], w3 = src[3], w4 = src[4];
        unsigned t0 = (w0 >> 6) << 4, t1 = (((w0 & 0x3f) << 4) | (w1 >> 12)) << 4;
        unsigned t2 = ((w1 >> 2) & 0x3ff) << 4, t3 = (((w1 & 3) << 8) | (w2 >> 8)) << 4;
        unsigned t4 = (((w2 & 0xff) << 2) | (w3 >> 14)) << 4, t5 = ((w3 >> 4) & 0x3ff) << 4;
        unsigned t6 = (((w3 & 0xf) << 6) | (w4 >> 10)) << 4, t7 = (w4 & 0x3ff) << 4;
        dst[0] = (t0 << 2) | (t1 >> 12);
        dst[1] = ((t1 & 0xfff) << 4) | (t2 >> 10);
        dst[2] = ((t2 & 0x3ff) << 6) | (t3 >> 8);
        dst[3] = ((t3 & 0xff) << 8) | (t4 >> 6);
        dst[4] = ((t4 & 0x3f) << 10) | (t5 >> 4);
        dst[5] = ((t5 & 0xf) << 12) | (t6 >> 2);
        dst[6] = ((t6 & 3) << 14) | t7;
        src += 5; dst += 7;
    }
}
// v94: 16 samples per step: 5 u32 in (10 u16), 7 u32 out (14 u16), sample << sh (0 = ML-style 10 bits in a
// 14-bit container: the encoder's SSSS categories shrink by 4, sh 4 = full-scale 14 bits).
static unsigned x_csh = 4, x_unpk = 0, x_unpk_set = 0, x_j9c = 0;   // v97
static void __attribute__((optimize("O3"))) conv_10_14f(const unsigned *src, unsigned *dst, unsigned n, unsigned sh)
{
    unsigned i;
    for (i = 0; i < n; i += 16) {
        unsigned short w[10], o[14];
        unsigned t[16], j, k;
        unsigned a0 = src[0], a1 = src[1], a2 = src[2], a3 = src[3], a4 = src[4];
        w[0] = a0; w[1] = a0 >> 16; w[2] = a1; w[3] = a1 >> 16; w[4] = a2; w[5] = a2 >> 16;
        w[6] = a3; w[7] = a3 >> 16; w[8] = a4; w[9] = a4 >> 16;
        for (j = 0, k = 0; j < 16; j += 8, k += 5) {
            unsigned w0 = w[k], w1 = w[k + 1], w2 = w[k + 2], w3 = w[k + 3], w4 = w[k + 4];
            t[j] = w0 >> 6; t[j + 1] = ((w0 & 0x3f) << 4) | (w1 >> 12);
            t[j + 2] = (w1 >> 2) & 0x3ff; t[j + 3] = ((w1 & 3) << 8) | (w2 >> 8);
            t[j + 4] = ((w2 & 0xff) << 2) | (w3 >> 14); t[j + 5] = (w3 >> 4) & 0x3ff;
            t[j + 6] = ((w3 & 0xf) << 6) | (w4 >> 10); t[j + 7] = w4 & 0x3ff;
        }
        for (j = 0; j < 16; j++) t[j] <<= sh;
        for (j = 0, k = 0; j < 16; j += 8, k += 7) {
            o[k] = (t[j] << 2) | (t[j + 1] >> 12);
            o[k + 1] = ((t[j + 1] & 0xfff) << 4) | (t[j + 2] >> 10);
            o[k + 2] = ((t[j + 2] & 0x3ff) << 6) | (t[j + 3] >> 8);
            o[k + 3] = ((t[j + 3] & 0xff) << 8) | (t[j + 4] >> 6);
            o[k + 4] = ((t[j + 4] & 0x3f) << 10) | (t[j + 5] >> 4);
            o[k + 5] = ((t[j + 5] & 0xf) << 12) | (t[j + 6] >> 2);
            o[k + 6] = ((t[j + 6] & 3) << 14) | t[j + 7];
        }
        for (j = 0; j < 7; j++) dst[j] = o[2 * j] | ((unsigned)o[2 * j + 1] << 16);
        src += 5; dst += 7;
    }
}
static unsigned x_enc = 0;   // v92: 20th CFG field: run the lossless encoder on pass 0 (12 or 14 = input bpp)   // v91: REC chained: after every N captured frames, leave one sensor frame to Canon (19th CFG field)
static unsigned x_skipy = 0;            // v90: RAWC skipping_y (0 = 1x3 all lines, 2 = Film 3x3: 1 line of 3), 18th CFG field
static unsigned lj_eoff;   // v159: tentative (defined with the LJ state below)
static unsigned mlv_crop = 0;   // v159: MLV describes the encoder window (EW/EH/EOFF), not the whole frame
static unsigned mlv_guid_lo = 0;
static void mlv_build_hdr(unsigned w, unsigned h, unsigned bpp, unsigned nframes)
{
    static const int cm[9] = { 6400, -480, -888, -5294, 13416, 2047, -1296, 2203, 6137 };
    unsigned char *p = mlv_hdr, *q;
    unsigned i, pitch = w * bpp / 8, used;
    if (!mlv_guid_lo) mlv_guid_lo = get_tick_count();
    memset(mlv_hdr, 0, sizeof(mlv_hdr));
    memcpy(p, "MLVI", 4); put32(p + 4, 52); memcpy(p + 8, "v2.0", 4);
    put32(p + 16, mlv_guid_lo); put32(p + 20, 0x4d313078);           // persistent GUID across chunks
    put16(p + 24, 0); put16(p + 26, 1); put32(p + 28, 0);
    put16(p + 32, 1); put16(p + 34, 0);                                // RAW, no audio
    put32(p + 36, nframes); put32(p + 40, 0); put32(p + 44, mlv_fps1000); put32(p + 48, 1000);
    p += 52;
    q = mlv_blk(p, "RAWI", 180);
    put16(q, w); put16(q + 2, h); q += 4;
    put32(q, 1); put32(q + 4, 0); put32(q + 8, h); put32(q + 12, w); put32(q + 16, pitch);
    put32(q + 20, pitch * h); put32(q + 24, bpp);
    put32(q + 28, 128u << (bpp - 10)); put32(q + 32, (1u << bpp) - 1);
    put32(q + 36, 0); put32(q + 40, 0); put32(q + 44, w); put32(q + 48, h);       // crop
    {   // active y1 x1 y2 x2 (v90: Film 3x3 rows 3-27 = optical black -> y1 = 28; v180: ImgMode 1 auto OB)
        unsigned y1 = (x_skipy || x_zoom) ? 28 : 4, x1 = 72;   // v159: zoom has 28 optical-black rows too
        if (x_m1) {
            unsigned h6800 = shamem(0xc0f06800);
            y1 = ((h6800 >> 16) >= 32) ? 0 : 26;
            x1 = ((h6800 & 0xffff) >= 0x30) ? 0 : 72;
        }
        if (mlv_crop) { unsigned r0 = lj_eoff / lvn_lb, c0 = (lj_eoff % lvn_lb) * 8 / lvn_bpp; y1 = r0 >= y1 ? 0 : y1 - r0; x1 = c0 >= x1 ? 0 : x1 - c0; }   // v159: encoder window
        put32(q + 52, y1); put32(q + 56, x1); put32(q + 60, y1 + (h - y1) / 2 * 2); put32(q + 64, w);
    }
    put32(q + 68, 0); put32(q + 72, 0);
    put32(q + 76, 0x02010100); put32(q + 80, 21);
    for (i = 0; i < 9; i++) { put32(q + 84 + 8 * i, (unsigned)cm[i]); put32(q + 88 + 8 * i, 10000); }
    put32(q + 156, 1100);
    p += 180;
    q = mlv_blk(p, "RAWC", 32);
    put16(q, 5184); put16(q + 2, 3456); put16(q + 4, 162); put16(q + 6, 0);
    q[8] = (x_zoom || x_m1) ? 1 : 3; q[9] = 0; q[10] = 1; q[11] = x_skipy;   // v158/v180: 1:1 in magnifier & ImgMode 1
    p += 32;
    q = mlv_blk(p, "IDNT", 84);
    memcpy(q, "Canon EOS M10", 13); put32(q + 32, 0x80000355);
    p += 84;
    used = p - mlv_hdr;
    mlv_blk(p, "NULL", 512 - used);
}
static void mlv_frame_hdr(unsigned char *p, unsigned k, unsigned fb, unsigned ts_us)
{
    memset(p, 0, 512);
    memcpy(p, "VIDF", 4); put32(p + 4, 512 + fb); put32(p + 8, ts_us); put32(p + 12, 0);
    put32(p + 16, k); put32(p + 28, 512 - 32);                         // frameSpace
    p += 512 + fb;
    memcpy(p, "NULL", 4); put32(p + 4, xr_nullsz); put32(p + 8, 0); put32(p + 12, 0);
}

static unsigned xr_fbytes, xr_fileno, xr_fcount[16], xr_chunk_start = 0;
static char xr_base[16] = "A/M10X3";   // v160: take base name (A/M10_0001 in shell mode)
static unsigned xr_roll_ms = 0, xr_roll_n = 0, xr_roll_fr = 0, xr_roll_drops = 0;   // v182: chunk switch cost (max ms), count, frame, ring drops at the 1st roll
static void xr_roll_close(void);
static void xr_roll(void)                   // v57: FAT32: < 4 GiB per file, ML-style chunks
{
    unsigned t0 = get_tick_count(), dt;
    if (!xr_roll_n) { xr_roll_fr = xr_wr; xr_roll_drops = x_dr[0]; }
    xr_roll_close();
    dt = get_tick_count() - t0;
    if (dt > xr_roll_ms) xr_roll_ms = dt;
    xr_roll_n++;
}
static void xr_roll_close(void)
{
    char nm[24];
    close(xr_fd);
    if (xr_fileno < 16) { xr_fcount[xr_fileno] = xr_wr - xr_chunk_start; xr_chunk_start = xr_wr; }
    xr_fileno++;
    sprintf(nm, "%s.M%02u", xr_base, xr_fileno - 1);
    xr_fd = open(nm, O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (xr_fd < 0) { xr_err = 2; return; }
    put16(mlv_hdr + 24, xr_fileno);
    put32(mlv_hdr + 36, 0);
    write(xr_fd, mlv_hdr, 512);
    xr_fbytes = 512;
}
static void mlv_finalize(unsigned w, unsigned h, unsigned bpp, int lj_class)   // v167: write finalized fps, fileCount and per-chunk videoFrameCount
{
    unsigned nfiles = xr_fileno + (xr_fd >= 0 ? 1 : 0), c;
    if (xr_fileno == 0 && xr_fd >= 0) {
        mlv_build_hdr(w, h, bpp, xr_wr);
        if (lj_class) put16(mlv_hdr + 32, 0x21);
        lseek(xr_fd, 0, SEEK_SET);
        write(xr_fd, mlv_hdr, 512);
        close(xr_fd);
        xr_fd = -1;
        return;
    }
    if (xr_fd >= 0) {
        if (xr_fileno < 16) xr_fcount[xr_fileno] = xr_wr - xr_chunk_start;
        close(xr_fd);
        xr_fd = -1;
    }
    if (nfiles > 16) nfiles = 16;
    if (!nfiles) return;
    mlv_build_hdr(w, h, bpp, 0);
    if (lj_class) put16(mlv_hdr + 32, 0x21);
    put16(mlv_hdr + 26, nfiles);
    for (c = 0; c < nfiles; c++) {
        char nm[24];
        int f;
        if (c == 0) sprintf(nm, "%s.MLV", xr_base);
        else sprintf(nm, "%s.M%02u", xr_base, c - 1);
        put16(mlv_hdr + 24, c);
        put32(mlv_hdr + 36, xr_fcount[c]);
        f = open(nm, O_RDWR, 0777);   // v182: no stdio (no FILE / buffer allocation from the CHDK heap)
        if (f >= 0) { lseek(f, 0, SEEK_SET); write(f, mlv_hdr, 512); close(f); }
    }
}
// v101: compressed REC. Raw ring: xr_nslot slots of xr_fb bytes from buf (captured by lvn_cap).
// Encoder task: raw slot k -> compressed ring slot (MLV VIDF header + LJ92 + NULL padding to 512),
// lj_cnt = frames encoded; the writer then writes compressed slots. Capture drops a frame if the
// raw slot it would overwrite is not yet encoded.
static unsigned lj_raw_n, lj_cslot_sz, lj_cslot_n, lj_cbase, lj_gate = 0;   // v103
static unsigned lj_wlo = 0, lj_whi = 0, lj_ph[512];   // v105: encoder start window (us after 8830), start phase per frame
static volatile unsigned lj_err = 0, lj_done = 0;   // v124: lj_cnt moved up
#define LJ_N 512
static unsigned lj_sz[LJ_N], lj_us[LJ_N], lj_t0;   // v114: smaller (module BSS must fit CHDK's free heap)
static int lj_sem;
static unsigned char *lj_buf; static unsigned lj_phys;
static unsigned lj_gap = 0, lj_new_win = 0;   // v113: busy gap (us) between slices; v115: each slice in a new 8830 window
static unsigned lj_ns = 1;   // v112: slices per frame (each an independent LJ92 stream; sizes in the VIDF frameSpace)
static unsigned lj_last_win = 0, lj_swlo = 0, lj_swhi = 0, lj_swch = 0x40000;   // v116: SD write window + chunk   // v115: 8830 of the window already used by the previous slice
static void lj_wait_win(void)
{
    unsigned tg0 = get_tick_count();
    if (!lj_whi) return;
    for (;;) {
        unsigned l8 = last_8830();
        if (lj_new_win && l8 == lj_last_win) { msleep(1); if (get_tick_count() - tg0 > 100 || xr_stop) break; continue; }   // v115: one slice per window
        int d = l8 ? sdiff(l8 & 0xfffff, usec()) : 0;
        while (d >= (int)x_per) d -= x_per;
        while (d < 0) d += x_per;
        if ((unsigned)d >= lj_wlo && (unsigned)d < lj_whi) { lj_last_win = l8; break; }
        if (get_tick_count() - tg0 > 100 || xr_stop) break;
        { unsigned togo = ((unsigned)d < lj_wlo) ? lj_wlo - d : x_per - d + lj_wlo; if (togo > 12000) msleep(1); }
    }
}
static volatile unsigned lj_kicked = 0;
static volatile unsigned lj_k_ok = 0, lj_k_no[4], lj_k_max = 0;   // v125: frame index + 1 whose encoder was started early
static unsigned lj_kwait = 8000;   // v138: us the kick waits for the previous encode (45th field)
static unsigned lj_swe = 0;        // v142: 47th field = 1: SD write waits for the encoder to be idle
static unsigned x_hbn = 6;         // v143: 48th field = head errors within 64 frames that stop REC (2..32)
static unsigned lj_eoff = 0;       // v139: encoder source byte offset in the raw frame (46th field), e.g. 28 rows * 2260 + 100 = active area
static unsigned x_exsz = EXMEM_SIZE;   // v149: 54th field = EXMEM size in MiB for lv_x3 (16..48): more compressed slots
static unsigned x_her = 0;         // v148: 53rd field = 1: no-pause head-error recovery (keep the frame, re-arm the IRQ, no 150 ms wait)
#define HE_ALL_N 1024
static unsigned x_he_all[HE_ALL_N];   // v148: every trapped error: (frame << 8) | status, written to A/M10HE.BIN
static unsigned x_he_late = 0;     // v148: failed passes absorbed right after an error (old wait used instead)
static unsigned x_he_fixed = 0, x_dup_us_max = 0;   // v172: 59th field (or shell): duplicate prev healthy frame on HEAD_ERR
static volatile unsigned lj_prev_sz = 0, lj_prev_tot = 0;
#define LJ_DUP_N 16
static volatile unsigned lj_dup_q[LJ_DUP_N], lj_dup_h = 0, lj_dup_t = 0;
// v173: logical frames may share an immutable compressed payload. Only the
// writer patches its header, immediately before the synchronous SD write.
#define LJ_MAP_N 16
static volatile unsigned lj_map[LJ_MAP_N];
static unsigned lj_slot(unsigned k) { return x_he_fix ? lj_map[k % lj_cslot_n] : k % lj_cslot_n; }
static unsigned lj_free_slot(void)
{
    unsigned cs, j, wr = xr_wr;   // stale lower wr only retains extra slots
    for (cs = 0; cs < lj_cslot_n; cs++) {
        if (lj_cnt && cs == lj_slot(lj_cnt - 1)) continue;   // retain predecessor even after SD write
        for (j = wr; j < lj_cnt; j++) if (lj_slot(j) == cs) break;
        if (j == lj_cnt) return cs;
    }
    return lj_cslot_n;
}

static void lj_vidf(unsigned k, unsigned sz)   // v127: VIDF header + NULL padding of compressed frame k
{
    unsigned cs = lj_slot(k);
    unsigned char *h = lj_buf + lj_cbase + cs * lj_cslot_sz;
    unsigned tot = (512 + sz + 16 + 511) & ~511u, nul = tot - 512 - sz;
    memset(h, 0, 512);
    memcpy(h, "VIDF", 4); put32(h + 4, 512 + sz); put32(h + 8, (unsigned)xr_vidf_us(k)); put32(h + 12, (unsigned)(xr_vidf_us(k) >> 32)); put32(h + 16, k); put32(h + 28, 480);
    h += 512 + sz; memcpy(h, "NULL", 4); put32(h + 4, nul); put32(h + 8, 0); put32(h + 12, 0);
    if (k < XR_MAX) xr_wus[k] = tot;
    lj_prev_sz = sz;
    lj_prev_tot = tot;
}
static int lj_collect(void)   // v127: finish the kicked encode if its CBR came; 1 = done (or none), 0 = still running, -1 = error
{
    unsigned k, sz, eus;
    if (!lj_kicked) return 1;
    if (!cb_done) return 0;
    k = lj_kicked - 1;
    tlf_set(k, 4, cb_us);   // v140
    sz = enc_end(&eus);
    lj_kicked = 0;
    if (k < LJ_N) { lj_sz[k] = sz; lj_us[k] = eus; }
    if (!sz) { lj_err = 2; return -1; }
    // v172b: a late HEAD_ERR may be registered after the early kick. Discard
    // that completed output; only the capture task collects, so it cannot
    // publish the bad frame before lv_x3 has registered the replacement.
    if (lj_dup_t < lj_dup_h && lj_dup_q[lj_dup_t % LJ_DUP_N] == k) {
        GiveSemaphore(lj_sem);
        return 1;
    }
    lj_vidf(k, sz);
    lj_cnt = k + 1;
    GiveSemaphore(xr_sem);
    return 1;
}
static void lj_kick(unsigned fr);
static void lj_drain(void)   // v167: flush remaining captured frames (lj_cnt < xr_prod) before xr_stop exits lj_task
{
    unsigned t = get_tick_count();
    while (lj_kicked && !cb_done && get_tick_count() - t < 3000) msleep(5);
    if (lj_kicked && !cb_done) { lj_err = 4; return; }
    lj_collect();
    if ((int)xr_prod > (int)x_ready) x_ready = xr_prod;
    while ((lj_cnt < xr_prod || lj_dup_t < lj_dup_h) && !lj_err && !xr_err && get_tick_count() - t < 10000) {
        unsigned before = lj_cnt;
        while ((int)(lj_cnt - xr_wr) >= (int)lj_cslot_n && !xr_err && get_tick_count() - t < 10000) {
            GiveSemaphore(xr_sem); msleep(5);
        }
        if (xr_err) break;
        lj_kick(lj_cnt);   // v172b: normal older frames may precede a queued duplicate
        if (lj_kicked) {
            while (!cb_done && get_tick_count() - t < 10000) msleep(2);
            if (!cb_done) { lj_err = 4; break; }
            lj_collect();
        } else if (lj_dup_t < lj_dup_h) {
            GiveSemaphore(lj_sem); msleep(2);
        } else if (lj_cnt == before && lj_cnt < xr_prod) { lj_err = 5; break; }
    }
    if (!lj_err && !xr_err && (lj_cnt < xr_prod || lj_dup_t < lj_dup_h)) lj_err = 5;
}
static void lj_kick(unsigned fr)
{
    unsigned rs, cs;
    { unsigned u0w = usec(); int rc;   // v138: previous encode often ends 0-5 ms after our DMA end: wait for it instead of skipping the kick
      while ((rc = lj_collect()) == 0 && udiff(u0w, usec()) < lj_kwait) ;
      if (rc <= 0) { lj_k_no[0]++; return; } }   // v127: previous one still running (or failed)
    if (lj_dup_t < lj_dup_h && lj_cnt >= lj_dup_q[lj_dup_t % LJ_DUP_N]) {
        // v172b: do not sleep in the capture path or block older good frames.
        // The worker publishes the duplicate before any subsequent encode.
        GiveSemaphore(lj_sem);
        return;
    }
    if (lj_ns != 1 || lj_kicked) { lj_k_no[0]++; return; }
    fr = lj_cnt;   // v126: oldest frame not yet encoded
    if (fr >= x_ready) { lj_k_no[1]++; return; }
    if (fr - xr_wr >= lj_cslot_n || fr >= XR_MAX) { lj_k_no[2]++; return; }   // only the next frame, one at a time, output slot free
    rs = xr_slot[fr] % lj_raw_n; cs = x_he_fix ? lj_free_slot() : fr % lj_cslot_n;
    if (cs >= lj_cslot_n) { lj_k_no[2]++; return; }
    if (x_he_fix) lj_map[fr % lj_cslot_n] = cs;
    enc_in_off = rs * xr_fb + lj_eoff; enc_out_off = lj_cbase + cs * lj_cslot_sz + 512; enc_out_size = lj_cslot_sz - 1024;   // v139: + source offset (active area only)
    { unsigned uk = usec();
    if (enc_begin((char *)lj_buf, lj_phys, 0)) { lj_kicked = fr + 1; lj_k_ok++; tlf_set(fr, 3, enc_u0); } else lj_k_no[3]++;   // v140
    uk = udiff(uk, usec()); if (uk > lj_k_max) lj_k_max = uk; }
}
static unsigned lj_async_n = 0;
static void lj_poll(void)   // v181: capture task only (sole collector): collect a finished encode, kick the oldest ready frame
{
    if (lj_err || xr_err || !x_kick) return;
    if (lj_kicked) { if (!cb_done) return; if (lj_collect() < 0) return; }
    if (!lj_kicked && lj_cnt < x_ready && lj_dup_t >= lj_dup_h) {
        unsigned ok0 = lj_k_ok, kw = lj_kwait;
        lj_kwait = 0; lj_kick(0); lj_kwait = kw;
        if (lj_k_ok != ok0) lj_async_n++;
    }
}
static void lj_task(void)
{
    for (;;) {
        if (x_kick) {   // v127: kick mode: the capture task starts and collects; v172: also copies HEAD_ERR duplicate slots
            while (lj_dup_t < lj_dup_h && !lj_err && !xr_err) {
                unsigned df = lj_dup_q[lj_dup_t % LJ_DUP_N];
                // v172b: capture is the sole encoder collector. Never wait here
                // for an older unstarted encode; it must be allowed to run first.
                if (lj_cnt < df || lj_kicked) break;
                if (lj_cnt != df || !df || lj_cslot_n < 2 || !lj_prev_tot || lj_prev_tot > lj_cslot_sz) { lj_err = 6; break; }
                if ((int)(df - xr_wr) >= (int)lj_cslot_n) { GiveSemaphore(xr_sem); break; }
                {
                    unsigned ud0 = usec(), udt;
                    // v173: no pixel copy, no header write while SD may read it.
                    // Ordered kick allocation retains the immediately preceding slot.
                    lj_map[df % lj_cslot_n] = lj_slot(df - 1);
                    if (df < XR_MAX) xr_wus[df] = lj_prev_tot;
                    if (df < LJ_N) { lj_sz[df] = lj_prev_sz; lj_us[df] = 0; }
                    udt = udiff(ud0, usec()); if (udt > x_dup_us_max) x_dup_us_max = udt;
                    lj_cnt = df + 1;
                    lj_dup_t++;
                    GiveSemaphore(xr_sem);
                }
            }
            // v172b: lj_drain in the capture task owns all tail collections.
            if (xr_stop && !lj_kicked && lj_dup_t >= lj_dup_h) break;
            if (lj_err || xr_err) break;
            TakeSemaphore(lj_sem, 20);
            continue;
        }
        if (lj_cnt < (x_ready > xr_prod ? x_ready : xr_prod) && !lj_err && !xr_err) {   // v121
            unsigned k = lj_cnt, rs = xr_slot[k] % lj_raw_n, cs = k % lj_cslot_n, eus = 0, sz = 0, j, hs, ssz[32], h0 = enc_h;
            while (k - xr_wr >= lj_cslot_n && !xr_err && !xr_stop) TakeSemaphore(xr_sem, 5);   // compressed slot still being written
            if (xr_err) break;
            if (lj_gate) { unsigned tg0 = get_tick_count(); while (!xr_gate && !xr_stop && get_tick_count() - tg0 < 60) ; }   // v103
            hs = (h0 / lj_ns) & ~1u;
            for (j = 0; j < lj_ns; j++) {
                unsigned e1 = 0, s1, hh = (j + 1 == lj_ns) ? h0 - hs * j : hs;
                if (j && lj_gap) { unsigned u0g = usec(); while (udiff(u0g, usec()) < lj_gap) ; }   // v113: let the head FIFO drain
                if (lj_gate == 2 && !(j == 0 && lj_kicked == k + 1)) {   // v119 (v125: not for a frame already started): slice starts only after a readout ended, never while one runs
                    unsigned tg0 = get_tick_count(), t1 = x_dma_t1;
                    if (j) while ((x_dma_t1 == t1 || x_dma_live) && !xr_stop && get_tick_count() - tg0 < 100) msleep(1);   // next slice: wait for the NEXT readout end
                    else { unsigned t1b = x_dma_t1; if (x_dma_live) while (x_dma_t1 == t1b && !xr_stop && get_tick_count() - tg0 < 100) { if (udiff(t1b, usec()) < 30000) msleep(1); } }   // v120: wait for this readout's end (sleep while far)
                }
                lj_wait_win();
                if (!j && k < 512) { unsigned l8 = last_8830(); int d = l8 ? sdiff(l8 & 0xfffff, usec()) : -1; while (d >= (int)x_per) d -= x_per; while (d < 0) d += x_per; lj_ph[k] = d; }   // v120: phase at encoder start
                enc_in_off = rs * xr_fb + j * hs * xr_fb / h0;      // line offset (xr_fb / h0 = bytes per line)
                enc_out_off = lj_cbase + cs * lj_cslot_sz + 512 + sz;
                enc_out_size = lj_cslot_sz - 1024 - sz;
                enc_h = hh;
                if (!j && lj_kicked == k + 1) { s1 = enc_end(&e1); lj_kicked = 0; }   // v125: started by the capture task at the DMA end
                else s1 = enc_frame((char *)lj_buf, lj_phys, 0, &e1);
                enc_h = h0;
                if (!s1) { sz = 0; break; }
                s1 = (s1 + 3) & ~3u;                                // keep each stream word aligned
                ssz[j] = s1; sz += s1; eus += e1;
            }
            if (k < LJ_N) { lj_sz[k] = sz; lj_us[k] = eus; }
            if (!sz) { lj_err = cb_done ? 2 : 3; break; }
            {   // VIDF header (frameSpace 480: "M10S", n, sizes...) + NULL padding
                unsigned char *h = lj_buf + lj_cbase + cs * lj_cslot_sz;
                unsigned tot = (512 + sz + 16 + 511) & ~511u, nul = tot - 512 - sz;
                memset(h, 0, 512);
                memcpy(h, "VIDF", 4); put32(h + 4, 512 + sz); put32(h + 8, (unsigned)xr_vidf_us(k)); put32(h + 12, (unsigned)(xr_vidf_us(k) >> 32)); put32(h + 16, k); put32(h + 28, 480);
                if (lj_ns > 1) { memcpy(h + 32, "M10S", 4); put32(h + 36, lj_ns); for (j = 0; j < lj_ns; j++) put32(h + 40 + 4 * j, ssz[j]); }
                h += 512 + sz; memcpy(h, "NULL", 4); put32(h + 4, nul); put32(h + 8, 0); put32(h + 12, 0);
                if (k < XR_MAX) xr_wus[k] = tot;
            }
            lj_cnt = k + 1;
            GiveSemaphore(xr_sem);
            continue;
        }
        if ((xr_stop && lj_cnt >= xr_prod) || lj_err || xr_err) break;
        TakeSemaphore(lj_sem, 2);
    }
    lj_done = 1;
    GiveSemaphore(xr_sem);
    ExitTask();
}
static void xr_task(void)
{
    for (;;) {
        if (lj_on && xr_wr < lj_cnt && !xr_err) {   // v101: compressed frames
            unsigned k = xr_wr, cs = lj_slot(k), t0 = usec(), len = (k < XR_MAX) ? xr_wus[k] : 0;
            char *p = (char *)lj_buf + lj_cbase + cs * lj_cslot_sz;
            if (xr_fbytes + len > 1900u * 1024 * 1024) xr_roll();
            if (xr_err) continue;
            if (xr_wlen < xr_fb && xr_wlen < len) len = xr_wlen;   // v102: wms KiB per frame (test: card load off)
            if (lj_swe) {   // v142: never write while the encoder runs (one DRAM client at a time on top of CH12 during a readout)
                unsigned tw = get_tick_count();
                while (lj_kicked && !cb_done && !xr_err && !(xr_stop && lj_done) && get_tick_count() - tw < 60) msleep(1);
                t0 = usec();
            }
            // v173: writer alone mutates a shared VIDF header; xr_wr remains
            // unchanged until every byte is written, protecting its physical slot.
            if (x_he_fix) { put32((unsigned char *)p + 8, (unsigned)xr_vidf_us(k)); put32((unsigned char *)p + 12, (unsigned)(xr_vidf_us(k) >> 32)); put32((unsigned char *)p + 16, k); }
            tlf_set(k, 5, t0);   // v140
            if (!len) xr_err = 1;
            else if (!lj_swhi) { if (write(xr_fd, p, len) != (int)len) xr_err = 1; }
            else {   // v116: chunks only while the sensor phase is inside [lo, hi] us after 8830
                unsigned o = 0, c, tw0 = get_tick_count();
                while (o < len && !xr_err) {
                    unsigned l8 = last_8830(); int d = l8 ? sdiff(l8 & 0xfffff, usec()) : 0;
                    while (d >= (int)x_per) d -= x_per;
                    while (d < 0) d += x_per;
                    if (l8 && ((unsigned)d < lj_swlo || (unsigned)d >= lj_swhi) && get_tick_count() - tw0 < 400 && !(xr_stop && lj_done)) { unsigned togo = ((unsigned)d < lj_swlo) ? lj_swlo - d : x_per - d + lj_swlo; if (togo > 11000) msleep(1); continue; }   // v117: bounded wait (v118: busy-poll the last 11 ms)
                    c = len - o; if (c > lj_swch) c = lj_swch;
                    if (write(xr_fd, p + o, c) != (int)c) xr_err = 1;
                    o += c; tw0 = get_tick_count();
                }
            }
            if (k < XR_MAX) xr_wus[k] = udiff(t0, usec());
            tlf_set(k, 6, usec());   // v140
            xr_fbytes += len;
            xr_wr = k + 1;
            GiveSemaphore(lj_sem);
            continue;
        }
        if (lj_on) {
            if (xr_stop && (lj_done || lj_err) && (xr_wr >= lj_cnt || xr_err)) break;
            TakeSemaphore(xr_sem, 20);
            continue;
        }
        if (xr_wr < xr_prod && !xr_err) {
            if (xr_mlv && xr_fbytes + xr_stride > 1900u * 1024 * 1024) xr_roll();   // v89n: < 2 GiB (CHDK PTP download + Lua seek are signed 32-bit)
            if (xr_err) continue;
            unsigned k = xr_wr, t0 = usec(), o, c;
            char *p = xr_buf + (xr_slot[k] % xr_nslot) * (xr_mlv ? xr_stride : xr_fb);
            unsigned wl = xr_mlv ? xr_stride : xr_wlen;
            for (o = 0; o < wl && !xr_err; o += c) {   // v39: chunks, only while no transfer runs
                c = wl - o; if (c > xr_chunk) c = xr_chunk;
                if (xr_gated) while (!xr_gate && !xr_stop) msleep(1);
                if (write(xr_fd, p + o, c) != (int)c) xr_err = 1;
            }
            if (k < XR_MAX) xr_wus[k] = udiff(t0, usec());
            xr_fbytes += xr_mlv ? xr_stride : xr_wlen;
            xr_wr = k + 1;
            continue;
        }
        if (xr_stop && (xr_wr >= xr_prod || xr_err)) break;
        TakeSemaphore(xr_sem, 20);
    }
    xr_done = 1;
    ExitTask();
}

// v63: EDMAC activity map, no capture at all. Samples the current address of
// every Canon EDMAC channel active in FHD + the SIO ring index every ~50 us
// for ms milliseconds; one record per change. -> A/LVX3E.BIN
static const unsigned em_ch[] = {
    0xc0f04008, 0xc0f04108, 0xc0f04308, 0xc0f04408, 0xc0f04608,
    0xc0f26008, 0xc0f26108, 0xc0f26208, 0xc0f26308, 0xc0f26608,
    0xc0f26808, 0xc0f26908, 0xc0f26a08, 0xc0f26b08, 0xc0f26c08, 0xc0f26d08,
    0xc0f30108, 0xc0f30208, 0xc0f30308, 0xc0f30608 };
#define EM_NCH (sizeof(em_ch) / sizeof(em_ch[0]))
static void edmac_map(char *buf, unsigned ms)
{
    unsigned *r = (unsigned *)buf, n = 0, maxn = (EXMEM_SIZE - 0x100000) / (4 * (2 + EM_NCH)), j;
    unsigned prev[EM_NCH], t0 = get_tick_count(), sb = sio_base(), fd;
    for (j = 0; j < EM_NCH; j++) prev[j] = 0xffffffff;
    while (get_tick_count() - t0 < ms && n < maxn) {
        unsigned cur[EM_NCH], ch = 0, u = usec();
        for (j = 0; j < EM_NCH; j++) { cur[j] = REG(em_ch[j]); if (cur[j] != prev[j]) ch = 1; }
        if (ch) {
            unsigned *q = r + n * (2 + EM_NCH);
            q[0] = u; q[1] = sb ? *(volatile unsigned *)(sb + 0x204) : 0;
            for (j = 0; j < EM_NCH; j++) { q[2 + j] = cur[j]; prev[j] = cur[j]; }
            n++;
        }
        while (udiff(u, usec()) < 50) ;
    }
    fd = open("A/LVX3E.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
    if (fd >= 0) {
        unsigned hd[4] = { 0x4d453358, n, EM_NCH, 0 };
        write(fd, hd, 16); write(fd, (void *)em_ch, sizeof(em_ch));
        write(fd, r, n * 4 * (2 + EM_NCH));
        if (sb) {           // + SIO ring for the time base
            unsigned nent = *(volatile unsigned *)(sb + 0x210) + 1, idx = *(volatile unsigned *)(sb + 0x204);
            if (nent > 0x1e00) nent = 0x1e00;
            write(fd, &idx, 4); write(fd, &nent, 4);
            write(fd, (void *)(sb + sio_ring), nent * 64);
        }
        close(fd);
    }
    slog("v63 edmac map n=%d ms=%d", n, ms);
}

static unsigned hex_u32(char **pq)   // v84b: strtol saturates at 0x7fffffff
{
    char *q = *pq; unsigned v = 0;
    while (*q == ' ' || *q == '\t') q++;
    for (;;) {
        char ch = *q; unsigned d;
        if (ch >= '0' && ch <= '9') d = ch - '0';
        else if (ch >= 'a' && ch <= 'f') d = ch - 'a' + 10;
        else if (ch >= 'A' && ch <= 'F') d = ch - 'A' + 10;
        else break;
        v = (v << 4) | d; q++;
    }
    *pq = q;
    return v;
}
/* v165: live B&W preview from our own RAW (shell, x5 magnifier). Same capture as REC (lvn_cap, 10-bit
 * PACK32 bitstream: u16 LE words, MSB first, offset 0), no encoder, no card. Each pass: one sensor frame,
 * then the recorded window (columns 192-2495, rows 28-1103) is sampled 2x2 (Bayer luma) onto the CHDK RGBA
 * overlay, 360 x 168 at y = PV_Y, with an auto black / gain / sqrt LUT. Stops on REC/SET (-> take), MENU,
 * magnifier exit, USB or repeated capture errors. */
#define PV_RGBA   ((unsigned *)(((0x41141000 + 960 * 270 * 3) + 0xff) & 0xffffff00))   // = lib.c CHDK_LAYER_BUF (chdk_rgba)
#define PV_BW     360
// v174: preview geometry is dynamic: thumbnail (bottom right, Canon x5 view stays visible for focus)
// or full frame (letterboxed 2048/1920 aspect between the HUD bars); toggled by DOWN.
static volatile unsigned pv_full = 0;
static unsigned PV_W = 172, PV_H = 80, PV_X = 360 - 172 - 4, PV_Y = 240 - 80 - 18;
static void pv_geom(void)
{
    if (pv_full) { PV_W = 352; PV_H = 184; PV_X = 4; PV_Y = 26; }
    else         { PV_W = 160; PV_H = 82;  PV_X = 360 - 160 - 4; PV_Y = 240 - 82 - 22; }
}
static unsigned char pv_lut[1024];
static int sh_usb(void);
static void sh_gui_assert(void);
extern void vid_bitmap_refresh();
typedef struct {
    unsigned char fps;
    unsigned char bpp;
    unsigned char rsel;
    unsigned char kind;            // v182: 0 = x5 magnifier, 1 = Film 1x3 (armed from PLAY, line 640), 2 = ImgMode 1 1440p
    unsigned short fl;
    unsigned short per;
    unsigned short c0;
    unsigned short w;
    const char *tag;
    unsigned short h;              // v185: ImgMode 1 frame lines (head = h + 16)
    unsigned short lclk;           // v185: ImgMode 1 TG line clock
    unsigned char m1_wide;         // v185: 1 = wide ImgMode 1 window (X0 0x30, CMOS 2/5/7 wide)
    unsigned short x0;             // v186b: ImgMode 1 CMOS X0 (window start)
    unsigned short c7;             // v186b: ImgMode 1 CMOS[7]
    unsigned char bpp_mask;        // v186b: supported depths: 1 = 10b, 2 = 12b, 4 = 14b
    const char *short_tag;         // v186b: 8-char SIZE label for the bottom bar
} sh_prof_t;
#define SH_X5 0
#define SH_X3 1
#define SH_M1 2
static const sh_prof_t sh_profs[] = {   // v186b: Magic Lantern-style Size x Bit-Depth, 100% ImgMode 1
    { 24, 14, 0x10, SH_M1, 1819, 41666, 0, 1920, "1920x1440 24p", 1440, 732, 0, 0x84, 0xac9, 7, "1440 4:3" },
    { 24, 14, 0x10, SH_M1, 1819, 41666, 0, 2048, "2048x1536 24p", 1536, 732, 0, 0x74, 0xac9, 7, "2K 4:3" },
    { 24, 14, 0x10, SH_M1, 1819, 41666, 0, 2160, "2160x1440 24p", 1440, 732, 0, 0x66, 0xac9, 7, "2.2K 3:2" },
    { 24, 14, 0x10, SH_M1, 1819, 41666, 0, 2304, "2304x1296 24p", 1296, 732, 0, 0x54, 0xa89, 7, "2.3K 169" },
    { 24, 14, 0x10, SH_M1, 1775, 41657, 0, 2592, "2592x1088 24p", 1088, 750, 0, 0x30, 0xa69, 7, "2.6K 2.4" },
    { 24, 14, 0x10, SH_M1, 2080, 41665, 0, 1728, "Wide 1800 24p", 1800, 640, 1, 0x30, 0xac6, 7, "Wide1800" },
    { 24, 14, 0x10, SH_M1, 1819, 41666, 0, 1728, "Wide 1440 24p", 1440, 732, 1, 0x30, 0xac9, 7, "Wide1440" },
    { 30, 14, 0x10, SH_M1, 1455, 33328, 0, 1920, "1920x1080 30p", 1080, 732, 0, 0x84, 0xa8a, 7, "1080 30p" },
    { 24, 10, 0x10, SH_M1, 1819, 41666, 0, 2304, "2304x1536 24p", 1536, 732, 0, 0x54, 0xac9, 1, "2.3K 3:2" },
    { 24, 10, 0x10, SH_M1, 1775, 41657, 0, 2592, "2592x1440 24p", 1440, 750, 0, 0x30, 0xac9, 1, "2.6K 1.8" },
};
#define SH_NPROF (sizeof(sh_profs) / sizeof(sh_profs[0]))
static volatile unsigned sh_prof_idx = 0, sh_armed_fps = 0;
static volatile unsigned sh_field = 0;   // v186b: HUD bottom-bar field (moved up)
static volatile unsigned sh_bpp = 14;   // v186b: selected bit depth (10/12/14), independent of the SIZE profile
static int sh_bpp_ok(const sh_prof_t *pr, unsigned bpp) { unsigned b = bpp == 10 ? 1u : bpp == 12 ? 2u : bpp == 14 ? 4u : 0u; return (pr->bpp_mask & b) != 0; }
static void sh_bpp_clamp(const sh_prof_t *pr)   // highest supported depth if the current one is not
{
    if (sh_bpp_ok(pr, sh_bpp)) return;
    sh_bpp = sh_bpp_ok(pr, 14) ? 14 : sh_bpp_ok(pr, 12) ? 12 : 10;
}
static void sh_bpp_step(const sh_prof_t *pr, int dir)   // dir > 0: 14 -> 12 -> 10, dir < 0: 10 -> 12 -> 14 (skips unsupported)
{
    unsigned b = sh_bpp;
    for (;;) {
        if (dir > 0) { if (b <= 10) return; b -= 2; } else { if (b >= 14) return; b += 2; }
        if (sh_bpp_ok(pr, b)) { sh_bpp = b; return; }
    }
}
static volatile unsigned sh_x3_ok = 0;   // v178: Film 1x3 armed and running
static volatile unsigned pv_zebra = 1, pv_clip_pct = 0;
static volatile unsigned pv_peak = 1;   // v183: focus peaking (standby full-res preview only), default ON
static volatile unsigned pv_mode = 0;    // v182 (ImgMode 1): 0 = 4:3 whole frame, 1 = 1:1 focus (centre 536x400), 2 = OFF (black)
static volatile unsigned sh_m1_ok = 0;   // v182: ImgMode 1 armed by the shell and running
static const sh_prof_t *sh_prof(void) { return &sh_profs[sh_prof_idx < SH_NPROF ? sh_prof_idx : 0]; }
static int sh_is_m1(void) { return sh_on && sh_prof()->kind == SH_M1; }
// v185: ImgMode 1 geometry of the current profile (defaults = v182 1920x1440)
static unsigned sh_m1_w(void) { const sh_prof_t *p = sh_prof(); return p->kind == SH_M1 && p->w ? p->w : 1920; }
static unsigned sh_m1_h(void) { const sh_prof_t *p = sh_prof(); return p->kind == SH_M1 && p->h ? p->h : 1440; }
static unsigned sh_m1_head_h(void) { return sh_m1_h() + 16; }
static unsigned sh_m1_x0(void) { const sh_prof_t *p = sh_prof(); return p->kind == SH_M1 && p->x0 ? p->x0 : 0x84u; }   // v186b: per-profile X0
static unsigned sh_m1_lclk(void) { const sh_prof_t *p = sh_prof(); return p->kind == SH_M1 && p->lclk ? p->lclk : 732; }
static unsigned sh_m1_fl(void) { const sh_prof_t *p = sh_prof(); return p->kind == SH_M1 && p->fl ? p->fl : 1819; }
static unsigned sh_m1_per(void) { const sh_prof_t *p = sh_prof(); return p->kind == SH_M1 && p->per ? p->per : 41666; }
static unsigned sh_m1_fc3c(void) { return (7058u - 2u * sh_m1_head_h()) / 2u; }
static unsigned sh_m1_wide(void) { return sh_on && sh_prof()->kind == SH_M1 && sh_prof()->m1_wide; }
static unsigned sh_m1_geom(const sh_prof_t *p) { return ((unsigned)p->w << 16) | ((unsigned)p->h << 2) | (unsigned)p->m1_wide; }
static volatile unsigned sh_m1_armed_geom = 0;   // v185: sh_m1_geom() of the profile ImgMode 1 was last armed with
static int m1_ready(void) { return *(volatile unsigned *)0x865c == 1 && *(volatile unsigned *)0xe664 == 3; }
static void sh_say(const char *s1, const char *s2);
static void sh_redraw(int force);
static int sh_arm_fps(const sh_prof_t *pr, int update_cache);
static int sh_handle_nav(int zoom);
static void sh_hud(int force);
static void sh_hud_clear(void);

static unsigned pv_stat[3];                   // last frame: frames, black, mean luma (raw units)
static volatile unsigned pv_has_img = 0;      // v184a: a preview image is on the LCD (REC -> Standby keeps it, no black flash)
#if defined(__GNUC__) && !defined(__clang__)
#define PV_HOT __attribute__((optimize("O2","schedule-insns2")))   // v184b: O2 again, built with -mword-relocations (no MOVW/MOVT reloc 47)
static inline __attribute__((always_inline)) unsigned pv_get10(const volatile unsigned short *p, unsigned c);
#else
#define PV_HOT
#endif
static inline unsigned pv_get10(const volatile unsigned short *p, unsigned c)
{
    unsigned b = c * 10, w = b >> 4, v = ((unsigned)p[w] << 16) | p[w + 1];
    return (v >> (22 - (b & 15))) & 0x3ff;
}
/* v184a / v184b: fixed REC-view LUTs for ImgMode 1 (black 127, span 896, daylight WB R x1.75 / B x1.5 folded in):
 * 10b -> 8b sqrt + subtle cinema S-curve, pre-shifted to their ARGB lane (v184b: px = lr[R] | lg[G] | lb[B]). */
#define PV_BLACK 0xFF000000u
static unsigned pv_lut_r[1024], pv_lut_g[1024], pv_lut_b[1024];   // v184b: u32, R = PV_BLACK | r8 << 16, G = g8 << 8, B = b8
static unsigned pv_m1_lut_ok = 0;
static unsigned pv_sqrt_m1(unsigned v)
{
    unsigned x = v > 127 ? (v - 127) * 65535 / 896 : 0, r = 0, bit;
    int s;
    if (x > 65535) x = 65535;
    for (bit = 1u << 7; bit; bit >>= 1) if ((r | bit) * (r | bit) <= x) r |= bit;   // r = sqrt(x), 0..255
    s = (int)r + ((int)r - 128) * (int)r * (255 - (int)r) / 49152;   // v184b: S-curve, 0 / 128 / 255 fixed, slope 0.34..1.33 (monotone)
    return s < 0 ? 0 : s > 255 ? 255 : (unsigned)s;
}
static void pv_build_m1_luts(void)
{
    unsigned v;
    for (v = 0; v < 1024; v++) {
        unsigned d = v > 127 ? v - 127 : 0, rr = 127 + ((d * 28) >> 4), bb = 127 + ((d * 24) >> 4);
        if (rr > 1023) rr = 1023;
        if (bb > 1023) bb = 1023;
        pv_lut_r[v] = PV_BLACK | (pv_sqrt_m1(rr) << 16);   // v184b: pre-shifted ARGB lanes (zero per-pixel cost)
        pv_lut_g[v] = pv_sqrt_m1(v) << 8;
        pv_lut_b[v] = pv_sqrt_m1(bb);
    }
    pv_m1_lut_ok = 1;
}
static void pv_make_lut(unsigned black, unsigned mean)
{
    unsigned v, span = mean > black + 4 ? (mean - black) * 4 : 64;   // mean -> 1/4 of full scale (~50 % after sqrt)
    if (span > 1023) span = 1023;
    for (v = 0; v < 1024; v++) {
        unsigned x = v > black ? (v - black) * 65535 / span : 0, r = 0, bit;
        if (x > 65535) x = 65535;
        for (bit = 1u << 7; bit; bit >>= 1) if ((r | bit) * (r | bit) <= x) r |= bit;   // r = sqrt(x), 0..255
        pv_lut[v] = r;
    }
    if (black == 127 && !pv_m1_lut_ok) pv_build_m1_luts();   // v184a: ImgMode 1 fixed view
}
// v182 (B.3): PV_RGBA / PV_BW = 360 are only valid on the LCD (HDMI: bm_w = 480): no direct overlay write otherwise
static int pv_ok(void) { return camera_screen.buffer_width == PV_BW; }
static void pv_fill(unsigned y0, unsigned y1, unsigned x0, unsigned x1, unsigned v)
{
    unsigned x, y;
    for (y = y0; y < y1; y++) { unsigned *o = PV_RGBA + y * PV_BW; for (x = x0; x < x1; x++) o[x] = v; }
}
static void pv_clear(void)
{
    unsigned y;
    if (!pv_ok()) return;
    for (y = PV_Y - 1; y < PV_Y + PV_H + 1; y++) memset(PV_RGBA + y * PV_BW + PV_X - 1, 0, (PV_W + 2) * 4);
    vid_bitmap_refresh();
}
/* v182 (B.2/B.3): in ImgMode 1 Canon's YUV view shows magenta / green / cyan bars through every transparent
 * overlay pixel. Rows 20..219 are made opaque black outside the 268 x 200 image window (x 46..313), or
 * entirely (full = 1, view OFF, no image yet); the HUD bars (rows 0..19, 220..239) are drawn opaque by sh_hud. */
/* v186b: aspect-fit even rect of a raw_w x raw_h frame inside the 360 x 200 image area (rows 20..219) */
static void pv_m1_rect(unsigned raw_w, unsigned raw_h, unsigned *out_x, unsigned *out_y, unsigned *out_w, unsigned *out_h)
{
    unsigned w = PV_BW, h = 200;
    if (raw_w && raw_h) {
        h = PV_BW * raw_h / raw_w;
        if (h > 200) { h = 200; w = 200 * raw_w / raw_h; if (w > PV_BW) w = PV_BW; }
    }
    w &= ~1u; h &= ~1u;
    if (w < 2) w = 2;
    if (h < 2) h = 2;
    *out_w = w; *out_h = h;
    *out_x = ((PV_BW - w) / 2) & ~1u;
    *out_y = 20 + (((200 - h) / 2) & ~1u);
}
/* v186b: rows the ImgMode 1 renderers may write (the BIT selector bar owns rows 200..219 while it is shown) */
static unsigned pv_m1_ylim(void) { return (sh_field == 4 && !sh_rec_on) ? 200u : 220u; }
static void pv_mask_opaque(int full, unsigned raw_w, unsigned raw_h)
{
    unsigned ox, oy, ow, oh;
    if (!pv_ok()) return;
    if (full || pv_mode == 2) pv_fill(20, 220, 0, PV_BW, PV_BLACK);
    else {
        pv_m1_rect(raw_w, raw_h, &ox, &oy, &ow, &oh);
        if (oy > 20) pv_fill(20, oy, 0, PV_BW, PV_BLACK);
        if (oy + oh < 220) pv_fill(oy + oh, 220, 0, PV_BW, PV_BLACK);
        if (ox) pv_fill(oy, oy + oh, 0, ox, PV_BLACK);
        if (ox + ow < PV_BW) pv_fill(oy, oy + oh, ox + ow, PV_BW, PV_BLACK);
    }
    vid_bitmap_refresh();
}
static void pv_mask_clear(void)   // leaving ImgMode 1: Canon's own view (x5 / Film) visible again
{
    pv_has_img = 0;
    if (!pv_ok()) return;
    memset(PV_RGBA + 20 * PV_BW, 0, 200 * PV_BW * 4);
    vid_bitmap_refresh();
}
#if defined(__GNUC__) && !defined(__clang__)
static inline __attribute__((always_inline)) unsigned pv_get12(const volatile unsigned short *p, unsigned c);
#endif
static inline unsigned pv_get12(const volatile unsigned short *p, unsigned c)   // v182 (B.4): b&15 in {0,12,8,4}
{
    unsigned b = c * 12, w = b >> 4, v = ((unsigned)p[w] << 16) | p[w + 1];
    return (v >> (20 - (b & 15))) & 0xfff;
}
/* v182 (B.4) / v184a / v184b / v186b: ImgMode 1 colour preview. Frame raw_w x raw_h PACK32 (10, 12 or 14 bit), RGGB
 * from (0,0) (X0 / Y0 even), no optical black in the window: fixed black 127 (10b scale; 12b >> 2, 14b >> 4).
 * pv_mode 0: whole frame aspect-fit (pv_m1_rect) in 360 x 200 (one quad per pixel); 1: centre 720 x 400 photosites
 * -> 360 x 200 at one quad per LCD dot. half_res (REC): quads written as 2 x 2 blocks. v184b: per-column word / shift
 * tables, one inner loop per bit depth (no bpp test per pixel), px = lr[R] | lg[G] | lb[B] (pre-shifted u32 LUTs).
 * v186b: the second sample of a quad has its own word / shift (col_w1 / col_sh1): a 14b pair spans up to 3 halfwords.
 * Rows >= pv_m1_ylim() are left alone (BIT selector bar). No refresh here. */
#define M1_ROW(D, M, SC, THR) \
    for (x = 0; x < W; x++) { \
        const unsigned w = col_w[x], sh = col_sh[x], w1 = col_w1[x], sh1 = col_sh1[x]; \
        const unsigned v0 = ((unsigned)p0[w] << 16) | p0[w + 1], v1 = ((unsigned)p1[w] << 16) | p1[w + 1]; \
        const unsigned u0 = ((unsigned)p0[w1] << 16) | p0[w1 + 1], u1 = ((unsigned)p1[w1] << 16) | p1[w1 + 1]; \
        unsigned s0 = (v0 >> sh) & (M), s1 = (u0 >> sh1) & (M), s2 = (v1 >> sh) & (M), s3 = (u1 >> sh1) & (M); \
        unsigned mx = s0 > s1 ? s0 : s1, m2 = s2 > s3 ? s2 : s3, px, g; \
        mx = mx > m2 ? mx : m2; \
        s0 >>= (SC); s1 >>= (SC); s2 >>= (SC); s3 >>= (SC); \
        g = (s1 + s2) >> 1; \
        if (mx >= (THR)) clip++; \
        if (zebra && mx >= (THR) && (((st * (x + y) + fidx) & 7) < 4)) px = 0xFFFF2800u; \
        else { \
            px = lr[s0] | lg[g] | lb_t[s3]; \
            if (!(x & 3)) { sum += g; n++; } \
            if (do_peak && mx < (THR) && y > 0 && x > 0) { \
                unsigned dg_h = g > g_left ? g - g_left : g_left - g; \
                unsigned dg_v = g > pk_prev[x] ? g - pk_prev[x] : pk_prev[x] - g; \
                if ((dg_h + dg_v) * 6 > g + g_left + 2 * black + 32) px = 0xFF00FF40u; \
            } \
        } \
        if (do_peak) { pk_prev[x] = (unsigned short)g; g_left = g; } \
        if (st == 2) { row_px[2 * x] = px; row_px[2 * x + 1] = px; } \
        else row_px[x] = px; \
        (void)(D); \
    }
static PV_HOT void pv_render_m1(const char *frame, unsigned bpp, int half_res, unsigned raw_w, unsigned raw_h)
{
    const unsigned mode = pv_mode, zebra = pv_zebra, peak = pv_peak, fidx = pv_stat[0];   // v184a: hoisted (volatile globals)
    const unsigned black = 127, st = half_res ? 2 : 1, ylim = pv_m1_ylim();
    const int do_peak = peak && !half_res, b12 = (bpp == 12), b14 = (bpp == 14);
    const unsigned *lr = pv_lut_r, *lg = pv_lut_g, *lb_t = pv_lut_b;   // v184b: hoisted LUT bases
    unsigned focus = (mode == 1), ox, oy, ow, oh, W, H, lb, lb_hw, c0 = 0, r0 = 0;
    unsigned x, y, sum = 0, n = 0, clip = 0, rows = 0;
    static unsigned short pk_prev[PV_BW];   // v183: previous output row green (10b scale)
    static unsigned short col_w[PV_BW], col_w1[PV_BW];   // v184b / v186b: first 16-bit word of quad samples c / c + 1
    static unsigned char col_sh[PV_BW], col_sh1[PV_BW];  // v184b / v186b: right shifts inside their 32-bit windows
    static unsigned row_px[PV_BW];           // v183d: cached row, burst-copied to uncached PV_RGBA (never reentrant)
    if (!pv_ok() || mode == 2 || !raw_w || !raw_h) return;
    if (bpp != 10 && bpp != 12 && bpp != 14) return;
    if (!pv_m1_lut_ok) pv_build_m1_luts();
    if (focus && (raw_w < 2 * PV_BW || raw_h < 400)) focus = 0;
    if (focus) { ox = 0; oy = 20; ow = PV_BW; oh = 200; c0 = ((raw_w - 2 * PV_BW) / 2) & ~1u; r0 = ((raw_h - 400) / 2) & ~1u; }
    else pv_m1_rect(raw_w, raw_h, &ox, &oy, &ow, &oh);
    W = ow / st; H = oh / st; lb = raw_w * bpp / 8; lb_hw = lb >> 1;
    for (x = 0; x < W; x++) {
        unsigned c = focus ? c0 + 2 * st * x : (x * raw_w / W) & ~1u, b = c * bpp, b1 = b + bpp;
        col_w[x] = (unsigned short)(b >> 4);
        col_sh[x] = (unsigned char)(32 - bpp - (b & 15));
        col_w1[x] = (unsigned short)(b1 >> 4);
        col_sh1[x] = (unsigned char)(32 - bpp - (b1 & 15));
    }
    for (y = 0; y < H; y++) {
        unsigned g_left = 0;
        const unsigned r = focus ? r0 + 2 * st * y : (y * raw_h / H) & ~1u, sy = oy + st * y;
        const unsigned short *p0 = (const unsigned short *)(frame + r * lb);         // v183b: not volatile (cached frame)
        const unsigned short *p1 = (const unsigned short *)(frame + (r + 1) * lb);
        unsigned *o = PV_RGBA + sy * PV_BW + ox;
        if (sy >= ylim) break;
        rows++;
        if (b14) { M1_ROW(14, 0x3fffu, 4, 16320u) }       // v186b
        else if (b12) { M1_ROW(12, 0xfffu, 2, 4080u) }    // v184b: bit depth chosen per row, never per pixel
        else if (st == 1) {
            /* v184c: 10-bit full-res rows, split fast / peak; v186b: row r + 1 = q + lb_hw halfwords (any width).
             * clip = any sample >= 1020 <=> bit 10 of (s + 4); n += ceil(W / 4) per row, minus zebra x % 4 == 0. */
            const unsigned zp = y + fidx;
            n += (W + 3) >> 2;
            if (!do_peak) {
                for (x = 0; x < W; x++) {
                    const unsigned short *q = p0 + col_w[x];
                    const unsigned sh = col_sh[x];
                    const unsigned v0 = ((unsigned)q[0] << 16) | q[1], v1 = ((unsigned)q[lb_hw] << 16) | q[lb_hw + 1];
                    const unsigned s0 = (v0 >> sh) & 0x3ffu, s1 = (v0 >> (sh - 10)) & 0x3ffu;
                    const unsigned s2 = (v1 >> sh) & 0x3ffu, s3 = (v1 >> (sh - 10)) & 0x3ffu;
                    const unsigned g = (s1 + s2) >> 1;
                    if (__builtin_expect((((s0 + 4) | (s1 + 4) | (s2 + 4) | (s3 + 4)) & 0x400u) != 0, 0)) {
                        clip++;
                        if (zebra && ((x + zp) & 7) < 4) { row_px[x] = 0xFFFF2800u; if (!(x & 3)) n--; continue; }
                    }
                    row_px[x] = lr[s0] | lg[g] | lb_t[s3];
                    if (!(x & 3)) sum += g;
                }
            } else {
                for (x = 0; x < W; x++) {
                    const unsigned short *q = p0 + col_w[x];
                    const unsigned sh = col_sh[x];
                    const unsigned v0 = ((unsigned)q[0] << 16) | q[1], v1 = ((unsigned)q[lb_hw] << 16) | q[lb_hw + 1];
                    const unsigned s0 = (v0 >> sh) & 0x3ffu, s1 = (v0 >> (sh - 10)) & 0x3ffu;
                    const unsigned s2 = (v1 >> sh) & 0x3ffu, s3 = (v1 >> (sh - 10)) & 0x3ffu;
                    const unsigned g = (s1 + s2) >> 1, gp = pk_prev[x], gl = g_left;
                    const unsigned clp = ((s0 + 4) | (s1 + 4) | (s2 + 4) | (s3 + 4)) & 0x400u;
                    unsigned px;
                    pk_prev[x] = (unsigned short)g; g_left = g;
                    if (__builtin_expect(clp != 0, 0)) {
                        clip++;
                        if (zebra && ((x + zp) & 7) < 4) { row_px[x] = 0xFFFF2800u; if (!(x & 3)) n--; continue; }
                    }
                    px = lr[s0] | lg[g] | lb_t[s3];
                    if (!(x & 3)) sum += g;
                    if (!clp && x && y) {
                        const unsigned dh = g > gl ? g - gl : gl - g, dv = g > gp ? g - gp : gp - g;
                        if ((dh + dv) * 6 > g + gl + 2 * black + 32) px = 0xFF00FF40u;
                    }
                    row_px[x] = px;
                }
            }
        }
        else { M1_ROW(10, 0x3ffu, 0, 1020u) }
        memcpy(o, row_px, W * st * 4);                                           // v183d: burst writes
        if (st == 2 && sy + 1 < ylim) memcpy(o + PV_BW, row_px, W * st * 4);
    }
    pv_clip_pct = (clip && rows) ? ((clip * 100 + W * rows - 1) / (W * rows)) : 0;
    pv_stat[0]++; pv_stat[1] = black;
    if (n) { unsigned cur = sum / n; pv_stat[2] = pv_stat[0] > 1 ? (pv_stat[2] * 3 + cur) >> 2 : cur; }   // v183b: EMA
    // v184a: no pv_make_lut() here (fixed REC view)
}
#undef M1_ROW
#define FN_DFLUSH   0xfc1267af   // v183b: dcache_flush_range(addr, len) = DCIMVAC loop + dsb sy (ROM 1.10d)
/* v184a / v186b: flush only the row pairs (r, r + 1) pv_render_m1 samples for (mode, half_res, raw_w, raw_h), 32-byte aligned. */
static void pv_dflush_m1(unsigned phys, unsigned lb, unsigned mode, int half_res, unsigned raw_w, unsigned raw_h)
{
    unsigned bpp, st, y, ox, oy, ow, oh;
    if (mode == 2 || !raw_w || !raw_h) return;
    bpp = lb * 8 / raw_w;
    if (!bpp) return;
    st = half_res ? 2 : 1;
    if (mode == 1 && raw_w >= 2 * PV_BW && raw_h >= 400) {   // 1:1: centre 720 x 400 photosites
        const unsigned c0 = ((raw_w - 2 * PV_BW) / 2) & ~1u, r0 = ((raw_h - 400) / 2) & ~1u, H = 200 / st;
        const unsigned x0 = (c0 * bpp / 8) & ~31u;
        unsigned x1 = ((c0 + 2 * PV_BW + 2) * bpp / 8 + 4 + 31) & ~31u;
        if (x1 > lb) x1 = lb;
        for (y = 0; y < H; y++) {
            unsigned a = phys + (r0 + 2 * st * y) * lb, s;
            s = (a + x0) & ~31u; ((fn2)FN_DFLUSH)(s, ((a + x1 + 31) & ~31u) - s);
            a += lb;
            s = (a + x0) & ~31u; ((fn2)FN_DFLUSH)(s, ((a + x1 + 31) & ~31u) - s);
        }
    } else {           // whole frame: whole row pairs
        unsigned H;
        pv_m1_rect(raw_w, raw_h, &ox, &oy, &ow, &oh);
        H = oh / st;
        for (y = 0; y < H; y++) {
            unsigned r = (y * raw_h / H) & ~1u, s = (phys + r * lb) & ~31u, e = (phys + (r + 2) * lb + 31) & ~31u;
            ((fn2)FN_DFLUSH)(s, e - s);
        }
    }
}
/* v185: Wide 1:3 ImgMode 1 (raw_w x raw_h PACK32, e.g. 1728 x 1440, horizontally squeezed 3x) preview. Dedicated
 * mask / renderer / dflush (the 1920 x 1440 4:3 path above is untouched), selected by the pv_m1_* dispatchers.
 * pv_mode 0: whole frame -> 360 x 100 (124 if raw_h > 1440) letterbox centred in rows 20..219, 2.39:1 ticks;
 * 1: centre 240 x 400 photosites -> 360 x 200 (desqueezed); 2: OFF. */
static void pv_mask_opaque_wide(int full, unsigned raw_h)
{
    if (!pv_ok()) return;
    if (full || pv_mode == 2) pv_fill(20, 220, 0, PV_BW, PV_BLACK);
    else if (pv_mode != 1) {
        unsigned oh = raw_h > 1440 ? 124 : 100, oy = 20 + (200 - oh) / 2;
        pv_fill(20, oy, 0, PV_BW, PV_BLACK);
        pv_fill(oy + oh, 220, 0, PV_BW, PV_BLACK);
    }
    vid_bitmap_refresh();
}
static PV_HOT void pv_render_m1_wide(const char *frame, unsigned bpp, int half_res, unsigned raw_w, unsigned raw_h)
{
    const unsigned mode = pv_mode, zebra = pv_zebra, peak = pv_peak, fidx = pv_stat[0];   // hoisted (volatile globals)
    const unsigned black = 127, focus = (mode == 1), st = half_res ? 2 : 1, ylim = pv_m1_ylim();
    const unsigned out_w = PV_BW, out_h = focus ? 200 : (raw_h > 1440 ? 124 : 100), out_y = focus ? 20 : (20 + (200 - out_h) / 2);
    const unsigned W = out_w / st, lb = raw_w * bpp / 8, lb_hw = lb >> 1;
    const int do_peak = peak && !half_res, b12 = (bpp == 12), b14 = (bpp == 14);
    const unsigned *lr = pv_lut_r, *lg = pv_lut_g, *lb_t = pv_lut_b;
    const unsigned w239 = out_h * 239 / 100, tx0 = (PV_BW - w239) / 2, tx1 = PV_BW - 1 - tx0;   // 2.39:1 framing ticks
    unsigned x, y, c0, r0, sum = 0, n = 0, clip = 0, H = out_h / st;
    static unsigned short pk_prev[PV_BW], col_w[PV_BW], col_w1[PV_BW];
    static unsigned char col_sh[PV_BW], col_sh1[PV_BW];   // v186b: second sample of the quad (14b pairs span 3 halfwords)
    static unsigned row_px[PV_BW];   // cached row, burst-copied to uncached PV_RGBA (never reentrant)
    if (!pv_ok() || mode == 2 || !raw_w || !raw_h) return;
    if (bpp != 10 && bpp != 12 && bpp != 14) return;
    if (!pv_m1_lut_ok) pv_build_m1_luts();
    c0 = raw_w > 240 ? ((raw_w - 240) / 2) & ~1u : 0;
    r0 = raw_h > 400 ? ((raw_h - 400) / 2) & ~1u : 0;
    for (x = 0; x < W; x++) {
        unsigned c = focus ? ((c0 + x * 240 / W) & ~1u) : ((x * raw_w / W) & ~1u), b = c * bpp, b1 = b + bpp;
        col_w[x] = (unsigned short)(b >> 4);
        col_sh[x] = (unsigned char)(32 - bpp - (b & 15));
        col_w1[x] = (unsigned short)(b1 >> 4);
        col_sh1[x] = (unsigned char)(32 - bpp - (b1 & 15));
    }
#define M1W_ROW(D, M, SC, THR) \
    for (x = 0; x < W; x++) { \
        const unsigned w = col_w[x], sh = col_sh[x], w1 = col_w1[x], sh1 = col_sh1[x]; \
        const unsigned v0 = ((unsigned)p0[w] << 16) | p0[w + 1], v1 = ((unsigned)p1[w] << 16) | p1[w + 1]; \
        const unsigned u0 = ((unsigned)p0[w1] << 16) | p0[w1 + 1], u1 = ((unsigned)p1[w1] << 16) | p1[w1 + 1]; \
        unsigned s0 = (v0 >> sh) & (M), s1 = (u0 >> sh1) & (M), s2 = (v1 >> sh) & (M), s3 = (u1 >> sh1) & (M); \
        unsigned mx = s0 > s1 ? s0 : s1, m2 = s2 > s3 ? s2 : s3, px, g; \
        mx = mx > m2 ? mx : m2; \
        s0 >>= (SC); s1 >>= (SC); s2 >>= (SC); s3 >>= (SC); \
        g = (s1 + s2) >> 1; \
        if (mx >= (THR)) clip++; \
        if (zebra && mx >= (THR) && (((st * (x + y) + fidx) & 7) < 4)) px = 0xFFFF2800u; \
        else { \
            px = lr[s0] | lg[g] | lb_t[s3]; \
            if (!(x & 3)) { sum += g; n++; } \
            if (do_peak && mx < (THR) && y > 0 && x > 0) { \
                unsigned dg_h = g > g_left ? g - g_left : g_left - g; \
                unsigned dg_v = g > pk_prev[x] ? g - pk_prev[x] : pk_prev[x] - g; \
                if ((dg_h + dg_v) * 6 > g + g_left + 2 * black + 32) px = 0xFF00FF40u; \
            } \
        } \
        if (do_peak) { pk_prev[x] = (unsigned short)g; g_left = g; } \
        if (st == 2) { row_px[2 * x] = px; row_px[2 * x + 1] = px; } \
        else row_px[x] = px; \
        (void)(D); \
    }
    for (y = 0; y < H; y++) {
        unsigned g_left = 0;
        unsigned r = focus ? r0 + 2 * st * y : (y * raw_h / H) & ~1u;
        const unsigned short *p0 = (const unsigned short *)(frame + r * lb);
        const unsigned short *p1 = (const unsigned short *)(frame + (r + 1) * lb);
        unsigned *o = PV_RGBA + (out_y + st * y) * PV_BW;
        if (out_y + st * y >= ylim) { H = y; break; }   // v186b: BIT selector bar rows
        if (b14) { M1W_ROW(14, 0x3fffu, 4, 16320u) }   // v186b
        else if (b12) { M1W_ROW(12, 0xfffu, 2, 4080u) }
        else if (st == 1) {   // 10-bit full-res rows: row r + 1 = q + lb_hw halfwords
            const unsigned zp = y + fidx;
            n += (W + 3) >> 2;
            if (!do_peak) {
                for (x = 0; x < W; x++) {
                    const unsigned short *q = p0 + col_w[x];
                    const unsigned sh = col_sh[x];
                    const unsigned v0 = ((unsigned)q[0] << 16) | q[1], v1 = ((unsigned)q[lb_hw] << 16) | q[lb_hw + 1];
                    const unsigned s0 = (v0 >> sh) & 0x3ffu, s1 = (v0 >> (sh - 10)) & 0x3ffu;
                    const unsigned s2 = (v1 >> sh) & 0x3ffu, s3 = (v1 >> (sh - 10)) & 0x3ffu;
                    const unsigned g = (s1 + s2) >> 1;
                    if (__builtin_expect((((s0 + 4) | (s1 + 4) | (s2 + 4) | (s3 + 4)) & 0x400u) != 0, 0)) {
                        clip++;
                        if (zebra && ((x + zp) & 7) < 4) { row_px[x] = 0xFFFF2800u; if (!(x & 3)) n--; continue; }
                    }
                    row_px[x] = lr[s0] | lg[g] | lb_t[s3];
                    if (!(x & 3)) sum += g;
                }
            } else {
                for (x = 0; x < W; x++) {
                    const unsigned short *q = p0 + col_w[x];
                    const unsigned sh = col_sh[x];
                    const unsigned v0 = ((unsigned)q[0] << 16) | q[1], v1 = ((unsigned)q[lb_hw] << 16) | q[lb_hw + 1];
                    const unsigned s0 = (v0 >> sh) & 0x3ffu, s1 = (v0 >> (sh - 10)) & 0x3ffu;
                    const unsigned s2 = (v1 >> sh) & 0x3ffu, s3 = (v1 >> (sh - 10)) & 0x3ffu;
                    const unsigned g = (s1 + s2) >> 1, gp = pk_prev[x], gl = g_left;
                    const unsigned clp = ((s0 + 4) | (s1 + 4) | (s2 + 4) | (s3 + 4)) & 0x400u;
                    unsigned px;
                    pk_prev[x] = (unsigned short)g; g_left = g;
                    if (__builtin_expect(clp != 0, 0)) {
                        clip++;
                        if (zebra && ((x + zp) & 7) < 4) { row_px[x] = 0xFFFF2800u; if (!(x & 3)) n--; continue; }
                    }
                    px = lr[s0] | lg[g] | lb_t[s3];
                    if (!(x & 3)) sum += g;
                    if (!clp && x && y) {
                        const unsigned dh = g > gl ? g - gl : gl - g, dv = g > gp ? g - gp : gp - g;
                        if ((dh + dv) * 6 > g + gl + 2 * black + 32) px = 0xFF00FF40u;
                    }
                    row_px[x] = px;
                }
            }
        }
        else { M1W_ROW(10, 0x3ffu, 0, 1020u) }
        if (!focus && (st * y < 6 || st * y + st > out_h - 6)) { row_px[tx0] = 0xFF888888u; row_px[tx1] = 0xFF888888u; }
        memcpy(o, row_px, W * st * 4);
        if (st == 2 && out_y + st * y + 1 < ylim) memcpy(o + PV_BW, row_px, W * st * 4);
    }
#undef M1W_ROW
    pv_clip_pct = (clip && H) ? ((clip * 100 + W * H - 1) / (W * H)) : 0;
    pv_stat[0]++; pv_stat[1] = black;
    if (n) { unsigned cur = sum / n; pv_stat[2] = pv_stat[0] > 1 ? (pv_stat[2] * 3 + cur) >> 2 : cur; }
}
/* v185: flush only the row pairs pv_render_m1_wide samples for (mode, half_res), 32-byte aligned. */
static void pv_dflush_m1_wide(unsigned phys, unsigned lb, unsigned mode, int half_res, unsigned raw_w, unsigned raw_h)
{
    unsigned bpp, st, y;
    if (mode == 2 || !raw_w || !raw_h) return;
    bpp = lb * 8 / raw_w;
    if (!bpp) return;
    st = half_res ? 2 : 1;
    if (mode == 1) {   // centre 240 x 400
        const unsigned c0 = raw_w > 240 ? ((raw_w - 240) / 2) & ~1u : 0, r0 = raw_h > 400 ? ((raw_h - 400) / 2) & ~1u : 0;
        const unsigned H = 200 / st, x0 = (c0 * bpp / 8) & ~31u;
        unsigned x1 = ((c0 + 242) * bpp / 8 + 4 + 31) & ~31u;
        if (x1 > lb) x1 = lb;
        for (y = 0; y < H; y++) {
            unsigned a = phys + (r0 + 2 * st * y) * lb, s;
            s = (a + x0) & ~31u; ((fn2)FN_DFLUSH)(s, ((a + x1 + 31) & ~31u) - s);
            a += lb;
            s = (a + x0) & ~31u; ((fn2)FN_DFLUSH)(s, ((a + x1 + 31) & ~31u) - s);
        }
    } else {           // whole frame: whole row pairs
        const unsigned oh = raw_h > 1440 ? 124 : 100, H = oh / st;
        for (y = 0; y < H; y++) {
            unsigned r = (y * raw_h / H) & ~1u, s = (phys + r * lb) & ~31u, e = (phys + (r + 2) * lb + 31) & ~31u;
            ((fn2)FN_DFLUSH)(s, e - s);
        }
    }
}
/* v185: ImgMode 1 preview dispatch (Wide 1:3 vs 1920 x 1440 4:3) */
static void pv_m1_mask(int full) { if (sh_m1_wide()) pv_mask_opaque_wide(full, sh_m1_h()); else pv_mask_opaque(full, sh_m1_w(), sh_m1_h()); }
static void pv_m1_dflush(unsigned phys, unsigned lb, unsigned mode, int hr) { if (sh_m1_wide()) pv_dflush_m1_wide(phys, lb, mode, hr, sh_m1_w(), sh_m1_h()); else pv_dflush_m1(phys, lb, mode, hr, sh_m1_w(), sh_m1_h()); }
static void pv_m1_render(const char *frame, unsigned bpp, int hr) { if (sh_m1_wide()) pv_render_m1_wide(frame, bpp, hr, sh_m1_w(), sh_m1_h()); else pv_render_m1(frame, bpp, hr, sh_m1_w(), sh_m1_h()); }
/* v182 (B.5) / v184a: preview during an ImgMode 1 take, task M10Pv (prio 0x1E, below M10XR 0x1C / M10Key 0x1D: idle CPU only).
 * v184a: renders the newest CAPTURED frame k = xr_prod - 1 (cached view + sampled-row dflush) under a seqlock on
 * xr_prod (the slot of k is rewritten by the capture of frame k + lj_raw_n); half res when the encoder lags >= 2.
 * v184b: 4:3 always half res (134 x 100, ~10 ms); 1:1 punch-in at full res + peaking while the encoder keeps up; 30 ms pace. */
static volatile unsigned pv_rec_on = 0, pv_rec_done = 1, pv_rec_n = 0, pv_rec_skip = 0;
static volatile unsigned pv_rec_skip_bl = 0, pv_rec_skip_torn = 0, pv_rec_ren_sum = 0, pv_rec_ren_max = 0;
static volatile unsigned pv_hud_dirty = 0;   // v184a: view toggled -> HUD redraw (M10Key in REC, M10PvS in standby)
static void pv_rec_task(void)
{
    unsigned last_k = 0xffffffff, last_mode = 0xffffffff;
    while (pv_rec_on) {
        unsigned k, rs, j, dup = 0, hr, cur_mode, t;
        if (!xr_prod || xr_prod - 1 == last_k) { msleep(10); continue; }
        k = xr_prod - 1;
        if (xr_prod - lj_cnt >= lj_raw_n - 1 || (xr_last_drop_ms && get_tick_count() - xr_last_drop_ms < 100) || !pv_ok() || pv_mode == 2) {
            pv_rec_skip++; pv_rec_skip_bl++; msleep(20); continue;   // encoder late / drop / no LCD / view OFF: leave it the CPU
        }
        if (k >= XR_MAX || xr_prod - k >= lj_raw_n - 1) { pv_rec_skip++; msleep(10); continue; }   // too close to the overwrite
        for (j = (lj_dup_h > LJ_DUP_N ? lj_dup_h - LJ_DUP_N : 0); j < lj_dup_h; j++) if (lj_dup_q[j % LJ_DUP_N] == k) dup = 1;
        if (dup) { pv_rec_skip++; last_k = k; msleep(10); continue; }                    // HEAD_ERR frame: torn raw
        cur_mode = pv_mode;
        hr = (cur_mode == 1 && xr_prod - lj_cnt < 2) ? 0 : 1;   // v184b: 4:3 -> 134 x 100 always; 1:1 full res unless the encoder lags
        rs = xr_slot[k] % lj_raw_n;
        if (sh_m1_wide() && (pv_hud_dirty || cur_mode != last_mode)) pv_m1_mask(0);   // v185: Wide letterbox bars repaint on a view toggle
        last_mode = cur_mode;
        t = get_tick_count();
        pv_m1_dflush((unsigned)lj_phys + rs * xr_fb, lvn_lb, cur_mode, hr);
        pv_m1_render((const char *)((unsigned)lj_phys + rs * xr_fb), lvn_bpp, hr);
        t = get_tick_count() - t;
        if (xr_prod - k >= lj_raw_n) { pv_rec_skip++; pv_rec_skip_torn++; continue; }   // slot rewritten meanwhile: not shown
        vid_bitmap_refresh();
        last_k = k;
        pv_rec_n++; pv_has_img = 1;
        pv_rec_ren_sum += t; if (t > pv_rec_ren_max) pv_rec_ren_max = t;
        msleep(30);   // v184b: ~12-15 fps live REC preview
    }
    pv_rec_done = 1;
    ExitTask();
}
static void pv_rec_start(void)
{
    if (!pv_rec_done || !pv_ok()) return;
    pv_rec_n = pv_rec_skip = pv_rec_skip_bl = pv_rec_skip_torn = pv_rec_ren_sum = pv_rec_ren_max = 0;
    pv_m1_mask(0);   // v184a: no black wipe (the standby image stays until the first REC frame)
    pv_rec_done = 0; pv_rec_on = 1;
    CreateTask("M10Pv", 0x1E, 0x1000, pv_rec_task);
}
static void pv_rec_stop(void)
{
    unsigned t = get_tick_count();
    if (pv_rec_done) return;
    pv_rec_on = 0;
    while (!pv_rec_done && get_tick_count() - t < 2000) msleep(10);
    slog("v182 rec preview n=%d skip=%d", pv_rec_n, pv_rec_skip);
    slog("  v184 bl=%d torn=%d", pv_rec_skip_bl, pv_rec_skip_torn);
    slog("  v184 ren_avg=%d ren_max=%d", pv_rec_n ? pv_rec_ren_sum / pv_rec_n : 0, pv_rec_ren_max);
    if (!pv_rec_done) { ts_pinned = 1; slog("v182 rec preview task still running: EXMEM pinned", 0, 0); }   // never free a buffer it may read
}
static void pv_render(const char *frame)
{
    unsigned x, y, sum = 0, n = 0, black = 0, clip = 0, border;
    if (!pv_ok()) return;
    unsigned lb = lvn_lb;
    const sh_prof_t *pr = sh_on ? sh_prof() : &sh_profs[0];
    unsigned c0 = pr->c0, cw = pr->w;
    {   // black: optical black columns 8..63, rows 200 / 600
        unsigned c, s = 0;
        for (c = 8; c < 64; c += 2) {
            s += pv_get10((const volatile unsigned short *)(frame + 200 * lb), c);
            s += pv_get10((const volatile unsigned short *)(frame + 600 * lb), c + 1);
        }
        black = s / 56;
    }
    for (y = 0; y < PV_H; y++) {
        unsigned r = (28 + y * 1076 / PV_H) & ~1u;
        const volatile unsigned short *p0 = (const volatile unsigned short *)(frame + r * lb);
        const volatile unsigned short *p1 = (const volatile unsigned short *)(frame + (r + 1) * lb);
        unsigned *o = PV_RGBA + (PV_Y + y) * PV_BW + PV_X;
        for (x = 0; x < PV_W; x++) {
            unsigned c = (c0 + x * cw / PV_W) & ~1u;
            unsigned s0 = pv_get10(p0, c), s1 = pv_get10(p0, c + 1);
            unsigned s2 = pv_get10(p1, c), s3 = pv_get10(p1, c + 1);
            unsigned mx = s0; if (s1 > mx) mx = s1; if (s2 > mx) mx = s2; if (s3 > mx) mx = s3;
            unsigned l = (s0 + s1 + s2 + s3) >> 2;
            if (mx >= 1020) clip++;
            if (pv_zebra && mx >= 1020 && (((x + y + pv_stat[0]) & 7) < 4)) {
                o[x] = 0xffff2800u;
            } else {
                unsigned g = pv_lut[l];
                o[x] = 0xff000000u | (g << 16) | (g << 8) | g;
            }
            if (!(x & 3)) { sum += l; n++; }
        }
    }
    pv_clip_pct = clip ? ((clip * 100 + PV_W * PV_H - 1) / (PV_W * PV_H)) : 0;
    border = pv_clip_pct ? 0xffff9000u : 0xffffffffu;
    for (x = 0; x < PV_W + 2; x++) { PV_RGBA[(PV_Y - 1) * PV_BW + PV_X - 1 + x] = border; PV_RGBA[(PV_Y + PV_H) * PV_BW + PV_X - 1 + x] = border; }
    for (y = 0; y < PV_H; y++) { PV_RGBA[(PV_Y + y) * PV_BW + PV_X - 1] = border; PV_RGBA[(PV_Y + y) * PV_BW + PV_X + PV_W] = border; }
    pv_stat[0]++; pv_stat[1] = black; pv_stat[2] = n ? sum / n : 0;
    pv_make_lut(black, pv_stat[2]);
    vid_bitmap_refresh();
}
#define FN_DCLEAN   0xfc1267cb
static void sh_pv_hud(void) { sh_hud(1); }   // v174: minimal HUD (status bar + exposure bar)
/* v184a / v184b: standby ImgMode 1 preview, async. sh_preview captures back to back into an ns-slot ring (v184b: up
 * to 8 EXMEM slots, slot = seq % ns, pv_cap_seq = completed captures); task M10PvS (prio 0x1E) renders the newest
 * complete slot from the cached view and drops it if the ring wrapped onto it meanwhile (seqlock on pv_cap_seq).
 * v184b: dflush timed apart from the render (pv_stby_fl_sum), msleep(5) per shown frame (Canon tasks never starve). */
static volatile unsigned pv_stby_on = 0, pv_stby_done = 1, pv_cap_seq = 0, pv_stby_n = 0, pv_stby_torn = 0;
static volatile unsigned pv_stby_ren_min = 0, pv_stby_ren_max = 0, pv_stby_ren_sum = 0, pv_mask_dirty = 0;
static volatile unsigned pv_stby_phys = 0, pv_stby_fb = 0, pv_stby_ns = 8, pv_stby_fl_sum = 0;
static void pv_stby_task(void)
{
    unsigned last = 0;
    while (pv_stby_on) {
        unsigned f = pv_cap_seq, ns = pv_stby_ns, sl, cur_mode, t, tf, fl;
        if (pv_mode != 2 && pv_ok()) {
            /* v185b: sentinel = top-right corner of the opaque mask (21, 358), never touched by the yellow clip % text
             * at (2, 22) (the old (30, 2) sentinel looped mask + HUD + refresh as soon as a highlight clipped); Wide
             * focus view has no mask (image fills 360 x 200): watch the opaque top HUD bar (1, 358) instead. */
            int wiped = PV_RGBA[1 * PV_BW + 358] != PV_BLACK;   // v186b: opaque top HUD bar sentinel for ALL ImgMode 1 modes
            int masked = 0;
            if (pv_mask_dirty || wiped) { pv_mask_dirty = 0; pv_m1_mask(0); masked = 1; pv_hud_dirty = 1; }   // overlay erased / view changed
            if (pv_hud_dirty) { pv_hud_dirty = 0; if (sh_m1_wide() && !masked) pv_m1_mask(0); sh_pv_hud(); }   // v185b: one mask per pass
        }
        if (!f || f == last || pv_mode == 2 || !pv_ok()) { msleep(5); continue; }
        sl = (f - 1) % ns;
        cur_mode = pv_mode;
        t = get_tick_count();
        pv_m1_dflush(pv_stby_phys + sl * pv_stby_fb, lvn_lb, cur_mode, 0);
        tf = get_tick_count();
        pv_m1_render((const char *)(pv_stby_phys + sl * pv_stby_fb), lvn_bpp, 0);
        fl = tf - t; t = get_tick_count() - tf;   // v184b: fl = dflush ms, t = render ms
        last = f;
        if (pv_mode == 2) { pv_mask_dirty = 1; pv_has_img = 0; continue; } // switched OFF meanwhile: sh_preview blacks it
        if (pv_cap_seq - f >= (ns > 1 ? ns - 1 : 1)) { pv_stby_torn++; continue; }   // capture f+ns-1 reuses slot (f-1)%ns
        vid_bitmap_refresh();
        msleep(5);   // v184b: yield to the Canon tasks at prio >= 0x1E every shown frame
        pv_stby_n++; pv_has_img = 1;
        pv_stby_fl_sum += fl;
        pv_stby_ren_sum += t;
        if (!pv_stby_ren_min || t < pv_stby_ren_min) pv_stby_ren_min = t;
        if (t > pv_stby_ren_max) pv_stby_ren_max = t;
        if (pv_hud_dirty || (pv_stby_n & 7) == 1) { if (pv_hud_dirty && sh_m1_wide()) pv_m1_mask(0); pv_hud_dirty = 0; sh_pv_hud(); }
    }
    pv_stby_done = 1;
    ExitTask();
}
static void sh_preview(char *buf, unsigned phys, unsigned lines)
{
    unsigned fails = 0, dt, endp, fb = lines * lvn_lb, ns = 1, cap_ms = 0;
    int m1 = x_m1 && sh_is_m1();   // v182: ImgMode 1 1440p preview (colour, opaque mask, 3 views)
    sh_pv_key = 0; sh_pv_n = 0; pv_stat[0] = 0; pv_clip_pct = 0;
    pv_geom(); sh_hud_clear();
    pv_make_lut(m1 ? 127 : 64, 300);
    if (m1) {
        x_px = 0;
        ns = (x_exsz > 0x00080000 && fb) ? (x_exsz - 0x00080000) / fb : 1; if (ns > 8) ns = 8; if (ns < 1) ns = 1;   // v184b: up to 8 slots (48 MiB: ~300-420 ms wrap margin)
        pv_m1_mask(pv_has_img ? 0 : 1); sh_pv_hud();   // v184a: REC -> Standby keeps the last image (no black flash)
        pv_cap_seq = 0; pv_stby_n = pv_stby_torn = pv_stby_ren_min = pv_stby_ren_max = pv_stby_ren_sum = pv_stby_fl_sum = 0;
        pv_hud_dirty = pv_mask_dirty = 0;
        pv_stby_phys = phys; pv_stby_fb = fb; pv_stby_ns = ns;
        if (pv_stby_done) { pv_stby_done = 0; pv_stby_on = 1; CreateTask("M10PvS", 0x1E, 0x1000, pv_stby_task); }
    }
    slog("v165 preview start lines=%d ns=%d", lines, ns);
    for (;;) {
        int r;
        unsigned sl = m1 ? pv_cap_seq % ns : 0, t0;
        if (sh_stop_req) { sh_pv_key = 1; break; }                          // REC (keywatch)
        if (kbd_is_key_pressed(KEY_SET) && !kbd_is_key_pressed(KEY_MENU)) { sh_pv_key = 2; break; }   // v182: SET starts REC too
        if (sh_quit_req || (kbd_is_key_pressed(KEY_MENU) && kbd_is_key_pressed(KEY_SET))) { sh_pv_key = 3; break; }   // v176: MENU held / MENU+SET = quit
        if (sh_usb()) { sh_pv_key = 4; break; }
        if (m1) {                                                          // v182: hold while ImgMode 1 runs (no magnifier head here)
            if (!m1_ready() || *(volatile unsigned *)DSS_FLAGS == 0) {
                sh_pv_key = 5;
                slog("v184c key=5 is=%d tg=%d", *(volatile unsigned *)0x865c, *(volatile unsigned *)0xe664);   // v184c: exact state
                slog("  dss=%x rec=%d", *(volatile unsigned *)DSS_FLAGS, (unsigned)camera_info.state.mode_rec);
                break;
            }
            if (!sh_is_m1() || sh_m1_geom(sh_prof()) != sh_m1_armed_geom) { sh_pv_key = 7; break; }                     // profile changed away from 1440p
        } else if (shamem(0xc0f06804) != 0x045702a6 || *(volatile unsigned *)DSS_FLAGS == 0) { sh_pv_key = 5; break; }
        {
            int nv = sh_handle_nav(m1 ? 0 : 1);
            if (m1) { if (nv == 2) pv_mask_dirty = 1; if (nv) pv_hud_dirty = 1; }   // v184a: drawn by M10PvS (no sync draw)
            else { if (nv == 2) { pv_clear(); pv_geom(); } if (nv) sh_pv_hud(); }
            if (m1 && (!sh_is_m1() || sh_m1_geom(sh_prof()) != sh_m1_armed_geom)) { sh_pv_key = 7; break; }
        }
        if (m1 && pv_mode == 2) {                                         // view OFF: no capture at all, black mask + HUD + keys
            if (pv_ok() && (pv_mask_dirty || pv_hud_dirty || PV_RGBA[21 * PV_BW + 358] != PV_BLACK || PV_RGBA[120 * PV_BW + 180] != PV_BLACK)) {
                pv_mask_dirty = pv_hud_dirty = 0; pv_m1_mask(1); sh_pv_hud();
            }
            wb_mon(0); sh_gui_assert();
            msleep(100);
            continue;
        }
        dt = endp = 0;
        t0 = get_tick_count();
        r = lvn_cap(buf + sl * fb, phys + sl * fb, lines, &dt, &endp);
        if (px_on) px_close();
        if (*(volatile unsigned *)(0x0000fa68 + 0x1c)) {                    // trapped head error: acknowledge, re-arm (as REC)
            *(volatile unsigned *)(0x0000fa68 + 0x1c) = 0;
            eng_out(0xc0f072c8, 0x20); eng_out(0xc0f072cc, 0x20); eng_out(0xc0f072d0, 0x40); eng_out(0xc0f072d4, 0x40);
            fails++; msleep(80);
        } else if (r <= 0 || r == 2) {
            fails++; msleep(r == 2 ? 10 : 80);
        } else {
            fails = 0;
            if (m1) { cap_ms += get_tick_count() - t0; pv_cap_seq++; }    // v184a: hand the slot to M10PvS, capture the next one at once
            else pv_render(buf);
            sh_pv_n++;
            if (!m1 && (sh_pv_n & 7) == 1) sh_pv_hud();   // v183b: 1/8
        }
        if (fails >= 20) { sh_pv_key = 6; break; }
        wb_mon(0); sh_gui_assert();
        if (!m1) msleep(20);                                                // v184a: ImgMode 1 back to back (lvn_cap paces on the sensor)
    }
    if (px_on) px_close();
    if (m1) {
        unsigned t = get_tick_count();
        pv_stby_on = 0;
        while (!pv_stby_done && get_tick_count() - t < 2000) msleep(10);
        if (!pv_stby_done) { ts_pinned = 1; slog("v184 stby preview task still running: EXMEM pinned", 0, 0); }   // never free a buffer it may read
        if (sh_is_m1() && sh_pv_key != 1 && sh_pv_key != 2) pv_m1_mask(1);   // v184a: REC/SET keep the image into REC
        slog("v184 stby cap=%d ren=%d", sh_pv_n, pv_stby_n);
        slog("  v184 cap_avg=%d torn=%d", sh_pv_n ? cap_ms / sh_pv_n : 0, pv_stby_torn);
        slog("  v184 ren min=%d avg=%d", pv_stby_ren_min, pv_stby_n ? pv_stby_ren_sum / pv_stby_n : 0);
        slog("  v184 ren max=%d", pv_stby_ren_max, 0);
        slog("  v184b fl_avg=%d ren_avg=%d", pv_stby_n ? pv_stby_fl_sum / pv_stby_n : 0, pv_stby_n ? pv_stby_ren_sum / pv_stby_n : 0);
    } else pv_clear();
    slog("v165 preview end key=%d frames=%d", sh_pv_key, sh_pv_n);
    slog("  v165 black=%d mean=%d", pv_stat[1], pv_stat[2]);
}
static void lv_x3(void)
{
    exmem_alloc_info ai;
    char *buf, cfg[384];   // v129: long CFG lines
    unsigned phys, k, i, npass = 1, lines = 256, bpp = 14, wms = 0, gap = 500, fl = 0, nfit, kk;
    int fd, ok = 1;

    if (ts_pinned) { strcpy(msg, "EXMEM pinned: redemarrer"); return; }
    msg[0] = 0; x_chf = 0; x_xo = 0; x_lo = 2000; x_hi = 7000; x_trg = 0; x_trg_done = 0; x_trg_us = 0; trg_busy = 0; trg_skip = 0;   // v179
    px_cycle = 6; x_need = 0; x_start_us = 0; ch_idx = 12; x_he_mode = 0; x_dc = 99; x_skipy = 0; x_skipn = 0; x_skips = 0; x_skip_fr = 0; x_enc = 0; x_csh = 4; x_unpk = 0; x_unpk_set = 0; x_j9c = 0; x_jpn = 0; enc_wr2 = 9; enc_rd = 0x23; lj_eh = 0; enc_w2w = enc_w2h = 0; x_epn = 0; lj_ns = 1; lj_gap = 0; lj_new_win = 0; lj_last_win = 0; lj_swlo = lj_swhi = 0; lj_swch = 0x40000; enc_mode = 1; x_rowm = 1; enc_prm_a = enc_prm_b = 0; enc_wov = 0; enc_rdb = 0; enc_wstride = 0; lj_wlo = lj_whi = 0; x_hbn = 6; lj_swe = 0; lj_eoff = 0; lj_kwait = 8000; lj_chase = 0; lj_chased = 0; lj_chase_n = 0; lj_chase_miss = 0; lj_u371 = 0; lj_ebits = 0; lj_rdf = 0; x_her = 0; x_exsz = EXMEM_SIZE; x_pbl = 0; x_skick = 0; ts_period = 0; x_rsel = 0; x_he_fix = 0; x_he_fixed = 0; x_dup_us_max = 0;           // v73 defaults (6 frames = 240 ms max hold of sem #6)
    fd = sh_on ? -1 : open("A/M10X3.CFG", O_RDONLY, 0777);
    if (sh_on || fd >= 0) {
        int n;
        if (sh_on) { unsigned kd = sh_prof()->kind; const char *rc = kd == SH_M1 ? SH_RECIPE_M1 : (kd == SH_X3 && !sh_pv) ? SH_RECIPE_X3 : SH_RECIPE; n = strlen(rc); memcpy(cfg, rc, n); }   // v160: built-in recipe (v178: 1x3, v182: ImgMode 1)
        else { n = read(fd, cfg, sizeof(cfg) - 1); close(fd); }
        if (n > 0) {
            char *q = cfg;
            cfg[n] = 0;
            npass = strtol(q, &q, 10);
            lines = strtol(q, &q, 10);
            bpp = strtol(q, &q, 10);
            wms = strtol(q, &q, 10);
            if (*q) { unsigned g = strtol(q, &q, 10); if (g > 0 && g <= 2000) gap = g; }
            if (*q) fl = strtol(q, &q, 10);         // v32 flags
            if (*q) x_chf = (unsigned)strtol(q, &q, 16);      // v68: CH12 EDMAC flags override
            if (*q) x_xo = hex_u32(&q);                        // v72: options (v84b: unsigned parse, bit 31 usable)
            if (*q) { unsigned v = strtol(q, &q, 10); if (v <= 40000) x_lo = v; }   // v180d: allow blanking offset up to 40 ms in m1
            if (*q) { unsigned v = strtol(q, &q, 10); if (v > x_lo && v <= 45000) x_hi = v; }   // v180d: allow window end up to 45 ms in m1
            if (*q) { unsigned v = strtol(q, &q, 10); if (v <= 50) px_cycle = v; }    // v73: frames per sem #6 hold (0 = whole run)
            if (*q) { unsigned v = strtol(q, &q, 10); if (v <= 1800) x_need = v; }    // v73/v180/v185: min lines of a kept short frame
            if (*q) { unsigned v = strtol(q, &q, 10); if (v <= 30000) x_start_us = v; }   // v79
            if (*q) { unsigned v = strtol(q, &q, 10); if (v == 2 || v == 5 || v == 11 || v == 12 || v == 14 || v == 18 || v == 19) ch_idx = v; }   // v81
            if (*q) x_he_mode = strtol(q, &q, 10);      // v85: 16th field
            if (*q) { unsigned v = strtol(q, &q, 10); if (v <= 24) x_dc = v; }   // v86: 17th field
            if (*q) { unsigned v = strtol(q, &q, 10); if (v <= 8) x_skipy = v; }   // v90: 18th field, RAWC skipping_y
            if (*q) { unsigned v = strtol(q, &q, 10); if (v <= 100) x_skipn = v; }   // v91: 19th field
            if (*q) { unsigned v = strtol(q, &q, 10); if (v == 10 || v == 11 || v == 12 || v == 14) x_enc = v; }   // v92: 20th field (v93: 10 = convert to 14 first)
            if (*q) { unsigned v = strtol(q, &q, 10); if (v <= 255) x_csh = v; }   // v94: 21st field = shift
            if (*q) { x_unpk = hex_u32(&q); x_unpk_set = 1; }   // v97: 22nd field = unpacker reg value (hex)
            while (*q == ' ') q++;
            while (*q && *q != '\n' && x_jpn < 12) {   // v99: 23rd field = OO:VVVVVVVV[,OO:VVVVVVVV...] JpCore pokes (hex)
                unsigned o = hex_u32(&q), v;
                if (*q != ':') break;
                q++; v = hex_u32(&q);
                if (o < 0x400 && !(o & 3)) { x_jpo[x_jpn] = o; x_jpv[x_jpn] = v; x_jpn++; }
                if (*q == ',') q++; else break;
            }
            while (*q == ' ') q++;
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v <= 6 || (v >= 7 && v <= 13)) enc_wr2 = v; }   // v104: 24th field = encoder WR2 channel
            if (*q && *q != '\n') { lj_wlo = strtol(q, &q, 10); if (*q) lj_whi = strtol(q, &q, 10); }   // v105: 25th/26th = encoder start window
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v >= 25 && v <= 47) enc_rd = v; }   // v106: 27th = encoder read channel
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v >= 16 && v <= 1800) lj_eh = v & ~1u; }   // v107/v180: 28th = encoder lines
            if (*q && *q != '\n') { enc_w2w = strtol(q, &q, 10); if (*q) enc_w2h = strtol(q, &q, 10); }   // v110: 29th/30th = WR2 (preview) w h
            while (*q == ' ') q++;
            while (*q && *q != '\n' && x_epn < 4) {   // v111: 31st field = AAAAAAAA:VVVVVVVV[|][,...] engine pokes after encoder setup ('|' = OR)
                unsigned a = hex_u32(&q), v, m = 0;
                if (*q != ':') break;
                q++; if (*q == '|') { m = 1; q++; }
                v = hex_u32(&q);
                if ((a >> 24) == 0xc0 && !(a & 3)) { x_epa[x_epn] = a; x_epv[x_epn] = v; x_epm[x_epn] = m; x_epn++; }
                if (*q == ',') q++; else break;
            }
            while (*q == ' ') q++;
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v >= 1 && v <= 32) lj_ns = v; }   // v112: 32nd field = slices
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v <= 20000) lj_gap = v; }   // v113: 33rd = gap us
            if (*q && *q != '\n') lj_new_win = strtol(q, &q, 10);   // v115: 34th = 1 -> one slice per 8830 window
            if (*q && *q != '\n') { lj_swlo = strtol(q, &q, 10); if (*q) lj_swhi = strtol(q, &q, 10); }   // v116: 35th/36th = SD write window
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v >= 16 && v <= 4096) lj_swch = v * 1024; }   // v116: 37th = chunk KiB
            if (*q && *q != '\n') enc_mode = strtol(q, &q, 10);   // v130: 38th = encoder cfg[7]
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v >= 1 && v <= 8) x_rowm = v; }   // v131: 39th = CH12 lines per row
            if (*q && *q != '\n') { enc_prm_a = strtol(q, &q, 10); if (*q) enc_prm_b = strtol(q, &q, 10); }   // v132: 40th/41st = FN_LL_PARAM
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v >= 64 && v <= 2592 && !(v & 15)) enc_wov = v; }   // v133: 42nd = encoder width (v159: up to 2592, checked against x_w below)
            if (*q && *q != '\n') enc_rdb = strtol(q, &q, 10);   // v134: 43rd = RD1 burst setter
            if (*q && *q != '\n') enc_wstride = strtol(q, &q, 10);   // v135: 44th = 1: encoder source stride = encoder width
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v <= 20000) lj_kwait = v; }   // v138: 45th = kick wait us
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v < 0x100000 && !(v & 3)) lj_eoff = v; }   // v139: 46th = encoder source offset (bytes, 4-aligned)
            if (*q && *q != '\n') lj_swe = strtol(q, &q, 10);   // v142: 47th = SD write only while the encoder is idle
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v >= 2 && v <= 32) x_hbn = v; }   // v143: 48th = burst stop threshold
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v < 1800) lj_chase = v; }   // v144/v180: 49th = chase start line (0 = off)
            if (*q && *q != '\n') lj_u371 = strtol(q, &q, 16);   // v145: 50th = c0f371fc raw value (hex) for REC encodes
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v == 1 || v == 2) lj_ebits = v; }   // v146: 51st = encoder depth code
            if (*q && *q != '\n') lj_rdf = strtol(q, &q, 16) & 0x60001000u;   // v147: 52nd = RD1 transfer-size flags (hex)
            if (*q && *q != '\n') x_her = strtol(q, &q, 10);   // v148: 53rd = no-pause head-error recovery
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v >= 16 && v <= 48) x_exsz = v << 20; }   // v149: 54th = EXMEM MiB
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v <= 1800) x_pbl = v; }   // v150/v180: 55th = busy-poll lines
            if (*q && *q != '\n') x_skick = strtol(q, &q, 10);   // v151: 56th = kick on short frames
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 10); if (v >= 1000 && v <= 10000) ts_period = v; }   // v153: 57th = task sampler us (0 off)
            if (*q && *q != '\n') { unsigned v = strtol(q, &q, 16); if (v == 0x10 || v == 0x12 || v == 0x22 || v == 0x2e) x_rsel = v; }   // v169: 58th = raw selector (hex)
            if (*q && *q != '\n') x_he_fix = strtol(q, &q, 10);   // v172: 59th = replace HEAD_ERR frames by previous healthy frame
        }
    }
    if (!sh_on) {   // v179: trigger block address (hex) in A/M10TRG.CFG (host test only; deleted by the host after use)
        int tf = open("A/M10TRG.CFG", O_RDONLY, 0777);
        if (tf >= 0) {
            char tb[24], *q = tb; int tn = read(tf, tb, sizeof(tb) - 1); close(tf);
            if (tn > 0) { unsigned a; tb[tn] = 0; a = hex_u32(&q); if (a >= 0x1000 && a < 0x40000000 && !(a & 3)) x_trg = (unsigned *)a; }
        }
    }
    if (sh_on && sh_prof()->kind == SH_M1) {   // v182: ImgMode 1 1440p: the capture is already 1920 wide (no encoder crop)
        const sh_prof_t *pr = sh_prof();
        unsigned ro_end = ((32u + pr->h + 16u) * (pr->lclk + 1u) + 31u) / 32u;   // v186b: readout end (us after CMOS 0)
        lines = pr->h;                                 // v185: profile frame height
        if (pr->per > 37000) x_lo = (ro_end + 600 > 35166u) ? ro_end + 600 : 35166u;   // v186b: arm inside V-blank (24p)
        else x_lo = (ro_end + 400 > pr->per - 4500u) ? ro_end + 400 : pr->per - 4500u;   // v186b: 30p
        x_hi = pr->per - 1200u;
        if (x_lo > x_hi - 400u) x_lo = x_hi - 400u;
        if (!sh_pv) {
            bpp = sh_bpp; x_rsel = 0x10; x_he_fix = 1; lj_eoff = 0; enc_wov = 0;   // v186b: depth from the BIT selector
            x_need = pr->h - 4; lj_eh = pr->h;
            lj_kwait = 8000;
        }
        else { bpp = 10; x_rsel = 0x10; x_he_fix = 0; x_need = pr->h - 4; }   // v185b: Standby waits for the full head too
    } else if (sh_on) {
        const sh_prof_t *pr = sh_prof();
        if (!sh_pv) { bpp = pr->bpp; x_rsel = pr->rsel; x_he_fix = pr->kind == SH_X3 ? 0 : 1; }   /* v178: 1x3 keeps HE frames (host repair) */   // v172: preview stays 10-bit; REC uses profile depth/selector + HE replacement
        else { bpp = 10; x_rsel = 0; x_he_fix = 0; }   // v174: recipe is now the 14-bit REC line; preview keeps its v165 10-bit path
        enc_wov = pr->w;
        if (pr->kind != SH_X3) lj_eoff = pr->c0 * bpp / 8;   // v178: 1x3 keeps the recipe offset (row 28, column 136)
    }
    if (x_he_fix && (!(fl & 0x100) || !(fl & 0x1000000) || !(x_xo & 0x80000000) || !x_her ||
                     x_enc != 11 || lj_ns != 1 || lj_new_win != 2 || lj_chase)) {
        strcpy(msg, "HEFIX: kick/HER sans chase requis");
        return;   // v172b: replacement only in the qualified single-stream kick path
    }
    {   // v81: write channel geometry (ROM table 0xfc6d87b8 / resources 0xfc6dd8e4)
        static const unsigned cb[25] = { 0xc0f04000, 0xc0f04100, 0xc0f04200, 0xc0f04300, 0xc0f04400, 0xc0f04500, 0xc0f04600,
            0xc0f26000, 0xc0f26100, 0xc0f26200, 0xc0f26300, 0xc0f26400, 0xc0f26500, 0xc0f26600,
            0xc0f30000, 0xc0f30100, 0xc0f30200, 0xc0f30300, 0xc0f30400, 0xc0f30500, 0xc0f30600, 0xc0f57000, 0xc0f58000, 0xc0f58100, 0xc0f58200 };
        ch_base = cb[ch_idx];
        ch_xbar = ch_idx < 8 ? 0xc0f05000 + 4 * ch_idx : 0xc0f051e0 + 4 * ch_idx;
        reslist[0] = 0x55 + ch_idx;       // resource id of the channel (0x61 for 12)
    }
    x_busy_max = x_busy_tot = x_waits = x_late_acc = 0; x_ref_tick = 0;
    x_diag = (x_xo & 0x20000000) ? 1 : 0;   // v80
    if (npass < 1) npass = 1;
    if (npass > LVM2_PASS && !(fl & 0x104)) npass = LVM2_PASS;
    if (npass > XR_MAX) npass = XR_MAX;                 // v33: long runs reuse the buffer (no image file)
    if (lines < 16) lines = 256;
    if (lines > 1800) lines = 1800;                 // v180/v185: up to 1800 lines (< 4 MiB checked below)
    x_m1 = (*(volatile unsigned *)0x865c == 1) ? 1 : 0;   // v180: ImgMode 1 continuous 1440p
    x_hi_post = x_m1 ? 45000 : 30000;   // v180d: m1 restore waits for CMOS 0 + x_lo (~35 ms)
    // v65: Film 1x3 frame = 1185 lines at the CH12 end (1190 head - 5): asking
    // more leaves the DMA armed -> Canon's chain dies a few frames later (r84c).
    { unsigned hh = (shamem(0xc0f06804) >> 16) & 0xffff;   // v89s: any tall head (live103: 1254...) -> CH12 frame = H - 6
      if (!x_m1 && (fl & 0x20000000) && hh >= 0x4a6 && hh <= 1280 + 6 && lines > ((x_xo & 0x1000) ? hh : hh - 6)) lines = (x_xo & 0x1000) ? hh : hh - 6; }   // v75d: xo 0x1000 = ask more, end by the 8830 abort
    if (bpp != 10 && bpp != 12) bpp = 14;
    x_zoom = (!x_m1 && zoom_head(shamem(0xc0f06804))) ? 1 : 0;   // v156/v180: x5 magnifier, 2592 x 1108
    x_w = x_zoom ? 2592 : LVN_W; x_per = x_zoom ? 33307 : 40000;
    if (x_zoom) { unsigned m = *(volatile unsigned *)0x865c, pc = (m < 0x34) ? *(volatile unsigned *)(0x575b0 + 36 * m + 0x1c) : 0; if (pc >= 20000 && pc <= 60000) x_per = pc; }   // v158: m10zfps.py sets 40017
    if (x_zoom) { unsigned zl = (shamem(0xc0f06804) >> 16) - 7; if (lines > zl) lines = zl; }   // native 1111-line head -> 1104 (v168z: H - 7)
    if (x_m1) {
        unsigned h6800 = shamem(0xc0f06800), h6804 = shamem(0xc0f06804);
        unsigned hw = ((h6804 & 0xffff) - (h6800 & 0xffff)) * 4;
        unsigned hh = (h6804 >> 16) - (h6800 >> 16) + 1;
        unsigned pc = *(volatile unsigned *)(0x575b0 + 36 * 1 + 0x1c);
        if (hw >= 640 && hw <= 2592 && !(hw & 15)) x_w = hw;
        if (hh >= 64 && lines > hh) lines = hh;
        if (pc >= 20000 && pc <= 160000) x_per = pc;
        if (x_hi + 1200 < x_per && x_per - 1200 > x_lo) x_hi = x_per - 1200;   // v180f (r159): arm window up to per - 1.2 ms (4 -> 5.3 ms at 24p: skips 7 -> 2 /99)
    }
    if (enc_wov > x_w) enc_wov = 0;                        // v159
    lvn_bpp = bpp; lvn_lb = x_w * bpp / 8;
    {   // v170: allow 2-block CH12 (> 4 MiB) when cropping 14-bit into a < 4 MiB encoder window
        unsigned enc_fb_est = (enc_wov ? enc_wov : x_w) * (lj_eh ? lj_eh : lines) * bpp / 8;
        if (lines * lvn_lb > 0x00400000) {
            if (!(x_zoom && bpp == 14 && (x_enc == 11 || x_enc == 14) && enc_wov && enc_fb_est <= 0x00400000 && (lines - lines / 2) * lvn_lb <= 0x00400000) &&
                !(x_m1 && (x_enc == 11 || (sh_on && sh_pv)) && (lines - lines / 2) * lvn_lb <= 0x00400000))   // v186a/v186b: ImgMode 1 REC + Standby, 2-block CH12 up to 8 MiB
                lines = 0x00400000 / lvn_lb;   // one EDMAC block < 4 MiB
        }
    }
    memset(&lm2, 0, sizeof(lm2));
    memcpy(lm2.magic, "M10LVX03", 8);
    lm2.w = x_w; lm2.lines = lines; lm2.lb = lvn_lb; lm2.npass = npass;
    lm2.r6804 = shamem(0xc0f06804); lm2.r6800 = shamem(0xc0f06800);
    lm2.r6008 = shamem(0xc0f06008); lm2.r6014 = shamem(0xc0f06014);
    lm2.dss_w = *(volatile unsigned *)0x001beb5c; lm2.dss_h = *(volatile unsigned *)0x001beb60;
    memcpy(lm2.cbr0, (void *)CBR_CH12, 12);
    slog("v25 LVX3 start 6804=%08x npass=%d", lm2.r6804, npass);
    slog("  lines=%d bpp=%d", lines, bpp);
    slog("  v156 zoom=%d w=%d", x_zoom, x_w); slog("  v158 per=%d us", x_per, 0);
    if (x_m1) slog("  v180 m1=1 lines=%d", lines, 0);
    slog("  v32 flags=%x gap=%d", fl, gap);
    idle_polls = (fl & 8) ? 2 : 20;
    lvn_post_ms = (fl & 0x10) ? 8 : 0;
    if (fl & 0x20) { tl_step = 250; lvm_sleep = 0; }  // v34: calibration pass (busy poll)
    lvn_sync = (fl & 0x40) ? 1 : 0;                 // v35: start each pass at the frame end
    wait_sleep = (fl & 0x1000) ? 1 : 0;             // v42: sleep in wait_eof (normally REC only)
    sync_late_max = (fl & 0x4000) ? 1500 : 0;       // v42: ignore a burst seen > 1.5 ms late
    sync_skips = 0; sync_last = 0; sync_per = 0; sync_prev = 0; pk_late = 0;
    sync_second = 0;
    sync_delay_us = (fl & 0x8000) ? 9000 : 0;      // v47: FHD 1x3: readout starts ~11 ms after the burst
    if ((fl & 0x8000) && (fl >> 16)) sync_delay_us = (fl >> 16) * 100;   // v48: flags bits 16+ = delay in 100 us
    sync_first = (fl & 0x200000) ? 1 : 0;          // v49 (overrides: no delay)
    sync_second = (fl & 0x400000) ? 1 : 0;         // v50: FHD 1x3: arm right after the 2nd burst (readout just ended)
    if (sync_second) sync_delay_us = 0;
    if (fl & 0x800000) lvn_sync = 3;               // v53: sync on the LV EDMAC end
    lv_last_end = 0;
    x_prec = (fl & 0x4000000) ? 1 : 0;             // v61: precise timing (no 10 ms sleep during the readout)
    x_chain = (fl & 0x8000000) ? 1 : 0;            // v61: chain passes on our own readout end
    x_post_us = (fl & 0x10000000) ? 1500 : 0;      // v61: busy wait after the DMA end
    x_prev_ok = 0; x_chained = 0; x_short = 0; x_short_min = 0;
    x_abort = 0;
    if (fl & 0x20000000) {                         // v62: sync on DFE 8830 (+ delay = wms * 100 us if set)
        lvn_sync = 4; x_dfe_ts = 0; x_dfe_miss = 0;
        x_dly_us = 6000;
        if (!(fl & 0x100) && wms >= 10 && wms <= 150) { x_dly_us = wms * 100; wms = 0; }
    }
    slog("  v61 prec=%d chain=%d", x_prec, x_chain);
    slog("  v62 sync=%d dly=%d", lvn_sync, x_dly_us);
    slog("  v68 ch12 flags=%08x", x_chf ? x_chf : ((x_xo & 4) ? 0x1000 : 0x40000000), 0);
    slog("  v72 xo=%x lo=%d", x_xo, x_lo);
    slog("  v72 hi=%d", x_hi, 0);
    slog("  v179 trg=%08x", (unsigned)x_trg, 0);
    if (sync_first) sync_delay_us = 0;
    if (fl & 0x80) { idle_polls = 0; gap = 0; }     // v36: back-to-back (every frame)
    // v73: persistent pipeline: 8830 sync with the CPU-friendly window only,
    // back-to-back passes (a gap would leave PACK32 on across readouts anyway:
    // lvn_cap closes when the window is gone, so a gap just costs a re-open)
    x_px = ((x_xo & 0x10) && lvn_sync == 4 && !x_prec) ? 1 : 0;
    if (x_px) { x_xo |= 1; idle_polls = 0; gap = 0; }   // ch12_idle 20 x msleep(5) / a gap would miss the window
    px_on = 0; px_opens = px_frames = px_late = px_rearm_err = px_pulses = 0; x_short_bad = 0;
    { unsigned hh = (shamem(0xc0f06804) >> 16) & 0xffff; x_flines = x_m1 ? lines : ((hh >= 0x4a6 && hh <= 1286) ? hh - 6 : 0); }   // v65/v180
    slog("  v73 px=%d cycle=%d", x_px, px_cycle);
    slog("  v73 need=%d flines=%d", x_need, x_flines);
    slog("  v80 build xo=%x diag=%d", x_xo, x_diag);
    slog("  v82 headerr0=%08x", *(volatile unsigned *)(0x0000fa68 + 0x1c), 0);
    x_heads = 0; x_he_pass = 0; x_he_val = 0; x_he_n = 0; x_he_late = 0; x_skick_n = 0; hs_n = 0; hs_after = 0; ea_n = 0; x_r450a0 = 0xffffffff; x_r450_fix = 0; x_he_frz = 0; wr_force = 0; tg_fix_n = 0; memset(wb_tick, 0, sizeof(wb_tick)); memset(wb_max, 0, sizeof(wb_max)); wb_logged = 0; wb_kick_n = 0; memset(x_hst, 0, sizeof(x_hst));   // v88: hs_*
    slog("  v85 he_mode=%d", x_he_mode, 0);
    slog("  v86 dc=%d", x_dc, 0);
    slog("  v81 ch=%d base=%08x", ch_idx, ch_base);
    slog("  v81 xbar=%08x res=%x", ch_xbar, reslist[0]);
    slog("  v79 start_us=%d", x_start_us, 0);
    slog("  v75 8090=%08x 370d4=%08x", shamem(0xc0f08090), shamem(0xc0f370d4));
    slog("  37014=%08x 37074=%08x", shamem(0xc0f37014), shamem(0xc0f37074));
    slog("  tg=%d is=%08x", *(volatile unsigned *)0x0000e664, (*(volatile unsigned *)0x00008654 << 16) | (*(volatile unsigned *)0x00008658 & 0xffff));
    /* v153: same extra reserve for REC off/on, no change to raw/compressed ring
     * addresses or existing SIO scratch. Never allocate the trace in CHDK heap. */
    if (x_rsel) slog("v169 rsel=%x canon 37040=%08x", x_rsel, shamem(0xc0f37040));
    if (ts_period && (!(fl & 0x100) || !ts_kernel_ok())) { strcpy(msg, "TSK kernel/config refuse"); slog("v153 task preflight refused", 0, 0); return; }
    buf = exmem_alloc_uncached(EXMEM_TYPE, x_exsz + ((fl & 0x100) ? TS_EXTRA + CAP_BYTES : 0), &ai);
    if (!buf) { strcpy(msg, "EXMEM refuse"); return; }
    phys = (unsigned)buf & 0x3fffffff;
    slog("  v75k buf phys=%08x nfit=%d", phys, (x_exsz - 0x00080000) / (lines * lvn_lb));
    nfit = (x_exsz - 0x00080000) / (lines * lvn_lb);   // v30: last 512 KiB = SIO ring copy
    if (npass > nfit && !(fl & 0x104)) npass = nfit;
    memset(buf, 0xee, (npass < nfit ? npass : nfit) * lines * lvn_lb);
    x_mcsrc = (x_xo & 0x1000000) ? buf + 3 * lines * lvn_lb : 0;   // v77: passes then use slots 0-2 only

    if (x_xo & 0x80000) {                           // v76: let Canon capture (EvfCaptureSystem 0xfc145636)
        unsigned mode = *(volatile unsigned *)0x865c, ok8664 = *(volatile unsigned *)0x8664;
        volatile unsigned *ce = (volatile unsigned *)(0x575b0 + 36 * mode);
        unsigned b_saved = ce[4], w, h, b, lb, fb, ns, kk2;
        if (x_xo & 0x800000) ce[4] = 10;            // v76b: 10-bit capture (cache bpp restored at the end)
        w = ce[0]; h = ce[1]; b = ce[4]; lb = w * b / 8; fb = lb * h;
        slog("v76 EVFCAP mode=%d 8664=%d", mode, ok8664);
        slog("  cache %dx%d", w, h);
        slog("  bpp=%d tg=%d", b, *(volatile unsigned *)0x0000e664);
        if (mode != 36 || ok8664 != 1 || !fb || fb > 0x00800000) {
            ce[4] = b_saved;
            slog("  v76 refused (would change mode)", 0, 0);
            exmem_free_uncached(EXMEM_TYPE); strcpy(msg, "EVFCAP refus"); return;
        }
        ns = (x_exsz - 0x00080000) / fb;
        memset(buf, 0xee, ns * fb);
        memset(&lm2, 0, sizeof(lm2)); memcpy(lm2.magic, "M10LVX03", 8);
        lm2.w = w; lm2.lines = h; lm2.lb = lb; lm2.npass = npass;
        lm2.r6804 = shamem(0xc0f06804);
        for (k = 0; k < npass; k++) {
            unsigned t0 = get_tick_count(), u0 = usec(), r;
            kk2 = k < 8 ? k : 8 + (k - 8) % 8;
            r = ((fn2)0xfc145637)(mode, (unsigned)buf + (k % ns) * fb);
            lm2.dt[kk2] = udiff(u0, usec()); lm2.st[kk2] = r; lm2.tick[kk2] = get_tick_count();
            lm2.cbr[kk2][1] = *(volatile unsigned *)0x0000e664;
            lm2.cbr[kk2][2] = *(volatile unsigned *)0x00008664;
            lm2.ndone = k + 1;
            if (*(volatile unsigned *)0x0000e664 != 3 && *(volatile unsigned *)0x0000e664 != 1) { ok = -1; break; }
            if (get_tick_count() - t0 > 3000) { ok = 0; break; }
            if (gap) msleep(gap);
        }
        ce[4] = b_saved;                            // v76b
        for (k = 0; k < lm2.ndone && k < 16; k++) slog("v76 cap %d dt=%d", k, lm2.dt[k]), slog("   r=%d tg=%d", lm2.st[k], lm2.cbr[k][1]);
        fd = open("A/LVX3.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
        if (fd >= 0) { write(fd, &lm2, sizeof(lm2)); write(fd, buf, (lm2.ndone < ns ? lm2.ndone : ns) * fb); close(fd); }
        exmem_free_uncached(EXMEM_TYPE);
        sprintf(msg, "EVFCAP %d/%d %s", (int)lm2.ndone, (int)npass, ok > 0 ? "ok" : "err");
        slog("v76 done ok=%d", ok, 0);
        lvn_bpp = 14; lvn_lb = LVN_LB;
        for (i = 0; i < 12; i++) { msleep(250); slog("  hb tg=%d 6804=%08x", *(volatile unsigned *)0x0000e664, shamem(0xc0f06804)); }
        return;
    }
    memset(stg, 0, sizeof(stg)); memset(x_pr, 0, sizeof(x_pr));   // v74
    wr_init();                      // v75c
    if (sh_pv) {                                    // v165: live B&W preview of the recorded window, ~10 fps
        sh_preview(buf, phys, lines);
        exmem_free_uncached(EXMEM_TYPE);
        lvn_bpp = 14; lvn_lb = LVN_LB;
        idle_polls = 20; lvn_post_ms = 0; tl_step = 1000; lvm_sleep = 1; lvn_sync = 0; wait_sleep = 0;
        return;
    }
    if (fl & 0x40000000) {                          // v63: EDMAC map only (no capture)
        edmac_map(buf, gap ? gap : 400);
        exmem_free_uncached(EXMEM_TYPE);
        sprintf(msg, "EDMAC map");
        return;
    }
    if (fl & 0x100) {                               // v37: record to card
        unsigned drops = 0, fr = 0, t0, maxbl = 0, xr_slot_cnt = 0, xr_t0_ms = 0;   // v183: 24.00p slots, REC t0
        int turbo_held = 0;   // v186a: FN_LCLK_HOLD0 + FN_CLKSAVE_TAKE held
        if (npass > XR_MAX) npass = XR_MAX;
        xr_fb = lines * lvn_lb;
        xr_mlv = (fl & 0x1000000) ? 1 : 0;          // v55: MLV output
        xr_nullsz = ((xr_fb + 16 + 511) & ~511u) - xr_fb;
        xr_stride = 512 + xr_fb + xr_nullsz;
        xr_nslot = (x_exsz - 0x00080000) / (xr_mlv ? xr_stride : xr_fb);
        lj_on = (x_enc == 11 && xr_mlv && (lvn_bpp == 10 || ((lvn_bpp == 14 || lvn_bpp == 12) && (enc_wov ? enc_wov : x_w) * (lj_eh ? lj_eh : lines) * lvn_bpp / 8 <= 0x00400000))) ? 1 : 0;   // v101/v170: compressed REC (10b or <4 MiB cropped 14b); v177: 12b too
        if (!lj_on && x_m1 && x_enc == 11 && xr_mlv && (lvn_bpp == 10 || lvn_bpp == 12 || lvn_bpp == 14) && (lines - lines / 2) * lvn_lb <= 0x00400000) lj_on = 1;   // v186a: ImgMode 1 2-block CH12 (> 4 MiB) compressed REC
        if (lj_on) {    // raw ring 3 x xr_fb, compressed ring after it, last 512 KiB = SIO copy
            unsigned enc_fb = (enc_wov ? enc_wov : x_w) * (lj_eh ? lj_eh : lines) * lvn_bpp / 8;
            lj_raw_n = 3; lj_cbase = (lj_raw_n * xr_fb + 0xfff) & ~0xfffu;
            lj_cslot_sz = (x_zoom || x_m1 || lvn_bpp == 12) ? ((enc_fb + enc_fb / 8 + 0xffff) & ~0xffffu) : 0x00280000;   /* v177/v180: slots sized by frame */
            if (x_m1 && lvn_bpp == 14 && enc_fb > 0x00400000) lj_cslot_sz = (enc_fb * 4 / 5 + 0xffff) & ~0xffffu;   // v186a: 5.5 MB 14b frame -> 6-7 slots in 48 MiB (LJ92 ~ 0.6x raw)
            lj_cslot_n = (x_exsz - 0x00080000 - lj_cbase) / lj_cslot_sz;
            if (x_m1 && xr_fb > 0x00400000) lj_cslot_n = (x_exsz - 0x000C0000 - lj_cbase) / lj_cslot_sz;   // v186b: > 4 MiB frames keep raw ring 3 (48 MiB -> 7-8 compressed slots)
            else if (x_m1) {   // v181 (r159): raw ring 5 absorbs encoder jitter (12b mean 41.5 < 41.67 ms); compressed slots end before WR2 (x_exsz - 0xC0000)
                unsigned cb5 = (5 * xr_fb + 0xfff) & ~0xfffu, n5 = (x_exsz - 0x000C0000 - cb5) / lj_cslot_sz;
                if (n5 >= 4) { lj_raw_n = 5; lj_cbase = cb5; lj_cslot_n = n5; }
                else lj_cslot_n = (x_exsz - 0x000C0000 - lj_cbase) / lj_cslot_sz;
            }
            if (x_he_fix) {
                if (lj_cslot_n > LJ_MAP_N) lj_cslot_n = LJ_MAP_N;
                if (lj_cslot_n < 2) { exmem_free_uncached(EXMEM_TYPE); strcpy(msg, "HEFIX: slots insuffisants"); return; }
                for (i = 0; i < LJ_MAP_N; i++) lj_map[i] = 0xffffffff;
            }
            xr_nslot = lj_raw_n; lj_cnt = lj_err = lj_done = 0; lj_gate = (fl & 0x200) ? 1 : 0; if (lj_new_win == 2) lj_gate = 2;   // v119: 34th field 2 = slices after readout ends   // v103: flag 0x200 = gated encoder (writes stay ungated in LJ mode)
            lj_buf = (unsigned char *)buf; lj_phys = phys;
            enc_w = enc_wov ? enc_wov : x_w; enc_h = lj_eh ? lj_eh : lines; enc_bits = lj_ebits ? lj_ebits : 2; enc_rd10 = (lvn_bpp == 10 || lvn_bpp == 12) ? 1 : 0; enc_rd12 = (lvn_bpp == 12) ? 1 : 0; enc_unpk = (lvn_bpp == 12) ? 0x10 : 0; enc_prec = 0;   // v170: enc_rd10=0 for 14-bit; v146 lj_ebits; v177: 12b = RD1 depth 1 + unpacker 0x10 (<< 2)
            enc_wr2_off = x_exsz - 0x00080000 - 0x00040000; enc_no_snap = 1; sem_enc = 0;
            {
                int hf = open((lvn_bpp == 14) ? "A/M10HUF14.BIN" : (lvn_bpp == 12) ? "A/M10HUF12.BIN" : "A/M10HUF.BIN", O_RDONLY, 0777);   // v177: 12-bit table
                enc_huff_ok = 0;
                if (hf >= 0) { if (read(hf, enc_huff, 96) == 96) enc_huff_ok = 1; close(hf); }
            }
            slog("v101 LJ raw=%d cslots=%d", lj_raw_n, lj_cslot_n);
            slog("  v101 cbase=%x huff=%d", lj_cbase, enc_huff_ok);
        }
        xr_buf = buf; xr_prod = xr_wr = xr_stop = xr_done = xr_err = 0;
        lm2.npass = npass;
        { char nm[24]; sprintf(nm, "%s.%s", xr_base, xr_mlv ? "MLV" : "RAW"); remove(nm); }   // v180f: free the old take first
        if (x_m1 && x_warm) {   // v180f (r159): 1st 2 MiB write of a take took 0.85-0.9 s (FAT free-cluster search) -> 11 ring drops. Pre-write x_warm MiB from the REC buffer, delete, then open.
            unsigned tw = get_tick_count(), m, wsz = 0x00200000;
            int wf = open("A/M10WARM.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
            if (wf >= 0) {
                for (m = 0; m < x_warm; m += 2) { if (write(wf, buf, wsz) != (int)wsz) break; wb_mon(0); }
                close(wf); remove("A/M10WARM.BIN");
            }
            slog("  v180f warm %d MiB ms=%d", x_warm, get_tick_count() - tw);
        }
        { char nm[24]; sprintf(nm, "%s.%s", xr_base, xr_mlv ? "MLV" : "RAW"); xr_fd = open(nm, O_WRONLY | O_CREAT | O_TRUNC, 0777); }
        if (xr_fd < 0) { exmem_free_uncached(EXMEM_TYPE); strcpy(msg, "RAW open err"); return; }
        xr_fileno = 0; xr_fbytes = 512; xr_chunk_start = 0; xr_roll_ms = xr_roll_n = xr_roll_fr = xr_roll_drops = 0;   // v182
        mlv_guid_lo = get_tick_count();
        mlv_crop = lj_on && (enc_wov || lj_eh || lj_eoff);
        if (mlv_crop) slog("  v159 crop %dx%d", enc_w, enc_h), slog("  v159 eoff=%d", lj_eoff, 0);
        if (xr_mlv) { mlv_build_hdr(mlv_crop ? enc_w : x_w, mlv_crop ? enc_h : lines, lj_on ? 14 : lvn_bpp, 0); if (lj_on) put16(mlv_hdr + 32, 0x21); write(xr_fd, mlv_hdr, 512); }   // v101: MLV video class 0x21 = RAW | LJ92
        else write(xr_fd, &lm2, sizeof(lm2));
        xr_sem = CreateBinarySemaphore("M10XR", 0);
        memset(tlf, 0, sizeof(tlf));   // v140
        capl = (unsigned (*)[5])(buf + x_exsz + TS_EXTRA); memset(capl, 0, CAP_BYTES); cap_n = 0; cap_k = 0xffffffff;   // v154: inside the REC-only reserve allocated above
        if (lj_on) { lj_sem = CreateBinarySemaphore("M10LJ", 0); lj_sem_p = &lj_sem; x_early = (lj_new_win == 2); x_ready = 0; x_dr[0] = x_dr[1] = x_dr[2] = 0; lj_kicked = 0; lj_k_ok = 0; lj_k_no[0] = lj_k_no[1] = lj_k_no[2] = lj_k_no[3] = 0; lj_k_max = 0; lj_prev_sz = 0; lj_prev_tot = 0; lj_dup_h = 0; lj_dup_t = 0; x_kick = (lj_new_win == 2 && lj_ns == 1) ? lj_kick : 0; x_poll = (x_kick && x_m1) ? lj_poll : 0; lj_async_n = 0; CreateTask("M10LJ", 0x1B, 0x1000, lj_task); }   // v124: back to 0x1B (0x19 starved the capture)   // v121   // v101: between capture (0x1A) and writer (0x1C)
        xr_gated = ((fl & 0x200) && !lj_on) ? 1 : 0;           // v39 (v103: LJ uses 0x200 for the encoder)
        xr_wlen = (wms && wms * 1024 < xr_fb) ? wms * 1024 : xr_fb;   // v41: 4th field = KiB written per frame
        xr_chunk = (fl & 0x800) ? 0x200000 : 0x20000;                // v41: bit11 big chunks
        slog("  v41 wlen=%d chunk=%d", xr_wlen, xr_chunk);
        xr_gate = 1;
        CreateTask("M10XR", 0x1C, 0x2000, xr_task);  // v38: BELOW the capture (0x1A): never preempts a PACK32 hold (v182: 8 KiB stack)
        if (sh_on && x_m1 && lj_on && pv_mode != 2) pv_rec_start();   // v182: live preview of encoded frames (prio 0x1E, idle CPU only)
        wait_sleep = (fl & 0x2000) ? 0 : 1;        // v42: bit13 busy sync in REC
        ts_start(buf + x_exsz);   // v153: after worker creation / before first readout
        slog_len = 0; slog_lost = 0; slog_defer = 1;   // v155: no card log I/O from the capture loop
        xr_last_drop_ms = 0;   // v183
        if (lj_on) {   // v186a: Canon refcounted clock holds for the whole compressed take (released after lj/xr drain)
            FW0(FN_LCLK_HOLD0); FW0(FN_CLKSAVE_TAKE); turbo_held = 1;
            slog("v186a turbo=%d", turbo_held, 0);
        }
        if (x_m1 && lj_on) {   // v183: 2 pre-roll captures (not published, encoder not kicked) before t0
            x_early = 0;
            for (i = 0; i < 2 && !(sh_on && sh_stop_req); i++) { unsigned dt0 = 0, ep0 = 0; lvn_cap(buf, phys, lines, &dt0, &ep0); }
            x_early = (lj_new_win == 2);
        }
        t0 = get_tick_count();
        xr_slot_cnt = 0; xr_t0_ms = t0;
        wb_defer = x_m1; wb_due = 0; wb_late_n = 0;   // v180f
        for (k = 0; k < npass; k++) {
            unsigned dt = 0, endp = 0, slot, off;
            int r;
            if (xr_err) { ok = -4; break; }
            cap_k = capl ? k % CAP_N : 0xffffffff;   // v154 (v182: ring)
            if (cap_k < CAP_N) { memset(capl[cap_k], 0, 20); capl[cap_k][4] = fr | 0x80000000u; }
            wb_mon(fr);   // v89i
            if ((fl & 0x2000000) && (kbd_is_key_pressed(KEY_SET) || kbd_is_key_pressed(KEY_SHOOT_HALF))) { slog("  REC stop key", 0, 0); break; }   // v56
            if (sh_on && sh_stop_req) { slog("  v160 REC stop (shell key)", 0, 0); break; }
            if (lj_on && x_kick) lj_collect();   // v127
            if (lj_on && lj_err) { ok = -7; break; }
            if (lj_on ? ((int)(xr_prod - lj_cnt) >= (int)lj_raw_n) : (xr_prod - xr_wr >= xr_nslot)) {      // writer (v101: encoder) behind: drop this sensor frame
                drops++; x_dr[0]++;
                xr_last_drop_ms = get_tick_count(); if (x_m1 && lj_on) xr_slot_cnt++;   // v183
                if (cap_k < CAP_N) { capl[cap_k][0] = usec() | 0x80000000u; capl[cap_k][3] = 0x0f000000u; }   // v154: drop (ring full)
                if (px_on && px_close() < 0) { ok = -1; break; }   // v73: no PACK32 on across an unarmed readout
                if (lvn_sync == 4) { if (!wait_dfe_w(200, 0, x_hi, x_hi)) { ok = -1; break; } }   // v73: wait_eof needs the SIO CMOS bursts
                else if (!wait_eof(200)) { ok = -1; break; }
                if (wb_due) wb_kick_due(fr);   // v182 (A.1): a drop burst never reaches lvn_cap: kick now, during a readout that is not ours
                if (lj_on && x_kick) {   // v137: catch-up. One kick per captured frame: a missed kick (writer slot busy) is never recovered, the backlog stays at the ring size -> drop bursts. We are now at the start of the frame we skip: its readout is not ours, let the encoder run through it.
                    unsigned u0c = usec(); int rc;
                    while ((rc = lj_collect()) == 0 && udiff(u0c, usec()) < 4000) ;   // must start now (~30 ms encode) to end before our next readout
                    if (rc > 0 && !lj_kicked && lj_cnt < x_ready) { unsigned ok0 = lj_k_ok; lj_kick(0); if (lj_k_ok != ok0) x_dr[1]++; }
                }
                continue;
            }
            if (x_skipn && fr && !(fr % x_skipn) && x_skip_fr != fr) {   // v91: one free sensor frame for Canon
                if (px_on && px_close() < 0) { ok = -1; break; }
                if (lvn_sync == 4) { if (!wait_dfe_w(200, 0, x_hi, x_hi)) { ok = -1; break; } }
                else if (!wait_eof(200)) { ok = -1; break; }
                x_skips++; x_skip_fr = fr;
            }
            slot = fr % xr_nslot; off = lj_on ? slot * xr_fb : (xr_mlv ? slot * xr_stride + 512 : slot * xr_fb);
            stg_k = fr < 8 ? fr : 8 + (fr - 8) % 8;
            if (fl & 0x400) {                       // v40: no capture, frame-synced writes only
                stg_k = 0; STG(0);
                r = wait_eof(200) ? 1 : -1;
            } else
            if (lj_on && fr < XR_MAX) { xr_slot[fr] = slot; xr_tick[fr] = get_tick_count() - t0; xr_drop_at[fr] = (unsigned short)(drops < 65535 ? drops : 65535); x_early_fr = fr; memset(TLF_ROW(fr), 0, 32); }   // v121 (v182: TLF ring row)
            lj_chased = 0;   // v144
            r = lvn_cap(buf + off, phys + off, lines, &dt, &endp);
            // v172b: an early kick proves this raw frame completed even if
            // the later restore/wait failed. Classify its HE before advancing fr.
            if (lj_on && x_he_fix && *(volatile unsigned *)(0x0000fa68 + 0x1c) &&
                !(r > 0 && r != 2) && (lj_kicked == fr + 1 || lj_cnt > fr)) r = 1;
            if (lj_on && x_ready > fr && !(r > 0 && r != 2)) { if (lj_kicked == fr + 1 || lj_cnt > fr) { fr++; xr_prod = fr; } else x_ready = fr; }   // v121/v128: published early but the pass failed: if its encode already started, keep the frame (it is complete in DRAM), else take it back
            if ((x_xo & 0x80000000) && x_her && *(volatile unsigned *)(0x0000fa68 + 0x1c) && r > 0 && r != 2) {   // v148: no-pause recovery (v172: x_he_fix replaces torn frame)
                unsigned hst = *(volatile unsigned *)(0x0000fa68 + 0x1c) & 0xff;
                if (x_he_n < HE_ALL_N) x_he_all[x_he_n] = (fr << 8) | hst;
                if (x_he_n < 32) x_he_at[x_he_n] = (fr << 8) | hst;
                else { unsigned q; for (q = 0; q < 31; q++) x_he_at[q] = x_he_at[q + 1]; x_he_at[31] = (fr << 8) | hst; }
                x_he_n++;
                *(volatile unsigned *)(0x0000fa68 + 0x1c) = 0;   // acknowledge, re-arm the cause masks (same as v89c)
                eng_out(0xc0f072c8, 0x20); eng_out(0xc0f072cc, 0x20); eng_out(0xc0f072d0, 0x40); eng_out(0xc0f072d4, 0x40);
                if (x_he_n <= 8) slog("v148 he kept fr=%d n=%d", fr, x_he_n);
                if (lj_on && x_he_fix && x_kick) {
                    if (lj_cnt > fr || (fr == 0 && lj_kicked)) {
                        // Already published, or first frame already in JpCore:
                        // no safe predecessor. Stop explicitly, never copy over DMA.
                        lj_err = 6; ok = -7; break;
                    }
                    if (fr == 0) { drops++; continue; }
                    if (lj_dup_h - lj_dup_t >= LJ_DUP_N) { lj_err = 6; ok = -7; break; }
                    lj_dup_q[lj_dup_h % LJ_DUP_N] = fr;
                    lj_dup_h++;
                    x_ready = fr + 1;
                    x_he_fixed++;
                    GiveSemaphore(lj_sem);
                }
                if (x_he_n >= x_hbn && fr - (x_he_at[(x_he_n < 32 ? x_he_n : 32) - x_hbn] >> 8) < 64) {
                    slog("v148 he burst, stop REC fr=%d", fr, 0);
                    if (lj_on && x_he_fix && x_kick) { fr++; xr_prod = fr; }
                    ok = -6; break;
                }
                // fall through: normal frame path below (fr++, encoder / writer)
            } else
            if ((x_xo & 0x80000000) && *(volatile unsigned *)(0x0000fa68 + 0x1c)) {   // v87: trapped head error in REC: drop, recover, re-arm
                if (x_her) x_he_late++;   // v148: the error pass itself failed: old recovery
                if (x_he_n < HE_ALL_N) x_he_all[x_he_n] = (fr << 8) | 0x80 | (*(volatile unsigned *)(0x0000fa68 + 0x1c) & 0x7f);   // v148: bit 7 = frame dropped
                if (x_he_n < 32) x_he_at[x_he_n] = (fr << 8) | (*(volatile unsigned *)(0x0000fa68 + 0x1c) & 0xff);
                if (x_he_n >= 32) { unsigned q; for (q = 0; q < 31; q++) x_he_at[q] = x_he_at[q + 1]; x_he_at[31] = (fr << 8) | 0x40; }   // v143: keep the last 32 for the burst check on long takes
                x_he_n++; drops++;
                if (px_on) px_close();
                if (x_diag && x_he_n == 1) hs_take(1);   // v88 (v167: diag only)
                if (x_he_n <= 8) slog("v89e REC he fr=%d n=%d", fr, x_he_n);   // v89e: survives a shutdown
                if (x_he_n == 1) { wr_force = 1; wr_init(); }   // v89o: ImgSens/TG words from the 1st error on (TG freeze study)
                if (x_he_n >= x_hbn && fr - (x_he_at[(x_he_n < 32 ? x_he_n : 32) - x_hbn] >> 8) < 64) {   // v143: burst threshold x_hbn (48th field, default 6)   // v89h: 3 errors in < 64 frames -> stop before WBInteg 3491 (r100p/q); v89l: 6 (WB kick v89j/k feeds WBInteg)
                    *(volatile unsigned *)(0x0000fa68 + 0x1c) = 0;
                    eng_out(0xc0f072c8, 0x20); eng_out(0xc0f072cc, 0x20); eng_out(0xc0f072d0, 0x40); eng_out(0xc0f072d4, 0x40);
                    slog("v89h he burst, stop REC fr=%d", fr, 0); ok = -6; break;
                }
                *(volatile unsigned *)(0x0000fa68 + 0x1c) = 0;   // v89c: clear + re-arm first
                eng_out(0xc0f072c8, 0x20); eng_out(0xc0f072cc, 0x20); eng_out(0xc0f072d0, 0x40); eng_out(0xc0f072d4, 0x40);
                if (x_he_mode >= 1000 && x_r450a0 != 0xffffffff) {   // v89f: he_mode + 1000 = put c0f450a0 back to its pre-error value
                    unsigned now = shamem(0xc0f450a0);
                    if (now != x_r450a0) { eng_out(0xc0f450a0, x_r450a0); x_r450_fix++; }
                    if (x_he_n <= 8) slog("  v89f 450a0 %x -> %x", now, x_r450a0);
                }
                if (x_he_mode % 1000 >= 100) msleep(x_he_mode % 1000);
                else {                                   // v89c/g: he_mode 1..99 = wait for N CONSECUTIVE sensor frames (8830 bursts)
                    unsigned okn = 0, t1 = get_tick_count(), nf = (x_he_mode % 1000) ? x_he_mode % 1000 : 2;
                    while (okn < nf && get_tick_count() - t1 < 1000) {   // v89m: 1 s (r100z_0: frozen TG, host must re-commit fast)
                        if (wait_dfe_w(200, 0, x_hi, 40000)) okn++;
                        else { okn = 0; x_he_frz++; }    // v89g: chain frozen (r100m: no 8830 for ~760 ms): stay out of PACK32
                        wb_mon(fr);   // v89i
                        wr_poll();   // v89o
                    }
                    if (x_he_n <= 8) slog("  v89g resume after %d ms frz=%d", get_tick_count() - t1, x_he_frz);
                    if (okn < nf) { slog("v89g chain frozen 1 s, stop REC", 0, 0); ok = -5; break; }
                }
                continue;
            }
            if ((x_xo & 0x80000000) && r > 0 && r != 2) {   // v88: diag snapshots + pre-error 450a0 tracking
                if (!x_he_n) {
                    if (x_diag) { if (!(fr & 7)) hs_take(0); if (fr == 4) ea_take(0); }   // v167: no 120 ms stall in REC unless x_diag set
                    x_r450a0 = shamem(0xc0f450a0);
                }
                else if (x_diag && hs_n == 2 && ++hs_after == 2) { hs_take(2); ea_take(2); }
            }
            if (r == 2) { drops++; x_dr[2]++; continue; }      // v58: PACK32 busy, frame skipped
            if (r <= 0 && x_her && x_he_n && fr - (x_he_at[(x_he_n < 32 ? x_he_n : 32) - 1] >> 8) <= 2 && x_he_late < 16) {   // v148: a pass failed right after a kept error (chain hiccup): old wait for 2 clean sensor frames instead of stopping
                unsigned okn = 0, t1 = get_tick_count();
                if (px_on) px_close();
                x_he_late++; drops++;
                while (okn < 2 && get_tick_count() - t1 < 1000) { if (wait_dfe_w(200, 0, x_hi, 40000)) okn++; else { okn = 0; x_he_frz++; } wb_mon(fr); }
                slog("v148 late fail r=%d fr=%d", (unsigned)r, fr);
                if (okn < 2) { slog("v148 chain frozen 1 s, stop REC", 0, 0); ok = -5; break; }
                continue;
            }
            if (r <= 0) {                           // v38: snapshot for the post-mortem
                unsigned sb = sio_base(), hd[8] = { 0x53583331, fr, tl_n, 0, 0, 0, 0, 0 };
                px_close();                         // v73 (no-op if lvn_cap already released)
                char *rb = buf + x_exsz - 0x00080000;
                if (sb) {
                    unsigned nent = *(volatile unsigned *)(sb + 0x210) + 1;
                    if (nent > 0x1e00) nent = 0x1e00;
                    hd[3] = *(volatile unsigned *)(sb + 0x204); hd[4] = nent; hd[5] = sb;
                    memcpy(rb, (void *)(sb + sio_ring), nent * 64);
                }
                hd[6] = xr_wr; hd[7] = xr_prod;
                xr_stop = 1; GiveSemaphore(xr_sem);
                { unsigned t = get_tick_count(); while (!xr_done && get_tick_count() - t < 5000) msleep(20); }
                fd = open("A/LVX3S.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
                if (fd >= 0) { write(fd, hd, sizeof(hd)); write(fd, tl, sizeof(tl)); if (sb) write(fd, rb, hd[4] * 64); write(fd, stg, sizeof(stg)); write(fd, x_pm, sizeof(x_pm)); write(fd, x_df, sizeof(x_df)); write(fd, x_pr, sizeof(x_pr)); write(fd, &wr_n, 4); write(fd, wr_log, sizeof(wr_log)); close(fd); }
                ok = r; break;
            }
            if (!lj_on && fr < XR_MAX) { xr_slot[fr] = slot; xr_tick[fr] = get_tick_count() - t0; }   // v167: in lj_on mode L3780 pre-capture timestamp stands
            if (xr_mlv && !lj_on) mlv_frame_hdr((unsigned char *)buf + slot * xr_stride, fr, xr_fb, (get_tick_count() - t0) * 1000);
            if (fr < 16) lm2.dt[fr] = dt;
            fr++; xr_slot_cnt++;   // v183
            xr_prod = fr;
            if (xr_prod - xr_wr > maxbl) maxbl = xr_prod - xr_wr;
            GiveSemaphore(xr_sem);
            if (lj_on) GiveSemaphore(lj_sem);
        }
        if (px_on && px_close() < 0 && ok > 0) ok = -1;   // v73: end / stop key / error: full release
        wb_defer = 0; if (wb_due) wb_kick_due(k);   // v180f: never leave a kick pending
        pv_rec_stop();   // v182: live preview task off before any EXMEM teardown
        // v182 (A.3): the log stays deferred through the whole report (one card write at the end, below)
        slog("  v180f wb kicks in readout=%d hi=%d", wb_late_n, x_hi);
        cap_n = k < CAP_N ? k : CAP_N; cap_k = 0xffffffff;   // v154
        if (!ts_stop()) { ok = -8; slog("v153 task drain timeout; EXMEM/module pinned", 0, 0); }
        if (lj_on && x_kick && !lj_err && !xr_err) lj_drain();   // v167: encode & enqueue any remaining tail frames before xr_stop
        xr_stop = 1; GiveSemaphore(xr_sem);
        if (lj_on && x_kick) { unsigned t = get_tick_count(); while (lj_kicked && !cb_done && get_tick_count() - t < 3000) msleep(5); lj_collect(); }   // v127: fallback if lj_drain skipped on err
        if (lj_on) { GiveSemaphore(lj_sem); { unsigned t = get_tick_count(); while (!lj_done && get_tick_count() - t < 20000) { GiveSemaphore(lj_sem); msleep(20); } } }
        { unsigned t = get_tick_count(); while (!xr_done && get_tick_count() - t < 20000) { GiveSemaphore(xr_sem); msleep(20); } }
        if (turbo_held) { FW0(FN_CLKSAVE_REL); FW0(FN_LCLK_REL0); turbo_held = 0; slog("v186a turbo released", 0, 0); }   // v186a: every exit path (incl. drain timeout)
        if (!xr_done || (lj_on && (!lj_done || lj_kicked))) {
            // A timed-out task/encoder may still touch EXMEM. Keep all state,
            // semaphores and module resident; only a power cycle can recover.
            ts_pinned = 1;
            slog("v172b drain timeout: EXMEM/module pinned", 0, 0);
            slog_flush();   // v182
            strcpy(msg, "Drain bloque: redemarrer boitier");
            return;
        }
        lm2.ndone = xr_wr;
        if (xr_mlv && x_m1 && lj_on && fr > 1 && fr <= XR_MAX) {   // v183: 24.00p slot grid (drops count as slots)
            unsigned span_ms = xr_tick[fr - 1] - xr_tick[0];
            unsigned slots = (fr - 1) + ((unsigned)xr_drop_at[fr - 1] - (unsigned)xr_drop_at[0]);
            unsigned per_us = (slots >= 10 && span_ms > 0) ? span_ms * 1000u / slots : 0;   // <= ~1.3e8: 32-bit safe
            if (per_us >= 41200 && per_us <= 42100) mlv_fps1000 = 1000000000u / per_us;
            else mlv_fps1000 = 1000000000u / (x_per ? x_per : 41666u);
        } else
        if (xr_mlv && fr > 1 && fr <= XR_MAX && xr_tick[fr - 1] > xr_tick[0])   // v89r: real cadence (frame timestamps), e.g. 12.4 fps
            mlv_fps1000 = (fr - 1) * 1000000u / (xr_tick[fr - 1] - xr_tick[0]);
        if (xr_mlv) mlv_finalize(mlv_crop ? enc_w : x_w, mlv_crop ? enc_h : lines, lj_on ? 14 : lvn_bpp, lj_on);
        else { lseek(xr_fd, 0, SEEK_SET); write(xr_fd, &lm2, sizeof(lm2)); close(xr_fd); }
        fd = open("A/M10X3T.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
        if (fd >= 0) { write(fd, &fr, 4); write(fd, xr_tick, fr * 4); write(fd, xr_wus, fr * 4); close(fd); }
        if (!ts_pinned) ts_save();   // v153: no callback outstanding before SD export
        fd = open("A/M10CAP.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);   // v154: per-pass record (CAP1)
        if (fd >= 0) {   // v182: ring -> chronological order (the last CAP_N passes); hd[3] = 182 when it wrapped
            unsigned hd[4] = { 0x31504143, capl ? cap_n : 0, 5, k > CAP_N ? 182 : 154 }, c0 = k > CAP_N ? k % CAP_N : 0;
            write(fd, hd, 16);
            if (capl && cap_n) { write(fd, capl + c0, (cap_n - c0) * 20); if (c0) write(fd, capl, c0 * 20); }
            close(fd);
        }
        fd = open("A/M10TLF.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);   // v140: per-frame timeline
        if (fd >= 0) {   // v182: TLF1 (rows = frames 0..n-1) or, once the ring wrapped, TLF2 = same layout + trailing u32 first frame
            unsigned n = fr < TLF_N ? fr : TLF_N, f0 = fr > TLF_N ? fr - TLF_N : 0, r0 = f0 % TLF_N;
            unsigned hd[4] = { f0 ? 0x32464c54 : 0x31464c54, n, 8, x_he_n };
            write(fd, hd, 16); write(fd, x_he_at, sizeof(x_he_at));
            write(fd, tlf[r0], (n - r0) * 32); if (r0) write(fd, tlf, r0 * 32);
            if (f0) write(fd, &f0, 4);
            close(fd);
        }
        if (x_he_n) {                               // v148: every error, (frame << 8) | status, bit 7 = dropped
            fd = open("A/M10HE.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
            if (fd >= 0) { unsigned hd[4] = { 0x31454856, x_he_n < HE_ALL_N ? x_he_n : HE_ALL_N, x_her, x_he_late }; write(fd, hd, 16); write(fd, x_he_all, (x_he_n < HE_ALL_N ? x_he_n : HE_ALL_N) * 4); close(fd); }
        }
        if (hs_n) {                                 // v88
            fd = open("A/M10HESH.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
            if (fd >= 0) { unsigned hd[4] = { 0x48534833, hs_n, HS_WORDS, ea_n }; write(fd, hd, 16); write(fd, hs_buf, hs_n * HS_WORDS * 4); write(fd, ea_buf, sizeof(ea_buf)); close(fd); }   // v89b: HSH3 + ea_buf[3][24][4] (ea_base order)
        }
        slog("v37 REC frames=%d drops=%d", fr, drops);
        if (lj_on) {
            unsigned i, smax = 0, umax = 0, ssum = 0, usum = 0, n = lj_cnt < LJ_N ? lj_cnt : LJ_N;
            for (i = 0; i < n; i++) { ssum += lj_sz[i] >> 10; usum += lj_us[i]; if (lj_sz[i] > smax) smax = lj_sz[i]; if (lj_us[i] > umax) umax = lj_us[i]; }
            slog("v101 LJ encoded=%d err=%d", lj_cnt, lj_err);
            slog("  v125 kicks ok=%d busy=%d", lj_k_ok, lj_k_no[0]);
            slog("  v125 notnext=%d slot=%d", lj_k_no[1], lj_k_no[2]);
            slog("  v125 chbusy=%d kick max us=%d", lj_k_no[3], lj_k_max);
            slog("  v126 drop ring=%d pk=%d", x_dr[0], x_dr[2]); slog("  v137 catchup=%d", x_dr[1], 0); slog("  v144 chase n=%d miss=%d", lj_chase_n, lj_chase_miss);
            slog("  v101 size avg KiB=%d max=%d", n ? ssum / n : 0, smax);
            slog("  v101 enc us avg=%d max=%d", n ? usum / n : 0, umax);
            if (lj_err) slog("  v101 cb st=%x size=%d", cb_st, cb_size);
            for (i = 0; i < n && i < 24; i += 2) slog("  v105 ph %d %d", lj_ph[i], i + 1 < n ? lj_ph[i + 1] : 0);
            slog("  v181 async kicks=%d raw=%d", lj_async_n, lj_raw_n);
            { unsigned i; for (i = 0; i < 9; i += 3) { slog("  v181b rd1 +%02x %08x", 4 * i, enc_rdg[i]); slog("    %08x %08x", enc_rdg[i + 1], enc_rdg[i + 2]); } }
            if (lvn_bpp == 12) eng_out(LL_UNPACK_REG, 0);   // v182: LL unpacker back to 10-bit (0) after a 12b take
            enc_rd10 = 0; enc_rd12 = 0; enc_no_snap = 0; enc_in_off = VID_IN_OFF; lj_on = 0; x_early = 0; lj_sem_p = 0; x_kick = 0; x_poll = 0;
            if (lj_done) DeleteSemaphore(lj_sem);
        }
        slog("  v88 hs_n=%d", hs_n, 0);
        slog("  v89f 450a0 fixes=%d last=%x", x_r450_fix, shamem(0xc0f450a0));
        slog("  v89g frozen waits=%d", x_he_frz, 0);
        slog("  v89i wb max 50=%d 54=%d", wb_max[0], wb_max[1]);
        slog("  v89i wb max 58=%d 5c=%d", wb_max[2], wb_max[3]);
        slog("  v89j wb kicks=%d", wb_kick_n, 0);
        slog("  v89q tg fixes=%d", tg_fix_n, 0);
        slog("  v87 he_n=%d", x_he_n, 0);
        slog("  v148 her=%d late=%d", x_her, x_he_late);
        slog("  v172 he fix=%d fixed=%d", x_he_fix, x_he_fixed);
        if (x_he_fixed) slog("  v172 dup us max=%d", x_dup_us_max, 0);
        slog("  v151 skick=%d n=%d", x_skick, x_skick_n);
        slog("  v91 skipn=%d skips=%d", x_skipn, x_skips);
        for (i = 0; i < x_he_n && i < 32; i++) slog("   he at frame %d st=%x", x_he_at[i] >> 8, x_he_at[i] & 0xff);
        slog("  v42 sync skips=%d", sync_skips, 0);
        slog("  written=%d err=%d", xr_wr, xr_err);
        slog("  ms=%d maxbacklog=%d", fr ? xr_tick[fr - 1] : 0, maxbl);
        slog("  ok=%d nslot=%d", ok, xr_nslot);
        slog("  files=%d err=%d", xr_fileno + 1, xr_err);
        slog("  pk_late=%d", pk_late, 0);
        slog("  v61 chained=%d short=%d", x_chained, x_short);
        slog("  v61 short_min=%d", x_short_min / lvn_lb, 0);
        slog("  v62 dfe_miss=%d", x_dfe_miss, 0);
        slog("  v69 aborted=%d", x_abort, 0);
        slog("  v72 waits=%d busymax=%d", x_waits, x_busy_max);
        slog("  v72 busytot=%d lateavg=%d", x_busy_tot, x_waits ? x_late_acc / x_waits : 0);
        slog("  v73 px opens=%d frames=%d", px_opens, px_frames);
        slog("  v73 late=%d rearm_err=%d", px_late, px_rearm_err);
        slog("  v73 pulses=%d short_bad=%d", px_pulses, x_short_bad);
        slog("  v182 roll n=%d max ms=%d", xr_roll_n, xr_roll_ms);
        slog("  v182 roll fr=%d drops_at_roll=%d", xr_roll_fr, xr_roll_drops);
        slog("  v182 wb watchdog kicks=%d", wb_wd_kicks, 0);
        slog("  v183 slots=%d t0=%d", xr_slot_cnt, xr_t0_ms);
        slog("  v183 fps1000=%d drops=%d", mlv_fps1000, drops);
        slog_flush();   // v182 (A.3): single card write of the capture + report lines
        if (xr_done) DeleteSemaphore(xr_sem);
        if (!ts_pinned) { ts_buf = 0; ts_names = 0; capl = 0; cap_k = 0xffffffff; exmem_free_uncached(EXMEM_TYPE); }
        if (ts_pinned) strcpy(msg, "TSK pinned: do not reload");
        else sprintf(msg, "REC %d img %d perdues %s", fr, drops, ok > 0 ? "ok" : "arret");
        lvn_bpp = 14; lvn_lb = LVN_LB;
        idle_polls = 20; lvn_post_ms = 0; tl_step = 1000; lvm_sleep = 1; lvn_sync = 0; wait_sleep = 0;
        if (wr_force) {   // v89o: ImgSens/TG change log since the 1st REC error
            int fd2 = open("A/LVX3H.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
            if (fd2 >= 0) { write(fd2, &wr_n, 4); write(fd2, wr_log, sizeof(wr_log)); close(fd2); }
            slog("  v89o wr_n=%d", wr_n, 0);
        }
        if (ok != -5 && !sh_on) for (i = 0; i < 8; i++) {   // v89m: frozen chain -> return at once (host re-commits); v89k: keep the WB watchdog running after REC (r100w_0 died here, 3 s after a burst stop); v182: skipped in the shell
            unsigned j;
            for (j = 0; j < 5; j++) { msleep(50); if (x_he_n || x_m1) wb_mon(fr); }   // v182: m1 too (WBInteg starves without a head error)
            slog("  hb tg=%d 6804=%08x", *(volatile unsigned *)0x0000e664, shamem(0xc0f06804));
        }
        if (x_he_n && ok != -5) { unsigned j; for (j = 0; j < 80; j++) { msleep(50); wb_mon(fr); } slog("  v89k post kicks=%d", wb_kick_n, 0); }   // 4 s more: until WBInteg is fed again
        return;
    }
    for (k = 0; k < npass; k++) {
        unsigned dt = 0, endp = 0, off = ((x_xo & 0x40000) ? (((x_xo >> 20) & 7) % nfit) : (k % ((x_xo & 0x1000000) ? 3 : nfit))) * lines * lvn_lb;   // v75k: fixed slot, v77: 3 slots
        int r;
        kk = k < 8 ? k : 8 + (k - 8) % 8;           // v33: records 0-7 = first passes, 8-15 = ring of the last
        stg_k = kk;
        if (shamem(0xc0f06804) == 0 || *(volatile unsigned *)DSS_FLAGS == 0) { ok = -2; break; }
        r = lvn_cap(buf + off, phys + off, lines, &dt, &endp);
        if (r == 2) r = 1;                          // v58: skipped frame (PACK32 busy), keep going
        STG(11);
        lm2.dt[kk] = dt; lm2.st[kk] = (unsigned)r; lm2.endp[kk] = endp - (phys + off);
        lm2.tick[kk] = get_tick_count();
        lm2.cbr[kk][0] = shamem(0xc0f06804);
        lm2.cbr[kk][1] = *(volatile unsigned *)0x0000e664;
        lm2.cbr[kk][2] = (*(volatile unsigned *)0x00008654 << 16) | (*(volatile unsigned *)0x00008658 & 0xffff);
        lm2.ndone = k + 1;
        if (!(fl & 1) && !x_px) {                   // v32 bit0: no card I/O during the run (v73: never with px)
            slog("LVX3 pass %d dt=%d", k, dt);
            slog("   st=%d tg=%d", r, lm2.cbr[kk][1]);
        }
        if (r <= 0) {                               // v30: snapshot the SIO ring NOW
            unsigned sb = sio_base();
            px_close();                             // v73 (no-op if lvn_cap already released)
            char *rb = buf + x_exsz - 0x00080000;
            unsigned hd[8] = { 0x53583331, k, tl_n, 0, 0, 0, 0, 0 };   // "1X3S"
            if (sb) {
                unsigned nent = *(volatile unsigned *)(sb + 0x210) + 1;
                if (nent > 0x1e00) nent = 0x1e00;    // <= 480 KiB
                hd[3] = *(volatile unsigned *)(sb + 0x204); hd[4] = nent; hd[5] = sb;
                memcpy(rb, (void *)(sb + sio_ring), nent * 64);
            }
            fd = open("A/LVX3S.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
            if (fd >= 0) {
                write(fd, hd, sizeof(hd));
                write(fd, tl, sizeof(tl));
                if (sb) write(fd, rb, hd[4] * 64);
                write(fd, stg, sizeof(stg));       // v31
                write(fd, x_pm, sizeof(x_pm));     // v66
                write(fd, x_df, sizeof(x_df)); write(fd, x_pr, sizeof(x_pr)); write(fd, &wr_n, 4); write(fd, wr_log, sizeof(wr_log));     // v71
                close(fd);
            }
            ok = r; break;
        }
        if ((x_xo & 0x80000000) && k && !(k % 50)) { if (px_on) px_close(); slog("v86 progress pass=%d he_n=%d", k, x_he_n); }   // v86b
        if ((x_xo & 0x80000000) && k < 512) x_hst[k] = (unsigned char)REG(0xc0f070dc);   // v85c (module-side direct read, like Head.c)
        if ((x_xo & 0x80000000) && x_he_mode && *(volatile unsigned *)(0x0000fa68 + 0x1c)) {   // v85: count, clear, keep going
            if (x_he_n < 32) x_he_at[x_he_n] = (k << 8) | (*(volatile unsigned *)(0x0000fa68 + 0x1c) & 0xff);
            x_he_n++;
            if (x_he_mode >= 100) {        // v85d: recovery pause, then re-arm and keep going
                if (px_on) px_close();
                slog("v86 he pass=%d n=%d", k, x_he_n);   // v86b: survives a later shutdown
                msleep(x_he_mode);
                *(volatile unsigned *)(0x0000fa68 + 0x1c) = 0;
                eng_out(0xc0f072c8, 0x20); eng_out(0xc0f072cc, 0x20); eng_out(0xc0f072d0, 0x40); eng_out(0xc0f072d4, 0x40);
            } else
            if (x_he_n < x_he_mode) {
                *(volatile unsigned *)(0x0000fa68 + 0x1c) = 0;   // v85b: stop (watch below) at the N-th error
                // v85c: the Head.c handler cleared the cause masks (0xfc17c1ac): re-arm them as Extract does
                eng_out(0xc0f072c8, 0x20); eng_out(0xc0f072cc, 0x20); eng_out(0xc0f072d0, 0x40); eng_out(0xc0f072d4, 0x40);
            }
        }
        if ((x_xo & 0x80000000) && *(volatile unsigned *)(0x0000fa68 + 0x1c)) {   // v84: head error trapped (m10hetrap): stop, watch recovery
            unsigned q, sb = sio_base(), sp = *(volatile unsigned *)0x0000fa80;
            x_he_pass = k + 1; x_he_val = *(volatile unsigned *)(0x0000fa68 + 0x1c);
            if (px_on) px_close();
            slog("v84 HEAD ERR trapped pass=%d he=%x", x_he_pass, x_he_val); slog("  v85 he_n=%d", x_he_n, 0); { unsigned j, kk3 = (k + 1 < 512) ? k + 1 : 512; char h[80]; for (j = 0; j < kk3; j += 24) { unsigned m, o = 0; for (m = j; m < j + 24 && m < kk3; m++) o += sprintf(h + o, "%02x", x_hst[m]); h[o] = 0; slog("  hst %d %s", j, (unsigned)h); } }
            for (q = 0; q < 40; q++) {           // does the chain keep running after a trapped head error?
                unsigned n = (sp != 0xfc1ee9a9) ? *(volatile unsigned *)((sp & ~1u) - 0x10) : 0xffff;
                slog("  he hb tg=%d sio=%d", *(volatile unsigned *)0x0000e664, sb ? *(volatile unsigned *)(sb + 0x204) : 0);
                slog("     ch24=%08x ch1=%08x", REG(0xc0f58208), REG(0xc0f04108));
                slog("     ch15=%08x ch16=%08x", REG(0xc0f30108), REG(0xc0f30208));
                slog("     he=%x trap_n=%d", *(volatile unsigned *)(0x0000fa68 + 0x1c), n);
                slog("     live70dc=%08x 72d0=%x", REG(0xc0f070dc), shamem(0xc0f072d0));
                msleep(50); wb_mon(k); msleep(50); wb_mon(k);   // v89t: keep WBInteg fed (r104c died here at H = 1254)
            }
            break;
        }
        if (px_on && ((k == 0 && wms) || gap || k + 1 >= npass)) px_close();   // v73: nothing armed next frame
        if (k == 0 && wms) {                        // v28: watch Canon after the first pass
            unsigned q;
            if (wms > 6000) wms = 6000;
            x3_watch(wms);
            fd = open("A/LVX3W.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
            if (fd >= 0) { write(fd, "M10X3W01", 8); write(fd, &xw_n, 4); write(fd, xw, xw_n * sizeof(xw_rec)); close(fd); }
            for (q = 0; q < xw_n && q < 30; q++) slog("  w %d tg=%d", xw[q].tick, xw[q].tg), slog("     is0=%08x sio=%d", xw[q].is[0], xw[q].sio);
            if (*(volatile unsigned *)0x0000e664 != 3) { ok = -3; break; }
        } else
        if (gap) { unsigned g; for (g = 0; g < gap; g += 50) { msleep(gap - g < 50 ? gap - g : 50); wb_mon(k); } }   // v29: configurable gap (v89t: WB watchdog)
    }
    if (px_on) px_close();                          // v73: DSS / LV lost break, safety net
    if (fl & 2) {                                   // v32 bit1: 3 s watch BEFORE any file write
        unsigned q;
        x3_watch(3000);
        fd = open("A/LVX3W.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
        if (fd >= 0) { write(fd, "M10X3W01", 8); write(fd, &xw_n, 4); write(fd, xw, xw_n * sizeof(xw_rec)); close(fd); }
        for (q = 0; q < xw_n && q < 20; q++) slog("  pw %d tg=%d", xw[q].tick, xw[q].tg);
    }
    slog("  v73 px opens=%d frames=%d", px_opens, px_frames);
    slog("  v73 late=%d rearm_err=%d", px_late, px_rearm_err);
    slog("  v73 pulses=%d short_bad=%d", px_pulses, x_short_bad);
    if ((fl & 1) || x_px) for (k = 0; k < lm2.ndone && k < 16; k++) slog("LVX3 rec %d dt=%d", k, lm2.dt[k]), slog("   st=%d tg=%d", lm2.st[k], lm2.cbr[k][1]);
    slog("  passes done=%d of %d", lm2.ndone, npass);
    slog("  v84 he_pass=%d he=%x", x_he_pass, x_he_val);
    slog("  v85 he_mode=%d he_n=%d", x_he_mode, x_he_n);
    for (i = 0; i < x_he_n && i < 32; i++) slog("   he at pass %d st=%x", x_he_at[i] >> 8, x_he_at[i] & 0xff);
    slog("  v42 sync skips=%d", sync_skips, 0);
    slog("  v61 chained=%d short=%d", x_chained, x_short);
    slog("  v61 short_min=%d pk_late=%d", x_short_min / lvn_lb, pk_late);
    slog("  v62 dfe_miss=%d late=%d", x_dfe_miss, sync_late_us);
    slog("  v69 aborted=%d", x_abort, 0);
    slog("  v72 waits=%d busymax=%d", x_waits, x_busy_max);
    slog("  v72 busytot=%d lateavg=%d", x_busy_tot, x_waits ? x_late_acc / x_waits : 0);
    slog("  ms total=%d", lm2.tick[lm2.ndone <= 8 ? lm2.ndone - 1 : 8 + (lm2.ndone - 9) % 8] - lm2.tick[0], 0);
    if (ok > 0) {                                   // v31: stage trace even without a stall (v33: + SIO ring)
        unsigned sb = sio_base();
        char *rb = buf + x_exsz - 0x00080000;
        unsigned hd[8] = { 0x53583331, 0xffffffff, tl_n, 0, 0, 0, 0, 0 };
        if (sb) {
            unsigned nent = *(volatile unsigned *)(sb + 0x210) + 1;
            if (nent > 0x1e00) nent = 0x1e00;
            hd[3] = *(volatile unsigned *)(sb + 0x204); hd[4] = nent; hd[5] = sb;
            memcpy(rb, (void *)(sb + sio_ring), nent * 64);
        }
        fd = open("A/LVX3S.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
        if (fd >= 0) { write(fd, hd, sizeof(hd)); write(fd, tl, sizeof(tl)); if (sb) write(fd, rb, hd[4] * 64); write(fd, stg, sizeof(stg)); write(fd, x_pm, sizeof(x_pm)); write(fd, x_df, sizeof(x_df)); write(fd, x_pr, sizeof(x_pr)); write(fd, &wr_n, 4); write(fd, wr_log, sizeof(wr_log)); close(fd); }
    }
    if (x_enc && ok > 0 && lm2.ndone >= 1 && (x_enc == lvn_bpp || (x_enc == 11 && lvn_bpp == 10)) && ((enc_wov ? enc_wov : x_w) * lines * lvn_bpp / 8 <= 0x00400000) && !(x_zoom && x_enc == 10)) {   // v92/v170: lossless encoder on pass 0 (supports cropped 14-bit)
        unsigned eus = 0, sz, hdr[8];
        enc_w = enc_wov ? enc_wov : x_w; enc_h = lines; enc_in_off = lj_eoff; enc_bits = lj_ebits ? lj_ebits : ((x_enc == 12) ? 1 : 2);   // v146, v133, v170 lj_eoff
        enc_rd10 = (x_enc == 11); enc_unpk = x_unpk_set ? x_unpk : (x_csh & 3) << 4;   // v95: CSH = unpacker code (0 = 10-bit); v97: 22nd field = raw value
        enc_prec = x_csh >> 4; enc_9c = x_j9c;   // v96: CSH = prec * 16 + unpack code, e.g. 160 = P 10
        if (x_enc == 10) {                          // v93: CPU 10 -> 14 bits into buf + 3 MiB (read uncached, then cached alias)
            unsigned u0 = usec(), t1, t2;
            conv_10_14((const unsigned short *)phys, (unsigned short *)(buf + 0x00300000), x_w * lines);
            t1 = udiff(u0, usec()); u0 = usec();
            conv_10_14f((const unsigned *)phys, (unsigned *)(buf + 0x00300000), x_w * lines, x_csh & 7);
            t2 = udiff(u0, usec());
            slog("v94 conv old=%d us fast=%d us", t1, t2);
            slog("  v94 shift=%d", x_csh, 0);
            enc_in_off = 0x00300000; enc_bits = 2;
        }
        enc_out_off = 0x00800000; enc_out_size = 0x00400000; enc_wr2_off = 0x00c00000; enc_no_snap = 0;
        sem_enc = 0;
        {   // v100: custom Huffman tables
            int hf = open("A/M10HUF.BIN", O_RDONLY, 0777);
            enc_huff_ok = 0;
            if (hf >= 0) { if (read(hf, enc_huff, 96) == 96) enc_huff_ok = 1; close(hf); }
        }
        slog("v92 ENC %d-bit h=%d", x_enc, lines); slog("  v157 enc w=%d zoom=%d", enc_w, x_zoom);
        slog("  v100 huff=%d", enc_huff_ok, 0);
        if (enc_rd10) slog("  v95 rd10 unpk=%x 371fc=%08x", enc_unpk, shamem(LL_UNPACK_REG));
        sz = enc_frame(buf, phys, 0, &eus);
        slog("  v92 enc size=%d us=%d", sz, eus);
        slog("  v92 cb st=%x size=%d", cb_st, cb_size);
        slog("  v111 rd flags=%08x wr flags=%08x", enc_f_rd, enc_f_wr);
        slog("  v92 tg=%d done=%d", *(volatile unsigned *)0x0000e664, cb_done);
        if (enc_rd10) slog("  v95 after 371fc=%08x", shamem(LL_UNPACK_REG), 0);
        if (enc_rd10) slog("  v98 prec=%d jpn=%d", enc_prec, x_jpn);
        { unsigned i; for (i = 0; i < x_jpn; i++) slog("  v99 jp %x=%x", x_jpo[i], x_jpv[i]); }
        hdr[0] = 0x434e4532; hdr[1] = sz; hdr[2] = eus; hdr[3] = cb_st; hdr[4] = cb_size; hdr[5] = x_enc; hdr[6] = lines; hdr[7] = enc_w;
        enc_in_off = VID_IN_OFF; enc_rd10 = 0; enc_rd12 = 0;
        fd = open("A/M10LL.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
        if (fd >= 0) { write(fd, hdr, sizeof(hdr)); if (sz && sz <= enc_out_size) write(fd, buf + enc_out_off, sz); close(fd); }
        enc_bits = 2;
    }
    if (!(fl & 4)) {                                // v32 bit2: skip the big file
        fd = open("A/LVX3.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
        if (fd >= 0) { write(fd, &lm2, sizeof(lm2)); write(fd, buf, lm2.ndone * lines * lvn_lb); close(fd); }
    } else {
        fd = open("A/LVX3.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
        if (fd >= 0) { write(fd, &lm2, sizeof(lm2)); close(fd); }
    }
    exmem_free_uncached(EXMEM_TYPE);
    idle_polls = 20; lvn_post_ms = 0; tl_step = 1000; lvm_sleep = 1; lvn_sync = 0;
    sprintf(msg, "LVX3 %d/%d %s", (int)lm2.ndone, (int)npass, ok > 0 ? "ok" : (ok == 0 ? "STALL" : (ok == -2 ? "LV perdue" : "err")));
    slog("v26 LVX3 done ok=%d", ok, 0);
    slog("  v179 trg done=%d us=%d", x_trg_done, x_trg_us); slog("  v179 trg busy=%d skip=%d", trg_busy, trg_skip);
    lvn_bpp = 14; lvn_lb = LVN_LB;
    for (i = 0; i < 12; i++) {
        unsigned q;
        for (q = 0; q < 25; q++) { msleep(10); if (q % 5 == 4) wb_mon(0); else wr_poll(); }   // v75h: keep watching Canon's state (v89t: WB watchdog)
        slog("  hb tg=%d 6804=%08x", *(volatile unsigned *)0x0000e664, shamem(0xc0f06804));
        slog("  hb headerr=%08x 8694=%x", *(volatile unsigned *)(0x0000fa68 + 0x1c), *(volatile unsigned *)0x00008694);   // v82
        if (i == 0) slog("  v83 heads=%d 72d0=%x", x_heads, shamem(0xc0f072d0));
        if (i == 3) {
            fd = open("A/LVX3H.BIN", O_WRONLY | O_CREAT | O_TRUNC, 0777);
            if (fd >= 0) { write(fd, &wr_n, 4); write(fd, wr_log, sizeof(wr_log)); close(fd); }
        }
    }
    wr_on = 0;
}

// ---- module plumbing (simple tool, runs once from the Tools menu) ----
static volatile int task_running = 0;
static volatile int run_async = 0;   // v181c: A/M10RUN.ASY -> _run returns at once, A/M10X3.END written at the end

static void cine_task(void)
{
    // v15: zoom x5 -> recording (v14 pipeline); normal live view -> LVN probe
    unsigned h = shamem(0xc0f06804);
    int fx = open("A/M10X3.CFG", O_RDONLY, 0777);   // v27: config present -> lv_x3 in any non-zoom LV
    if (fx >= 0) close(fx);
    int fz = open("A/M10Z.CFG", O_RDONLY, 0777);   // v156: marker file -> lv_x3 also in the x5 magnifier
    if (fz >= 0) close(fz);
    if (!sh_on && *(volatile unsigned *)0x865c == 1) wb_wd_start();   // v182 (A.5-1): ImgMode 1 take driven by M10M1.LUA
    if (zoom_head(h) && fz >= 0 && fx >= 0 && *(volatile unsigned *)DSS_FLAGS != 0) lv_x3();   // v168z: tall zoom too
    else if (h != 0 && *(volatile unsigned *)DSS_FLAGS != 0 && h != 0x045702a6 && ((h >> 16) == 0x4a6 || fx >= 0))
        lv_x3();                    // v25: Film / 1x3 (head 1190 lines), v27: any head if A/M10X3.CFG
    else if (h != 0 && *(volatile unsigned *)DSS_FLAGS != 0 && h != 0x045702a6)
        lv_multi2();                // v24 (v23: lv_watch, v18-22: lv_multi2)
    else
        grab();
    if (run_async) {   // v181c: stand-alone Lua (kbd task free during the take): end marker for the script
        int fe = open("A/M10X3.END", O_WRONLY | O_CREAT | O_TRUNC, 0777);
        if (fe >= 0) { write(fe, msg, strlen(msg)); close(fe); }
        run_async = 0;
    }
    wb_wd_end();   // v182: the Lua kicks again once it has seen A/M10X3.END
    task_running = 0;
    ExitTask();
}

// ---------------------------------------------------------------------------
// v160: stand-alone shell (no host). Runs when A/M10SH.CFG exists (created by
// the autostart script): installs what the host tools used to install, waits
// for the x5 magnifier (touch), records on the REC key (SET as fallback), one
// numbered take per press. Everything is RAM only and lost at power-off.
// ---------------------------------------------------------------------------
#include "m10_blobs.h"
#define SH_PTR      0x9b50          // SIO hook pointer (m10sio.PTR), Canon value 0x121
#define SH_ORIG     0x121
#define SH_CBR      0xfa80          // head-error callback [0xfa68 + 0x18]
#define SH_CANONCBR 0xfc1ee9a9
#define SH_TGTAB    0x2cdc0         // TgPixelRes pointer table
#define SH_REC46    0xfc73045c
#define SH_FLD46    0xfc7308e8
#define SH_CACHE41  (0x575b0 + 36 * 41)
#define FN_IINVAL   0xfc126871
#define SH_NENT     4096
#define SH_PHYSW2   (0x00056bec + 8)  // physw_status[2] (stubs_entry 110d)
#define SH_USBMASK  0x10000000       // USB power (platform_kbd.h USB_MASK)
static int sh_usb_ok = 0;   // v182: A/M10USB.OK present -> desk test with USB plugged in
static int sh_usb(void) { return !sh_usb_ok && (*(volatile unsigned *)SH_PHYSW2 & SH_USBMASK) != 0; }
static char *sh_hook = 0, *sh_stub = 0, *sh_rec = 0;
static unsigned sh_take = 0, sh_key = KEY_VIDEO, sh_frames = 0;
static char sh_line[64], sh_l1[48], sh_l2[64];
static volatile unsigned sh_dirty = 1, sh_quit = 0;
static unsigned sh_t_redraw = 0;
static void sh_say(const char *s1, const char *s2)   // v174: transient message (centre toast), drawn by sh_hud
{
    strncpy(sh_l1, s1, sizeof(sh_l1) - 1); sh_l1[sizeof(sh_l1) - 1] = 0;
    strncpy(sh_l2, s2 ? s2 : "", sizeof(sh_l2) - 1); sh_l2[sizeof(sh_l2) - 1] = 0;
    sh_dirty = 1;
}
// ---------------------------------------------------------------------------
// v174: manual exposure in the shell. Canon's own Tv/ISO controls are hidden (our gui
// handler eats the keys) and, in the x5 magnifier, Canon's dial events drop the magnifier
// (live r133). So exposure is forced at the sensor through the SIO hook override tables,
// exactly as m10sio.py does (validated in x5 at 20:15: CMOS 0 = analog gain, TG 805f/8061
// = end-of-exposure line, Gray coded; magnifier kept, image follows linearly).
//   ISO : CMOS reg 0  100 0x03, 200 0x27, 400 0x4b, 800 0x6f, 1600 0x93, 3200 0xb7 (live109)
//   Tv  : exposure = (frame lines - end line) * line time. 24p loupe: frame 1819 lines,
//         41666 us -> 22.9 us/line. AUTO = Canon AE (no override).
// Hook v6 layout: header at +0x200 (+20 = cmos enable), cmos table +0x240 (16 x (0x10000|v)),
// TG table +0x300 (64 x (reg<<16|val)), match +0x400, header +28 = TG enable, +40/+44 counters.
// ---------------------------------------------------------------------------
static const unsigned short sh_iso_v[] = { 0, 100, 200, 400, 800, 1600, 3200 };
static const unsigned char  sh_iso_c[] = { 0, 0x03, 0x27, 0x4b, 0x6f, 0x93, 0xb7 };
#define SH_NISO (sizeof(sh_iso_v) / sizeof(sh_iso_v[0]))
static const unsigned short sh_tv_d[] = { 0, 30, 48, 50, 60, 100, 125, 200, 250, 500, 1000 };   // 1/x s; 0 = AUTO
#define SH_NTV (sizeof(sh_tv_d) / sizeof(sh_tv_d[0]))
static volatile unsigned sh_iso_i = 0, sh_tv_i = 0;          // 0 = AUTO (Canon)
static volatile int sh_av96 = 0;                              // v176: 0 = AUTO (Canon), else av96 (F = 2^(av96/192))
extern short shooting_get_min_av96(void);
extern short shooting_get_max_av96(void);
extern void shooting_set_av96_direct(short av96, short is_now);
extern int shooting_get_aperture_from_av96(short av96);
extern void exit_alt(void);
#define FN_MOVEIRIS 0xfc43f6b9                               // MoveIrisWithAv(short *) 110d
static void sh_av_apply(void)
{
    short v;
    if (!sh_av96) return;
    v = (short)sh_av96;
    shooting_set_av96_direct(v, 1);
    ((fn1)FN_MOVEIRIS)((unsigned)&v);
    slog("v176 av96=%d", sh_av96, 0);
}
static void sh_fmt_av(char *s)
{
    if (!sh_av96) { strcpy(s, "F AUTO"); return; }
    { int a = shooting_get_aperture_from_av96((short)sh_av96); a = (a + 50) / 100; sprintf(s, "F%d.%d", a / 10, a % 10); }
}
static void sh_poke(unsigned a, unsigned v);
extern unsigned long get_batt_perc(void);
static unsigned sh_gray(unsigned b) { return b ^ (b >> 1); }
static void sh_hook_w(unsigned off, unsigned v) { if (sh_hook) sh_poke((unsigned)sh_hook + off, v); }
static int sh_x3_ok_now(void);
#define SH_M1_ISO_DEF 4      // v182: ImgMode 1 has no Canon AE path: ISO 800 (CMOS 0 = 0x6f) when the field says AUTO
#define SH_M1_TV_DEF  2      // v182: 1/48 (180 degrees at 24p)
#define SH_M1_LCLK    732
static unsigned sh_m1_iso(void) { return sh_iso_i ? sh_iso_i : SH_M1_ISO_DEF; }
static unsigned sh_m1_tv(void) { return sh_tv_i ? sh_tv_i : SH_M1_TV_DEF; }
static void sh_expo_apply(void)
{
    unsigned i, tv = sh_tv_i;
    if (!sh_hook || *(volatile unsigned *)((unsigned)sh_hook + 0x200) != 0x364f4953) return;   // v6 only
    if (sh_prof()->kind == SH_M1) {   // v182 (C.2): ImgMode 1 overrides = M10M1.LUA switch_m1 (CMOS 0/5/7, TG 8006/805f/8061)
        if (sh_prof()->m1_wide) {   // v185: wide ImgMode 1 window (CMOS 2 / 5 / 7)
            sh_hook_w(0x240 + 4 * 2, 0x10000 | 0x742);
            sh_hook_w(0x240 + 4 * 5, 0x10000 | 0x020);
            sh_hook_w(0x240 + 4 * 7, 0x10000 | (sh_prof()->c7 ? sh_prof()->c7 : 0xac6u));   // v186b: per-profile CMOS[7]
        } else {
            sh_hook_w(0x240 + 4 * 2, 0);
            sh_hook_w(0x240 + 4 * 5, 0x10000 | 0x300);
            sh_hook_w(0x240 + 4 * 7, 0x10000 | (sh_prof()->c7 ? sh_prof()->c7 : 0xae9u));   // v186b: per-profile CMOS[7]
        }
        sh_hook_w(0x240, 0x10000 | sh_iso_c[sh_m1_iso()]);
        sh_hook_w(0x200 + 20, 1);
        tv = sh_m1_tv();
    } else {
    // ISO: CMOS reg 0
    if (sh_iso_i) { sh_hook_w(0x240, 0x10000 | sh_iso_c[sh_iso_i]); sh_hook_w(0x200 + 20, 1); }
    else { sh_hook_w(0x240, 0); sh_hook_w(0x200 + 20, sh_prof()->kind == SH_X3 && sh_x3_ok_now() ? 1 : 0); }   // v178: CMOS 7 override stays on in 1x3
    sh_hook_w(0x240 + 4 * 2, 0);                                                              // v185: CMOS 2 (wide ImgMode 1) never outside it
    sh_hook_w(0x240 + 4 * 5, 0);                                                              // v182: ImgMode 1 CMOS 5 never outside it
    if (!(sh_prof()->kind == SH_X3 && sh_x3_ok_now())) sh_hook_w(0x240 + 4 * 7, 0);           // v182: CMOS 7 only for 1x3 (0x140) / ImgMode 1 (0xae9)
    if ((*(volatile unsigned *)((unsigned)sh_hook + 0x308) >> 16) == 0x8006) { sh_hook_w(0x308, 0); sh_hook_w(0x408, 0); }   // v182: stale ImgMode 1 line clock
    }
    // Tv: TG 805f / 8061 end line (entries 0 and 1; v182: entry 2 belongs to 8006 / 800c, never cleared here)
    sh_hook_w(0x200 + 28, 0); sh_hook_w(0x200 + 44, 0);
    for (i = 0; i < 2; i++) { sh_hook_w(0x400 + 4 * i, 0); sh_hook_w(0x300 + 4 * i, 0); }
    if (sh_prof()->kind == SH_M1) { sh_hook_w(0x408, 0); sh_hook_w(0x308, (0x8006u << 16) | sh_gray(sh_m1_lclk())); }   // v182: line clock 732 (0x03b2)
    if (tv) {
        const sh_prof_t *pr = sh_prof();
        unsigned fl = pr->fl, us = 1000000u / sh_tv_d[tv], lines = us * fl / pr->per, end;
        if (lines > fl - 40) lines = fl - 40;          // keep a margin before the next readout
        if (lines < 2) lines = 2;
        end = fl - lines;
        if (end < 17) end = 17;                        // 0x11 = longest pose Canon itself programs in the loupe
        sh_hook_w(0x300, (0x805fu << 16) | sh_gray(end));
        sh_hook_w(0x304, (0x8061u << 16) | sh_gray(end));
        sh_hook_w(0x200 + 40, 0);
        sh_hook_w(0x200 + 28, 1);
    }
}
static void sh_expo_off(void)
{
    unsigned i;
    if (!sh_hook) return;
    sh_hook_w(0x200 + 20, 0); sh_hook_w(0x200 + 28, 0); sh_hook_w(0x200 + 44, 0);
    for (i = 0; i < 16; i++) sh_hook_w(0x240 + 4 * i, 0);
    for (i = 0; i < 4; i++) { sh_hook_w(0x300 + 4 * i, 0); sh_hook_w(0x400 + 4 * i, 0); }
}
// ---------------------------------------------------------------------------
// v174 HUD. One status bar (top), one exposure bar (bottom), nothing else.
//   top    : [o REC 00:12 288]   24p 2K 14b        12 min   [batt]
//   bottom : ISO 800 | 1/50 | ZEB | VUE       (selected field highlighted)
// Pad: UP/DOWN pick the field, LEFT/RIGHT change it. REC/SET = take. MENU+SET = quit.
// Fields: 0 ISO, 1 Tv, 2 aperture, 3 profile, 4 zebras, 5 preview size.
// ---------------------------------------------------------------------------
#define SH_NFIELD 7   // v186b: 0 ISO, 1 Tv, 2 Av, 3 SIZE, 4 BIT, 5 ZEB/PK, 6 VIEW
static volatile unsigned sh_hud_drawn = 0;   // v186b: sh_field moved up (pv_m1_ylim)
static unsigned sh_toast_t = 0, sh_rec_t0 = 0;
// v182 (B.3): in ImgMode 1 every HUD background is OPAQUE black (the 50 % grey let Canon's colour bars through)
static unsigned sh_bg(void) { return sh_is_m1() ? COLOR_BLACK : COLOR_GREY_DK_TRANS; }
#define SH_C_BAR   MAKE_COLOR(sh_bg(), COLOR_WHITE)
#define SH_C_SEL   MAKE_COLOR(COLOR_WHITE, COLOR_BLACK)
#define SH_C_DIM   MAKE_COLOR(sh_bg(), COLOR_GREY_LT)
static void sh_hud_clear(void)
{
    unsigned y;
    if (!pv_ok()) { sh_hud_drawn = 0; return; }
    if (sh_is_m1()) {   // v182: never transparent in ImgMode 1 (bars black, centre = mask)
        pv_fill(0, 20, 0, PV_BW, PV_BLACK); pv_fill(220, 240, 0, PV_BW, PV_BLACK);
        pv_m1_mask(1);
        sh_hud_drawn = 0;
        return;
    }
    for (y = 0; y < 20; y++) memset(PV_RGBA + y * PV_BW, 0, PV_BW * 4);
    for (y = 240 - 20; y < 240; y++) memset(PV_RGBA + y * PV_BW, 0, PV_BW * 4);
    for (y = 100; y < 140; y++) memset(PV_RGBA + y * PV_BW, 0, PV_BW * 4);
    vid_bitmap_refresh();
    sh_hud_drawn = 0;
}
static void sh_fmt_tv(char *s, unsigned i) { if (!i) strcpy(s, "AUTO"); else sprintf(s, "1/%u", sh_tv_d[i]); }
static void sh_hud(int force)
{
    const sh_prof_t *pr = sh_prof();
    char s[48], tv[12];
    unsigned kb, mbps, mins, x, pct, bg = sh_bg(), m1 = sh_is_m1();
    if (!force && sh_hud_drawn && get_tick_count() - sh_t_redraw < 500) return;
    if (!pv_ok()) return;                                                          // v182: HDMI (480 wide): no CHDK layer writes
    kb = GetFreeCardSpaceKb();
    sh_t_redraw = get_tick_count(); sh_hud_drawn = 1;
    // top bar
    draw_rectangle(0, 0, 359, 19, MAKE_COLOR(bg, bg), RECT_BORDER0 | DRAW_FILLED);
    if (sh_rec_on) {
        unsigned sec = (get_tick_count() - sh_rec_t0) / 1000;
        draw_rectangle(4, 5, 13, 14, MAKE_COLOR(COLOR_RED, COLOR_RED), RECT_BORDER0 | DRAW_FILLED);
        sprintf(s, "%02u:%02u", sec / 60, sec % 60);
        draw_string(18, 2, s, MAKE_COLOR(bg, COLOR_RED));
    } else draw_string(4, 2, "M10", SH_C_DIM);
    if (pr->kind == SH_M1) sprintf(s, "%s %ub%s", pr->tag, sh_bpp, sh_m1_ok ? "" : "*");   // v186b: SIZE + BIT
    else sprintf(s, "%s%s", pr->tag, pr->kind == SH_X3 ? (sh_x3_ok ? "" : "*") : (pr->fps != sh_armed_fps ? "*" : ""));
    draw_string(180 - (int)strlen(s) * 4, 2, s, SH_C_BAR);
    if (pr->kind == SH_M1) {   // v186b: W * H * fps * LJ92 factor (bytes / px x 100: 14b 1.02, 12b 1.08, 10b 0.95) -> MB/s
        mbps = ((unsigned)pr->w * pr->h * pr->fps / 100u) * (sh_bpp == 14 ? 102u : sh_bpp == 12 ? 108u : 95u) / 1000000u;   // 32-bit (no __aeabi_uldivmod)
        if (!mbps) mbps = 1;
    } else mbps = pr->bpp == 14 ? 56 : pr->bpp == 12 ? 54 : 45;   // measured MB/s (LJ92, typical scene)
    mins = (kb >> 10) / mbps / 60;
    sprintf(s, "%umin", mins);
    draw_string(300 - (int)strlen(s) * 8, 2, s, mins < 3 ? MAKE_COLOR(bg, COLOR_RED) : SH_C_BAR);
    pct = get_batt_perc();
    draw_rectangle(310, 5, 349, 14, MAKE_COLOR(m1 ? COLOR_BLACK : COLOR_TRANSPARENT, COLOR_WHITE), RECT_BORDER1 | (m1 ? DRAW_FILLED : 0));
    draw_rectangle(350, 8, 352, 11, MAKE_COLOR(COLOR_WHITE, COLOR_WHITE), RECT_BORDER0 | DRAW_FILLED);
    x = 311 + 37 * (pct > 100 ? 100 : pct) / 100;
    if (x > 311) draw_rectangle(311, 6, x, 13, MAKE_COLOR(pct < 20 ? COLOR_RED : COLOR_WHITE, pct < 20 ? COLOR_RED : COLOR_WHITE), RECT_BORDER0 | DRAW_FILLED);
    // bottom bar: hidden during a take (nothing to change)
    draw_rectangle(0, 220, 359, 239, MAKE_COLOR(bg, bg), RECT_BORDER0 | DRAW_FILLED);
    if (!sh_rec_on) {
        static const int fx[SH_NFIELD] = { 4, 68, 114, 166, 236, 272, 312 };   // v186b
        unsigned f;
        for (f = 0; f < SH_NFIELD; f++) {
            switch (f) {
            case 0: if (m1) sprintf(s, "ISO %u", sh_iso_v[sh_m1_iso()]); else if (sh_iso_i) sprintf(s, "ISO %u", sh_iso_v[sh_iso_i]); else strcpy(s, "ISO AUTO"); break;
            case 1: sh_fmt_tv(tv, m1 ? sh_m1_tv() : sh_tv_i); strcpy(s, tv); break;
            case 2: sh_fmt_av(s); break;
            case 3: strcpy(s, pr->short_tag ? pr->short_tag : pr->tag); break;          // v186b: SIZE
            case 4: sprintf(s, "%ub", sh_bpp); break;                                   // v186b: BIT
            case 5: strcpy(s, pv_zebra ? (pv_peak ? "Z+P" : "ZEB") : (pv_peak ? "PK" : "---")); break;   // v183
            default: if (m1) strcpy(s, pv_mode == 0 ? (sh_m1_wide() ? "WIDE" : "FIT") : pv_mode == 1 ? "1:1" : "OFF"); else strcpy(s, pv_full ? "PLEIN" : "VIGN"); break;
            }
            draw_string(fx[f], 222, s, f == sh_field ? SH_C_SEL : SH_C_BAR);
        }
        if (sh_field == 4) {   // v186b: Magic Lantern-style depth selector bar, opaque, rows 200..219
            static const unsigned bv[3] = { 14, 12, 10 };
            unsigned i;
            draw_rectangle(0, 200, 359, 219, MAKE_COLOR(COLOR_BLACK, COLOR_GREY), RECT_BORDER1 | DRAW_FILLED);
            for (i = 0; i < 3; i++) {
                sprintf(s, "%ub", bv[i]);
                draw_string(124 + 40 * (int)i, 202, s, bv[i] == sh_bpp ? SH_C_SEL : sh_bpp_ok(pr, bv[i]) ? SH_C_BAR : MAKE_COLOR(COLOR_BLACK, COLOR_GREY_DK));
            }
        }
    } else {
        if (m1) sprintf(s, "ISO %u", sh_iso_v[sh_m1_iso()]); else if (sh_iso_i) sprintf(s, "ISO %u", sh_iso_v[sh_iso_i]); else strcpy(s, "ISO AUTO");
        draw_string(4, 222, s, SH_C_DIM);
        sh_fmt_tv(tv, m1 ? sh_m1_tv() : sh_tv_i); draw_string(80, 222, tv, SH_C_DIM);
        sh_fmt_av(tv); draw_string(140, 222, tv, SH_C_DIM);
        draw_string(250, 222, "REC = stop", SH_C_DIM);
    }
    // zebra clip readout next to the thumbnail (v182: ImgMode 1 = top left of the image, opaque)
    if ((sh_pv || (m1 && sh_rec_on)) && pv_clip_pct) {
        sprintf(s, "%u%%", pv_clip_pct);
        if (m1) draw_string(2, 22, s, MAKE_COLOR(COLOR_BLACK, COLOR_YELLOW));
        else draw_string(PV_X, PV_Y - 17 < 20 ? 22 : PV_Y - 17, s, MAKE_COLOR(COLOR_GREY_DK_TRANS, COLOR_YELLOW));
    }
    // toast (centre, 2 s)
    if (sh_dirty) { sh_dirty = 0; sh_toast_t = get_tick_count(); }
    if (sh_l1[0] && get_tick_count() - sh_toast_t < 2000) {
        unsigned w = strlen(sh_l1) > strlen(sh_l2) ? strlen(sh_l1) : strlen(sh_l2);
        int x0 = 180 - (int)w * 4 - 6;
        if (x0 < 0) x0 = 0;
        draw_rectangle(x0, 102, 359 - x0, sh_l2[0] ? 138 : 120, MAKE_COLOR(bg, bg), RECT_BORDER0 | DRAW_FILLED);
        draw_string(180 - (int)strlen(sh_l1) * 4, 103, sh_l1, SH_C_BAR);
        if (sh_l2[0]) draw_string(180 - (int)strlen(sh_l2) * 4, 121, sh_l2, SH_C_DIM);
    } else if (sh_l1[0]) {
        unsigned y;
        sh_l1[0] = 0;
        if (m1) pv_fill(100, 140, 0, PV_BW, PV_BLACK);                            // v182: back to the opaque mask (the next render refills the image)
        else for (y = 100; y < 140; y++) memset(PV_RGBA + y * PV_BW, 0, PV_BW * 4);   // under the toast only
        if (sh_pv) sh_t_redraw = 0;
    }
    vid_bitmap_refresh();
}
// v164: magnifier "radar". Canon's x5 LCD shows only the magnifier rect [0x57d38: cx cy x0 y0 x1 y1]
// (readout coordinates, 1040 x 694) of the 2592 x 1108 readout; the take records columns
// v174: kept only as a small frame-line warning when the x5 view leaves the recorded window.
#define SH_MAGRECT  0x00057d38
static int sh_zoom_now(void) { return shamem(0xc0f06804) == 0x045702a6; }
static void sh_redraw(int force)   // v174: CHDK gui task entry point: HUD only, never during a take
{
    if (sh_rec_on && !force) return;
    if (sh_pv && !force) return;                     // preview loop draws the HUD itself
    sh_hud(force);
}
static volatile unsigned sh_lua_wait = 0;   // v178c: while set, CHDK's kbd task reaches action_stack_process_all (Lua script runs)
static int sh_kbd(void) { return (sh_on && !sh_lua_wait) ? 1 : 0; }   // v161: 1 = masked keys (REC, SET, MENU, arrows, shutter) never reach Canon; touch is not masked
static gui_handler sh_gui = { GUI_MODE_MODULE, sh_redraw, sh_kbd, 0, 0, GUI_MODE_FLAG_NODRAWRESTORE };
static gui_handler *sh_prev_gui = 0;
static void sh_gui_assert(void) { if (sh_on && camera_info.state.gui_mode != GUI_MODE_MODULE) { gui_handler *o = gui_set_mode(&sh_gui); if (!sh_prev_gui && o != &sh_gui) sh_prev_gui = o; } }
static void sh_poke(unsigned a, unsigned v)   // atomic 32-bit store through the hook's poke32 (as m10sio)
{
    if (sh_hook) ((fn2)(((unsigned)sh_hook) | 1))(a, v); else *(volatile unsigned *)a = v;
}
static int sh_install_hook(void)
{
    unsigned p = *(volatile unsigned *)SH_PTR, b, size = 0x500 + SH_NENT * 64;
    if (p != SH_ORIG) {                                       // already there (host tools or earlier run)
        unsigned m = *(volatile unsigned *)((p & ~1u) - 0x10 + 0x200);
        if (m == 0x364f4953 || m == 0x354f4953 || m == 0x344f4953) { sh_hook = (char *)((p & ~1u) - 0x10); return 1; }
        return 0;
    }
    if (memcmp((void *)0x120, "\x43\x68\x23\xf0\xff\x03\x13\x43", 8)) return 0;   // low-RAM SIO code differs
    b = (unsigned)malloc(size + 32);
    if (!b) return 0;
    b = (b + 31) & ~31u;
    memset((void *)b, 0, size);
    memcpy((void *)b, hook6_blob, HOOK6_LEN);
    { unsigned *h = (unsigned *)(b + 0x200); h[0] = 0x364f4953; h[1] = 0; h[2] = SH_ORIG; h[3] = 0x50; h[4] = SH_NENT - 1; }
    ((fn2)FN_DCLEAN)(b, size);
    ((fn2)FN_IINVAL)(b, HOOK6_LEN);
    sh_hook = (char *)b;
    ((fn2)(b | 1))(SH_PTR, (b + 0x10) | 1);                  // poke32: atomic swap
    return 1;
}
static int sh_install_trap(void)
{
    unsigned p = *(volatile unsigned *)SH_CBR, b;
    if (p != SH_CANONCBR) return 1;                           // stub already there
    if (!sh_stub) {
        b = (unsigned)malloc(STUB2_LEN + 16);
        if (!b) return 0;
        b = (b + 7) & ~7u;
        memset((void *)b, 0, STUB2_LEN);
        memcpy((void *)b, stub2_blob, sizeof(stub2_blob));
        ((fn2)FN_DCLEAN)(b, STUB2_LEN);
        ((fn2)FN_IINVAL)(b, STUB2_LEN);
        sh_stub = (char *)b;
    }
    sh_poke(SH_CBR, ((unsigned)sh_stub + 0x10) | 1);
    *(volatile unsigned *)0xfa84 = 0;
    return 1;
}
static int sh_arm_fps(const sh_prof_t *pr, int update_cache)   // = m10zfps.py arm <fl> cache fld (live116)
{
    unsigned cur = *(volatile unsigned *)(SH_TGTAB + 4 * 46), per = pr->per;
    if (pr->kind != SH_X5) return 1;   /* v178: 1x3 leaves table 46 / sh_armed_fps alone (armed from PLAY at the REC key, sh_x3_arm); v182: ImgMode 1 has its own tables (sh_m1_arm_tables) */
    if (cur != (unsigned)sh_rec) {
        if (*(volatile unsigned short *)SH_REC46 != 732 || *(volatile unsigned short *)(SH_REC46 + 0xc) != 1456 || *(volatile unsigned *)(SH_REC46 + 0xc8) != 33306) return 0;
        if (*(volatile unsigned *)SH_FLD46 != 33306 || *(volatile unsigned *)(SH_FLD46 + 0x14) != 31979) return 0;
        if (!sh_rec) { unsigned b = (unsigned)malloc(0xd0 + 0x60 + 64); if (!b) return 0; sh_rec = (char *)((b + 31) & ~31u); }
        memcpy(sh_rec, (void *)SH_REC46, 0xd0);
        memcpy(sh_rec + 0xd0, (void *)SH_FLD46, 0x60);
    }
    *(unsigned short *)(sh_rec + 0x0c) = pr->fl; *(unsigned short *)(sh_rec + 0x10) = pr->fl;
    *(unsigned short *)(sh_rec + 0x80) = pr->fl - 57; *(unsigned *)(sh_rec + 0xc8) = per;
    *(unsigned *)(sh_rec + 0xd0) = per; *(unsigned *)(sh_rec + 0xd0 + 0x14) = per - (33306 - 31979);
    ((fn2)FN_DCLEAN)((unsigned)sh_rec, 0x130);
    if (cur != (unsigned)sh_rec) {
        sh_poke(SH_TGTAB + 4 * 46, (unsigned)sh_rec);
        sh_poke(SH_TGTAB + 0xe4 + 4 * 46, (unsigned)sh_rec + 0xd0);
    }
    if (update_cache) {
        sh_poke(SH_CACHE41 + 0x1c, per);
        sh_armed_fps = pr->fps;
    }
    return 1;
}
static int sh_handle_nav(int zoom)   // v174: UP/DOWN = field, LEFT/RIGHT = value. 1 = changed, 2 = preview geometry
{
    static unsigned prev = 0, t_rep = 0;
    unsigned cur = (kbd_is_key_pressed(KEY_LEFT) ? 1u : 0u)
                 | (kbd_is_key_pressed(KEY_RIGHT) ? 2u : 0u)
                 | (kbd_is_key_pressed(KEY_UP) ? 4u : 0u)
                 | (kbd_is_key_pressed(KEY_DOWN) ? 8u : 0u);
    unsigned edge = cur & ~prev, ret = 1;
    int d;
    if (!edge && (cur & 3) && get_tick_count() - t_rep > 350) edge = cur & 3;   // hold LEFT/RIGHT = repeat
    if (edge) t_rep = get_tick_count();
    prev = cur;
    if (!edge) return 0;
    if (edge & 12) {   // v186b: leaving BIT wipes its selector bar (rows 200..219)
        unsigned of = sh_field;
        sh_field = (edge & 4) ? (sh_field + SH_NFIELD - 1) % SH_NFIELD : (sh_field + 1) % SH_NFIELD;
        if (of == 4 && sh_field != 4) { pv_mask_dirty = 1; return 2; }
        return 1;
    }
    d = (edge & 2) ? 1 : -1;
    if (sh_is_m1() && (sh_field == 0 || sh_field == 1)) {   // v182: ImgMode 1: no AUTO (no Canon AE on that path), wrap 1..N-1
        unsigned n = sh_field ? SH_NTV : SH_NISO, i = sh_field ? sh_m1_tv() : sh_m1_iso();
        i = (i - 1 + (n - 1) + d) % (n - 1) + 1;
        if (sh_field) sh_tv_i = i; else sh_iso_i = i;
        sh_expo_apply();
        return 1;
    }
    switch (sh_field) {
    case 0: sh_iso_i = (sh_iso_i + SH_NISO + d) % SH_NISO; sh_expo_apply(); break;
    case 1: sh_tv_i = (sh_tv_i + SH_NTV + d) % SH_NTV; sh_expo_apply(); break;
    case 2: {
        int lo = shooting_get_min_av96(), hi = shooting_get_max_av96(), v = sh_av96;
        if (lo < 0 || hi <= lo) { sh_say("OUVERTURE", "indisponible"); break; }
        if (!v) v = d > 0 ? lo : hi;                      // AUTO -> widest (RIGHT) or smallest (LEFT)
        else { v += 32 * d; if (v < lo || v > hi) v = 0; }   // 1/3 stop; past either end -> AUTO
        sh_av96 = v;
        sh_av_apply();
        break;
    }
    case 3: {
        unsigned k0 = sh_prof()->kind;
        unsigned g0 = sh_m1_geom(sh_prof());
        sh_prof_idx = (sh_prof_idx + SH_NPROF + d) % SH_NPROF;
        sh_bpp_clamp(sh_prof());                          // v186b: SIZE clamps BIT to the highest supported depth
        if (sh_prof()->kind != SH_X3 && k0 == SH_X3) { sh_x3_ok = 0; sh_hook_w(0x240 + 4 * 7, 0); }   // v178: leaving 1x3 drops its CMOS 7 override
        if ((k0 == SH_M1) != (sh_prof()->kind == SH_M1)) { ret = 2; break; }   // v182: into / out of ImgMode 1: shell_task switches (Lua IPC, tables)
        sh_arm_fps(sh_prof(), !zoom);
        sh_expo_apply();                                  // Tv lines depend on the frame length
        if (sh_m1_geom(sh_prof()) != g0) ret = 2;         // v186b: new SIZE -> preview geometry (re-arm in the shell)
        if (zoom && sh_prof()->kind == SH_X5 && sh_prof()->fps != sh_armed_fps) sh_say("CADENCE: SORTIR/RENTRER x5", 0);
        if (sh_prof()->kind == SH_X3) sh_say("1x3 25p 12b", "REC = armer");
        break;
    }
    case 4:     // v186b: BIT 14 -> 12 -> 10 (RIGHT) / 10 -> 12 -> 14 (LEFT); no sensor re-switch (sh_m1_geom unchanged)
        sh_bpp_step(sh_prof(), d);
        break;
    case 5: {   // v183: Z+P -> PK -> ZEB -> --- (m = zebra | peak << 1, idx = 3 - m)
        unsigned m = (pv_zebra ? 1u : 0u) | (pv_peak ? 2u : 0u), idx = 3u - m;
        idx = (idx + 4u + (unsigned)d) & 3u; m = 3u - idx;
        pv_zebra = m & 1u; pv_peak = (m >> 1) & 1u;
        break;
    }
    default:
        if (sh_is_m1()) pv_mode = (pv_mode + 3 + d) % 3;  // v182: 4:3 / 1:1 / OFF
        else pv_full = !pv_full;
        ret = 2; break;
    }
    return ret;
}
static int sh_next_take(void)   // first free A/M10_NNNN.MLV
{
    char nm[24];
    unsigned n;
    for (n = sh_take ? sh_take + 1 : 1; n < 10000; n++) {
        int fd; sprintf(nm, "A/M10_%04d.MLV", n);
        fd = open(nm, O_RDONLY, 0777);
        if (fd < 0) { sh_take = n; sprintf(xr_base, "A/M10_%04d", n); return 1; }
        close(fd);
    }
    return 0;
}
static int sh_key_down(void) { return kbd_is_key_pressed(sh_key); }
static void sh_wait_release(void) { unsigned t = get_tick_count(); while (sh_key_down() && get_tick_count() - t < 3000) msleep(20); }
static void sh_x3_restore_ptr(void);
static void sh_m1_restore_tables(void);
static void sh_uninstall(void)   // v162: hand the camera back to Canon (USB plugged / quit)
{
    sh_m1_restore_tables();
    sh_x3_restore_ptr();
    if (sh_rec && *(volatile unsigned *)(SH_TGTAB + 4 * 46) == (unsigned)sh_rec) {
        sh_poke(SH_TGTAB + 4 * 46, SH_REC46);
        sh_poke(SH_TGTAB + 0xe4 + 4 * 46, SH_FLD46);
        sh_poke(SH_CACHE41 + 0x1c, 33306);
    }
    if (sh_stub && *(volatile unsigned *)SH_CBR == (((unsigned)sh_stub + 0x10) | 1)) sh_poke(SH_CBR, SH_CANONCBR);
    sh_expo_off();                                            // v174: Canon owns exposure again
    if (sh_hook && *(volatile unsigned *)SH_PTR == (((unsigned)sh_hook + 0x10) | 1)) sh_poke(SH_PTR, SH_ORIG);   // poke32 runs from the hook code itself, still in RAM
    sh_hook = 0;
}

// ---------------------------------------------------------------------------
// v182 (spec C.2/C.3): ImgMode 1 (1920x1440 1:1) RAM tables, power lock, and
// filesystem-free RAM IPC with M10SHELL.LUA (siohook6 header +0x220 / +0x224).
// ---------------------------------------------------------------------------
#define FN_LOCK_PWR    0xfc1fb48d   // LockMainPower (1.10d stubs_entry.S)
#define FN_UNLOCK_PWR  0xfc1fb425   // UnlockMainPower (1.10d stubs_entry.S)
#define SH_M1_TAB_EX   0x2cd24
#define SH_M1_SLOT_EX  3
#define SH_M1_REC_EX   0xfc72f27c
#define SH_M1_EX_SZ    0x68
#define SH_M1_DRV      9
#define SH_M1_ROMREC   0xfc72fd0c
#define SH_M1_TG_SZ    0xd0
#define SH_M1_FLD_SZ   0x2c
#define SH_M1_CACHE1   (0x575b0 + 36 * 1)
#define SH_M1_X0       0x34
#define SH_M1_Y0       32
#define SH_M1_W        1920
#define SH_M1_HEAD_H   1456
#define SH_M1_FL       1819
#define SH_M1_PER      41666
#define SH_M1_FC3C_VAL ((7058 - 2 * SH_M1_HEAD_H) / 2)   // 2073
#define SH_IPC_REQ_OFF 0x220
#define SH_IPC_ACK_OFF 0x224
#define SH_IPC_ARG_OFF 0x280   // v185: siohook6 pad, C -> Lua argument ([0xfc3c] for m1_on)
#define SH_IPC_M1_ON   1
#define SH_IPC_M1_OFF  2
#define SH_IPC_REC     3
#define SH_IPC_PLAY    4
#define SH_IPC_AF      5   // v183: one-shot Canon hybrid AF (Lua: ImgMode 1 off, AF, back)
#define SH_IPC_END     0xE0

static char *sh_m1_ex = 0, *sh_m1_tg = 0, *sh_m1_fld = 0;
static unsigned sh_m1_orig_fld = 0, sh_m1_orig_cache[9], sh_m1_fc3c0 = 0;
static int sh_m1_patched = 0, sh_m1_fc3c_saved = 0, sh_pwr_locked = 0;

static void sh_pwr_lock(int lock)
{
    if (lock && !sh_pwr_locked) {
        ((fn0)FN_LOCK_PWR)();
        ((fn1)0xfc1fb4dd)(0);   // v184c: SetAutoShutdownTime(0) (1.10d stubs_entry.S): no Display-Off / idle timer
        sh_pwr_locked = 1;
    }
    else if (!lock && sh_pwr_locked) { ((fn0)FN_UNLOCK_PWR)(); sh_pwr_locked = 0; }
}

static int sh_ipc_req(unsigned code, unsigned ms)   // v182 (C.3): RAM mailbox in siohook6 (+0x220 req, +0x224 ack)
{
    unsigned t = get_tick_count(), ack = 0;
    if (!sh_hook || *(volatile unsigned *)((unsigned)sh_hook + 0x200) != 0x364f4953) return 0;
    sh_hook_w(SH_IPC_ACK_OFF, 0);
    sh_lua_wait = 1;                                          // let CHDK kbd_task run the Lua script
    sh_hook_w(SH_IPC_REQ_OFF, code);
    slog("v182 ipc req=%x", code, 0);
    while (get_tick_count() - t < ms) {
        ack = *(volatile unsigned *)((unsigned)sh_hook + SH_IPC_ACK_OFF);
        if ((ack & 0x1ffu) == (code | 0x100u)) {
            sh_lua_wait = 0;
            slog("v182 ipc ack=%08x ms=%d", ack, get_tick_count() - t);
            return (code == SH_IPC_END) ? 1 : (int)((ack >> 9) & 1u);
        }
        msleep(50);
    }
    sh_hook_w(SH_IPC_REQ_OFF, 0);
    sh_lua_wait = 0;
    slog("v182 ipc timeout req=%x", code, 0);
    return 0;
}

static int sh_m1_arm_tables(void)   // v182 (C.2): RAM copies of Extract[3], TgPixelRes[9], FldSpec[9], cache[1]
{
    unsigned W = sh_m1_w(), HH = sh_m1_head_h(), X0 = sh_m1_x0(), LC = sh_m1_lclk(), FL = sh_m1_fl(), PER = sh_m1_per();   // v185
    unsigned i, x1 = X0 + W / 4, y1 = SH_M1_Y0 + HH - 1;
    unsigned ll = (LC << 16) | LC, fld_delta;
    if (!sh_m1_patched) {
        unsigned cur_ex = *(volatile unsigned *)(SH_M1_TAB_EX + 4 * SH_M1_SLOT_EX);
        unsigned cur_tg = *(volatile unsigned *)(SH_TGTAB + 4 * SH_M1_DRV);
        if (cur_ex != SH_M1_REC_EX || cur_tg != SH_M1_ROMREC) {
            slog("v182 m1 tables unexpected ex=%08x tg=%08x", cur_ex, cur_tg);
            return 0;
        }
        sh_m1_orig_fld = *(volatile unsigned *)(SH_TGTAB + 0xe4 + 4 * SH_M1_DRV);
        for (i = 0; i < 9; i++) sh_m1_orig_cache[i] = *(volatile unsigned *)(SH_M1_CACHE1 + 4 * i);
    }
    if (!sh_m1_fc3c_saved) { sh_m1_fc3c0 = *(volatile unsigned *)0xfc3c; sh_m1_fc3c_saved = 1; }
    if (!sh_m1_ex) {
        unsigned b = (unsigned)malloc(SH_M1_EX_SZ + 32);
        if (!b) return 0;
        sh_m1_ex = (char *)((b + 15) & ~15u);
    }
    if (!sh_m1_tg) {
        unsigned b = (unsigned)malloc(SH_M1_TG_SZ + SH_M1_FLD_SZ + 64);
        if (!b) return 0;
        sh_m1_tg = (char *)((b + 15) & ~15u);
        sh_m1_fld = sh_m1_tg + SH_M1_TG_SZ + 16;
    }
    memcpy(sh_m1_ex, (void *)SH_M1_REC_EX, SH_M1_EX_SZ);
    *(unsigned *)(sh_m1_ex + 0x0c) = W;      *(unsigned *)(sh_m1_ex + 0x10) = HH;
    *(unsigned *)(sh_m1_ex + 0x14) = W;      *(unsigned *)(sh_m1_ex + 0x18) = HH;
    *(unsigned *)(sh_m1_ex + 0x24) = x1;           *(unsigned *)(sh_m1_ex + 0x28) = y1;
    *(unsigned *)(sh_m1_ex + 0x2c) = X0;     *(unsigned *)(sh_m1_ex + 0x30) = SH_M1_Y0;

    memcpy(sh_m1_tg, (void *)SH_M1_ROMREC, SH_M1_TG_SZ);
    *(unsigned *)(sh_m1_tg + 0x00) = ll;           *(unsigned *)(sh_m1_tg + 0x04) = ll;
    *(unsigned *)(sh_m1_tg + 0x08) = LC;
    *(unsigned *)(sh_m1_tg + 0x0c) = FL;     *(unsigned *)(sh_m1_tg + 0x10) = FL;
    *(unsigned *)(sh_m1_tg + 0x80) = 0x10000u + (FL - 42);
    *(unsigned *)(sh_m1_tg + 0xc8) = PER;

    memcpy(sh_m1_fld, (void *)sh_m1_orig_fld, SH_M1_FLD_SZ);
    fld_delta = *(volatile unsigned *)sh_m1_orig_fld - *(volatile unsigned *)(sh_m1_orig_fld + 0x14);
    *(unsigned *)(sh_m1_fld + 0x00) = PER;
    *(unsigned *)(sh_m1_fld + 0x14) = (PER > fld_delta + 1000) ? (PER - fld_delta) : 1000;

    ((fn2)FN_DCLEAN)((unsigned)sh_m1_ex, SH_M1_EX_SZ);
    ((fn2)FN_DCLEAN)((unsigned)sh_m1_tg, SH_M1_TG_SZ + SH_M1_FLD_SZ + 16);

    sh_m1_patched = 1;
    sh_poke(SH_M1_TAB_EX + 4 * SH_M1_SLOT_EX, (unsigned)sh_m1_ex);
    sh_poke(SH_TGTAB + 4 * SH_M1_DRV, (unsigned)sh_m1_tg);
    sh_poke(SH_TGTAB + 0xe4 + 4 * SH_M1_DRV, (unsigned)sh_m1_fld);
    sh_poke(SH_M1_CACHE1 + 0, W);            sh_poke(SH_M1_CACHE1 + 4, HH);
    sh_poke(SH_M1_CACHE1 + 8, W);            sh_poke(SH_M1_CACHE1 + 12, HH);
    sh_poke(SH_M1_CACHE1 + 0x1c, PER);
    return 1;
}

static void sh_m1_restore_tables(void)
{
    unsigned i;
    if (sh_m1_fc3c_saved) {
        sh_poke(0xfc3c, sh_m1_fc3c0);
        sh_m1_fc3c_saved = 0;
    }
    if (sh_m1_patched) {
        sh_poke(SH_M1_TAB_EX + 4 * SH_M1_SLOT_EX, SH_M1_REC_EX);
        sh_poke(SH_TGTAB + 4 * SH_M1_DRV, SH_M1_ROMREC);
        sh_poke(SH_TGTAB + 0xe4 + 4 * SH_M1_DRV, sh_m1_orig_fld);
        for (i = 0; i < 9; i++) sh_poke(SH_M1_CACHE1 + 4 * i, sh_m1_orig_cache[i]);
        sh_m1_patched = 0;
    }
}

static int sh_m1_enter(void)   // v182 (C.4): arm tables + overrides + Lua m1_on
{
    unsigned h;
    sh_m1_ok = 0;
    if (!sh_m1_arm_tables()) { sh_say("1440p", "tables RAM refusees"); return 0; }
    sh_expo_apply();
    sh_install_trap();
    sh_say("1440p", "armement...");
    if (pv_ok()) { pv_m1_mask(1); sh_hud(1); }
    sh_hook_w(SH_IPC_ARG_OFF, sh_m1_fc3c());                    // v185: [0xfc3c] for this head height (Lua m1_on)
    if (!sh_ipc_req(SH_IPC_M1_ON, 12000)) {
        sh_m1_restore_tables();
        sh_expo_off();
        sh_say("1440p", "bascule refusee");
        return 0;
    }
    h = shamem(0xc0f06804);
    slog("v182 m1 enter mode=%d tg=%d", *(volatile unsigned *)0x865c, *(volatile unsigned *)0xe664);
    slog("  v182 m1 6804=%08x fc3c=%d", h, *(volatile unsigned *)0xfc3c);
    if (!m1_ready() || (h >> 16) != (SH_M1_Y0 + sh_m1_head_h() - 1)) {
        sh_m1_restore_tables();
        sh_ipc_req(SH_IPC_M1_OFF, 8000);
        sh_say("1440p", "tete inattendue");
        return 0;
    }
    sh_m1_ok = 1;
    sh_m1_armed_geom = sh_m1_geom(sh_prof());                   // v185
    pv_has_img = 0;                                             // v185b: next sh_preview starts with a full opaque wipe
    sh_say("1440p PRET", "REC = prise");
    return 1;
}

static void sh_m1_leave(void)   // v182 (C.4): restore ROM tables + overrides, then Lua m1_off (-> mode 3 + MV_START)
{
    int need = sh_m1_ok || *(volatile unsigned *)0x865c == 1;
    sh_m1_ok = 0;
    sh_m1_restore_tables();
    sh_expo_off();
    if (need) sh_ipc_req(SH_IPC_M1_OFF, 8000);
    pv_mask_clear();
}

// ---------------------------------------------------------------------------
// v178: Film 1x3 (full APS-C width, 3x horizontal binning) armed by the shell itself,
// = tools/_r147_session.py: in PLAY, TgPixelRes 41 (Film) -> RAM copy with a 640-clock line
// (40 ms frame kept: 2000 lines), SIO hook TG table 800c=0 (no vertical skip), then the camera
// enters record (Canon commits Film with our table), CMOS 7 = 0x140 (window, no ghost), head-error
// trap; at the take MOVOFF 8 + WBSmth 0x133c88 = 50 (restored after). Lens on Film (dial).
// ---------------------------------------------------------------------------
#define SH_REC41    0xfc7301ec
#define SH_X3LINE   640
static char *sh_rec41 = 0;
static int sh_x3_ok_now(void) { return sh_x3_ok; }
static int sh_x3_head(void) { return (shamem(0xc0f06804) >> 16) == 0x4a6 && *(volatile unsigned *)0xe664 == 3; }
static void sh_x3_restore_ptr(void)
{
    if (sh_rec41 && *(volatile unsigned *)(SH_TGTAB + 4 * 41) == (unsigned)sh_rec41) sh_poke(SH_TGTAB + 4 * 41, SH_REC41);
}
static int sh_x3_arm(void)   // returns 1 when Film 1x3 runs (head 1190 lines, TG running)
{
    unsigned i, fr, per;
    volatile unsigned *hdr;
    sh_x3_ok = 0;
    if (!sh_hook || *(volatile unsigned *)((unsigned)sh_hook + 0x200) != 0x364f4953) { sh_say("1x3", "hook v6 absent"); return 0; }
    if (*(volatile unsigned short *)SH_REC41 != 520 || *(volatile unsigned short *)(SH_REC41 + 0xc) != 2461 || *(volatile unsigned short *)(SH_REC41 + 0x80) != 2381) { sh_say("1x3", "table Film inattendue"); return 0; }
    sh_say("1x3", "armement...");
    sh_hud(1);
    sh_x3_restore_ptr();                                      // ROM table while Canon changes modes
    slog("v178b arm start rec=%d shoot=%d", camera_info.state.mode_rec, camera_info.state.mode_shooting);
    // v178d: the Film mode is chosen by the user (capmode.set from the script did not stick: live 21:30, back in photo 727 lines)
    if (!camera_info.state.mode_video) { sh_say("PASSE EN MODE FILM", "puis REC"); return 0; }
    if (!camera_info.state.state_kbd_script_run) { sh_say("SCRIPT ARRETE", "eteindre / rallumer"); slog("v178d no script", 0, 0); return 0; }
    // Film (auto) + PLAY by the Lua script; arming must happen in PLAY (r141: arming in a live Film kills the camera)
    if (!sh_ipc_req(SH_IPC_PLAY, 20000)) { sh_say("1x3", "script: lecture impossible"); return 0; }
    msleep(500);
    slog("v178b in play rec=%d tg=%d", camera_info.state.mode_rec, *(volatile unsigned *)0xe664);
    if (!sh_rec41) { unsigned b = (unsigned)malloc(0xd0 + 64); if (!b) return 0; sh_rec41 = (char *)((b + 31) & ~31u); }
    memcpy(sh_rec41, (void *)SH_REC41, 0xd0);
    fr = (40000u * 32 + SH_X3LINE / 2) / SH_X3LINE;          // 2000 lines
    per = (fr * SH_X3LINE + 16) / 32;                         // 40000 us
    for (i = 0; i < 10; i += 2) *(unsigned short *)(sh_rec41 + i) = *(volatile unsigned short *)(SH_REC41 + i) - 520 + SH_X3LINE - 1;
    *(unsigned short *)(sh_rec41 + 0x0c) = fr; *(unsigned short *)(sh_rec41 + 0x10) = fr; *(unsigned short *)(sh_rec41 + 0x80) = fr - 80;
    *(unsigned *)(sh_rec41 + 0xc8) = per;
    ((fn2)FN_DCLEAN)((unsigned)sh_rec41, 0xd0);
    sh_poke(SH_TGTAB + 4 * 41, (unsigned)sh_rec41);
    slog("v178b table41 %x", (unsigned)sh_rec41, 0);
    // TG override table: only 800c = 0 (sh_expo_apply owns entries 0/1 for Tv; 800c goes in entry 2)
    hdr = (volatile unsigned *)((unsigned)sh_hook + 0x200);
    sh_hook_w(0x200 + 28, 0); sh_hook_w(0x200 + 44, 0);
    for (i = 0; i < 64; i++) { sh_hook_w(0x300 + 4 * i, 0); sh_hook_w(0x400 + 4 * i, 0); }
    sh_hook_w(0x308, 0x800c0000u);
    sh_hook_w(0x200 + 40, 0);
    sh_hook_w(0x200 + 28, 1);
    // enter record by the Lua script (half-press + set_record, as _r147_session.py)
    if (!sh_ipc_req(SH_IPC_REC, 20000)) { sh_x3_restore_ptr(); sh_expo_apply(); sh_say("1x3", "script: visee impossible"); return 0; }
    for (i = 0; i < 80 && !sh_x3_head(); i++) msleep(100);
    slog("v178 x3 arm head=%08x tg_hits=%d", shamem(0xc0f06804), hdr[10]);
    sh_hook_w(0x308, 0);                                      // 800c only matters at the commit
    sh_x3_restore_ptr();                                      // the running Film keeps the slow line until the next commit
    sh_expo_apply();                                          // ISO/Tv overrides back (v174)
    if (!camera_info.state.mode_video || !hdr[10] || !sh_x3_head() || shamem(0xc0f06008) != 0x0280027e) { sh_say("1x3", "commit refuse"); slog("v178 x3 fail 6008=%08x", shamem(0xc0f06008), 0); return 0; }
    sh_hook_w(0x240 + 4 * 7, 0x10000 | 0x140);                // CMOS 7 = 0x140 (r144/r145: window without ghost)
    sh_hook_w(0x200 + 20, 1);
    sh_install_trap();
    sh_x3_ok = 1;
    sh_say("1x3 PRET", "REC = prise");
    return 1;
}
static unsigned sh_x3_mov0 = 0, sh_x3_wb0 = 0;
static void sh_x3_take_begin(void)   // MOVOFF 8 + POKE 0x133c88 = 50 (as tools/m10x3raw.py)
{
    sh_x3_mov0 = *(volatile unsigned *)0x35d7c; sh_poke(0x35d7c, sh_x3_mov0 & ~8u);
    sh_x3_wb0 = *(volatile unsigned *)0x133c88; sh_poke(0x133c88, 50);
}
static void sh_x3_take_end(void)
{
    sh_poke(0x35d7c, sh_x3_mov0);
    sh_poke(0x133c88, sh_x3_wb0);
}
static void shell_task(void)
{
    static int osd_saved = -1;
    unsigned prev_kind;
    sh_on = 1;
    sh_m1_ok = 0;
    { int fu = open("A/M10USB.OK", O_RDONLY, 0777); if (fu >= 0) { close(fu); sh_usb_ok = 1; } else sh_usb_ok = 0; }
    sh_pwr_lock(1);                                           // v182 (A.5-6): block Canon APO while shell runs
    slog("v185b shell start", 0, 0);
    osd_saved = conf.show_osd; conf.show_osd = 0;             // v174: no CHDK OSD (DNG/space/batt/clock/temp)
    draw_restore();
    if (sh_usb()) { sh_say("USB branche", "shell arrete"); goto out; }   // v162
    if (!sh_install_hook()) { sh_say("ERREUR", "hook capteur refuse"); goto out; }
    if (!sh_arm_fps(sh_prof(), 1)) { sh_say("ERREUR", "cadence refusee"); goto out; }
    wb_wd_start();                                            // v182 (A.5-1): independent WBInteg watchdog (prio 0x18)
    slog("v182 hook %x rec46 %x", (unsigned)sh_hook, *(volatile unsigned *)(SH_TGTAB + 4 * 46));
    sh_expo_apply();
    sh_av_apply();
    remove("A/M10SH.END");
    prev_kind = sh_prof()->kind;
    if (prev_kind == SH_M1) sh_say("M10 1440p", "initialisation...");
    else sh_say("M10 CINE", prev_kind == SH_X3 ? "REC = armer 1x3" : "touche la loupe x5");
    for (;;) {
        unsigned h = shamem(0xc0f06804), kb;
        int zoom = (h == 0x045702a6), nv;
        const sh_prof_t *pr = sh_prof();
        // v182 (C.4): handle profile transitions into / out of ImgMode 1 cleanly
        if (prev_kind == SH_M1 && pr->kind != SH_M1) {
            wb_wd_force = 1; wb_kick_now(); sh_m1_leave(); msleep(400); wb_wd_force = 0;   // v185b: WBInteg.c:3491 assert on 1440p -> x5/1x3
            sh_arm_fps(pr, !zoom);
            sh_expo_apply();
            if (pr->kind == SH_X3) sh_say("1x3 25p 12b", "REC = armer");
            else sh_say(pr->tag, "touche la loupe x5");
            sh_hud(1);
        }
        prev_kind = pr->kind;

        // ---------------- v182: ImgMode 1 1920x1440 1:1 ----------------
        if (pr->kind == SH_M1) {
            sh_install_trap();
            sh_gui_assert();
            if (sh_usb()) { sh_say("USB branche", "sortie"); break; }
            if (sh_quit_req || (kbd_is_key_pressed(KEY_MENU) && kbd_is_key_pressed(KEY_SET))) { sh_say("M10 CINE", "sortie"); break; }
            if (sh_m1_ok && sh_m1_geom(pr) != sh_m1_armed_geom) {   // v185: ImgMode 1 geometry changed -> full re-enter
                slog("v185 m1 geom %x -> %x", sh_m1_armed_geom, sh_m1_geom(pr));
                wb_wd_force = 1; wb_kick_now();
                sh_m1_enter();
                wb_wd_force = 0;
                sh_hud(1);
                msleep(100);
                continue;
            }
            if (!sh_m1_ok) {
                if (m1_ready() && (h >> 16) == (SH_M1_Y0 + sh_m1_head_h() - 1)) {
                    sh_m1_ok = 1;
                } else if (!camera_info.state.mode_rec) {
                    sh_say("1440p", "passage en visee...");
                    sh_hud(1);
                    wb_wd_force = 1; wb_kick_now();           // v184c: WB keepalive across the REC switch
                    if (*(volatile unsigned *)0x865c == 1) { sh_m1_restore_tables(); sh_expo_off(); sh_ipc_req(SH_IPC_M1_OFF, 5000); }
                    sh_ipc_req(SH_IPC_REC, 8000);
                    wb_wd_force = 0;
                    msleep(200);
                    continue;
                } else if (*(volatile unsigned *)0x865c == 3 && *(volatile unsigned *)0xe664 == 3 && !camera_info.state.mode_video) {
                    sh_m1_enter();
                    sh_hud(1);
                    msleep(100);
                    continue;
                } else {
                    nv = sh_handle_nav(0);
                    sh_say("MODE PHOTO (M) REQUIS", "Tourner molette -> M");
                    sh_hud(nv != 0);
                    msleep(150);
                    continue;
                }
            }
            if (!m1_ready()) {
                sh_m1_ok = 0;
                sh_m1_restore_tables();
                sh_say("MODE 1440p PERDU", "re-armement...");
                sh_hud(1);
                msleep(300);
                continue;
            }
            nv = sh_handle_nav(0);
            if (nv == 2 && (sh_prof()->kind != SH_M1 || sh_m1_geom(sh_prof()) != sh_m1_armed_geom)) continue;   // profile switched away from 1440p
            if (nv == 2) pv_m1_mask(1);
            kb = GetFreeCardSpaceKb();
            sh_hud(nv != 0);
            if (kb >= 600 * 1024) {                           // live RGGB 1440p preview (4:3, 1:1 focus, or OFF) until REC/MENU/USB/profile
                sh_stop_req = 0; sh_pv = 1;
                sh_pv_hud();
                lv_x3();
                sh_pv = 0;
                if (sh_pv_key == 3) { sh_say("M10 CINE", "sortie"); break; }
                if (sh_pv_key == 4) { sh_say("USB branche", "sortie"); break; }
                if (sh_pv_key == 7) continue;                 // profile changed away from 1440p
                if (sh_pv_key == 5) { sh_m1_ok = 0; sh_m1_restore_tables(); sh_say("MODE 1440p PERDU", 0); msleep(200); continue; }
                if (sh_pv_key == 6) { sh_say("APERCU EN ERREUR", "REC reste possible"); sh_hud(1); msleep(800); }
                if (sh_pv_key != 1 && sh_pv_key != 2) {
                    if (sh_pv_key != 6) { msleep(100); continue; }
                    if (!(sh_key_down() || kbd_is_key_pressed(KEY_SET))) { msleep(50); continue; }
                }
                sh_key = (sh_pv_key == 2 || kbd_is_key_pressed(KEY_SET)) ? KEY_SET : KEY_VIDEO;
                sh_wait_release(); sh_stop_req = 0;
            } else {
                if (kbd_is_key_pressed(KEY_MENU) || !(sh_key_down() || kbd_is_key_pressed(KEY_SET))) { msleep(50); continue; }
                sh_key = kbd_is_key_pressed(KEY_VIDEO) ? KEY_VIDEO : KEY_SET;
                sh_wait_release();
            }
            if (!m1_ready()) { sh_m1_ok = 0; sh_m1_restore_tables(); continue; }
            if (kb < 600 * 1024) { sh_say("CARTE PLEINE", 0); sh_hud(1); msleep(1500); continue; }
            if (!sh_next_take()) { sh_say("PLUS DE NUMERO LIBRE", 0); sh_hud(1); msleep(1500); continue; }
            if (*(volatile unsigned *)0xfc3c != sh_m1_fc3c()) {   // v184c: Canon ReEVF ran (MotionVector awake): full re-enter, no blind poke
                slog("v184c fc3c reset=%d -> re-enter", *(volatile unsigned *)0xfc3c, 0);
                sh_m1_enter();
                if (!sh_m1_ok) continue;
            }
            *(volatile unsigned *)0xfa84 = 0;
            sh_gui_assert();
            sh_rec_on = 1; sh_rec_t0 = get_tick_count(); sh_l1[0] = 0; sh_hud_clear(); sh_hud(1);
            camera_set_led(4, 1, 0);
            sh_stop_req = 0;
            lv_x3();                                          // REC 1920x1440 until stop / error / XR_MAX frames
            camera_set_led(4, 0, 0); sh_rec_on = 0;
            sh_wait_release(); msleep(300); sh_stop_req = 0;
            sh_frames = xr_wr;
            sprintf(sh_line, "%u images%s%s", sh_frames, msg[0] ? "  " : "", msg);
            slog("v182 m1 take %d frames=%d", sh_take, sh_frames);
            // v182 (C.4): NEVER re-switch ImgMode 1 after a take; only check health + [0xfc3c]
            if (!m1_ready()) { sh_m1_ok = 0; sh_m1_restore_tables(); sh_say("MODE 1440p PERDU", "re-armement..."); }
            else {
                if (*(volatile unsigned *)0xfc3c != sh_m1_fc3c()) sh_poke(0xfc3c, sh_m1_fc3c());
                *(volatile unsigned *)0xfa84 = 0;
                sh_say(xr_base + 2, sh_line);
            }
            sh_hud_clear(); sh_hud(1);
            msleep(1500);
            continue;
        }

        // ---------------- Film 1x3 (v178) ----------------
        if (pr->kind == SH_X3) {                              // v178: Film 1x3 profile (no magnifier, no preview)
            sh_install_trap();
            sh_gui_assert();
            nv = sh_handle_nav(0);
            if (nv == 2 && sh_prof()->kind != SH_X3) continue;
            kb = GetFreeCardSpaceKb();
            sh_hud(nv != 0);
            if (sh_usb()) { sh_say("USB branche", "sortie"); break; }
            if (sh_quit_req || (kbd_is_key_pressed(KEY_MENU) && kbd_is_key_pressed(KEY_SET))) { sh_say("M10 CINE", "sortie"); break; }
            if (sh_x3_ok && !sh_x3_head()) { sh_x3_ok = 0; sh_hook_w(0x240 + 4 * 7, 0); sh_say("1x3 PERDU", "REC = rearmer"); }
            if (kbd_is_key_pressed(KEY_MENU) || !(sh_key_down() || kbd_is_key_pressed(KEY_SET))) { msleep(50); continue; }
            sh_key = kbd_is_key_pressed(KEY_VIDEO) ? KEY_VIDEO : KEY_SET;
            sh_wait_release();
            if (!sh_x3_ok) { sh_x3_arm(); sh_hud(1); sh_wait_release(); sh_stop_req = 0; continue; }   // 1st press arms, 2nd records
            if (kb < 600 * 1024) { sh_say("CARTE PLEINE", 0); sh_hud(1); msleep(1500); continue; }
            if (!sh_next_take()) { sh_say("PLUS DE NUMERO LIBRE", 0); sh_hud(1); msleep(1500); continue; }
            sh_gui_assert();
            sh_x3_take_begin();
            sh_rec_on = 1; sh_rec_t0 = get_tick_count(); sh_l1[0] = 0; sh_hud_clear(); sh_hud(1);
            camera_set_led(4, 1, 0);
            sh_stop_req = 0;
            lv_x3();
            camera_set_led(4, 0, 0); sh_rec_on = 0;
            sh_x3_take_end();
            sh_wait_release(); msleep(300); sh_stop_req = 0;
            sh_frames = xr_wr;
            sprintf(sh_line, "%u images he %u%s%s", sh_frames, x_he_n, msg[0] ? "  " : "", msg);
            slog("v178 x3 take %d frames=%d", sh_take, sh_frames);
            { char nm[24]; int fe; sprintf(nm, "%s.HE", xr_base); fe = open(nm, O_WRONLY | O_CREAT | O_TRUNC, 0777);   // head-error list next to the take (host repair: m10x3fix --log)
              if (fe >= 0) { char ln[32]; unsigned q; for (q = 0; q < x_he_n && q < HE_ALL_N; q++) { int l = sprintf(ln, "he at frame %u\n", x_he_all[q] >> 8); write(fe, ln, l); } close(fe); } }
            sh_say(xr_base + 2, sh_line); sh_hud_clear(); sh_hud(1);
            msleep(1500);
            continue;
        }

        // ---------------- x5 magnifier (v160-v176) ----------------
        sh_install_trap();                                    // lost at each magnifier entry / exit: re-arm always
        sh_gui_assert();                                      // v161
        if (!zoom && sh_armed_fps != pr->fps) sh_arm_fps(pr, 1);
        nv = sh_handle_nav(zoom);
        if (nv == 2 && sh_prof()->kind != SH_X5) continue;
        if (nv == 2) pv_geom();
        kb = GetFreeCardSpaceKb();
        sh_hud(nv != 0);
        if (sh_usb()) { sh_say("USB branche", "sortie"); break; }      // v162: PC connection -> leave
        if (sh_quit_req || (kbd_is_key_pressed(KEY_MENU) && kbd_is_key_pressed(KEY_SET))) { sh_say("M10 CINE", "sortie"); break; }   // v176: MENU held 1 s (or MENU + SET)
        if (zoom && kb >= 600 * 1024) {                        // v165: live B&W preview from our RAW until a key
            sh_stop_req = 0; sh_pv = 1;
            sh_pv_hud();
            lv_x3();
            sh_pv = 0;
            if (sh_pv_key == 3) { sh_say("M10 CINE", "sortie"); break; }
            if (sh_pv_key == 6) { sh_say("APERCU EN ERREUR", "REC reste possible"); sh_hud(1); msleep(1000); }
            if (sh_pv_key != 1 && sh_pv_key != 2) {           // left the magnifier / USB / preview error: loop re-checks
                if (sh_pv_key == 5) sh_say("LOUPE QUITTEE", "touche la loupe x5");
                if (sh_pv_key != 6) { msleep(100); continue; }
                if (!(sh_key_down() || kbd_is_key_pressed(KEY_SET))) { msleep(50); continue; }
            }
            sh_key = (sh_pv_key == 2 || kbd_is_key_pressed(KEY_SET)) ? KEY_SET : KEY_VIDEO;
            sh_wait_release(); sh_stop_req = 0;
            zoom = (shamem(0xc0f06804) == 0x045702a6);
        } else {
            if (kbd_is_key_pressed(KEY_MENU) || !(sh_key_down() || kbd_is_key_pressed(KEY_SET))) { msleep(50); continue; }
            sh_key = kbd_is_key_pressed(KEY_VIDEO) ? KEY_VIDEO : KEY_SET;
            sh_wait_release();
        }
        if (!zoom) { sh_say("PAS EN LOUPE", "touche la loupe x5"); sh_hud(1); msleep(800); continue; }
        if (kb < 600 * 1024) { sh_say("CARTE PLEINE", 0); sh_hud(1); msleep(1500); continue; }
        if (!sh_next_take()) { sh_say("PLUS DE NUMERO LIBRE", 0); sh_hud(1); msleep(1500); continue; }
        sh_gui_assert();
        sh_rec_on = 1; sh_rec_t0 = get_tick_count(); sh_l1[0] = 0; sh_hud_clear(); sh_hud(1);
        camera_set_led(4, 1, 0);
        sh_stop_req = 0;
        lv_x3();                                              // REC until stop / error / XR_MAX frames
        camera_set_led(4, 0, 0); sh_rec_on = 0;
        sh_wait_release(); msleep(300); sh_stop_req = 0;   // stop press must not start the next take
        sh_frames = xr_wr;
        sprintf(sh_line, "%u images%s%s", sh_frames, msg[0] ? "  " : "", msg);
        slog("v160 take %d frames=%d", sh_take, sh_frames);
        sh_say(xr_base + 2, sh_line); sh_hud_clear(); sh_hud(1);
        msleep(1500);
    }
out:
    wb_wd_force = 1; wb_kick_now();                           // v184c: keep WBInteg fed through the 1 -> 3 switch
    sh_m1_leave();                                            // v182: restore ImgMode 1 -> Photo 3 while Lua & hook are still alive
    msleep(400); wb_wd_force = 0;                             // v184c: settle (WBInteg.c:3491 3 s assert on MENU exit)
    wb_wd_end();                                              // v182: stop WB watchdog before unloading hook/module
    sh_ipc_req(SH_IPC_END, 1500);                             // v182: tell M10SHELL.LUA to exit cleanly before 0x9b50=0x121
    sh_uninstall();                                           // v162
    sh_pwr_lock(0);                                           // v182: symmetric UnlockMainPower
    slog("v182 shell end: %s", (unsigned)sh_l2, 0);
    sh_hud_clear(); sh_hud(1); msleep(1000);
    if (pv_ok()) { unsigned y; for (y = 0; y < 240; y++) memset(PV_RGBA + y * PV_BW, 0, PV_BW * 4); vid_bitmap_refresh(); }
    if (osd_saved >= 0) conf.show_osd = osd_saved;
    { unsigned t = get_tick_count(); while (kbd_is_key_pressed(KEY_MENU) && get_tick_count() - t < 3000) msleep(20); }   // v184c: no PressMenuButton leak
    sh_quit = 1;
    sh_on = 0;                                                // sh_kbd() now returns 0: keys go back to Canon
    if (sh_prev_gui && camera_info.state.gui_mode == GUI_MODE_MODULE) gui_set_mode(sh_prev_gui);
    exit_alt();                                               // v176: leave CHDK ALT (kbd_blocked) -> Canon gets every key
    { int fe = open("A/M10SH.END", O_WRONLY | O_CREAT | O_TRUNC, 0777); if (fe >= 0) { write(fe, "1\n", 2); close(fe); } }   // fallback marker for legacy Lua
    sh_quit_req = 0;
    task_running = 0;
    ExitTask();
}
// v160: key watcher used during a take (lv_x3 runs in the shell task)
static void sh_keywatch_task(void)
{
    for (;;) {
        if (!sh_on) break;
        {   // v176: MENU held 1 s = quit (not during a take); SET/REC ignored while MENU is down
            static unsigned t_menu = 0;
            if (kbd_is_key_pressed(KEY_MENU)) { if (!t_menu) t_menu = get_tick_count(); else if (!sh_rec_on && get_tick_count() - t_menu > 1000) sh_quit_req = 1; }
            else t_menu = 0;
        }
        if (((sh_key_down() && !kbd_is_key_pressed(KEY_MENU)) || (sh_rec_on && sh_usb())) && !sh_stop_req) { sh_stop_req = 1; }   // v162: USB ends the take
        {   // v184a: half-press rising edge = 4:3 <-> 1:1 view toggle (ImgMode 1, standby and REC; Canon AF dip removed)
            static unsigned hp_prev = 0;
            unsigned hp = kbd_is_key_pressed(KEY_SHOOT_HALF) ? 1 : 0;
            if (hp && !hp_prev && sh_is_m1() && (sh_pv || sh_rec_on) && !kbd_is_key_pressed(KEY_MENU) && !kbd_is_key_pressed(KEY_SET) && pv_mode != 2) {
                pv_mode = (pv_mode == 1) ? 0 : 1;
                pv_hud_dirty = 1;
            }
            hp_prev = hp;
        }
        if (sh_rec_on) sh_gui_assert();                       // v161: keep REC away from Canon during a take
        if (sh_rec_on && sh_prof()->kind != SH_X3) {          // v175: whole HUD redrawn at 1 Hz during a take (v178e: not in 1x3; v182: also restores opaque mask in ImgMode 1)
            static unsigned last = 0xffffffff, wiped = 0;
            unsigned sec = (get_tick_count() - sh_rec_t0) / 1000;
            if (sec != last || pv_hud_dirty) {               // v184a: + immediate redraw after a view toggle
                pv_hud_dirty = 0;
                if (sh_m1_wide() && pv_ok()) pv_m1_mask(0);   // v185: Wide letterbox repaint on 0<->1
                last = sec;
                if (pv_ok() && PV_RGBA[1 * PV_BW + 100] == 0 && wiped < 4) { wiped++; slog("v175 HUD wiped in RAM at %ds (n=%d)", sec, wiped); }   // erased vs not composited
                if (sh_is_m1() && pv_ok() && ((sh_m1_wide() && pv_mode == 1) ? PV_RGBA[1 * PV_BW + 358] != PV_BLACK : PV_RGBA[21 * PV_BW + 358] != PV_BLACK))
                    pv_m1_mask(pv_mode == 2);                 // v185b: mask corner (21, 358) / Wide focus: top HUD bar (1, 358)
                sh_hud(1);                                    // redraw + vid_bitmap_refresh
            }
        }
        msleep(30);
    }
    ExitTask();
}

int _run()
{
    running = 1;
    if (!task_running) {                         // v160: shell mode when A/M10SH.CFG exists
        int fs = open("A/M10SH.CFG", O_RDONLY, 0777);
        if (fs >= 0) {
            close(fs);
            task_running = 1; sh_quit = 0;
            sh_say("M10 CINE", "installation");
            CreateTask("M10Shell", 0x1A, 0x2000, shell_task);   // v182: 8 KiB stack
            CreateTask("M10Key", 0x1D, 0x1000, sh_keywatch_task);   // v175: 4 KiB (draws the full HUD during REC)
            running = 0;                                      // return at once (called from the autostart script); the
            return 0;                                         // module stays loaded while task_running. Keys are kept
                                                              // from Canon by the script's ALT mode (kbd_blocked).
        }
    }
    if (!task_running && ts_pinned) { strcpy(msg, "TSK pinned: do not reload"); running = 0; return -1; }
    if (!task_running) {
        int fa = open("A/M10RUN.ASY", O_RDONLY, 0777);   // v181c: async run for the stand-alone Lua script:
        if (fa >= 0) {                                    // blocking here would freeze the kbd task (no key
            close(fa); remove("A/M10RUN.ASY"); remove("A/M10X3.END");   // state -> REC deaf to STOP, r159)
            run_async = 1; task_running = 1;
            CreateTask("M10Cine", 0x1A, 0x2000, cine_task);   // v182: 8 KiB stack
            running = 0;
            return 0;                                     // stays loaded while task_running (_module_can_unload)
        }
        task_running = 1;
        CreateTask("M10Cine", 0x1A, 0x2000, cine_task);       // v182: 8 KiB stack
    }
    while (task_running) msleep(50);
    draw_string(10, 40, msg, MAKE_COLOR(COLOR_BLACK, COLOR_WHITE));
    { unsigned w; for (w = 0; w < (x_m1 ? 4 : 80); w++) { msleep(50); if (x_m1) wb_mon(0); } }
    running = 0;
    return 0;
}

int _module_can_unload() { return running == 0 && !task_running && !wb_wd_on && pv_rec_done && pv_stby_done && !ts_pending && !ts_busy && !ts_pinned; }
int _module_exit_alt() { if (!task_running && !wb_wd_on && pv_rec_done && pv_stby_done && !ts_pending && !ts_busy && !ts_pinned) running = 0; return 0; }

libsimple_sym _librun = { { 0, 0, _module_can_unload, _module_exit_alt, _run } };

ModuleInfo _module_info =
{
    MODULEINFO_V1_MAGICNUM,
    sizeof(ModuleInfo),
    SIMPLE_MODULE_VERSION,
    ANY_CHDK_BRANCH, 0, OPT_ARCHITECTURE,
    ANY_PLATFORM_ALLOWED,
    (int32_t)"M10 Cine RAW",
    MTYPE_TOOL,
    &_librun.base,
    ANY_VERSION,
    ANY_VERSION,
    ANY_VERSION,
    ANY_VERSION,
    0,
};
