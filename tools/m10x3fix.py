#!/usr/bin/env python3
"""r145: repair a Film 1x3 compressed MLV recorded with the slow sensor line (TgPixelRes 600/640 clk)
and write a plain uncompressed 12-bit MLV that MLV App opens.

    m10x3fix.py IN.MLV OUT.MLV [--dark DARK_LVX3.BIN ...] [--off 136] [--first a] [--last b]

Defects measured on r145 (sub-agent vision-stripes, 2026-11-17):
  1. column offset FPN confined to raw columns x % 8 in {4..7}, opposite sign on even / odd rows
     (stable, measured on lens-cap frames r142_dark_L600/L640) -> subtracted first;
  2. even rows (R / G1): raw columns x % 8 in {4..7} hold the block 8 columns to the right
     (E[x] = T[x + 8]) -> even rows de-permuted: T[8k+4..7] = E[8(k-1)+4..7];
  3. on-sensor AF pixel grid left uncorrected after a head error -> m10mlv.fix_af ('x3' 1x3 geometry);
  4. a kept head error moves the raster 12 px (window offset 136 -> 124, phase mod 8 changes):
     the offset is tracked per frame from the column profile of the dark FPN.
Raw column x_1808 = x_1536 + off (encoder window EOFF: row 28, column 136).
Output: 12-bit samples (14-bit container >> 2), black 512, white 4095, same geometry, RAWC 3x binning.
"""
import os, struct, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m10ljmlv as L
import m10mlv as MV
import m10holdan as H

W_FULL = 1808
CROP_L = 8           # left columns without a source block for the even-row de-permutation
AF_TOP, AF_C0 = 24, 136   # r145: AF grid measured at window rows 91-1067 / cols 108-1523 = m10mlv.AF_BOX (115-1091, 244-1659)


def dark_profile(files):
    """per-column offset (12-bit codes, mean 0) for even and odd rows, full 1808 width.
    r149: medians (PREFIFO darks hold raw AF cells at ~0 that bias a mean), then median over the files."""
    cols = []
    for fn in files:
        ps = np.stack([a[:1184].astype(np.float32) for w, l, a in H.passes(fn)])
        m = np.median(ps, 0)[40:1170]
        cols.append(np.array([np.median(m[p::2], 0) for p in (0, 1)], np.float64))
    prof = np.median(np.stack(cols), 0)
    for p in (0, 1):
        prof[p] -= np.median(prof[p, 80:1780])
    return prof


# r149: lens-cap PREFIFO (RSEL=22) darks at line 640, Film 1x3, 25 independent arm/commit cycles whose
# settings left the column FPN unchanged (r149 sweep); leave-one-out residual 0.25 codes (vs 5.9 raw).
PREFIFO640 = ['base', 'dfe_scale', 'dfe_scale0', 'dfe_scale0p814', 'tgshift', 'tgshift238', 'tgshift0',
              'cmos_30xf00', 'cmos_30xf0c', 'cmos_30xf18', 'cmos_41', 'cmos_43', 'cmos_60x789', 'cmos_60x78a',
              'cmos_60x78f', 'cmos_60x79b', 'cmos_60x7ab', 'cmos_80x000', 'cmos_80x400', 'cmos_50x21',
              'cmos_50x22', 'cmos_50x23', 'cmos_50x28', 'cmos_50x2c', 'cmos_50x30']


def g1g2_err(x):
    """mean |G1 - interpolated G2| (scene-independent Bayer consistency, low = rows aligned)."""
    G1 = x[0::2, 1::2]; G2 = x[1::2, 0::2]
    n = min(G1.shape[0], G2.shape[0]) - 1
    g1 = G1[1:n, :-1]
    it = (G2[0:n - 1, :-1] + G2[0:n - 1, 1:] + G2[1:n, :-1] + G2[1:n, 1:]) / 4
    return float(np.mean(np.abs(g1 - it)))


def track_off(x, prev):
    """window offset with the right phase mod 8 (G1/G2 test), closest to prev (head-error shifts are 12 px)."""
    best = None
    for ph in (0, 4):
        cand = [o for o in range(prev - 24, prev + 25, 4) if (o - prev) % 8 == ph]
        e = g1g2_err(depermute(x.copy(), cand[0]))
        if best is None or e < best[0]:
            best = (e, cand)
    cand = best[1]
    if (cand[0] - prev) % 8 == 0:
        return prev, best[0]
    return min(cand, key=lambda o: (abs(abs(o - prev) - 12), abs(o - prev))), best[0]


def depermute(img, off):
    """even rows: block columns (x+off)%8 in 4..7 take the block 8 raw columns to the left."""
    w = img.shape[1]
    x = np.arange(w)
    xr = x + off
    sel = (xr % 8 >= 4) & (x - 8 >= 0)
    ev = img[0::2]
    src = ev[:, x[sel] - 8].copy()
    ev[:, x[sel]] = src
    img[0::2] = ev
    return img


RB_BAD = ((0, (0, 4)), (1, (3, 7)))   # r146: (row parity, sensor col % 8) of the R / B samples that are
                                      # misplaced in 1x3 binning (also at the native line 521, r138):
                                      # same-colour error 550-700 vs 20 elsewhere -> magenta dotted edges


def fix_rb(x, off):
    """r146: rebuild the misplaced R (even rows, sensor col%8 in 0,4) and B (odd rows, 3,7) samples by
    colour-difference interpolation: G at the site + mean(C - G) of the same-colour neighbours +-2 columns."""
    h, w = x.shape
    xs = np.arange(w)
    src = x.copy()

    def gat(r, c):
        return (src[r, c - 1] + src[r, c + 1] + src[r - 1, c] + src[r + 1, c]) / 4
    for par, bad in RB_BAD:
        rows = np.arange(2 + par, h - 2, 2)
        for ph in bad:
            cs = xs[((xs + off) % 8 == ph) & (xs >= 4) & (xs < w - 4)]
            R, C = np.meshgrid(rows, cs, indexing='ij')
            x[R, C] = gat(R, C) + ((src[R, C - 2] - gat(R, C - 2)) + (src[R, C + 2] - gat(R, C + 2))) / 2
    return x


def grid_table(x):
    """r147: 10 x 8 table (window row % 10, window col % 8) of the mean error of each sample vs its
    vertical same-colour neighbours, measured on vertical edges (strong horizontal gradient, weak
    vertical one). On-sensor AF pixels show 500-900 there (Canon's own correction is horizontal and
    fails on vertical edges; after a head error it stops altogether), normal cells 10-20."""
    h, w = x.shape
    rows = np.arange(8, h - 8); xs = np.arange(8, w - 8)
    tab = np.zeros((10, 8))
    for rm in range(10):
        rr = rows[rows % 10 == rm]
        for cm in range(8):
            cs = xs[xs % 8 == cm]
            v = x[np.ix_(rr, cs)]; up = x[np.ix_(rr - 2, cs)]; dn = x[np.ix_(rr + 2, cs)]
            gh = np.abs(x[np.ix_(rr, cs - 2)] - x[np.ix_(rr, cs + 2)]); gv = np.abs(up - dn)
            m = (gh > 300) & (gv < 60)
            e = np.mean(np.abs(v - (up + dn) / 2)[m]) if m.sum() > 50 else 0
            # bright flat areas: AF cells read ~0.6x, cells next to them ~1.45x (live102) -> relative error x 600
            ref = (up + dn + x[np.ix_(rr, cs - 2)] + x[np.ix_(rr, cs + 2)]) / 4 - 512
            f = (gh < 60) & (gv < 60) & (ref > 150)          # R / B are dim (frosted glass: R ~280 over black)
            r = 600 * np.median(np.abs((v[f] - 512) / ref[f] - 1)) if f.sum() > 50 else 0
            tab[rm, cm] = max(e, r)
    return tab


def fix_grid(x, thr=30.0):
    """r147: repair the AF-pixel cells found by grid_table() (> max(thr, 2.5 x median)) with an
    edge-directed same-colour interpolation (vertical / horizontal weighted by 1 / gradient).
    Cells repeat every 10 rows: their vertical neighbours (+-2 rows) are always normal samples."""
    tab = grid_table(x)
    lim = max(thr, 2.5 * float(np.median(tab[tab > 0])))
    cells = [(int(r), int(c)) for r, c in zip(*np.nonzero(tab > lim))]
    h, w = x.shape
    s = x.copy()
    for rm, cm in cells:
        rr = np.arange(4, h - 4); rr = rr[rr % 10 == rm]
        cc = np.arange(4, w - 4); cc = cc[cc % 8 == cm]
        R, C = np.meshgrid(rr, cc, indexing='ij')
        v = (s[R - 2, C] + s[R + 2, C]) / 2; hz = (s[R, C - 2] + s[R, C + 2]) / 2
        wv = 1 / (np.abs(s[R - 2, C] - s[R + 2, C]) + 8); wh = 1 / (np.abs(s[R, C - 2] - s[R, C + 2]) + 8)
        x[R, C] = (wv * v + wh * hz) / (wv + wh)
    return x, cells


def flat_despeckle(x, rel=0.09):
    """r147: local AF-pixel lines (row period 30, col period 8, only in part of the frame, ~+18 %)
    escape the whole-frame cell table: in flat areas (same-colour neighbours agree within 40
    codes) replace a sample that deviates from their mean by more than `rel`."""
    s = x.copy()
    up, dn = np.roll(s, 2, 0), np.roll(s, -2, 0)
    l, r = np.roll(s, 2, 1), np.roll(s, -2, 1)
    ref = (up + dn + l + r) / 4
    sig = ref - 512
    m = (np.abs(up - dn) < 40) & (np.abs(l - r) < 40) & (np.abs(up - l) < 60) & (sig > 100)
    m &= np.abs(s - ref) > np.maximum(rel * sig, 25)
    m[:4] = m[-4:] = False; m[:, :4] = m[:, -4:] = False
    x[m] = ref[m]
    return int(m.sum())


def seam_rows(cur, prev, nxt):
    """r146: first row of a head-error seam (rows below = another part of the sensor), or None.
    Per-row mean |difference| to BOTH neighbour frames (green plane, 12-bit codes)."""
    def g(a):
        a = a.astype(np.float32)
        return (a[0::2, 1::2] + a[1::2, 0::2]) / 2
    c, p, n = g(cur), g(prev), g(nxt)
    # motion-tolerant: each 20-row band (half-res) must match prev or next within a +-10 px shift;
    # bands from another sensor area / another frame do not (error 200-900 vs 10-60 codes)
    H, W = c.shape
    B, S = 20, 5
    errs = []
    for r0 in range(S, H - B - S, B):
        a = c[r0:r0 + B, 2 * S:W - 2 * S]
        best = 1e9
        for ref in (p, n):
            for dy in range(-S, S + 1):
                rb = ref[r0 + dy:r0 + dy + B]
                for dx in range(-2 * S, 2 * S + 1, 2):
                    e = float(np.mean(np.abs(a[::2, ::4] - rb[::2, 2 * S + dx:W - 2 * S + dx:4])))
                    best = min(best, e)
        errs.append(best)
    errs = np.array(errs)
    base = float(np.percentile(errs, 20))
    bad = errs > max(3.0 * base, 120.0)
    if bad.sum() < 2:
        return None
    tail = np.cumsum(bad[::-1])[::-1] / np.arange(len(bad), 0, -1)
    i0 = int(np.argmax((tail > 0.6) & bad))
    return 2 * (S + B * i0)


def pack12(img):
    """12-bit samples -> MSB-first bitstream in u16 LE words (PACK32 pack-2 / MLV raw)."""
    v = img.astype(np.uint16).ravel()
    bits = ((v[:, None] >> np.arange(11, -1, -1, dtype=np.uint16)) & 1).astype(np.uint8).ravel()
    by = np.packbits(bits)
    return by.view('>u2').astype('<u2').tobytes()


def main(a):
    if len(a) < 2:
        print(__doc__); return 2
    src, dst = a[0], a[1]
    opt = {}; darks = []
    i = 2
    while i < len(a):
        if a[i] == '--dark': darks.append(a[i + 1]); i += 2
        else: opt[a[i]] = a[i + 1]; i += 2
    here = os.path.dirname(os.path.abspath(__file__))
    if not darks and '--fixoff' in opt:                     # PREFIFO output: PREFIFO darks (r149)
        darks = [os.path.join(here, '..', 'captures', 'live71', 'r148_sw_L640_%s_LVX3.BIN' % t) for t in PREFIFO640]
        darks = [d for d in darks if os.path.exists(d)]
        print('PREFIFO dark master: %d captures' % len(darks))
    if not darks:
        darks = [os.path.join(here, '..', 'captures', 'live142', 'r142_dark_L%d_LVX3.BIN' % n) for n in (600, 640)]
    prof = dark_profile(darks)
    off = int(opt.get('--off', 136))
    first = int(opt.get('--first', 0)); last = int(opt['--last']) if '--last' in opt else None
    bpp_in, black_in, white_in = L.mlv_info(src)
    fps1000 = struct.unpack_from('<I', open(src, 'rb').read(64), 44)[0]
    frames = []
    shifts = 0
    for k, p in L.frames(src):
        if k < first or (last is not None and k >= last):
            continue
        img = L.decode(p, shift=0)
        if img is None:
            continue
        x = img.astype(np.float64) / 4.0                    # 14-bit container -> 12-bit codes
        o2, sc = (off, 0) if '--fixoff' in opt else track_off(x, off)   # r147: RSEL=22 (PREFIFO) keeps the window fixed
        if o2 != off:
            shifts += 1; print('frame %d: window offset %d -> %d (G1/G2 err %.1f)' % (k, off, o2, sc)); off = o2
        for p_ in (0, 1):
            x[p_::2] -= prof[p_, off:off + x.shape[1]]
        x = depermute(x, off)
        if os.environ.get('GRIDFIX', '1') != '0':           # r147: replaces fix_af + fix_rb (AF cells located per frame)
            x, cells = fix_grid(x)
            x, cells2 = fix_grid(x)                         # second pass: cells next to the AF grid (~1.45x)
            x, cells3 = fix_grid(x); cells2 += cells3
            nfl = flat_despeckle(x)
            if k % 50 == 0: print('frame %d: flat despeckle %d' % (k, nfl))
            if k % 50 == 0 or k in (12, 13, 15, 16): print('frame %d: AF cells %s + %s' % (k, cells, cells2))
        y = np.clip(np.round(x), 0, 4095).astype(np.uint16)
        h, w = y.shape
        top = AF_TOP                                       # 1x3 AF grid ('x3' geometry) is in raw row - 4 coordinates
        c0 = off + 12                                      # AF grid fixed on the sensor: window col c = sensor col c + off; box col = sensor col + 12 (r145: off 124 -> 136)
        full = np.full((h + top + 4, w + c0 + 8), 512, np.uint16)
        full[top:top + h, c0:c0 + w] = y
        naf = 0
        if os.environ.get('GRIDFIX', '1') == '0':
            naf = MV.fix_af(full, 512, margin=80, detect=500, geom='x3')   # old fixed-geometry AF repair
        if os.environ.get('RBFIX', '0') != '0':             # r146 fix_rb: too broad (4/5 rows were fine), off by default
            win = full[top:top + h, c0:c0 + w].astype(np.float64)
            full[top:top + h, c0:c0 + w] = np.clip(np.round(fix_rb(win, off)), 0, 4095).astype(np.uint16)
        # residual AF / dead samples: same-colour median of 4 neighbours when the sample is far below them
        f = full.astype(np.int32)
        nb = np.stack([np.roll(f, 2, 0), np.roll(f, -2, 0), np.roll(f, 2, 1), np.roll(f, -2, 1)])
        med = np.median(nb, 0)
        bad = (f < 512 - 40) & (med - f > 120)
        bad[:4] = bad[-4:] = False
        f[bad] = med[bad].astype(np.int32); full[:] = f.astype(np.uint16); naf += int(bad.sum())
        if k % 50 == 0: print('frame %d: off %d, AF fixed %d' % (k, off, naf), flush=True)
        frames.append((k, full[top:top + h, c0 + CROP_L:c0 + w].copy()))   # drop the first columns (de-permute fallback)
    if not frames:
        print('no frame'); return 1
    # r146: head-error frames carry a seam (rows below it come from another sensor area / another
    # frame): replace the whole frame with the previous clean output (a repeated frame is less
    # visible than a tear while panning).
    nrep = 0
    if os.environ.get('SEAMFIX', '1') != '0':
        # candidates: head errors listed in the module log ('he at frame N') and the frame after each;
        # without a log every frame is a candidate (camera motion can then be mistaken for a seam).
        log = opt.get('--log') or src.replace('_M10X3.MLV', '_M10CINE.LOG')
        cand = None
        if os.path.exists(log):
            he = []
            for ln in open(log, errors='replace'):
                if 'he_n=' in ln: he = []                    # keep the list of the last run only
                if 'he at frame' in ln: he.append(int(ln.split('he at frame')[1].split()[0]))
            cand = set(he) | {f + 1 for f in he} | {f + 2 for f in he}   # r147: PREFIFO, the raster shift lands on N+2
            print('head errors from %s: %s' % (os.path.basename(log), sorted(he)))
        idx = {k: i for i, (k, _) in enumerate(frames)}
        test = [idx[k] for k in sorted(cand) if k in idx] if cand is not None else range(1, len(frames) - 1)
        bad = [False] * len(frames)
        for i in test:
            if i == 0 or i == len(frames) - 1: continue
            j = i + 1
            while j < len(frames) - 1 and cand is not None and frames[j][0] in cand: j += 1
            pv = frames[i - 1][1] if not bad[i - 1] else frames[max(b for b in range(i) if not bad[b])][1]
            s = seam_rows(frames[i][1], pv, frames[j][1])
            if s is None and '--fixoff' in opt:          # r147: whole-frame raster roll after an error (r147_F: -2 rows / -520 px)
                def gplane(z):
                    z = z.astype(np.float32); return (z[0::2, 1::2] + z[1::2, 0::2]) / 2
                ga, gb = gplane(frames[i][1]), gplane(pv)
                ga -= ga.mean(); gb -= gb.mean()
                R = np.fft.fft2(gb) * np.conj(np.fft.fft2(ga)); R /= np.abs(R) + 1e-9
                cc = np.fft.ifft2(R).real
                dy, dx = np.unravel_index(np.argmax(cc), cc.shape)
                if (dy, dx) != (0, 0) and min(dy, cc.shape[0] - dy) + min(dx, cc.shape[1] - dx) > 3:
                    s = 0; print('frame %d: whole-frame roll (%d, %d) half-res' % (frames[i][0], dy, dx))
            if s is not None:
                bad[i] = True; print('frame %d: seam at row %d -> repeat previous clean frame' % (frames[i][0], s))
        last_good = None
        for i in range(len(frames)):
            if bad[i] and last_good is not None:
                frames[i] = (frames[i][0], frames[last_good][1]); nrep += 1
            elif not bad[i]:
                last_good = i
    h, w = frames[0][1].shape
    with open(dst, 'wb') as f:
        hdr = bytearray(MV.header_blocks(w, h, 12, 512, 4095, len(frames), fps1000=fps1000))
        # active area: whole window (no OB inside the encoder window)
        pos = hdr.find(b'RAWI'); ri = pos + 16 + 4
        struct.pack_into('<iiii', hdr, ri + 13 * 4, 0, 0, h, w)
        f.write(bytes(hdr))
        for n, (k, img) in enumerate(frames):
            f.write(MV.vidf(pack12(img), n, int(n * 1e9 / fps1000)))
    print('wrote %s: %d frames %dx%d 12-bit, %d window shifts, %d seam frames repeated, %.0f MB' % (dst, len(frames), w, h, shifts, nrep, os.path.getsize(dst) / 1e6))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
