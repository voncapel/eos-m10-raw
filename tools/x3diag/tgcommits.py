import sys
sys.path.insert(0,'tools')
from m10siodec import load, writes
def ig(g):
  n=0
  while g: n^=g; g>>=1
  return n
for fn in sys.argv[1:]:
  try: W=writes(load(fn))
  except Exception as e: print(fn,e); continue
  # find commits: TG write 8000=0
  print('=====',fn,len(W))
  i=0
  while i<len(W):
    w=W[i]
    if w[2]=='TG' and w[3]==0x8000 and w[4]==0:
      seq=[]; j=i
      while j<len(W) and len(seq)<400:
        if W[j][2]=='TG': seq.append((W[j][3],W[j][4]))
        if W[j][2]=='TG' and W[j][3]==0x8047 and W[j][4]==0x550: break
        j+=1
      # also the CMOS state at that time
      print('commit @%d: %d TG writes'%(w[0],len(seq)))
      print('  '+' '.join('%04x=%x'%s for s in seq))
      i=j
    i+=1
