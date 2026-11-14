#!/usr/bin/env python3
"""live100 (Fable step 4): head-error rate vs CH12 start delay.

    m10heseries.py TAGBASE LO[:HI] [LO[:HI] ...] [-n REPEAT]

Runs 300-frame NORAW 1x3 series (CMOS 7 = 0x280, he 4, v89g recovery), one per
LO (round-robin, REPEAT times), and appends 'tag lo hi frames he_n' to
captures/live71/heseries.txt.  Stops at the first run where the camera is gone.
"""
import os, sys, re, subprocess, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'captures', 'live71')


def last_block(path):
    t = open(path, errors='replace').read().splitlines()
    fr = he = None
    for ln in t:
        m = re.search(r'v37 REC frames=(\d+)', ln)
        if m: fr = int(m.group(1)); he = None
        m = re.search(r'v87 he_n=(\d+)', ln)
        if m: he = int(m.group(1))
    return fr, he


def main(a):
    rep = 1
    if '-n' in a:
        i = a.index('-n'); rep = int(a[i + 1]); a = a[:i] + a[i + 2:]
    base, wins = a[0], a[1:]
    res = open(os.path.join(OUT, 'heseries.txt'), 'a')
    for r in range(rep):
        for w in wins:
            lo, hi = (w.split(':') + [None])[:2]
            hi = hi or str(int(lo) + 2500)
            tag = '%s_lo%s_hi%s_%d' % (base, lo, hi, r)
            time.sleep(3)   # live101: let Canon settle after the previous M -> Film (r101a_7 froze at USB open)
            env = dict(os.environ, CMOS='7=0x280', NORAW='1', TAG=tag)
            p = subprocess.run(['timeout', '300', sys.executable, os.path.join(HERE, 'm10x3raw.py'),
                                'x3', '300', '1184', '10', '0', '0', '0x23800980', '0', '0x80000001',
                                lo, hi, '6', '0', '0', '12', '4', '99'],
                               env=env, capture_output=True, text=True)
            out = p.stdout + p.stderr
            logp = os.path.join(OUT, '%s_M10CINE.LOG' % tag)
            fr, he = last_block(logp) if os.path.exists(logp) else (None, None)
            alive = 'clean  tg=3' in out
            line = '%s lo=%s hi=%s frames=%s he_n=%s alive=%d' % (tag, lo, hi, fr, he, alive)
            print(line, flush=True)
            res.write(line + '\n'); res.flush()
            if not alive:
                print(out[-1500:])
                return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
