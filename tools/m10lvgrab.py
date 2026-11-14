#!/usr/bin/env python3
"""Grab the camera live view over CHDK PTP -> PNG.

    m10lvgrab.py OUT.png

PTP GetDisplayData fails on this build, so we read Canon's UYVY viewport
ring directly: viewport_buffers (ROM 0xfc62318c, 4 buffers) and
current_viewport_buffer (RAM 0x8810); the frame after the current one is
the last complete frame (CHDK vid_get_viewport_live_fb).  Size from
GetVRAMHPixelsSize/GetVRAMVPixelsSize (0xfc12a4d3/0xfc12a4db); buffer
row pitch 736 px.
"""
import os, struct, sys
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam

CMD_GETDISPLAY = 10


VP_BUFS = [0x42cf6a00, 0x430eb200, 0x434dfa00, 0x438d4200]


def grab(c, pitch=736):
    cur = c.peek(0x8810)[0]
    i = VP_BUFS.index(cur) if cur in VP_BUFS else 0
    buf = VP_BUFS[(i + 1) & 3]
    vw = c.call(0xfc12a4d3)
    vh = c.call(0xfc12a4db)
    if not (0 < vw <= pitch and 0 < vh <= 1080):
        vw, vh = 720, 480
    n = pitch * vh * 2
    d = bytearray()
    for o in range(0, n, 0x10000):
        d += c.read(buf + o, min(0x10000, n - o))
    return bytes(d), 2, 0, pitch, vw, vh


def to_rgb(d, fb_type, start, bw, vw, vh):
    if fb_type in (2, 3):              # UYVY, 2 bytes / pixel
        raw = np.frombuffer(d, np.uint8, bw * vh * 2, start).reshape(vh, bw * 2)
        u = raw[:, 0::4].astype(float) - 128
        y0 = raw[:, 1::4].astype(float)
        v = raw[:, 2::4].astype(float) - 128
        y1 = raw[:, 3::4].astype(float)
        y = np.empty((vh, bw)); y[:, 0::2] = y0; y[:, 1::2] = y1
        u = np.repeat(u, 2, 1); v = np.repeat(v, 2, 1)
    elif fb_type == 0:                 # UYVYYY, 6 bytes / 4 pixels
        raw = np.frombuffer(d, np.uint8, bw * vh * 6 // 4, start).reshape(vh, bw * 6 // 4)
        u = raw[:, 0::6].astype(float) - 128
        v = raw[:, 2::6].astype(float) - 128
        y = np.empty((vh, bw))
        for i, o in enumerate((1, 3, 4, 5)):
            y[:, i::4] = raw[:, o::6]
        u = np.repeat(u, 4, 1); v = np.repeat(v, 4, 1)
    else:
        raise SystemExit("unsupported fb_type %d" % fb_type)
    y, u, v = y[:, :vw], u[:, :vw], v[:, :vw]
    # DIGIC 6 chroma is signed in practice; BT.601
    r = y + 1.402 * v
    g = y - 0.344 * u - 0.714 * v
    b = y + 1.772 * u
    return np.clip(np.dstack([r, g, b]), 0, 255).astype(np.uint8)


def save_png(rgb, fn):
    import zlib
    h, w, _ = rgb.shape
    raw = b"".join(b"\0" + rgb[i].tobytes() for i in range(h))
    chunk = lambda t, x: struct.pack(">I", len(x)) + t + x + struct.pack(">I", zlib.crc32(t + x) & 0xffffffff)
    open(fn, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                         + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    c = Cam()
    d, t, s, bw, vw, vh = grab(c)
    c.close()
    print("fb_type %d buffer %d visible %dx%d" % (t, bw, vw, vh))
    save_png(to_rgb(d, t, s, bw, vw, vh), sys.argv[1])
    print("->", sys.argv[1])
