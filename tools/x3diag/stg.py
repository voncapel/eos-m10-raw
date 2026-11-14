import struct,sys
d=open(sys.argv[1],'rb').read()
hd=struct.unpack_from('<8I',d,0)
nent=hd[4]
o=32+40*160+nent*64
stg_arr = [ [struct.unpack_from('<4I',d,o+16*(12*k+s)) for s in range(12)] for k in range(16) ]
print('STG records:')
for k in range(16):
    s0 = stg_arr[k][0]
    s1 = stg_arr[k][1] # gate=0
    s4 = stg_arr[k][4] # PK_ON done
    s5 = stg_arr[k][5] # DMA start
    s6 = stg_arr[k][6] # DMA end
    s7 = stg_arr[k][7] # ch12_stop
    s10 = stg_arr[k][10] # unlock
    print('pass slot %2d: s0_late=%5d us, pk_wait=%4d us, dma_run=%6d us, total=%6d us, tg_end=%d' % (
        k, s0[3], (s4[0]-s1[0])&0xfffff, (s6[0]-s5[0])&0xfffff, (s10[0]-s0[0])&0xfffff, s6[1]
    ))
