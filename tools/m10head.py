#!/usr/bin/env python3
"""1x3 head-window test: enter 1x3 (Film commit with TG 0x800c=0), then
raise the head vertical size in steps and watch.  The head height is set
in two registers that must agree: 0xc0f06804 (high half = lines) and
0xc0f072c0 (= lines + 2).  The frame length (0xc0f06014, 2461 lines in Film)
is left alone: Film has 1271 lines of vertical blanking to spare.

    m10head.py LINES [LINES ...]        e.g. m10head.py 1400 1700 2000

For each step: EngDrvOut(0xc0f06804, (LINES << 16) | low), wait 2 s, log TG
task state / head / timers, grab the live view.  Aborts the ramp if the TG
task leaves state 3.  Always restores 0xc0f06804 and re-commits Film cleanly
(M -> VIDEO_STD without overrides) at the end.  Log -> captures/live67/.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10lvgrab, m10auto

FN_ENGDRV_OUT = 0xfc38d28b
HEAD = 0xc0f06804
HEAD_END = 0xc0f072c0   # = head lines + 2 in every Canon mode (photo 729/727, film 1192/1190)
OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live67')


def main(a):
    steps = [int(x, 0) for x in a]
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, 'head_%s.txt' % '_'.join(map(str, steps))), 'w')
    say = lambda s: (print(s), log.write(s + '\n'), log.flush())
    c = Cam()
    k = m10sio.find(c)
    assert k is not None and k.magic == m10sio.M3
    m10sio.clear_overrides(k)
    say('mode M: %s' % m10auto.setmode(c, 'M'))
    k.set_h(28, 0); k.set_h(32, 0x800c); k.set_h(36, 0); k.set_h(44, 0); k.set_h(28, 1)
    say('mode VIDEO_STD (800c=0): %s' % m10auto.setmode(c, 'VIDEO_STD', 2000))
    m10sio.clear_overrides(k)
    s = m10auto.state(c, k)
    say('1x3    ' + m10auto.fmt(s))
    h0 = s['h6804']
    e0 = c.shadow(HEAD_END)
    say('72c0=%d (head %d)' % (e0, h0 >> 16))
    if s['tg'] != 3 or (h0 >> 16) != 0x4a6 or e0 != 0x4a8:
        say('unexpected state, abort')
    else:
        m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)), os.path.join(OUT, 'head_1190.png'))
        try:
            for L in steps:
                v = (L << 16) | (h0 & 0xffff)
                c.call(FN_ENGDRV_OUT, HEAD_END, L + 2)
                c.call(FN_ENGDRV_OUT, HEAD, v)
                time.sleep(2)
                s = m10auto.state(c, k)
                say('L=%4d  ' % L + m10auto.fmt(s))
                if s['tg'] != 3:
                    say('TG task left state 3 -> stop ramp')
                    break
                m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)),
                                   os.path.join(OUT, 'head_%d.png' % L))
        finally:
            c.call(FN_ENGDRV_OUT, HEAD, h0)
            c.call(FN_ENGDRV_OUT, HEAD_END, e0)
            say('restored 6804=%08x 72c0=%d' % (c.shadow(HEAD), c.shadow(HEAD_END)))
    say('mode M: %s' % m10auto.setmode(c, 'M'))
    say('mode VIDEO_STD: %s' % m10auto.setmode(c, 'VIDEO_STD', 2000))
    say('clean  ' + m10auto.fmt(m10auto.state(c, k)))
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
