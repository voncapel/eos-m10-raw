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
def at(raw): return lastT-((lastraw-raw)&0xfffff)
D=[T[j] for j in range(first,idx) if ent(j)[4]==0xfc1bd4e3 and ent(j)[5]==0x8830]
C=[T[j] for j in range(first,idx) if ent(j)[4]==0xfc1bec0f and (ent(j)[5]>>12)&0xf==0]
t0=at(R[0][0])
print('records',n,'span %.1f ms'%((at(R[-1][0])-t0)/1e3))
# activity intervals per channel: periods when the address changes
for c in range(nch):
    acts=[]; st=None; last=None; lastv=None
    for r in R:
        t=at(r[0]); v=r[2+c]
        if lastv is not None and v!=lastv:
            if st is None or t-last>800: 
                if st is not None: acts.append((st,last))
                st=t
            last=t
        lastv=v
    if st is not None: acts.append((st,last))
    if not acts: continue
    # express relative to preceding 8830
    def rel(t):
        dd=[x for x in D if x<=t]; return (t-dd[-1])/1e3 if dd else None
    s=' '.join('[%.1f..%.1f]'%(rel(a) if rel(a) is not None else -99,(b-a)/1e3) for a,b in acts[:10])
    print('%08x n=%2d %s'%(ch[c]-8,len(acts),s))
cm=[(c-max(x for x in D if x<=c))/1e3 for c in C if any(x<=c for x in D)]
print('CMOS0 rel 8830:',' '.join('%.1f'%x for x in cm[:12]))
