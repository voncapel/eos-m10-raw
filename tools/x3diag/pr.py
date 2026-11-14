#!/usr/bin/env python3
"""v74: per-pass record of the persistent PACK32 path (x_pr, after x_df in LVX3S.BIN).

    pr.py captures/live71/<tag>_LVX3S.BIN

Columns: path (open / reuse), PACK32/PreproPort shadow right before ch12_arm,
REG(CH12) before start, DMA time, bytes received -> lines, st, 8090 after.
"""
import struct, sys
d = open(sys.argv[1], 'rb').read()
hd = struct.unpack_from('<8I', d, 0)
o = 32 + 40 * 160 + hd[4] * 64 + 16 * 12 * 4 * 4 + 64 * 4 + 16 * (1 + 72) * 4
if len(d) < o + 16 * 12 * 4:
    sys.exit('no x_pr block (pre-v74 file)')
lb = int(sys.argv[2]) if len(sys.argv) > 2 else 2260
print('slot path  8090     8264 8268 82bc 8bf0 37014    37074    ch12  dt_us  lines st  8090end')
for k in range(16):
    r = struct.unpack_from('<12I', d, o + 48 * k)
    if r[0] == 0:
        continue
    path = {1: 'open ', 2: 'reuse'}.get(r[0] & 3, '?')
    rx, st = r[10] & 0x0fffffff, r[10] >> 28
    print('%2d   %s %08x %4x %4x %4x %4x %08x %08x %4x %6d %5d %2d  %08x  xo=%x' % (
        k, path, r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], rx // lb, st, r[11], (r[0] >> 4) & 0x3c0))
