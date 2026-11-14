#!/usr/bin/env python3
"""Full-resolution MP4 from a compressed M10 MLV (LJ92, Film 3x3 or x5 magnifier 2592 wide), one or several chunks.

    m10ljmp4.py OUT.mp4 FILE.MLV [FILE.M00 ...]   env: FPS=25 FIRST=0 LAST=None CRF=16 EV=0

Per frame: m10ljmlv repaired() (12 px OB shift undone, rows of a head-error frame patched from the
previous frame), AF pixel grid fix (3x3), crop to the 1724 x 1156 active area, bilinear demosaic,
daylight white balance (0.48 / 1 / 0.66), EOS M10 camera -> sRGB matrix, sRGB gamma.
The exposure scale is set once from the first 50 frames (99.5th percentile) and kept, so the
brightness does not pump.  Output: H.264 yuv420p (BT.709), 25 fps by default.
Chunks are decoded in order as one stream (the repair window spans the .MLV -> .M00 boundary).
"""
import os, subprocess, sys
import numpy as np
from scipy.ndimage import convolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m10ljmlv as L
import m10mlv as M

BLACK, WHITE = 127.5, 1023.0
WB = np.array([1 / 0.48, 1.0, 1 / 0.66], np.float32)
Y0, H, X0, W = 28, 1156, 84, 1724

# XYZ (D65) -> camera, from the DNG ColorMatrix1 (rows = camera R, G, B)
XYZ2CAM = np.array(M.COLOR_MATRIX_M10, np.float64).reshape(3, 3) / 10000
SRGB2XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                     [0.2126729, 0.7151522, 0.0721750],
                     [0.0193339, 0.1191920, 0.9503041]])
_c = XYZ2CAM @ SRGB2XYZ                      # sRGB -> camera
_c = _c / _c.sum(1, keepdims=True)           # rows normalised: white stays white after WB
CAM2SRGB = np.linalg.inv(_c).astype(np.float32)

K_G = np.array([[0, 1, 0], [1, 4, 1], [0, 1, 0]], np.float32) / 4
K_RB = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32) / 4


def demosaic(x):
    """Bilinear RGGB demosaic of a black-subtracted float image (even width / height)."""
    h, w = x.shape
    r = np.zeros_like(x); g = np.zeros_like(x); b = np.zeros_like(x)
    r[0::2, 0::2] = x[0::2, 0::2]
    g[0::2, 1::2] = x[0::2, 1::2]; g[1::2, 0::2] = x[1::2, 0::2]
    b[1::2, 1::2] = x[1::2, 1::2]
    return np.stack([convolve(r, K_RB, mode='mirror'), convolve(g, K_G, mode='mirror'),
                     convolve(b, K_RB, mode='mirror')], -1)


def srgb(v):
    v = np.clip(v, 0, 1)
    return np.where(v <= 0.0031308, 12.92 * v, 1.055 * np.power(v, 1 / 2.4) - 0.055)


def chained(files, first, last):
    """repaired() over several chunks, as one stream (no gap in the repair window)."""
    orig = L.frames
    def frames():
        for f in files:
            yield from orig(f)
    L.frames = lambda fn: frames()
    try:
        yield from L.repaired(None, first, last)
    finally:
        L.frames = orig


CLIP = 940 - BLACK          # live114: highlights clip per cell at 948 / 973 / 1023 depending on the
                            # frame (head-error frames, 3x3 binning): treat >= 940 raw as saturated


def highlight(rgb, sat):
    """Saturated pixels -> neutral white (after WB the clipped channels would turn magenta)."""
    if sat.any():
        m = rgb.max(-1)
        rgb[sat] = m[sat, None]
    return rgb


def main(a):
    if len(a) < 2:
        print(__doc__); return 2
    out, files = a[0], a[1:]
    fps = os.environ.get('FPS', '25')
    first = int(os.environ.get('FIRST', '0'))
    last = int(os.environ['LAST']) if os.environ.get('LAST') else None
    crf = os.environ.get('CRF', '16')
    ev = float(os.environ.get('EV', '0'))
    p = None; scale = None; samples = []; buf = []; n = 0
    global Y0, H, X0, W
    for k, img in chained(files, first, last):
        if img.shape[1] != 1808:                 # live117: x5 magnifier 1:1 (OB 72 cols / 28 rows, no AF grid)
            X0 = 72 if img.shape[1] == 2592 else 0   # live119: shell crop EW=2400 EOFF=160 -> no OB columns
            Y0 = 28; H = (img.shape[0] - 28) // 2 * 2; W = img.shape[1] - X0
        else:
            M.fix_af(img, 127, geom='3x3')
        x = img[Y0:Y0 + H, X0:X0 + W].astype(np.float32) - BLACK
        sat = convolve((x >= CLIP).astype(np.float32), np.ones((3, 3), np.float32), mode='mirror') > 0
        x = np.minimum(x, CLIP)
        rgb = demosaic(x) * WB
        rgb = highlight(rgb, sat)
        rgb = rgb @ CAM2SRGB.T
        if scale is None:                    # fixed exposure from the first frames
            buf.append(rgb); samples.append(np.percentile(rgb[::4, ::4], 99.5))
            if len(buf) < 50:
                continue
            scale = max(1.0, float(np.median(samples))) / (2 ** ev)
            pending = buf; buf = None
        else:
            pending = [rgb]
        for f in pending:
            o = (srgb(f / scale) * 255 + 0.5).astype(np.uint8)
            if p is None:
                p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                                      '-s', '%dx%d' % (W, H), '-r', fps, '-i', '-',
                                      '-c:v', 'libx264', '-preset', 'slow', '-crf', crf, '-pix_fmt', 'yuv420p',
                                      '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                                      '-movflags', '+faststart', out], stdin=subprocess.PIPE)
            p.stdin.write(o.tobytes()); n += 1
            if n % 100 == 0:
                print('%d frames' % n, flush=True)
    if buf:                                  # fewer than 50 frames in total
        scale = max(1.0, float(np.median(samples))) / (2 ** ev)
        for f in buf:
            o = (srgb(f / scale) * 255 + 0.5).astype(np.uint8)
            if p is None:
                p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                                      '-s', '%dx%d' % (W, H), '-r', fps, '-i', '-',
                                      '-c:v', 'libx264', '-preset', 'slow', '-crf', crf, '-pix_fmt', 'yuv420p',
                                      '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                                      '-movflags', '+faststart', out], stdin=subprocess.PIPE)
            p.stdin.write(o.tobytes()); n += 1
    if p is None:
        print('no frame'); return 1
    p.stdin.close(); rc = p.wait()
    print('-> %s  %d frames, %dx%d, %s fps, scale %.1f, ffmpeg rc %d' % (out, n, W, H, fps, scale, rc))
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
