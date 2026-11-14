import struct,sys
d=open(sys.argv[1],'rb').read()
hd=struct.unpack_from('<8I',d,0)
tl_n=hd[2]
print('tl_n =', tl_n)
tl=[struct.unpack_from('<10I',d,32+40*i) for i in range(tl_n)]
t0=tl[0][0]
lb=2260
print(' time_ms  ptr_l     tg     sio    4308(LV)    4108(PR)    6608(R1)    4608(R2)')
for t in tl:
    dt = ((t[0]-t0+0x80000)&0xfffff)-0x80000
    print('%8.2f  %5d  %5d  %6d  %08x  %08x  %08x  %08x' % (
        dt/1000, t[1]//lb, t[2] if t[2]<0x80000000 else t[2]-2**32, t[3], t[6], t[7], t[8], t[9]
    ))
