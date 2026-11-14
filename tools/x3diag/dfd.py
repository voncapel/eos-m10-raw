import struct,sys,collections
d=open(sys.argv[1],'rb').read()
hd=struct.unpack_from('<8I',d,0)
o=32+40*160+hd[4]*64+16*12*4*4+256
W=1+3*24
cnt=collections.Counter()
for k in range(16):
    r=struct.unpack_from('<%dI'%W,d,o+4*W*k)
    n=r[0]
    items=[(r[1+3*i],r[2+3*i],r[3+3*i]) for i in range(min(n,24))]
    for it in items: cnt[it[0]]+=1
    print(k,n,' '.join('%x:%x>%x'%it for it in items)[:300])
print(cnt.most_common(30))
