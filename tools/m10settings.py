#!/usr/bin/env python3
"""live112: snapshot / check the Canon settings that change a REC test, so a run is never made
with a setting silently reset (ISO back to auto after a power cycle, AF, IS...).

    m10settings.py show                 print the current values
    m10settings.py save NAME            store them in tools/settings_NAME.json
    m10settings.py check NAME           compare with NAME; exit code 1 if anything differs

Props (propset 10): 8 AF frame (1 = 1-point, 2 = face/tracking), 12 continuous AF,
141 focus mode (1 = MF), 153 IS mode (2 = off), 157 ISO mode (0 = auto), 165 metering,
276 user Tv, 29 user Av, 281 WB mode, 308 servo AF, 113 display mode.
Note (live109): set_prop(276) over USB does NOT change the exposure sent to the sensor: shutter /
ISO must be set on the camera (dial / menu).  Hence this tool only checks, it never writes.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m10ptp import Cam, fmt_msg

PROPS = {8: 'af_frame', 12: 'cont_af', 141: 'focus_mode', 153: 'is_mode', 157: 'iso_mode',
         165: 'metering', 276: 'user_tv', 29: 'user_av', 281: 'wb_mode', 308: 'servo_af', 113: 'display'}
HERE = os.path.dirname(os.path.abspath(__file__))


def read(c):
    code = 'local r="" for _,p in ipairs({%s}) do r=r..p.."="..tostring(get_prop(p)).." " end ' \
           'return r.."mode="..require"capmode".get_name()' % ','.join(map(str, PROPS))
    s = fmt_msg(c.lua(code)[-1])
    out = {}
    for kv in s.split():
        k, v = kv.split('=')
        out[PROPS[int(k)] if k.isdigit() else k] = v
    return out


def main(a):
    op = a[0] if a else 'show'
    c = Cam()
    try:
        cur = read(c)
    finally:
        c.close()
    if op == 'show':
        print(' '.join('%s=%s' % kv for kv in cur.items()))
    elif op == 'save':
        json.dump(cur, open(os.path.join(HERE, 'settings_%s.json' % a[1]), 'w'), indent=1)
        print('saved', cur)
    elif op == 'check':
        ref = json.load(open(os.path.join(HERE, 'settings_%s.json' % a[1])))
        # live114: the m10x3raw run leaves the camera in VIDEO_STD (Film auto) even when the dial
        # says VIDEO_M, which reports ISO auto (0) instead of the dial ISO. Not a user change.
        ignore = {'mode'} | ({'iso_mode'} if ref.get('mode') != cur.get('mode') else set())
        diff = {k: (ref[k], cur.get(k)) for k in ref if k not in ignore and ref[k] != cur.get(k)}
        if diff:
            print('SETTINGS CHANGED (ref -> now):', ' '.join('%s %s->%s' % (k, r, n) for k, (r, n) in diff.items()))
            sys.exit(1)
        print('settings ok')


if __name__ == '__main__':
    main(sys.argv[1:])
