#!/usr/bin/env python3
"""1x3 RAW recording -> MP4 preview through the DNG pipeline (rawpy/LibRaw
demosaic, colour matrix, 3:1 horizontal stretch).

    m10x3preview.py FILE OUT.mp4 [--frames a:b] [--bright 2.0] [--width 1920]
"""
import argparse, os, subprocess, sys, tempfile
import numpy as np, rawpy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m10x3dng as X


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file'); ap.add_argument('out')
    ap.add_argument('--frames', default='0:'); ap.add_argument('--bright', type=float, default=2.0)
    ap.add_argument('--width', type=int, default=1920); ap.add_argument('--wb', default='daylight')
    a = ap.parse_args()
    d, w, lines, lb, bpp, fb, n = X.frames(a.file)
    s, e = (a.frames.split(':') + [''])[:2]
    s = int(s or 0); e = min(int(e) if e else n, n)
    tmp = tempfile.mkdtemp()
    subprocess.run([sys.executable, X.__file__, a.file, tmp, '--frames', '%d:%d' % (s, e), '--wb', a.wb], check=True)
    proc = None
    for k in range(s, e):
        with rawpy.imread(os.path.join(tmp, 'f%05d.dng' % k)) as r:
            rgb = r.postprocess(use_camera_wb=True, output_bps=8, no_auto_bright=True, bright=a.bright,
                                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD)
        h, ww = rgb.shape[:2]
        if proc is None:
            oh = int(a.width * h / ww) // 2 * 2
            proc = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                                     '-s', '%dx%d' % (ww, h), '-r', '25', '-i', '-', '-vf',
                                     'scale=%d:%d:flags=lanczos' % (a.width, oh), '-pix_fmt', 'yuv420p',
                                     '-c:v', 'libx264', '-crf', '16', a.out], stdin=subprocess.PIPE)
        proc.stdin.write(np.ascontiguousarray(rgb).tobytes())
        os.remove(os.path.join(tmp, 'f%05d.dng' % k))
    proc.stdin.close(); proc.wait()
    print('wrote', a.out, e - s, 'frames')


if __name__ == '__main__':
    main()
