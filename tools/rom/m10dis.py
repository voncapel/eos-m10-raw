import capstone,struct,sys
D=open(__import__('os').path.join(__import__('os').path.dirname(__file__),'..','..','dumps','M10_110d_ROM_8MB.BIN'),'rb').read(); B=0xfc000000
md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_THUMB)
def dis(a,n=60,stop=True):
  print('=====',hex(a))
  for i,ins in enumerate(md.disasm(D[a-B:a-B+n*4+8],a)):
    s=ins.op_str
    if 'pc,' in s and ins.mnemonic.startswith('ldr') and '#' in s:
        off=int(s.split('#')[1].rstrip(']'),16); lit=((ins.address+4)&~3)+off
        if B<=lit<B+len(D): s+='  ; =%08x'%struct.unpack_from('<I',D,lit-B)[0]
    print(hex(ins.address),ins.mnemonic,s)
    if stop and ((ins.mnemonic.startswith('pop') and 'pc' in s) or (ins.mnemonic in ('b.w','bx') and i>2)): break
    if i>=n: break
