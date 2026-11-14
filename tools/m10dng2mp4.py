#!/usr/bin/env python3
"""m10dng2mp4.py DNGDIR OUT.mp4 [fps=12.5] [width=1920] [gain=2.0]
Quick preview: rawpy demosaic (camera WB, 16-bit), horizontal 3:1 de-anamorphose
to `width`, exposure gain, x264 CRF 18.  Needs rawpy + ffmpeg."""
import sys, os, glob, subprocess, numpy as np, rawpy

d, out = sys.argv[1], sys.argv[2]
fps = float(sys.argv[3]) if len(sys.argv) > 3 else 12.5
W = int(sys.argv[4]) if len(sys.argv) > 4 else 1920
gain = float(sys.argv[5]) if len(sys.argv) > 5 else 2.0
files = sorted(glob.glob(os.path.join(d, '*.dng')))
p = None
for i, fn in enumerate(files):
    with rawpy.imread(fn) as r:
        rgb = r.postprocess(use_camera_wb=True, output_bps=16, no_auto_bright=True, gamma=(2.222, 4.5),
                            bright=gain, user_flip=0, output_color=rawpy.ColorSpace.sRGB)
    h, w = rgb.shape[:2]
    H = int(W * h / w) // 2 * 2
    if p is None:
        p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb48le',
                              '-s', '%dx%d' % (w, h), '-r', str(fps), '-i', '-', '-vf', 'scale=%d:%d:flags=lanczos' % (W, H),
                              '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out],
                             stdin=subprocess.PIPE)
        print('%d frames %dx%d -> %dx%d @ %.2f fps' % (len(files), w, h, W, H, fps))
    p.stdin.write(rgb.astype('<u2').tobytes())
p.stdin.close(); p.wait()
print('->', out, '%.1f MB' % (os.path.getsize(out) / 1e6))
