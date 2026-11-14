#!/usr/bin/env python3
"""Decode an A/LVX3.BIN (m10cine lv_x3, header "M10LVX03") into frames.

    m10lvx3dec.py FILE [OUTPREFIX]

PACK32 pack 2 = one bitstream of 16-bit little-endian words, MSB first; the
first sample starts at an unknown even bit offset (0..2*bpp-2): pick the one
that makes same-colour neighbours (s[i], s[i+2]) smoothest.
Prints per-pass stats (filled lines, mean level, difference with the previous
pass) and writes OUTPREFIX_pNN.png (half-res RGB, gamma) for a few passes.
"""
import struct, sys, zlib
import numpy as np

HDR = 512


def header(d):
    assert d[:8] == b'M10LVX03', d[:8]
    w, lines, lb, npass, ndone = struct.unpack_from('<5I', d, 8)
    return w, lines, lb, npass, ndone


def bits_of(raw):
    words = np.frombuffer(raw[:len(raw) // 2 * 2], '<u2')
    return np.unpackbits(words.astype('>u2').view(np.uint8))


def samples(bits, off, bpp, n):
    b = bits[off:off + n * bpp].reshape(n, bpp).astype(np.uint32)
    return (b << np.arange(bpp - 1, -1, -1, dtype=np.uint32)).sum(1)


def best_offset(raw, bpp, lb, line):
    seg = raw[lb * line: lb * line + 1024]
    bits = bits_of(seg)
    best = None
    for off in range(0, 2 * bpp, 2):
        s = samples(bits, off, bpp, 600).astype(np.int64)
        sc = np.abs(s[2:] - s[:-2]).sum()
        if best is None or sc < best[0]:
            best = (sc, off)
    return best[1]


def decode(raw, bpp, w, lines, lb, off):
    bits = bits_of(raw)
    n = (len(bits) - off) // bpp
    s = samples(bits, off, bpp, n)
    per = lb * 8 // bpp
    s = s[:n // per * per].reshape(-1, per)[:lines, :w]
    if s.shape[0] < lines:
        s = np.vstack([s, np.zeros((lines - s.shape[0], w), s.dtype)])
    return s


def png(fn, rgb):
    h, w, _ = rgb.shape
    rows = b''.join(b'\0' + rgb[y].tobytes() for y in range(h))
    def ch(t, x):
        c = struct.pack('>I', len(x)) + t + x
        return c + struct.pack('>I', zlib.crc32(t + x) & 0xffffffff)
    open(fn, 'wb').write(b'\x89PNG\r\n\x1a\n' + ch(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                         + ch(b'IDAT', zlib.compress(rows, 6)) + ch(b'IEND', b''))


def to_rgb(img, bpp):
    f = img.astype(np.float32)
    h, w = f.shape
    f = f[:h // 2 * 2, :w // 2 * 2]
    # phase of the Bayer pattern unknown: take 2x2 cells, brightest diagonal = green
    a, b, c, d = f[0::2, 0::2], f[0::2, 1::2], f[1::2, 0::2], f[1::2, 1::2]
    if (a + d).mean() > (b + c).mean():
        g = (a + d) / 2; r, bl = b, c
    else:
        g = (b + c) / 2; r, bl = a, d
    black = np.percentile(f, 0.5)
    rgb = np.stack([r, g, bl], -1) - black
    rgb /= max(np.percentile(rgb, 99.5), 1)
    rgb = np.clip(rgb, 0, 1) ** (1 / 2.2)
    return (rgb * 255).astype(np.uint8)


def main(a):
    d = open(a[0], 'rb').read()
    w, lines, lb, npass, ndone = header(d)
    bpp = lb * 8 // w
    out = a[1] if len(a) > 1 else None
    print('w=%d lines=%d lb=%d bpp=%d npass=%d ndone=%d' % (w, lines, lb, bpp, npass, ndone))
    fb = lines * lb
    n = min(ndone, (len(d) - HDR) // fb)
    prev = None
    off = best_offset(d[HDR:HDR + fb], bpp, lb, lines // 2)
    for k in range(n):
        raw = d[HDR + k * fb: HDR + (k + 1) * fb]
        rl = np.frombuffer(raw, np.uint8).reshape(lines, lb)
        filled = int((rl != 0xee).any(1).sum())
        o = 0   # live78: synced frames always start on a sample; a search can pick
                # o = bpp (one sample later) and flip the Bayer column phase
        img = decode(raw, bpp, w, lines, lb, o)
        diff = '' if prev is None else ' d_prev=%.1f' % np.abs(img.astype(np.int32) - prev).mean()
        print('pass %2d off=%2d filled=%d/%d mean=%.1f%s' % (k, o, filled, lines, img.mean(), diff))
        prev = img.astype(np.int32)
        if out and (k < 2 or k == n - 1):
            png('%s_p%02d.png' % (out, k), to_rgb(img, bpp))


if __name__ == '__main__':
    main(sys.argv[1:])
