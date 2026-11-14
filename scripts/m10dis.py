#!/usr/bin/env python3
"""Tiny Thumb2 disassembler/xref helper for the M10 110f ROM (base 0xFC000000)."""
import sys, struct, re, capstone
BASE=0xfc000000
D=open(__file__.rsplit('/',2)[0]+'/dumps/M10_110f_ROM.BIN','rb').read()
NAMES={}
for l in open(__file__.rsplit('/',2)[0]+'/chdk/trunk/platform/m10/sub/110f/funcs_by_name.csv'):
    p=l.strip().split(',')
    if len(p)>=2 and p[0].startswith('0x'): NAMES[int(p[0],16)&~1]=p[1]
md=capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB); md.detail=False
def u32(a): return struct.unpack_from('<I',D,a-BASE)[0]
def cstr(a):
    o=a-BASE
    if not (0<=o<len(D)): return None
    e=D.find(b'\0',o,o+200)
    s=D[o:e]
    return s.decode('latin1') if e>o and all(32<=c<127 or c in (9,10) for c in s) else None
def dis(addr,n=60):
    addr&=~1
    for i in md.disasm(D[addr-BASE:addr-BASE+n*4],addr):
        c=''
        m=re.search(r'#0x([0-9a-f]+)',i.op_str)
        if i.mnemonic.startswith(('bl','b.','b ','blx','cb')) or i.mnemonic in('b','bl','blx','b.w'):
            if m: t=int(m.group(1),16); c=NAMES.get(t&~1,'')
        if i.mnemonic.startswith('ldr') and '[pc' in i.op_str:
            off=re.search(r'#0x([0-9a-f]+)',i.op_str); off=int(off.group(1),16) if off else 0
            lit=((i.address+4)&~3)+off; v=u32(lit); s=cstr(v); c=f'=0x{v:x}'+(f' "{s}"' if s else '')+(' '+NAMES.get(v&~1,'') if (v&~1) in NAMES else '')
        print(f'{i.address:08x}: {i.mnemonic:8} {i.op_str:30} {c}')
        n-=1
        if n<=0: break
def strxref(s):
    """Find string addr, then literal-pool words pointing to it."""
    out=[]
    for m in re.finditer(re.escape(s.encode())+b'\0',D):
        sa=BASE+m.start()
        w=struct.pack('<I',sa)
        refs=[BASE+r.start() for r in re.finditer(re.escape(w),D) if r.start()%4==0]
        out.append((sa,refs))
    return out
if __name__=='__main__':
    if sys.argv[1]=='d': dis(int(sys.argv[2],16), int(sys.argv[3]) if len(sys.argv)>3 else 60)
    elif sys.argv[1]=='s':
        for sa,refs in strxref(sys.argv[2]): print(hex(sa), [hex(r) for r in refs])
