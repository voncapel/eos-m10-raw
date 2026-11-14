#!/usr/bin/env python3
"""live109: RAW signal level of a Film 3x3 single-pass probe (LVX3.BIN).

    m10level.py FILE [FILE ...]

Per pass: OB black (cols 0-71, rows 28+), active-area median / mean / p99
above black (rows 28+, cols 84+), per CFA cell (R G1 G2 B), OB temporal sd
(pass 0 vs 1).
"""
import sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m10lvx3dec as D


def passes(fn):
    d = open(fn, 'rb').read()
    w, lines, lb, npass, ndone = D.header(d)
    bpp = lb * 8 // w; fb = lines * lb
    for k in range(ndone):
        yield D.decode(d[D.HDR + k * fb: D.HDR + (k + 1) * fb], bpp, w, lines, lb, 0).astype(np.float32)


def main(a):
    for fn in a:
        P = list(passes(fn))
        res = []
        for img in P:
            ob = float(np.median(img[28:, :72]))
            act = img[28:1180, 84:] - ob
            cells = [float(np.median(act[i::2, j::2])) for i in (0, 1) for j in (0, 1)]
            res.append((ob, float(np.median(act)), float(act.mean()), float(np.percentile(act, 99)), cells))
        tsd = float(np.std(P[0][28:, :72] - P[1][28:, :72]) / np.sqrt(2)) if len(P) > 1 else float('nan')
        r = res[-1]
        print('%-28s black %.1f  med %.1f mean %.1f p99 %.0f  RGGB %s  OB tsd %.2f' % (
            os.path.basename(fn)[:28], r[0], r[1], r[2], r[3], [round(x, 1) for x in r[4]], tsd))


if __name__ == '__main__':
    main(sys.argv[1:])
