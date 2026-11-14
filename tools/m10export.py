#!/usr/bin/env python3
"""Export an M10 shell take (compressed MLV, x5 magnifier) for a normal editing / grading app.

    m10export.py prores  M10_0007.MLV [OUT.mov]   ProRes 4444, ARRI LogC3 curve + ARRI Wide Gamut 3
    m10export.py dng     M10_0007.MLV [OUTDIR]    CinemaDNG sequence (true RAW, 16-bit, one file per frame)

The .M00 / .M01 ... chunks next to the .MLV are picked up automatically.

Options (environment variables):
    FIRST=0 LAST=        frame range (LAST excluded)
    FPS=25               frame rate written in the file
    EV=0                 ProRes: exposure shift in stops (+1 = one stop brighter in log)
    HEAD=4               ProRes: stops of headroom above 18 % grey for the sensor clip point
    WB=daylight|auto     ProRes: daylight (0.48 / 1 / 0.66) or grey-world from the first 25 frames
                         (DNG: the same neutral is written as AsShotNeutral, the app can change it)

ProRes log: in DaVinci Resolve, set the clip's input to "ARRI LogC3 / ARRI Wide Gamut 3"
(Color Space Transform, or the built-in "ARRI LogC3 to Rec709" LUT); in Premiere / Final Cut,
use the "ARRI LogC3 to Rec709" LUT. Middle grey sits at the LogC3 EI 800 grey level (0.391).
CinemaDNG: import the folder in Resolve (Camera RAW tab: white balance, exposure, then any log).

Per frame (both modes): LJ92 decode, head-error repair (m10ljmlv.repaired), black 127.5, white 1023.
ProRes adds: bilinear demosaic, white balance, camera -> AWG3 matrix (DNG ColorMatrix of the
EOS M10), saturated pixels -> neutral, LogC3 encode, 10-bit 4:4:4.
"""
import glob, os, struct, subprocess, sys
import numpy as np
from scipy.ndimage import convolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m10ljmp4 as P
import m10mlv as M
import m10raw2dng as R

BLACK, WHITE = 127.5, 1023.0
CLIP = WHITE - BLACK        # live122: x5 shell takes clip at 1023 (the 940 of the 3x3 Film mode cut 0.15 stop)
KNEE = 0.80                 # soft roll to neutral from 80 % of the clip point (no flat white patches)
DAYLIGHT = np.array([0.48, 1.0, 0.66])

# ARRI Wide Gamut 3 -> XYZ (D65)
AWG3_XYZ = np.array([[0.638008, 0.214704, 0.097744],
                     [0.291954, 0.823841, -0.115795],
                     [0.002798, -0.067034, 1.153294]])
_c = (np.array(M.COLOR_MATRIX_M10, np.float64).reshape(3, 3) / 10000) @ AWG3_XYZ   # AWG3 -> camera
_c = _c / _c.sum(1, keepdims=True)                    # white stays white after WB
CAM2AWG3 = np.linalg.inv(_c).astype(np.float32)


def logc3(t):
    """ARRI LogC3, EI 800 (scene linear, 0.18 = grey -> 0.391)."""
    t = np.maximum(t, -0.0)
    return np.where(t > 0.010591, 0.247190 * np.log10(np.maximum(5.555556 * t + 0.052272, 1e-6)) + 0.385537,
                    5.367655 * t + 0.092809)


def chunks(mlv):
    base = os.path.splitext(mlv)[0]
    extra = sorted(f for f in glob.glob(base + '.M[0-9][0-9]'))
    return [mlv] + extra


def active(img):
    """Active area of a shell take: OB rows 0-27 dropped; OB columns only if the frame has them."""
    x0 = 72 if img.shape[1] == 2592 else 0
    a = img[28:, x0:]
    return a[:a.shape[0] // 2 * 2, :a.shape[1] // 2 * 2]


def write_cdng(path, img, neutral, fps, frame):
    h, w = img.shape
    entries = []

    def add(tag, typ, values):
        fmt = {1: 'B', 2: 's', 3: 'H', 4: 'I', 5: 'II', 10: 'ii'}[typ]
        if typ == 2:
            b = values.encode() + b'\0'; entries.append((tag, typ, len(b), b)); return
        b = b''.join(struct.pack('<' + fmt, *v) for v in values) if typ in (5, 10) else struct.pack('<%d%s' % (len(values), fmt), *values)
        entries.append((tag, typ, len(values), b))

    pix = img.astype('<u2').tobytes()
    add(254, 4, [0]); add(256, 4, [w]); add(257, 4, [h]); add(258, 3, [16]); add(259, 3, [1])
    add(262, 3, [32803]); add(271, 2, 'Canon'); add(272, 2, 'Canon EOS M10')
    add(273, 4, [0]); add(274, 3, [1]); add(277, 3, [1]); add(278, 4, [h]); add(279, 4, [len(pix)])
    add(284, 3, [1]); add(305, 2, 'm10export')
    add(33421, 3, [2, 2]); add(33422, 1, [0, 1, 1, 2])                   # RGGB
    add(50706, 1, [1, 4, 0, 0]); add(50707, 1, [1, 1, 0, 0]); add(50708, 2, 'Canon EOS M10')
    add(50710, 1, [0, 1, 2]); add(50711, 3, [1])
    add(50713, 3, [1, 1]); add(50714, 5, [R.rational(BLACK, 1000)]); add(50717, 4, [int(WHITE)])
    add(50721, 10, [(v, 10000) for v in M.COLOR_MATRIX_M10])
    add(50728, 5, [R.rational(v) for v in neutral])
    add(50778, 3, [21])                                                   # D65
    add(50829, 4, [0, 0, h, w])                                           # ActiveArea
    add(51044, 10, [(int(round(float(fps) * 1000)), 1000)])               # FrameRate (CinemaDNG)
    s = frame // int(round(float(fps))); f = frame % int(round(float(fps)))
    bcd = lambda v: ((v // 10) << 4) | (v % 10)
    add(51043, 1, [bcd(f), bcd(s % 60), bcd(s // 60 % 60), bcd(s // 3600), 0, 0, 0, 0])   # TimeCodes
    entries.sort(key=lambda e: e[0])
    ifd_off = 8
    extra_off = ifd_off + 2 + 12 * len(entries) + 4
    extra, ifd, strip_pos = bytearray(), bytearray(struct.pack('<H', len(entries))), None
    for tag, typ, count, b in entries:
        if len(b) <= 4:
            ifd += struct.pack('<HHI', tag, typ, count) + b.ljust(4, b'\0')
            if tag == 273: strip_pos = len(ifd) - 4
        else:
            ifd += struct.pack('<HHII', tag, typ, count, extra_off + len(extra))
            extra += b
            if len(extra) % 2: extra += b'\0'
    ifd += struct.pack('<I', 0)
    pix_off = extra_off + len(extra); pix_off += (-pix_off) % 16
    ifd[strip_pos:strip_pos + 4] = struct.pack('<I', pix_off)
    with open(path, 'wb') as fo:
        fo.write(b'II*\0' + struct.pack('<I', ifd_off)); fo.write(ifd); fo.write(extra)
        fo.write(b'\0' * (pix_off - extra_off - len(extra))); fo.write(pix)


def grey_world(frames):
    acc = np.zeros(3)
    for a in frames:
        x = a.astype(np.float32) - BLACK
        r, g, b = x[0::2, 0::2], (x[0::2, 1::2] + x[1::2, 0::2]) / 2, x[1::2, 1::2]
        ok = (r < CLIP * 0.9) & (g < CLIP * 0.9) & (b < CLIP * 0.9) & (g > 8)
        acc += [r[ok].mean(), g[ok].mean(), b[ok].mean()]
    return acc / acc[1]


def main(a):
    if len(a) < 2 or a[0] not in ('prores', 'dng'):
        print(__doc__); return 2
    mode, mlv = a[0], a[1]
    files = chunks(mlv)
    base = os.path.splitext(os.path.basename(mlv))[0]
    out = a[2] if len(a) > 2 else os.path.join(os.path.dirname(mlv) or '.', base + ('_LogC3.mov' if mode == 'prores' else '_CDNG'))
    fps = os.environ.get('FPS', '25')
    first = int(os.environ.get('FIRST', '0'))
    last = int(os.environ['LAST']) if os.environ.get('LAST') else None
    ev = float(os.environ.get('EV', '0')); head = float(os.environ.get('HEAD', '4'))
    wbmode = os.environ.get('WB', 'daylight')
    print('%s: %s -> %s' % (mode, ' + '.join(os.path.basename(f) for f in files), out), flush=True)

    src = (active(img) for k, img in P.chained(files, first, last))
    neutral = DAYLIGHT
    pending = []
    if wbmode == 'auto':
        for img in src:
            pending.append(img)
            if len(pending) >= 25: break
        neutral = grey_world(pending)
        print('auto WB neutral %.3f %.3f %.3f' % tuple(neutral), flush=True)

    def stream():
        yield from pending
        yield from src

    n = 0
    if mode == 'dng':
        os.makedirs(out, exist_ok=True)
        for img in stream():
            write_cdng(os.path.join(out, '%s_%06d.dng' % (base, n)), img, neutral, fps, n)
            n += 1
            if n % 100 == 0: print('%d frames' % n, flush=True)
        print('-> %s  %d DNG, %dx%d, %s fps' % (out, n, img.shape[1], img.shape[0], fps))
        return 0

    wb = (1.0 / neutral).astype(np.float32)
    scale = CLIP / (0.18 * 2 ** head) / (2 ** ev)       # raw units per scene-linear 1.0
    p = None
    for img in stream():
        x = img.astype(np.float32) - BLACK
        x = np.minimum(x, CLIP)
        rgb = P.demosaic(x)
        # live122: how close to the clip each pixel is (largest raw channel), 0 below KNEE, 1 at clip
        s = np.clip((rgb.max(-1) / CLIP - KNEE) / (1 - KNEE), 0, 1)
        s = convolve(s, np.ones((3, 3), np.float32) / 9, mode='mirror')[..., None]
        rgb = rgb * wb
        rgb = rgb * (1 - s) + rgb.max(-1, keepdims=True) * s
        rgb = (rgb @ CAM2AWG3.T) / scale
        o = (np.clip(logc3(rgb), 0, 1) * 65535 + 0.5).astype('<u2')
        if p is None:
            h, w = o.shape[:2]
            p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb48le',
                                  '-s', '%dx%d' % (w, h), '-r', fps, '-i', '-',
                                  '-c:v', 'prores_ks', '-profile:v', '4', '-pix_fmt', 'yuv444p10le', '-vendor', 'apl0',
                                  '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                                  '-metadata:s:v', 'comment=ARRI LogC3 EI800 / ARRI Wide Gamut 3',
                                  out], stdin=subprocess.PIPE)
        p.stdin.write(o.tobytes()); n += 1
        if n % 100 == 0: print('%d frames' % n, flush=True)
    if p is None:
        print('no frame'); return 1
    p.stdin.close(); rc = p.wait()
    print('-> %s  %d frames, %dx%d, %s fps, ffmpeg rc %d' % (out, n, w, h, fps, rc))
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
