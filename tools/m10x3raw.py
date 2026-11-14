#!/usr/bin/env python3
"""RAW capture probe in 1x3 (or plain Film), fully scripted over USB.

    m10x3raw.py [x3|film] [NPASS] [LINES] [BPP]   default: x3 1 256 14

1. M -> VIDEO_STD commit, with TG 0x800c = 0 (only if Canon sends 2) for x3,
2. disarm the hook (800c is only written at commit: the 1x3 state persists),
3. write A/M10X3.CFG and run the m10cine.flt module through the CHDK core's
   module_run() (found in the running core: 0x3e8c70, Thumb) -> v25 lv_x3():
   NPASS isolated CH12 passes of LINES lines + 3 s TG watch,
4. download A/LVX3.BIN and A/M10CINE.LOG into captures/live71/, report TG state,
5. restore a clean Film (M -> VIDEO_STD) if the camera is still alive.
"""
import os, sys, time, struct
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
import m10sio, m10auto

MODULE_RUN = 0x3e8c71        # CHDK core (1.7.0 on card) module_run(char *name), Thumb
FN_MALLOC = 0xfc38d3f1
OUT = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live71')
# live108: Film mode used for the commits.  VIDEO_STD = Canon's auto-exposure Film; VIDEO_M keeps the user's
# manual shutter / ISO (FILMMODE=VIDEO_M).  Both must give the same 1190-line head (checked by the caller).
FILMMODE = os.environ.get('FILMMODE', 'VIDEO_STD')



def cfg_tail():
    """live109: optional CFG fields 21+ (module v97-v130), emitted up to the last one set."""
    E = os.environ
    fields = [('UNPK', '0'), ('JP', 'a0:0'), ('WR2', '9'), ('EWIN', '0 0'), ('ERD', '35'), ('EH', '0'),
              ('W2', '0 0'), ('EP', '0:0'), ('NS', '1 0 0'), ('SW', '0 0 256'), ('EMODE', '1'), ('ROWM', '1'), ('PRM', '0 0'), ('EW', '0'), ('RDB', '0'), ('EWS', '0'), ('KW', '8000'), ('EOFF', '0'), ('SWE', '0'), ('HBN', '6'), ('CHASE', '0'), ('U371', '0'), ('EBITS', '0'), ('RDF', '0'), ('HER', '0'), ('EXM', '16'), ('PBL', '0'), ('SKICK', '0'), ('TSK', '0')]
    last = max([i for i, (k, d) in enumerate(fields) if E.get(k)] or [-1])
    return ''.join(' ' + (E.get(k) or d) for k, d in fields[:last + 1])

def main(a):
    mode = a[0] if a else 'x3'
    npass = int(a[1]) if len(a) > 1 else 1
    lines = int(a[2]) if len(a) > 2 else 256
    bpp = int(a[3]) if len(a) > 3 else 14
    wms = int(a[4]) if len(a) > 4 else 0
    gap = int(a[5]) if len(a) > 5 else 500
    fl = int(a[6], 0) if len(a) > 6 else 0     # v32 flags: 1 no SD I/O, 2 post-watch, 4 no image, 8 fast idle
    chf = int(a[7], 0) if len(a) > 7 else 0    # v68: CH12 EDMAC flags (0 = 0x40000000)
    xo = int(a[8], 0) if len(a) > 8 else 0     # v72: 1 sleepy 8830 window, 2 chain, 4 pack 4, 0x10 persistent PACK32
    lo = int(a[9]) if len(a) > 9 else 2000     # v72: window start (us after 8830)
    hi = int(a[10]) if len(a) > 10 else 7000   # v72: window end
    pxc = int(a[11]) if len(a) > 11 else 6     # v73: px_cycle frames per sem #6 hold (0 = whole run)
    xnd = int(a[12]) if len(a) > 12 else 0     # v73: x_need min lines for short frame
    xst = int(a[13]) if len(a) > 13 else 0     # v79: CH12 start us after 8830 (xo 0x10000000)
    wch = int(a[14]) if len(a) > 14 else 12    # v81: write EDMAC channel (2, 5, 11, 12, 14, 18, 19)
    hem = int(a[15]) if len(a) > 15 else 0     # v85: 1 = keep going on trapped head errors (xo 0x80000000)
    xdc = int(a[16]) if len(a) > 16 else 99    # v86: Canon write channel cut from the crossbar during our pass
    tag = '%s_%dx%d_%db%s' % (mode, npass, lines, bpp, ('_w%d' % wms if wms else '') + ('_g%d' % gap if gap != 500 else '') + ('_f%x' % fl if fl else '') + ('_e%x' % chf if chf else '') + ('_o%x_%d_%d' % (xo, lo, hi) if xo else '') + ('_px%d' % pxc if pxc != 6 else '') + ('_nd%d' % xnd if xnd else '') + ('_st%d' % xst if xst else '') + ('_ch%d' % wch if wch != 12 else '') + ('_he%d' % hem if hem else '') + ('_dc%d' % xdc if xdc != 99 else ''))
    os.makedirs(OUT, exist_ok=True)
    log = open(os.path.join(OUT, 'x3raw_%s.txt' % tag), 'w')
    say = lambda s: (print(s), log.write(s + '\n'), log.flush())
    c = Cam(timeout=int(os.environ.get("USBTMO", "60000")))
    k = m10sio.find(c)
    assert k is not None and k.magic in m10sio.MTAB, 'needs the v4 hook'
    m10sio.clear_overrides(k)
    # sanity: module_run prologue in the running core
    assert c.read(MODULE_RUN - 1, 4) == bytes.fromhex('2de9f041'), 'module_run not found'
    zoom = mode == 'zoom'                       # live115: x5 magnifier (entered by touch): never change the mode over USB
    if zoom:
        h = c.shadow(0xc0f06804)
        if h != 0x045702a6:
            say('not in the x5 magnifier (6804=%08x), abort' % h); c.close(); return
        say('zoom x5 (no mode change)'); hits = 1
    elif os.environ.get('NOMODE'):              # live100: capture in the current state (no M -> Film commit)
        say('nomode (keep current 1x3 state)')
        hits = 1
    else:
        say('mode M: %s' % m10auto.setmode(c, 'M'))
        if mode == 'x3':
            m10sio.set_tg_table(k, [(0x800c, 0)])   # only written at commit
        say('armed  ' + m10sio.over_state(k))
        say('mode %s: %s' % (FILMMODE, m10auto.setmode(c, FILMMODE, 2000)))
        hits = k.h(40)
    m10sio.clear_overrides(k)
    s = m10auto.state(c, k)
    say('state  ' + m10auto.fmt(s) + ' 800c_hits=%d' % hits)
    if s['tg'] != 3 or (mode == 'x3' and hits == 0):
        say('unexpected state, abort')
        c.close()
        return
    cm = [tuple(int(v, 0) for v in x.split('=')) for x in os.environ.get('CMOS', '').split(',') if x]
    if cm:                                      # steady-state CMOS rewrites (e.g. CMOS=7=0x804)
        for r, v in cm:
            k.poke(k.b + k.cmos + 4 * r, 0x10000 | (v & 0xfff))
        k.set_h(20, 1)
        time.sleep(0.5)
        s = m10auto.state(c, k)
        say('cmos   ' + m10sio.over_state(k) + ' tg=%d' % s['tg'])
        if s['tg'] != 3:
            m10sio.clear_overrides(k)
            say('TG not running after CMOS override, abort')
            c.close()
            return
        tag += '_c' + '_'.join('%d-%03x' % x for x in cm)
    skipy = int(os.environ.get('SKIPY', '2' if mode == 'film' else '0'))   # v90: RAWC skipping_y (Film 3x3 = 2)
    skipn = int(os.environ.get('SKIPN', '0'))   # v91: REC chained, one free frame for Canon every N frames
    enc = int(os.environ.get('ENC', '0'))       # v92: lossless encoder test on pass 0 (12 / 14)
    open('/tmp/M10X3.CFG', 'w').write('%d %d %d %d %d %d %x %x %d %d %d %d %d %d %d %d %d %d %d %d%s\n' % (npass, lines, bpp, wms, gap, fl, chf, xo, lo, hi, pxc, xnd, xst, wch, hem, xdc, skipy, skipn, enc, int(os.environ.get('CSH', '4')), cfg_tail()))
    c.upload('/tmp/M10X3.CFG', 'A/M10X3.CFG')
    if zoom:                                    # marker: lets the module run lv_x3 in the magnifier (v156)
        open('/tmp/M10Z.CFG', 'w').write('1\n'); c.upload('/tmp/M10Z.CFG', 'A/M10Z.CFG')
    else:
        c.lua('os.remove("A/M10Z.CFG")')
    movoff = int(os.environ.get('MOVOFF', '0'), 16)   # live109: clear LvMovOptimus flag bits ([0x35d7c]; 0x8 = CH24 YUV 1080p) during the run
    mov0 = None
    if movoff:
        mov0 = c.peek(0x35d7c)[0]
        c.poke(0x35d7c, mov0 & ~movoff)
        say('movoff %08x -> %08x' % (mov0, c.peek(0x35d7c)[0]))
    # live113c: POKE=ADDR=VAL[,ADDR=VAL] RAM words written after the Film commit (which resets Canon
    # state such as the WBSmth threshold 0x133c88) and restored after the run.  RAM only, never MMIO.
    pokes = []
    for x in os.environ.get('POKE', '').split(','):
        if x:
            a, v = (int(s, 0) for s in x.split('='))
            assert (a >> 28) not in (0xc, 0xd) and a < 0x40000000, 'POKE is for RAM only'
            pokes.append((a, c.peek(a)[0]))
            c.poke(a, v)
            say('poke %08x %08x -> %08x' % (a, pokes[-1][1], c.peek(a)[0]))
    name = c.call(FN_MALLOC, 32)
    c.write(name, b'm10cine.flt\0')
    say('module_run ...')
    t0 = time.time()
    try:
        r = c.call(MODULE_RUN, name)
        say('module_run -> %d (%.1f s)' % (r, time.time() - t0))
    except Exception as e:
        say('module_run call failed after %.1f s: %r' % (time.time() - t0, e))
    time.sleep(0.1)   # v89m: re-commit fast if the TG froze
    if mov0 is not None:
        try:
            c.poke(0x35d7c, mov0); say('movoff restored %08x' % c.peek(0x35d7c)[0])
        except Exception as e:
            say('movoff restore failed: %r' % (e,))
    for a, v in pokes:
        try:
            say('poke %08x after run = %08x, restoring %08x' % (a, c.peek(a)[0], v)); c.poke(a, v)
        except Exception as e:
            say('poke restore failed: %r' % (e,))
    try:
        if cm:
            m10sio.clear_overrides(k)
        if os.environ.get('TAG'):
            tag = os.environ['TAG']
        say('tg after = %d  6804=%08x' % (c.peek(0xe664)[0], c.shadow(0xc0f06804)))
        if zoom:
            c.lua('os.remove("A/M10Z.CFG")'); say('zoom: no re-commit')
        elif os.environ.get('NOCLEAN'):         # live100: keep the post-run state (no M -> VIDEO_STD)
            say('noclean ' + m10sio.over_state(k))
        else:                                   # live100 (v89k): re-commit BEFORE the downloads (WBInteg may be starving)
            say('mode M: %s' % m10auto.setmode(c, 'M'))
            say('mode %s: %s' % (FILMMODE, m10auto.setmode(c, FILMMODE, 2000)))
            say('clean  ' + m10auto.fmt(m10auto.state(c, k)))
        files = ('M10CINE.LOG', 'M10X3T.BIN', 'LVX3S.BIN', 'LVX3H.BIN', 'M10HESH.BIN', 'M10TLF.BIN', 'M10HE.BIN', 'M10TSK.BIN', 'M10TSN.BIN', 'M10CAP.BIN', 'M10X3.MLV' if fl & 0x1000000 else 'M10X3.RAW') if fl & 0x100 else \
            (('M10CINE.LOG', 'LVX3E.BIN') if fl & 0x40000000 else
             ('LVX3.BIN', 'M10CINE.LOG', 'LVX3S.BIN') + (('LVX3W.BIN',) if wms or fl & 2 else ()) + (('M10LL.BIN',) if os.environ.get('ENC') else ()))
        if os.environ.get('NORAW'):
            files = tuple(f for f in files if not f.endswith(('.RAW', '.MLV')))
        for f in files:
            dst = os.path.join(OUT, '%s_%s' % (tag, f))
            try:
                c.download('A/' + f, dst)
                say('got    ' + dst)
            except Exception as e:
                say('no     %s (%s)' % (f, e))
        if fl & 0x1000000 and not os.environ.get('NORAW'):   # v89n: MLV chunks .M00, .M01 ... (< 2 GiB each)
            for n in range(16):
                dst = os.path.join(OUT, '%s_M10X3.M%02d' % (tag, n))
                try:
                    c.download('A/M10X3.M%02d' % n, dst)
                    say('got    ' + dst)
                except Exception:
                    break
    except Exception as e:
        say('post-run failed (camera off?): %r' % e)
    c.close()


if __name__ == '__main__':
    main(sys.argv[1:])
