#!/usr/bin/env python3
"""Passive trace of a sensor mode commit: engine shadow + SIO ring.

    m10commit.py FROM TO [OUT]        e.g. m10commit.py M VIDEO_STD

Starts in mode FROM, launches a Lua mode switch to TO *asynchronously*
(script keeps running on the camera), and meanwhile polls in a tight USB
loop: the engine shadow of the head block (0xc0f06000-60ff, 6800-68ff,
7000-72ff, via the RAM shadow *(0x28dbc)+(reg&0x7ffff)) and the SIO hook
ring index.  Every change of a shadow word is logged with the host time and
the SIO ring index at that moment, so each head write can be placed between
two serial frames (whose return addresses identify the ROM caller).
Writes nothing to the camera except the Lua mode switch.
Output: captures/live68/commit_FROM_TO.{json,sio}
"""
import json, os, struct, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10auto

OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live68')
BLOCKS = ((0x6000, 0x100), (0x6800, 0x100), (0x7000, 0x300))


def main(a):
    frm, to = a[0], a[1]
    os.makedirs(OUT, exist_ok=True)
    tag = '%s_%s' % (frm, to)
    c = Cam()
    k = m10sio.find(c)
    assert k is not None and k.magic == m10sio.M3
    m10sio.clear_overrides(k)
    print('mode', frm, m10auto.setmode(c, frm))
    sb = c.peek(0x28dbc)[0]

    def snap():
        d = {}
        for base, n in BLOCKS:
            raw = c.read(sb + base, n)
            for i in range(0, n, 4):
                d[0xc0f00000 + base + i] = struct.unpack_from('<I', raw, i)[0]
        return d

    cur = snap()
    idx0 = k.h(4)
    events = []
    # asynchronous Lua: start the switch, do not wait for completion
    c.chdk(7, [0], ('capmode=require"capmode" capmode.set("%s")' % to).encode() + b'\0')
    t0 = time.time()
    t_head = None
    while time.time() - t0 < 6.0:
        idx = k.h(4)
        new = snap()
        for r, v in new.items():
            if v != cur[r] and r != 0xc0f06004:
                events.append((round(time.time() - t0, 4), idx, r, cur[r], v))
                if r == 0xc0f06804 and t_head is None:
                    t_head = time.time()
        cur = new
        if t_head and time.time() - t_head > 0.15:
            break               # pull the ring before it wraps
    print('%d shadow changes' % len(events))
    for e in events:
        print('t=%7.4f sio=%7d %08x: %08x -> %08x' % e)
    # pull the SIO ring covering the window
    idx1 = k.h(4)
    nm1 = k.h(16)
    n = min(idx1 - idx0, nm1 + 1)
    ents = []
    for j in range(idx1 - n, idx1, 256):
        cnt = min(256, idx1 - j)
        raw = c.read(k.b + k.ent + (j & nm1) * 64, cnt * 64) if (j & nm1) + cnt <= nm1 + 1 else \
            c.read(k.b + k.ent + (j & nm1) * 64, (nm1 + 1 - (j & nm1)) * 64) + \
            c.read(k.b + k.ent, (cnt - (nm1 + 1 - (j & nm1))) * 64)
        for q in range(cnt):
            ents.append((j + q,) + struct.unpack_from('<16I', raw, q * 64))
    m10sio.save(os.path.join(OUT, 'commit_%s.sio' % tag), idx1, ents)
    json.dump({'from': frm, 'to': to, 'idx0': idx0, 'idx1': idx1, 'lost': (idx1 - idx0) - n,
               'events': [[e[0], e[1], '%08x' % e[2], '%08x' % e[3], '%08x' % e[4]] for e in events]},
              open(os.path.join(OUT, 'commit_%s.json' % tag), 'w'), indent=1)
    print('sio %d..%d (%d kept, %d lost)' % (idx0, idx1, n, (idx1 - idx0) - n))
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
