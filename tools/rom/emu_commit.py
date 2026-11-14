#!/usr/bin/env python3
"""emu_commit.py — unicorn harness for M10 (fw 1.10d) image-pipeline code.

Loads the 8 MB ROM at 0xfc000000 and a 4 MB RAM snapshot at 0, stubs the DryOS
kernel (0xbfe0xxxx, not in the dump), traps every MMIO access 0xc0000000-0xdfffffff
(reads return the engine shadow value, writes are logged), and runs one ROM
function with given arguments.  Used to find which engine registers follow the
head height H (see notes/head_height_deps.md).

    python3 emu_commit.py extract 7 [H]          Extract.c 0xfc157082(idx)
    python3 emu_commit.py fld [MODE] [H]         FldCreat 0xfc22f2c0 via the ImgSens cache
    python3 emu_commit.py sweep                  fld at H = 1190 1254 1440 1800 2270, law table

As a module: E = Emu(); E.call(addr, args); E.writes -> [(pc, reg, val, kind)]
"""
import os, struct, sys
from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_ARM, \
    UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_UNMAPPED, UC_HOOK_CODE, \
    UC_HOOK_MEM_FETCH_UNMAPPED, UC_PROT_ALL
from unicorn.arm_const import *

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.join(HERE, '..', '..')
ROM_PATH = os.path.join(PROJ, 'dumps', 'M10_110d_ROM_8MB.BIN')
ROM_F_PATH = os.path.join(PROJ, 'dumps', 'M10_110f_ROM.BIN')
RAM_PATH = os.path.join(PROJ, 'captures', 'live70', 'ram_VIDEO_STD.bin')
ROM_BASE, RAM_SIZE = 0xfc000000, 0x400000
SHADOW_PTR = 0x28dbc
STACK_TOP = 0x3f0000          # inside the RAM dump, high area (zeroed before use)
RET_MAGIC = 0x00000100        # return address sentinel (Thumb |1 added)
TRAMP_A, TRAMP_T = 0xbfef0000, 0xbfef0010   # 'bx lr' trampolines (ARM / Thumb) in the stub page
ENGDRV_OUT, ENGDRV_MASK = 0xfc38d28a, 0xfc38d2c4

# DryOS / libc entry points that are reached through ARM thunks and are not in the dump.
# Anything executed outside [ROM] and [RAM code] is answered with r0 = 0 and a return.
KNOWN = {
    0xbfe153e5: 'TakeSemaphore', 0xbfe1545d: 'GiveSemaphore', 0xbfe1496d: 'SleepTask',
    0xbfe14e53: 'SetEventFlag', 0xbfe14e81: 'ClearEventFlag', 0xbfe14d51: 'WaitForAnyEventFlag',
    0xbfe14dd3: 'WaitForAllEventFlag', 0xbfe14eb1: 'GetEventFlagValue', 0x010e1009: 'DebugAssert',
    0x010e101f: 'DebugAssert2', 0xbfe151d5: 'PostMessageQueue', 0xbfe15253: 'TryPostMessageQueue',
    0xbfe150ff: 'ReceiveMessageQueue',
}


def _bzero(E, d, n, _):
    if 0 < n < 0x1000000 and E.ensure(d, n): E.u.mem_write(d, b'\0' * n)
def _memset(E, d, c, n):
    if 0 < n < 0x1000000 and E.ensure(d, n): E.u.mem_write(d, bytes([c & 0xff]) * n)
def _memset32(E, d, n, v):          # ^[inferred] memset32(dst, len, value)
    if 0 < n < 0x1000000 and E.ensure(d, n): E.u.mem_write(d, struct.pack('<I', v) * (n // 4))
def _memcpy(E, d, s, n):
    if 0 < n < 0x1000000 and E.ensure(d, n) and E.ensure(s, n):
        E.u.mem_write(d, bytes(E.u.mem_read(s, n)))
        E.copies.append((d, s, n))
def _memzero(E, d, n, _): _bzero(E, d, n, 0)

# RAM-resident libc (0x0110xxxx, beyond the 4 MB snapshot), by address from funcs_by_address.csv
LIBC = {0x01100b74: _bzero, 0x01100b78: _memset32, 0x01100a48: _memzero, 0x01100a38: _memset,
        0x01100a8c: _memcpy, 0x01100928: _memcpy, 0x011009b0: _memcpy}


class Emu:
    def __init__(self, ram_path=RAM_PATH, trace=False, max_insn=2_000_000):
        self.rom = open(ROM_PATH, 'rb').read()
        ram = bytearray(open(ram_path, 'rb').read())
        self.u = u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        u.mem_map(0, RAM_SIZE, UC_PROT_ALL)
        u.mem_write(0, bytes(ram))
        u.mem_map(ROM_BASE, 0x2000000, UC_PROT_ALL)
        # ^[inferred] beyond the 8 MB 1.10d dump, use the 32 MB 1.10f dump (data tables only;
        # code is < 8 MB). Approximation: flagged in the report when such reads occur.
        if os.path.exists(ROM_F_PATH):
            f = open(ROM_F_PATH, 'rb').read()
            u.mem_write(ROM_BASE + 0x800000, f[0x800000:0x2000000])
        u.mem_write(ROM_BASE, self.rom)
        u.hook_add(UC_HOOK_MEM_READ, self._hi_rom, begin=ROM_BASE + 0x800000, end=ROM_BASE + 0x1ffffff)
        # uncached alias of RAM (0x40000000 | addr) used by Canon for DMA buffers
        u.mem_map(0x40000000, RAM_SIZE, UC_PROT_ALL)
        u.mem_write(0x40000000, bytes(ram))
        # MMIO window (engine + peripherals): mapped so accesses succeed, hooked to log
        u.mem_map(0xc0000000, 0x01000000, UC_PROT_ALL)
        u.mem_map(0xd0000000, 0x00100000, UC_PROT_ALL)
        # kernel area: one RAM page per thunk target so fetch succeeds, then we redirect
        u.mem_map(0xbfe00000, 0x100000, UC_PROT_ALL)
        u.mem_write(TRAMP_A, struct.pack('<I', 0xe12fff1e))      # bx lr (ARM)
        u.mem_write(TRAMP_T, struct.pack('<H', 0x4770))          # bx lr (Thumb)
        self.shadow_base = struct.unpack_from('<I', ram, SHADOW_PTR)[0]
        # shadow lives at 0x01040000 (beyond the 4 MB dump): map a private copy
        self.shadow = bytearray(0x80000)
        sp = os.path.join(PROJ, 'captures', 'live70', 'shadow_pf_1_VIDEO_STD.bin')
        if os.path.exists(sp):
            self.shadow[:] = open(sp, 'rb').read()[:0x80000]
        u.mem_map(0x01000000, 0x00200000, UC_PROT_ALL)    # 0x0100_0000-0x011f_ffff (shadow + RAM code 0x010e...)
        u.mem_write(self.shadow_base, bytes(self.shadow))
        u.mem_map(0x00400000, 0x00c00000, UC_PROT_ALL)    # rest of low RAM (heap above the dump)
        self.writes, self.reads, self.calls, self.stubs = [], [], [], {}
        self.hi_rom_reads, self.lazy, self.copies = set(), set(), []
        self.trace, self.max_insn, self.n = trace, max_insn, 0
        self.stub_ret = {}          # addr -> r0 value for named stubs
        u.hook_add(UC_HOOK_MEM_WRITE, self._mmio_w, begin=0xc0000000, end=0xdfffffff)
        u.hook_add(UC_HOOK_MEM_READ, self._mmio_r, begin=0xc0000000, end=0xdfffffff)
        u.hook_add(UC_HOOK_CODE, self._code)
        u.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)

    # ---- hooks
    def _mmio_w(self, u, access, addr, size, val, _):
        pc = u.reg_read(UC_ARM_REG_PC)
        val &= (1 << (8 * size)) - 1
        self.writes.append((pc, addr, val, 'mmio'))
        if 0xc0f00000 <= addr < 0xc1000000:     # keep the shadow coherent for later reads
            off = addr & 0x7ffff
            struct.pack_into('<I', self.shadow, off & ~3, val)

    def _mmio_r(self, u, access, addr, size, val, _):
        off = addr & 0x7ffff
        v = struct.unpack_from('<I', self.shadow, off & ~3)[0] if 0xc0f00000 <= addr < 0xc1000000 else 0
        u.mem_write(addr & ~3, struct.pack('<I', v))
        self.reads.append((u.reg_read(UC_ARM_REG_PC), addr))

    def _hi_rom(self, u, access, addr, size, val, _):
        self.hi_rom_reads.add((u.reg_read(UC_ARM_REG_PC), addr & ~0xff))

    def ensure(self, addr, n=4):
        """map (zeroed) 1 MB pages on demand for RAM/DMA buffers outside the snapshot"""
        if not (addr < 0x80000000 or 0xa0000000 <= addr < 0xb0000000):
            return False
        for p in range(addr & ~0xfffff, (addr + n + 0xfffff) & ~0xfffff, 0x100000):
            try:
                self.u.mem_map(p, 0x100000, UC_PROT_ALL); self.lazy.add(p)
            except UcError:
                pass
        return True

    def _unmapped(self, u, access, addr, size, val, _):
        if access in (20, 21):          # fetch: genuine derail
            print('!! unmapped fetch %#x' % addr); return False
        if self.ensure(addr, size):
            return True
        pc = u.reg_read(UC_ARM_REG_PC)
        print('!! unmapped access %#x at pc %#x (type %d)' % (addr, pc, access))
        return False

    def _ret(self, r0=0):
        u = self.u
        lr = u.reg_read(UC_ARM_REG_LR)
        u.reg_write(UC_ARM_REG_R0, r0 & 0xffffffff)
        self._jump(lr)

    def _jump(self, target):
        # unicorn ignores T-bit changes through CPSR writes inside a hook; return through
        # an ARM 'bx lr' trampoline so the interworking bit of LR is honoured.
        u = self.u
        u.reg_write(UC_ARM_REG_LR, target)
        cpsr = u.reg_read(UC_ARM_REG_CPSR)
        if cpsr & 0x20:        # currently Thumb: use the Thumb trampoline
            u.reg_write(UC_ARM_REG_PC, TRAMP_T | 1)
        else:
            u.reg_write(UC_ARM_REG_PC, TRAMP_A)

    def _code(self, u, addr, size, _):
        self.n += 1
        if self.n > self.max_insn:
            print('!! instruction budget exhausted at %#x' % addr); u.emu_stop(); return
        if addr == RET_MAGIC:
            u.emu_stop(); return
        if self.trace:
            print('  %08x' % addr)
        # EngDrvOut / masked EngDrvOut: log as engine writes (the MMIO hook also sees them)
        if addr in (ENGDRV_OUT, ENGDRV_MASK):
            r0, r1, r2 = (u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
            self.calls.append((u.reg_read(UC_ARM_REG_LR) - 1, 'EngDrvOut' if addr == ENGDRV_OUT else 'EngDrvMask', r0, r1, r2))
            return
        if addr in (TRAMP_A, TRAMP_T):
            return
        if (addr | 1) in LIBC or addr in LIBC:
            fn = LIBC.get(addr | 1) or LIBC[addr]
            a0, a1, a2 = (u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
            fn(self, a0, a1, a2)
            self.stubs[fn.__name__] = self.stubs.get(fn.__name__, 0) + 1
            self._ret(a0)
            return
        if 0xbfe00000 <= addr < 0xbff00000 or 0x010e0000 <= addr < 0x01200000:
            name = KNOWN.get(addr | 1, KNOWN.get(addr, 'k_%08x' % addr))
            self.stubs[name] = self.stubs.get(name, 0) + 1
            self._ret(self.stub_ret.get(name, 0))
            return
        if addr in self.patches:
            self.patches[addr](self)

    ram_code_ok = set()
    patches = {}

    # ---- API
    def r32(self, a): return struct.unpack('<I', self.u.mem_read(a, 4))[0]
    def w32(self, a, v): self.u.mem_write(a, struct.pack('<I', v & 0xffffffff))
    def rd(self, a, n): return bytes(self.u.mem_read(a, n))
    def wr(self, a, b): self.u.mem_write(a, b)

    def call(self, fn, args=(), stack_args=()):
        u = self.u
        sp = STACK_TOP
        u.mem_write(sp - 0x8000, b'\0' * 0x8000)
        sp -= 0x100
        for i, v in enumerate(stack_args):
            self.w32(sp + 4 * i, v)
        regs = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
        for r, v in zip(regs, list(args) + [0] * 4):
            u.reg_write(r, v & 0xffffffff)
        u.reg_write(UC_ARM_REG_SP, sp)
        u.reg_write(UC_ARM_REG_LR, RET_MAGIC | 1)
        self.n = 0
        try:
            u.emu_start(fn | 1, RET_MAGIC, count=self.max_insn + 10)
        except UcError as e:
            print('!! UcError %s at pc %#x' % (e, u.reg_read(UC_ARM_REG_PC)))
        return u.reg_read(UC_ARM_REG_R0)

    def engine_writes(self):
        """final value per engine register written (MMIO hook, last write wins)"""
        out = {}
        for pc, a, v, k in self.writes:
            out[a] = (v, pc)
        return out


# ------------------------------------------------------------------ experiments
EXTRACT_FN, EXTRACT_TAB = 0xfc157082, 0x2cd24
FLD_FN, IMGS_CACHE = 0xfc22f2c0, 0x575b0
EXTRACT_REC_FILM = 0xfc72f34c


def patch_extract_record(E, idx, H, base=EXTRACT_REC_FILM, scratch=0x3e0000):
    rec = bytearray(E.rom[base - ROM_BASE: base - ROM_BASE + 0x68])
    for off in (0x10, 0x18, 0x28):            # visible H, H2, head y1 (live69)
        struct.pack_into('<i', rec, off, H)
    E.wr(scratch, bytes(rec))
    E.w32(EXTRACT_TAB + 4 * idx, scratch)
    return scratch


def run_extract(idx=7, H=None):
    E = Emu()
    if H is not None:
        patch_extract_record(E, idx, H)
    E.w32(0xe460, 1)                          # Extract "open" state (else returns 0x17)
    r = E.call(EXTRACT_FN, (idx,))
    return E, r


def run_fld(mode=36, H=None, W=None):
    """FldCreat(mode, W, H, bpp/ppp, struct) as called by ImgSens 0xfc1ee394, args from the cache"""
    E = Emu()
    c = IMGS_CACHE + 36 * mode
    w, h = E.r32(c), E.r32(c + 4)
    if H is not None:
        h = H
        E.w32(c + 4, H); E.w32(c + 12, H)
    if W is not None:
        w = W
        E.w32(c, W); E.w32(c + 8, W)
    bpp = E.r32(c + 0x10)
    st = E.r32(c + 0x20)
    E.w32(0x13dc0c, 0)                         # PreProCommon use count 0 -> FldCreat does a full setup (0xfc34d3fc)
    r = E.call(FLD_FN, (mode, w, h, bpp), stack_args=(st,))
    return E, r


def law(v, H, ref_v, ref_H):
    """express the change of a register as a function of H (per 16-bit half)"""
    out = []
    for name, sh in (('lo', 0), ('hi', 16)):
        a, b = (ref_v >> sh) & 0xffff, (v >> sh) & 0xffff
        if a == b: continue
        d = b - a; dH = H - ref_H
        for k, s in ((1, 'H'), (2, '2H'), (0.5, 'H/2'), (3, '3H'), (4, '4H')):
            if abs(d - k * dH) <= 1:
                c = int(round(b - k * H))
                out.append('%s=%s%+d' % (name, s, c) if c else '%s=%s' % (name, s)); break
        else:
            out.append('%s:%d->%d' % (name, a, b))
    if not out and v != ref_v:
        out.append('%08x->%08x' % (ref_v, v))
    return ' '.join(out)


def sweep(Hs=(1190, 1254, 1440, 1800, 2270), runner=run_fld):
    res = {}
    for H in Hs:
        E, r = runner(H=H)
        res[H] = E.engine_writes()
        print('H=%d: %d engine writes, %d distinct regs, ret %#x, stubs %s' %
              (H, len(E.writes), len(res[H]), r, dict(sorted(E.stubs.items()))))
    ref = res[Hs[0]]
    regs = sorted(set().union(*[set(x) for x in res.values()]))
    rows = []
    for a in regs:
        vals = [res[H].get(a, (None, 0))[0] for H in Hs]
        if len(set(vals)) > 1:
            rows.append((a, vals, law(vals[-1], Hs[-1], vals[0], Hs[0]), res[Hs[0]].get(a, (0, 0))[1]))
    static = [a for a in regs if len(set(res[H].get(a, (None, 0))[0] for H in Hs)) == 1]
    return res, rows, static


if __name__ == '__main__':
    a = sys.argv[1:] or ['sweep']
    if a[0] == 'extract':
        E, r = run_extract(int(a[1]) if len(a) > 1 else 7, int(a[2]) if len(a) > 2 else None)
        print('ret', hex(r), 'stubs', E.stubs)
        for pc, reg, val, k in E.writes: print('  %08x <- %08x   (pc %08x)' % (reg, val, pc))
    elif a[0] == 'fld':
        E, r = run_fld(int(a[1]) if len(a) > 1 else 36, int(a[2]) if len(a) > 2 else None)
        print('ret', hex(r), 'stubs', E.stubs, 'insn', E.n)
        for pc, reg, val, k in E.writes: print('  %08x <- %08x   (pc %08x)' % (reg, val, pc))
    elif a[0] == 'sweep':
        res, rows, static = sweep()
        print('\nregisters that follow H (value at 1190 ... 2270, law, writer pc @1190):')
        for reg, vals, lw, pc in rows:
            print('  %08x  %s  %-22s pc %08x' % (reg, ' '.join('%08x' % (v or 0) for v in vals), lw, pc))
        print('%d registers written but constant in H' % len(static))
