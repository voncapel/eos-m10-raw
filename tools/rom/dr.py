import sys; sys.path.insert(0,__import__('os').path.dirname(__file__))
import capstone,struct
from xref import D,B
md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB); md.skipdata=True
def dr(lo,hi):
    for ins in md.disasm(D[lo-B:hi-B],lo):
        s=ins.op_str
        if ins.mnemonic.startswith('ldr') and 'pc,' in s and '#' in s:
            try:
                off=int(s.split('#')[1].rstrip(']'),16); lit=((ins.address+4)&~3)+off
                if B<=lit<B+len(D): s+='  ; =%08x'%struct.unpack_from('<I',D,lit-B)[0]
            except: pass
        print(hex(ins.address),ins.mnemonic,s)
if __name__=='__main__': dr(int(sys.argv[1],16),int(sys.argv[2],16))
