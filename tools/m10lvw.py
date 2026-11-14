#!/usr/bin/env python3
"""Analyse A/LVW.BIN (m10cine v23): passive watch of CH12 / crossbar / TG
state in normal live view, one record per change.

  m10lvw.py LVW.BIN
"""
import struct, sys
from collections import Counter

d = open(sys.argv[1], 'rb').read()
if d[:8] != b'M10LVW01':
    sys.exit('pas un fichier M10LVW01')
n = struct.unpack_from('<I', d, 8)[0]
recs = [struct.unpack_from('<7I', d, 12 + 28 * i) for i in range(n)]
print('%d changements' % n)
print('valeurs ctl  :', Counter(r[2] for r in recs).most_common(6))
print('valeurs xbar :', Counter('%08x' % r[4] for r in recs).most_common(6))
print('valeurs tg   :', Counter(r[5] for r in recs).most_common(6))
print('valeurs taille:', Counter('%08x' % r[6] for r in recs).most_common(6))
prev = None
for t_us, tick, ctl, addr, xbar, tg, sz in recs[:200]:
    dt = '' if prev is None else '+%d ms' % (tick - prev)
    print('%6d ms %8s  ctl=%x addr=%08x xbar=%08x tg=%d size=%08x' % (tick, dt, ctl, addr, xbar, tg, sz))
    prev = tick
