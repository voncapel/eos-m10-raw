import struct,sys,collections
d=open(sys.argv[1],'rb').read()
hd=struct.unpack_from('<8I',d,0)
o=32+40*160; nent=hd[4]; o2=o+nent*64; idx=hd[3]
stg=struct.unpack_from('<%dI'%(16*12*4),d,o2)
E=[struct.unpack_from('<16I',d,o+64*i) for i in range(nent)]
ents=[E[j&(nent-1)] for j in range(idx-nent,idx)]
slot=int(sys.argv[2])
ref=stg[(slot*12+5)*4]&0xfffff
rel=lambda t:(((t-ref+0x80000)&0xfffff)-0x80000)/1000
print('stages', ['%d:%.1f'%(i,rel(stg[(slot*12+i)*4])) for i in range(12) if stg[(slot*12+i)*4]])
# group entries into bursts by 0.5ms gaps
cur=[];out=[]
for e in ents:
    t=rel(e[0]&0xfffff)
    if t<-130: continue
    if cur and t-cur[-1][0]>0.4: out.append(cur); cur=[]
    cur.append((t,e[4],e[5]))
out.append(cur)
for g in out:
    c=collections.Counter('%x'%x[1] for x in g)
    keys=[('%x'%x[2]) for x in g if x[1] in (0xfc1bd4e3,0xfc1bec0f)][:6]
    print('%7.1f +%4.1f n=%3d %s %s'%(g[0][0],g[-1][0]-g[0][0],len(g),dict(c),keys))
