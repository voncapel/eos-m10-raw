#!/usr/bin/env python3
"""live106: calibrate the line-count registers at H = 1190 (head untouched, true 1x3, HEAD output).

    m10tgcal.py TAG SPEC [SPEC ...]      SPEC = tgv string of m10tall3.py, e.g. 82b6:1001  or  d88c6:1000,d88ce:1000

One Film commit + 2 isolated passes per SPEC (m10tall3.py 1190 nohiv tgv=SPEC rec=2 lines=1184
xo=88000001).  For each: the values really sent (commit trace) and the row classes of pass 0:
  T = textured (sd > 5), a = flat with analogue noise (0.3 < sd <= 5, sensor powered down),
  D = flat and constant (sd <= 0.3, digital blanking).
Stops at the first run that fails.  Output: captures/live106/<TAG>_<spec>_*, tgcal_<TAG>.txt
"""
import os, sys, subprocess, shutil
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import m10lvx3dec as D, m10siodec as S
SRC = os.path.join(HERE, '..', 'captures', 'live103')
OUT = os.path.join(HERE, '..', 'captures', 'live106')


def ungray(g):
    n = 0
    while g:
        n ^= g
        g >>= 1
    return n


def rows(fn, k=0):
    d = open(fn, 'rb').read()
    w, lines, lb, npass, ndone = D.header(d)
    if ndone <= k:
        return None
    img = D.decode(d[D.HDR + k * lines * lb:D.HDR + (k + 1) * lines * lb], lb * 8 // w, w, lines, lb, 0).astype(np.float32)
    sd, mean, ob = img[:, 200:1700].std(1), img[:, 200:1700].mean(1), img[:, :72].mean(1)
    fill = np.nonzero(np.abs(ob - 852.5) < 1)[0]
    end = int(fill.min()) if len(fill) else lines
    cls = ''.join('T' if s > 5 else ('a' if s > 0.3 else 'D') for s in sd[:end])
    segs, i = [], 0
    while i < end:                      # run-length, periodic stretches (period 5) folded
        j = i
        while j < end and cls[j] == cls[i]:
            j += 1
        segs.append((i, j - 1, cls[i]))
        i = j
    out, i = [], 0
    while i < len(segs):
        if segs[i][1] - segs[i][0] < 6:  # short runs: describe the mixed stretch as a whole
            j = i
            while j < len(segs) and segs[j][1] - segs[j][0] < 6:
                j += 1
            part = cls[segs[i][0]:segs[j - 1][1] + 1]
            out.append('%d-%d mixed(%s, %d%% T)' % (segs[i][0], segs[j - 1][1], part[:10], 100 * part.count('T') // len(part)))
            i = j
        else:
            a, b, c = segs[i]
            out.append('%d-%d %s(%.0f)' % (a, b, c, mean[a:b + 1].mean()))
            i += 1
    return end, out


def sent(fn, regs):
    d = {}
    for w in S.writes(S.load(fn)):
        if w[2] in ('TG', 'DFE') and w[3] in regs:
            d.setdefault(w[3], []).append(w[4])
    return ' '.join('%04x=%s' % (r, '/'.join('%x(g%d)' % (v, ungray(v)) for v in sorted(set(d[r])))) if r in d else '%04x=NOT SEEN' % r
                    for r in sorted(regs))


def main(a):
    os.makedirs(OUT, exist_ok=True)
    tag, log = a[0], open(os.path.join(OUT, 'tgcal_%s.txt' % a[0]), 'a')

    def say(s):
        print(s, flush=True)
        log.write(s + '\n')
        log.flush()
    for spec in a[1:]:
        name = '%s_%s' % (tag, spec.replace(':', '-').replace(',', '_'))
        for f in ('LVX3.BIN', 'M10CINE.LOG', 'LVX3S.BIN'):
            p = os.path.join(SRC, '%s_%s' % (name, f))
            if os.path.exists(p):
                os.remove(p)
        cmd = [sys.executable, os.path.join(HERE, 'm10tall3.py'), '1190', 'nohiv', 'c7=0x240', 'watch=1', 'wbkick', 'rearm',
               'rec=2', 'lines=1184', 'fl=0x20000000', 'xo=88000001', 'tag=' + name] + (['tgv=' + spec] if spec != 'ref' else [])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        keep = [l for l in r.stdout.splitlines() if l.startswith(('module_run', 'exception', 'TG task', 'watch', 'clean'))]
        say('=== %s' % spec)
        for l in keep:
            say('    ' + l[:230])
        regs = {0x8172, 0x8178, 0x82b6, 0x82f8, 0x8196, 0x8197, 0x88c6, 0x88ce, 0x88d6, 0x88d7}
        csio = os.path.join(SRC, 'tall3_H1190_c7-240_nohiv_commit.sio')
        if os.path.exists(csio):
            say('    sent  ' + sent(csio, regs))
            shutil.copy(csio, os.path.join(OUT, name + '_commit.sio'))
        fn = os.path.join(SRC, name + '_LVX3.BIN')
        if not os.path.exists(fn) or 'module_run -> 0' not in r.stdout:
            say('    FAILED (stop)')
            say(r.stdout[-600:])
            break
        for f in ('LVX3.BIN', 'M10CINE.LOG', 'LVX3S.BIN'):
            shutil.move(os.path.join(SRC, '%s_%s' % (name, f)), os.path.join(OUT, '%s_%s' % (name, f)))
        for k in (0, 1):
            x = rows(os.path.join(OUT, name + '_LVX3.BIN'), k)
            if x:
                say('    pass %d: %d rows | %s' % (k, x[0], ' | '.join(x[1])))


if __name__ == '__main__':
    main(sys.argv[1:])
