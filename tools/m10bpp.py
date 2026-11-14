#!/usr/bin/env python3
"""Decode and check the m10cine v4 bit-depth test (A/M10C_16.RAW, M10C_12.RAW, M10C_10.RAW).

File = cine_hdr2 (little endian) + nframes * frame_bytes:
    char magic[8] = "M10CINE2"
    u32 width, height, bpp, black, white, nframes, line_bytes, frame_bytes,
        pack_mode, frame_us[4], gap_us[4], status[4]
Unwritten bytes are 0xee (the module fills the buffer before the DMA).

PACK32 10/12-bit format (found on probe40, 2026-11-07):
  - the buffer is a sequence of u16 little-endian words;
  - even words and odd words form two independent bitstreams (one per
    pixel of an even/odd pair: one 4-byte DMA unit = 1 word of each);
  - each stream packs n-bit samples MSB first, across word boundaries
    (12-bit: 4 samples per 3 words, 10-bit: 8 samples per 5 words);
  - samples are interleaved back as stream0, stream1, stream0, ...;
  - the value is the TOP n bits of the 14-bit sample (12 = 14 >> 2,
    10 = 14 >> 4): black 512 / 128, no highlight wrap.
The DMA can start in the middle of a packing group, so each frame begins at
a bit phase that is a multiple of gcd(16, n); it is found per stream as the
phase giving the smoothest sequence.

usage: m10bpp.py DIR [--dng] [--png]
"""
import argparse
import os
import struct
import sys
from math import gcd

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HDR = struct.Struct("<8s9I4I4I4I")


def read(path):
    data = open(path, "rb").read()
    h = HDR.unpack_from(data, 0)
    keys = "magic w h bpp black white nf lb fb mode".split()
    d = dict(zip(keys, h[:10]))
    d["fus"], d["gap"], d["st"] = h[10:14], h[14:18], h[18:22]
    d["data"] = np.frombuffer(data, dtype=np.uint8, offset=HDR.size)
    return d


def _stream_bits(words):
    return np.unpackbits(words.astype(">u2").view(np.uint8), bitorder="big")


def _take(bits, n, off):
    bits = bits[off:]
    m = len(bits) // n
    return (bits[: m * n].reshape(m, n).astype(np.uint32) << np.arange(n - 1, -1, -1, dtype=np.uint32)).sum(1)


def _rough(v):
    v = v.astype(np.float32)
    return np.abs(v[1:] - v[:-1]).mean() / (v.std() + 1e-6)


def unpack(frame_bytes, n, probe_bits=200000):
    """Decode one PACK32 n-bit frame. Returns (samples u32, phases)."""
    w = frame_bytes[: len(frame_bytes) // 2 * 2].view("<u2")
    step = gcd(16, n)
    out, phases = [], []
    for s in (0, 1):
        bits = _stream_bits(w[s::2])
        cands = [(o, _rough(_take(bits[:probe_bits], n, o))) for o in range(0, n, step)]
        o = min(cands, key=lambda c: c[1])[0]
        phases.append(o)
        out.append(_take(bits, n, o))
    m = min(len(out[0]), len(out[1]))
    v = np.empty(2 * m, np.uint32)
    v[0::2], v[1::2] = out[0][:m], out[1][:m]
    return v, phases


def pct(v):
    q = np.percentile(v, [0.1, 50, 99.9])
    return "min %5d p0.1 %5d med %5d p99.9 %5d max %5d" % (v.min(), q[0], q[1], q[2], v.max())


def preview(img14, path):
    """Half-size RGB preview of a Bayer image (phase unknown: plain average)."""
    from PIL import Image
    h, w = img14.shape
    f = img14[: h // 2 * 2, : w // 2 * 2].astype(np.float32) - 2048
    a = f[0::2, 0::2]; b = (f[0::2, 1::2] + f[1::2, 0::2]) / 2; c = f[1::2, 1::2]
    rgb = np.stack([a, b, c], 2)
    rgb = np.clip(rgb / np.percentile(rgb, 99.5), 0, 1) ** (1 / 2.2)
    Image.fromarray((rgb * 255).astype(np.uint8)).save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    ap.add_argument("--dng", action="store_true", help="write frame 0 of each depth as a DNG (14-bit scale)")
    ap.add_argument("--png", action="store_true", help="write a half-size preview of each frame")
    a = ap.parse_args()

    for bpp in (16, 12, 10):
        p = os.path.join(a.dir, "M10C_%02d.RAW" % bpp)
        if not os.path.exists(p):
            print("%s: absent" % p)
            continue
        d = read(p)
        w, hgt = d["w"], d["h"]
        print("== %s bpp=%d nf=%d line=%d B frame=%d B 8094=%#x"
              % (os.path.basename(p), d["bpp"], d["nf"], d["lb"], d["fb"], d["mode"]))
        print("   frame_us", d["fus"][: d["nf"]], "gap_us", d["gap"][: d["nf"]], "status", d["st"][: d["nf"]])
        for f in range(d["nf"]):
            fr = d["data"][f * d["fb"]:(f + 1) * d["fb"]]
            if bpp == 16:
                v14 = fr.view("<u2").astype(np.uint32) >> 2
                info = ""
            else:
                v, ph = unpack(fr, bpp)
                print("   frame %d %d-bit: %s  (bit phases %s)" % (f, bpp, pct(v), ph))
                v14 = v << (14 - bpp)
                info = ""
            print("   frame %d as 14-bit: %s%s" % (f, pct(v14), info))
            lines = len(v14) // w
            lines -= lines % 2
            img = v14[: lines * w].reshape(lines, w).astype(np.uint16)
            base = os.path.join(a.dir, "M10C_%02d_f%d" % (bpp, f))
            if a.png:
                preview(img, base + ".png")
            if a.dng and f == 0:
                import m10raw2dng as M
                M.write_dng(base + ".dng", img, M.gray_world_neutral(img))
    return 0


if __name__ == "__main__":
    sys.exit(main())
