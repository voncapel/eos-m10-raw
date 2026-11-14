import sys,struct,re; sys.path.insert(0,__import__('os').path.dirname(__file__))
from xref import D,B
import capstone
md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB); md.skipdata=True
def s_at(a):
    if not (B<=a<B+len(D)): return None
    s=D[a-B:a-B+64].split(b'\0')[0]
    if re.fullmatch(rb'[A-Za-z0-9_]+\.c',s): return s.decode()
def fileof(addr,span=0x1000):
    best=None
    for ins in md.disasm(D[addr-span-B:addr+span-B],addr-span):
        o=ins.op_str; t=None
        if ins.mnemonic in('adr','adr.w') : 
            try: t=((ins.address+4)&~3)+int(o.split('#')[1],16)
            except: pass
        elif ins.mnemonic.startswith('subw') and 'pc' in o:
            t=((ins.address+4)&~3)-int(o.split('#')[1],16)
        elif ins.mnemonic.startswith('addw') and 'pc' in o:
            t=((ins.address+4)&~3)+int(o.split('#')[1],16)
        elif ins.mnemonic.startswith('ldr') and 'pc,' in o and '#' in o:
            try:
                lit=((ins.address+4)&~3)+int(o.split('#')[1].rstrip(']'),16); t=struct.unpack_from('<I',D,lit-B)[0]
            except: pass
        if t:
            s=s_at(t)
            if s:
                d=abs(ins.address-addr)
                if best is None or d<best[0]: best=(d,s)
    return best[1] if best else '?'
if __name__=='__main__':
    for a in sys.argv[1:]: print(a,fileof(int(a,16)))
