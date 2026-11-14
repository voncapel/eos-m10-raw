#!/usr/bin/env python3
"""m10fpm.py [OUT.fpm]   -> MLV App focus pixel map for the M10 FHD 1x3 stream.

MLV App (pixelproc.c load_pixel_map) looks for '<cameraId hex>_<raw_width>x<raw_height>.fpm'
next to the application binary (drag the file onto the MLV App window to install it);
one 'x y' pair per line, coordinates in the raw frame (before active_area cropping,
panPos is 0 in our MLV).  Grid measured live100/live102: box rows 115-1091 / cols
244-1659 after the 4 pad rows, 12 cells per 10x8 block (row % 10, col % 8)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m10mlv as M

W, H, CAM = 1808, 1184, 0x80000355
out = sys.argv[1] if len(sys.argv) > 1 else '%x_%dx%d.fpm' % (CAM, W, H)
r0, r1, c0, c1 = M.AF_BOX
n = 0
with open(out, 'w') as f:
    f.write('#FPM %X Canon EOS M10 FHD 1x3 (m10cine), 12-cell AF grid\n' % CAM)
    for y in range(r0, r1 + 1):
        for x in range(c0, c1 + 1):
            if (y % 10, x % 8) in M.AF_GRID12:
                f.write('%d %d\n' % (x, y + M.PAD_ROWS)); n += 1
print(out, n, 'pixels')
