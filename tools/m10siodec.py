#!/usr/bin/env python3
"""Decode a SIO trace saved by `m10sio.py dump FILE` into register writes.

    m10siodec.py FILE            per-frame table (one row per CMOS reg-0 burst)
    m10siodec.py FILE --raw      every decoded write
Writers (by return address): CMOS (ch6, CMOSAccs), CDS, DFE, TG (TgDrvWAKA),
ppp; ch4 writers send (addr, data) as two 16-bit frames.
"""
import struct, sys
NAMES = {0xfc414d41: 'CDS', 0xfc414d4b: 'CDS', 0xfc35b5e9: 'ppp', 0xfc35b5f3: 'ppp',
         0xfc1bec0f: 'CMOS', 0xfc1bd4e3: 'DFE', 0xfc1bd4ed: 'DFE',
         0xfc231323: 'TG', 0xfc23132d: 'TG'}

def load(fn):
    d = open(fn, 'rb').read()
    idx, n = struct.unpack_from('<II', d)
    return [struct.unpack_from('<17I', d, 8 + 68 * i) for i in range(n)]

def writes(E):
    out, i, t0 = [], 0, E[0][1]
    while i < len(E):
        k, t, ch, cfg, nb, lr, d0 = E[i][:7]
        nm = NAMES.get(lr, '%08x' % lr)
        dt = (t - t0) & 0xfffff
        if nm in ('CDS', 'ppp', 'DFE', 'TG') and i + 1 < len(E) and E[i + 1][5] == lr + 10:
            out.append((k, t, nm, d0 & 0xffff, E[i + 1][6] & 0xffff)); i += 2; continue
        if nm == 'CMOS':
            out.append((k, t, nm, d0 >> 12 & 0xf, d0 & 0xfff))
        else:
            out.append((k, t, nm, d0, 0))
        i += 1
    return out

def frames(W):
    fr, cur = [], None
    for w in W:
        if w[2] == 'CMOS' and w[3] == 0:
            cur = {'t': w[1], 'k': w[0]}; fr.append(cur)
        if cur is not None:
            cur[(w[2], w[3])] = w[4]
    return fr

if __name__ == '__main__':
    W = writes(load(sys.argv[1]))
    if '--raw' in sys.argv:
        for w in W: print('%6d %05x %-5s %04x = %04x' % w)
        sys.exit()
    F = frames(W)
    keys = sorted({k for f in F for k in f if isinstance(k, tuple)}, key=lambda x: (x[0], x[1]))
    var = [k for k in keys if len({f.get(k) for f in F}) > 1]
    print('%d frames; constant:' % len(F), ' '.join('%s.%x=%x' % (k[0], k[1], F[-1][k]) for k in keys if k not in var and k in F[-1]))
    print('k      dt_us  ' + ' '.join('%s.%x' % k for k in var))
    pt = None
    for f in F:
        dt = ((f['t'] - pt) & 0xfffff) if pt is not None else 0; pt = f['t']
        print('%6d %6d  ' % (f['k'], dt) + ' '.join(('%x' % f[k]) if k in f else '-' for k in var))
