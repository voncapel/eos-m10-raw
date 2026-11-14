#!/usr/bin/env python3
"""live116: slow the x5 magnifier from 30 to ~25 fps through Canon's own commit.

TgPixelRes is a RAM pointer table 0x2cdc0[DrvType] -> 0xd0-byte ROM records.
Zoom = DrvType 46 (ROM 0xfc73045c): line 733 clocks (+0..+8 = 732), frame
1456 lines (+0x0c/+0x10), +0x80 = frame - 57 (-> head reg 7050), +0xc8 = period us.
We copy the record to malloc'd RAM, lengthen the frame, and point 0x2cdc0[46] at
the copy.  Nothing is written to any engine register: Canon programs 6014, 7050,
TG 8173... itself when the USER enters the magnifier by touch (this tool never
changes the mode).  RAM writes only.

    m10zfps.py arm [LINES] [cache] [fld]  copy + patch + redirect (default LINES 1747 = 40.02 ms)
                                          cache: also ImgSens cache mode 41 period (+0x1c)
                                          fld:   also FldSpec[46] period (copy + redirect)
    m10zfps.py state                      pointer, record fields, cache, head timers (shadow), tg
    m10zfps.py restore                    ROM pointers back, cache back (always safe)
    m10zfps.py watch [S]                  passive: 6014/6804/tg every 0.5 s (shadow only)

State of the arm (copy address, originals) is kept in /tmp/m10zfps.json.
"""
import os, sys, time, struct, json
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam

TAB = 0x2cdc0
FLD = TAB + 0xe4
DRV = 46
ROMREC = 0xfc73045c
ROMFLD = 0xfc7308e8
CACHE41 = 0x575b0 + 36 * 41
FN_MALLOC = 0xfc38d3f1
RECSZ = 0xd0
CLK = 32e6
ST = '/tmp/m10zfps.json'
LOG = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live116')


def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def u32(b, o): return struct.unpack_from('<I', b, o)[0]


def show(c, say):
    p = c.peek(TAB + 4 * DRV)[0]; f = c.peek(FLD + 4 * DRV)[0]
    r = c.read(p, RECSZ)
    line = u16(r, 0) + 1
    say('rec[46] %08x%s line %d fl %d/%d +80 %d per %d us  (frame %.2f ms)' % (
        p, ' (ROM)' if p == ROMREC else ' (COPY)', line, u16(r, 0xc), u16(r, 0x10), u16(r, 0x80), u32(r, 0xc8),
        u16(r, 0xc) * line / CLK * 1e3))
    say('fld[46] %08x%s per %d' % (f, ' (ROM)' if f == ROMFLD else ' (COPY)', c.peek(f)[0]))
    say('cache41 %s' % (struct.unpack('<9I', c.read(CACHE41, 36)),))
    say('tg %d 6804 %08x 6008 %08x 6014 %08x 7050 %08x' % (c.peek(0xe664)[0], c.shadow(0xc0f06804), c.shadow(0xc0f06008),
                                                          c.shadow(0xc0f06014), c.shadow(0xc0f07050)))


def main(a):
    cmd = a[0] if a else 'state'
    os.makedirs(LOG, exist_ok=True)
    log = open(os.path.join(LOG, 'zfps.txt'), 'a')
    def say(s):
        s = time.strftime('%H:%M:%S ') + s; print(s); log.write(s + '\n'); log.flush()
    c = Cam(timeout=20000)
    say('== ' + ' '.join([cmd] + a[1:]))
    if cmd == 'arm':
        lines = int(a[1]) if len(a) > 1 and a[1].isdigit() else 1747
        assert 1456 <= lines <= 2100, 'frame length out of the sane range'
        if c.shadow(0xc0f06804) == 0x045702a6:
            say('in the magnifier now: leave it first (the record is read at the commit)'); c.close(); return
        cur = c.peek(TAB + 4 * DRV)[0]
        assert cur == ROMREC, 'record 46 already redirected (%08x): restore first' % cur
        rom = c.read(ROMREC, RECSZ)
        assert u16(rom, 0) == 732 and u16(rom, 0xc) == 1456 and u16(rom, 0x80) == 1399 and u32(rom, 0xc8) == 33306, 'unexpected ROM record'
        line = u16(rom, 0) + 1
        per = int(round(lines * line / CLK * 1e6))
        rec = bytearray(rom)
        struct.pack_into('<H', rec, 0x0c, lines); struct.pack_into('<H', rec, 0x10, lines)
        struct.pack_into('<H', rec, 0x80, lines - 57)
        struct.pack_into('<I', rec, 0xc8, per)
        buf = c.call(FN_MALLOC, RECSZ + 0x60 + 64)
        assert buf, 'malloc failed'
        cp = (buf + 31) & ~31
        c.write(cp, bytes(rec))
        assert c.read(cp, RECSZ) == bytes(rec)
        st = {'buf': buf, 'rec': cp, 'lines': lines, 'per': per}
        if 'fld' in a:
            fr = bytearray(c.read(ROMFLD, 0x60))
            assert u32(fr, 0) == 33306 and u32(fr, 0x14) == 31979
            struct.pack_into('<I', fr, 0, per)
            struct.pack_into('<I', fr, 0x14, per - (33306 - 31979))   # Fable: max exposure = period - 1327 us (2nd sub-record untouched)
            fcp = cp + RECSZ
            c.write(fcp, bytes(fr)); st['fld'] = fcp
        if 'cache' in a:
            st['cache'] = c.peek(CACHE41 + 0x1c)[0]
            assert st['cache'] == 33306
        json.dump(st, open(ST, 'w'))
        c.poke(TAB + 4 * DRV, cp)
        if 'fld' in a: c.poke(FLD + 4 * DRV, st['fld'])
        if 'cache' in a: c.poke(CACHE41 + 0x1c, per)
        say('armed: frame %d lines x %d clk = %d us (%.2f fps), copy %08x%s%s' % (
            lines, line, per, 1e6 / per, cp, ' +fld' if 'fld' in a else '', ' +cache' if 'cache' in a else ''))
        show(c, say)
    elif cmd == 'restore':
        c.poke(TAB + 4 * DRV, ROMREC); c.poke(FLD + 4 * DRV, ROMFLD)
        if c.peek(CACHE41 + 0x1c)[0] != 33306: c.poke(CACHE41 + 0x1c, 33306)
        say('restored ROM pointers and cache')
        show(c, say)
    elif cmd == 'watch':
        t1 = time.time() + (float(a[1]) if len(a) > 1 else 10)
        while time.time() < t1:
            say('tg %d 6804 %08x 6014 %08x 7050 %08x' % (c.peek(0xe664)[0], c.shadow(0xc0f06804), c.shadow(0xc0f06014), c.shadow(0xc0f07050)))
            time.sleep(0.5)
    else:
        show(c, say)
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
