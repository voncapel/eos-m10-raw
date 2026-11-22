#!/usr/bin/env python3
"""Canon EOS M10 Wide 1:3 (ImgMode 1, 1728 x H) Hybrid CMOS AF II focus pixel map.

The AF lattice repeats every 30 rows x 8 columns of the active area (sensor x0 = 0x30, y0 = 32, CFA RGGB).
8 sites per tile, (y % 30, x % 8):
    R: (6, 0) (18, 4) (20, 2) (20, 6)      B: (3, 7) (21, 3) (25, 1) (25, 5)
No green photosite is touched; 8 / 240 = 3.333 % of all pixels.

    m10wide_fpm.py --export-fpm OUT.fpm [--width 1728] [--height 1800|1440]
    m10wide_fpm.py --check-mlv FILE.MLV         frame 0: decode (lj92d), fix_wide_raw(), row_hp_std before/after
"""
import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TILE_H, TILE_W = 30, 8
SITES_R = ((6, 0), (18, 4), (20, 2), (20, 6))
SITES_B = ((3, 7), (21, 3), (25, 1), (25, 5))
SITES = SITES_R + SITES_B
HERE = os.path.dirname(os.path.abspath(__file__))


def site_mask(h, w):
    """Boolean (h, w) mask of the focus pixels; (0, 0) = top-left of the active area (an R photosite)."""
    m = np.zeros((h, w), bool)
    for y, x in SITES:
        m[y::TILE_H, x::TILE_W] = True
    return m


def site_list(w, h):
    """Focus pixels as (x, y), row-major."""
    ys, xs = np.nonzero(site_mask(h, w))
    return list(zip(xs.tolist(), ys.tolist()))


def export_fpm(path, w=1728, h=1800):
    pts = site_list(w, h)
    with open(path, 'w') as f:
        f.write('# Canon EOS M10 Wide 1:3 ImgMode 1 focus pixel map (Hybrid CMOS AF II)\n')
        f.write('# raw %dx%d, active origin x0=0x30 y0=32, RGGB, period %d rows x %d cols\n' % (w, h, TILE_H, TILE_W))
        f.write('# R (y%%30,x%%8): %s  B: %s\n' % (' '.join(map(str, SITES_R)), ' '.join(map(str, SITES_B))))
        f.write('# %d pixels (%.3f%% of %d), 0%% green\n' % (len(pts), 100.0 * len(pts) / (w * h), w * h))
        f.write('# X Y\n')
        f.writelines('%d %d\n' % p for p in pts)
    return len(pts)


def fix_wide_raw(arr):
    """Copy of arr with every focus pixel replaced by the mean of its clean same-channel 4-neighbours
    (L / R / U / D at +-2). Neighbours outside the frame or on another focus pixel are skipped."""
    a = np.asarray(arr)
    h, w = a.shape
    m = site_mask(h, w)
    src = a.astype(np.float64)
    acc = np.zeros((h, w)); n = np.zeros((h, w))
    for dy, dx in ((0, -2), (0, 2), (-2, 0), (2, 0)):
        ys, yd = slice(max(dy, 0), h + min(dy, 0)), slice(max(-dy, 0), h + min(-dy, 0))
        xs, xd = slice(max(dx, 0), w + min(dx, 0)), slice(max(-dx, 0), w + min(-dx, 0))
        ok = ~m[ys, xs]
        acc[yd, xd] += np.where(ok, src[ys, xs], 0.0)
        n[yd, xd] += ok
    out = a.copy()
    fix = m & (n > 0)
    out[fix] = np.rint(acc[fix] / n[fix]).astype(a.dtype)
    return out


def row_hp_std(a, box=9):
    """Per CFA plane: std of (row-mean profile - box-filtered profile) over interior rows.
    The 30-row AF lattice shows up as periodic row offsets in the R / B planes."""
    a = a.astype(np.float64)
    h, w = a.shape
    k = np.ones(box) / box
    res = {}
    for name, oy, ox in (('R', 0, 0), ('Gr', 0, 1), ('Gb', 1, 0), ('B', 1, 1)):
        prof = a[oy::2, ox + 2 * (w // 16):w - w // 8:2].mean(1)
        hp = prof - np.convolve(prof, k, mode='same')
        res[name] = float(hp[box:-box].std())
    return res


def site_rms(a):
    """RMS of (pixel - 4-neighbour mean) at the focus pixels vs the other R / B photosites."""
    a = a.astype(np.float64)
    h, w = a.shape
    p = np.pad(a, 2, mode='reflect')
    d = a - (p[2:-2, :-4] + p[2:-2, 4:] + p[:-4, 2:-2] + p[4:, 2:-2]) / 4
    m = site_mask(h, w)
    rb = np.zeros((h, w), bool); rb[0::2, 0::2] = True; rb[1::2, 1::2] = True
    return float(np.sqrt((d[m] ** 2).mean())), float(np.sqrt((d[rb & ~m] ** 2).mean()))


def find_lj92d():
    for p in ('/tmp/lj92d', '/tmp/ljc/lj92d'):
        if os.access(p, os.X_OK):
            return p
    out = os.path.join(tempfile.gettempdir(), 'lj92d')
    subprocess.run(['cc', '-O2', '-o', out, os.path.join(HERE, 'lj92d.c')], check=True)
    return out


def check_mlv(path):
    import m10ljmlv as M
    M.LJ = find_lj92d()
    bpp, black, white = M.mlv_info(path)
    k, parts = next(M.frames(path))
    a = M.decode(parts, shift=0 if bpp == 14 else 4)
    if a is None:
        sys.exit('frame %d: lj92d decode failed' % k)
    f = fix_wide_raw(a)
    m = site_mask(*a.shape)
    print('%s frame %d: %dx%d %d-bit black %.0f white %d, %d focus px (%.3f%%), %d changed'
          % (os.path.basename(path), k, a.shape[1], a.shape[0], bpp, black, white, int(m.sum()), 100.0 * m.mean(),
             int((f != a).sum())))
    assert (f[~m] == a[~m]).all()
    for tag, img in (('before', a), ('after ', f)):
        s = row_hp_std(img); fp, ref = site_rms(img)
        print('%s row_hp_std R %.2f Gr %.2f Gb %.2f B %.2f | site resid rms %.1f (other R/B %.1f)'
              % (tag, s['R'], s['Gr'], s['Gb'], s['B'], fp, ref))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--export-fpm', metavar='OUT.fpm')
    ap.add_argument('--width', type=int, default=1728)
    ap.add_argument('--height', type=int, default=1800)
    ap.add_argument('--check-mlv', metavar='PATH')
    a = ap.parse_args(argv)
    if not (a.export_fpm or a.check_mlv):
        ap.error('nothing to do: --export-fpm and/or --check-mlv')
    if a.export_fpm:
        n = export_fpm(a.export_fpm, a.width, a.height)
        print('%s: %d focus pixels (%dx%d, %.3f%%)' % (a.export_fpm, n, a.width, a.height, 100.0 * n / (a.width * a.height)))
    if a.check_mlv:
        check_mlv(a.check_mlv)


if __name__ == '__main__':
    main()
