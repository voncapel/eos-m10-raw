#!/usr/bin/env python3
"""Read A/M10CINE.RAW (m10cine.flt) and write one DNG per frame.

File = cine_hdr (little endian) + frames (u16, 14-bit << 2, 2592 x 1107):
    char magic[8] = "M10CINE1"
    u32 width, height, bpp, black, white, nframes
    u32 frame_us[2], gap_us[2], status[2]

The DMA starts wherever the sensor head is, mid-line: --skip moves the
start by N samples (probe37: 410 + 2592) so that the Bayer phase is RGGB.
The whole capture is treated as one continuous stream, so a seam between
frame 1 and frame 2 is visible if samples were lost at the re-arm.

The line start cannot be found blindly from the data (it depends on the
scene); use a mire capture: try --skip values until the chart is upright
and the patches are red / green / blue (--auto only fixes the Bayer phase
parity, not the line start).

usage: m10cine2dng.py M10CINE.RAW [--skip N] [--auto]
"""
import argparse
import struct
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import m10raw2dng as M  # noqa: E402

HDR = struct.Struct("<8s6I2I2I2I")


def bayer_phase_skip(stream, width):
    """Smallest skip giving equal green pairs and R at (0,0) (RGGB)."""
    best = None
    for k in range(0, 2 * width):
        n = (len(stream) - k) // width
        n -= n % 2
        q = stream[k:k + 400 * width].reshape(-1, width).astype(np.float32)
        p = [q[i::2, j::2].mean() for i in (0, 1) for j in (0, 1)]
        greens = abs(p[1] - p[2])
        score = greens
        if best is None or score < best[0]:
            best = (score, k, p)
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw")
    ap.add_argument("--skip", type=int, default=0, help="samples to drop at the start")
    ap.add_argument("--auto", action="store_true", help="search a skip with equal green pairs")
    a = ap.parse_args()

    data = open(a.raw, "rb").read()
    h = HDR.unpack_from(data, 0)
    magic, w, hgt, bpp, black, white, nf = h[0], *h[1:7]
    fus, gap, st = h[7:9], h[9:11], h[11:13]
    print("magic=%s %dx%d bpp=%d black=%d white=%d frames=%d frame_us=%s gap_us=%s status=%s"
          % (magic, w, hgt, bpp, black, white, nf, fus, gap, st))
    stream = (np.frombuffer(data, dtype="<u2", offset=HDR.size, count=nf * w * hgt) >> 2).astype(np.uint16)
    skip = a.skip
    if a.auto:
        score, skip, p = bayer_phase_skip(stream, w)
        print("auto skip %d (green pair diff %.1f, means %s)" % (skip, score, [int(x) for x in p]))
    s = stream[skip:]
    lines = len(s) // w
    lines -= lines % 2
    img = s[:lines * w].reshape(lines, w)
    p = [img[i::2, j::2].astype(np.float32).mean() for i in (0, 1) for j in (0, 1)]
    print("phase means (0,0)(0,1)(1,0)(1,1) =", [int(x) for x in p], "(RGGB if (0,0) is red)")
    prefix = a.raw.rsplit(".", 1)[0]
    for f in range(nf):
        seg = img[f * hgt:(f + 1) * hgt]
        seg = seg[: len(seg) - len(seg) % 2]
        if len(seg) < 64:
            continue
        out = "%s_%02d.dng" % (prefix, f)
        M.write_dng(out, seg, M.gray_world_neutral(seg))
        print(out, seg.shape)
    out = prefix + "_stream.dng"
    M.write_dng(out, img, M.gray_world_neutral(img))
    print(out, img.shape, "(whole stream, shows the seam)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
