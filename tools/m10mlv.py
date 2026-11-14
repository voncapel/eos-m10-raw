#!/usr/bin/env python3
"""MLV (Magic Lantern Video) writer / reader for the M10 1x3 RAW stream.

    m10mlv.py FILE.RAW OUT.MLV        convert an A/M10X3.RAW recording (M10LVX03)
    m10mlv.py --check FILE.MLV        parse an MLV, list blocks, verify frames
    m10mlv.py --dng FILE.MLV OUT [a b]      frames a..b-1 -> DNG (raw values)
    m10mlv.py --dngcal FILE.MLV OUT [a b]   same, with per-cell clip / column-gain
                                            calibration (M10ROWS=1036 drops the bottom band)
    m10mlv.py --fps 12.4 FILE.MLV [.M00..]  set the MLVI frame rate of every chunk
    m10mlv.py --fix FILE.MLV .M00 ...       fix fileCount / frame counts of a split recording

The camera writes PACK32 pack-2 data: one MSB-first bitstream of u16 LE words
at 10/12/14 bpp. That is exactly the MLV RAW payload format of ML on DIGIC 5
(raw_info.bits_per_pixel = 10/12/14, pitch = width * bpp / 8), so frames are
copied verbatim. Columns 0-71 = optical black, rows 0-3 = head padding:
expressed through raw_info.active_area. CFA RGGB, EOS M10 colour matrix.
VIDF blocks are padded (frameSpace) to a multiple of 512 bytes, like ML.
"""
import struct, sys, os, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

COLOR_MATRIX_M10 = [6400, -480, -888, -5294, 13416, 2047, -1296, 2203, 6137]
OB_COLS, PAD_ROWS = 72, 4
ALIGN = 512


def blk(kind, payload, ts=0):
    return kind + struct.pack('<IQ', 16 + len(payload), ts) + payload


def raw_info(w, h, bpp, black, white):
    pitch = w * bpp // 8
    ri = struct.pack('<IIiiiii', 1, 0, h, w, pitch, pitch * h, bpp)
    ri += struct.pack('<ii', black, white)
    ri += struct.pack('<iiii', 0, 0, w, h)                        # crop/jpeg origin + size
    y2 = PAD_ROWS + (h - PAD_ROWS) // 2 * 2
    ri += struct.pack('<iiii', PAD_ROWS, OB_COLS, y2, w)          # active area y1 x1 y2 x2
    ri += struct.pack('<ii', 0, 0)                                # exposure bias
    ri += struct.pack('<ii', 0x02010100, 21)                      # CFA RGGB, D65
    for v in COLOR_MATRIX_M10:
        ri += struct.pack('<ii', v, 10000)
    ri += struct.pack('<i', 1100)                                 # dynamic range EV x100 (guess)
    assert len(ri) == 0xa0, len(ri)
    return ri


def header_blocks(w, h, bpp, black, white, nframes, fps1000=25000, guid=None):
    guid = guid or (int(time.time() * 1e6) & 0xffffffffffffffff)
    mlvi = b'MLVI' + struct.pack('<I', 52) + b'v2.0\0\0\0\0' + struct.pack(
        '<QHHIHHIIII', guid, 0, 1, 0, 1, 0, nframes, 0, fps1000, 1000)
    assert len(mlvi) == 52
    rawi = blk(b'RAWI', struct.pack('<HH', w, h) + raw_info(w, h, bpp, black, white))
    rawc = blk(b'RAWC', struct.pack('<HHHHBBBBhh', 5184, 3456, 162, 0, 3, 0, 1, 0, -32768, -32768))
    idnt = blk(b'IDNT', b'Canon EOS M10'.ljust(32, b'\0') + struct.pack('<I', 0x80000355) + b'\0' * 32)
    t = time.localtime()
    rtci = blk(b'RTCI', struct.pack('<10H', t.tm_sec, t.tm_min, t.tm_hour, t.tm_mday, t.tm_mon - 1,
                                     t.tm_year - 1900, (t.tm_wday + 1) % 7, t.tm_yday - 1, 0, 0) + b'\0' * 8)
    expo = blk(b'EXPO', struct.pack('<IIIIQ', 1, 0, 0, 0, 0))
    wbal = blk(b'WBAL', struct.pack('<7I', 0, 5500, 2080, 1000, 1520, 0, 0))   # daylight-ish
    out = mlvi + rawi + rawc + idnt + rtci + expo + wbal
    pad = (-(len(out) + 16)) % ALIGN                              # NULL block to the next 512
    out += b'NULL' + struct.pack('<IQ', 16 + pad, 0) + b'\0' * pad
    assert len(out) % ALIGN == 0
    return out


def vidf(frame, k, ts):
    space = (-(32 + len(frame))) % ALIGN
    hdr = b'VIDF' + struct.pack('<IQIHHHHI', 32 + space + len(frame), ts, k, 0, 0, 0, 0, space)
    return hdr + b'\0' * space + frame


def convert(src, dst):
    import m10lvx3dec as D
    d = open(src, 'rb').read()
    w, lines, lb, npass, ndone = D.header(d)
    bpp = lb * 8 // w
    fb = lines * lb
    n = min(ndone, (len(d) - D.HDR) // fb)
    black = {10: 127, 12: 508, 14: 2032}[bpp]
    white = (1 << bpp) - 1
    with open(dst, 'wb') as f:
        f.write(header_blocks(w, lines, bpp, black, white, n))
        for k in range(n):
            f.write(vidf(d[D.HDR + k * fb: D.HDR + (k + 1) * fb], k, k * 40000))
    print('wrote %s: %d frames %dx%d %d-bit (%.1f MB)' % (dst, n, w, lines, bpp, os.path.getsize(dst) / 1e6))


def check(fn):
    import numpy as np
    d = open(fn, 'rb').read()
    pos, counts, info, nvid = 0, {}, None, 0
    while pos + 16 <= len(d):
        kind = d[pos:pos + 4]; size = struct.unpack_from('<I', d, pos + 4)[0]
        if size < 16 or pos + size > len(d):
            print('bad block at', pos, kind, size); break
        counts[kind] = counts.get(kind, 0) + 1
        if kind == b'MLVI':
            print('MLVI', d[pos + 8:pos + 16], 'frames', struct.unpack_from('<I', d, pos + 36)[0],
                  'fps', struct.unpack_from('<II', d, pos + 44))
        elif kind == b'RAWI':
            xr, yr = struct.unpack_from('<HH', d, pos + 16)
            v = struct.unpack_from('<IIiiiiiii', d, pos + 20)
            aa = struct.unpack_from('<4i', d, pos + 20 + 13 * 4)
            info = dict(w=v[3], h=v[2], pitch=v[4], bpp=v[6], black=v[7], white=v[8])
            print('RAWI', xr, yr, info, 'active', aa)
        elif kind == b'RAWC' and info is not None:
            info['skip_y'] = d[pos + 16 + 11]          # live109: 2 = Film 3x3 (native 3:2, no stretch)
        elif kind == b'VIDF':
            fnum, = struct.unpack_from('<I', d, pos + 16)
            space, = struct.unpack_from('<I', d, pos + 28)
            data = d[pos + 32 + space: pos + size]
            assert len(data) == info['pitch'] * info['h'], (len(data), info)
            if nvid == 0:
                import m10lvx3dec as D
                img = D.decode(data, info['bpp'], info['w'], info['h'], info['pitch'], 0)
                print('VIDF 0: mean %.1f, OB median %.0f' % (img.mean(), np.median(img[:, :OB_COLS])))
            nvid += 1
        pos += size
    print('blocks', {k.decode(): v for k, v in counts.items()}, 'end', pos, 'size', len(d))


def fix_chunks(files):
    """Set fileCount and videoFrameCount in every chunk of a split recording
    (camera writes A/M10X3.MLV, .M00, .M01 ... with fileNum 0, 1, 2 ...)."""
    for fn in files:
        with open(fn, 'r+b') as f:
            d = f.read()
            n, pos = 0, 0
            while pos + 16 <= len(d):
                size = struct.unpack_from('<I', d, pos + 4)[0]
                if size < 16: break
                if d[pos:pos + 4] == b'VIDF': n += 1
                pos += size
            f.seek(26); f.write(struct.pack('<H', len(files)))
            f.seek(36); f.write(struct.pack('<I', n))
            print(fn, 'fileNum', struct.unpack_from('<H', d, 24)[0], 'frames', n, 'complete' if pos == len(d) else 'TRUNCATED at %d' % pos)


def set_fps(files, fps):
    """Write sourceFpsNom/Denom (MLVI +44/+48) in every chunk (v89r writes the
    measured cadence; older recordings say 25.000)."""
    for fn in files:
        with open(fn, 'r+b') as f:
            f.seek(44); f.write(struct.pack('<II', int(round(fps * 1000)), 1000))
        print(fn, 'fps -> %.3f' % fps)


def mlv_frames(fn):
    """yield (info, frame_bytes) for each VIDF of an MLV file"""
    d = open(fn, 'rb').read()
    pos, info = 0, None
    while pos + 16 <= len(d):
        kind = d[pos:pos + 4]; size = struct.unpack_from('<I', d, pos + 4)[0]
        if kind == b'RAWI':
            v = struct.unpack_from('<IIiiiiiii', d, pos + 20)
            info = dict(w=v[3], h=v[2], pitch=v[4], bpp=v[6], black=v[7], white=v[8])
        elif kind == b'RAWC' and info is not None:
            info['skip_y'] = d[pos + 16 + 11]          # live109: 2 = Film 3x3 (native 3:2, no stretch)
        elif kind == b'VIDF':
            space, = struct.unpack_from('<I', d, pos + 28)
            yield info, d[pos + 32 + space: pos + size]
        pos += size


CELLS = ((0, 0), (0, 1), (1, 0), (1, 1))      # R, G1, G2, B (RGGB)


def calib(fn, black, nfr=16, rows=None):
    """Measure the per-CFA-cell clip plateau and the even/odd column gain on a
    few frames (live99). In FHD 1x3 the sensor clips far below 1023 and at a
    different level per cell (r98f: R 234, G1 197, G2 241, B 190 above black),
    and even columns (R, G2) read ~10 % hotter than odd ones (G2/G1 = 1.10 in
    the mid-tones): with one white level the clipped highlights turn magenta."""
    import numpy as np, m10lvx3dec as D
    acc = []
    for k, (info, data) in enumerate(mlv_frames(fn)):
        if k >= nfr: break
        img = D.decode(data, info['bpp'], info['w'], info['h'], info['pitch'], 0)[PAD_ROWS:]
        acc.append(img[:rows, OB_COLS:].astype(np.float32) - black)
    mu = np.mean(acc, 0)
    clip = []
    for a, b in CELLS:
        v = mu[a::2, b::2]; v = v[v > np.percentile(v, 92)].astype(int)
        h = np.convolve(np.bincount(v), np.ones(7) / 7, 'same')
        clip.append(float(np.argmax(h)))
    g1, g2 = mu[0::2, 1::2], mu[1::2, 0::2]
    ok = (g1 > 20) & (g1 < 0.6 * clip[1]) & (g2 < 0.6 * clip[2])
    par = float(np.median(g2[ok] / g1[ok])) if ok.sum() > 1000 else 1.0
    return clip, par


# live100: pixel grid that drops to ~7-36 (far below black) in every frame after
# the first trapped head error (r100c frames >= 15), R/B cells only.  Frame
# coordinates after PAD_ROWS, OB columns included: rows 115-1091, cols 244-1659,
# (row % 10, col % 8) in AF_GRID.  ^[inferred] on-sensor AF (phase) pixels that
# Canon stops correcting after the error.  Clean frames have none.
AF_BOX = (115, 1091, 244, 1659)
AF_GRID = ((0, 0), (1, 7), (5, 3), (6, 4))
# live102 (r102b): the full grid is 12 cells per 10x8 block (3 per column phase,
# rows 2 apart), and in highlights the samples do not drop below black but read
# ~0.6x (grid) or ~1.45x (cells next to the grid) their neighbours -> visible
# as a green/yellow mesh on bright areas with the "below black" criterion only.
AF_GRID12 = ((0, 0), (2, 0), (8, 0), (4, 4), (6, 4), (8, 4),
             (3, 3), (5, 3), (7, 3), (1, 7), (3, 7), (9, 7))
# live109: Film 3x3 (800c = 2) has its own grid, measured on r108e (frames 6-40,
# stable in > 90 % of the frames), RAW frame coordinates (no row crop): same box
# rows 119-1095, cols 244-1659, 12 cells per 10x8 block; all 12 used for detection.
AF3_BOX = (119, 1095, 232, 1659)   # live114 (r114_exm1min): the grid starts at col 232, not 244
                                   # (cols 232-243 = image cols 148-159 left as a dotted green line)
AF3_GRID12 = ((0, 0), (0, 4), (0, 6), (4, 0), (4, 2), (4, 4),
              (5, 1), (5, 3), (5, 7), (9, 3), (9, 5), (9, 7))
GEOM = {'x3': (AF_BOX, AF_GRID12, AF_GRID), '3x3': (AF3_BOX, AF3_GRID12, AF3_GRID12)}
_af_cache = {}


def _af_masks(shape, geom='x3'):
    import numpy as np
    if (shape, geom) in _af_cache:
        return _af_cache[(shape, geom)]
    (r0, r1, c0, c1), grid12, gdet = GEOM[geom]
    h, w = shape
    r1, c1 = min(r1, h - 3), min(c1, w - 3)
    Y, X = np.indices(shape)
    gm = np.zeros(shape, bool)
    for rm, cm in grid12:
        gm |= (Y % 10 == rm) & (X % 8 == cm)
    gm[:r0] = gm[r1 + 1:] = False; gm[:, :c0] = gm[:, c1 + 1:] = False
    g4 = np.zeros(shape, bool)
    for rm, cm in gdet:
        g4 |= (Y % 10 == rm) & (X % 8 == cm)
    g4 &= gm
    rb = np.zeros(shape, bool); rb[r0 + 2:r1 - 1, c0 + 2:c1 - 1] = True
    rb &= ((Y + X) % 2 == 0) & ~gm
    _af_cache[(shape, geom)] = (gm, g4, rb)
    return gm, g4, rb


def fix_af(img, black, margin=20, detect=500, geom='x3'):
    """Repair the on-sensor AF pixel grid left uncorrected after a head error.
    Detection: >= `detect` samples of the classic 4-cell grid below
    black - margin (clean frames have ~0).  Repair: every sample of the 12-cell
    grid that deviates from its same-colour neighbours (vertical weight 3,
    horizontal 1, diagonal 0.5, grid samples excluded) by more than
    max(margin, 25 %) is replaced; then a lighter despeckle (40 / 35 %) of the
    remaining R/B cells inside the box catches the ~1.45x cells next to the
    grid in highlights.  Returns the count fixed (0 on a clean frame)."""
    import numpy as np
    gm, g4, rb = _af_masks(img.shape, geom)
    if int((img[g4].astype(np.int32) < black - margin).sum()) < detect:
        return 0
    f = img.astype(np.float32)

    def repair(mask, marg, rel, excl):
        ys, xs = np.nonzero(mask)
        acc = np.zeros(len(ys), np.float32); cnt = np.zeros(len(ys), np.float32)
        for dy, dx, wg in ((-2, 0, 3), (2, 0, 3), (0, -2, 1), (0, 2, 1),
                           (-2, -2, .5), (-2, 2, .5), (2, -2, .5), (2, 2, .5)):
            yy, xx = ys + dy, xs + dx
            ok = ~excl[yy, xx]
            acc[ok] += wg * f[yy[ok], xx[ok]]; cnt[ok] += wg
        v = np.where(cnt > 0, acc / np.maximum(cnt, 1e-6), f[ys, xs])
        bad = np.abs(f[ys, xs] - v) > np.maximum(marg, rel * np.abs(v - black))
        f[ys[bad], xs[bad]] = v[bad]
        return int(bad.sum())

    n = repair(gm, margin, 0.25, gm)
    n += repair(rb, 40, 0.35, np.zeros(img.shape, bool))
    img[:] = np.round(f).astype(img.dtype)
    return n


IMG_X0 = 84     # live102: columns 0-71 optical black, 72-83 still at black level -> crop (M10XOFF=0 keeps them)
PAD3 = 28       # live109: Film 3x3 rows 0-2 head padding, 3-27 optical black -> image from row 28 (1724 x 1156)


def to_dng(fn, outdir, first=0, last=None, cal=False, rows=None):
    import numpy as np, m10lvx3dec as D, m10x3dng as X
    os.makedirs(outdir, exist_ok=True)
    c, naf = None, 0
    x0 = int(os.environ.get('M10XOFF', IMG_X0)) // 2 * 2
    for k, (info, data) in enumerate(mlv_frames(fn)):
        if k < first: continue
        if last is not None and k >= last: break
        s3 = info.get('skip_y') == 2 or os.environ.get('M10GEOM') == '3x3'
        black, white = info['black'], info['white']
        img = D.decode(data, info['bpp'], info['w'], info['h'], info['pitch'], 0)
        if s3:                                   # 3x3: AF grid in raw coordinates, then crop OB rows
            if not os.environ.get('M10NOAF'):
                img = img.copy()
                if fix_af(img, black, geom='3x3'): naf += 1
            img = img[PAD3:]
        else:
            img = img[PAD_ROWS:]
        img = img[:rows]
        img = img[: img.shape[0] // 2 * 2]
        if not s3 and not os.environ.get('M10NOAF'):
            img = img.copy()
            if fix_af(img, black): naf += 1
        img = img[:, x0:]
        if k == first or (first == 0 and k == 0):
            print('%s geometry: %d x %d, DefaultScale %d:1' % ('Film 3x3' if s3 else '1x3', img.shape[1], img.shape[0], 1 if s3 else 3))
        if cal:
            if c is None:
                clip, par = calib(fn, black, rows=rows)
                gain = [1 / par, 1.0, 1 / par, 1.0]              # even columns: R, G2
                wl = 0.97 * min(cl * g for cl, g in zip(clip, gain))
                c = (clip, gain, wl, (white - black) / wl)
                print('cal: clip R/G1/G2/B %s above black, column gain %.3f, white %.0f'
                      % ([int(v) for v in clip], par, wl))
            clip, gain, wl, s = c
            x = img.astype(np.float32) - black
            for (a, b), cl, g in zip(CELLS, clip, gain):
                v = x[a::2, b::2]
                sat = v >= 0.95 * cl
                v *= g; v[sat] = wl
                np.minimum(v, wl, out=v)
            img = np.clip(x * s + black, 0, white).astype(np.uint16)
        X.write_dng(os.path.join(outdir, 'f%05d.dng' % k), img, 'RGGB', [black] * 4,
                    white, [0.48, 1.0, 0.66], scale_x=1 if s3 else 3)
    print('DNG ->', outdir, '(AF grid repaired in %d frames; M10NOAF=1 to disable)' % naf)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--check':
        check(a[1])
    elif a and a[0] == '--fix':
        fix_chunks(a[1:])
    elif a and a[0] == '--fps':
        set_fps(a[2:], float(a[1]))
    elif a and a[0] in ('--dng', '--dngcal'):
        # --dngcal: per-cell clip + column gain calibration; M10ROWS=1036 crops the bottom band
        rows = int(os.environ['M10ROWS']) if os.environ.get('M10ROWS') else None
        to_dng(a[1], a[2], int(a[3]) if len(a) > 3 else 0, int(a[4]) if len(a) > 4 else None,
               cal=a[0] == '--dngcal', rows=rows)
    else:
        convert(a[0], a[1])
