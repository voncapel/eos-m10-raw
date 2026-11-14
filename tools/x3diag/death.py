#!/usr/bin/env python3
"""Where does Canon's SIO activity stop, relative to our last passes' stages?
    death.py captures/live71/<tag>_LVX3S.BIN"""
import struct, sys
d = open(sys.argv[1], 'rb').read()
hd = struct.unpack_from('<8I', d, 0); nent, idx = hd[4], hd[3]
o = 32 + 40 * 160; ring = d[o:o + nent * 64]; o += nent * 64
ents = [struct.unpack_from('<16I', ring, 64 * i) for i in range(nent)]
seq = [ents[i % nent] for i in range(idx - nent, idx)]
stg = [[struct.unpack_from('<4I', d, o + 16 * (12 * k + s)) for s in range(12)] for k in range(16)]
ref = seq[-1][0] & 0xfffff
rel = lambda u: ((u - ref + 0x80000) & 0xfffff) - 0x80000
ev = []
for e in seq[-400:]:
    lr = e[4]
    if lr == 0xfc1bd4e3 and e[5] == 0x8830: ev.append((rel(e[0] & 0xfffff), 'DFE 8830'))
    elif lr == 0xfc1bec0f and ((e[5] >> 12) & 0xf) == 0: ev.append((rel(e[0] & 0xfffff), 'CMOS0'))
names = {0: 'enter', 1: 'synced', 4: 'PK_ON', 5: 'DMA start', 6: 'DMA end+wait', 7: 'ch12 stop', 8: 'PK regs', 9: 'PK_GIVE', 10: 'unlock', 11: 'loop'}
for k in range(16):
    for s in names:
        t = stg[k][s][0]
        if t: ev.append((rel(t & 0xfffff), 'pass %d %s' % (k, names[s])))
ev = [e for e in ev if e[0] > -400000]
for t, n in sorted(ev)[-40:]:
    print('%9.2f ms  %s' % (t / 1000, n))
print('(0 = last SIO entry)')
