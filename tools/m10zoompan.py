#!/usr/bin/env python3
"""Find the sensor window-position registers: pan the zoom x5 box with the
arrow keys while tracing every CMOS / TG write (hook v4, passive).

    m10zoompan.py [KEYS]     default KEYS = up,up,up,down,down,down,down,down,down,left,left,right,right,right,right

The camera must already be in zoom x5 (head 6804 = 045702a6).  For each key:
click it (Lua), keep pulling the SIO ring, then note per-frame CMOS regs 1-9
and every TG write.  Prints the registers whose value changed after each key.
Writes nothing to the sensor; only presses keys.
Output: captures/live80/zoompan.{sio,txt}
"""
import os, struct, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio
from m10siodec import writes

OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live80')
ESZ = 64


class Ring:
    def __init__(self, k):
        self.k, self.nm1 = k, k.h(16)
        self.last, self.ents, self.lost = k.h(4), [], 0

    def pull(self):
        k, nent = self.k, self.nm1 + 1
        idx = k.h(4)
        if idx - self.last > nent - 64:
            self.lost += idx - self.last - (nent - 64)
            self.last = idx - (nent - 64)
        while self.last < idx:
            s = self.last & self.nm1
            cnt = min(idx - self.last, nent - s, 1024)
            raw = k.c.read(k.b + k.ent + s * ESZ, cnt * ESZ)
            for j in range(cnt):
                self.ents.append((self.last + j,) + struct.unpack_from('<16I', raw, j * ESZ))
            self.last += cnt
        return idx

    def run(self, secs):
        t0 = time.time()
        while time.time() - t0 < secs:
            self.pull()
            time.sleep(0.05)


def cmos_frames(W):
    """list of (sio_idx, {reg: val}) per CMOS burst (starts at reg 0)."""
    out, cur = [], None
    for w in W:
        if w[2] == 'CMOS':
            if w[3] == 0:
                cur = (w[0], {}); out.append(cur)
            if cur:
                cur[1][w[3]] = w[4]
    return out


def main(a):
    keys = (a[0] if a else 'up,up,up,down,down,down,down,down,down,'
            'left,left,right,right,right,right').split(',')
    os.makedirs(OUT, exist_ok=True)
    c = Cam()
    k = m10sio.find(c)
    assert k is not None and k.magic in m10sio.MTAB, 'needs the v4 hook'
    m10sio.clear_overrides(k)
    h = c.shadow(0xc0f06804)
    print('head 6804=%08x tg=%d' % (h, c.peek(0xe664)[0]))
    if h != 0x045702a6:
        print('WARNING: not in zoom x5 (expected 045702a6)')
    r = Ring(k)
    marks = []
    r.run(1.0)
    for key in keys:
        marks.append((r.pull(), key, c.shadow(0xc0f06800), c.shadow(0xc0f06804)))
        c.lua('click("%s") sleep(150)' % key)
        r.run(0.9)
    marks.append((r.pull(), 'end', c.shadow(0xc0f06800), c.shadow(0xc0f06804)))
    m10sio.save(os.path.join(OUT, 'zoompan.sio'), r.last, r.ents)
    print('%d entries, %d lost, tg=%d' % (len(r.ents), r.lost, c.peek(0xe664)[0]))
    c.close()

    # ---- analysis
    W = writes(r.ents)                    # same 17-word layout as m10siodec.load
    F = cmos_frames(W)
    log = open(os.path.join(OUT, 'zoompan.txt'), 'w')
    say = lambda s: (print(s), log.write(s + '\n'))
    tgw = [w for w in W if w[2] == 'TG']
    for i, (idx, key, h0, h1) in enumerate(marks[:-1]):
        nxt = marks[i + 1][0]
        before = [f for f in F if f[0] < idx][-1:]
        after = [f for f in F if idx <= f[0] < nxt]
        if not before or not after:
            say('%-6s (no frames)' % key); continue
        b = before[0][1]
        last = after[-1][1]
        ch = ['%d:%03x->%03x' % (reg, b.get(reg, -1), last.get(reg, -1))
              for reg in range(1, 10) if b.get(reg) != last.get(reg)]
        tg = sorted({(w[3], w[4]) for w in tgw if idx <= w[0] < nxt and w[3] not in (0x805f, 0x8061)})
        say('%-6s head %08x/%08x  CMOS %s  TG %s' % (key, h0, h1, ' '.join(ch) or '-',
            ' '.join('%04x=%x' % t for t in tg) or '-'))
    # every distinct CMOS state seen
    seen = []
    for idx, f in F:
        s = tuple(f.get(reg, -1) for reg in range(1, 10))
        if not seen or seen[-1][1] != s:
            seen.append((idx, s))
    say('distinct CMOS 1-9 states:')
    for idx, s in seen:
        say('  @%d  ' % idx + ' '.join('%d:%03x' % (j + 1, v) for j, v in enumerate(s)))


if __name__ == '__main__':
    main(sys.argv[1:])
