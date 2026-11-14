#!/usr/bin/env python3
"""live120: what crops the x5 magnifier display?  Read-only snapshots.

    m10zoomdisp.py wake            half-press + set_record (no hook, no USB mode change once in M)
    m10zoomdisp.py snap TAG        engine shadow (512 KiB) + head 6800/6804 + zoom state RAM
                                   -> captures/live120/zd_TAG.{shadow,json}
    m10zoomdisp.py diff A B        list shadow words that differ between snapshots A and B
    m10zoomdisp.py ram TAG         RAM 0x1000-0x400000 -> captures/live120/ram_TAG.bin
    m10zoomdisp.py ramdiff A B     words/halfwords in 1..3000 that changed (magnifier position nudge)

Never reads 0xC0/0xD0 directly: the shadow is RAM (*(0x28dbc)).
"""
import os, sys, json, struct
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam, fmt_msg

OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live120')
SIZE = 0x80000


def snap(tag):
    os.makedirs(OUT, exist_ok=True)
    c = Cam(timeout=20000)
    base = c.peek(0x28dbc)[0]
    sh = b''.join(c.read(base + o, 0x10000) for o in range(0, SIZE, 0x10000))
    open(os.path.join(OUT, 'zd_%s.shadow' % tag), 'wb').write(sh)
    w = lambda r: struct.unpack_from('<I', sh, r & 0x7ffff)[0]
    info = {'6800': '%08x' % w(0xc0f06800), '6804': '%08x' % w(0xc0f06804),
            'imgsens_mode': c.peek(0x865c)[0], 'extract_idx': c.peek(0xe460 + 0xc)[0]}
    for k in ('get_zoom', 'get_focus'):
        try: info[k] = fmt_msg(c.lua('return %s()' % k)[-1])
        except Exception as e: info[k] = str(e)
    c.close()
    json.dump(info, open(os.path.join(OUT, 'zd_%s.json' % tag), 'w'), indent=1)
    print(tag, info)


def diff(a, b):
    A = open(os.path.join(OUT, 'zd_%s.shadow' % a), 'rb').read()
    B = open(os.path.join(OUT, 'zd_%s.shadow' % b), 'rb').read()
    n = 0
    for o in range(0, SIZE, 4):
        x, y = struct.unpack_from('<I', A, o)[0], struct.unpack_from('<I', B, o)[0]
        if x != y:
            print('c0f%05x  %08x  %08x' % (o, x, y)); n += 1
    print(n, 'differ')


def ram(tag):
    c = Cam(timeout=30000)
    print('6804 %08x' % c.shadow(0xc0f06804))
    d = b''.join(c.read(a, 0x10000) for a in range(0x1000, 0x400000, 0x10000))
    c.close()
    open(os.path.join(OUT, 'ram_%s.bin' % tag), 'wb').write(d)
    print('ram', tag, len(d))


def ramdiff(a, b, lo=1, hi=3000):
    A = open(os.path.join(OUT, 'ram_%s.bin' % a), 'rb').read()
    Bb = open(os.path.join(OUT, 'ram_%s.bin' % b), 'rb').read()
    for o in range(0, min(len(A), len(Bb)) - 4, 4):
        x, y = struct.unpack_from('<I', A, o)[0], struct.unpack_from('<I', Bb, o)[0]
        if x != y and lo <= x <= hi and lo <= y <= hi:
            print('%08x  %6d -> %6d' % (0x1000 + o, x, y))
        else:
            for k in (0, 2):
                u, v = struct.unpack_from('<H', A, o + k)[0], struct.unpack_from('<H', Bb, o + k)[0]
                if u != v and lo <= u <= hi and lo <= v <= hi and x != y and not (lo <= x <= hi):
                    print('%08x h %6d -> %6d' % (0x1000 + o + k, u, v))


def wake():
    c = Cam(timeout=20000)
    for code in ['press("shoot_half") sleep(800) release("shoot_half") sleep(500)', 'set_record(true) sleep(2500)',
                 'press("shoot_half") sleep(800) release("shoot_half") sleep(800)']:
        try: c.lua(code)
        except Exception as e: print('lua err', e)
    print('record mode:', fmt_msg(c.lua('return tostring(get_mode())')[-1]))
    c.close()


if __name__ == '__main__':
    a = sys.argv[1:]
    {'wake': lambda: wake(), 'snap': lambda: snap(a[1]), 'diff': lambda: diff(a[1], a[2]), 'ram': lambda: ram(a[1]), 'ramdiff': lambda: ramdiff(a[1], a[2])}[a[0]]()
