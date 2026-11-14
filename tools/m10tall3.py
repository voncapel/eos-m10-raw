#!/usr/bin/env python3
"""Taller FHD 1x3 readout (live103): Film commit with a coherent head height H.

    m10tall3.py H [c7=0x2c0] [nohiv] [notg] [nocmos] [keep]     e.g. m10tall3.py 1254
    options: watch=S wbkick rearm (count head errors in LV) dfe [dfe2] [no8197] (hook v6) cleartg sdump
             eXXXXX=VAL (forced engine write) rec=N fl=.. lines=.. tag=..
    m10tall3.py restore                                          undo everything, clean Film

Recipe from notes/head_height_deps.md (unicorn emulation of the Film commit):
  - Extract record of Film (slot *(0x2cd24+4*7), ROM 0xfc72f34c) copied to RAM,
    +0x10/+0x18/+0x28 = H  -> Canon writes 6800/6804 and 72c0 = H+2,
  - ImgSens size cache 0x575b0, modes 34 AND 36: +4/+12 = H
    -> FldCreat (08184, 373e8/f4, 37a70/ad0/b8c, 450a4 = 3H-3) and DirectSS (c0f42xxx),
  - HivShd offset [0xfc3c] = 1190 - H -> c0f04a10 = 2H (DMA starts 2(H-1190) bytes early),
  - TG (hook, Gray, conditional on Canon's Film values): 800c = 0, 8172/8178/82f8 = H+3,
    82b6 = H+1,
  - CMOS 7 (hook, steady state): vertical window end opened (default 0x2c0).
Then M -> VIDEO_STD, watch the TG 4 s, dump the height-carrying registers.
'keep' leaves the state for a capture (m10x3raw.py with NOMODE=1 NOCLEAN=1).
Output: captures/live103/tall3_<tag>.txt (+ .sio if the TG dies)
"""
import os, sys, time, struct
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10auto

OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live103')
TAB, SLOT, REC = 0x2cd24, 7, 0xfc72f34c
CACHE, CMODES, H0 = 0x575b0, (34, 36), 1190
HIVOFF = 0xfc3c
FN_MALLOC = 0xfc38d3f1
# (register, shift, expected offset from H)  -- notes/head_height_deps.md section 2
HREGS = [(0xc0f06804, 16, 0), (0xc0f072c0, 0, 2), (0xc0f08184, 0, -1), (0xc0f373e8, 16, -1),
         (0xc0f373f4, 16, 0), (0xc0f37a70, 16, -1), (0xc0f37ad0, 16, -1), (0xc0f37b8c, 16, -1),
         (0xc0f42014, 16, -1), (0xc0f42918, 16, -1), (0xc0f4292c, 16, 3), (0xc0f42938, 16, -1),
         (0xc0f42948, 16, 0), (0xc0f42950, 16, -1), (0xc0f4296c, 16, -1), (0xc0f42980, 16, 0),
         (0xc0f42994, 16, -1), (0xc0f09008, 16, -1), (0xc0f09034, 16, -2), (0xc0f10064, 16, -1)]
FIXED = (0xc0f35088, 0xc0f450a4, 0xc0f04a10, 0xc0f04a08)


def gray(n):
    return n ^ (n >> 1)


def hdump(c, say, h):
    out, bad = [], []
    for r, sh, d in HREGS:
        v = ((c.shadow(r) >> sh) & 0xffff) - d
        out.append('%05x:%d' % (r & 0xfffff, v))
        if v != h:
            bad.append('%05x' % (r & 0xfffff))
    say('hregs  ' + ' '.join(out))
    say('other  ' + ' '.join('%05x=%08x' % (r & 0xfffff, c.shadow(r)) for r in FIXED))
    say('not at H=%d: %s' % (h, ' '.join(bad) or '-'))


def restore(c, k, say, recommit=True):
    c.poke(TAB + 4 * SLOT, REC)
    for m in CMODES:
        c.poke(CACHE + 36 * m + 4, H0)
        c.poke(CACHE + 36 * m + 12, H0)
    c.poke(HIVOFF, 0)
    m10sio.clear_overrides(k)
    say('restored extract/cache/hiv, ' + m10sio.over_state(k))
    if recommit:
        say('mode M: %s' % m10auto.setmode(c, 'M'))
        say('mode VIDEO_STD: %s' % m10auto.setmode(c, 'VIDEO_STD', 1500))
        say('clean  ' + m10auto.fmt(m10auto.state(c, k)))


def main(a):
    os.makedirs(OUT, exist_ok=True)
    c = Cam(timeout=int(os.environ.get("USBTMO", "600000")))
    k = m10sio.find(c)
    assert k is not None and k.magic in m10sio.MTAB, 'needs the SIO hook (v4+)'
    if a and a[0] == 'restore':
        restore(c, k, print)
        c.close()
        return
    h = int(a[0], 0)
    opt = dict(x.split('=', 1) for x in a[1:] if '=' in x)
    c7 = int(opt.get('c7', '0x2c0'), 0)
    use_hiv, use_tg, use_cmos, keep = 'nohiv' not in a, 'notg' not in a, 'nocmos' not in a, 'keep' in a
    tag = 'H%d_c7-%03x' % (h, c7) + ('_nohiv' if not use_hiv else '') + ('_notg' if not use_tg else '') + ('_nocmos' if not use_cmos else '')
    log = open(os.path.join(OUT, 'tall3_%s.txt' % tag), 'w')
    say = lambda s: (print(s), log.write(s + '\n'), log.flush())
    say('tall3 %s  vbatt %s' % (tag, c.lua('return get_vbatt()')))
    m10sio.clear_overrides(k)
    if c.peek(0xe664)[0] != 3:          # live104 (r104f): LV asleep (tg = 1) -> the commit dies; wake it first
        c.lua('press("shoot_half") sleep(800) release("shoot_half") sleep(1500)')
        say('LV was asleep, half-press -> tg=%x' % c.peek(0xe664)[0])
        assert c.peek(0xe664)[0] == 3, 'live view does not wake'
    if c.peek(0xfa80)[0] == 0xfc1ee9a9:
        # live104 (r104j): an LV sleep/wake puts Canon's callback back; without the trap the first
        # head error at H != 1190 is fatal.  Install it here (same stub as m10hetrap.py install).
        import m10hetrap
        mem = c.call(FN_MALLOC, len(m10hetrap.STUB) + 16)
        sb_ = (mem + 7) & ~7
        c.write(sb_, m10hetrap.STUB)
        c.call(m10sio.FN_DCLEAN, sb_, len(m10hetrap.STUB))
        c.call(m10sio.FN_IINVAL, sb_, len(m10hetrap.STUB))
        assert c.read(sb_, len(m10hetrap.STUB), buffered=False) == m10hetrap.STUB
        k.poke(0xfa80, (sb_ + 0x10) | 1)
        c.poke(0xfa84, 0)
        say('trap   reinstalled at %08x, [0xfa80]=%08x' % (sb_, c.peek(0xfa80)[0]))
        assert c.peek(0xfa80)[0] == (sb_ + 0x10) | 1
    say('mode M: %s' % m10auto.setmode(c, 'M'))
    assert c.peek(TAB + 4 * SLOT)[0] == REC, 'Extract slot 7 already redirected (run restore)'
    for m in CMODES:
        assert c.peek(CACHE + 36 * m + 4)[0] == H0, ('cache', m, c.peek(CACHE + 36 * m, 4))
    rec = bytearray(c.read(REC, 0x68))
    assert struct.unpack_from('<I', rec, 0x28)[0] == H0
    for off in (0x10, 0x18, 0x28):
        struct.pack_into('<I', rec, off, h)
    buf = c.call(FN_MALLOC, 0x80)
    c.write(buf, bytes(rec))
    assert c.read(buf, 0x68) == bytes(rec)
    tab = [(0x800c, 0)]
    if use_tg:
        tab += [(r, gray(h + 3), gray(H0 + 3)) for r in (0x8172, 0x8178, 0x82f8)] + \
               [(0x82b6, gray(h + 1), gray(H0 + 1))]
    if 'dfe' in a:
        # live104: the sensor/TG frame is 8196 + 8197 = 119 + 1099 = 1218 lines (= H0 + 28) and the DFE
        # blanks rows beyond 88c6/88ce = H0 - 2: move every Film line counter by H - H0 (hook v5/v6).
        assert k.magic in (m10sio.M5, m10sio.M6), 'dfe needs hook v5/v6 (m10sio.py swap6)'
        dh = h - H0
        tab += [(0x88c6, 0x4a4 + dh, 0x4a4), (0x88ce, 0x4a4 + dh, 0x4a4)]
        if 'dfe2' not in a:
            tab += [(0x88d7, 0x44b + dh, 0x44b), (0x8a54, 0x44a + dh, 0x44a), (0x8ab5, 0x44a + dh, 0x44a)]
    if 'f8197' in a or ('dfe' in a and 'no8197' not in a):
        # live104 (r104b): frames end at row 1218 = 8196 + 8197 (119 + 1099, Gray) -> the head never gets
        # its 1254 lines (error bit 6 every frame).  8197 is a TG register: hook v4 is enough.
        tab += [(0x8197, gray(1099 + h - H0 + int(opt.get('x8197', 0))), 0x66e)]
    if 'tgv' in opt:
        # live104: tgv=82b6:901,8178:903 (TG, value Gray-coded here) / tgv=d88c6:900 (DFE, raw, hook v6):
        # replace single commit-time values, to find which register gates the valid rows.
        for x in opt['tgv'].split(','):
            r, v = x.split(':')
            dfe = r.startswith('d')
            reg, val = int(r.lstrip('d'), 16), int(v, 0)
            tab = [e for e in tab if e[0] != reg] + [(reg, val if dfe else gray(val))]
    alive = True
    pend = []
    hivsave = None
    early = None
    try:
        c.poke(TAB + 4 * SLOT, buf)
        for m in CMODES:
            c.poke(CACHE + 36 * m + 4, h)
            c.poke(CACHE + 36 * m + 12, h)
        m10sio.set_tg_table(k, tab)
        if use_cmos:
            k.poke(k.b + k.cmos + 4 * 7, 0x10000 | (c7 & 0xfff))
            k.set_h(20, 1)
        say('armed  ' + m10sio.over_state(k))
        t0 = time.time()
        if use_hiv and h != H0:
            # live103: HivShd is re-read every frame and its size must be 2 x the CURRENT head
            # height (r103: offset posed in Photo -> 727-line head with a 1582-byte table ->
            # TG -1 before the commit).  Start the commit asynchronously and pose the offset
            # as soon as the head shows H.
            c.chdk(7, [0], b'capmode=require"capmode" capmode.set("VIDEO_STD")\0')
            thiv = None
            while time.time() - t0 < 4:
                if (c.shadow(0xc0f06804) >> 16) == h:
                    c.poke(HIVOFF, (H0 - h) & 0xffffffff)
                    thiv = time.time() - t0
                    break
            time.sleep(max(0.0, 1.0 - (time.time() - t0)))
            early = m10sio.read_ring(k)
            say('hiv    offset %d posed at %s ms, idx=%d 4a10=%08x' % (H0 - h, thiv and int(thiv * 1000),
                c.peek(0xfbac + 0x2c)[0], c.shadow(0xc0f04a10)))
            time.sleep(1.5)
            say('mode   %s' % c.lua('return get_mode()'))
            if 'hivfill' in a and thiv is not None and h > H0:
                # live104 (r104b): the table is 8 bytes/line (40 00 00 00 x2) and the DMA now starts
                # 8 x (H - H0) bytes before it, in never-written RAM -> rows 0-63 lose their black level.
                # Fill that gap with the table's own pattern (uncached alias), put the bytes back at restore.
                a8, nb = c.shadow(0xc0f04a08), 8 * (h - H0)
                pat = c.read(a8 + nb, 8)
                if pat == bytes.fromhex('4000000040000000'):
                    hivsave = (a8, c.read(a8, nb))
                    c.write(0x40000000 | a8, pat * (h - H0))
                    say('hivfill %08x + %d bytes (table at %08x), readback %s' % (a8, nb, a8 + nb, c.read(0x40000000 | a8, 8).hex()))
                else:
                    say('hivfill skipped: table head %s at %08x' % (pat.hex(), a8 + nb))
        else:
            # live106: async commit + ring read at ~1 s (the 4096-entry ring only holds ~1.6 s:
            # with the blocking setmode the commit writes had already left it)
            c.chdk(7, [0], b'capmode=require"capmode" capmode.set("VIDEO_STD")\0')
            time.sleep(1.0)
            early = m10sio.read_ring(k)
            time.sleep(0.9)
            say('mode   %s' % c.lua('return get_mode()'))
        say('commit %.1f s  %s  800c_hits=%d' % (time.time() - t0, m10auto.fmt(m10auto.state(c, k)), k.h(40)))
        hdump(c, say, h)
        # live103: which TG addr/data pairs did the commit send (was 800c really 0?)
        idx, ents = early if early else m10sio.read_ring(k)
        m10sio.save(os.path.join(OUT, 'tall3_%s_commit.sio' % tag), idx, ents)
        tgw, pend_a = [], None
        for e in ents:
            if e[2] != 4:
                continue
            if e[5] == 0xfc231323:
                pend_a = e[6] & 0xffff
            elif e[5] == 0xfc23132d and pend_a is not None:
                if pend_a in (0x800c, 0x8172, 0x8178, 0x82f8, 0x82b6, 0x8000):
                    tgw.append('%04x=%x' % (pend_a, e[6] & 0xffff))
                pend_a = None
        say('tgsent ' + ' '.join(tgw[-24:]))
        t1 = time.time()
        tg = None
        trap = c.peek(0xfa80)[0]
        tb = (trap & ~1) - 0x10 if trap != 0xfc1ee9a9 else None
        wsecs = float(opt.get('watch', 4))
        for x in a:              # live103: forced engine writes after the commit, e.g. e35088=0x4e6
            if x.startswith('e') and '=' in x and x[1:x.index('=')].strip('0123456789abcdef') == '':
                r, v = int(x[1:x.index('=')], 16) | 0xc0f00000, int(x[x.index('=') + 1:], 0)
                old = c.shadow(r)
                c.call(0xfc38d28b, r, v)
                say('eng    %08x %08x -> %08x (now %08x)' % (r, old, v, c.shadow(r)))
        if 'fix9034' in a:       # live103: WBInteg table leaves c0f09034 at 1190-2 while 09008 follows H
            v = c.shadow(0xc0f09034)
            nv = (v & 0xffff) | ((h - 2) << 16)
            c.call(0xfc38d28b, 0xc0f09034, nv)
            say('fix    c0f09034 %08x -> %08x (now %08x)' % (v, nv, c.shadow(0xc0f09034)))
        if 'sdump' in a:         # live103: whole EngDrv shadow, to diff against shadow_1190.bin
            sb = c.peek(0x28dbc)[0]
            open(os.path.join(OUT, 'tall3_%s_shadow.bin' % tag), 'wb').write(c.read(sb, 0x80000))
            say('sdump  tall3_%s_shadow.bin' % tag)
        trace = []
        wbl, wbt, kicks, rearms = None, time.time(), 0, 0
        # live107: fresh count per run.  [0xfa84] and the stub counters were stale from the previous run
        # (H = 1219-1221: one error during the mode transition, none afterwards, read as "n constant").
        nstart = c.peek(tb)[0] if tb else 0
        say('masks  72c8/cc/d0/d4 = %s  [0xfa84]=%x  stub n=%d (errors before the watch)' % (
            ' '.join('%x' % c.shadow(r) for r in (0xc0f072c8, 0xc0f072cc, 0xc0f072d0, 0xc0f072d4)), c.peek(0xfa84)[0], nstart))
        c.poke(0xfa84, 0)
        while time.time() - t1 < wsecs:
            tg = c.peek(0xe664)[0]
            n = c.peek(tb, 3) if tb else (0, 0, 0)
            wb = c.peek(0xc6f0 + 0x58, 2)
            if wb != wbl:
                wbl, wbt = wb, time.time()
            elif 'wbkick' in a and time.time() - wbt > 0.4:
                c.call(0xfc314c94, c.peek(0xc6f0 + 0x20)[0], 0x20050)   # j_SetEventFlag (ARM thunk)
                kicks += 1; wbt = time.time()
            if 'rearm' in a and tb and c.shadow(0xc0f072d0) == 0:
                # live104: Head.c's handler clears the cause masks at the 1st error, so later frames
                # fail silently.  Re-arm them (as Extract 0xfc157280) and count: n grows = frames broken.
                c.poke(0xfa84, 0)
                for r, v in ((0xc0f072c8, 0x20), (0xc0f072cc, 0x20), (0xc0f072d0, 0x40), (0xc0f072d4, 0x40)):
                    c.call(0xfc38d28b, r, v)
                rearms += 1
            trace.append('%.1f:n%d/%x/wb%04x,%04x' % (time.time() - t1, n[0], n[1], wb[0] & 0xffff, wb[1] & 0xffff))
            if tg == 0xffffffff:
                break
            time.sleep(0.2)
        say('watch  ' + ' '.join(trace) + ' kicks=%d rearms=%d' % (kicks, rearms))
        say('errors during the watch: %d (stub n %d -> %d), masks now %s' % (
            (c.peek(tb)[0] - nstart) if tb else -1, nstart, c.peek(tb)[0] if tb else -1,
            ' '.join('%x' % c.shadow(r) for r in (0xc0f072c8, 0xc0f072cc, 0xc0f072d0, 0xc0f072d4))))
        if 'sweep' in opt and tb and tg != 0xffffffff:
            # live104: in-place sweep, no re-commit.  sweep=7:0x280,0x2c0,...  (CMOS reg 7) or
            # sweep=t8172:0x69d,...  (per-frame TG register, raw value).  For each value: pose it in the
            # hook table, let 0.4 s pass, re-arm the head-error masks, count trapped errors over 0.8 s
            # (20 frames).  0 error = the source now delivers at least H + 1 lines.
            what, vals = opt['sweep'].split(':')
            def rearm():
                c.poke(0xfa84, 0)
                for r, v in ((0xc0f072c8, 0x20), (0xc0f072cc, 0x20), (0xc0f072d0, 0x40), (0xc0f072d4, 0x40)):
                    c.call(0xfc38d28b, r, v)
            for v in [int(x, 0) for x in vals.split(',')] + [c7]:
                if what.startswith('t'):
                    reg = int(what[1:], 16)
                    m10sio.set_tg_table(k, [e for e in tab if e[0] != reg] + [(reg, v)])
                else:
                    k.poke(k.b + k.cmos + 4 * int(what, 0), 0x10000 | (v & 0xfff))
                time.sleep(0.4)
                res = []
                for rep in range(4):
                    rearm()
                    n0 = c.peek(tb)[0]
                    time.sleep(0.2)
                    res.append('%d/%x' % (c.peek(tb)[0] - n0, c.peek(0xfa84)[0]))
                    c.call(0xfc314c94, c.peek(0xc6f0 + 0x20)[0], 0x20050)
                tg = c.peek(0xe664)[0]
                say('sweep  %s=%03x  errors/status per 0.2 s: %s  tg=%x' % (what, v, ' '.join(res), tg))
                if tg == 0xffffffff:
                    break
        s = m10auto.state(c, k)
        say('t+4s   ' + m10auto.fmt(s) + ' headerr=[0xfa84]=%x' % c.peek(0xfa84)[0])
        if s['tg'] == 0xffffffff:
            alive = False
            say('TG task in error (camera will shut down)')
            idx, ents = m10sio.read_ring(k)
            m10sio.save(os.path.join(OUT, 'tall3_%s.sio' % tag), idx, ents)
        else:
            if 'cleartg' in a:                  # live104: 8172/8173 are re-sent EVERY frame -> keep the table by default
                m10sio.set_tg_table(k, [])
            say('ALIVE  ' + m10sio.over_state(k))
            if 'probe' in opt:
                # live104: probe=7:0x2c0,0x340/8:0x000/t8172:0x0 -> for each value: pose it (CMOS reg in the
                # hook table, or per-frame TG reg), 1 isolated pass (HEAD output by default), fetch and
                # measure: last row before the 852 fill (frame end), first flat row (no sensor data).
                import numpy as np, m10lvx3dec as D
                name = c.call(FN_MALLOC, 32)
                c.write(name, b'm10cine.flt\0')
                L = int(opt.get('lines', h - 6))
                def kick():
                    c.call(0xfc314c94, c.peek(0xc6f0 + 0x20)[0], 0x20050)
                def one(label):
                    for rep in range(4):        # r104: 2 passes out of 3 stop after ~36 rows (lottery) -> retry
                        ok1, end1 = one1(label)
                        if not ok1 or end1 > 100:
                            break
                    return ok1
                def one1(label):
                    end = 0
                    cfg = '1 %d 10 0 500 %d 0 %s 5000 7500 6 0 0 12 4 99\n' % (L, 0x20000000, opt.get('xo', '88000001'))
                    open('/tmp/M10X3.CFG', 'w').write(cfg)
                    c.upload('/tmp/M10X3.CFG', 'A/M10X3.CFG'); kick()
                    n0 = c.peek(tb)[0] if tb else 0
                    r = c.call(0x3e8c71, name); kick()
                    fn = os.path.join(OUT, '%s_%s_LVX3.BIN' % (opt.get('tag', 'probe'), label))
                    c.download('A/LVX3.BIN', fn); kick()
                    d = open(fn, 'rb').read()
                    w, lines, lb, npass, ndone = D.header(d); bpp = lb * 8 // w
                    res = 'no pass'
                    if r == 0 and ndone:
                        img = D.decode(d[D.HDR:D.HDR + lines * lb], bpp, w, lines, lb, 0).astype(np.float32)
                        ob, sd = img[:, :72].mean(1), img[:, 200:1700].std(1)
                        fill = np.nonzero(np.abs(ob - 852.5) < 1)[0]
                        end = int(fill.min()) if len(fill) else lines
                        tex = np.nonzero(sd[:end] > 3)[0]
                        flat = [int(x) for x in np.nonzero(sd[:end] < 0.6)[0] if x > 100]
                        res = 'frame end %d, image rows %s..%s, first flat row %s (%d flat), OB top %.0f mid %.0f, mean %.0f' % (
                            end, tex.min() if len(tex) else '-', tex.max() if len(tex) else '-',
                            flat[0] if flat else '-', len(flat), ob[:20].mean(), ob[min(600, max(end - 1, 0))], img[40:max(end, 41), 200:1700].mean())
                    say('probe  %-12s run=%d trap+%d tg=%x : %s' % (label, r & 0xffffffff, (c.peek(tb)[0] - n0) if tb else 0, c.peek(0xe664)[0], res))
                    return (c.peek(0xe664)[0] != 0xffffffff and r == 0), end
                ok = one('ref')
                for spec in opt['probe'].split('/'):
                    if not ok:
                        break
                    what, vals = spec.split(':')
                    for v in [int(x, 0) for x in vals.split(',')]:
                        if what.startswith('c'):         # live107: cB:0x34a = CMOS reg 0xB sent directly
                            # Canon only ever sends CMOS 0-9 (ROM tables 0xfc72ee50), so the hook cannot rewrite
                            # A-F: call CMOSAccs 0xfc1bebfa(reg, val) itself.  The value stays in the sensor
                            # until power-off (Canon never re-sends these registers).
                            c.call(0xfc1bebfb, int(what[1:], 16), v & 0xfff)
                        elif what.startswith('tg'):      # tgXXXX:N = TG register, N Gray-coded
                            m10sio.set_tg_table(k, [e for e in tab if e[0] != int(what[2:], 16)] + [(int(what[2:], 16), gray(v))])
                        elif what.startswith('t'):
                            m10sio.set_tg_table(k, [e for e in tab if e[0] != int(what[1:], 16)] + [(int(what[1:], 16), v)])
                        else:
                            k.poke(k.b + k.cmos + 4 * int(what, 0), 0x10000 | (v & 0xfff))
                        time.sleep(0.3); kick()
                        ok = one('%s-%03x' % (what, v))
                        if not ok:
                            break
                    if what.startswith('c'):
                        pass                             # direct CMOS write: no known value to restore
                    elif what.startswith('t'):
                        m10sio.set_tg_table(k, tab)
                    else:
                        k.poke(k.b + k.cmos + 4 * int(what, 0), (0x10000 | (c7 & 0xfff)) if int(what, 0) == 7 else 0)
                    time.sleep(0.3)
                alive = c.peek(0xe664)[0] != 0xffffffff
            if 'rec' in opt:
                # live103: run the module from this same process, WB kicked until the call
                # (a 3 s gap without kicks = WBInteg 3491, r103i).  v89s kicks inside REC.
                n, L = int(opt['rec']), int(opt.get('lines', h - 6))
                fl = int(opt.get('fl', '0x21800980'), 0)
                cfg = '%d %d 10 0 %d %d 0 %s 5000 7500 6 0 0 12 4 99\n' % (n, L, 0 if fl & 0x100 else 500, fl, opt.get('xo', '80000001'))   # fl: decimal (m10x3raw format)
                name = c.call(FN_MALLOC, 32)
                c.write(name, b'm10cine.flt\0')
                c.write(name + 16, b'A/M10X3.CFG\0')
                open('/tmp/M10X3.CFG', 'w').write(cfg)
                c.upload('/tmp/M10X3.CFG', 'A/M10X3.CFG')
                c.call(0xfc314c94, c.peek(0xc6f0 + 0x20)[0], 0x20050)
                say('rec    cfg %s' % cfg.strip())
                t2 = time.time()
                try:
                    r = c.call(0x3e8c71, name)
                    say('module_run -> %d (%.1f s) tg=%x' % (r, time.time() - t2, c.peek(0xe664)[0]))
                except Exception as e:
                    alive = False
                    say('module_run failed after %.1f s: %r' % (time.time() - t2, e))
                if alive:
                    pend.extend(('M10CINE.LOG', 'LVX3S.BIN', 'LVX3.BIN') if not fl & 0x100 else ('M10CINE.LOG', 'LVX3S.BIN', 'M10X3.MLV'))
    except Exception as e:
        alive = False
        say('exception (camera off?): %r' % e)
    finally:
        if alive and not keep:
            restore(c, k, say)
            if hivsave:
                c.write(0x40000000 | hivsave[0], hivsave[1])
                say('hivfill bytes restored at %08x' % hivsave[0])
    if alive and pend:          # after the clean Film re-commit (WBInteg fed again)
        tag2 = opt.get('tag', 'r103_' + tag)
        for f in pend:
            try:
                c.download('A/' + f, os.path.join(OUT, '%s_%s' % (tag2, f)))
            except Exception as e:
                say('no %s (%r)' % (f, e))
        say('got    %s_* in %s' % (tag2, OUT))
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
