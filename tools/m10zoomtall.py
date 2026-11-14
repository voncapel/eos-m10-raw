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
ZOOM6804 = 0x045702a6
FN_MALLOC = 0xfc38d3f1
CANON_CBR = 0xfc1ee9a9
# (register, shift, offset from the head height) measured on captures/live70/shadow_zoom.bin
HREGS = [(0xc0f06804, 16, 0), (0xc0f072c0, 0, 2), (0xc0f08184, 0, -4), (0xc0f35088, 0, -3),
         (0xc0f373e8, 16, -4), (0xc0f373f4, 16, -3), (0xc0f37a70, 16, -4), (0xc0f37ad0, 16, -4),
         (0xc0f37b8c, 16, -4), (0xc0f42014, 16, -4), (0xc0f42918, 16, -4), (0xc0f4292c, 16, 0),
         (0xc0f42938, 16, -4), (0xc0f42948, 16, -3), (0xc0f42950, 16, -4), (0xc0f4296c, 16, -4),
         (0xc0f42980, 16, -3), (0xc0f42994, 16, -4), (0xc0f450a4, 16, -4)]
OTHER = (0xc0f06800, 0xc0f06008, 0xc0f06014, 0xc0f07050, 0xc0f04a08, 0xc0f04a10, 0xc0f09008, 0xc0f09034)


def gray(n):
    return n ^ (n >> 1)


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
    h = HHEAD + dh
    tag = 'H%d' % h
    log = open(os.path.join(OUT, 'zoomtall_%s.txt' % tag), 'w')

    def say(s):
        print(s, flush=True)
        log.write(s + '\n')
        log.flush()

    say('zoomtall %s (dh %+d)  vbatt %d' % (tag, dh, struct.unpack('<I', c.lua('return get_vbatt()')[0][2])[0]))
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
    tab = []
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
        m10sio.set_tg_table(k, tab)
    say('armed  ' + m10sio.over_state(k))
    say('READY  tap the x5 magnifier now (waiting %s s)' % opt.get('wait', '600'))
    alive, t0, seen = True, time.time(), None
    try:
        while time.time() - t0 < float(opt.get('wait', 600)):
            v = c.shadow(0xc0f06804)
            if (v >> 16) in (HHEAD, h) and (v & 0xffff) == 0x2a6:
                seen = v
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
            if c.peek(0xfa80)[0] == CANON_CBR:
                trap(c, k, say)
            say('zoom   6804=%08x after %.1f s' % (seen, tz - t0))
            time.sleep(1.2)
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
            idx, ents = m10sio.read_ring(k)
            m10sio.save(os.path.join(OUT, 'zoomtall_%s_commit.sio' % tag), idx, ents)
            tgw, pend = {}, None
            for e in ents:
                if e[2] != 4:
                    continue
                if e[5] == 0xfc231323:
                    pend = e[6] & 0xffff
                elif e[5] == 0xfc23132d and pend is not None:
                    tgw[pend] = e[6] & 0xffff
                    pend = None
            say('tgsent ' + ' '.join('%04x=%x' % (r, tgw[r]) for r in sorted(tgw)))
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
