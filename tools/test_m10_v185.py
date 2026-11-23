#!/usr/bin/env python3
"""Host regression & contract test suite for m10cine.flt v185 (no USB).

v185: ImgMode 1 Wide profiles (Wide 1800 10b 1728x1800 LCLK 640 FL 2080, Wide 1440 12b / 10b 1728x1440), CMOS 2/5/7
wide window (CMOS 3 never touched), siohook6 pad ARG_OFF 0x280 carrying [0xfc3c] from C to M10SHELL.LUA, and a
dedicated Wide 1:3 preview (pv_mask_opaque_wide / pv_render_m1_wide / pv_dflush_m1_wide behind the pv_m1_* dispatch).
The C test compiles the real functions extracted from m10_cine.c with ASan + UBSan and -Wall -Wextra -Werror and
checks every LCD pixel against an independent model, plus dcache-flush coverage of every byte the renderer reads.

v185b: Standby + REC arm at x_lo 37600 for Wide 1800, overlay sentinel (21, 358) / Wide focus (1, 358) instead of
the clip-text pixel (30, 2), sh_m1_enter clears pv_has_img, 1440p -> non-1440p switch under the WB keepalive.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C_SRC = (ROOT / 'module/m10_cine.c' if (ROOT / 'module/m10_cine.c').exists()
         else ROOT / 'src/chdk/trunk/modules/m10_cine.c')   # public repo layout first, R&D tree second
LUA_SRC = (ROOT / 'card/CHDK/SCRIPTS/M10SHELL.LUA' if (ROOT / 'card/CHDK/SCRIPTS/M10SHELL.LUA').exists()
           else ROOT / 'tools/shell/M10SHELL.LUA')
# CHDK trunk (hostlua, platform stubs): $M10_CHDK, ./chdk (module/build.sh default) or the R&D tree src/chdk
CHDK_TRUNK = next((Path(d) / 'trunk' for d in (os.environ.get('M10_CHDK'), ROOT / 'chdk', ROOT / 'src/chdk')
                   if d and (Path(d) / 'trunk/tools/hostlua').is_dir()), ROOT / 'src/chdk/trunk')
HOSTLUA = CHDK_TRUNK / 'tools/hostlua/lua'
sys.path.insert(0, str(ROOT / 'tools'))
from test_m10_v184 import func_def, decl, strip_comments  # noqa: E402

PROF_RE = re.compile(r'\{\s*(\d+),\s*(\d+),\s*(0x[0-9a-fA-F]+),\s*(\w+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*"([^"]+)",'
                     r'\s*(\d+),\s*(\d+),\s*(\d+)\s*\}')


def run_c(code: str):
    with tempfile.TemporaryDirectory() as d:
        src, exe = Path(d) / 'test.c', Path(d) / 'test'
        src.write_text(code)
        subprocess.run(['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fno-omit-frame-pointer',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', str(src), '-o', str(exe)],
                       check=True)
        res = subprocess.run([str(exe)], timeout=600, capture_output=True, text=True)
        assert res.returncode == 0, res.stdout + res.stderr
        return res


class TestV185Tables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = C_SRC.read_text()
        cls.code = strip_comments(cls.text)

    def test_profiles_and_tables(self):
        t = self.text
        blk = t[t.index('static const sh_prof_t sh_profs[] = {'):]
        blk = blk[:blk.index('};')]
        rows = re.findall(
            r'\{\s*(\d+),\s*(\d+),\s*0x[0-9a-fA-F]+,\s*(\w+),\s*(\d+),\s*(\d+),\s*0,\s*(\d+),\s*"([^"]+)",'
            r'\s*(\d+),\s*(\d+),\s*(\d+),\s*0x[0-9a-fA-F]+,\s*0x[0-9a-fA-F]+,\s*(\d+),\s*"([^"]+)"\s*\}',
            blk,
        )
        self.assertEqual(len(rows), 10)
        P = {r[6]: dict(fps=int(r[0]), bpp=int(r[1]), kind=r[2], fl=int(r[3]), per=int(r[4]), w=int(r[5]),
                        h=int(r[7]), lclk=int(r[8]), wide=int(r[9]), mask=int(r[10])) for r in rows}
        self.assertEqual(rows[0][6], '1920x1440 24p')   # default profile = 1440p 4:3
        p0 = P['1920x1440 24p']
        self.assertEqual((p0['w'], p0['h'], p0['wide'], p0['lclk']), (1920, 1440, 0, 732))
        self.assertEqual(P['Wide 1800 24p'], dict(fps=24, bpp=14, kind='SH_M1', fl=2080, per=41665, w=1728, h=1800, lclk=640, wide=1, mask=7))
        self.assertEqual(P['Wide 1440 24p'], dict(fps=24, bpp=14, kind='SH_M1', fl=1819, per=41666, w=1728, h=1440, lclk=732, wide=1, mask=7))
        for tag, p in P.items():
            if p['kind'] == 'SH_M1':
                self.assertLessEqual((p['h'] - p['h'] // 2) * (p['w'] * p['bpp'] // 8), 0x400000, tag)
        self.assertIn('#define SH_IPC_ARG_OFF 0x280', t)
        self.assertIn('static unsigned sh_m1_fc3c(void) { return (7058u - 2u * sh_m1_head_h()) / 2u; }', t)
        self.assertIn('static unsigned sh_m1_head_h(void) { return sh_m1_h() + 16; }', t)
        self.assertEqual(((7058 - 2 * (1800 + 16)) // 2, (7058 - 2 * (1440 + 16)) // 2), (1713, 2073))
        lv = strip_comments(func_def(t, 'lv_x3'))
        for s in ('lines = pr->h;', 'if (lines > 1800) lines = 1800;', 'x_need = pr->h - 4; lj_eh = pr->h;'):
            self.assertIn(s, lv)

    def test_cmos_wide_contract(self):
        e = strip_comments(func_def(self.text, 'sh_expo_apply'))
        i = e.index('if (sh_prof()->m1_wide) {')
        wide, rest = e[i:e.index('} else {', i)], e[e.index('} else {', i):]
        self.assertIn('sh_hook_w(0x240 + 4 * 2, 0x10000 | 0x742);', wide)
        self.assertIn('sh_hook_w(0x240 + 4 * 5, 0x10000 | 0x020);', wide)
        self.assertIn('sh_prof()->c7', wide)
        m1_11 = rest[:rest.index('sh_hook_w(0x240, 0x10000 | sh_iso_c[sh_m1_iso()]);')]
        self.assertIn('sh_hook_w(0x240 + 4 * 2, 0);', m1_11)                     # 1:1 ImgMode 1 clears CMOS 2
        self.assertIn('sh_prof()->c7', m1_11)
        non_m1 = e[e.index('} else {', e.index('sh_m1_tv();')):]
        self.assertIn('sh_hook_w(0x240 + 4 * 2, 0);', non_m1[:non_m1.index('// Tv') if '// Tv' in non_m1 else len(non_m1)])
        self.assertEqual(e.count('sh_hook_w(0x240 + 4 * 2, 0);'), 2)
        self.assertNotIn('0xf08', e)                                              # CMOS 3 = 0xf08 is never written
        self.assertNotRegex(e, r'0x240\s*\+\s*4\s*\*\s*3\b')
        self.assertNotIn('0x10000 | 0xf08', self.code)
        self.assertIn('sh_hook_w(0x308, (0x8006u << 16) | sh_gray(sh_m1_lclk()));', e)   # TG 8006 = profile line clock
        self.assertNotIn('sh_gray(SH_M1_LCLK)', e)

    def test_lua_fc3c_ipc(self):
        lua = LUA_SRC.read_text()
        for s in ('local ARG_OFF     = 0x280', 'local fw = peek(b + ARG_OFF)', 'if fw < 100 or fw > 3500 then fw = FC3C_M1 end',
                  'if peek(FC3C) == last_fc3c then poke(FC3C, fc3c0) end'):
            self.assertIn(s, lua)
        stm = [s for s in re.findall(r'[^;{}]*\bSH_IPC_ARG_OFF\b[^;{}]*;', self.code) if '#define' not in s]
        self.assertTrue(stm, 'SH_IPC_ARG_OFF never written by the C side')
        self.assertIn('sh_m1_fc3c()', self.code)
        if not HOSTLUA.exists():
            self.skipTest('hostlua missing (set M10_CHDK to a CHDK checkout)')
        v182 = (ROOT / 'tools/test_m10_v182.py').read_text()   # reuse the v182 hostlua mock (firmware + IPC driver)
        i = v182.index("harness = f'''") + len("harness = f'''")
        h = v182[i:v182.index("'''", i)].replace('{{', '{').replace('}}', '}').replace('{LUA_SRC}', str(LUA_SRC))
        a = 'if step == 20 then mem[HOOK + 0x224] = 0; mem[HOOK + 0x220] = 1 end'
        b = 'mem[0xfc3c] == 2073, "m1_on state wrong"'
        self.assertIn(a, h)
        self.assertIn(b, h)
        h = h.replace(a, 'if step == 20 then mem[HOOK + 0x280] = ARG_VAL; mem[HOOK + 0x224] = 0; mem[HOOK + 0x220] = 1 end')
        h = h.replace(b, 'mem[0xfc3c] == EXPECT_FC3C, "m1_on fc3c wrong: " .. tostring(mem[0xfc3c])')
        for arg, exp in ((1713, 1713), (0, 2073), (99, 2073), (2073, 2073)):   # m1_off must restore 24 in every case
            with self.subTest(arg=arg), tempfile.TemporaryDirectory() as d:
                p = Path(d) / 'm.lua'
                p.write_text(f'local ARG_VAL, EXPECT_FC3C = {arg}, {exp}\n' + h)
                res = subprocess.run([str(HOSTLUA), str(p)], capture_output=True, text=True, timeout=10)
                self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
                self.assertIn('lua mock ok', res.stdout)


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define PV_BW 360
#define PV_BLACK 0xFF000000u
#define PV_HOT
static unsigned fake_rgba[PV_BW * 240];
#define PV_RGBA fake_rgba
typedef void (*fn2_t)(unsigned, unsigned);
#define fn2 fn2_t
static void mock_flush(unsigned s, unsigned len);
#define FN_DFLUSH ((uintptr_t)mock_flush)
static struct { int buffer_width; } camera_screen = { 360 };
static unsigned refresh_n = 0;
static volatile unsigned sh_field = 0, sh_rec_on = 0;
static unsigned pv_m1_ylim(void) { return (sh_field == 4 && !sh_rec_on) ? 200u : 220u; }
static void vid_bitmap_refresh(void) { refresh_n++; }
@@DECLS@@
static int pv_ok(void) { return camera_screen.buffer_width == PV_BW; }
@@FUNCS@@
#define RW @@RW@@u
#define RH @@RH@@u
#define BPP @@BPP@@u
#define LB (RW * BPP / 8u)
#define BASE 0x10000000u
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL line %d valk=%u: ", __LINE__, valk); printf(__VA_ARGS__); printf("\n"); exit(1); } } while (0)
static const unsigned PEAK = 0xFF00FF40u, ZEB = 0xFFFF2800u, SENT = 0x5A5A5A5Au, TICK = 0xFF888888u;
static unsigned char *flushed, *need;
static size_t fsz;
static unsigned nflush, valk;
static char *fr_buf;
static unsigned expv[PV_BW * 240], gcur[PV_BW], gprev[PV_BW];
static void mock_flush(unsigned s, unsigned len) {
    if (s % 32u || len % 32u || !len || s < BASE || (size_t)(s - BASE) + len > fsz + 32u) { printf("BAD FLUSH s=%x len=%u\n", s, len); exit(2); }
    memset(flushed + (s - BASE), 1, len);
    nflush++;
}
static unsigned val(unsigned r, unsigned c) {   /* 10-bit scale photosite value */
    if (valk == 1) return c < 864u ? 127u : 600u;    /* focus edge at the centre column */
    if (valk == 2) return c < 864u ? 200u : 1023u;   /* right half clipped */
    return 127u + ((r >> 1) * 7u + (c >> 1) * 13u + (r & 1u) * 31u + (c & 1u) * 57u) % 800u;
}
static char *mk(void) {   /* exact-size PACK32 frame: ASan catches any read past the last row */
    char *fr = calloc(RH, LB);
    assert(fr);
    for (unsigned r = 0; r < RH; r++) {
        unsigned short *d = (unsigned short *)(fr + (size_t)r * LB);
        for (unsigned c = 0; c < RW; c++) {
            unsigned b = c * BPP, w = b >> 4, sh = b & 15u, top = 16u - BPP, v = val(r, c) * (BPP == 12u ? 4u : 1u);
            if (sh <= top) d[w] |= (unsigned short)(v << (top - sh));
            else { d[w] |= (unsigned short)(v >> (sh - top)); d[w + 1] |= (unsigned short)(v << (16u + top - sh)); }
        }
    }
    for (unsigned r = 0; r < RH; r += 97) for (unsigned c = 0; c + 8u < RW; c += 31) {   /* packer == firmware readers */
        const unsigned short *p = (const unsigned short *)(fr + (size_t)r * LB);
        unsigned got = BPP == 12u ? pv_get12(p, c) : pv_get10(p, c), ex = val(r, c) * (BPP == 12u ? 4u : 1u);
        CHECK(got == ex, "pack r=%u c=%u got=%u exp=%u", r, c, got, ex);
    }
    return fr;
}
static unsigned out_h_of(unsigned mode) { return mode == 1 ? 200u : (RH > 1440u ? 124u : 100u); }
static unsigned out_y_of(unsigned mode) { return mode == 1 ? 20u : 20u + (200u - out_h_of(mode)) / 2u; }
static void fill_sent(void) { for (unsigned i = 0; i < PV_BW * 240u; i++) fake_rgba[i] = expv[i] = SENT; }
static void model_mask(unsigned mode, int full) {
    unsigned oy = out_y_of(0), oh = out_h_of(0);
    for (unsigned y = 20; y < 220; y++)
        if (full || mode == 2 || (mode == 0 && (y < oy || y >= oy + oh)))
            for (unsigned x = 0; x < PV_BW; x++) expv[y * PV_BW + x] = PV_BLACK;
}
static unsigned model(unsigned mode, int hr, unsigned zebra, unsigned peak, unsigned fidx) {   /* independent reference */
    const unsigned st = hr ? 2u : 1u, focus = mode == 1, oh = out_h_of(mode), oy = out_y_of(mode);
    const unsigned W = PV_BW / st, H = oh / st, c0 = ((RW - 240u) / 2u) & ~1u, r0 = ((RH - 400u) / 2u) & ~1u;
    const unsigned w239 = oh * 239u / 100u, tx0 = (PV_BW - w239) / 2u, tx1 = PV_BW - 1u - tx0;
    unsigned clip = 0;
    for (unsigned y = 0; y < H; y++) {
        for (unsigned x = 0; x < W; x++) {
            unsigned c = focus ? ((c0 + x * 240u / W) & ~1u) : ((x * RW / W) & ~1u);
            unsigned r = focus ? r0 + 2u * st * y : ((y * RH / H) & ~1u);
            unsigned s0 = val(r, c), s1 = val(r, c + 1), s2 = val(r + 1, c), s3 = val(r + 1, c + 1);
            unsigned mx = s0 > s1 ? s0 : s1, g = (s1 + s2) >> 1, px, cl;
            mx = s2 > mx ? s2 : mx;
            mx = s3 > mx ? s3 : mx;
            for (unsigned k = 0; k < 2; k++) memset(need + (size_t)(r + k) * LB + 2u * ((c * BPP) >> 4), 1, 4);
            cl = mx >= 1020u;
            clip += cl;
            if (cl && zebra && ((st * (x + y) + fidx) & 7u) < 4u) px = ZEB;
            else {
                px = pv_lut_r[s0] | pv_lut_g[g] | pv_lut_b[s3];
                if (peak && !hr && !cl && x && y) {
                    unsigned gl = gcur[x - 1], gp = gprev[x], dh = g > gl ? g - gl : gl - g, dv = g > gp ? g - gp : gp - g;
                    if ((dh + dv) * 6u > g + gl + 2u * 127u + 32u) px = PEAK;
                }
            }
            gcur[x] = g;
            for (unsigned dy = 0; dy < st; dy++) for (unsigned dx = 0; dx < st; dx++) expv[(oy + st * y + dy) * PV_BW + st * x + dx] = px;
        }
        if (!focus && (st * y < 6u || st * y + st > oh - 6u))
            for (unsigned dy = 0; dy < st; dy++) { expv[(oy + st * y + dy) * PV_BW + tx0] = TICK; expv[(oy + st * y + dy) * PV_BW + tx1] = TICK; }
        memcpy(gprev, gcur, sizeof(gcur));
    }
    return clip ? (clip * 100u + W * H - 1u) / (W * H) : 0u;
}
static unsigned count_px(unsigned v, unsigned *xmin, unsigned *xmax) {
    unsigned n = 0;
    *xmin = PV_BW; *xmax = 0;
    for (unsigned i = 0; i < PV_BW * 240u; i++) if (fake_rgba[i] == v) {
        unsigned x = i % PV_BW;
        n++;
        *xmin = x < *xmin ? x : *xmin;
        *xmax = x > *xmax ? x : *xmax;
    }
    return n;
}
static void run(unsigned mode, int hr, unsigned zebra, unsigned peak) {
    unsigned fidx = 3u + mode * 2u + (unsigned)hr + valk * 5u, pct, rn, oy = out_y_of(mode), oh = out_h_of(mode), a, b, n;
    fill_sent();
    pv_mode = mode; pv_zebra = zebra; pv_peak = peak;
    rn = refresh_n;
    pv_mask_opaque_wide(0, RH);
    model_mask(mode, 0);
    CHECK(refresh_n == rn + 1 && !memcmp(fake_rgba, expv, sizeof(expv)), "mask mode=%u", mode);
    pv_stat[0] = fidx;
    memset(need, 0, fsz);
    pct = model(mode, hr, zebra, peak, fidx);
    pv_render_m1_wide(fr_buf, BPP, hr, RW, RH);
    for (unsigned i = 0; i < PV_BW * 240u; i++)
        CHECK(fake_rgba[i] == expv[i], "pix mode=%u hr=%d zb=%u pk=%u y=%u x=%u got=%08x exp=%08x", mode, hr, zebra, peak, i / PV_BW, i % PV_BW, fake_rgba[i], expv[i]);
    CHECK(pv_clip_pct == pct && pv_stat[0] == fidx + 1u && refresh_n == rn + 1, "clip %u/%u stat %u", pv_clip_pct, pct, pv_stat[0]);
    if (mode == 0) {   /* letterbox + 2.39:1 ticks, explicit */
        unsigned w239 = oh * 239u / 100u, tx0 = (PV_BW - w239) / 2u;
        CHECK(oy == (RH > 1440u ? 58u : 70u) && oh == (RH > 1440u ? 124u : 100u), "geom");
        for (unsigned y = 20; y < 220; y++) for (unsigned x = 0; x < PV_BW; x++) {
            unsigned v = fake_rgba[y * PV_BW + x];
            if (y < oy || y >= oy + oh) CHECK(v == PV_BLACK, "bar y=%u", y);
            else CHECK(v != SENT, "hole y=%u x=%u", y, x);
        }
        for (unsigned k = 0; k < 6; k++) {
            CHECK(fake_rgba[(oy + k) * PV_BW + tx0] == TICK && fake_rgba[(oy + k) * PV_BW + PV_BW - 1u - tx0] == TICK, "top tick %u", k);
            CHECK(fake_rgba[(oy + oh - 1u - k) * PV_BW + tx0] == TICK && fake_rgba[(oy + oh - 1u - k) * PV_BW + PV_BW - 1u - tx0] == TICK, "bottom tick %u", k);
        }
    } else for (unsigned i = 20 * PV_BW; i < 220 * PV_BW; i++) CHECK(fake_rgba[i] != SENT, "focus hole %u", i);
    if (valk == 0) CHECK(pv_clip_pct == 0, "no clip expected");
    if (valk == 2) {
        n = count_px(ZEB, &a, &b);
        CHECK(pv_clip_pct == 50 && (zebra ? n > 0 && a >= 180 : n == 0), "zebra n=%u a=%u pct=%u", n, a, pv_clip_pct);
    }
    if (valk == 1 && mode == 1) {
        n = count_px(PEAK, &a, &b);
        CHECK(peak && !hr ? (n == 199 && a == 180 && b == 180) : n == 0, "peaking n=%u x=%u..%u hr=%d pk=%u", n, a, b, hr, peak);
    }
    memset(flushed, 0, fsz + 64); nflush = 0;
    pv_dflush_m1_wide(BASE, LB, mode, hr, RW, RH);
    CHECK(nflush > 0, "no flush");
    for (size_t i = 0; i < fsz; i++) CHECK(!need[i] || flushed[i], "unflushed byte row=%zu off=%zu mode=%u hr=%d", i / LB, i % LB, mode, hr);
}
int main(void) {
    unsigned runs = 0, rn, s0;
    (void)pv_lut;
    fsz = (size_t)RH * LB;
    need = malloc(fsz); flushed = malloc(fsz + 64);
    assert(need && flushed && fsz <= 0x400000u);
    pv_build_m1_luts();
    CHECK(pv_m1_lut_ok == 1 && (pv_lut_r[500] & 0xFF000000u) == PV_BLACK && pv_lut_g[1023] > pv_lut_g[300], "luts");
    for (valk = 0; valk < 3; valk++) {
        fr_buf = mk();
        for (unsigned mode = 0; mode < 2; mode++) for (int hr = 0; hr < 2; hr++)
            for (unsigned zb = 0; zb < 2; zb++) for (unsigned pk = 0; pk < 2; pk++) { run(mode, hr, zb, pk); runs++; }
        free(fr_buf);
    }
    valk = 0; fr_buf = mk();
    fill_sent(); pv_mode = 2; rn = refresh_n;                       /* view OFF */
    pv_mask_opaque_wide(0, RH); model_mask(2, 0);
    CHECK(refresh_n == rn + 1 && !memcmp(fake_rgba, expv, sizeof(expv)), "off mask");
    pv_render_m1_wide(fr_buf, BPP, 0, RW, RH); pv_render_m1_wide(fr_buf, BPP, 1, RW, RH);
    CHECK(!memcmp(fake_rgba, expv, sizeof(expv)), "off render wrote");
    nflush = 0; pv_dflush_m1_wide(BASE, LB, 2, 0, RW, RH); pv_dflush_m1_wide(BASE, LB, 2, 1, RW, RH);
    CHECK(nflush == 0, "off flush");
    fill_sent(); pv_mode = 0; pv_mask_opaque_wide(1, RH); model_mask(0, 1);   /* full = 1: whole window black */
    CHECK(!memcmp(fake_rgba, expv, sizeof(expv)), "full mask");
    camera_screen.buffer_width = 480; fill_sent(); rn = refresh_n; s0 = pv_stat[0];   /* HDMI: never touch PV_RGBA */
    for (unsigned mode = 0; mode < 3; mode++) {
        pv_mode = mode;
        pv_mask_opaque_wide(0, RH); pv_mask_opaque_wide(1, RH);
        pv_render_m1_wide(fr_buf, BPP, 0, RW, RH); pv_render_m1_wide(fr_buf, BPP, 1, RW, RH);
    }
    CHECK(!memcmp(fake_rgba, expv, sizeof(expv)) && refresh_n == rn && pv_stat[0] == s0, "hdmi guard");
    camera_screen.buffer_width = 360;
    free(fr_buf); free(need); free(flushed);
    printf("v185 wide ok %ux%u %ub runs=%u\n", RW, RH, BPP, runs);
    return 0;
}
'''


class TestV185bContracts(unittest.TestCase):
    """v185b: Standby + REC V-blank arming, overlay sentinel off the clip text, sh_m1_enter wipe, WB keepalive."""
    @classmethod
    def setUpClass(cls):
        cls.text = C_SRC.read_text()
        cls.code = strip_comments(cls.text)

    def fn(self, name):
        d = func_def(self.text, name)
        self.assertIsNotNone(d, f'{name} not found')
        return strip_comments(d)

    def test_lv_x3_vblank_arm(self):
        lv = self.fn('lv_x3')
        i = lv.index('if (sh_on && sh_prof()->kind == SH_M1) {')
        blk = lv[i:lv.index('} else if (sh_on) {', i)]
        i_lines, i_lo, i_pv = blk.index('lines = pr->h;'), blk.index('x_lo ='), blk.index('if (!sh_pv) {')
        self.assertLess(i_lines, i_lo)
        self.assertLess(i_lo, i_pv, 'dynamic x_lo must be set for Standby and REC alike')
        rec = blk[i_pv:blk.index('else {', i_pv)]
        self.assertIn('x_need = pr->h - 4; lj_eh = pr->h;', rec)
        stby = blk[blk.index('else {', i_pv):]
        self.assertIn('bpp = 10; x_rsel = 0x10; x_he_fix = 0;', stby)
        self.assertIn('x_need = pr->h - 4;', stby)
        self.assertNotIn('lj_eh', stby)

    def test_overlay_sentinel(self):
        self.assertNotIn('PV_RGBA[30 * PV_BW + 2]', self.text)
        # v186: pv_stby_task uses opaque top HUD bar (1, 358) for ALL ImgMode 1 modes
        self.assertIn('PV_RGBA[1 * PV_BW + 358] != PV_BLACK', self.fn('pv_stby_task'))
        for n in ('sh_preview', 'sh_keywatch_task'):
            self.assertIn('PV_RGBA[21 * PV_BW + 358]', self.fn(n), n)
        self.assertIn('PV_RGBA[1 * PV_BW + 358] != PV_BLACK', self.fn('sh_keywatch_task'))
        h = self.fn('sh_hud')
        self.assertIn('draw_string(2, 22, s, MAKE_COLOR(COLOR_BLACK, COLOR_YELLOW));', h)

    def test_stby_single_mask(self):
        st = self.fn('pv_stby_task')
        head = st[:st.index('if (!f || f == last')]
        self.assertNotRegex(head, r'pv_m1_mask\(0\);[^\n]*\n[^\n]*if \(pv_hud_dirty\) \{ pv_hud_dirty = 0; if \(sh_m1_wide\(\)\) pv_m1_mask\(0\);')
        self.assertIn('if (sh_m1_wide() && !masked) pv_m1_mask(0);', head)
        self.assertIn('masked = 1;', head)

    def test_m1_enter_wipe(self):
        e = self.fn('sh_m1_enter')
        i = e.index('sh_m1_armed_geom = sh_m1_geom(sh_prof());')
        self.assertTrue(e[i:].split(';', 1)[1].lstrip().startswith('pv_has_img = 0;'))
        self.assertLess(i, e.index('return 1;'))

    def test_profile_leave_wb_keepalive(self):
        st = self.fn('shell_task')
        i = st.index('if (prev_kind == SH_M1 && pr->kind != SH_M1) {')
        blk = st[i:st.index('prev_kind = pr->kind;', i)]
        seq = ['wb_wd_force = 1;', 'wb_kick_now();', 'sh_m1_leave();', 'msleep(400);', 'wb_wd_force = 0;', 'sh_arm_fps(pr, !zoom);']
        pos = [blk.index(s) for s in seq]
        self.assertEqual(pos, sorted(pos))
        self.assertIn('wb_wd_force = 1; wb_kick_now(); sh_m1_leave(); msleep(400); wb_wd_force = 0;', blk)

    def test_banner(self):
        self.assertRegex(self.text[:24], r'^/\*\n \* v18(5b|6)')
        self.assertRegex(self.fn('shell_task'), r'slog\("v18(5b|6\w*) shell start", 0, 0\);')


class TestV185WidePreview(unittest.TestCase):
    def test_wide_preview_and_dflush_asan(self):
        text = C_SRC.read_text()
        decls = [decl(text, n) for n in ('pv_stat', 'pv_lut', 'pv_lut_r', 'pv_m1_lut_ok', 'pv_zebra', 'pv_peak', 'pv_mode')]
        names = ('pv_sqrt_m1', 'pv_build_m1_luts', 'pv_fill', 'pv_get10', 'pv_get12',
                 'pv_mask_opaque_wide', 'pv_render_m1_wide', 'pv_dflush_m1_wide')
        funcs = [func_def(text, n) for n in names]
        for n, f in zip(names, funcs):
            self.assertIsNotNone(f, n)
        for w, h, bpp in ((1728, 1800, 10), (1728, 1440, 10), (1728, 1440, 12)):
            with self.subTest(w=w, h=h, bpp=bpp):
                code = (HARNESS.replace('@@DECLS@@', '\n'.join(decls)).replace('@@FUNCS@@', '\n'.join(funcs))
                        .replace('@@RW@@', str(w)).replace('@@RH@@', str(h)).replace('@@BPP@@', str(bpp)))
                res = run_c(code)
                print(res.stdout, end='')
                self.assertIn(f'v185 wide ok {w}x{h} {bpp}b runs=48', res.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
