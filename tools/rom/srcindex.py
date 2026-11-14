#!/usr/bin/env python3
"""Map Canon source-file names (e.g. CMOSDrv.c) to the ROM code that cites them.

Canon's assert/log calls load the address of the source-file string.  We scan
the whole ROM (Thumb) for literal-pool loads / adr pointing at "*.c" strings,
then attribute each hit to the enclosing function (nearest preceding push lr).

    srcindex.py build                -> writes srcindex.json (cache)
    srcindex.py file CMOSDrv.c       -> functions citing that file
    srcindex.py grep CMOS            -> files matching a regex, with counts
"""
import json, os, re, struct, sys
sys.path.insert(0, os.path.dirname(__file__))
from xref import D, B

CACHE = os.path.join(os.path.dirname(__file__), "srcindex.json")


def cstrings():
    out = {}
    for m in re.finditer(rb"[A-Za-z0-9_]{2,60}\.c\0", D):
        out[B + m.start()] = m.group()[:-1].decode()
    return out


def func_start(a):
    for x in range(a & ~1, max(B, a - 0x2000), -2):
        h = struct.unpack_from("<H", D, x - B)[0]
        h2 = struct.unpack_from("<H", D, x - B + 2)[0]
        if (h & 0xff00) == 0xb500 or (h == 0xe92d and h2 & 0x4000):
            return x
    return None


def build():
    strs = cstrings()
    lits = {}
    for off in range(0, len(D) - 4, 4):
        v = struct.unpack_from("<I", D, off)[0]
        if v in strs:
            lits[B + off] = v
    hits = {}
    for a in range(B, B + len(D) - 4, 2):
        h = struct.unpack_from("<H", D, a - B)[0]
        t = None
        if (h & 0xf800) == 0x4800:            # ldr rX,[pc,#imm8*4]
            t = ((a + 4) & ~3) + (h & 0xff) * 4
        elif h == 0xf8df:                     # ldr.w rX,[pc,#imm12]
            h2 = struct.unpack_from("<H", D, a - B + 2)[0]
            t = ((a + 4) & ~3) + (h2 & 0xfff)
        elif (h & 0xf800) == 0xa000:          # adr rX,#imm8*4
            v = ((a + 4) & ~3) + (h & 0xff) * 4
            if v in strs:
                hits.setdefault(strs[v], set()).add(a)
            continue
        if t is not None and t in lits:
            hits.setdefault(strs[lits[t]], set()).add(a)
    idx = {}
    for f, sites in hits.items():
        fns = {}
        for s in sites:
            fs = func_start(s)
            if fs:
                fns.setdefault("0x%08x" % fs, []).append("0x%08x" % s)
        idx[f] = fns
    json.dump(idx, open(CACHE, "w"), indent=0, sort_keys=True)
    return idx


def load():
    return json.load(open(CACHE)) if os.path.exists(CACHE) else build()


if __name__ == "__main__":
    op = sys.argv[1] if len(sys.argv) > 1 else "build"
    if op == "build":
        print("%d files indexed" % len(build()))
    elif op == "file":
        for fn, sites in sorted(load().get(sys.argv[2], {}).items()):
            print(fn, len(sites))
    elif op == "grep":
        r = re.compile(sys.argv[2], re.I)
        for f, fns in sorted(load().items()):
            if r.search(f):
                print("%-36s %3d funcs" % (f, len(fns)))
