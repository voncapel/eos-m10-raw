#!/usr/bin/env python3
"""live104: last value of every TG / DFE register in SIO traces, side by side.

    m10tgdiff.py A.sio B.sio [C.sio ...] [--all]

Shows the registers whose last value differs between the traces (--all: every register), with the
Gray-decoded value: TG line counters are Gray coded (8172 = 0x6fd -> 1193).  Used to find what else
than 8172/8178/82b6/82f8 carries the sensor frame height (zoom x5 reads 1111 lines in 1:1).
"""
import sys
import m10siodec as S


def ungray(g):
    n = 0
    while g:
        n ^= g
        g >>= 1
    return n


def last(fn):
    d = {}
    for w in S.writes(S.load(fn)):
        if w[2] in ('TG', 'DFE'):
            d[(w[2], w[3])] = w[4]
        elif w[2] == 'CMOS':
            d[('CMOS', w[3])] = w[4]
    return d


def main(a):
    files = [x for x in a if not x.startswith('--')]
    L = [last(f) for f in files]
    print('%-10s' % 'reg' + ''.join('%-22s' % f.split('/')[-1][-21:] for f in files))
    for k in sorted(set().union(*L)):
        v = [d.get(k) for d in L]
        if '--all' in a or len(set(v)) > 1:
            print('%-4s %04x ' % k + ''.join('%-22s' % ('-' if x is None else '%04x (g %d)' % (x, ungray(x))) for x in v))


if __name__ == '__main__':
    main(sys.argv[1:])
