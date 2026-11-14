import sys,struct; sys.path.insert(0,__import__('os').path.dirname(__file__))
from xref import bl_target,D,B
def pushes(lo,hi):
    out=[]
    for a in range(lo,hi,2):
        h=struct.unpack_from('<H',D,a-B)[0]
        if (h&0xff00)==0xb500: out.append(a)           # push {..,lr}
        h2=struct.unpack_from('<H',D,a-B+2)[0]
        if h==0xe92d and (h2&0x4000): out.append(a)    # push.w {..,lr}
    return out
_allbl=None
def allbl():
    global _allbl
    if _allbl is None:
        _allbl={}
        for a in range(B,B+len(D)-4,2):
            t=bl_target(a)
            if t is not None: _allbl.setdefault(t&~1,[]).append(a)
    return _allbl
def bw_target(a):
    h1,h2=struct.unpack_from('<HH',D,a-B)
    if (h1&0xf800)!=0xf000 or (h2&0xd000)!=0x9000: return None
    S=(h1>>10)&1; imm10=h1&0x3ff; J1=(h2>>13)&1; J2=(h2>>11)&1; imm11=h2&0x7ff
    I1=1-(J1^S); I2=1-(J2^S)
    off=(S<<24)|(I1<<23)|(I2<<22)|(imm10<<12)|(imm11<<1)
    if S: off-=1<<25
    return a+4+off
def anyref(targets):
    out=[]
    for a in range(B,B+len(D)-4,2):
        t=bl_target(a) or bw_target(a)
        if t is not None and (t&~1) in targets: out.append((a,t&~1))
    return out
