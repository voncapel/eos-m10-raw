#!/usr/bin/env python3
"""Dump the whole EngDrv shadow (RAM copy of 0xc0f00000-0xc0f7ffff written by
EngDrvOut) for a sequence of capture modes, read-only.

    m10shadowdump.py TAG MODE [MODE ...]      e.g. m10shadowdump.py pf M VIDEO_STD
    m10shadowdump.py TAG MODE ... t0x800c=0   arm the TG override for the LAST mode

Shadow base = *(0x28dbc); register r lives at base + (r & 0x7ffff).  Output:
captures/live70/shadow_TAG_<i>_<MODE>.bin (512 KiB each).
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10auto

OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live70')
SIZE = 0x80000


def dump(c):
    base = c.peek(0x28dbc)[0]
    return b''.join(c.read(base + o, 0x10000) for o in range(0, SIZE, 0x10000))


def main(a):
    tag, modes, tg = a[0], [], None
    for x in a[1:]:
        if x.startswith('t'):
            r, v = x[1:].split('=')
            tg = (int(r, 0), int(v, 0))
        else:
            modes.append(x)
    os.makedirs(OUT, exist_ok=True)
    c = Cam()
    k = m10sio.find(c)
    if k is not None:
        m10sio.clear_overrides(k)
    try:
        for i, m in enumerate(modes):
            if tg and i == len(modes) - 1:
                assert k is not None and k.magic == m10sio.M3
                k.set_h(28, 0); k.set_h(32, tg[0]); k.set_h(36, tg[1]); k.set_h(44, 0); k.set_h(28, 1)
            r = m10auto.setmode(c, m, 2000)
            if k is not None:
                m10sio.clear_overrides(k)
            s = m10auto.state(c, k) if k is not None else {}
            fn = os.path.join(OUT, 'shadow_%s_%d_%s.bin' % (tag, i, m))
            open(fn, 'wb').write(dump(c))
            print(m, r, m10auto.fmt(s) if s else '', '->', fn)
    finally:
        if k is not None:
            m10sio.clear_overrides(k)
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
