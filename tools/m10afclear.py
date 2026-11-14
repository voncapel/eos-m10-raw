#!/usr/bin/env python3
"""live100: find the lightest Canon action that clears the AF-pixel defect
left by a trapped head error (pink dots in every frame after the first error).

    m10afclear.py [MAXTRY]

1. Record 300 frames (NOCLEAN) until a run shows AF dots in its last frames
   (at most MAXTRY runs, default 3).
2. Then, without any M -> Film commit, try in order:
     nothing (control), half-press, ISO change and back, zoom x5 and back,
     M -> Film (full re-commit, known to clear it)
   each followed by a 6-frame NOMODE capture; report the AF-dot count.
Captures: captures/live99/r100af_<step>.MLV.  Needs: trap installed, CMOS 7
override handled by m10x3raw (CMOS=7=0x280), module >= v89c on the card.
"""
import os, sys, subprocess, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import m10mlv as M, m10lvx3dec as D
from m10ptp import Cam

L71 = os.path.join(HERE, '..', 'captures', 'live71')
L99 = os.path.join(HERE, '..', 'captures', 'live99')
BASE = ['x3', None, '1184', '10', '0', '0', '0x23800980', '0', '0x80000001', '5000', '7500',
        '6', '0', '0', '12', '4', '99']


def run(tag, n, env):
    a = list(BASE); a[1] = str(n)
    e = dict(os.environ, CMOS='7=0x280', TAG=tag, NOCLEAN='1', **env)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'm10x3raw.py')] + a, env=e,
                       capture_output=True, text=True, timeout=900)
    out = r.stdout + r.stderr
    ok = 'module_run -> 0' in out
    src = os.path.join(L71, tag + '_M10X3.MLV')
    dst = os.path.join(L99, tag + '.MLV')
    if os.path.exists(src):
        os.replace(src, dst)
    return ok, dst if os.path.exists(dst) else None, out


def dots(fn):
    res = []
    for info, data in M.mlv_frames(fn):
        a = D.decode(data, 10, 1808, 1184, 2260, 0)[M.PAD_ROWS:, M.OB_COLS:]
        res.append(int((a < 100).sum()))
    return res


def lua(code):
    c = Cam(timeout=60000)
    try:
        return c.lua(code)
    finally:
        c.close()


def main(a):
    maxtry = int(a[0]) if a else 3
    got = False
    for t in range(maxtry):
        tag = 'r100af_seed%d' % t
        ok, fn, out = run(tag, 300, {'NORAW': '1'})     # dots follow any trapped error: read the log
        log = os.path.join(L71, tag + '_M10CINE.LOG')
        if not ok or not os.path.exists(log):
            print(tag, 'FAILED', out[-400:]); return
        txt = open(log, 'rb').read().decode('latin1')
        he = txt.rsplit('v87 he_n=', 1)[-1].split()[0] if 'v87 he_n=' in txt else '?'
        print(tag, 'he_n', he)
        if he not in ('0', '?'):
            got = True; break
    if not got:
        print('no run with AF dots, stop'); return
    steps = [
        ('control', None),
        ('halfpress', 'press("shoot_half") sleep(800) release("shoot_half") sleep(1500)'),
        ('iso', 'local s=get_sv96() set_sv96(s+96) sleep(1500) set_sv96(s) sleep(1500)'),
        ('zoom5', 'click("zoom_in") sleep(1500) click("zoom_in") sleep(1500)'),
        ('mfilm', None),
    ]
    for name, code in steps:
        if code:
            try:
                print(name, 'lua', lua(code))
            except Exception as e:
                print(name, 'lua error', e)
        tag = 'r100af_' + name
        env = {} if name == 'mfilm' else {'NOMODE': '1'}
        ok, fn, out = run(tag, 6, env)
        if not ok or not fn:
            print(tag, 'FAILED', out[-400:]); return
        d = dots(fn)
        print(tag, 'dots per frame', d)
        if d and max(d) < 1000:
            print('==> cleared by', name); return


if __name__ == '__main__':
    main(sys.argv[1:])
