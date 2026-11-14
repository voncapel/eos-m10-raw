#!/usr/bin/env python3
"""Taller 1x3 window trial in VGA 25p (head 727 lines, readout ~12 ms of 40).

    m10tall.py N [H=lines] [C7=0x80b] [secs=S] [keep]

1. M -> VIDEO_STD commit with the v4 TG table armed (conditional on Canon's
   VGA values): 800c=0 (1x3), 8172/8178/82f8 = 730+N, 82b6 = 728+N (Gray).
   The table stays armed (Canon rewrites 8172/8173 every frame).
2. optional H: head 6804 (and 72c0) + H lines, written with EngDrvOut
   after the commit (H <= N: the TG must clock at least as many lines).
3. optional C7: CMOS 7 rewrite (vertical start) during the trial.
4. watch the TG task for S s (default 5), grab the live view.
5. restore: head back, disarm, M -> VIDEO_STD (clean VGA).  With 'keep',
   leave everything armed (for a RAW capture with m10x3raw.py afterwards).
Output: captures/live80/tall_N{_H}{_c7}.{txt,png}
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10lvgrab, m10auto

OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live80')
ENGDRVOUT = 0xfc38d28b
H0, HEAD0, H72C0 = 727, 0x02d701dc, 0x2d9


def gray(n):
    return n ^ (n >> 1)


def main(a):
    n = int(a[0], 0)
    h, c7, secs, keep = 0, None, 5.0, False
    for x in a[1:]:
        if x.startswith('H='):
            h = int(x[2:], 0)
        elif x.startswith('C7='):
            c7 = int(x[3:], 0)
        elif x.startswith('secs='):
            secs = float(x[5:])
        elif x == 'keep':
            keep = True
    tag = 'N%d' % n + ('_H%d' % h if h else '') + ('_c7-%03x' % c7 if c7 is not None else '')
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, 'tall_%s.txt' % tag), 'w')
    say = lambda s: (print(s), log.write(s + '\n'), log.flush())
    c = Cam()
    k = m10sio.find(c)
    assert k is not None and k.magic in m10sio.MTAB
    m10sio.clear_overrides(k)
    say('mode M: %s' % m10auto.setmode(c, 'M'))
    tab = [(0x800c, 0, 4)]
    if n:
        tab += [(0x8172, gray(730 + n), gray(730)), (0x8178, gray(730 + n), gray(730)),
                (0x82f8, gray(730 + n), gray(730)), (0x82b6, gray(728 + n), gray(728))]
    m10sio.set_tg_table(k, tab)
    if c7 is not None:
        k.poke(k.b + k.cmos + 4 * 7, 0x10000 | c7)
        k.set_h(20, 1)
    say('armed  ' + m10sio.over_state(k))
    say('mode VIDEO_STD: %s' % m10auto.setmode(c, 'VIDEO_STD', 2000))
    s = m10auto.state(c, k)
    say('commit ' + m10auto.fmt(s))
    dead = s['tg'] == 0xffffffff
    if not dead and s['h6804'] != HEAD0:
        say('unexpected head, abort'); dead = True
    if not dead and h:
        c.call(ENGDRVOUT, 0xc0f06804, HEAD0 + (h << 16))
        c.call(ENGDRVOUT, 0xc0f072c0, H72C0 + h)
        say('head   6804=%08x 72c0=%08x' % (c.shadow(0xc0f06804), c.shadow(0xc0f072c0)))
    t0 = time.time()
    while not dead and time.time() - t0 < secs:
        if c.peek(0xe664)[0] == 0xffffffff:
            dead = True
            break
        time.sleep(0.2)
    s = m10auto.state(c, k)
    say('t+%.0fs  ' % (time.time() - t0) + m10auto.fmt(s))
    if s['tg'] == 0xffffffff or dead:
        say('TG task in error (camera will shut down)')
        c.close()
        return
    png = os.path.join(OUT, 'tall_%s.png' % tag)
    m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)), png)
    say('grab   ' + png)
    if keep:
        say('kept armed')
        c.close()
        return
    if h:
        c.call(ENGDRVOUT, 0xc0f06804, HEAD0)
        c.call(ENGDRVOUT, 0xc0f072c0, H72C0)
    m10sio.clear_overrides(k)
    say('mode M: %s' % m10auto.setmode(c, 'M'))
    say('mode VIDEO_STD: %s' % m10auto.setmode(c, 'VIDEO_STD', 2000))
    say('clean  ' + m10auto.fmt(m10auto.state(c, k)))
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
