#!/usr/bin/env python3
"""probe55 LVM.BIN: map every line of each pass onto frame lines of passes 0+1 (correlation, 7 bit phases, OB-column alignment)."""
import sys,struct,numpy as np
sys.path.insert(0,'tools')
from m10lvn import unpack14
d=open('captures/probe55/LVM.BIN','rb').read()
n=struct.calcsize('<8s9I8I8I8I8I96I96I'); raw=d[n:]
W,L,LB=1808,256,3164
streams={}
for k in range(8):
    seg=raw[k*L*LB:(k+1)*L*LB]
    streams[k]=[unpack14(seg,(len(seg)-ph-8)*8//14,ph).astype(np.float32) for ph in (0,4,8,12,16,20,24)]
ref=streams[0][0][:255*W].reshape(255,W); ref2=streams[1][0][:255*W].reshape(255,W)
R=np.vstack([ref,ref2])[:,100:1800:2]
R=R-R.mean(1,keepdims=True); R/=np.linalg.norm(R,axis=1,keepdims=True)+1e-6
def col_ob(s):  # position of dark OB columns (36 wide) modulo W
    nl=len(s)//W; M=s[:nl*W].reshape(nl,W); M=np.median(M,0)
    sc=np.convolve(np.r_[M,M[:40]],np.ones(30)/30,'valid')[:W]; return int(np.argmin(sc))
for k in range(8):
    o=col_ob(streams[k][0])  # OB column offset independent of phase? use phase 0 approx
    out=[]
    nl=(len(streams[k][0])-o)//W
    for i in range(nl):
        best=(-1,None,None)
        for pi,s in enumerate(streams[k]):
            # OB pos shifts by bytes: sample offset of phase pi is 4*pi*8/14 samples approx; search +-3
            for dlt in range(-4,1):
                a=o+i*W+dlt
                if a<0 or a+W>len(s): continue
                v=s[a+100:a+1800:2]; m=v.mean()
                if m<2300: 
                    if best[0]<0: best=(0,'B',pi)
                    continue
                v=v-m; nv=np.linalg.norm(v)
                c=R@(v/nv); j=int(np.argmax(c))
                if c[j]>best[0]: best=(c[j],j,pi)
        out.append(best)
    # summarize: segments of consecutive matched lines
    segs=[];cur=None
    for i,(c,j,pi) in enumerate(out):
        if j=='B': t=('B',None)
        elif j is None or c<0.85: t=('?',None)
        else: t=('n',pi)
        if cur and cur[0]==t:
            cur[2]=i; 
            if t[0]=='n': cur[4]=j
        else:
            if cur: segs.append(cur)
            cur=[t,i,i,(j if t[0]=='n' else None),(j if t[0]=='n' else None)]
    segs.append(cur)
    s=' '.join(('%s[%d-%d]'%(g[0][0],g[1],g[2]) + ('ph%d:%s-%s'%(g[0][1]*4,g[3],g[4]) if g[0][0]=='n' else '')) for g in segs if g[2]-g[1]>=2 or g[0][0]=='n')
    print(k,'ob',o,s)
