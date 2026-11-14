#!/usr/bin/env python3
"""live109: optimal lossless-JPEG Huffman tables for the Canon encoder (args[18]).

    m10huff.py OUT.BIN LVX3.BIN [...]     (10-bit captures, encoded as << 4 by the hardware unpacker)

Format (as ROM 0xfc6d8de4): per component 48 bytes = BITS[16] + HUFFVAL[32] (zero padded),
two components.  A dummy symbol (16) takes the all-ones code (forbidden in JPEG).
Exactly 15 symbols (SSSS 0-14): the Canon encoder refuses a 16th (live109).
"""
import sys, heapq, numpy as np
import m10level as L


def ssss_hist(raw, shift=4):
    x = raw.astype(np.int64) << shift
    a = x.reshape(x.shape[0], -1, 2)
    d = np.empty_like(a)
    d[:, 1:] = a[:, 1:] - a[:, :-1]
    d[1:, 0] = a[1:, 0] - a[:-1, 0]
    d[0, 0] = a[0, 0] - (1 << 13)
    ad = np.abs(d); s = np.zeros(ad.shape, int); nz = ad > 0
    s[nz] = np.floor(np.log2(ad[nz])).astype(int) + 1
    u, c = np.unique(s, return_counts=True)
    return dict(zip(u.tolist(), c.tolist()))


def lengths(counts, maxlen=16):
    while True:
        h = [(c, i, [s]) for i, (s, c) in enumerate(sorted(counts.items()))]
        heapq.heapify(h); Ln = {s: 0 for s in counts}; k = 1000
        while len(h) > 1:
            a = heapq.heappop(h); b = heapq.heappop(h)
            for s in a[2] + b[2]: Ln[s] += 1
            k += 1; heapq.heappush(h, (a[0] + b[0], k, a[2] + b[2]))
        if max(Ln.values()) <= maxlen: return Ln
        counts = {s: max(c, max(counts.values()) // 2 ** 15) for s, c in counts.items()}


def table(counts):
    c = {s: counts.get(s, 0) + 1 for s in range(0, 15)}       # categories 0-14 only (16 symbols -> encoder refuses, live109)
    c[16] = 0.5                                                 # dummy: gets the all-ones code
    Ln = lengths(c)
    bits = [0] * 16; vals = []
    for l in range(1, 17):
        vs = sorted([s for s in Ln if Ln[s] == l and s != 16], key=lambda s: -c[s])
        if 16 in Ln and Ln[16] == l: vs.append(16)
        bits[l - 1] = len(vs); vals += vs
    vals = [v for v in vals if v != 16]
    bits[Ln[16] - 1] -= 1                                       # drop the dummy itself (code stays unused)
    return bits, vals, Ln


def main(a):
    tot = {}
    for fn in a[1:]:
        raw = list(L.passes(fn))[0]
        for s, n in ssss_hist(raw).items(): tot[s] = tot.get(s, 0) + n
    bits, vals, Ln = table(tot)
    est = sum((Ln[s] + s) * n for s, n in tot.items()) / 8e6 / len(a[1:])
    print('BITS', bits, 'VALS', vals, 'est %.2f MB/frame' % est)
    blk = bytes(bits) + bytes(vals + [0] * (32 - len(vals)))
    open(a[0], 'wb').write(blk + blk)


if __name__ == '__main__':
    main(sys.argv[1:])
