#!/usr/bin/env python3
"""live109: head line timer (0xc0f06008 low = line clocks - 1 @ 32 MHz) and frame length (0xc0f06014 = lines - 1).

    m10tgfast.py                 show
    m10tgfast.py LINECLK         set line period to LINECLK clocks, frame length kept at 40 ms (B = 1.28e6 / LINECLK - 1)
    m10tgfast.py restore         Film 25p defaults (0x02090207, 0x99c)
Writes through EngDrvOut (0xfc38d28b) then 0xc0f06000 = 1 (commit), like ML fps-engio.
"""
import sys
from m10ptp import Cam
OUT = 0xfc38d28b
c = Cam(timeout=10000)
def show(t):
    print('%s 6008=%08x 6014=%08x 600c=%08x 6010=%08x' % (t, c.shadow(0xc0f06008), c.shadow(0xc0f06014), c.shadow(0xc0f0600c), c.shadow(0xc0f06010)))
show('before')
if len(sys.argv) > 1:
    if sys.argv[1] == 'restore':
        va, vb = 0x02090207, 0x99c
    else:
        n = int(sys.argv[1]); a = c.shadow(0xc0f06008)
        va = (a & 0xffff0000) | (n - 1)
        vb = int(round(1280000.0 / n)) - 1
    c.call(OUT, 0xc0f06008, va); c.call(OUT, 0xc0f06014, vb); c.call(OUT, 0xc0f06000, 1)
    show('after ')
