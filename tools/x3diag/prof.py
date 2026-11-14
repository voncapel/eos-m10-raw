import struct,sys
p=sys.argv[1]
d=open(p+'LVX3S.BIN','rb').read()
hd=struct.unpack_from('<8I',d,0)
o=32+40*160+hd[4]*64+16*12*4*4
pm=struct.unpack_from('<64I',d,o)
h=open(p+'LVX3.BIN','rb').read()
w,lines,lb,npass,ndone=struct.unpack_from('<5I',h,8)
oo=8+20+24+12
dt=struct.unpack_from('<16I',h,oo); st=struct.unpack_from('<16I',h,oo+64); ep=struct.unpack_from('<16I',h,oo+128); tk=struct.unpack_from('<16I',h,oo+192)
print('stalled',hd[1],'ndone',ndone)
for i in sorted(range(16),key=lambda i:tk[i]):
    print('%2d dt=%6d st=%d end=%4d tick=%d'%(i,dt[i],st[i],ep[i]//lb,tk[i]), 'first=%.1f last=%.1f maxgap=%.2f at=%d'%(pm[4*i]/1e3,pm[4*i+1]/1e3,pm[4*i+2]/1e3,pm[4*i+3]))
