#!/usr/bin/env python3
"""Classify each crossbar-port slot captured by M10PORTS.LUA.

Usage: analyze_ports.py PORTS.BIN M10PORTS.TXT

For every 64 KB slot, report how much was written and which pixel format
best explains the data:
  - UYVY   : 8-bit 4:2:2 (chroma bytes ~0x00/0xff signed, luma bytes smooth)
  - B16    : 14-bit Bayer stored in 16-bit LE words (values < 16384, strong
             2-pixel periodicity = CFA)
  - B14p   : 14-bit Bayer packed with Canon/ML raw_pixblock layout
  - B12p / B10p : same for lossy-free 12/10-bit packing
A Bayer stream shows a lag-2 difference clearly smaller than lag-1 on
colourful scenes, and plausible black level (~2048 for 14-bit on M10).
"""
import re
import sys

import numpy as np

SLOT = 0x10000
MARK = 0xDEADBEEF


def unpack_ml(buf, bits):
    """Unpack Canon raw: bitstream MSB-first over little-endian 16-bit words."""
    w = np.frombuffer(buf[: len(buf) // 2 * 2], dtype="<u2").byteswap()
    b = np.unpackbits(w.view(np.uint8))
    n = len(b) // bits
    x = b[: n * bits].reshape(n, bits).astype(np.uint32)
    return (x << np.arange(bits - 1, -1, -1, dtype=np.uint32)).sum(1).astype(np.float64)


def score_stream(v, full):
    if v.size < 64:
        return None
    d1 = np.abs(np.diff(v)).mean() / full
    d2 = np.abs(v[2:] - v[:-2]).mean() / full
    return d1, d2


def classify(data):
    res = {}
    b = np.frombuffer(data, dtype=np.uint8)
    q = b[: len(b) // 4 * 4].reshape(-1, 4).astype(np.float64)
    if len(q) > 16:
        sm = [np.abs(np.diff(q[:, k])).mean() for k in range(4)]
        signed_chroma = np.mean(np.minimum(q[:, [0, 2]], 255 - q[:, [0, 2]]) < 48)
        res["uyvy"] = (sm[1] + sm[3]) / 2 < 12 and signed_chroma > 0.8
    u16 = np.frombuffer(data[: len(data) // 2 * 2], dtype="<u2").astype(np.float64)
    res["b16_plaus"] = float(np.mean(u16 < 16384))
    res["b16"] = score_stream(u16, 16384.0)
    for bits in (14, 12, 10):
        res[f"b{bits}p"] = score_stream(unpack_ml(data, bits), float(1 << bits))
    return res


def main():
    blob = open(sys.argv[1], "rb").read()
    meta = {}
    for line in open(sys.argv[2], encoding="latin-1"):
        m = re.match(r"slot=(\d+) port=0x([0-9a-f]+) rt=(-?\d+).*kb_written=(\d+)", line)
        if m:
            meta[int(m.group(1))] = (int(m.group(2), 16), int(m.group(3)), int(m.group(4)))
    nslots = len(blob) // SLOT
    print(f"{nslots} slots")
    for s in range(nslots):
        port, rt, kb = meta.get(s, (-1, -1, -1))
        raw = blob[s * SLOT:(s + 1) * SLOT]
        words = np.frombuffer(raw, dtype="<u4")
        if kb == 0 or np.all(words[::256] == MARK):
            continue
        # keep only the written part (marker words every KB)
        written = raw[: max(kb, 1) * 1024]
        c = classify(written)
        tag = []
        if c.get("uyvy"):
            tag.append("UYVY")
        for k in ("b16", "b14p", "b12p", "b10p"):
            sc = c.get(k)
            if sc and sc[1] < 0.75 * sc[0] and sc[1] < 0.08:
                if k != "b16" or c["b16_plaus"] > 0.97:
                    tag.append(f"{k.upper()}?")
        rts = f"rt=0x{rt:02x}" if rt >= 0 else "      "
        def fmt(sc):
            return "  -  " if sc is None else f"{sc[0]:.3f}/{sc[1]:.3f}"
        print(f"slot {s:3d} port 0x{port:02x} {rts} kb={kb:3d} "
              f"b16 {fmt(c['b16'])} plaus={c['b16_plaus']:.2f} "
              f"b14p {fmt(c['b14p'])} b12p {fmt(c['b12p'])} b10p {fmt(c['b10p'])} "
              f"-> {' '.join(tag) or '?'}")


if __name__ == "__main__":
    main()
