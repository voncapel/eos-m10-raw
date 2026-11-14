#!/usr/bin/env python3
"""Analyse A/LVM2.BIN (m10cine v18): 16 isolated 256-line passes of the
normal live view (each one a full take/release of PACK32), CH12 CBR entry.

  m10lvm2.py LVM2.BIN [--png sheet.png]
"""
import argparse, struct, sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m10lvn import unpack14, best_phase

NP = 16
FMT = '<8s11I3I%dI%dI%dI%dI%dI' % (NP, NP, NP, NP, NP * 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bin')
    ap.add_argument('--png')
    a = ap.parse_args()
    d = open(a.bin, 'rb').read()
    n = struct.calcsize(FMT)
    v = struct.unpack_from(FMT, d)
    if v[0] != b'M10LVM02':
        sys.exit('pas un fichier M10LVM02')
    w, lines, lb, npass, ndone, r6804, r6800, r6008, r6014, dw, dh = v[1:12]
    cbr0 = v[12:15]
    o = 15
    dt, st, endp, tick = (v[o + i * NP:o + (i + 1) * NP] for i in range(4))
    cbr = v[o + 4 * NP:o + 7 * NP]
    print('tete 6804=%08x (%d lignes) 6008=%08x 6014=%08x DSS %dx%d' % (r6804, r6804 >> 16, r6008, r6014, dw, dh))
    print('CBR CH12 avant : fn=%08x arg=%08x arme=%d' % cbr0)
    raw = d[n:]
    tiles = []
    for k in range(ndone):
        seg = raw[k * lines * lb:(k + 1) * lines * lb]
        nw = sum(1 for i in range(lines) if seg[i * lb:(i + 1) * lb] != b'\xee' * lb)
        ph = best_phase(seg, lb, lines)[0] if nw else 0
        c = cbr[3 * k:3 * k + 3]
        print('passe %2d : t=%6d ms %6d us statut %d fin +%#x lignes %3d phase %2d | CBR %08x %08x %d' % (
            k, tick[k], dt[k], st[k], endp[k], nw, ph, c[0], c[1], c[2]))
        if nw:
            img = unpack14(seg[ph:], lines * w - 32, 0)
            img = np.concatenate([img, np.zeros(lines * w - len(img), img.dtype)]).reshape(lines, w).astype(int)
            tiles.append(img)
    if a.png and tiles:
        from PIL import Image
        im = np.vstack([np.vstack([t, np.full((4, w), 16383)]) for t in tiles])
        im = ((np.clip(im - 2048, 0, 6000) / 6000) ** 0.45 * 255).astype(np.uint8)
        Image.fromarray(im[::2, ::2]).save(a.png)
        print('apercu ->', a.png)


if __name__ == '__main__':
    main()
