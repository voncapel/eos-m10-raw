#!/usr/bin/env python3
"""live109: what Canon sends to the sensor for the current exposure (Film LV).

    m10expo.py [SECS] [TV96] [SV96]

Optionally sets PROPCASE_USER_TV (276) / ISO (157) first (APEX*96 values,
e.g. TV 1/200 = 734, 1/100 = 638, 1/50 = 542, 1/25 = 446), then streams the
SIO ring for SECS (default 1.5) and prints, per sensor frame, TG 805f/8061
(exposure, Gray-coded), CMOS 0-9 and the DFE / CDS writes that vary.
Ring channel mask 0x50 (ch4 + ch6) as installed by m10wake / M10HOOK=install6.
"""
import os, sys, time, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m10ptp import Cam
import m10sio, m10siodec as S


def gray2bin(g):
    b = 0
    while g:
        b ^= g; g >>= 1
    return b


def props(c):
    r = c.lua('return get_prop(274)..","..get_prop(276)..","..get_prop(157)..","..get_prop(356)')
    return r[-1][2].decode() if r else '?'


def snap(c, k, secs=1.5, out='/tmp/m10expo.sio'):
    m10sio.stream(k, out, secs)
    F = S.frames(S.writes(S.load(out)))
    return F


def summary(F):
    keys = collections.Counter()
    for f in F[1:]:
        for kk in f:
            if isinstance(kk, tuple):
                keys[kk] += 1
    res = {}
    for kk in keys:
        vals = collections.Counter(f[kk] for f in F[1:] if kk in f)
        res[kk] = vals.most_common(1)[0][0]
    return res


def main(a):
    secs = float(a[0]) if a else 1.5
    c = Cam(timeout=20000)
    k = m10sio.find(c)
    if len(a) > 1 and a[1] != '-':
        c.lua('set_prop(276,%d)' % int(a[1]))
    if len(a) > 2 and a[2] != '-':
        c.lua('set_prop(157,%d)' % int(a[2]))
    time.sleep(0.6)
    print('props tv,user_tv,iso,sv =', props(c), 'tg=%d' % c.peek(0xe664)[0])
    F = snap(c, k, secs)
    r = summary(F)
    e = r.get(('TG', 0x805f)), r.get(('TG', 0x8061))
    if None not in e:
        raw = e[0] << 16 | e[1] if e[0] < 0x100 else (e[0] << 8 | e[1])
    print('%d frames' % len(F), ' '.join('%s.%x=%x' % (kk[0], kk[1], v) for kk, v in sorted(r.items())
                                        if kk[0] in ('CMOS', 'DFE', 'CDS') or kk[1] in (0x805f, 0x8061)))
    for kk in ((('TG', 0x805f)), ('TG', 0x8061)):
        if kk in r:
            print('  %s.%x raw %x -> bin %d' % (kk[0], kk[1], r[kk], gray2bin(r[kk])))
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
