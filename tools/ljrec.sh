#!/bin/bash
# ljrec.sh TAG N WMS XO CHF [extra env]
# Film 3x3 REC test driver (live110-114). Historical: the current mode is the x5 magnifier shell.
cd "$(dirname "$0")"
if [ -n "$SETREF" ]; then timeout 30 python3 m10settings.py check $SETREF || { echo "abort: settings differ from $SETREF"; exit 1; }; fi
timeout 30 python3 -c "from m10ptp import Cam; c=Cam(); c.lua('press(\"shoot_half\") sleep(400) release(\"shoot_half\") sleep(600)')" >/dev/null 2>&1
timeout 60 python3 m10hetrap.py install >/dev/null 2>&1
UNPK=0 CSH=0 ENC=11 FILMMODE=${FILMMODE:-VIDEO_STD} TAG=$1 NORAW=1 USBTMO=600000 timeout 500 python3 m10x3raw.py film $2 1184 10 $3 0 ${FL:-0x21800980} ${5:-0} $4 ${LO:-5000} ${HI:-7500} 6 0 0 12 4 ${DC:-99} 2>&1 | grep -E "failed"
L=../captures/live71/$1_M10CINE.LOG
strings $L 2>/dev/null | awk '/v101 LJ raw/{n=NR} {a[NR]=$0} END{for(i=n;i<=NR;i++) print a[i]}' | grep -E "REC frames|LJ encoded|size avg|enc us|he_n|written=|ok=" | tr '\n' ' '; echo
python3 - $1 <<'PY'
import sys,struct,numpy as np,os
f='../captures/live71/%s_M10X3T.BIN'%sys.argv[1]
if os.path.exists(f):
    d=open(f,'rb').read(); n=struct.unpack_from('<I',d)[0]
    if n>1:
        t=np.array(struct.unpack_from('<%dI'%n,d,4)); dt=np.diff(t); print(n,'frames fps %.2f'%((n-1)*1000/max(1,t[-1]-t[0])),'dt>50:',(dt>50).sum())
PY
