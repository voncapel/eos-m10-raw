#!/usr/bin/env python3
"""live105: can the head be made taller in zoom x5 (the only Canon mode that reads every line)?

    m10zoomtall.py DH [wait=S] [watch=N] [sdump] [keep]     DH = extra head lines (0 = control run)
    m10zoomtall.py restore

The x5 magnifier cannot be entered by script (touch only): the tool arms everything in photo live
view, then WAITS for the user to tap the magnifier; Canon's own commit then programs the taller zoom.
Armed before the tap (all in RAM, restored at the end):
  - Extract record of the zoom (slot 36 of 0x2cd24, ROM 0xfc72f624: 2592 x 1108, head 1111):
    +0x10/+0x18 = 1108 + DH, +0x28 = 1111 + DH        -> c0f06804, c0f072c0
  - ImgSens size cache 0x575b0, mode 41: +4/+12 = 1108 + DH   -> FldCreat / DirectSS registers
  - per-mode reg/val list in RAM: c0f35088 (0x378f4) = 0x454 + DH
  - TG (hook, Gray, only on Canon's zoom values 0x677 / 0x674): 8172/8178/82f8 = H + 3, 82b6 = H + 1
Nothing else: 800c is already 0 in zoom, CMOS 5/7 are the window position, WBInteg (c0f09008/9034 =
1107/1106 lines, hard table) does not follow and is kicked when stale, HivShd is sized by the width
there (c0f04a10 = 0x2880 = 4 x 2592).
After the tap: height registers, TG values really sent, then the head-error count with the cause
masks re-armed every 0.25 s (Head.c clears them at the 1st error).  0 error = the head gets its
H lines; 1 per re-arm = the sensor still stops early (as in Film at 1254, live104).
  - Optional Still-gating overrides for testing the H>1111 vertical wall (SIO hook v5/v6):
    preset=p1a|p1a512|p1b|p1b512|p1c|p2|p2b|p2c|p3
    tg=REG:VAL[@ORIG],...   raw 16-bit hex TG pairs (ch4, lr 0xfc231323)
    dfe=REG:VAL[@ORIG],...  raw 16-bit hex DFE pairs (ch4, lr 0xfc1bd4e3, v5/v6)
    cmos=REG:VAL,...        12-bit hex CMOS SPI pairs (ch6)
    tgpre=REG:VAL[@RST],... direct TgDrvWAKA write before tap (restored in finally)
    tag=NAME                suffix for zoomtall_H<H>_<NAME>.txt
Output: captures/live105/zoomtall_<tag>.txt (+ _commit.sio, _shadow.bin with sdump)
"""
import os, sys, time, struct
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10auto, m10hetrap

OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live105')
TAB, SLOT, REC = 0x2cd24, 36, 0xfc72f624
CACHE, CMODE = 0x575b0, 41
HIMG, HHEAD = 1108, 1111                 # image lines / head lines of Canon's zoom x5
L35088, V35088 = 0x378f4, 0x454          # RAM list entry (c0f35088, value)
ZFPS_TAB, ZFPS_DRV, ZFPS_ROM = 0x2cdc0, 46, 0xfc73045c
ZOOM6804 = 0x045702a6
FN_MALLOC = 0xfc38d3f1
FN_TG_WRITE = 0xfc231309                 # TgDrvWAKA(reg, val) Thumb entry
CANON_CBR = 0xfc1ee9a9
# (register, shift, offset from the head height) measured on captures/live70/shadow_zoom.bin
HREGS = [(0xc0f06804, 16, 0), (0xc0f072c0, 0, 2), (0xc0f08184, 0, -4), (0xc0f35088, 0, -3),
         (0xc0f373e8, 16, -4), (0xc0f373f4, 16, -3), (0xc0f37a70, 16, -4), (0xc0f37ad0, 16, -4),
         (0xc0f37b8c, 16, -4), (0xc0f42014, 16, -4), (0xc0f42918, 16, -4), (0xc0f4292c, 16, 0),
         (0xc0f42938, 16, -4), (0xc0f42948, 16, -3), (0xc0f42950, 16, -4), (0xc0f4296c, 16, -4),
         (0xc0f42980, 16, -3), (0xc0f42994, 16, -4), (0xc0f450a4, 16, -4)]
OTHER = (0xc0f06800, 0xc0f06008, 0xc0f06014, 0xc0f07050, 0xc0f04a08, 0xc0f04a10, 0xc0f09008, 0xc0f09034)
TG_KNOWN_RST = {0x8008: 0x0f00}
WATCH_CH4 = {0x8000, 0x8008, 0x800c, 0x802c, 0x8047, 0x8079, 0x8170, 0x8172, 0x8173,
             0x8176, 0x8178, 0x8179, 0x8187, 0x82b6, 0x82f3, 0x82f8, 0x82f9,
             0x8826, 0x8840, 0x8860, 0x88c6, 0x88ce}
PRESETS = {
    'p1a':    {'tg': [(0x82f3, 0x0030, 0x000c)], 'dfe': [], 'cmos': []},
    'p1a512': {'tg': [(0x82f3, 0x030a, 0x000c)], 'dfe': [], 'cmos': []},
    'p1b':    {'tg': [(0x82f3, 0x0030, 0x000c), (0x8170, 0x0011, 0x0401), (0x8176, 0x0011, 0x0401)],
               'dfe': [], 'cmos': []},
    'p1b512': {'tg': [(0x82f3, 0x030a, 0x000c), (0x8170, 0x0011, 0x0401), (0x8176, 0x0011, 0x0401)],
               'dfe': [], 'cmos': []},
    'p1c':    {'tg': [(0x82f3, 0x0030, 0x000c), (0x8170, 0x0011, 0x0401), (0x8176, 0x0011, 0x0401),
                      (0x802c, 0x0010), (0x8047, 0x0010), (0x8079, 0x0001)],
               'dfe': [], 'cmos': []},
    'p2':     {'tg': [(0x82f3, 0x0030, 0x000c), (0x8170, 0x0011, 0x0401), (0x8176, 0x0011, 0x0401)],
               'dfe': [(0x8840, 0x0035, 0x001d), (0x8860, 0x000d, 0x000f)], 'cmos': []},
    'p2b':    {'tg': [(0x82f3, 0x0030, 0x000c), (0x8170, 0x0011, 0x0401), (0x8176, 0x0011, 0x0401)],
               'dfe': [(0x8826, 0x2605, 0x0d05), (0x8840, 0x0035, 0x001d), (0x8860, 0x000d, 0x000f)],
               'cmos': []},
    'p2c':    {'tg': [(0x82f3, 0x0030, 0x000c), (0x8170, 0x0011, 0x0401), (0x8176, 0x0011, 0x0401),
                      (0x802c, 0x0010), (0x8047, 0x0010), (0x8079, 0x0001)],
               'dfe': [(0x8826, 0x2605, 0x0d05), (0x8840, 0x0035, 0x001d), (0x8860, 0x000d, 0x000f)],
               'cmos': []},
    'p3':     {'tg': [(0x82f3, 0x0030, 0x000c), (0x8170, 0x0011, 0x0401), (0x8176, 0x0011, 0x0401)],
               'dfe': [(0x8826, 0x2605, 0x0d05), (0x8840, 0x0035, 0x001d), (0x8860, 0x000d, 0x000f)],
               'cmos': [(2, 0x0c6), (3, 0x900), (6, 0x02b)]},
}


def gray(n):
    return n ^ (n >> 1)


def parse_pairs(spec, allow_orig=True):
    """Parse 'REG:VAL[@ORIG],...' with hex register/value numbers."""
    out = []
    for item in (x.strip() for x in spec.split(',') if x.strip()):
        r_s, rest = item.split(':', 1)
        reg = int(r_s, 16)
        if allow_orig and '@' in rest:
            v_s, o_s = rest.split('@', 1)
            out.append((reg, int(v_s, 16), int(o_s, 16)))
        else:
            out.append((reg, int(rest, 16)))
    return out


def dedup_ch4(entries):
    """siohook6 stops on the first matching reg; keep the latest entry per reg."""
    by_reg = {}
    for e in entries:
        by_reg[e[0]] = e
    return list(by_reg.values())


def zfps_info(c):
    p = c.peek(ZFPS_TAB + 4 * ZFPS_DRV)[0]
    rec = c.read(p, 0xd0)
    fl = struct.unpack_from('<H', rec, 0xc)[0]
    per = struct.unpack_from('<I', rec, 0xc8)[0]
    return 'rec46=%08x(%s) fl=%d per=%dus(%.2ffps)' % (
        p, 'ROM' if p == ZFPS_ROM else 'COPY', fl, per, 1e6 / per if per else 0.0)


def summarize_sio(ents, idx0):
    """Return (tgw, dfew, cmosw, seq_str) from captured ring entries."""
    tgw, dfew, cmosw = {}, {}, {}
    pend_tg, pend_dfe, seq, last_c = None, None, [], {}
    for e in ents:
        if e[0] < idx0:
            continue
        ch, lr, d0 = e[2], e[5], e[6]
        if ch == 6 and e[4] == 16:
            r, v = (d0 >> 12) & 0xf, d0 & 0xfff
            cmosw[r] = v
            if last_c.get(r) != v and r in (0, 2, 3, 5, 6, 7):
                seq.append('C%x:%03x' % (r, v))
            last_c[r] = v
        elif ch == 4:
            if lr == 0xfc231323:
                pend_tg = d0 & 0xffff
            elif lr == 0xfc23132d and pend_tg is not None:
                v = d0 & 0xffff
                tgw[pend_tg] = v
                if pend_tg in WATCH_CH4:
                    seq.append('%04x=%x' % (pend_tg, v))
                pend_tg = None
            elif lr == 0xfc1bd4e3:
                pend_dfe = d0 & 0xffff
            elif lr == 0xfc1bd4ed and pend_dfe is not None:
                v = d0 & 0xffff
                dfew[pend_dfe] = v
                if pend_dfe in WATCH_CH4:
                    seq.append('D%04x=%x' % (pend_dfe, v))
                pend_dfe = None
    return tgw, dfew, cmosw, seq


def trap(c, k, say):
    if c.peek(0xfa80)[0] != CANON_CBR:
        return
    mem = c.call(FN_MALLOC, len(m10hetrap.STUB) + 16)
    b = (mem + 7) & ~7
    c.write(b, m10hetrap.STUB)
    c.call(m10sio.FN_DCLEAN, b, len(m10hetrap.STUB))
    c.call(m10sio.FN_IINVAL, b, len(m10hetrap.STUB))
    assert c.read(b, len(m10hetrap.STUB), buffered=False) == m10hetrap.STUB
    k.poke(0xfa80, (b + 0x10) | 1)
    c.poke(0xfa84, 0)
    say('trap   installed at %08x' % b)


def restore(c, k, say):
    c.poke(TAB + 4 * SLOT, REC)
    c.poke(CACHE + 36 * CMODE + 4, HIMG)
    c.poke(CACHE + 36 * CMODE + 12, HIMG)
    if c.peek(L35088)[0] == 0xc0f35088:
        c.poke(L35088 + 4, V35088)
    m10sio.clear_overrides(k)
    say('restored extract/cache/list, ' + m10sio.over_state(k))


def rearm(c):
    c.poke(0xfa84, 0)
    for r, v in ((0xc0f072c8, 0x20), (0xc0f072cc, 0x20), (0xc0f072d0, 0x40), (0xc0f072d4, 0x40)):
        c.call(0xfc38d28b, r, v)


def main(a):
    os.makedirs(OUT, exist_ok=True)
    c = Cam(timeout=int(os.environ.get('USBTMO', '60000')))
    k = m10sio.find(c)
    assert k is not None and k.magic in m10sio.MTAB, 'needs the SIO hook'
    if a and a[0] == 'restore':
        restore(c, k, print)
        if 'nomode' in a:                       # live117: never change the mode over USB (OperTrns.c 649)
            print(m10auto.fmt(m10auto.state(c, k))); return
        print('mode VIDEO_STD: %s' % m10auto.setmode(c, 'VIDEO_STD', 1500))
        print(m10auto.fmt(m10auto.state(c, k)))
        return
    dh = int(a[0], 0)
    opt = dict(x.split('=', 1) for x in a[1:] if '=' in x)
    preset_name = opt.get('preset')
    if preset_name:
        assert preset_name in PRESETS, 'unknown preset %r (valid: %s)' % (preset_name, ','.join(PRESETS))
    h = HHEAD + dh
    suffix = opt.get('tag') or preset_name or ''
    tag = 'H%d%s' % (h, ('_' + suffix) if suffix else '')
    log = open(os.path.join(OUT, 'zoomtall_%s.txt' % tag), 'w')

    def say(s):
        print(s, flush=True)
        log.write(s + '\n')
        log.flush()

    say('zoomtall %s (dh %+d)  vbatt %d' % (tag, dh, struct.unpack('<I', c.lua('return get_vbatt()')[0][2])[0]))
    say('zfps   ' + zfps_info(c))
    m10sio.clear_overrides(k)
    if c.peek(0xe664)[0] != 3:
        c.lua('press("shoot_half") sleep(800) release("shoot_half") sleep(1500)')
    assert c.peek(0xe664)[0] == 3, 'live view is not running'
    trap(c, k, say)
    if (c.shadow(0xc0f06804) & 0xffff) == 0x2a6:        # still in the magnifier: MENU twice leaves it (live105)
        assert 'nomode' not in a, 'in the magnifier: ask the user to leave it first'
        c.lua('click("menu") sleep(900) click("menu") sleep(1500)')
        say('left the magnifier -> 6804=%08x' % c.shadow(0xc0f06804))
    h0 = c.shadow(0xc0f06804)
    assert h0 != ZOOM6804 and (h0 >> 16) != h, 'already in zoom: leave the magnifier first (%08x)' % h0
    assert c.peek(TAB + 4 * SLOT)[0] == REC, 'Extract slot 36 already redirected (run restore)'
    assert c.peek(CACHE + 36 * CMODE, 4) == [2592, HIMG, 2592, HIMG], c.peek(CACHE + 36 * CMODE, 4)
    assert c.peek(L35088, 2) == [0xc0f35088, V35088], ['%x' % x for x in c.peek(L35088, 2)]
    rec = bytearray(c.read(REC, 0x68))
    assert struct.unpack_from('<I', rec, 0x28)[0] == HHEAD and struct.unpack_from('<I', rec, 0x10)[0] == HIMG
    tab, dfe_entries, cmos_entries, tgpre_entries = [], [], [], []
    if dh:
        struct.pack_into('<I', rec, 0x10, HIMG + dh)
        struct.pack_into('<I', rec, 0x18, HIMG + dh)
        struct.pack_into('<I', rec, 0x28, h)
        buf = c.call(FN_MALLOC, 0x80)
        c.write(buf, bytes(rec))
        assert c.read(buf, 0x68) == bytes(rec)
        tab = [(r, gray(h + 3), gray(HHEAD + 3)) for r in (0x8172, 0x8178, 0x82f8)] + \
              [(0x82b6, gray(h + 1), gray(HHEAD + 1))]
        c.poke(TAB + 4 * SLOT, buf)
        c.poke(CACHE + 36 * CMODE + 4, HIMG + dh)
        c.poke(CACHE + 36 * CMODE + 12, HIMG + dh)
        c.poke(L35088 + 4, V35088 + dh)
    if preset_name:
        p = PRESETS[preset_name]
        tab += p['tg']
        dfe_entries += p['dfe']
        cmos_entries += p['cmos']
    if 'tg' in opt:
        tab += parse_pairs(opt['tg'], allow_orig=True)
    if 'dfe' in opt:
        dfe_entries += parse_pairs(opt['dfe'], allow_orig=True)
    if 'cmos' in opt:
        cmos_entries += parse_pairs(opt['cmos'], allow_orig=False)
    if 'tgpre' in opt:
        tgpre_entries += parse_pairs(opt['tgpre'], allow_orig=True)
    if dfe_entries:
        assert k.magic in (m10sio.M5, m10sio.M6), 'dfe overrides require SIO hook v5/v6'
        tab += dfe_entries
    tab = dedup_ch4(tab)
    if tab:
        m10sio.set_tg_table(k, tab)
    def arm_cmos():
        for r, v in cmos_entries:
            assert 0 <= r < 16, 'invalid CMOS reg %d' % r
            k.poke(k.b + k.cmos + 4 * r, 0x10000 | (v & 0xfff))
        k.set_h(20, 1)
    # live123: arming the CMOS table before the tap rewrote the photo live view (5280-column Still
    # profile sent to the 727-line LV) and froze the camera.  Default: arm only once the zoom is seen
    # (cmosearly = old behaviour: armed before the tap, also hits Canon's zoom commit frames).
    if cmos_entries and 'cmosearly' in a:
        arm_cmos()
    tgpre_rst = []
    if tgpre_entries:
        for e in tgpre_entries:
            reg, val = e[0], e[1]
            rst = e[2] if len(e) > 2 else TG_KNOWN_RST.get(reg)
            c.call(FN_TG_WRITE, reg, val)
            if rst is not None:
                tgpre_rst.append((reg, rst))
        say('tgpre  ' + ' '.join('%04x=%04x(rst=%s)' % (
            e[0], e[1], ('%04x' % (e[2] if len(e) > 2 else TG_KNOWN_RST[e[0]])) if (len(e) > 2 or e[0] in TG_KNOWN_RST) else 'none')
            for e in tgpre_entries))
    idx0 = k.h(4)
    say('armed  ' + m10sio.over_state(k))
    say('READY  tap the x5 magnifier now (waiting %s s)' % opt.get('wait', '600'))
    alive, t0, seen = True, time.time(), None
    try:
        while time.time() - t0 < float(opt.get('wait', 600)):
            v = c.shadow(0xc0f06804)
            if (v >> 16) in (HHEAD, h) and (v & 0xffff) == 0x2a6:
                seen = v
                if cmos_entries and 'cmosearly' not in a:
                    arm_cmos()
                    say('cmos   armed after the zoom: ' + m10sio.over_state(k))
                break
            if c.peek(0xe664)[0] == 1:          # LV went to sleep while waiting: wake, re-arm the trap
                c.lua('press("shoot_half") sleep(800) release("shoot_half") sleep(1200)')
                trap(c, k, say)
                say('       (live view was asleep, woken)')
            time.sleep(0.05)
        if seen is None:
            say('no zoom seen (6804 = %08x)' % c.shadow(0xc0f06804))
        else:
            tz = time.time()
            idx_win = max(idx0, k.h(4) - 400)
            if c.peek(0xfa80)[0] == CANON_CBR:
                trap(c, k, say)
            say('zoom   6804=%08x after %.1f s' % (seen, tz - t0))
            time.sleep(0.35)
            idx, ents = m10sio.read_ring(k)
            time.sleep(0.85)
            say('state  ' + m10auto.fmt(m10auto.state(c, k)))
            out, bad = [], []
            for r, sh, d in HREGS:
                v = ((c.shadow(r) >> sh) & 0xffff) - d
                out.append('%05x:%d' % (r & 0xfffff, v))
                if v != h:
                    bad.append('%05x' % (r & 0xfffff))
            say('hregs  ' + ' '.join(out))
            say('other  ' + ' '.join('%05x=%08x' % (r & 0xfffff, c.shadow(r)) for r in OTHER))
            say('not at H=%d: %s' % (h, ' '.join(bad) or '-'))
            m10sio.save(os.path.join(OUT, 'zoomtall_%s_commit.sio' % tag), idx, ents)
            tgw, dfew, cmosw, seq = summarize_sio(ents, idx_win)
            say('tgsent ' + ' '.join('%04x=%x' % (r, tgw[r]) for r in sorted(tgw)))
            say('dfesent ' + ' '.join('%04x=%x' % (r, dfew[r]) for r in sorted(dfew)))
            say('cmossent ' + ' '.join('%x=%03x' % (r, cmosw[r]) for r in sorted(cmosw)))
            say('tgseq  ' + ' '.join(seq[:90]))
            if 'sdump' in a:
                sb = c.peek(0x28dbc)[0]
                open(os.path.join(OUT, 'zoomtall_%s_shadow.bin' % tag), 'wb').write(c.read(sb, 0x80000))
            tp = c.peek(0xfa80)[0]
            tb = (tp & ~1) - 0x10
            say('masks  72c8=%x 72d0=%x headerr=%x trap n=%d' % (c.shadow(0xc0f072c8), c.shadow(0xc0f072d0),
                                                             c.peek(0xfa84)[0], c.peek(tb)[0]))
            res, wbl, wbt, kicks = [], None, time.time(), 0
            for i in range(int(opt.get('watch', 16))):
                rearm(c)
                n0 = c.peek(tb)[0]
                time.sleep(0.25)
                res.append('%d/%x' % (c.peek(tb)[0] - n0, c.peek(0xfa84)[0]))
                wb = c.peek(0xc6f0 + 0x58, 2)       # WBInteg tables do not follow H (live103): kick when stale
                if wb != wbl:
                    wbl, wbt = wb, time.time()
                elif time.time() - wbt > 0.4:
                    c.call(0xfc314c94, c.peek(0xc6f0 + 0x20)[0], 0x20050)
                    kicks += 1
                    wbt = time.time()
                tg = c.peek(0xe664)[0]
                if tg != 3:
                    res.append('tg=%x' % tg)
                    break
            say('errors per 0.25 s (count/status): ' + ' '.join(res) + '  wbkicks=%d' % kicks)
            say('end    ' + m10auto.fmt(m10auto.state(c, k)))
            if c.peek(0xe664)[0] == 0xffffffff:
                alive = False
                say('TG task in error (camera will shut down)')
    except Exception as e:
        alive = False
        say('exception (camera off?): %r' % e)
    finally:
        if alive and tgpre_rst:
            for reg, rst in tgpre_rst:
                c.call(FN_TG_WRITE, reg, rst)
            say('tgpre  restored ' + ' '.join('%04x=%04x' % x for x in tgpre_rst))
        if alive and 'nomode' in a:             # live117: restore RAM only; the user leaves the magnifier
            restore(c, k, say)
            say('nomode: RAM restored, no mode change (the zoom stays tall until the next entry)')
        elif alive and 'keep' not in a:
            if (c.shadow(0xc0f06804) & 0xffff) == 0x2a6:
                c.lua('click("menu") sleep(900) click("menu") sleep(1500)')
                say('left the magnifier -> 6804=%08x tg=%x' % (c.shadow(0xc0f06804), c.peek(0xe664)[0]))
            restore(c, k, say)
            say('mode VIDEO_STD: %s' % m10auto.setmode(c, 'VIDEO_STD', 1500))
            say('mode M: %s' % m10auto.setmode(c, 'M', 1500))
            say('clean  ' + m10auto.fmt(m10auto.state(c, k)))
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
