#!/usr/bin/env python3
"""Apply sensor overrides for a few seconds and watch the camera.

    m10cmostry.py SECONDS [cREG=VAL ...] [tREG=VAL]

    cREG=VAL   CMOS register override (e.g. c8=0x000)
    tREG=VAL   TG override, one slot (e.g. t0x800c=0)

Needs the v3 SIO hook (m10sio.py swap).  Polls ~every 120 ms: TG task state
[0xe664], head geometry (shadow 0xc0f06804), timers, DSS geometry, hit
counters.  All overrides are cleared at the end, or immediately if the TG
task goes to the error state (-1) twice in a row.  Log -> captures/live65/.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio


GRAB = 0   # seconds after arming at which to grab the live view (0 = no grab)


def main(a):
    global GRAB
    if a and a[0].startswith('grab='):
        GRAB = float(a[0][5:]); a = a[1:]
    secs = float(a[0])
    cm, tg = [], None
    for x in a[1:]:
        r, v = x[1:].split('=')
        if x[0] == 'c':
            cm.append((int(r, 0), int(v, 0)))
        elif x[0] == 't':
            tg = (int(r, 0), int(v, 0))
    c = Cam()
    k = m10sio.find(c)
    assert k is not None and k.magic == m10sio.M3, "needs the v3 hook"
    tag = '_'.join(['c%d-%03x' % o for o in cm] + (['t%04x-%04x' % tg] if tg else []))
    d = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live65')
    os.makedirs(d, exist_ok=True)
    fn = os.path.join(d, 'try_%s.txt' % tag)
    log = open(fn, 'w')

    def snap(t):
        s = (t, c.peek(0xe664)[0], c.shadow(0xc0f06804), c.shadow(0xc0f06008),
             c.shadow(0xc0f06014)) + tuple(c.peek(0x1beb5c, 2)) + (k.h(24), k.h(40), k.h(4))
        line = ('t=%5.2f tg=%x 6804=%08x 6008=%08x 6014=%08x dss=%dx%d'
                ' cmos_hits=%d tg_hits=%d sio=%d' % s)
        log.write(line + '\n'); log.flush()
        return s, line

    s0, l = snap(-0.1)
    print('before', l)
    for r, v in cm:
        k.poke(k.b + k.cmos + 4 * r, 0x10000 | (v & 0xfff))
    if cm:
        k.set_h(20, 1)
    if tg:
        k.set_h(28, 0); k.set_h(32, tg[0]); k.set_h(36, tg[1]); k.set_h(44, 0); k.set_h(28, 1)
    print('armed:', m10sio.over_state(k))
    t0, bad, last, grabbed = time.time(), 0, None, False
    try:
        while time.time() - t0 < secs:
            if GRAB and not grabbed and time.time() - t0 > GRAB:
                import m10lvgrab
                gfn = fn[:-4] + '.png'
                m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)), gfn)
                print('grabbed ->', gfn); grabbed = True
            s, l = snap(time.time() - t0)
            key = s[1:7]
            if key != last:
                print(l); last = key
            bad = bad + 1 if s[1] == 0xffffffff else 0
            if bad > 1:
                print('TG task in error (-1) -> abort')
                break
            time.sleep(0.1)
    finally:
        m10sio.clear_overrides(k)
    time.sleep(0.5)
    s, l = snap(time.time() - t0)
    print('after ', l)
    print('hits during try: cmos %d, tg %d' % (s[7] - s0[7], s[8] - s0[8]))
    c.close()
    print('log ->', fn)


if __name__ == '__main__':
    main(sys.argv[1:])
