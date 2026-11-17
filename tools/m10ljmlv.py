#!/usr/bin/env python3
"""live109: compressed M10 MLV (video class 0x21, LJ92 14-bit container of 10-bit data) tools.

    m10ljmlv.py --check FILE.MLV            decode every frame (lj92d), report sizes / failures
    m10ljmlv.py --mp4 FILE.MLV OUT.mp4 [FPS]  half-size preview (3x3 Film crop, daylight WB)
    m10ljmlv.py --dng FILE.MLV OUTDIR [a b]   frames a..b-1 -> DNG (10-bit values, 3x3 geometry, AF fix)

live112: --mp4/--dng undo the 12 px head-error shift (OB edge) and patch the rows a kept error
frame lost (v148 no-pause recovery) from the previous frame; REPAIR=0 = old resync() only.

Frames: VIDF payload = one LJ92 stream (P=14, 904 x H, 2 components) or several
("M10S" n sizes in the frameSpace).  Values decode to sample << 4.
Needs /tmp/ljc/lj92d (cc -O2 -o /tmp/ljc/lj92d tools/lj92d.c).
"""
import os, struct, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
LJ = '/tmp/ljc/lj92d'
W = 1808


def frames(fn):
    import mmap                              # live122: mmap, not read(): a 2 GB take in RAM swapped the Mac
    fo = open(fn, 'rb')
    d = mmap.mmap(fo.fileno(), 0, access=mmap.ACCESS_READ)
    pos = 0
    while pos + 16 <= len(d):
        k = d[pos:pos + 4]; sz = struct.unpack_from('<I', d, pos + 4)[0]
        if sz < 16: break
        if k == b'VIDF':
            n, = struct.unpack_from('<I', d, pos + 16)
            sp, = struct.unpack_from('<I', d, pos + 28)
            body = d[pos + 32 + sp: pos + sz]
            if d[pos + 32:pos + 36] == b'M10S':
                ns, = struct.unpack_from('<I', d, pos + 36)
                ss = struct.unpack_from('<%dI' % ns, d, pos + 40)
                parts, o = [], 0
                for s in ss: parts.append(body[o:o + s]); o += s
            else:
                parts = [body]
            yield n, parts
        pos += sz


def mlv_info(fn):
    """Read bpp, black, white from the MLV RAWI block (default 10-bit legacy)."""
    d = open(fn, 'rb').read(512)
    pos = 0
    while pos + 8 <= len(d):
        k = d[pos:pos + 4]; sz = struct.unpack_from('<I', d, pos + 4)[0]
        if sz < 8: break
        if k == b'RAWI' and sz >= 60:
            bpp, black, white = struct.unpack_from('<3I', d, pos + 44)
            return bpp, float(black), int(white)
        pos += sz
    return 10, 127.5, 1023


def decode(parts, shift=4):
    out = []
    with tempfile.TemporaryDirectory() as t:
        for i, p in enumerate(parts):
            a, b = os.path.join(t, 'a'), os.path.join(t, 'b')
            open(a, 'wb').write(p)
            r = subprocess.run([LJ, a, b], capture_output=True)
            if r.returncode: return None
            u = np.fromfile(b, '<u2')
            w = int(r.stdout.split()[0]) if r.stdout.split() else W   # live116: lj92d prints the decoded width (2592 in the x5 magnifier)
            out.append(u.reshape(-1, w))
    arr = np.vstack(out)
    return (arr >> shift).astype(np.uint16) if shift else arr.astype(np.uint16)


def resync(img):
    """live110: after a trapped head error the head stream carries N extra pixels (1023) at the
    very start of every following frame (r109gl_2: N = 12 from frame 181 on): the whole frame is
    shifted N px in raster order.  Undo it; fill the lost tail (and short frames ending in 1023)
    from the row above (same CFA phase).  Returns (img, N)."""
    f = img.ravel()
    n = int(np.argmax(f != 1023)) if f[0] == 1023 else 0
    if n > 256: n = 0
    if n:
        f = np.concatenate([f[n:], np.full(n, 1023, f.dtype)])
    t = int(np.argmax(f[::-1] != 1023)) if f[-1] == 1023 else 0
    img = f.reshape(img.shape).copy()
    if t:
        h, w = img.shape
        for j in range(t):
            p = h * w - 1 - j
            img.flat[p] = img.flat[p - 2 * w]
    return img, n


def ob_shift(img):
    """live112: raster shift from the left OB edge (active area starts at column 72 when aligned).
    The 12 leading pixels are not always 1023 (r109ha: 789, or garbage on the error frame itself),
    so measure where the active area starts on the middle rows instead."""
    x = img[200:1000:4].astype(np.float32)
    ob = np.median(x[:, 10:60], 1, keepdims=True)
    c = (x[:, 40:200] > ob + 15)
    e = np.where(c.any(1), c.argmax(1) + 40, -1)
    e = e[e > 0]
    # live114: the shifted frame starts with N identical garbage pixels (973 / 1016 / 1023 ...):
    # count them first.  The OB-edge estimate is +-1 px (r114_exm1min: 13 for a true 12) and an
    # odd shift swaps the CFA phase (magenta frames): it is only a fallback, snapped to even.
    f = img.ravel()
    run = int(np.argmax(f[:80] != f[0]))
    if 4 <= run <= 64 and f[0] > 600 and not run & 1:
        return run
    if img.shape[1] not in (1808, 2592):     # live122: shell crop (2304 / 2400) has no OB columns: the
        return 0                             # OB-edge fallback found 38-48 px "shifts" -> magenta frames
    if not len(e): return 0
    s = int(np.median(e)) - 72
    s = s // 2 * 2 if s & 1 and (f[s - 1] > 600) else (s + 1) // 2 * 2 if s & 1 else s
    return s if 4 <= s <= 64 else 0


def unshift(img, n):
    f = img.ravel()
    w = img.shape[1]
    f = np.concatenate([f[n:], f[-2 * w:-2 * w + n]])   # lost tail <- same CFA phase, two rows up
    return f.reshape(img.shape)


def repaired(fn, first=0, last=None):
    """live112 (v148 no-pause recovery): yield (k, img) with the raster shift undone and the rows
    damaged by a head error (one-line seam: lines after the error are garbage until the frame end)
    replaced by the previous output frame.  Damaged rows = rows far from BOTH neighbours."""
    win = []
    prev_out = None
    stats = {'shifted': 0, 'patched': 0, 'rows': 0}
    def fix(k, img):
        s = ob_shift(img)
        if s: stats['shifted'] += 1; img = unshift(img, s)
        return k, img.astype(np.int32)
    bpp, _, _ = mlv_info(fn)
    sh = 0 if bpp == 14 else 4
    src = ((k, decode(p, shift=sh)) for k, p in frames(fn) if k >= first and (last is None or k < last))
    src = (fix(k, im) for k, im in src if im is not None)
    def emit(i):
        nonlocal prev_out
        k, cur = win[i]
        nb = [win[j][1] for j in (i - 1, i + 1) if 0 <= j < len(win)]
        if prev_out is not None and len(nb) == 2:
            d = np.minimum(*[np.abs(cur - n)[:, 100:1700].mean(1) for n in nb])
            base = float(np.percentile(d[28:], 10))
            sc14 = cur.max() > 1024
            bad = d > max(4.0 * base, 95.0 if sc14 else 8.0)
            strong = d > max(6.5 * base, 260.0 if sc14 else 20.0)
            if bad.sum() >= 180 or strong.sum() >= 2:
                cur = cur.copy()
                if bad.sum() >= 16:                      # seam: the rest of the frame is garbage
                    r0 = int(np.argmax(bad)); m = np.zeros_like(bad); m[r0:] = True
                else:                                    # a few rows: patch them (+-4)
                    m = np.convolve(strong, np.ones(9), 'same') > 0
                cur[m] = prev_out[m]
                stats['patched'] += 1; stats['rows'] += int(m.sum())
                win[i] = (k, cur)
        prev_out = cur
        return k, cur.astype(np.uint16)
    for item in src:
        win.append(item)
        if len(win) == 2 and prev_out is None:
            yield emit(0)
        if len(win) == 3:
            yield emit(1); win.pop(0)
    if len(win) == 2: yield emit(1)
    elif len(win) == 1 and prev_out is None: yield emit(0)
    print('repair: %(shifted)d shifted, %(patched)d patched (%(rows)d rows)' % stats, file=sys.stderr)


def images(fn, first=0, last=None):
    """Frames ready for output: repaired() (REPAIR=1, default) or the old per-frame resync()."""
    if os.environ.get('REPAIR', '1') != '0':
        yield from repaired(fn, first, last); return
    bpp, _, _ = mlv_info(fn)
    sh = 0 if bpp == 14 else 4
    for k, parts in frames(fn):
        if k < first or (last is not None and k >= last): continue
        img = decode(parts, shift=sh)
        if img is None: continue
        yield k, resync(img)[0]


def main(a):
    bpp, black_lv, white_lv = mlv_info(a[1]) if len(a) > 1 and os.path.exists(a[1]) else (10, 127.5, 1023)
    sh = 0 if bpp == 14 else 4
    if a[0] == '--check':
        n = bad = 0; sizes = []
        for k, parts in frames(a[1]):
            img = decode(parts, shift=sh); n += 1; sizes.append(sum(len(p) for p in parts))
            if img is None: bad += 1
        print('%d frames (%d-bit), %d failed, size avg %.2f MB max %.2f MB, last shape %s' % (n, bpp, bad, np.mean(sizes) / 1e6, max(sizes) / 1e6, None if img is None else img.shape))
    elif a[0] == '--mp4':
        out = a[2]; fps = a[3] if len(a) > 3 else '12.5'
        p = None; sc = None
        for k, img in images(a[1]):
            if img.shape[1] == 1808:
                if os.environ.get('AFFIX', '1') != '0':
                    import m10mlv as M
                    M.fix_af(img, int(round(black_lv)), geom='3x3')
                x = img[28:28 + 1156, 84:84 + 1724].astype(np.float32) - black_lv
            else:
                x = img[28:, 72 if img.shape[1] == 2592 else 0:]
                x = x[:x.shape[0] // 2 * 2, :x.shape[1] // 2 * 2].astype(np.float32) - black_lv
            r = x[0::2, 0::2] / 0.48; g = (x[0::2, 1::2] + x[1::2, 0::2]) / 2; b = x[1::2, 1::2] / 0.66
            rgb = np.stack([r, g, b], -1)
            if sc is None: sc = max(1.0, np.percentile(rgb, 99.5))
            rgb = (np.clip(rgb / sc, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)
            if p is None:
                h, w = rgb.shape[:2]
                p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (w, h), '-r', fps, '-i', '-',
                                      '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', out], stdin=subprocess.PIPE)
            p.stdin.write(rgb.tobytes())
        p.stdin.close(); p.wait(); print('->', out)
    elif a[0] == '--dng':
        import m10mlv as M, m10x3dng as X
        os.makedirs(a[2], exist_ok=True)
        first = int(a[3]) if len(a) > 3 else 0; last = int(a[4]) if len(a) > 4 else None
        for k, img in images(a[1], first, last):
            if img.shape[1] != 1808:                 # live117: x5 magnifier 1:1 (no AF grid, OB = 72 cols / 28 rows)
                img = img[28:, 72 if img.shape[1] == 2592 else 0:]   # live119: 2400-wide shell crop has no OB columns
                img = img[:img.shape[0] // 2 * 2]
            else:
                M.fix_af(img, int(round(black_lv)), geom='3x3')
                img = img[28:28 + 1156, 84:]
            X.write_dng(os.path.join(a[2], 'f%05d.dng' % k), img, 'RGGB', [black_lv] * 4, white_lv, [0.48, 1.0, 0.66], scale_x=1)
        print('DNG ->', a[2])


if __name__ == '__main__':
    main(sys.argv[1:])
