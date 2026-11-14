#!/usr/bin/env python3
"""Convert an EOS M10 PACK32 16-bit dump (M10PK32.LUA, zoom x5) into DNG.

Input format (validated 2026-11-07, probe24):
  - u16 little endian, one sensor line = 2592 samples (5184 bytes)
  - value = 14-bit sample << 2 (low 2 bits always 0), black 2048 (14-bit)
  - Bayer RGGB: (0,0)=R, (0,1)=(1,0)=G, (1,1)=B
  - the DMA starts anywhere in a frame, so a dump can hold the end of one
    frame and the start of the next: segments are split at frame breaks.

Writes a minimal uncompressed DNG 1.4 (pure numpy, no dependency).

usage: m10raw2dng.py PKZ5.BIN [-o out_prefix] [--width 2592] [--min-lines 64]
"""
import argparse
import struct
import sys

import numpy as np

# LibRaw colordata.cpp, "EOS M10" (XYZ -> camera, D65), /10000
COLOR_MATRIX_M10 = [6400, -480, -888, -5294, 13416, 2047, -1296, 2203, 6137]
BLACK14 = 2048
WHITE14 = 16383


def load_lines(path, width):
    raw = np.fromfile(path, dtype="<u2")
    # M10PK32 stamps 0xdeadbeef on the first word of every 4 KB block before
    # the DMA: the first still-stamped block marks the end of the real data
    # (the rest of an unwritten block is stale memory).
    words = raw[: len(raw) // 2048 * 2048].reshape(-1, 2048)
    stamped = np.where((words[:, 0] == 0xBEEF) & (words[:, 1] == 0xDEAD))[0]
    n = int(stamped[0]) * 2048 if len(stamped) else len(raw)
    lines = n // width
    return raw[: lines * width].reshape(lines, width)


def frame_breaks(img, min_lines):
    """Lines where a new frame starts (big jump between same-colour rows)."""
    f = img.astype(np.float32)
    d = np.abs(f[2:] - f[:-2]).mean(axis=1)          # same Bayer row parity
    thr = max(6 * np.median(d), 100)              # 14-bit units
    cand = np.where(d > thr)[0]
    breaks = []
    for c in cand:
        b = int(c) + 2
        b -= b % 2                                   # keep RGGB phase
        if not breaks or b - breaks[-1] >= min_lines:
            breaks.append(b)
    return breaks


def gray_world_neutral(seg):
    s = seg.astype(np.float64) - BLACK14
    r = np.clip(s[0::2, 0::2], 0, None).mean()
    g = np.clip(np.concatenate([s[0::2, 1::2].ravel(), s[1::2, 0::2].ravel()]), 0, None).mean()
    b = np.clip(s[1::2, 1::2], 0, None).mean()
    return [r / g, 1.0, b / g]   # camera response to white


def rational(x, den=1000000):
    return (int(round(x * den)), den)


def write_dng(path, data, neutral):
    h, w = data.shape
    entries = []  # (tag, type, count, value-bytes)

    def add(tag, typ, values):
        fmt = {1: "B", 2: "s", 3: "H", 4: "I", 5: "II", 10: "ii"}[typ]
        if typ == 2:
            b = values.encode() + b"\0"
            entries.append((tag, typ, len(b), b))
            return
        if typ in (5, 10):
            b = b"".join(struct.pack("<" + fmt, *v) for v in values)
        else:
            b = struct.pack("<%d%s" % (len(values), fmt), *values)
        entries.append((tag, typ, len(values), b))

    pix = data.astype("<u2").tobytes()
    add(254, 4, [0])                      # NewSubFileType: main image
    add(256, 4, [w])
    add(257, 4, [h])
    add(258, 3, [16])
    add(259, 3, [1])                      # no compression
    add(262, 3, [32803])                  # CFA
    add(271, 2, "Canon")
    add(272, 2, "Canon EOS M10")
    add(273, 4, [0])                      # StripOffsets (patched)
    add(274, 3, [1])
    add(277, 3, [1])
    add(278, 4, [h])
    add(279, 4, [len(pix)])
    add(284, 3, [1])
    add(305, 2, "m10raw2dng (PACK32 zoom x5)")
    add(33421, 3, [2, 2])                 # CFARepeatPatternDim
    add(33422, 1, [0, 1, 1, 2])           # CFAPattern RGGB
    add(50706, 1, [1, 4, 0, 0])           # DNGVersion
    add(50707, 1, [1, 1, 0, 0])
    add(50708, 2, "Canon EOS M10")        # UniqueCameraModel
    add(50710, 1, [0, 1, 2])              # CFAPlaneColor
    add(50711, 3, [1])                    # CFALayout rectangular
    add(50714, 4, [BLACK14])              # BlackLevel
    add(50717, 4, [WHITE14])              # WhiteLevel
    add(50721, 10, [(v, 10000) for v in COLOR_MATRIX_M10])  # ColorMatrix1
    add(50728, 5, [rational(v) for v in neutral])           # AsShotNeutral
    add(50778, 3, [21])                   # CalibrationIlluminant1 = D65

    entries.sort(key=lambda e: e[0])
    ifd_off = 8
    ifd_size = 2 + 12 * len(entries) + 4
    extra_off = ifd_off + ifd_size
    extra = bytearray()
    ifd = bytearray(struct.pack("<H", len(entries)))
    strip_pos = None
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
        f.write(b"II*\0" + struct.pack("<I", ifd_off))
        f.write(ifd)
        f.write(extra)
        f.write(b"\0" * (pix_off - extra_off - len(extra)))
        f.write(pix)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bin")
    ap.add_argument("-o", "--out", default=None, help="output prefix (default: input name)")
    ap.add_argument("--width", type=int, default=2592)
    ap.add_argument("--min-lines", type=int, default=64, help="drop shorter segments")
    a = ap.parse_args()

    img = load_lines(a.bin, a.width)
    if np.count_nonzero(img & 3):
        print("warning: low 2 bits not zero, is this a 16 bpp dump?", file=sys.stderr)
    img = (img >> 2).astype(np.uint16)
    cuts = [0] + frame_breaks(img, a.min_lines) + [img.shape[0]]
    prefix = a.out or a.bin.rsplit(".", 1)[0]
    n = 0
    for i in range(len(cuts) - 1):
        s, e = cuts[i], cuts[i + 1]
        e -= (e - s) % 2
        if e - s < a.min_lines:
            continue
        seg = img[s:e]
        neutral = gray_world_neutral(seg)
        out = "%s_%02d.dng" % (prefix, n)
        write_dng(out, seg, neutral)
        print("%s: lines %d-%d (%dx%d) neutral R/G B/G %.3f/%.3f" % (out, s, e - 1, a.width, e - s, neutral[0], neutral[2]))
        n += 1
    if n == 0:
        print("no segment written", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
