#!/usr/bin/env python3
"""live107: where does the sensor data stop in a tall-head pass?

    m10holdan.py FILE_LVX3.BIN [...]

Beyond the last line the sensor really sends, the stream is a digital hold: the same pair of
values repeated (period 2 = the two output channels), exactly 1,1 at the HEAD output.  For each
pass: rows before the 852 fill (frame end), first sample of the hold (row, column), the held
pair, mean / sd of the image rows, optical black.  The hold start is the metric to move.
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m10lvx3dec as D


def passes(fn):
    d = open(fn, 'rb').read()
    w, lines, lb, npass, ndone = D.header(d)
    bpp = lb * 8 // w
    for p in range(ndone):
        yield w, lines, D.decode(d[D.HDR + p * lines * lb:D.HDR + (p + 1) * lines * lb], bpp, w, lines, lb, 0).astype(int)


def hold(a, w, need=3000):
    """(end_row, hold_index or None, pair)"""
    ob = a[:, :72].mean(1)
    fill = np.nonzero(np.abs(ob - 852.5) < 1)[0]
    end = int(fill.min()) if len(fill) else a.shape[0]
    f = a[:end].reshape(-1)
    if len(f) < need + 4:
        return end, None, None
    same = (f[2:] == f[:-2]).astype(np.int32)
    cs = np.concatenate(([0], np.cumsum(same)))
    run = cs[need:] - cs[:-need]
    idx = np.nonzero(run == need)[0]
    idx = idx[idx > 40 * w]                 # the top rows can be flat too (optical black / CMOS 7)
    if not len(idx):
        return end, None, None
    i = int(idx[0]) + 2
    return end, i, (int(f[i]), int(f[i + 1]))


def describe(fn):
    out = []
    for w, lines, a in passes(fn):
        end, i, pair = hold(a, w)
        body = a[100:min(end, 1100), 200:1700] if end > 200 else a[:1, :1]
        s = 'end %4d' % end
        s += ' hold@%4d:%-4d %s' % (i // w, i % w, pair) if i is not None else ' no hold'
        s += ' mean %.0f sd %.0f ob %.0f' % (body.mean(), body.std(), a[100:min(end, 1100), :72].mean() if end > 200 else 0)
        out.append(s)
    return out


if __name__ == '__main__':
    for fn in sys.argv[1:]:
        try:
            r = describe(fn)
        except Exception as e:
            r = ['error %r' % e]
        print('%-34s %s' % (os.path.basename(fn).replace('_LVX3.BIN', ''), ' | '.join(r) or 'no pass'))
