#!/usr/bin/env python3
"""CMOS register override trial with the v4 hook, steady state (no commit).

    m10cmosv4.py TAG REG=VAL [REG=VAL ...] [secs=S]

Arms the CMOS rewrite table, waits S s (default 1.5) while watching the TG
task, grabs the live view, disarms, waits, grabs a reference.  Disarms at once
if the TG task goes to -1.  Output: captures/live80/cmos_TAG{,_ref}.png + .txt
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10lvgrab, m10auto

OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live80')


def main(a):
    tag, secs, ov = a[0], 1.5, []
    for x in a[1:]:
        r, v = x.split('=')
        if r == 'secs':
            secs = float(v)
        else:
            ov.append((int(r, 0), int(v, 0)))
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, 'cmos_%s.txt' % tag), 'w')
    say = lambda s: (print(s), log.write(s + '\n'), log.flush())
    c = Cam()
    k = m10sio.find(c)
    assert k is not None and k.magic in m10sio.MTAB
    m10sio.clear_overrides(k)
    say('base   ' + m10auto.fmt(m10auto.state(c, k)))
    bad = False
    try:
        for r, v in ov:
            k.poke(k.b + k.cmos + 4 * r, 0x10000 | (v & 0xfff))
        k.set_h(24, 0)
        k.set_h(20, 1)
        t0 = time.time()
        while time.time() - t0 < secs:
            if c.peek(0xe664)[0] == 0xffffffff:
                bad = True
                break
            time.sleep(0.1)
        s = m10auto.state(c, k)
        say('armed  ' + m10auto.fmt(s))
        if s['tg'] == 0xffffffff:
            bad = True
        if not bad:
            png = os.path.join(OUT, 'cmos_%s.png' % tag)
            m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)), png)
            say('grab   ' + png)
    finally:
        m10sio.clear_overrides(k)
        say('disarm ' + m10sio.over_state(k))
    if bad:
        say('TG task in error!')
        return
    time.sleep(1.0)
    say('clean  ' + m10auto.fmt(m10auto.state(c, k)))
    ref = os.path.join(OUT, 'cmos_%s_ref.png' % tag)
    m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)), ref)
    say('ref    ' + ref)
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
