"""Host unit tests for the EOS M10 module: v167 fixes, shell profiles (v172+ format), MLV chunking and LJ drain."""
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

MODULE_C = Path(__file__).resolve().parent.parent / 'module' / 'm10_cine.c'


def extract_c_block(src, start_marker, end_marker):
    i = src.index(start_marker)
    j = src.index(end_marker, i)
    return src[i:j]


class V167ModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = MODULE_C.read_text()

    def test_sh_recipe_xneed_and_diag_gate(self):
        m = re.search(r'#define\s+SH_RECIPE\s+"([^"\\]+)\\n"', self.src)
        self.assertIsNotNone(m)
        fields = m.group(1).split()
        self.assertGreaterEqual(len(fields), 55)
        self.assertEqual(fields[7], '80000003')   # x_xo: bit 29 (x_diag) clear
        self.assertEqual(fields[11], '1102')      # x_need: reject incomplete short frames
        self.assertEqual(fields[18], '11')        # LJ92 lossless
        self.assertEqual(fields[52], '48')        # 48 MiB EXMEM

        # Verify ea_take(0/2) and hs_take(0/1/2) inside lv_x3 REC loop require x_diag
        rec_block = extract_c_block(self.src, 'if (x_he_n >= x_hbn', 'if (r == 2) { drops++')
        for fn in ('hs_take(1)', 'hs_take(0)', 'ea_take(0)', 'hs_take(2)', 'ea_take(2)'):
            idx = rec_block.index(fn)
            line = rec_block[rec_block.rfind('\n', 0, idx) + 1:rec_block.find('\n', idx)]
            self.assertIn('x_diag', line, f'{fn} must be gated by x_diag: {line}')

        # Verify post-capture tick overwrite skips lj_on frames
        self.assertIn('if (!lj_on && fr < XR_MAX) { xr_slot[fr] = slot; xr_tick[fr] = get_tick_count() - t0; }', self.src)

    def test_profiles_geometry_and_fps_math(self):
        block = extract_c_block(self.src, 'static const sh_prof_t sh_profs[] = {', '};')
        # v185+: { fps, bpp, rsel, kind, fl, per, c0, w, tag, h, lclk, m1_wide }
        #   kind 0 = x5 magnifier (TG line 733), SH_X3 = Film 1x3 (SH_X3LINE 640), SH_M1 = ImgMode 1 (line lclk + 1)
        entries = re.findall(r'\{\s*(\d+),\s*(\d+),\s*(0x[0-9a-fA-F]+|\d+),\s*(\w+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),'
                             r'\s*"([^"]+)",\s*(\d+),\s*(\d+),\s*(\d+)\s*\}', block)
        n_rows = len(re.findall(r'^\s*\{', block, re.M))
        self.assertEqual(len(entries), n_rows, 'a profile row does not match the v185 sh_prof_t layout')
        self.assertEqual(len(entries), 14)
        kinds = {'0': 0, 'SH_X5': 0, 'SH_X3': 1, 'SH_M1': 2}
        self.assertEqual(sum(kinds[e[3]] == 0 for e in entries), 8, 'x5 magnifier profiles')
        self.assertEqual(sum(kinds[e[3]] == 1 for e in entries), 1, 'Film 1x3 profiles')
        self.assertEqual(sum(kinds[e[3]] == 2 for e in entries), 5, 'ImgMode 1 profiles')
        self.assertEqual(kinds[entries[0][3]], 2, 'default profile must be ImgMode 1 1440p')
        self.assertTrue(any(int(e[1]) == 14 and int(e[2], 0) == 0x10 for e in entries), '14-bit HEAD profile missing')
        x3line = int(re.search(r'#define\s+SH_X3LINE\s+(\d+)', self.src).group(1))
        for fps_s, bpp_s, rsel_s, kind_s, fl_s, per_s, c0_s, w_s, tag, h_s, lclk_s, wide_s in entries:
            fps, bpp, fl, per, c0, w = int(fps_s), int(bpp_s), int(fl_s), int(per_s), int(c0_s), int(w_s)
            h, lclk, wide, kind = int(h_s), int(lclk_s), int(wide_s), kinds[kind_s]
            self.assertEqual(w % 16, 0, tag)
            self.assertEqual(c0 % 16 if kind != 1 else c0 % 8, 0, tag)
            if kind == 2:   # ImgMode 1: full sensor window, no c0 offset, explicit frame lines and TG line clock
                self.assertIn(bpp, (10, 12), tag)
                self.assertEqual(c0, 0, tag)
                self.assertIn((w, h, wide), ((1920, 1440, 0), (1728, 1440, 1), (1728, 1800, 1)), tag)
                line = lclk + 1
            else:
                self.assertEqual((h, lclk, wide), (0, 0, 0), tag)
                self.assertIn(bpp, (10, 14) if kind == 0 else (12,), tag)
                self.assertGreaterEqual(c0, 72, tag)
                self.assertLessEqual(c0 + w, 2592, tag)
                eoff = c0 * bpp // 8
                self.assertEqual(eoff * 8, c0 * bpp, tag)
                self.assertEqual(eoff % 4, 0, tag)
                self.assertLess(eoff, 2592 * bpp // 8, tag)
                if bpp == 14:
                    self.assertLessEqual(w * 1104 * 14 // 8, 0x00400000, tag)   # 14-bit LJ92 input < 4 MiB
                max_pv_c = ((c0 + 171 * w // 172) & ~1) + 1
                self.assertLess(max_pv_c, 2592, tag)
                line = 733 if kind == 0 else x3line
            self.assertEqual(per, round(fl * line / 32.0), tag)
            real_fps = 1e6 / (fl * line / 32.0)
            self.assertAlmostEqual(real_fps, fps, delta=0.02, msg=tag)

    @unittest.skipUnless(shutil.which('cc'), 'host C compiler not available')
    def test_c_mlv_chunk_finalize_and_lj_drain(self):
        mlv_helpers = extract_c_block(self.src, 'static unsigned char mlv_hdr[512];', 'static unsigned x_skipn')
        mlv_code = extract_c_block(self.src, 'static unsigned mlv_guid_lo = 0;', 'static void mlv_frame_hdr')
        roll_code = extract_c_block(self.src, 'static unsigned xr_fbytes', '// v101: compressed REC.')
        drain_code = extract_c_block(self.src, 'static void lj_drain(void)', 'static void lj_kick(unsigned fr)')

        harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <assert.h>

static unsigned tick_val = 123456;
static unsigned get_tick_count(void) { return tick_val; }
static void msleep(long ms) { (void)ms; }
static unsigned GiveSemaphore(int s) { (void)s; return 0; }

static unsigned x_skipy = 0, x_zoom = 1, lvn_lb = 3240, lvn_bpp = 10, lj_eoff = 100, mlv_crop = 1;
static unsigned x_m1 = 0, x_dr[3];                                       /* v180/v182: ImgMode 1 flag, drop reasons */
static unsigned shamem(unsigned reg) { (void)reg; return 0; }           /* v180: ImgMode 1 OB probe (x_m1 = 0 here) */
static unsigned xr_wr = 0, xr_prod = 0, xr_err = 0, x_ready = 0;
static int xr_fd = -1, xr_sem = 1;
static unsigned lj_cnt = 0, lj_err = 0, lj_cslot_n = 4, lj_kicked = 0, cb_done = 0;
#define LJ_DUP_N 8
static volatile unsigned lj_dup_q[LJ_DUP_N], lj_dup_h = 0, lj_dup_t = 0;
static int lj_sem = 2;

''' + mlv_helpers + mlv_code + roll_code + '''
static void lj_collect(void) {
    if (!lj_kicked || !cb_done) return;
    lj_kicked = 0;
    lj_cnt++;
    xr_wr = lj_cnt; /* writer keeps pace during drain */
}
static void lj_kick(unsigned fr) {
    if (lj_kicked || fr >= x_ready || fr - xr_wr >= lj_cslot_n) return;
    lj_kicked = fr + 1;
    cb_done = 1;
}
''' + drain_code + '''

int main(int argc, char **argv) {
    (void)argc;
    snprintf(xr_base, sizeof(xr_base), "%s", argv[1]);

    /* Case 1: lj_drain completes in-flight frame + 2 queued tail frames */
    lj_cnt = 97; xr_wr = 96; x_ready = 98; xr_prod = 100;
    lj_kicked = 98; cb_done = 1;
    lj_drain();
    assert(lj_err == 0 && lj_kicked == 0 && lj_cnt == 100 && x_ready == 100);

    /* Case 2: 3-chunk split MLV finalize */
    xr_wr = 0; xr_fileno = 0; xr_chunk_start = 0;
    mlv_guid_lo = get_tick_count();
    char nm[24];
    snprintf(nm, sizeof(nm), "%s.MLV", xr_base);
    xr_fd = open(nm, O_WRONLY | O_CREAT | O_TRUNC, 0777);
    assert(xr_fd >= 0);
    mlv_build_hdr(2512, 1104, 14, 0);
    put16(mlv_hdr + 32, 0x21);
    write(xr_fd, mlv_hdr, 512);
    xr_fbytes = 512;

    xr_wr = 600;
    xr_roll();
    assert(xr_err == 0 && xr_fd >= 0);
    xr_wr = 1150;
    xr_roll();
    assert(xr_err == 0 && xr_fd >= 0);
    xr_wr = 1273;

    tick_val = 999999;
    mlv_fps1000 = 24001;
    mlv_finalize(2512, 1104, 14, 1);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            c_path = os.path.join(td, 'harness.c')
            bin_path = os.path.join(td, 'harness')
            base = 'M10_0001'
            Path(c_path).write_text(harness)
            comp = subprocess.run(['cc', '-O2', '-Wall', '-Wextra', c_path, '-o', bin_path], capture_output=True, text=True)
            self.assertEqual(comp.returncode, 0, comp.stderr)
            run = subprocess.run([bin_path, base], cwd=td, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)

            chunks = [(f'{base}.MLV', 0, 600), (f'{base}.M00', 1, 550), (f'{base}.M01', 2, 123)]
            guids = set()
            for fn, exp_num, exp_frames in chunks:
                hdr = Path(td, fn).read_bytes()
                self.assertEqual(len(hdr), 512)
                magic, sz, ver, guid, fnum, fcnt, fflags, vcls, acls, vfc, afc, fps_n, fps_d = struct.unpack_from(
                    '<4sI8sQHHIHHIIII', hdr, 0
                )
                self.assertEqual(magic, b'MLVI')
                self.assertEqual(sz, 52)
                self.assertEqual(fnum, exp_num)
                self.assertEqual(fcnt, 3)
                self.assertEqual(fflags, 0)
                self.assertEqual(vcls, 0x21)
                self.assertEqual(acls, 0)
                self.assertEqual(vfc, exp_frames)
                self.assertEqual(afc, 0)
                self.assertEqual(fps_n, 24001)
                self.assertEqual(fps_d, 1000)
                guids.add(guid)
                rawi_tag, rawi_sz, raw_w, raw_h = struct.unpack_from('<4sI8xHH', hdr, 52)
                self.assertEqual(rawi_tag, b'RAWI')
                self.assertEqual(rawi_sz, 180)
                self.assertEqual((raw_w, raw_h), (2512, 1104))
                y1, x1, y2, x2 = struct.unpack_from('<4I', hdr, 52 + 16 + 4 + 52)
                self.assertEqual((y1, x1, y2, x2), (28, 0, 1104, 2512))
            self.assertEqual(len(guids), 1)


if __name__ == '__main__':
    unittest.main()
