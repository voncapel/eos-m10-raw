#!/usr/bin/env python3
"""SIO trace / override hook for the EOS M10 (fw 1.10d), installed over USB PTP.

SioDrv.c sends every serial frame (CMOS sensor = SIO channel 6, TG/DFE/CDS =
channel 4, ...) through the RAM function pointer *(0x9b50) (= 0x121, low-RAM
copy of ROM 0xfc130b02).  We replace it with a small trampoline that logs
each frame in a ring buffer, can rewrite frames, then jumps to the original.

Blob versions (magic in header): v1 'SIOH' log only, v2 'SIO2' + CMOS table,
v3 'SIO3' + CMOS table + one TG (TgDrvWAKA addr/data) override, v4 'SIO4' +
16-entry TG table with optional match on the original value.  New installs use v4.

    m10sio.py install [NENT] [MASK]   allocate + install v3 (default 2048, 0x50)
    m10sio.py swap [NENT] [MASK]      replace the installed hook by a fresh v3
    m10sio.py remove                  restore *(0x9b50) = 0x121 (blob kept)
    m10sio.py status | clear | mask MASK
    m10sio.py stream FILE SECONDS     fetch the ring continuously (+ FILE.marks)
    m10sio.py dump [FILE]
    m10sio.py cmos REG VAL|off        override CMOS register REG (12 bits)
    m10sio.py tg REG VAL [REG VAL..] | tg off   TG overrides (v4 table, v3 single)
    m10sio.py off                     clear every override (panic button)
    m10sio.py over                    override state and hit counters
"""
import os, struct, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam

PTR = 0x9b50
ORIG = 0x121
FN_MALLOC = 0xfc38d3f1
FN_DCLEAN = 0xfc1267cb   # (addr, len) D-cache clean range
FN_IINVAL = 0xfc126871   # (addr, len) I-cache invalidate range
BLOBS = {4: os.path.join(os.path.dirname(__file__), "siohook", "siohook4.bin"),
         5: os.path.join(os.path.dirname(__file__), "siohook", "siohook5.bin"),
         6: os.path.join(os.path.dirname(__file__), "siohook", "siohook6.bin")}
BLOB = BLOBS[5]
STATE = "/tmp/m10sio.state"
ESZ = 64
M1, M2, M3, M4 = 0x484f4953, 0x324f4953, 0x334f4953, 0x344f4953
M5 = 0x354f4953          # v5 = v4 layout + DFE addr/data in the ch4 table
M6 = 0x364f4953          # v6 = v5 with a 64-entry ch4 table (tg 0x300, match 0x400, ring 0x500)
MTAB = (0x344f4953, M5, M6)   # hooks with a ch4 (TG/DFE) table
# version -> (header offset, cmos table offset, ring offset)
LAYOUT = {M1: (0x100, None, 0x140), M2: (0x100, 0x140, 0x180), M3: (0x200, 0x240, 0x280),
          M4: (0x200, 0x240, 0x300), M5: (0x200, 0x240, 0x300),
          M6: (0x200, 0x240, 0x500)}
TGTAB, TGMATCH = 0x280, 0x2c0   # v4: 16 x (reg<<16|val), 16 x (bit16|orig val)


class Hook:
    """An installed blob: base address + layout."""
    def __init__(self, c, b, magic):
        self.c, self.b, self.magic = c, b, magic
        self.hdr, self.cmos, self.ent = LAYOUT[magic]
        # ch4 table: (tg offset, match offset, entries)
        self.tgtab, self.tgmatch, self.ntg = (0x300, 0x400, 64) if magic == M6 else (TGTAB, TGMATCH, 16)

    def h(self, off, n=1):
        v = self.c.peek(self.b + self.hdr + off, n)
        return v[0] if n == 1 else v

    def poke(self, addr, val):
        return self.c.call(self.b | 1, addr, val)

    def set_h(self, off, val):
        return self.poke(self.b + self.hdr + off, val)


def find(c):
    """Return the installed Hook, or None if *(0x9b50) is the original."""
    p = c.peek(PTR)[0]
    if p == ORIG:
        return None
    b = (p & ~1) - 0x10
    for m, (hdr, _, _) in LAYOUT.items():
        if c.peek(b + hdr)[0] == m:
            return Hook(c, b, m)
    raise SystemExit("*(0x9b50)=%08x: unknown hook, refusing" % p)


def base_of(c):
    """Back-compat for m10cmostry.py: (base, ptr)."""
    k = find(c)
    return (k.b if k else None), c.peek(PTR)[0]


def install(c, nent=2048, mask=0x50, swap=False, ver=5):
    assert nent & (nent - 1) == 0
    k = find(c)
    if k is not None and not swap:
        print("already installed at %08x" % k.b)
        return k
    if c.read(0x120, 8) != bytes.fromhex("436823f0ff031343"):
        raise SystemExit("low-RAM SIO code at 0x120 differs, refusing")
    MV = {4: M4, 5: M5, 6: M6}[ver]
    hdr, _, ent = LAYOUT[MV]
    blob = bytearray(open(BLOBS[ver], "rb").read())
    assert struct.unpack_from("<I", blob, hdr)[0] == MV
    size = ent + nent * ESZ
    mem = c.call(FN_MALLOC, size + 32)
    if not mem:
        raise SystemExit("malloc failed")
    b = (mem + 31) & ~31
    if swap and k is not None:
        orig = c.peek(k.b + k.hdr + 8)[0]      # chain to what the old hook chained to
        assert orig == ORIG, "old hook chains to %08x" % orig
    struct.pack_into("<IIIII", blob, hdr, MV, 0, ORIG, mask, nent - 1)
    c.write(b, bytes(blob))
    for o in range(len(blob), size, 0x10000):
        c.write(b + o, bytes(min(0x10000, size - o)))
    if c.read(b, len(blob)) != bytes(blob):
        raise SystemExit("blob readback mismatch")
    c.call(FN_DCLEAN, b, size)
    c.call(FN_IINVAL, b, len(blob))
    old = c.call(b | 1, PTR, (b + 0x10) | 1)       # poke32: atomic swap
    print("installed v%d at %08x (malloc %08x), nent %d, mask %#x, old ptr %08x"
          % (ver, b, mem, nent, mask, old))
    open(STATE, "w").write("%x %d %x\n" % (b, nent, MV))
    return Hook(c, b, MV)


def remove(c):
    k = find(c)
    if k is None:
        print("not installed")
        return
    k.poke(PTR, ORIG)
    print("removed (blob left at %08x, idx %d)" % (k.b, k.h(4)))


def clear_overrides(k):
    if k.magic in (M2, M3, M4, M5, M6):
        k.set_h(20, 0)
        for r in range(16):
            k.poke(k.b + k.cmos + 4 * r, 0)
    if k.magic in (M3, M4, M5, M6):
        k.set_h(28, 0)
        k.set_h(44, 0)
    if k.magic in MTAB:
        for i in range(k.ntg):
            k.poke(k.b + k.tgtab + 4 * i, 0)
            k.poke(k.b + k.tgmatch + 4 * i, 0)


def set_tg_table(k, entries):
    """v4: entries = [(reg, val) or (reg, val, required_orig_val)], armed atomically."""
    assert k.magic in MTAB and len(entries) <= k.ntg, (len(entries), k.ntg)
    k.set_h(28, 0)
    k.set_h(44, 0)
    for i in range(k.ntg):
        e = entries[i] if i < len(entries) else (0, 0)
        k.poke(k.b + k.tgmatch + 4 * i, (0x10000 | (e[2] & 0xffff)) if len(e) > 2 else 0)
        k.poke(k.b + k.tgtab + 4 * i, ((e[0] & 0xffff) << 16) | (e[1] & 0xffff))
    k.set_h(40, 0)
    if entries:
        k.set_h(28, 1)


def read_ring(k):
    idx, nm1 = k.h(4), k.h(16)
    nent = nm1 + 1
    n = min(idx, nent)
    raw = bytearray()
    for o in range(0, nent * ESZ, 0x8000):
        raw += k.c.read(k.b + k.ent + o, min(0x8000, nent * ESZ - o))
    return idx, [(j,) + struct.unpack_from("<16I", raw, (j & nm1) * ESZ)
                 for j in range(idx - n, idx)]


def save(fn, last, ents):
    open(fn, "wb").write(struct.pack("<II", last, len(ents)) +
                         b"".join(struct.pack("<17I", *e) for e in ents))


def stream(k, out, secs):
    c = k.c
    nm1 = k.h(16)
    nent = nm1 + 1
    last = k.h(4)
    ents, lost, t0, marks, tm = [], 0, time.time(), [], 0
    while time.time() - t0 < secs:
        idx = k.h(4)
        if time.time() - tm > 0.25:
            tm = time.time()
            m = (round(tm - t0, 2), idx, c.shadow(0xc0f06804), c.shadow(0xc0f06008),
                 c.shadow(0xc0f06014)) + tuple(c.peek(0x1beb5c, 2)) + (c.peek(0x28738)[0],)
            if not marks or marks[-1][2:] != m[2:]:
                print("t=%6.2f idx=%d 6804=%08x 6008=%08x 6014=%08x dss=%dx%d flags=%x" % m)
            marks.append(m)
        if idx - last > nent - 64:
            lost += idx - last - (nent - 64)
            last = idx - (nent - 64)
        while last < idx:
            s = last & nm1
            cnt = min(idx - last, nent - s, 1024)
            raw = c.read(k.b + k.ent + s * ESZ, cnt * ESZ)
            for j in range(cnt):
                ents.append((last + j,) + struct.unpack_from("<16I", raw, j * ESZ))
            last += cnt
        time.sleep(0.1)
    save(out, last, ents)
    open(out + ".marks", "w").write("\n".join(" ".join(str(x) for x in m) for m in marks))
    print("%d entries, %d lost, -> %s" % (len(ents), lost, out))


def over_state(k):
    s = "v%d" % {M1: 1, M2: 2, M3: 3, M4: 4, M5: 5, M6: 6}[k.magic]
    if k.magic in (M2, M3, M4, M5, M6):
        tab = k.c.peek(k.b + k.cmos, 16)
        s += " cmos_en=%d hits=%d [%s]" % (k.h(20), k.h(24), " ".join(
            "%d:%03x" % (r, v & 0xfff) for r, v in enumerate(tab) if v & 0x10000))
    if k.magic in MTAB:
        t, m = k.c.peek(k.b + k.tgtab, k.ntg), k.c.peek(k.b + k.tgmatch, k.ntg)
        s += " | tg_en=%d hits=%d [%s]" % (k.h(28), k.h(40), " ".join(
            "%04x=%04x%s" % (v >> 16, v & 0xffff, ("(if %04x)" % (mm & 0xffff)) if mm & 0x10000 else "")
            for v, mm in zip(t, m) if v >> 16))
    if k.magic == M3:
        s += " | tg_en=%d reg=%04x val=%04x hits=%d pend=%d" % (
            k.h(28), k.h(32), k.h(36), k.h(40), k.h(44))
    return s


def decode(e):
    k, t, ch, cfg, nb, lr, d0, d1 = e[:8]
    s = "%6d %06x ch%d nb%2d lr=%08x d0=%08x" % (k, t, ch, nb, lr, d0)
    if ch == 6 and nb == 16:
        s += "  CMOS reg %x = %03x" % (d0 >> 12 & 0xf, d0 & 0xfff)
    return s


def main(a):
    if not a:
        print(__doc__)
        return 1
    c = Cam()
    try:
        op = a[0]
        arg = lambda i, d: int(a[i], 0) if len(a) > i else d
        if op in ("install", "swap", "install6", "swap6", "install4", "swap4"):
            install(c, arg(1, 2048), arg(2, 0x50), swap=op.startswith("swap"), ver=6 if op.endswith("6") else (4 if op.endswith("4") else 5))
            return 0
        k = find(c)
        if k is None:
            print("ptr %08x (not installed)" % c.peek(PTR)[0])
            return 1
        if op == "remove":
            remove(c)
        elif op == "status":
            print("base %08x %s idx %d mask %#x nent %d" %
                  (k.b, over_state(k).split()[0], k.h(4), k.h(12), k.h(16) + 1))
        elif op == "clear":
            k.set_h(4, 0)
        elif op == "mask":
            k.set_h(12, int(a[1], 0))
        elif op == "off":
            clear_overrides(k)
            print("all overrides cleared:", over_state(k))
        elif op == "cmos":
            assert k.magic in (M2, M3, M4, M5, M6), "needs v2+"
            if a[1] == "off":
                clear_overrides(k)
            else:
                r = int(a[1], 0)
                v = 0 if a[2] == "off" else (0x10000 | (int(a[2], 0) & 0xfff))
                k.poke(k.b + k.cmos + 4 * r, v)
                k.set_h(20, 1)
            print(over_state(k))
        elif op == "tg" and k.magic in MTAB:
            if a[1] == "off":
                set_tg_table(k, [])
            else:
                set_tg_table(k, [(int(a[i], 0), int(a[i + 1], 0)) for i in range(1, len(a) - 1, 2)])
            print(over_state(k))
        elif op == "tg":
            assert k.magic == M3, "needs v3"
            if a[1] == "off":
                k.set_h(28, 0)
                k.set_h(44, 0)
            else:
                k.set_h(28, 0)
                k.set_h(32, int(a[1], 0) & 0xffff)
                k.set_h(36, int(a[2], 0) & 0xffff)
                k.set_h(44, 0)
                k.set_h(28, 1)
            print(over_state(k))
        elif op == "over":
            print(over_state(k))
        elif op == "stream":
            stream(k, a[1], float(a[2]) if len(a) > 2 else 20)
        elif op == "dump":
            idx, ents = read_ring(k)
            if len(a) > 1:
                save(a[1], idx, ents)
            print("base %08x idx %d (%d kept)" % (k.b, idx, len(ents)))
            for e in ents:
                print(decode(e))
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
