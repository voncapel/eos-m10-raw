import struct,re,capstone,sys
D=open(__import__('os').path.join(__import__('os').path.dirname(__file__),'..','..','dumps','M10_110d_ROM_8MB.BIN'),'rb').read(); B=0xfc000000
md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB)
def bl_target(a):
    h1,h2=struct.unpack_from('<HH',D,a-B)
    if (h1&0xf800)!=0xf000 or (h2&0xd000) not in (0xd000,0xc000): return None
    S=(h1>>10)&1; imm10=h1&0x3ff; J1=(h2>>13)&1; J2=(h2>>11)&1; imm11=h2&0x7ff
    I1=1-(J1^S); I2=1-(J2^S)
    off=(S<<24)|(I1<<23)|(I2<<22)|(imm10<<12)|(imm11<<1)
    if S: off-=1<<25
    t=a+4+off
    if (h2&0x1000)==0: t&=~3
    return t
def callers(targets):
    out=[]
    for a in range(B,B+len(D)-4,2):
        t=bl_target(a)
        if t is not None and (t&~1) in targets: out.append(a)
    return out
