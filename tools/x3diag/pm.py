import struct,sys
d=open(sys.argv[1],'rb').read()
hd=struct.unpack_from('<8I',d,0)
nent=hd[4]
o=32+40*160+nent*64+16*12*16
pm = [ struct.unpack_from('<4I',d,o+16*k) for k in range(16) ]
for k in range(16):
    print('slot %2d: first=%.2f ms, last=%.2f ms, maxgap=%.2f ms at line %d' % (
        k, pm[k][0]/1000, pm[k][1]/1000, pm[k][2]/1000, pm[k][3]
    ))
