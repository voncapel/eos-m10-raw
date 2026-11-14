#!/usr/bin/env python3
"""Read A/M10CINE.VID written by m10cine (v10 = M10VID01, v11 = M10VID02):
timing report, extract LJ92 frames, optionally decode them with lj92d
(tools/lj92d.c, built at /tmp/ljc/lj92d) and write DNGs.

  m10vid.py M10CINE.VID [--out DIR] [--dng N]   (--dng: decode first N frames)
"""
import argparse, os, struct, subprocess, sys

V1_HDR = '<8s' + 'I' * 21          # v10 vid_hdr, 92 bytes
V1_FIELDS = ('w h bits nf_planned fb_in nf_done total_ms sum_cap sum_enc sum_wr '
             'cap_min cap_max enc_min enc_max wr_min wr_max real pipe2 pipe3 p0 p1').split()
V2_FIELDS = ('w h bits nf_planned fb_in nf_done nf_written total_ms prod_ms sum_cap sum_enc sum_wr '
             'cap_min cap_max enc_min enc_max wr_min wr_max real prod nslot max_backlog werr '
             'nphase_nz ph_us_max wait_ms hdr_blk rec_blk').split()
V2_NFMAX = 240


def parse_v1(d):
    v = struct.unpack_from(V1_HDR, d)
    h = dict(zip(V1_FIELDS, v[1:]))
    off, frames = struct.calcsize(V1_HDR), []
    while off + 20 <= len(d) and d[off:off + 4] == b'VIDF':
        sz, cap, enc, ph = struct.unpack_from('<IIII', d, off + 4)
        frames.append(dict(off=off + 20, sz=sz, cap=cap, enc=enc, ph=ph & 0xff, phus=ph >> 8))
        off += 20 + sz
    return h, frames


def parse_v2(d):
    fmt = '<8s%dI' % len(V2_FIELDS)
    v = struct.unpack_from(fmt, d)
    h = dict(zip(V2_FIELDS, v[1:]))
    o = struct.calcsize(fmt)
    h['tick_ms'] = struct.unpack_from('<%dI' % V2_NFMAX, d, o)
    h['wr_us'] = struct.unpack_from('<%dI' % V2_NFMAX, d, o + 4 * V2_NFMAX)
    ext = struct.unpack_from('<6I', d, o + 8 * V2_NFMAX)      # v12 fields (0 in v11)
    h.update(zip('version nf_encoded cap_wait_ms ndiff nrestored enc_st'.split(), ext))
    o13 = o + 8 * V2_NFMAX + 24                                # v13 arrays (0 before)
    if o13 + 8 * V2_NFMAX <= h['hdr_blk']:
        h['ivl_us'] = struct.unpack_from('<%dI' % V2_NFMAX, d, o13)
        h['stage_us'] = struct.unpack_from('<%dI' % V2_NFMAX, d, o13 + 4 * V2_NFMAX)
        o14 = o13 + 8 * V2_NFMAX
        if o14 + 12 <= h['hdr_blk']:
            h['prealloc_ms'], h['steady_ivl_us'], h['steady_n'] = struct.unpack_from('<3I', d, o14)
    hb, rb = h['hdr_blk'] or 2048, h['rec_blk'] or 512
    off, frames = hb, []
    while off + rb <= len(d) and d[off:off + 4] == b'VIDF':
        sz, cap, enc, ph, phus, tick, idx = struct.unpack_from('<7I', d, off + 4)
        frames.append(dict(off=off + rb, sz=sz, cap=cap, enc=enc, ph=ph, phus=phus, tick=tick, idx=idx))
        off += rb + ((sz + rb - 1) // rb) * rb
    return h, frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('vid')
    ap.add_argument('--out', default=None)
    ap.add_argument('--dng', type=int, default=0)
    a = ap.parse_args()
    d = open(a.vid, 'rb').read()
    magic = d[:8]
    if magic == b'M10VID01':
        h, frames = parse_v1(d)
    elif magic == b'M10VID02':
        h, frames = parse_v2(d)
    else:
        sys.exit('format inconnu %r' % magic)
    nd = h['nf_done'] or 1
    print('%s fenetre %dx%d %d bits, %d/%d trames, %d ms' % (
        magic.decode(), h['w'], h['h'], h['bits'], h['nf_done'], h['nf_planned'], h['total_ms']))
    nw = h.get('nf_written', h['nf_done']) or 1
    for k in ('cap', 'enc', 'wr'):
        div = nw if k == 'wr' else nd
        print('  %-3s moy %6d us  min %6d  max %6d' % (k, h['sum_' + k] // div, h[k + '_min'], h[k + '_max']))
    if magic == b'M10VID01':
        print('  reel %.2f i/s, pipeline 2 taches %.2f i/s, 3 taches %.2f i/s' % (
            h['real'] / 100, h['pipe2'] / 100, h['pipe3'] / 100))
    else:
        print('  ecrites %d, reel %.2f i/s (fin d\'ecriture comprise), production %.2f i/s en %d ms' % (
            h['nf_written'], h['real'] / 100, h['prod'] / 100, h['prod_ms']))
        print('  attente de slot libre %d ms, file max %d/%d, erreur ecriture %d, recherche phase max %d us' % (
            h['wait_ms'], h['max_backlog'], h['nslot'], h['werr'], h['ph_us_max']))
        if h.get('version', 0) >= 13:
            n = h['nf_done']
            iv = [x for x in h['ivl_us'][1:n] if x]
            st = [x for x in h['stage_us'][:n] if x]
            if iv:
                print('  intervalle capture (us) : moy %d min %d max %d -> %.2f i/s' % (
                    sum(iv) / len(iv), min(iv), max(iv), 1e6 / (sum(iv) / len(iv))))
            if len(iv) > 12:
                r = iv[9:]
                print('  regime (trames 10+) : %.2f i/s, %d/%d intervalles > 41,67 ms' % (
                    1e6 / (sum(r) / len(r)), sum(1 for x in r if x > 41667), len(r)))
            if h.get('steady_ivl_us'):
                print('  v14 : regime calcule a bord %.2f i/s, pre-allocation %d ms' % (
                    1e6 / h['steady_ivl_us'], h['prealloc_ms']))
            if st:
                print('  etage compression (us) : moy %d min %d max %d' % (sum(st) / len(st), min(st), max(st)))
        if h.get('version', 0) >= 12:
            print('  v%d : %d encodees, capture en attente %d ms, registres modifies %d / restaures %d, statut enc %#x' % (
                h['version'], h['nf_encoded'], h['cap_wait_ms'], h['ndiff'], h['nrestored'], h['enc_st']))
        t = [x for x in h['tick_ms'][:h['nf_done']]]
        if len(t) > 1:
            dt = [t[i + 1] - t[i] for i in range(len(t) - 1)]
            print('  intervalle entre trames (ms) : moy %.1f min %d max %d' % (sum(dt) / len(dt), min(dt), max(dt)))

    tot = sum(f['sz'] for f in frames)
    if frames:
        print('  %d frames read, avg %.0f KB/frame, ratio %.2f:1, %.1f MB/s at 24 fps' % (
            len(frames), tot / len(frames) / 1024, h['fb_in'] * len(frames) / tot, tot / len(frames) * 24 / 1e6))
        print('  phases (octets) :', ' '.join(str(f['ph']) for f in frames))
        print('  tailles (Ko) :', ' '.join(str(f['sz'] // 1024) for f in frames))
    out = a.out or os.path.splitext(a.vid)[0] + '_frames'
    os.makedirs(out, exist_ok=True)
    here = os.path.dirname(os.path.abspath(__file__))
    for i, f in enumerate(frames):
        p = os.path.join(out, 'f%03d.ljpg' % i)
        open(p, 'wb').write(d[f['off']:f['off'] + f['sz']])
        if i < a.dng:
            u = p[:-5] + '.u16'
            subprocess.run(['/tmp/ljc/lj92d', p, u], check=True, stderr=subprocess.DEVNULL)
            sys.path.insert(0, here)
            import numpy as np
            from m10raw2dng import write_dng, gray_world_neutral
            img = np.fromfile(u, '<u2').reshape(h['h'], h['w'])
            write_dng(p[:-5] + '.dng', img, gray_world_neutral(img))
            os.remove(u)
    print('  trames ->', out)


if __name__ == '__main__':
    main()
