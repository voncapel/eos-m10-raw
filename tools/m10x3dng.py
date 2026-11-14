#!/usr/bin/env python3
"""1x3 RAW (A/M10X3.RAW or A/LVX3.BIN, header "M10LVX03") -> DNG sequence.

    m10x3dng.py FILE OUTDIR [--frames a:b] [--cfa RGGB|GRBG|GBRG|BGGR] [--skip-rows 4]

Decoding (live77/78): PACK32 pack 2 = one MSB-first bitstream of u16 LE
words; every frame of a synced recording starts on a sample boundary (bit
offset 0). A single fixed offset is used for all frames: a per-frame
smoothness search can pick offset 10 (= one sample later), which flips the
Bayer column phase and gives magenta/green frames.
Rows 0-2 repeat (sensor head padding) -> dropped. Columns 0-71 are optical
black: per-CFA-channel black level measured there. White = 1023 (10-bit).
DefaultScale = 3:1 (columns binned x3), so raw developers stretch the width.
"""
import argparse, os, struct, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m10lvx3dec as D
import m10raw2dng as M

CFA = {'RGGB': [0, 1, 1, 2], 'GRBG': [1, 0, 2, 1], 'GBRG': [1, 2, 0, 1], 'BGGR': [2, 1, 1, 0]}
OB_COLS = 72


def frames(path):
    d = open(path, 'rb').read()
    w, lines, lb, npass, ndone = D.header(d)
    bpp = lb * 8 // w
    fb = lines * lb
    n = min(ndone, (len(d) - D.HDR) // fb)
    return d, w, lines, lb, bpp, fb, n


def decode_frame(d, k, w, lines, lb, bpp, fb, skip_rows):
    img = D.decode(d[D.HDR + k * fb: D.HDR + (k + 1) * fb], bpp, w, lines, lb, 0)
    img = img[skip_rows:]
    return img[: img.shape[0] // 2 * 2]


def write_dng(path, img, cfa, black, white, neutral, scale_x=3):
    """img: native-bpp values; written as 16-bit with black/white tags."""
    h, w = img.shape
    entries = []

    def add(tag, typ, values):
        fmt = {1: "B", 2: "s", 3: "H", 4: "I", 5: "II", 10: "ii"}[typ]
        if typ == 2:
            b = values.encode() + b"\0"
            entries.append((tag, typ, len(b), b)); return
        if typ in (5, 10):
            b = b"".join(struct.pack("<" + fmt, *v) for v in values)
        else:
            b = struct.pack("<%d%s" % (len(values), fmt), *values)
        entries.append((tag, typ, len(values), b))

    pix = img.astype("<u2").tobytes()
    add(254, 4, [0]); add(256, 4, [w]); add(257, 4, [h]); add(258, 3, [16]); add(259, 3, [1])
    add(262, 3, [32803]); add(271, 2, "Canon"); add(272, 2, "Canon EOS M10")
    add(273, 4, [0]); add(274, 3, [1]); add(277, 3, [1]); add(278, 4, [h]); add(279, 4, [len(pix)])
    add(284, 3, [1]); add(305, 2, "m10x3dng (1x3 binned)")
    add(33421, 3, [2, 2]); add(33422, 1, CFA[cfa])
    add(50706, 1, [1, 4, 0, 0]); add(50707, 1, [1, 1, 0, 0]); add(50708, 2, "Canon EOS M10")
    add(50710, 1, [0, 1, 2]); add(50711, 3, [1])
    add(50713, 3, [2, 2])                                     # BlackLevelRepeatDim
    add(50714, 5, [M.rational(b, 1000) for b in black])       # BlackLevel per CFA cell
    add(50717, 4, [white])
    add(50718, 5, [M.rational(scale_x, 1000), M.rational(1, 1000)])   # DefaultScale
    add(50721, 10, [(v, 10000) for v in M.COLOR_MATRIX_M10])
    add(50728, 5, [M.rational(v) for v in neutral])
    add(50778, 3, [21])
    entries.sort(key=lambda e: e[0])
    ifd_off = 8
    extra_off = ifd_off + 2 + 12 * len(entries) + 4
    extra, ifd, strip_pos = bytearray(), bytearray(struct.pack("<H", len(entries))), None
    for tag, typ, count, b in entries:
        if len(b) <= 4:
            ifd += struct.pack("<HHI", tag, typ, count) + b.ljust(4, b"\0")
            if tag == 273:
                strip_pos = len(ifd) - 4
        else:
            ifd += struct.pack("<HHII", tag, typ, count, extra_off + len(extra))
            extra += b
            if len(extra) % 2:
                extra += b"\0"
    ifd += struct.pack("<I", 0)
    pix_off = extra_off + len(extra)
    pix_off += (-pix_off) % 16
    ifd[strip_pos:strip_pos + 4] = struct.pack("<I", pix_off)
    with open(path, "wb") as f:
        f.write(b"II*\0" + struct.pack("<I", ifd_off)); f.write(ifd); f.write(extra)
        f.write(b"\0" * (pix_off - extra_off - len(extra))); f.write(pix)


def levels(img, cfa):
    ob = img[:, :OB_COLS].astype(np.float64)
    black = [float(np.median(ob[i::2, j::2])) for i in (0, 1) for j in (0, 1)]
    act = img[:, OB_COLS + 8:].astype(np.float64)
    ch = {}
    for idx, (i, j) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
        c = CFA[cfa][idx]
        ch.setdefault(c, []).append(np.clip(act[i::2, j::2] - black[idx], 0, None).mean())
    r, g, b = (np.mean(ch[c]) for c in (0, 1, 2))
    return black, [r / g, 1.0, b / g]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file'); ap.add_argument('outdir')
    ap.add_argument('--frames', default='0:')
    ap.add_argument('--cfa', default='RGGB')
    ap.add_argument('--skip-rows', type=int, default=4)
    ap.add_argument('--wb', default='daylight', help="daylight | grayworld | r,b (R/G, B/G camera neutral)")
    a = ap.parse_args()
    d, w, lines, lb, bpp, fb, n = frames(a.file)
    s, e = (a.frames.split(':') + [''])[:2]
    s = int(s or 0); e = int(e) if e else n
    os.makedirs(a.outdir, exist_ok=True)
    white = (1 << bpp) - 1
    black = neutral = None
    for k in range(s, min(e, n)):
        img = decode_frame(d, k, w, lines, lb, bpp, fb, a.skip_rows)
        if black is None:
            black, neutral = levels(img, a.cfa)          # fixed for the whole clip
            if a.wb == 'daylight':
                neutral = [0.48, 1.0, 0.66]              # EOS M10 daylight (LibRaw-like multipliers 2.08/1.52)
            elif a.wb != 'grayworld':
                r, b = (float(x) for x in a.wb.split(','))
                neutral = [r, 1.0, b]
            print('%dx%d bpp=%d black=%s neutral=%s' % (img.shape[1], img.shape[0], bpp,
                  [round(x, 1) for x in black], [round(x, 3) for x in neutral]))
        write_dng(os.path.join(a.outdir, 'f%05d.dng' % k), img, a.cfa, black, white, neutral)
    print('wrote', min(e, n) - s, 'DNG to', a.outdir)


if __name__ == '__main__':
    main()
