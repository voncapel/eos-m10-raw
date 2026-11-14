import struct,sys
p=sys.argv[1]
d=open(p,'rb').read()
hd=struct.unpack_from('<8I',d,0)
print('hdr magic=%08x pass=%d tl_n=%d sioidx=%d nent=%d base=%08x'%hd[:6])
tl=[struct.unpack_from('<10I',d,32+40*i) for i in range(hd[2])]
o=32+40*160
nent=hd[4]; ring=d[o:o+nent*64]; o+=nent*64
stg=struct.unpack_from('<%dI'%(16*12*4),d,o)
# ring entries: us, ch, cfg, nbits, LR, data0, data1, stack...
ents=[struct.unpack_from('<16I',ring,64*i) for i in range(nent)]
idx=hd[3]
# order: entries i&(nent-1) by index; latest index idx-1
N=nent
seq=[ents[(i)%N] for i in range(idx-N,idx)]
t0=tl[0][0] if tl else 0
def rel(u): return ((u-t0+0x80000)&0xfffff)-0x80000
print('timeline (us rel first sample, ptr lines, tg, sio)')
lb=2260
for t in tl[:80]:
    print('%7d %5d tg=%d sio=%d'%(rel(t[0]),t[1]//lb,t[2] if t[2]<0x80000000 else t[2]-2**32,t[3]))
ev=[]
for k,e in enumerate(seq):
    if e[4]==0xfc1bd4e3 and e[5]==0x8830: ev.append(('8830',rel(e[0]&0xfffff),idx-N+k))
    if e[4]==0xfc1bec0f and ((e[5]>>12)&0xf)==0: ev.append(('CMOS0',rel(e[0]&0xfffff),idx-N+k))
print('events near:')
for x in ev[-40:]: print(x)
print('last 60 SIO entries:')
for k,e in enumerate(seq[-60:]):
    print('%6d %8d ch=%d LR=%08x d=%08x %08x'%(idx-60+k, rel(e[0]&0xfffff), e[1], e[4], e[5], e[6]))
