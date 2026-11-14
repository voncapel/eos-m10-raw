#!/usr/bin/env python3
"""Snapshot sensor/TG/head state (RAM + engine shadows) -> JSON. m10state.py TAG"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam
SH = [0xc0f06000, 0xc0f06004, 0xc0f06008, 0xc0f0600c, 0xc0f06010, 0xc0f06014, 0xc0f06018,
      0xc0f0601c, 0xc0f06020, 0xc0f06024, 0xc0f06028, 0xc0f0602c, 0xc0f06030,
      0xc0f06800, 0xc0f06804, 0xc0f06808, 0xc0f0680c, 0xc0f06810, 0xc0f06824, 0xc0f06828,
      0xc0f0682c, 0xc0f06830, 0xc0f06834, 0xc0f06838, 0xc0f0683c,
      0xc0f07048, 0xc0f0705c, 0xc0f07064, 0xc0f07150, 0xc0f07154, 0xc0f0713c,
      0xc0f37014, 0xc0f37074, 0xc0f08090, 0xc0f08094, 0xc0f37270, 0xc0f37274]
RAM = {'dss': (0x28714, 16), 'cmos': (0x2cca8, 48), 'cmosdrv': (0xe42c, 16),
       'tg': (0xe664, 32), 'tgw': (0xe67c, 16), 'cds': (0x2cc6c, 16), 'dfe': (0x2cc18, 24),
       'head': (0xfa68, 16), 'e558': (0xe558, 4), 'dssgeo': (0x1beb5c, 4)}
c = Cam()
st = {'sh': {'%08x' % r: '%08x' % c.shadow(r) for r in SH}}
for k, (a, n) in RAM.items():
    st[k] = ['%08x' % v for v in c.peek(a, n)]
c.close()
tag = sys.argv[1] if len(sys.argv) > 1 else 'state'
fn = os.path.join(os.path.dirname(__file__), '..', 'captures', 'live63', 'state_%s.json' % tag)
json.dump(st, open(fn, 'w'), indent=1)
print(json.dumps(st)[:3000])
