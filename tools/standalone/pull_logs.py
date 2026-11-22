#!/usr/bin/env python3
"""v182 : rapatrie les journaux de diagnostic du shell autonome (essais T1/T2/T3, spec A.6).

    pull_logs.py [--no-romlog] [--mlv N] [--with-mlv] [--out DIR]

1. Dump frais de A/ROMLOG.LOG (methode validee sur M10, cf. tools/m10wake.py) :
     os.remove("A/ROMLOG.LOG") ; call_event_proc("System.Create") ;
     call_event_proc("GetLogToFile", "A/ROMLOG.LOG", 1)
   (--no-romlog : garde le ROMLOG.LOG deja present sur la carte, sans redumper).
2. Copie dans captures/diag_<AAAAMMJJ_HHMMSS>/ : A/ROMLOG.LOG, A/M10M1.LOG, A/M10CINE.LOG,
   et les .LOG des N dernieres prises A/M1_*.MLV / A/M10_*.MLV (MLV eux-memes avec --with-mlv).
3. Affiche l'en-tete de ROMLOG.LOG, les lignes ASSERT / Exception eventuelles, et la fin des journaux.

Lecture seule cote boitier (hors dump ROMLOG) : aucun peek MMIO 0xC0xxxxxx / 0xD0xxxxxx par PTP.
"""
import os, sys, re, time, argparse
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from m10ptp import Cam, fmt_msg
import _r157_m1_cut3509 as R

PROJ = os.path.dirname(TOOLS)
FIXED = ['ROMLOG.LOG', 'M10M1.LOG', 'M10CINE.LOG']
PAT_TAKE = re.compile(r'^(M1|M10)_(\d{4})\.(MLV|LOG)$', re.I)
PAT_ALERT = re.compile(r'assert|exception|abort|err(or)?\b|shutdown|wbinteg', re.I)

LUA_LIST = r'''
local t = os.listdir("A/") or {}
local out = {}
for _, n in ipairs(t) do
  local u = string.upper(n)
  if string.find(u, "^M10?_%d%d%d%d%.") then
    local s = os.stat("A/" .. n)
    if s and not s.is_dir then table.insert(out, n .. ":" .. tostring(s.size) .. ":" .. tostring(s.mtime)) end
  end
end
return table.concat(out, ";")
'''


def lua_ret(c, code, wait=30.0):
    msgs = c.lua(code, wait=wait)
    for m in msgs:
        if m[0] == 'err':
            raise RuntimeError('erreur Lua : %s' % fmt_msg(m))
    rets = [m for m in msgs if m[0] == 'ret']
    return fmt_msg(rets[-1]) if rets else None


def card_size(c, path):
    v = lua_ret(c, 'local s = os.stat("%s") return s and s.size or -1' % path)
    return v if isinstance(v, int) else -1


def dump_romlog(c):
    t0 = time.time()
    r = lua_ret(c, 'if os.stat("A/ROMLOG.LOG") then os.remove("A/ROMLOG.LOG") end '
                   'call_event_proc("System.Create") '
                   'return call_event_proc("GetLogToFile","A/ROMLOG.LOG",1)', wait=60.0)
    print('GetLogToFile -> %r (%.1f s)' % (r, time.time() - t0))


def fetch(c, remote, local):
    n = card_size(c, remote)
    if n < 0:
        print('  absent  %s' % remote)
        return False
    c.download(remote, local)
    print('  %-22s %9d o  -> %s' % (remote, os.path.getsize(local), os.path.relpath(local, PROJ)))
    return True


def show_romlog(path, head=25):
    data = open(path, 'rb').read().decode('latin-1', errors='replace').splitlines()
    print('\n===== ROMLOG.LOG : en-tete (%d lignes au total) =====' % len(data))
    for l in data[:head]:
        print('  ' + l)
    alerts = [(i, l) for i, l in enumerate(data) if PAT_ALERT.search(l)]
    asserts = [(i, l) for i, l in alerts if re.search(r'assert', l, re.I)]
    if asserts:
        print('===== ASSERT (%d) : cause logicielle =====' % len(asserts))
        for i, l in asserts[:20]:
            print('  %5d: %s' % (i + 1, l))
    else:
        print('===== aucune ligne ASSERT : plutot alimentation / APO (spec A.6) =====')
    others = [(i, l) for i, l in alerts if (i, l) not in asserts]
    if others:
        print('----- autres lignes notables (%d, 15 dernieres) -----' % len(others))
        for i, l in others[-15:]:
            print('  %5d: %s' % (i + 1, l))


def show_tail(path, n=20):
    data = open(path, 'rb').read().decode('latin-1', errors='replace').splitlines()
    print('\n===== %s : %d dernieres lignes (%d au total) =====' % (os.path.basename(path), min(n, len(data)), len(data)))
    for l in data[-n:]:
        print('  ' + l)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-romlog', action='store_true', help='ne pas redumper ROMLOG.LOG')
    ap.add_argument('--mlv', type=int, default=3, help='nombre de dernieres prises listees / rapatriees (.LOG)')
    ap.add_argument('--with-mlv', action='store_true', help='rapatrie aussi les .MLV (gros fichiers)')
    ap.add_argument('--out', help='dossier de sortie (defaut captures/diag_<timestamp>)')
    ap.add_argument('--tail', type=int, default=20)
    a = ap.parse_args()

    out = a.out or os.path.join(PROJ, 'captures', 'diag_' + time.strftime('%Y%m%d_%H%M%S'))
    os.makedirs(out, exist_ok=True)
    R.drain_ep_in()
    c = Cam(timeout=60000)
    got = []
    try:
        vb = lua_ret(c, 'return get_vbatt()')
        usb = lua_ret(c, 'return get_usb_power(1)')
        print('vbatt %s mV, usb %s' % (vb, usb))
        if not a.no_romlog:
            try:
                dump_romlog(c)
            except Exception as e:
                print('dump ROMLOG echoue : %s (copie de l\'existant)' % e)
        print('rapatriement -> %s' % os.path.relpath(out, PROJ))
        for f in FIXED:
            loc = os.path.join(out, f)
            if fetch(c, 'A/' + f, loc):
                got.append(loc)

        lst = lua_ret(c, LUA_LIST) or ''
        takes = {}
        for ent in filter(None, lst.split(';')):
            name, size, mtime = ent.rsplit(':', 2)
            m = PAT_TAKE.match(name)
            if not m:
                continue
            key = (int(mtime) if mtime.lstrip('-').isdigit() else 0, m.group(1).upper(), int(m.group(2)))
            takes.setdefault(key, {})[m.group(3).upper()] = (name, int(size))
        last = sorted(takes)[-a.mlv:] if a.mlv > 0 else []
        print('\ndernieres prises (%d sur %d) :' % (len(last), len(takes)))
        for k in last:
            ent = takes[k]
            mlv = ent.get('MLV')
            print('  %s_%04d  MLV %s  LOG %s  %s' % (k[1], k[2],
                  ('%d o' % mlv[1]) if mlv else '-',
                  ('%d o' % ent['LOG'][1]) if 'LOG' in ent else '-',
                  time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(k[0])) if k[0] else ''))
            if 'LOG' in ent:
                loc = os.path.join(out, ent['LOG'][0])
                if fetch(c, 'A/' + ent['LOG'][0], loc):
                    got.append(loc)
            if a.with_mlv and mlv:
                fetch(c, 'A/' + mlv[0], os.path.join(out, mlv[0]))
    finally:
        c.close()

    for p in got:
        if os.path.basename(p) == 'ROMLOG.LOG':
            show_romlog(p)
    for p in got:
        if os.path.basename(p) != 'ROMLOG.LOG':
            show_tail(p, a.tail)
    print('\n-> %s' % out)


if __name__ == '__main__':
    main()
