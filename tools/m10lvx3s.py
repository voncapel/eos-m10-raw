#!/usr/bin/env python3
"""live115: chronology of an lv_x3 run from A/LVX3S.BIN ("1X3S").

    m10lvx3s.py FILE [--all]

Layout (m10_cine.c, end of lv_x3): hd[8] = {"1X3S", pass|-1, tl_n, ring write idx,
nent, sio base, ., .}; tl[160] = {us, ptr, tg, sio, w[6]} (last pass, 1 / ms);
SIO ring nent x 64 o (word 0 = 20-bit us, word 4 = LR, word 5 = data);
stg[16][12][4] = {us, tg, 8654<<16|8658, sio idx} per pass (STG 1 = synced,
5 = CH12 start, 6 = restore done).
Prints every DFE 8830 of the ring, the per-pass stage times relative to the
nearest preceding 8830, the 8830 intervals, and the last pass' readout
(first / last line time vs 8830).  All times are the 20-bit us timer.
"""
import struct, sys
import numpy as np

DFE = 0xfc1bd4e3
M = 0xfffff


def d20(a, b):
    """b - a on the 20-bit us timer, signed."""
    return ((b - a + 0x80000) & M) - 0x80000


def load(fn):
    d = open(fn, 'rb').read()
    hd = struct.unpack_from('<8I', d, 0)
    o = 32
    tl = [struct.unpack_from('<10I', d, o + 40 * i) for i in range(160)]
    o += 40 * 160
    widx, nent = hd[3], hd[4]
    ring = [struct.unpack_from('<16I', d, o + 64 * i) for i in range(nent)]
    o += 64 * nent
    stg = np.frombuffer(d[o:o + 16 * 12 * 16], '<u4').reshape(16, 12, 4)
    o += 16 * 12 * 16
    pm = np.frombuffer(d[o:o + 256], '<u4').reshape(16, 4)
    o += 256 + 16 * 73 * 4
    pr = np.frombuffer(d[o:o + 16 * 12 * 4], '<u4').reshape(16, 12)
    # ring in write order: oldest = widx & (nent-1)
    order = [ring[(widx + i) % nent] for i in range(nent)]
    return hd, tl[:hd[2]], order, stg, pm, pr


def main(a):
    fn = a[0]
    hd, tl, ring, stg, pm, pr = load(fn)
    # unwrap ring timestamps into a monotonic timeline (entries in write order)
    ev, t, prev = [], 0, None
    base = hd[3] - hd[4]                 # absolute write index of ring[0] (oldest)
    for j, e in enumerate(ring):
        if e[4] == 0 and e[0] == 0:
            continue
        ts = e[0] & M
        if prev is not None:
            dt = (ts - prev) & M
            if dt > 0x80000:      # out of order (should not happen): keep
                dt = 0
            t += dt
        prev = ts
        ev.append((t, ts, e[4], e[5], e, base + j))
    d8 = [(t, ts, ai) for t, ts, lr, v, e, ai in ev if lr == DFE and v == 0x8830]
    print('%s: pass=%d tl_n=%d ring %d entries, %d DFE 8830' % (fn.split('/')[-1], hd[1] if hd[1] != 0xffffffff else -1, hd[2], hd[4], len(d8)))
    iv = np.diff([t for t, _, _ in d8])
    if len(iv):
        print('8830 intervals us: median %d  min %d  max %d' % (np.median(iv), iv.min(), iv.max()))
        print('  all:', ' '.join(str(int(x)) for x in iv[-60:]))
    def rel(u, idx=None):
        """(us since the preceding 8830, us to the next one).  With idx (SIO write index at the
        time of u) the preceding 8830 is the last one written before idx: no 20-bit ambiguity.
        Returns (None, None) when idx is older than the ring."""
        if idx is None or idx < base:
            return None, None
        pre = [x for x in d8 if x[2] < idx]
        nxt = [x for x in d8 if x[2] >= idx]
        b = d20(pre[-1][1], u) if pre else None
        af = d20(u, nxt[0][1]) if nxt else None
        return b, af

    names = {0: 'enter', 1: 'synced', 5: 'CH12 start', 6: 'restored'}
    print('\nper pass (us after the preceding 8830 / before the next):')
    for k in range(16):
        if not stg[k, 0, 0] and not stg[k, 5, 0]:
            continue
        row = []
        for i in (1, 5, 6):
            u = int(stg[k, i, 0]) & M
            if not stg[k, i, 0]:
                continue
            b, af = rel(u, int(stg[k, i, 3]))
            row.append('%s +%s/-%s' % (names[i], b, af))
        dma = int(pr[k, 9])
        st = int(pr[k, 10]) >> 28
        print('  pass %d: %s | dma %d us st %d rx %d o | first-move %d us last-move %d us' % (
            k, ', '.join(row), dma, st, int(pr[k, 10]) & 0xfffffff, int(pm[k, 0]), int(pm[k, 1])))
        if k and stg[k - 1, 6, 0]:
            print('          restore(k-1) -> CH12 start(k) = %d us' % d20(int(stg[k - 1, 6, 0]) & M, int(stg[k, 5, 0]) & M))
    if tl:
        mv = [r for r in tl if r[1] and r[1] < 0x80000000]
        if mv:
            f, l = mv[0], max(mv, key=lambda r: r[1])
            lb = None
            print('\nlast pass timeline: %d samples' % len(tl))
            for r in tl:
                b, af = rel(r[0] & M, r[3])
                print('   t +%s after 8830  ptr %8d o = %5d lines  tg %d' % (b, r[1], r[1] // 3240, r[2]))
            for nm, r in (('first line seen', f), ('last pointer move', l)):
                b, af = rel(r[0] & M, r[3])
                print('  %s: +%s us after 8830 (-%s to next), ptr %d o' % (nm, b, af, r[1]))
    if '--all' in a:
        t0 = ev[0][0] if ev else 0
        for t, ts, lr, v, e, ai in ev:
            if lr == DFE:
                print('%9d  %05x DFE %04x' % (t - t0, ts, v))


if __name__ == '__main__':
    main(sys.argv[1:])
