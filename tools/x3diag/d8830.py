import struct,sys
for fn in sys.argv[1:]:
    d=open(fn,'rb').read()
    hd=struct.unpack_from('<8I',d,0)
    o=32+40*160; nent=hd[4]; idx=hd[3]
    E=[struct.unpack_from('<16I',d,o+64*i) for i in range(nent)]
    ents=[E[j&(nent-1)] for j in range(idx-nent,idx)]
    D=[e[0]&0xfffff for e in ents if e[4]==0xfc1bd4e3 and e[5]==0x8830]
    C=[e[0]&0xfffff for e in ents if e[4]==0xfc1bec0f and (e[5]>>12)&0xf==0]
    dd=[((b-a)&0xfffff)/1000 for a,b in zip(D,D[1:])]
    cc=[((b-a)&0xfffff)/1000 for a,b in zip(C,C[1:])]
    vals=set((e[6]) for e in ents if e[4]==0xfc1bd4e3 and e[5]==0x8830)
    print(fn,'n8830',len(D),'vals',vals,'span %.0f ms'%(((D[-1]-D[0])&0xfffff)/1000))
    print('  8830 dt:',' '.join('%.1f'%x for x in dd))
    print('  cmos dt:',' '.join('%.1f'%x for x in cc))
