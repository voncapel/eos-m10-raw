#!/usr/bin/env python3
"""Analyse the normal live view captures of m10cine v15 (A/LV?_NNNN.RAW,
header M10LVN01, 14-bit PACK32 pack 2 single stream, 1808 px/line).

  m10lvn.py LVA_1024.RAW [--png out.png]

Reports: bit phase, black level, colour structure (Bayer 2x2 means per half
line, same tests that showed G|R planes in probe21-26), vertical/horizontal
smoothness at lags 1-4 (line skipping vs binning), frame boundary rows
(blanking), and saves a preview.
"""
import argparse, struct, sys
import numpy as np

HDR = '<8s18I'


def unpack14(buf, nsamp, byte_off):
    w = np.frombuffer(buf[byte_off:byte_off + (nsamp * 14 + 15) // 16 * 2 + 2], dtype='<u2')
    bits = np.unpackbits(w.astype('>u2').view(np.uint8))[:nsamp * 14].reshape(nsamp, 14)
    return (bits.astype(np.uint32) * (1 << np.arange(13, -1, -1, dtype=np.uint32))).sum(1)


def best_phase(raw, lb, lines):
    base = lb * (lines // 2)
    sc = []
    for j in range(7):
        v = unpack14(raw, 400, base + 4 * j).astype(int)
        sc.append(np.abs(v[2:] - v[:-2]).mean())
    return 4 * int(np.argmin(sc)), sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('raw')
    ap.add_argument('--png')
    a = ap.parse_args()
    d = open(a.raw, 'rb').read()
    n = struct.calcsize(HDR)
    v = struct.unpack_from(HDR, d)
    if v[0] != b'M10LVN01':
        sys.exit('pas un fichier M10LVN01')
    (w, lines, lb, bits, r6800, r6804, r6008, r6014, dw, dh, dfl, dt, st, endp, ph0) = v[1:16]
    raw = d[n:]
    if len(d) >= n + 8 + 96 * 4 and lines * lb + n + 8 + 96 * 4 == len(d):   # v16 header (+ step, ntr, trace)
        step, ntr = struct.unpack_from('<2I', d, n)
        tr = struct.unpack_from('<%dI' % ntr, d, n + 8)
        raw = d[n + 8 + 4 * ntr:]
        nz = [t for t in tr if t]
        print('  v16 etape %d, trace pointeur (lignes, 1 point/ms) : %s' % (
            step, ' '.join(str(t // lb) for t in tr[:60])))
        if len(nz) > 2:
            # line rate from the steady part of the trace
            sl = [(tr[i + 1] - tr[i]) / lb for i in range(len(tr) - 1) if tr[i] and tr[i + 1] > tr[i]]
            if sl:
                print('  debit pendant le transfert : %.1f lignes/ms (mediane)' % sorted(sl)[len(sl) // 2])
    print('%s : %d lignes x %d px, statut %d, DMA %d us, fin +%#x (%d lignes)' % (
        a.raw, lines, w, st, dt, endp, endp // lb))
    print('  tete 6800=%08x 6804=%08x (%d lignes), 6008=%08x 6014=%08x, DSS %dx%d flags %08x' % (
        r6800, r6804, r6804 >> 16, r6008, r6014, dw, dh, dfl))
    good = min(lines, endp // lb) if endp else lines
    ph, sc = best_phase(raw, lb, good)
    print('  phase %d octets (scores %s)' % (ph, ' '.join('%.0f' % x for x in sc)))
    img = unpack14(raw, good * w - 8, ph)
    img = np.concatenate([img, np.zeros(8, img.dtype)]).reshape(good, w).astype(int)
    print('  min/mediane/max %d / %d / %d' % (img.min(), np.median(img), img.max()))
    half = w // 2
    for name, (r0, c0) in (('(0,0)', (0, 0)), ('(0,1)', (0, 1)), ('(1,0)', (1, 0)), ('(1,1)', (1, 1))):
        q = img[r0::2, c0::2]
        print('  parite %s : moitie G %5d  moitie D %5d' % (name, q[:, 20:half // 2 - 20].mean(), q[:, half // 2 + 20:-20].mean()))
    row = img[good // 2, 40:-40]
    col = img[20:-20, w // 3]
    print('  lissage horizontal lag1-4 :', ' '.join('%.1f' % np.abs(row[p:] - row[:-p]).mean() for p in (1, 2, 3, 4)))
    print('  lissage vertical   lag1-4 :', ' '.join('%.1f' % np.abs(col[p:] - col[:-p]).mean() for p in (1, 2, 3, 4)))
    cc = np.corrcoef(img[:, 40:half - 40].ravel(), img[:, half + 40:w - 40].ravel())[0, 1]
    print('  correlation moitie G / moitie D : %.3f (proche de 1 = deux plans de la meme image)' % cc)
    dv = np.abs(img[2:] - img[:-2]).mean(1)
    rows = np.argsort(dv)[-3:][::-1]
    print('  vertical breaks (frame start?) at rows:', ', '.join('%d (%.0f)' % (r, dv[r]) for r in rows),
          'mediane %.0f' % np.median(dv))
    flat = np.where(img.std(1) < 20)[0]
    if len(flat):
        print('  lignes plates (blanking) : %d, premiere %d derniere %d' % (len(flat), flat[0], flat[-1]))
    if a.png:
        from PIL import Image
        im = ((np.clip(img - 2048, 0, 6000) / 6000) ** 0.45 * 255).astype(np.uint8)
        Image.fromarray(im).save(a.png)
        print('  apercu ->', a.png)


if __name__ == '__main__':
    main()
