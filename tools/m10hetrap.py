#!/usr/bin/env python3
"""live97: trap the head-error IRQ (0x80) callback so ImgSens never sees it.

Head.c _headErrorInterrupt (0xfc17b61c) reads c0f070dc into [0xfa84], clears
the cause masks, then jumps to the callback pointer [0xfa68+0x18] = [0xfa80]
(ImgSens 0xfc1ee9a9 -> event 0x4000000 -> fatal 0x100001 if bit 5/6).
We replace [0xfa80] by a Thumb stub that only counts and records the status.

    m10hetrap.py install      stub in malloc'ed RAM, swap [0xfa80]
    m10hetrap.py state        count / last / OR of statuses, current pointer
    m10hetrap.py remove       restore Canon's callback

Needs the SIO hook (poke32 = atomic 32-bit store, m10sio.py install4).
The stub address is kept in the hook-free word 0x... no: printed and also
found again by scanning: [0xfa80] itself points to it while installed.
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio

CBR = 0xfa80                 # [0xfa68 + 0x18]
CANON_CBR = 0xfc1ee9a9
FN_MALLOC = 0xfc38d3f1
STUB = bytes.fromhex('00000000' * 4 +
                     'aff21401 0a68 0132 0a60 4ff68423 1b68 4b60 8a68 1a43 8a60 7047 00bf'.replace(' ', ''))

# live110: STUB2 = same counters + per-error ring of 16 x 32 bytes at header + 0x80:
#   usec timer c0242014, status, CH12 addr c0f26508, encoder RD1 addr c0f26c08, CH22 c0f58008, read ch47 c0f58908
STUB2 = bytes.fromhex('00000000000000000000000000000000aff214010a6801320a604ff684231b684b60886818438860013a02f00f0252010a448032084800681060536007480068906007480068d06006480068106106480068506170470000142024c00865f2c0086cf2c00880f5c00889f5c0aff30080000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000')


def info(c):
    p = c.peek(CBR)[0]
    if p == CANON_CBR:
        return p, None
    b = (p & ~1) - 0x10
    return p, c.peek(b, 4)


def main(a):
    op = a[0] if a else 'state'
    c = Cam()
    k = m10sio.find(c)
    assert k is not None, 'needs the SIO hook (m10sio.py install4)'
    p, d = info(c)
    if op in ('install', 'install2'):
        stub = STUB2 if op == 'install2' or os.environ.get('HESTUB2') else STUB
        if d is not None:
            print('already installed at %08x' % p)
        elif p != CANON_CBR:
            print('unexpected [0xfa80] = %08x, abort' % p)
        else:
            mem = c.call(FN_MALLOC, len(stub) + 16)
            b = (mem + 7) & ~7
            c.write(b, stub)
            c.call(m10sio.FN_DCLEAN, b, len(stub))
            c.call(m10sio.FN_IINVAL, b, len(stub))
            assert c.read(b, len(stub), buffered=False) == stub
            k.poke(CBR, (b + 0x10) | 1)
            print('installed stub %08x, [0xfa80] %08x -> %08x' % (b, CANON_CBR, c.peek(CBR)[0]))
    elif op == 'dump':
        if d is None: print('no stub')
        else:
            b = (p & ~1) - 0x10
            e = c.peek(b + 0x80, 16 * 8)
            n = d[0]
            for i in range(max(0, n - 16), n):
                j = i % 16; r = e[8 * j:8 * j + 6]
                print('err %d us=%05x st=%x ch12=%08x rd1=%08x ch22=%08x ch47=%08x' % ((i, r[0] & 0xfffff) + tuple(r[1:6])))
    elif op == 'remove':
        if d is None:
            print('not installed ([0xfa80] = %08x)' % p)
        else:
            k.poke(CBR, CANON_CBR)
            print('restored [0xfa80] = %08x; stub counts: n=%d last=%x or=%x' % (c.peek(CBR)[0], d[0], d[1], d[2]))
    p, d = info(c)
    tg = struct.unpack('<i', c.read(0xe664, 4))[0]
    print('[0xfa80]=%08x tg=%d headerr=[0xfa84]=%x' % (p, tg, c.peek(0xfa84)[0]),
          ('stub n=%d last=%x or=%x' % tuple(d[:3])) if d else '(Canon callback)')
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
