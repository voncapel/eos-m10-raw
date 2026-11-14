#!/usr/bin/env python3
"""Combined 1x3 commit trial (hook v4): during one M -> VIDEO_STD commit, rewrite
several TG registers (table, optionally conditional on Canon's original value),
and optionally redirect the Film Extract record (head window) to a RAM copy.

    m10x3.py [L=LINES] [tREG=VAL[@ORIG]] ...
      e.g.  m10x3.py t0x800c=0@2                      (known 1x3, regression)
            m10x3.py L=1400 t0x800c=0@2 t0x82b6=...   (taller head + TG window)

TG values are written raw (Gray-coded registers must be encoded by the caller:
use g:N to Gray-encode N, e.g. t0x8172=g:1400).  The Extract copy patches
+0x10/+0x18/+0x28 = LINES and the ImgSens size cache (modes 34/36).
Always: disarm the hook table, restore the Extract pointer and cache, and
re-commit M -> VIDEO_STD cleanly.  Log + LV grab -> captures/live70/.
"""
import os, sys, time, struct
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10lvgrab, m10auto

TAB = 0x2cd24
SLOT7 = TAB + 4 * 7
REC7 = 0xfc72f34c
CACHE = 0x575b0
CACHE_MODES = (34, 36)
FN_MALLOC = 0xfc38d3f1
OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live70')


def gray(n):
    return n ^ (n >> 1)


def val(s):
    return gray(int(s[2:], 0)) if s.startswith('g:') else int(s, 0)


def main(a):
    lines, tg = None, []
    for x in a:
        if x.startswith('L='):
            lines = int(x[2:], 0)
        elif x.startswith('t'):
            r, v = x[1:].split('=')
            if '@' in v:
                v, o = v.split('@')
                tg.append((int(r, 0), val(v), val(o)))
            else:
                tg.append((int(r, 0), val(v)))
    tag = '_'.join((['L%d' % lines] if lines else []) +
                   ['%04x-%x' % (e[0], e[1]) + ('@%x' % e[2] if len(e) > 2 else '') for e in tg]) or 'none'
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, 'x3_%s.txt' % tag), 'w')
    say = lambda s: (print(s), log.write(s + '\n'), log.flush())
    c = Cam()
    k = m10sio.find(c)
    assert k is not None and k.magic in m10sio.MTAB, "needs the v4 hook"
    m10sio.clear_overrides(k)
    assert struct.unpack('<I', c.read(SLOT7, 4))[0] == REC7
    say('mode M: %s' % m10auto.setmode(c, 'M'))
    cache_orig = {m: c.peek(CACHE + 36 * m, 4) for m in CACHE_MODES}
    buf = None
    if lines:
        rec = bytearray(c.read(REC7, 0x68))
        for off in (0x10, 0x18, 0x28):
            struct.pack_into('<I', rec, off, lines)
        buf = c.call(FN_MALLOC, 0x80)
        assert buf
        c.write(buf, bytes(rec))
        assert c.read(buf, 0x68) == bytes(rec)
    ok = False
    try:
        if buf:
            c.poke(SLOT7, buf)
            for m in CACHE_MODES:
                c.poke(CACHE + 36 * m + 4, lines)
                c.poke(CACHE + 36 * m + 12, lines)
        m10sio.set_tg_table(k, tg)
        k.set_h(4, 0)                     # fresh ring for this commit
        say('armed  ptr7=%08x %s' % (struct.unpack('<I', c.read(SLOT7, 4))[0], m10sio.over_state(k)))
        say('mode VIDEO_STD: %s' % m10auto.setmode(c, 'VIDEO_STD', 2000))
        for i in range(3):
            s = m10auto.state(c, k)
            say('t+%ds   ' % (2 * i) + m10auto.fmt(s) + ' 72c0=%08x tg_hits=%d' % (c.shadow(0xc0f072c0), k.h(40)))
            if s['tg'] == 0xffffffff:
                say('TG task in error -> abort')
                try:
                    idx, ents = m10sio.read_ring(k)
                    fn = os.path.join(OUT, 'x3_%s.sio' % tag)
                    m10sio.save(fn, idx, ents)
                    say('sio    %s (%d entries)' % (fn, len(ents)))
                except Exception as e:
                    say('sio dump failed: %r' % e)
                break
            if i == 0:
                png = os.path.join(OUT, 'x3_%s.png' % tag)
                m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)), png)
                say('grab   ' + png)
                ok = True
            time.sleep(2)
    finally:
        try:
            # Canon rewrites 8172/8173 every frame: never disarm while still in the
            # patched Film mode.  Restore Extract, go to Photo M (its TG values do
            # not match the @orig conditions), then disarm.
            c.poke(SLOT7, REC7)
            if ok:
                say('mode M (still armed): %s' % m10auto.setmode(c, 'M'))
            m10sio.clear_overrides(k)
            for m, v in cache_orig.items():
                c.poke(CACHE + 36 * m, *v)
            say('restore ptr7=%08x %s' % (struct.unpack('<I', c.read(SLOT7, 4))[0], m10sio.over_state(k)))
        except Exception as e:
            say('restore FAILED: %r' % e)
    if ok:
        say('mode VIDEO_STD: %s' % m10auto.setmode(c, 'VIDEO_STD', 2000))
        say('clean  ' + m10auto.fmt(m10auto.state(c, k)))
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
