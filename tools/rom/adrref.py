import struct
D=open(__import__('os').path.join(__import__('os').path.dirname(__file__),'..','..','dumps','M10_110d_ROM_8MB.BIN'),'rb').read(); B=0xfc000000
def adr_refs(t):
    out=[]
    lo=max(0,t-B-4200); hi=min(len(D)-4,t-B+4200)
    for i in range(lo,hi,2):
        a=B+i; h=struct.unpack_from('<H',D,i)[0]
        pc=(a+4)&~3
        if (h&0xf800)==0xa000 and pc+(h&0xff)*4==t: out.append(a)
        h2=struct.unpack_from('<H',D,i+2)[0]
        if (h&0xfbff) in (0xf20f,0xf2af) and (h2&0x8000)==0:
            imm=((h>>10)&1)<<11 | ((h2>>12)&7)<<8 | (h2&0xff)
            if (h&0xfbff)==0xf20f and pc+imm==t: out.append(a)
            if (h&0xfbff)==0xf2af and pc-imm==t: out.append(a)
    return out
