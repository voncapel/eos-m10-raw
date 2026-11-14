#!/usr/bin/env python3
"""Redirect Canon's "Extract" head-window record and replay a mode commit.

Extract.c (0xfc157082) programs the head window 0xc0f06800/04 from the record
returned by 0xfc1bf7dc(idx) = *(0x2cd24 + 4*idx)  (RAM pointer table, ROM records
0x68 bytes).  Film uses idx 7 (ROM 0xfc72f34c): +0x24 = 476 (x0), +0x28 = 1190
(head lines), +0x2c = 0x18, +0x30 = 1  ->  6800 = 0x00010018, 6804 = 0x04a601dc.
Getters used by ImgSens.c: +0x0c/+0x10 (1808 x 1190) and +0x14/+0x18 (same).

    m10extract.py FROM TO [LINES] [t0x800c=0]
        LINES omitted -> unmodified copy (control: proves the redirection)

Copies record 7 to malloc'd RAM, patches +0x10/+0x18/+0x28 = LINES, points
*(0x2cd24+28) at the copy, arms the TG override if given, switches FROM -> TO,
records state + LV grab, then ALWAYS restores the ROM pointer and re-commits
FROM -> TO cleanly.  Log -> captures/live69/.
"""
import os, sys, time, struct
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10lvgrab, m10auto

TAB = 0x2cd24
IDX_CUR = 0xe460 + 0xc
FN_MALLOC = 0xfc38d3f1
RECSZ = 0x68
CACHE = 0x575b0          # ImgSens per-mode size cache, 36 B: +0 w, +4 h, +8 w2, +0xc h2 (filled at boot)
CACHE_MODES = (34, 36)   # ImgSens modes whose Extract record is 7 (0xfc156fa4)
OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live69')


def main(a):
    frm, to = a[0], a[1]
    lines, tg = None, None
    for x in a[2:]:
        if x.startswith('t'):
            r, v = x[1:].split('=')
            tg = (int(r, 0), int(v, 0))
        else:
            lines = int(x, 0)
    tag = '%s_%s_%s%s' % (frm, to, 'ctl' if lines is None else 'L%d' % lines,
                          '_t%04x-%x' % tg if tg else '')
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, 'ext_%s.txt' % tag), 'w')
    say = lambda s: (print(s), log.write(s + '\n'), log.flush())
    c = Cam()
    k = m10sio.find(c)
    assert k is not None and k.magic == m10sio.M3, "needs the v3 hook"
    m10sio.clear_overrides(k)
    say('mode %s: %s' % (frm, m10auto.setmode(c, frm)))
    idx = struct.unpack('<I', c.read(IDX_CUR, 4))[0]
    say('extract idx (current) = %d' % idx)
    slot = TAB + 4 * 7
    orig = struct.unpack('<I', c.read(slot, 4))[0]
    assert orig == 0xfc72f34c, hex(orig)
    rec = bytearray(c.read(orig, RECSZ))
    w = list(struct.unpack('<26I', rec))
    say('rec7   ' + ' '.join('%x' % x for x in w))
    if lines is not None:
        for off in (0x10, 0x18, 0x28):
            struct.pack_into('<I', rec, off, lines)
    buf = c.call(FN_MALLOC, 0x80)
    assert buf, 'malloc failed'
    c.write(buf, bytes(rec))
    assert c.read(buf, RECSZ) == bytes(rec)
    say('copy @%08x  ' % buf + ' '.join('%x' % x for x in struct.unpack('<26I', rec)))
    cache_orig = {m: c.peek(CACHE + 36 * m, 4) for m in CACHE_MODES}
    say('cache  ' + ' '.join('%d:%s' % (m, '/'.join('%x' % x for x in v)) for m, v in cache_orig.items()))
    try:
        c.poke(slot, buf)
        if lines is not None:
            for m in CACHE_MODES:
                c.poke(CACHE + 36 * m + 4, lines)
                c.poke(CACHE + 36 * m + 12, lines)
        if tg:
            k.set_h(28, 0); k.set_h(32, tg[0]); k.set_h(36, tg[1]); k.set_h(44, 0); k.set_h(28, 1)
        say('armed  ptr=%08x %s' % (struct.unpack('<I', c.read(slot, 4))[0], m10sio.over_state(k)))
        say('mode %s: %s' % (to, m10auto.setmode(c, to, 2000)))
        for i in range(4):
            s = m10auto.state(c, k)
            say('t+%ds   ' % (2 * i) + m10auto.fmt(s) + ' 72c0=%08x' % c.shadow(0xc0f072c0))
            if s['tg'] == 0xffffffff:
                say('TG task in error -> abort')
                break
            if i == 0:
                png = os.path.join(OUT, 'ext_%s.png' % tag)
                m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)), png)
                say('grab   ' + png)
            time.sleep(2)
    finally:
        try:
            m10sio.clear_overrides(k)
            c.poke(slot, orig)
            for m, v in cache_orig.items():
                c.poke(CACHE + 36 * m, *v)
            say('restore ptr=%08x %s' % (struct.unpack('<I', c.read(slot, 4))[0], m10sio.over_state(k)))
        except Exception as e:
            say('restore FAILED: %r' % e)
    say('mode %s: %s' % (frm, m10auto.setmode(c, frm)))
    say('mode %s: %s' % (to, m10auto.setmode(c, to, 2000)))
    say('clean  ' + m10auto.fmt(m10auto.state(c, k)))
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
