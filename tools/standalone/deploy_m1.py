#!/usr/bin/env python3
"""v183 : deploie le shell unifie (m10cine.flt v183 + M10SHELL.LUA) sur la carte.

    deploy_m1.py [--flt builds/v183/m10cine.flt] [--clean] [--usb-ok on|off]
    deploy_m1.py --legacy-m1 [--bpp 10] [--frames 2400] [--test N]   (ancien script M10M1.LUA, r159)
    deploy_m1.py --restore-prev                                        (remet l'ancien M10SHELL.LUA)

Par defaut (shell unifie v182+, work/v182_audit_spec.md C ; v183 : work/v183_rom_af_audit.md) :
  module = builds/v183/m10cine.flt, sinon src/chdk/trunk/modules/.o4/m10cine.flt (derniere compilation),
  sinon builds/v182/m10cine.flt  -> A/CHDK/MODULES/m10cine.flt   (--flt pour une autre version)
  La version reelle est lue dans les chaines du .flt (plus grand "vNNN") et affichee.
  tools/shell/M10SHELL.LUA     -> A/CHDK/SCRIPTS/M10SHELL.LUA  (script autostart unifie)
  builds/M10HUF.BIN (si present), builds/M10HUF12.BIN, builds/M10HUF14.BIN (si present) -> A/
  Le siohook6 est embarque dans le module (hook6_blob) : A/M10SIO6.BIN n'est plus necessaire.
  Nettoyage systematique des fichiers obsoletes qui interfereraient avec le shell :
    A/M10M1.CFG, A/M10RUN.ASY, A/M10X3.CFG (+ A/M10X3.REQ, A/M10X3.ACK, A/M10SH.END avec --clean).
  L'ancien M10SHELL.LUA de la carte est sauvegarde une seule fois en A/CHDK/SCRIPTS/M10SHPRV.LUA.
  --usb-ok on : cree A/M10USB.OK (essais bureau, cable branche : l'USB n'arrete pas le shell) ;
  --usb-ok off : le supprime (usage normal sur batterie).

Chaque fichier envoye est relu octet par octet (SHA1 affiche).
Securite : aucune lecture MMIO 0xC0xxxxxx / 0xD0xxxxxx par PTP (elle fige le boitier) ;
ce script ne lit que des fichiers et des variables Lua.
"""
import os, re, sys, time, argparse, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
from m10ptp import Cam, CMD_EXEC, CMD_STATUS, fmt_msg
import _r157_m1_cut3509 as R

PROJ = os.path.dirname(TOOLS)
BUILDS = os.path.join(PROJ, 'builds')
FLT_CANDIDATES = [os.path.join(BUILDS, 'v183', 'm10cine.flt'),
                  os.path.join(PROJ, 'src', 'chdk', 'trunk', 'modules', '.o4', 'm10cine.flt'),
                  os.path.join(BUILDS, 'v182', 'm10cine.flt')]
FLT_DEFAULT = next((p for p in FLT_CANDIDATES if os.path.exists(p)), FLT_CANDIDATES[0])
IPC_MIN = 182   # IPC RAM hook+0x220/0x224 (M10SHELL.LUA) depuis v182
SHELL_LOCAL = os.path.join(TOOLS, 'shell', 'M10SHELL.LUA')
SHELL_CARD = 'A/CHDK/SCRIPTS/M10SHELL.LUA'
SHELL_PREV = 'A/CHDK/SCRIPTS/M10SHPRV.LUA'
OBSOLETE = ['A/M10M1.CFG', 'A/M10RUN.ASY', 'A/M10X3.CFG']
OBSOLETE_CLEAN = OBSOLETE + ['A/M10X3.REQ', 'A/M10X3.ACK', 'A/M10SH.END', 'A/M10SH.CFG']
OUT = os.path.join(PROJ, 'captures', 'live159')

# ancien deploiement r159 (M10M1.LUA autonome)
LEGACY_FILES = [
    (os.path.join(BUILDS, 'v181c', 'm10cine.flt'), 'A/CHDK/MODULES/m10cine.flt'),
    (os.path.join(BUILDS, 'M10HUF12.BIN'), 'A/M10HUF12.BIN'),
    (os.path.join(TOOLS, 'siohook', 'siohook6.bin'), 'A/M10SIO6.BIN'),
    (os.path.join(HERE, 'M10M1.LUA'), 'A/CHDK/SCRIPTS/M10M1.LUA'),
]


def flt_version(path):
    """Plus grand marqueur "vNNN[x]" des chaines du module (slog), ex. (183, 'v183'). (0, '?') si absent."""
    best = (0, '?')
    for m in re.finditer(rb'(?<![0-9A-Za-z])v(1[0-9]{2})([a-z]?)(?![0-9A-Za-z])', open(path, 'rb').read()):
        n = int(m.group(1))
        if n > best[0]:
            best = (n, m.group(0).decode())
    return best


def card_exists(c, path):
    return R.lua_i(c, 'return os.stat("%s") and 1 or 0' % path) == 1


def card_remove(c, path):
    if card_exists(c, path):
        c.lua('os.remove("%s")' % path)
        print('  supprime %s' % path)


def put(c, local, remote):
    c.upload(local, remote)
    tmp = '/tmp/m10_readback.bin'
    if os.path.exists(tmp):
        os.remove(tmp)
    c.download(remote, tmp)
    a, b = open(local, 'rb').read(), open(tmp, 'rb').read()
    assert a == b, 'relecture differente : %s (%d o envoyes, %d relus)' % (remote, len(a), len(b))
    print('  %-30s %7d o  sha1 %s' % (remote, len(a), hashlib.sha1(a).hexdigest()[:12]))


def cfg_text(bpp, frames, usb_ok):
    src = open(os.path.join(HERE, 'M10M1.CFG')).read().splitlines()
    out = []
    for l in src:
        k = l.split('=')[0].strip()
        if k == 'bpp': l = 'bpp=%d' % bpp
        elif k == 'frames': l = 'frames=%d          # plafond ; demi-appui = STOP' % frames
        elif k == 'usb_ok': l = 'usb_ok=%d' % usb_ok
        out.append(l)
    return '\n'.join(out) + '\n'


def backup_shell(c):
    """Sauvegarde une seule fois l'autostart de la carte s'il n'est pas deja le shell unifie (v182+)."""
    if not card_exists(c, SHELL_CARD) or card_exists(c, SHELL_PREV):
        return
    c.download(SHELL_CARD, '/tmp/m10_prev_shell.lua')
    if re.search(rb'shell unifie \(v1[89][0-9]', open('/tmp/m10_prev_shell.lua', 'rb').read()):
        return
    put(c, '/tmp/m10_prev_shell.lua', SHELL_PREV)
    print('  sauvegarde ancien autostart -> %s' % SHELL_PREV)


def deploy_unified(c, a):
    flt = os.path.abspath(a.flt)
    assert os.path.exists(flt), 'module absent : %s (compiler v183 ou --flt)' % flt
    ver, tag = flt_version(flt)
    print('module %s : %s (%d o, sha1 %s)' % (os.path.relpath(flt, PROJ), tag, os.path.getsize(flt),
                                            hashlib.sha1(open(flt, 'rb').read()).hexdigest()[:12]))
    assert os.path.exists(SHELL_LOCAL), SHELL_LOCAL
    files = [(flt, 'A/CHDK/MODULES/m10cine.flt'), (SHELL_LOCAL, SHELL_CARD)]
    huf12 = os.path.join(BUILDS, 'M10HUF12.BIN')
    assert os.path.exists(huf12), huf12
    files.append((huf12, 'A/M10HUF12.BIN'))
    for name in ('M10HUF.BIN', 'M10HUF14.BIN'):
        p = os.path.join(BUILDS, name)
        if os.path.exists(p):
            files.append((p, 'A/' + name))
        elif not card_exists(c, 'A/' + name):
            print('  ATTENTION : A/%s absent (ni local ni carte) -> Huffman par defaut JpCore pour ce bpp' % name)
    if ver < IPC_MIN:
        print('  ATTENTION : module %s (%s) : l\'IPC RAM (hook+0x220/0x224) exige v%d+ ; '
              'le shell basculera sur le protocole fichiers A/M10X3.REQ' % (flt, tag, IPC_MIN))

    print('nettoyage :')
    for p in (OBSOLETE_CLEAN if a.clean else OBSOLETE):
        card_remove(c, p)
    backup_shell(c)
    print('upload :')
    for l, r in files:
        put(c, l, r)
    if a.usb_ok == 'on':
        open('/tmp/M10USB.OK', 'w').write('1\n')
        put(c, '/tmp/M10USB.OK', 'A/M10USB.OK')
        print('  A/M10USB.OK cree : le shell tourne cable branche (essais bureau)')
    elif a.usb_ok == 'off':
        card_remove(c, 'A/M10USB.OK')
    elif card_exists(c, 'A/M10USB.OK'):
        print('  NOTE : A/M10USB.OK present sur la carte (shell actif meme cable branche ; --usb-ok off pour retirer)')
    print('shell unifie (module %s) installe comme script autostart (%s).' % (tag, SHELL_CARD))
    print('Verifier dans CHDK : Script > Autostart = Always, script = M10SHELL.LUA, Lua native calls = ON.')


def deploy_legacy(c, a):
    files = list(LEGACY_FILES)
    for l, r in files:
        assert os.path.exists(l), l
    if os.path.exists(os.path.join(BUILDS, 'M10HUF.BIN')):
        files.append((os.path.join(BUILDS, 'M10HUF.BIN'), 'A/M10HUF.BIN'))
    elif not card_exists(c, 'A/M10HUF.BIN'):
        print('  ATTENTION : A/M10HUF.BIN absent (table 10 b) -> Huffman par defaut JpCore')
    print('upload (legacy M10M1) :')
    for l, r in files:
        put(c, l, r)
    open('/tmp/M10M1.CFG', 'w').write(cfg_text(a.bpp, a.frames, 0))
    put(c, '/tmp/M10M1.CFG', 'A/M10M1.CFG')
    backup_shell(c)
    put(c, os.path.join(HERE, 'M10M1.LUA'), SHELL_CARD)
    print('M10M1 (legacy r159) installe comme script autostart (M10SHELL.LUA).')

    if a.test:
        os.makedirs(OUT, exist_ok=True)
        open('/tmp/M10M1.CFG', 'w').write(cfg_text(a.bpp, a.test, 1))
        put(c, '/tmp/M10M1.CFG', 'A/M10M1.CFG')
        c.lua('os.remove("A/M10M1.LOG")')
        code = open(os.path.join(HERE, 'M10M1.LUA')).read()
        # declencheur simule : un thread ne peut pas presser pendant que le script tourne -> on
        # remplace is_pressed("shoot_full") par un declenchement automatique unique.
        code = code.replace('if is_pressed("shoot_full") then',
                            'if n == 0 then').replace(
                            'log("PRET (" .. n .. " prises)")', 'log("PRET (" .. n .. " prises)") break')
        c.chdk(CMD_EXEC, [0], (code + '\0').encode())
        t0 = time.time()
        while time.time() - t0 < 120:
            time.sleep(1.0)
            st = c.chdk(CMD_STATUS)[0]
            sv = st[0] if isinstance(st, (list, tuple)) else st
            if (sv & 1) == 0:
                break
        print('script termine en %.0f s' % (time.time() - t0))
        c.download('A/M10M1.LOG', os.path.join(OUT, 'M10M1_test.LOG'))
        print(open(os.path.join(OUT, 'M10M1_test.LOG'), errors='replace').read()[-3000:])
        name = fmt_msg(c.lua('for n=9999,1,-1 do local f=string.format("A/M1_%04d.MLV",n) if os.stat(f) then return f end end return ""')[-1])
        if name:
            loc = os.path.join(OUT, os.path.basename(name))
            c.download(name, loc)
            import m10cut
            print(m10cut.summary(loc)[0])
        open('/tmp/M10M1.CFG', 'w').write(cfg_text(a.bpp, a.frames, 0))
        put(c, '/tmp/M10M1.CFG', 'A/M10M1.CFG')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--flt', default=FLT_DEFAULT, help='module a deployer (defaut %s)' % os.path.relpath(FLT_DEFAULT, PROJ))
    ap.add_argument('--clean', action='store_true', help='supprime aussi REQ/ACK/END/M10SH.CFG residuels')
    ap.add_argument('--usb-ok', choices=('on', 'off'), help='cree / supprime A/M10USB.OK')
    ap.add_argument('--legacy-m1', action='store_true', help='ancien deploiement M10M1.LUA (r159, v181c)')
    ap.add_argument('--bpp', type=int, default=10, help='(legacy) 10 ou 12')
    ap.add_argument('--frames', type=int, default=2400, help='(legacy) plafond de trames')
    ap.add_argument('--test', type=int, default=0, help='(legacy) prise de validation de N trames, cable branche')
    ap.add_argument('--restore-prev', '--restore-x3', dest='restore_prev', action='store_true',
                    help='remet l\'autostart sauvegarde (M10SHPRV.LUA, ou M10SHX3.LUA des deploiements r159)')
    a = ap.parse_args()
    R.drain_ep_in()
    c = Cam(timeout=60000)
    try:
        vb = R.lua_i(c, 'return get_vbatt()')
        print('vbatt %d mV' % vb)
        if a.restore_prev:
            src = SHELL_PREV if card_exists(c, SHELL_PREV) else 'A/CHDK/SCRIPTS/M10SHX3.LUA'
            assert card_exists(c, src), 'pas de sauvegarde (M10SHPRV.LUA / M10SHX3.LUA)'
            c.download(src, '/tmp/m10_prev_shell.lua')
            put(c, '/tmp/m10_prev_shell.lua', SHELL_CARD)
            print('autostart restaure depuis %s' % src)
            return
        if a.legacy_m1:
            deploy_legacy(c, a)
        else:
            deploy_unified(c, a)
    finally:
        c.close()


if __name__ == '__main__':
    main()
