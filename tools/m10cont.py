#!/usr/bin/env python3
"""live109: continuity of a single-pass capture (LVX3.BIN): first row where
same-colour rows two apart stop correlating (packet loss / shifted packets).

    m10cont.py FILE [FILE ...]
"""
import os, sys, warnings
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m10level as L

warnings.filterwarnings('ignore')


def first_bad(img, thr=0.5):
    x = img[28:, 84:].astype(np.float32)
    x = x - x.mean(1, keepdims=True)
    n = np.sqrt((x * x).sum(1)) + 1e-6
    c = (x[:-2] * x[2:]).sum(1) / (n[:-2] * n[2:])
    sd = x.std(1)
    bad = np.nonzero((c < thr) & (sd[:-2] > 2) & (sd[2:] > 2))[0]
    return (int(bad[0]) + 28 if len(bad) else None), len(bad)


if __name__ == '__main__':
    for fn in sys.argv[1:]:
        for k, img in enumerate(L.passes(fn)):
            fb, nb = first_bad(img)
            print('%-34s pass %d rows %d  first bad row %s  bad rows %d' % (os.path.basename(fn)[:34], k, img.shape[0], fb, nb))
