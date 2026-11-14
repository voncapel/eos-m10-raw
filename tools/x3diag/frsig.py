import struct,sys,collections
d=open(sys.argv[1],'rb').read()
hd=struct.unpack_from('<8I',d,0)
o=32+40*160; nent=hd[4]; idx=hd[3]
E=[struct.unpack_from('<16I',d,o+64*i) for i in range(nent)]
first=idx-nent; ent=lambda j:E[j&(nent-1)]
T={};acc=0;prev=ent(first)[0]&0xfffff
for j in range(first,idx):
    t=ent(j)[0]&0xfffff; acc+=(t-prev)&0xfffff; prev=t; T[j]=acc
frames=[]; cur=None
for j in range(first,idx):
    e=ent(j)
    if e[4]==0xfc1bec0f and (e[5]>>12)&0xf==0:
        cur=[T[j],[]]; frames.append(cur)
    if cur:
        if e[4] in (0xfc1bec0f,): cur[1].append(('C',e[5]&0xffff))
        elif e[4]==0xfc231323: cur[1].append(('T',e[5],e[6]))
        elif e[4]==0xfc1bd4e3: cur[1].append(('D',e[5],e[6]))
        elif e[4] in (0xfc414d41,0xfc35b5e9): cur[1].append((hex(e[4])[-4:],e[5],e[6]))
        elif e[4] in (0xfc1bd4ed,0xfc23132d,0xfc414d4b,0xfc35b5f3): pass
        else: cur[1].append(('?',hex(e[4]),e[5],e[6]))
prevsig=None
for t,s in frames[-25:]:
    sig=tuple(s)
    diff='' if prevsig is None else ' '.join(str(x) for x in set(sig)-set(prevsig))
    print('%8.1f n=%3d %s'%((t-T[idx-1])/1e3,len(s),diff[:200]))
    prevsig=sig
