#!/usr/bin/env python3
"""Analyse A/LVM.BIN (m10cine v17): Canon EVF job/state dump + up to 8
re-armed 256-line passes of the normal live view (PACK32 14-bit pack 2).

  m10lvm.py LVM.BIN [--png sheet.png]
"""
import argparse, struct, sys, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m10lvn import unpack14

NP = 8
FMT = '<8s9I%dI%dI%dI%dI96I96I' % (NP, NP, NP, NP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bin')
    ap.add_argument('--png')
    a = ap.parse_args()
    d = open(a.bin, 'rb').read()
    n = struct.calcsize(FMT)
    v = struct.unpack_from(FMT, d)
    if v[0] != b'M10LVM01':
        sys.exit('pas un fichier M10LVM01')
    w, lines, lb, npass, ndone, r6804, r6800, r6008, r6014 = v[1:10]
    o = 10
    dt, st, endp, gap = (v[o + i * NP:o + (i + 1) * NP] for i in range(4))
    job = v[o + 4 * NP:o + 4 * NP + 96]
    est = v[o + 4 * NP + 96:o + 4 * NP + 192]
    print('tete 6804=%08x (%d lignes) 6800=%08x 6008=%08x 6014=%08x' % (r6804, r6804 >> 16, r6800, r6008, r6014))
    print('job EVF 0x697e0 :', ' '.join('%x' % x for x in job[:24]))
    print('etat EVF 0xc8f0 :', ' '.join('%x' % x for x in est[:24]))
    print('  job[0]=%d (type), job[4]=%#x (adresse), job[0x14/4]=%d (passes ?), job[0x24/4]=%#x (table)' % (
        job[0], job[1], job[5], job[9]))
    raw = d[n:]
    tiles = []
    for k in range(ndone):
        seg = raw[k * lines * lb:(k + 1) * lines * lb]
        nw = sum(1 for i in range(lines) if seg[i * lb:(i + 1) * lb] != b'\xee' * lb)
        print('passe %d : %6d us, statut %d, fin +%#x (%d lignes), ecart %d us, lignes ecrites %d' % (
            k, dt[k], st[k], endp[k], endp[k] // lb, gap[k], nw))
        if nw:
            img = unpack14(seg, lines * w - 8, 0)
            img = np.concatenate([img, np.zeros(8, img.dtype)]).reshape(lines, w).astype(int)
            tiles.append(img)
    if a.png and tiles:
        from PIL import Image
        im = np.vstack([np.vstack([t, np.full((4, w), 16383)]) for t in tiles])
        im = ((np.clip(im - 2048, 0, 6000) / 6000) ** 0.45 * 255).astype(np.uint8)
        Image.fromarray(im[:, ::2]).save(a.png)
        print('apercu ->', a.png)


if __name__ == '__main__':
    main()
