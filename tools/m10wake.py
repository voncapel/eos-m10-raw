#!/usr/bin/env python3
"""After a power-on: unlock the shooting screen (half-press, set_record, menu x2,
half-press), reinstall the v4 SIO hook, optionally fetch files left by the
previous run.

    m10wake.py [PREFIX]     PREFIX -> download A/M10CINE.LOG, A/LVX3S.BIN to
                            captures/live71/PREFIX_<file>
"""
import os, sys, subprocess
sys.path.insert(0, os.path.dirname(__file__))
from m10ptp import Cam, fmt_msg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'captures', 'live71')


def main(a):
    c = Cam(timeout=20000)
    for code in ['press("shoot_half") sleep(800) release("shoot_half") sleep(500)',
                 'set_record(true) sleep(2500)',
                 'click("menu") sleep(700) click("menu") sleep(700)',
                 'press("shoot_half") sleep(800) release("shoot_half") sleep(1000)']:
        try:
            c.lua(code)
        except Exception as e:
            print('lua err', e)
    r = c.lua('return tostring(get_mode())')
    print('record mode:', r and fmt_msg(r[-1]))
    if a:
        try:                                    # live86: fresh ROMLOG (ImgSens / shutdown reason)
            c.lua('if os.stat("A/ROMLOG.LOG") then os.remove("A/ROMLOG.LOG") end call_event_proc("System.Create") return call_event_proc("GetLogToFile","A/ROMLOG.LOG",1)')
        except Exception as e:
            print('romlog err', e)
        for f in ('M10CINE.LOG', 'LVX3S.BIN', 'LVX3H.BIN', 'ROMLOG.LOG'):
            try:
                c.download('A/' + f, os.path.join(OUT, '%s_%s' % (a[0], f)))
                print('got', f)
            except Exception as e:
                print('no', f, e)
    c.close()
    subprocess.run([sys.executable, os.path.join(HERE, 'm10sio.py'), os.environ.get('M10HOOK', 'install'), '4096', '0x50'])


if __name__ == '__main__':
    main(sys.argv[1:])
