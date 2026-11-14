import struct,sys
d=open(sys.argv[1],'rb').read()
mag,n,nch,_=struct.unpack_from('<4I',d,0)
ch=struct.unpack_from('<%dI'%nch,d,16); o=16+4*nch
R=[struct.unpack_from('<%dI'%(2+nch),d,o+4*(2+nch)*i) for i in range(n)]
o+=4*(2+nch)*n
idx,nent=struct.unpack_from('<2I',d,o); o+=8
E=[struct.unpack_from('<16I',d,o+64*i) for i in range(nent)]
first=idx-nent; ent=lambda j:E[j&(nent-1)]
T={};acc=0;prev=ent(first)[0]&0xfffff
for j in range(first,idx):
    t=ent(j)[0]&0xfffff; acc+=(t-prev)&0xfffff; prev=t; T[j]=acc
lastT=T[idx-1]; lastraw=ent(idx-1)[0]&0xfffff
at=lambda raw: lastT-((lastraw-raw)&0xfffff)
D=[T[j] for j in range(first,idx) if ent(j)[4]==0xfc1bd4e3 and ent(j)[5]==0x8830]
C=[T[j] for j in range(first,idx) if ent(j)[4]==0xfc1bec0f and (ent(j)[5]>>12)&0xf==0]
ts=[at(r[0]) for r in R]
# 0.5 ms bins, 3 frames starting from the 3rd 8830 inside window
D=[x for x in D if ts[0]<x<ts[-1]]
base=D[1]
names=[('%x'%(c-8))[-5:] for c in ch]
act={}
for i in range(1,n):
    for c in range(nch):
        if R[i][2+c]!=R[i-1][2+c]:
            b=int((ts[i]-base)//500)
            act.setdefault(b,set()).add(c)
used=sorted(set(c for s in act.values() for c in s))
print('t(ms)  '+' '.join('%5s'%names[c] for c in used))
for b in range(0,240):
    t=b*0.5
    mark=''
    for x in D:
        if 0<=x-base-b*500<500: mark+=' <8830'
    for x in C:
        if 0<=x-base-b*500<500: mark+=' <CMOS'
    s=act.get(b,set())
    print('%5.1f  '%t+' '.join('%5s'%('#' if c in s else '.') for c in used)+mark)
