#!/usr/bin/env python3
"""v75c/v75h: change log of Canon ImgSens / TG RAM words.

    wr.py captures/live71/<tag>_LVX3S.BIN [last_n]   (block after x_pr)
    wr.py captures/live71/<tag>_LVX3H.BIN [last_n]   (v75h: written 1 s after the run)

Each line: time (ms, relative to the first record), address, new value,
pass slot / STG stage active when the change was seen.
"""
import struct, sys
ADDR = [0x8650, 0x8654, 0x8658, 0x865c, 0x8660, 0x8664, 0x8668, 0x866c,
        0x8694, 0x8698, 0x8688, 0x868c, 0xe660, 0xe664, 0xe668, 0x28738,
        0xe440, 0xe444, 0x4ac04, 0x4ac08, 0x4ac0c, 0x2cd0c, 0x8694, 0xf1a6]   # v89p: last = ImgSens flag value
d = open(sys.argv[1], 'rb').read()
if sys.argv[1].endswith('LVX3H.BIN'):
    o = 0
else:
    hd = struct.unpack_from('<8I', d, 0)
    o = 32 + 40 * 160 + hd[4] * 64 + 16 * 12 * 4 * 4 + 64 * 4 + 16 * 73 * 4 + 16 * 12 * 4
    if len(d) < o + 4:
        sys.exit('no wr_log (pre-v75c file)')
n = struct.unpack_from('<I', d, o)[0]
recs = [struct.unpack_from('<3I', d, o + 4 + 12 * i) for i in range(min(n, 480))]
last = int(sys.argv[2]) if len(sys.argv) > 2 else 200
if not recs:
    sys.exit('empty')
prev = recs[0][0] & 0xfffff
acc = 0
rows = []
for r in recs:
    t = r[0] & 0xfffff
    acc += (t - prev) & 0xfffff
    prev = t
    rows.append((acc, r[0] >> 24, r[1], r[2]))
print('records', n)
for acc, i, v, s in rows[-last:]:
    name = 'START' if i == 0xff else '%05x' % ADDR[i]
    vs = '%d' % (v - 2**32) if v > 0xffff0000 else '%08x' % v
    print('%9.2f ms  %s = %s   pass %d stg %d' % (acc / 1000, name, vs, s >> 16, s & 0xffff))
