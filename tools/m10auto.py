#!/usr/bin/env python3
"""Fully scripted sensor override trial (no user action needed).

    m10auto.py FROM TO [cREG=VAL ...] [tREG=VAL]   e.g.  m10auto.py M VIDEO_STD t0x800c=0

1. switch to capture mode FROM (CHDK capmode) and wait for live view,
2. arm the overrides in the v3 SIO hook,
3. switch to TO (Canon replays the sensor commit through the hook),
4. wait 2 s, record head geometry / TG state, grab the live view (PNG),
5. disarm, switch FROM -> TO again to restore a clean sensor state,
6. grab a reference PNG of the clean state.
Abort/disarm immediately if the TG task goes to error (-1).
Output: captures/live66/auto_<tag>.{txt,png} and ..._ref.png
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam, fmt_msg
import m10sio, m10lvgrab

OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live66')


def setmode(c, name, wait_ms=1500):
    r = c.lua('capmode=require"capmode" local ok=capmode.set("%s") sleep(%d) '
              'return tostring(ok).." "..capmode.get_name()' % (name, wait_ms))
    return fmt_msg(r[-1]) if r else None


def state(c, k):
    return dict(tg=c.peek(0xe664)[0], h6804=c.shadow(0xc0f06804), h6800=c.shadow(0xc0f06800),
                t6008=c.shadow(0xc0f06008), t6014=c.shadow(0xc0f06014),
                dss=tuple(c.peek(0x1beb5c, 2)), cmos_hits=k.h(24), tg_hits=k.h(40))


def fmt(s):
    return ('tg=%x 6804=%08x 6800=%08x 6008=%08x 6014=%08x dss=%dx%d cmos_hits=%d tg_hits=%d'
            % (s['tg'], s['h6804'], s['h6800'], s['t6008'], s['t6014'],
               s['dss'][0], s['dss'][1], s['cmos_hits'], s['tg_hits']))


def main(a):
    frm, to = a[0], a[1]
    cm, tg = [], None
    for x in a[2:]:
        r, v = x[1:].split('=')
        if x[0] == 'c':
            cm.append((int(r, 0), int(v, 0)))
        else:
            tg = (int(r, 0), int(v, 0))
    tag = '%s_%s_' % (frm, to) + '_'.join(['c%d-%03x' % o for o in cm] +
                                         (['t%04x-%04x' % tg] if tg else []))
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, 'auto_%s.txt' % tag), 'w')
    say = lambda s: (print(s), log.write(s + '\n'), log.flush())
    c = Cam()
    k = m10sio.find(c)
    assert k is not None and k.magic == m10sio.M3, "needs the v3 hook"
    m10sio.clear_overrides(k)
    try:
        say('mode %s: %s' % (frm, setmode(c, frm)))
        say('base   ' + fmt(state(c, k)))
        for r, v in cm:
            k.poke(k.b + k.cmos + 4 * r, 0x10000 | (v & 0xfff))
        if cm:
            k.set_h(20, 1)
        if tg:
            k.set_h(28, 0); k.set_h(32, tg[0]); k.set_h(36, tg[1]); k.set_h(44, 0); k.set_h(28, 1)
        say('armed  ' + m10sio.over_state(k))
        say('mode %s: %s' % (to, setmode(c, to, 2000)))
        s = state(c, k)
        say('patch  ' + fmt(s))
        if s['tg'] == 0xffffffff:
            say('TG task in error -> abort')
        else:
            png = os.path.join(OUT, 'auto_%s.png' % tag)
            m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)), png)
            say('grab   ' + png)
    finally:
        m10sio.clear_overrides(k)
        say('disarm ' + m10sio.over_state(k))
    say('mode %s: %s' % (frm, setmode(c, frm)))
    say('mode %s: %s' % (to, setmode(c, to, 2000)))
    say('clean  ' + fmt(state(c, k)))
    ref = os.path.join(OUT, 'auto_%s_ref.png' % tag)
    m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)), ref)
    say('ref    ' + ref)
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
