#!/usr/bin/env python3
"""Coherent taller 1x3 window in VGA 25p, posed by Canon itself at commit.

    m10tall2.py H [noTG] [nocache] [keep]      e.g. m10tall2.py 743

Before the M -> VIDEO_STD commit:
  - Extract record of the VGA mode (slot *(0x2cd24+4*4), ROM 0xfc72f2e4)
    copied to RAM with height H (+0x10/+0x18/+0x28) -> head 6804/72c0,
  - ImgSens size cache 0x575b0, mode 37 (VGA 25p) height = H
    -> FldCreat programs the downstream engines (PACK32, prepro, ...),
  - TG table: 800c=0 (1x3) and the Gray line counters 8172/8178/82f8 = H+3,
    82b6 = H+1 (conditional on Canon's VGA values).
After the commit: dump the ~20 height-carrying registers, watch the TG task.
Restore: Extract pointer + cache, disarm, M -> VIDEO_STD (unless 'keep').
Output: captures/live80/tall2_H.txt
"""
import os, sys, time, struct
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10lvgrab, m10auto

OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live80')
TAB, SLOT = 0x2cd24, 4
REC = 0xfc72f2e4
CACHE, CMODE = 0x575b0, 37
FN_MALLOC = 0xfc38d3f1
H0 = 727
HREGS = [(0xc0f06804, 16, 0), (0xc0f072c0, 0, 2), (0xc0f08184, 0, -1), (0xc0f09008, 16, -1),
         (0xc0f10064, 16, -1), (0xc0f35088, 0, 0), (0xc0f373e8, 16, -1), (0xc0f373f4, 16, 0),
         (0xc0f37a70, 16, -1), (0xc0f37ad0, 16, -1), (0xc0f37b8c, 16, -1), (0xc0f42014, 16, -1),
         (0xc0f42918, 16, -1), (0xc0f4292c, 16, 3), (0xc0f42938, 16, -1), (0xc0f42948, 16, 0),
         (0xc0f42950, 16, -1), (0xc0f4296c, 16, -1), (0xc0f42980, 16, 0), (0xc0f42994, 16, -1)]


def gray(n):
    return n ^ (n >> 1)


def hdump(c, say):
    out = []
    for r, sh, d in HREGS:
        v = c.shadow(r)
        out.append('%04x:%d%+d' % (r & 0xfffff, ((v >> sh) & 0xffff) - d, d))
    say('hregs  ' + ' '.join(out))
    say('extra  ' + ' '.join('%08x=%08x' % (r, c.shadow(r)) for r in (0xc0f04a10, 0xc0f08234, 0xc0f09034)))


def main(a):
    h = int(a[0], 0)
    use_tg, use_cache, keep = 'noTG' not in a, 'nocache' not in a, 'keep' in a
    tag = 'H%d' % h + ('' if use_tg else '_noTG') + ('' if use_cache else '_nocache') + ('_dfe' if 'dfe' in a else '') + ('_hiv' if 'hiv' in a else '') + ('_film' if 'film' in a else '') + ('_8a5b' if '8a5b' in a else '') + ('_fulldfe' if 'fulldfe' in a else '') + ''.join('_' + x.replace('=', '-') for x in a if x.startswith('e') and '=' in x) + ''.join('_' + x.replace('=', '-') for x in a if x.startswith('c') and '=' in x)
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, 'tall2_%s.txt' % tag), 'w')
    say = lambda s: (print(s), log.write(s + '\n'), log.flush())
    c = Cam()
    k = m10sio.find(c)
    assert k is not None and k.magic in m10sio.MTAB
    m10sio.clear_overrides(k)
    say('mode M: %s' % m10auto.setmode(c, 'M'))
    assert c.peek(TAB + 4 * SLOT)[0] == REC
    corig = c.peek(CACHE + 36 * CMODE, 4)
    assert corig[1] == H0, corig
    rec = bytearray(c.read(REC, 0x68))
    for off in (0x10, 0x18, 0x28):
        struct.pack_into('<I', rec, off, h)
    buf = c.call(FN_MALLOC, 0x80)
    c.write(buf, bytes(rec))
    assert c.read(buf, 0x68) == bytes(rec)
    tab = [(0x800c, 0, 4)]
    if use_tg:
        tab += [(r, gray(h + 3), gray(730)) for r in (0x8172, 0x8178, 0x82f8)] + \
               [(0x82b6, gray(h + 1), gray(728))]
    if 'dfe' in a:                       # hook v5: DFE line counters (VGA 724 / 671 / 670)
        assert k.magic in (m10sio.M5, m10sio.M6), 'dfe needs hook v5'
        tab += [(0x88c6, h - 3, 724), (0x88ce, h - 3, 724),
                (0x88d7, 671 + h - H0, 671), (0x8a54, 670 + h - H0, 670), (0x8ab5, 670 + h - H0, 670),
                (0x8197, gray(671 + h - H0), gray(671))]
    if 'film' in a:
        # Film recipe: every line-count register Canon sends in FHD 25p
        # (1190 head lines), VGA skip-pattern registers kept (rows consecutive).
        assert k.magic in (m10sio.M5, m10sio.M6) and h == 1190, 'film recipe: H=1190, hook v5'
        tab = [(0x800c, 0, 4),
               (0x8172, 0x6fd, 0x3b7), (0x8178, 0x6fd, 0x3b7), (0x82f8, 0x6fd, 0x3b7),
               (0x82b6, 0x6f4, 0x3b4), (0x8196, 0x4c, 0x7a), (0x8197, 0x66e, 0x3d0),
               (0x88c6, 0x4a4, 0x2d4), (0x88ce, 0x4a4, 0x2d4), (0x88d6, 0x77, 0x53),
               (0x88d7, 0x44b, 0x29f), (0x8a53, 0x77, 0x53), (0x8a54, 0x44a, 0x29e),
               (0x8ab4, 0x77, 0x53), (0x8ab5, 0x44a, 0x29e)]
        if '8a5b' in a:
            tab.append((0x8a5b, 0x613, 0x60b))
        if 'fulldfe' in a:
            # every other DFE commit value that differs Film/VGA (needs hook v6, 64 entries)
            assert k.magic == m10sio.M6, 'fulldfe needs hook v6'
            tab += [(0x88b0, 0x0, 0x1), (0x88d5, 0x903, 0xb03), (0x88da, 0x201, 0x504),
                    (0x88db, 0x706, 0xb0a), (0x88df, 0x0, 0x2), (0x88e0, 0x2, 0x1), (0x88e1, 0x1, 0x0),
                    (0x88e7, 0x9, 0xa), (0x88e8, 0x6, 0x5), (0x8a5b, 0x613, 0x60b),
                    (0x8ab1, 0x1303, 0xb03), (0x8ab6, 0x201, 0x504), (0x8ab7, 0x706, 0xb0a),
                    (0x8ab8, 0xc0b, 0xffff), (0x8ab9, 0x1110, 0xffff), (0x8abc, 0x3, 0x203),
                    (0x8abd, 0x102, 0x1), (0x8abe, 0x3, 0xffff), (0x8abf, 0x102, 0xffff),
                    (0x8ac3, 0x66, 0x5), (0x8ac4, 0x99, 0xa)]
    alive = True
    try:
        c.poke(TAB + 4 * SLOT, buf)
        if use_cache:
            c.poke(CACHE + 36 * CMODE + 4, h)
            c.poke(CACHE + 36 * CMODE + 12, h)
        m10sio.set_tg_table(k, tab)
        for x in a:                      # CMOS rewrites, e.g. c8=0x400 (Film value)
            if x.startswith('c') and '=' in x and x[1:x.index('=')].isdigit():
                r, v = int(x[1:x.index('=')]), int(x[x.index('=') + 1:], 0)
                k.poke(k.b + k.cmos + 4 * r, 0x10000 | (v & 0xfff))
                k.set_h(20, 1)
        say('armed  ' + m10sio.over_state(k))
        if 'hiv' in a:
            # HivShd read DMA (ch 0x1b, c0f04a10) must be 2*H bytes per row:
            # size = ROM[0xfc659b34][idx] - 2*off, idx at 0xfbac+0x2c, off at 0xfc3c.
            # Use the Film entry (2380) and off = 1190 - H, posed right after the commit.
            # engine registers left at their VGA value by the ISP setup (e.g. pre-
            # processing window c0f09034 = 902 x H-2): forced via EngDrvOut as soon as
            # Canon writes them, for 1.5 s after the switch starts.
            eng = []
            for x in a:
                if x.startswith('e') and '=' in x:
                    r, v = x[1:].split('=')
                    eng.append((int(r, 16) | 0xc0f00000, int(v, 0)))
            c.chdk(7, [0], b'capmode=require"capmode" capmode.set("VIDEO_STD")\0')
            t0 = time.time()
            hiv_done, nfix, tfix = False, 0, []
            while time.time() - t0 < (1.5 if eng else 3):
                if not hiv_done and c.peek(0xfbac + 0x20)[0] == CMODE and c.peek(0xfbac + 0x2c)[0] == 2:
                    c.poke(0xfc3c, 1190 - h)
                    c.poke(0xfbac + 0x2c, 1)
                    hiv_done = True
                    thiv = time.time()
                    if not eng:
                        break
                if hiv_done and c.shadow(0xc0f06804) >> 16 == h:
                    for r, v in eng:
                        if c.shadow(r) != v:
                            c.call(0xfc38d28b, r, v)
                            nfix += 1
                            tfix.append(int((time.time() - t0) * 1000))
            if eng:
                say('eng    %d forced writes at ms %s; now %s' % (nfix, tfix[:12],
                    ' '.join('%05x=%08x' % (r & 0xfffff, c.shadow(r)) for r, v in eng)))
                t0 = thiv
            say('hiv    poked after %.0f ms: idx=%d off=%d 4a10=%08x' % (
                (time.time() - t0) * 1000, c.peek(0xfbac + 0x2c)[0], c.peek(0xfc3c)[0], c.shadow(0xc0f04a10)))
            time.sleep(1.5)
        else:
            say('mode VIDEO_STD: %s' % m10auto.setmode(c, 'VIDEO_STD', 1500))
        s = m10auto.state(c, k)
        say('commit ' + m10auto.fmt(s))
        hdump(c, say)
        if 'shadow' in a:
            import m10shadowdump
            t1 = time.time()
            open(os.path.join(OUT, 'tall2_%s.shadow' % tag), 'wb').write(m10shadowdump.dump(c))
            say('shadow dumped in %.1f s, tg=%x' % (time.time() - t1, c.peek(0xe664)[0]))
        t0 = time.time()
        while time.time() - t0 < 4:
            if c.peek(0xe664)[0] == 0xffffffff:
                break
            time.sleep(0.2)
        s = m10auto.state(c, k)
        say('t+4s   ' + m10auto.fmt(s))
        if s['tg'] == 0xffffffff:
            alive = False
            say('TG task in error (camera will shut down)')
            idx, ents = m10sio.read_ring(k)
            m10sio.save(os.path.join(OUT, 'tall2_%s.sio' % tag), idx, ents)
        else:
            png = os.path.join(OUT, 'tall2_%s.png' % tag)
            m10lvgrab.save_png(m10lvgrab.to_rgb(*m10lvgrab.grab(c)), png)
            say('grab   ' + png)
    finally:
        if alive and not keep:
            say('mode M (armed): %s' % m10auto.setmode(c, 'M'))
        if not keep:
            c.poke(TAB + 4 * SLOT, REC)
            c.poke(CACHE + 36 * CMODE, *corig)
            m10sio.clear_overrides(k)
            say('restored ' + m10sio.over_state(k))
    if alive and not keep:
        say('mode VIDEO_STD: %s' % m10auto.setmode(c, 'VIDEO_STD', 1500))
        say('clean  ' + m10auto.fmt(m10auto.state(c, k)))
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
