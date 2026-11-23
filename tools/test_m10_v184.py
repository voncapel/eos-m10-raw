#!/usr/bin/env python3
"""Host regression & contract test suite for m10cine.flt v184a / v184b (no USB).

v184b: pre-shifted u32 LUTs (px = lr[R] | lg[G] | lb[B], cinema S-curve baked in), no 2-quad average / saturation
pass, per-column word / shift tables, one inner loop per bit depth, PV_HOT O2 (-mword-relocations build), standby
ring up to 8 slots with dflush timed apart + msleep(5), REC 4:3 always half res, 1:1 full res + peaking, 30 ms pace.

v184a: ImgMode 1 preview polish. Fixed REC-view colour LUTs (pv_lut_r/g/b, daylight WB folded in), saturation
x1.35, 4:3 2-quad averaging (10b full res), output-grid focus peaking in both views, sampled-row dcache flush
(pv_dflush_m1), async standby render task M10PvS on a 3-slot EXMEM ring, REC preview of the newest captured frame,
seamless Standby <-> REC transitions (pv_has_img), half-press 4:3 <-> 1:1 toggle (Canon AF dip removed).
The C tests compile the real functions extracted from m10_cine.c with ASan + UBSan.
"""
import os
import re
import subprocess
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


def func_def(text: str, name: str):
    """Full definition (signature + body) of a top-level `static ... name(...)` function, or None."""
    for m in re.finditer(rf'^static[^\n;{{]*\b{name}\s*\(', text, re.M):
        nl = text.find('\n', m.end())
        line_tail = text[m.end():nl] if nl >= 0 else text[m.end():]
        if ';' in line_tail.split('//')[0]:
            continue   # prototype or one-line function
        brace = text.find('{', nl if nl >= 0 else m.end())
        if brace < 0:
            continue
        depth, end = 1, brace + 1
        while depth:
            depth += (text[end] == '{') - (text[end] == '}')
            end += 1
        return text[m.start():end]
    return None


def decl(text: str, name: str) -> str:
    m = re.search(rf'^static [^;\n(]*\b{name}\b[^;\n(]*;', text, re.M)
    assert m, f'declaration of {name} not found in m10_cine.c'
    return m.group(0)


def strip_comments(t: str) -> str:
    t = re.sub(r'/\*.*?\*/', '', t, flags=re.S)
    return re.sub(r'//[^\n]*', '', t)


V185_DISPATCH = (('pv_m1_mask(', 'pv_mask_opaque('), ('pv_m1_dflush(', 'pv_dflush_m1('), ('pv_m1_render(', 'pv_render_m1('))


def v185_norm(s: str) -> str:
    """v185: ImgMode 1 call sites go through pv_m1_mask / pv_m1_dflush / pv_m1_render, which forward verbatim to
    pv_mask_opaque / pv_dflush_m1 / pv_render_m1 unless sh_m1_wide() (pinned by TestV185Dispatch below)."""
    for a, b in V185_DISPATCH:
        s = s.replace(a, b)
    return s


def run_c(code: str):
    with tempfile.TemporaryDirectory() as d:
        src, exe = Path(d) / 'test.c', Path(d) / 'test'
        src.write_text(code)
        subprocess.run(['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Wno-unused-function',
                        '-Wno-unused-parameter', '-Wno-sign-compare', '-fno-omit-frame-pointer',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=undefined',
                        str(src), '-o', str(exe)], check=True)
        res = subprocess.run([str(exe)], timeout=300, capture_output=True, text=True)
        assert res.returncode == 0, res.stdout + res.stderr
        return res


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PV_BW 360
#define PV_BLACK 0xFF000000u
#define PV_M1_X 46
#define PV_M1_W 266
#define PV_M1_H 200
#define PV_HOT
static unsigned fake_rgba[PV_BW * 240];
#define PV_RGBA fake_rgba
typedef void (*fn2_t)(unsigned, unsigned);
#define fn2 fn2_t
static void mock_flush(unsigned s, unsigned len);
#define FN_DFLUSH ((uintptr_t)mock_flush)
static struct { int buffer_width; } camera_screen = { 360 };
static int refresh_n = 0;
static volatile unsigned sh_field = 0, sh_rec_on = 0;
static unsigned pv_m1_ylim(void) { return (sh_field == 4 && !sh_rec_on) ? 200u : 220u; }
static void vid_bitmap_refresh(void) { refresh_n++; }
@@DECLS@@
static int pv_ok(void) { return camera_screen.buffer_width == PV_BW; }
@@FUNCS@@
#define pv_render_m1(f, b, h) pv_render_m1(f, b, h, 1920, 1440)
#define pv_dflush_m1(p, l, m, h) pv_dflush_m1(p, l, m, h, 1920, 1440)

static const unsigned PEAK = 0xFF00FF40u, ZEB = 0xFFFF2800u, SENT = 0x5A5A5A5Au;
#define PX(x, y) fake_rgba[(20 + (y)) * PV_BW + PV_M1_X + (x)]

static unsigned model(unsigned s0, unsigned g, unsigned s3) {   /* v184b reference colour pipeline: one OR of the lanes */
    return pv_lut_r[s0] | pv_lut_g[g] | pv_lut_b[s3];
}
#define R8(v) ((pv_lut_r[v] >> 16) & 255u)
#define G8(v) ((pv_lut_g[v] >> 8) & 255u)
#define B8(v) (pv_lut_b[v] & 255u)
typedef unsigned (*valfn)(unsigned, unsigned);
static unsigned v_map(unsigned r, unsigned c) { return 127 + ((((r >> 1) * 7) + ((c >> 1) * 13)) % 800); }
static unsigned v_edge(unsigned r, unsigned c) { return c < 960 ? 127 : 600; }
static unsigned v_flat(unsigned r, unsigned c) { return 300 + ((r * 7 + c * 13) % 3); }
static unsigned v_clip(unsigned r, unsigned c) { return c < 960 ? 127 : 1023; }
static unsigned v_ab(unsigned r, unsigned c) { return ((c >> 1) & 1) ? 127 : 700; }
static unsigned v_col(unsigned r, unsigned c) { unsigned ch = ((r & 1) << 1) | (c & 1); return ch == 0 ? 420 : ch == 3 ? 300 : 380; }
static unsigned v_c130(unsigned r, unsigned c) { return 130; }
static unsigned v_c900(unsigned r, unsigned c) { return 900; }

static void pack_row(unsigned short *dst, const unsigned *vals, unsigned bpp) {
    unsigned top = 16 - bpp, m = (1u << bpp) - 1;
    memset(dst, 0, 1920 * bpp / 8);
    for (unsigned c = 0; c < 1920; c++) {
        unsigned b = c * bpp, w = b >> 4, sh = b & 15, v = vals[c] & m;
        if (sh <= top) dst[w] |= (unsigned short)(v << (top - sh));
        else { dst[w] |= (unsigned short)(v >> (sh - top)); dst[w + 1] |= (unsigned short)(v << (16 + top - sh)); }
    }
}
static char *mk(unsigned bpp, valfn f) {   /* exact-size frame: ASan catches any read past row 1439 */
    size_t lb = 1920 * bpp / 8;
    char *fr = malloc(1440 * lb);
    static unsigned tmp[1920];
    assert(fr);
    for (unsigned r = 0; r < 1440; r++) {
        for (unsigned c = 0; c < 1920; c++) tmp[c] = f(r, c) * (bpp == 12 ? 4 : 1);
        pack_row((unsigned short *)(fr + r * lb), tmp, bpp);
    }
    return fr;
}
static void sentinel(void) { for (unsigned i = 0; i < PV_BW * 240; i++) fake_rgba[i] = SENT; }
static unsigned ox_of(unsigned mode) { return mode == 1 ? 0u : PV_M1_X; }
static unsigned ow_of(unsigned mode) { return mode == 1 ? PV_BW : PV_M1_W; }
static void outside_untouched_m(unsigned mode) {
    unsigned ox = ox_of(mode), ow = ow_of(mode);
    for (unsigned y = 0; y < 240; y++)
        for (unsigned x = 0; x < PV_BW; x++)
            if (y < 20 || y >= 220 || x < ox || x >= ox + ow) assert(fake_rgba[y * PV_BW + x] == SENT);
}
static void outside_untouched(void) { outside_untouched_m(pv_mode); }
static unsigned cnt(unsigned v) {
    unsigned n = 0, ox = ox_of(pv_mode), ow = ow_of(pv_mode);
    for (unsigned y = 0; y < PV_M1_H; y++) for (unsigned x = 0; x < ow; x++) n += fake_rgba[(20 + y) * PV_BW + ox + x] == v;
    return n;
}
static unsigned c_of(unsigned mode, unsigned st, unsigned x) { return mode == 1 ? 600 + 2 * st * x : (x * 1920 / (PV_M1_W / st)) & ~1u; }
static unsigned r_of(unsigned mode, unsigned st, unsigned y) { return mode == 1 ? 520 + 2 * st * y : (y * 1440 / (PV_M1_H / st)) & ~1u; }

static void check_map(unsigned bpp, unsigned mode, int hr) {   /* exact geometry + colour of every output pixel */
    char *f = mk(bpp, v_map);
    unsigned st = hr ? 2 : 1, ox = ox_of(mode), ow = ow_of(mode), W = ow / st, H = PV_M1_H / st;
    pv_mode = mode; pv_peak = 0; pv_zebra = 0;
    sentinel();
    pv_render_m1(f, bpp, hr);
    for (unsigned y = 0; y < H; y++)
        for (unsigned x = 0; x < W; x++) {
            unsigned r = r_of(mode, st, y), c = c_of(mode, st, x), s = v_map(r, c);
            unsigned e = model(s, s, s);
            for (unsigned dy = 0; dy < st; dy++)
                for (unsigned dx = 0; dx < st; dx++) assert(fake_rgba[(20 + st * y + dy) * PV_BW + ox + st * x + dx] == e);
        }
    outside_untouched();
    assert(pv_clip_pct == 0);
    free(f);
}
static void check_peak_edge(unsigned bpp, unsigned mode) {
    char *f = mk(bpp, v_edge);
    unsigned n = 0, ox = ox_of(mode), ow = ow_of(mode);
    pv_mode = mode; pv_peak = 1; pv_zebra = 1;
    sentinel();
    pv_render_m1(f, bpp, 0);
    for (unsigned y = 0; y < PV_M1_H; y++)
        for (unsigned x = 0; x < ow; x++)
            if (fake_rgba[(20 + y) * PV_BW + ox + x] == PEAK) { n++; assert(x > 0 && y > 0); assert(c_of(mode, 1, x) >= 960 && c_of(mode, 1, x - 1) < 960); }
    printf("edge peaks bpp=%u mode=%u n=%u\n", bpp, mode, n);
    assert(n >= PV_M1_H / 2 && n <= PV_M1_H);
    outside_untouched();
    free(f);
}
static void check_flat(unsigned bpp, unsigned mode) {
    char *f = mk(bpp, v_flat);
    pv_mode = mode; pv_peak = 1; pv_zebra = 1;
    sentinel();
    pv_render_m1(f, bpp, 0);
    assert(cnt(PEAK) == 0 && cnt(ZEB) == 0);
    free(f);
}
static void check_zebra(unsigned bpp, unsigned mode, unsigned zeb) {
    char *f = mk(bpp, v_clip);
    unsigned nz = 0, fidx = pv_stat[0], ox = ox_of(mode), ow = ow_of(mode);
    pv_mode = mode; pv_peak = 1; pv_zebra = zeb;
    sentinel();
    pv_render_m1(f, bpp, 0);
    for (unsigned y = 0; y < PV_M1_H; y++)
        for (unsigned x = 0; x < ow; x++) {
            unsigned px = fake_rgba[(20 + y) * PV_BW + ox + x];
            if (c_of(mode, 1, x) >= 960) {
                assert(px != PEAK);   /* zebra (or plain white) wins over peaking on clip */
                if (zeb && ((x + y + fidx) & 7) < 4) { assert(px == ZEB); nz++; } else assert(px != ZEB);
            } else assert(px != ZEB);
        }
    printf("clip bpp=%u mode=%u zebra=%u nz=%u clip_pct=%u\n", bpp, mode, zeb, nz, pv_clip_pct);
    assert(zeb ? nz > 0 : nz == 0);
    assert(pv_clip_pct >= 45 && pv_clip_pct <= 55);
    free(f);
}

static unsigned fl_s[4096], fl_l[4096], fl_n;
static void mock_flush(unsigned s, unsigned len) { assert(fl_n < 4096); fl_s[fl_n] = s; fl_l[fl_n] = len; fl_n++; }
static void check_flush(unsigned bpp, unsigned mode, int hr, unsigned phys) {
    unsigned lb = 1920 * bpp / 8, st = hr ? 2 : 1, W = ow_of(mode) / st, H = PV_M1_H / st;
    size_t fsz = (size_t)1440 * lb;
    unsigned lo = phys & ~31u, hi = (unsigned)((phys + fsz + 31) & ~31u);
    unsigned char *cov = calloc(fsz, 1);
    assert(cov);
    fl_n = 0;
    pv_dflush_m1(phys, lb, mode, hr);
    if (mode == 2) { assert(fl_n == 0); free(cov); return; }
    assert(fl_n == (mode == 1 ? 2 * H : H));
    for (unsigned i = 0; i < fl_n; i++) {
        assert(fl_s[i] % 32 == 0 && fl_l[i] % 32 == 0 && fl_l[i] > 0);   /* whole cache lines */
        assert(fl_s[i] >= lo && fl_s[i] + fl_l[i] <= hi);                /* never outside the frame's lines */
        for (unsigned a = fl_s[i]; a < fl_s[i] + fl_l[i]; a++) if (a >= phys && a < phys + fsz) cov[a - phys] = 1;
    }
    for (unsigned y = 0; y < H; y++)
        for (unsigned x = 0; x < W; x++) {
            unsigned r = r_of(mode, st, y), c = c_of(mode, st, x), cc[1] = { c }, nc = 1;   /* v184b: one quad per pixel */
            for (unsigned rr = r; rr < r + 2; rr++)
                for (unsigned k = 0; k < nc; k++) {
                    size_t off = (size_t)rr * lb + ((cc[k] * bpp) >> 4) * 2;
                    for (unsigned b = 0; b < 4; b++) assert(cov[off + b]);   /* every word pv_render_m1 reads is flushed */
                }
        }
    free(cov);
}

int main(void) {
    /* A. LUTs built lazily on the first render, sane, WB folded in */
    assert(pv_m1_lut_ok == 0);
    {
        char *g = mk(10, v_c130);
        pv_mode = 0; sentinel(); pv_render_m1(g, 10, 0); free(g);
    }
    assert(pv_m1_lut_ok == 1);
    assert(G8(0) == 0 && G8(127) == 0 && G8(1023) == 255 && R8(1023) == 255 && B8(1023) == 255);
    for (unsigned v = 0; v < 1024; v++)   /* v184b: pre-shifted ARGB lanes, alpha only in R */
        assert((pv_lut_r[v] & 0xFF00FFFFu) == PV_BLACK && (pv_lut_g[v] & ~0xFF00u) == 0 && (pv_lut_b[v] & ~0xFFu) == 0);
    for (unsigned v = 1; v < 1024; v++) assert(R8(v) >= R8(v - 1) && G8(v) >= G8(v - 1) && B8(v) >= B8(v - 1));
    assert(R8(400) > B8(400) && B8(400) > G8(400));   /* daylight WB: R x1.75, B x1.5 */
    /* v184b: cinema S-curve on the sqrt: ends fixed, deeper shadows (sqrt 63 -> 48), brighter upper mids (181 -> 195) */
    assert(pv_sqrt_m1(127) == 0 && pv_sqrt_m1(1023) == 255);
    printf("curve shadow=%u mid=%u\n", pv_sqrt_m1(183), pv_sqrt_m1(575));
    assert(pv_sqrt_m1(183) < 63 && pv_sqrt_m1(183) >= 40 && pv_sqrt_m1(575) > 181 && pv_sqrt_m1(575) <= 205);

    /* B. geometry: 10b & 12b, 4:3 / 1:1, full & half res (v184b: one quad per pixel everywhere) */
    for (unsigned bpp = 10; bpp <= 12; bpp += 2)
        for (unsigned mode = 0; mode < 2; mode++)
            for (int hr = 0; hr < 2; hr++) check_map(bpp, mode, hr);
    {   /* v184b: no 2-quad average: alternating 700 / 127 quads stay distinct in every view and bit depth */
        char *a10 = mk(10, v_ab), *a12 = mk(12, v_ab);
        pv_mode = 0; pv_peak = 0; pv_zebra = 0;
        for (int hr = 0; hr < 2; hr++) {
            char *fr[2] = { a10, a12 };
            for (int k = 0; k < 2; k++) {
                sentinel(); pv_render_m1(fr[k], k ? 12 : 10, hr);
                unsigned hi = cnt(model(700, 700, 700)), lo = cnt(model(127, 127, 127));
                assert(hi > 0 && lo > 0 && hi + lo == PV_M1_W * PV_M1_H);
                assert(cnt(model(413, 413, 413)) == 0);
            }
        }
        free(a10); free(a12);
    }

    /* C. fixed REC view: no per-frame brightness drift (bright / dark frames and pv_make_lut do not move it) */
    {
        static unsigned out1[PV_M1_W * PV_M1_H], out2[PV_M1_W * PV_M1_H];
        static unsigned lr[1024], lg[1024], lbb[1024];
        char *mid = mk(10, v_map), *br = mk(10, v_c900), *dk = mk(10, v_c130), *m12 = mk(12, v_map);
        memcpy(lr, pv_lut_r, sizeof(lr)); memcpy(lg, pv_lut_g, sizeof(lg)); memcpy(lbb, pv_lut_b, sizeof(lbb));
        for (unsigned hr = 0; hr < 2; hr++) {
            char *fr = hr ? m12 : mid;
            unsigned bpp = hr ? 12 : 10;
            pv_mode = 0; pv_peak = 0; pv_zebra = 0;
            sentinel(); pv_render_m1(fr, bpp, hr);
            for (unsigned y = 0; y < PV_M1_H; y++) for (unsigned x = 0; x < PV_M1_W; x++) out1[y * PV_M1_W + x] = PX(x, y);
            for (int i = 0; i < 4; i++) { pv_render_m1(br, 10, hr); pv_render_m1(dk, 10, hr); }
            pv_make_lut(127, 900); pv_make_lut(127, 140); pv_make_lut(64, 300);
            sentinel(); pv_render_m1(fr, bpp, hr);
            for (unsigned y = 0; y < PV_M1_H; y++) for (unsigned x = 0; x < PV_M1_W; x++) out2[y * PV_M1_W + x] = PX(x, y);
            assert(memcmp(out1, out2, sizeof(out1)) == 0);
        }
        assert(!memcmp(lr, pv_lut_r, sizeof(lr)) && !memcmp(lg, pv_lut_g, sizeof(lg)) && !memcmp(lbb, pv_lut_b, sizeof(lbb)));
        free(mid); free(br); free(dk); free(m12);
    }

    /* D. v184b: colour = one OR of the three pre-shifted LUT lanes (no saturation pass, no clamp), 10b & 12b */
    {
        char *f = mk(10, v_col), *f12 = mk(12, v_col);
        unsigned e = PV_BLACK | (R8(420) << 16) | (G8(380) << 8) | B8(300);
        pv_peak = 0; pv_zebra = 0;
        pv_mode = 1; sentinel(); pv_render_m1(f, 10, 0);
        printf("col lut=(%u,%u,%u) px=%08x\n", R8(420), G8(380), B8(300), PX(100, 100));
        assert(PX(100, 100) == e && cnt(e) == PV_BW * PV_M1_H);
        pv_mode = 0; sentinel(); pv_render_m1(f12, 12, 1);
        assert(cnt(e) == PV_M1_W * PV_M1_H);
        outside_untouched();
        free(f); free(f12);
    }

    /* E. peaking: edges > 0 (both views, 10b/12b), flat == 0, zebra wins on clip, half_res disables it */
    for (unsigned bpp = 10; bpp <= 12; bpp += 2)
        for (unsigned mode = 0; mode < 2; mode++) {
            check_peak_edge(bpp, mode);
            check_flat(bpp, mode);
            check_zebra(bpp, mode, 1);
            check_zebra(bpp, mode, 0);
            char *f = mk(bpp, v_edge);
            pv_mode = mode; pv_peak = 1; pv_zebra = 1;
            sentinel(); pv_render_m1(f, bpp, 1);
            assert(cnt(PEAK) == 0);
            outside_untouched();
            free(f);
        }

    /* F. bounds: exact-size frames for every combination, writes confined to the window, OFF / HDMI guards */
    for (unsigned bpp = 10; bpp <= 12; bpp += 2) {
        char *f = mk(bpp, v_clip);
        for (unsigned mode = 0; mode < 3; mode++)
            for (int hr = 0; hr < 2; hr++)
                for (unsigned pk = 0; pk < 2; pk++) {
                    pv_mode = mode; pv_peak = pk; pv_zebra = 1;
                    sentinel(); pv_render_m1(f, bpp, hr);
                    if (mode == 2) assert(cnt(SENT) == PV_M1_W * PV_M1_H);
                    outside_untouched();
                    assert(pv_clip_pct <= 100);
                }
        camera_screen.buffer_width = 480;
        pv_mode = 0; sentinel(); pv_render_m1(f, bpp, 0);
        assert(cnt(SENT) == PV_M1_W * PV_M1_H);
        camera_screen.buffer_width = 360;
        free(f);
    }

    /* G. pv_dflush_m1: lb 2400 / 2880, 32-byte aligned lines, covers every sampled word */
    assert(1920 * 10 / 8 == 2400 && 1920 * 12 / 8 == 2880);
    for (unsigned bpp = 10; bpp <= 12; bpp += 2)
        for (unsigned mode = 0; mode < 3; mode++)
            for (int hr = 0; hr < 2; hr++) { check_flush(bpp, mode, hr, 0x40000000u); check_flush(bpp, mode, hr, 0x40000010u); }

    printf("v184 render ok\n");
    return 0;
}
'''


class TestV184Render(unittest.TestCase):
    def test_render_m1_asan(self):
        text = C_SRC.read_text()
        names = ('pv_get10', 'pv_get12', 'pv_sqrt_m1', 'pv_build_m1_luts', 'pv_make_lut', 'pv_fill',
                 'pv_m1_rect', 'pv_mask_opaque', 'pv_render_m1', 'pv_dflush_m1')
        m1_row = re.search(r'^#define\s+M1_ROW\b(?:[^\n]*\\\n)*[^\n]*', text, re.M).group(0)
        funcs = []
        for n in names:
            d = func_def(text, n)
            self.assertIsNotNone(d, f'{n} definition not found')
            if n == 'pv_render_m1':
                funcs.append(m1_row)
            funcs.append(d)
            if n == 'pv_render_m1':
                funcs.append('#undef M1_ROW')
        decls = []
        for n in ('pv_stat', 'pv_lut', 'pv_lut_r', 'pv_m1_lut_ok', 'pv_zebra', 'pv_peak', 'pv_mode'):
            d = decl(text, n)
            if d not in decls:
                decls.append(d)
        program = HARNESS.replace('@@DECLS@@', '\n'.join(decls)).replace('@@FUNCS@@', '\n'.join(funcs))
        res = run_c(program)
        print(res.stdout, end='')
        self.assertIn('v184 render ok', res.stdout)


class TestV184Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = C_SRC.read_text()
        cls.code = strip_comments(cls.text)

    def fn(self, name):
        d = func_def(self.text, name)
        self.assertIsNotNone(d, f'{name} not found')
        return d

    def test_inline_and_hot(self):
        t = self.text
        self.assertEqual(t.count('static inline unsigned pv_get10('), 1)
        self.assertEqual(t.count('static inline unsigned pv_get12('), 1)
        for n in ('pv_get10', 'pv_get12'):
            m = re.search(r'#if defined\(__GNUC__\) && !defined\(__clang__\)\n(?:[^\n]*\n)*?'
                          rf'static inline __attribute__\(\(always_inline\)\) unsigned {n}\([^)]*\);\n(?:[^\n]*\n)*?#e', t)
            self.assertIsNotNone(m, f'always_inline prototype of {n} missing / not GCC-guarded')
            self.assertLess(m.start(), t.index(f'static inline unsigned {n}('))
        self.assertIn('#define PV_HOT __attribute__((optimize("O2","schedule-insns2")))', t)   # v184b: -mword-relocations build
        self.assertEqual(strip_comments(t).count('optimize("O2"'), 1)   # only PV_HOT
        self.assertIn('static PV_HOT void pv_render_m1(', t)

    def test_render_fixed_view(self):
        body = strip_comments(self.fn('pv_render_m1'))
        self.assertNotIn('pv_make_lut(', body)
        self.assertIn('lb = raw_w * bpp / 8', body)
        self.assertIn('const unsigned *lr = pv_lut_r, *lg = pv_lut_g, *lb_t = pv_lut_b;', body)
        self.assertIn('px = lr[s0] | lg[g] | lb_t[s3];', body)
        self.assertNotIn('340', body)    # v184b: no saturation multiply
        self.assertNotIn('avg2', body)   # v184b: no 2-quad average
        self.assertNotIn('255', body)    # v184b: no per-pixel clamp
        self.assertIn('col_w[x] = (unsigned short)(b >> 4);', body)
        self.assertIn('32 - bpp - (b & 15)', body)
        self.assertEqual(body.count('bpp == 12'), 1, 'bit depth tested once per frame')
        m1_row = re.search(r'^#define\s+M1_ROW\b(?:[^\n]*\\\n)*[^\n]*', self.text, re.M).group(0)
        for bad in ('bpp', '/', 'col_x', '1920'):
            self.assertNotIn(bad, m1_row, f'{bad} in the per-pixel loop')
        for s in ('0xFFFF2800u', '0xFF00FF40u', 'mx >= (THR)', 'mx < (THR)', 'do_peak'):
            self.assertIn(s, m1_row)
        self.assertIn('if (b14) { M1_ROW(14, 0x3fffu, 4, 16320u) }', body)
        self.assertIn('else if (b12) { M1_ROW(12, 0xfffu, 2, 4080u) }', body)
        self.assertIn('else { M1_ROW(10, 0x3ffu, 0, 1020u) }', body)
        self.assertIn('static unsigned pv_lut_r[1024], pv_lut_g[1024], pv_lut_b[1024];', self.text)
        bl = strip_comments(self.fn('pv_build_m1_luts'))
        for s in ('pv_lut_r[v] = PV_BLACK | (pv_sqrt_m1(rr) << 16);', 'pv_lut_g[v] = pv_sqrt_m1(v) << 8;', 'pv_lut_b[v] = pv_sqrt_m1(bb);'):
            self.assertIn(s, bl)
        self.assertLess(self.text.index('#define PV_BLACK'), self.text.index('static void pv_build_m1_luts('))

    def test_dflush(self):
        d = strip_comments(self.fn('pv_dflush_m1'))
        self.assertIn('bpp = lb * 8 / raw_w', d)
        self.assertIn('& ~31u', d)
        self.assertIn('FN_DFLUSH', d)
        self.assertIn('pv_dflush_m1((unsigned)lj_phys + rs * xr_fb, lvn_lb, cur_mode, hr)', v185_norm(self.fn('pv_rec_task')))
        self.assertIn('pv_dflush_m1(pv_stby_phys + sl * pv_stby_fb, lvn_lb, cur_mode, 0)', v185_norm(self.fn('pv_stby_task')))

    def test_rec_task(self):
        b = strip_comments(self.fn('pv_rec_task'))
        self.assertIn('k = xr_prod - 1;', b)
        self.assertIn('xr_prod - lj_cnt >= lj_raw_n - 1', b)
        self.assertIn('xr_prod - k >= lj_raw_n - 1', b)
        self.assertIn('(unsigned)lj_phys + rs * xr_fb', b)
        self.assertNotIn('0x40000000', b)   # cached view, no uncached alias
        self.assertNotIn('1000', b)
        for ms in re.findall(r'msleep\(\s*(\d+)\s*\)', b):
            self.assertLess(int(ms), 100, 'no long delay in the REC preview loop')
        self.assertIn('pv_rec_n++; pv_has_img = 1;', b)
        self.assertIn('hr = (cur_mode == 1 && xr_prod - lj_cnt < 2) ? 0 : 1;', b)   # v184b
        self.assertLess(b.index('cur_mode = pv_mode;'), b.index('hr = ('))
        self.assertIn('msleep(30);', b)
        self.assertNotIn('msleep(40)', b)
        s = v185_norm(strip_comments(self.fn('pv_rec_start')))
        self.assertNotIn('pv_mask_opaque(1)', s)
        self.assertIn('pv_mask_opaque(0)', s)

    def test_preview_seamless(self):
        t = self.text
        self.assertIn('static volatile unsigned pv_has_img = 0;', t)
        sp = v185_norm(self.fn('sh_preview'))
        self.assertIn('ns = (x_exsz > 0x00080000 && fb) ? (x_exsz - 0x00080000) / fb : 1; if (ns > 8) ns = 8; if (ns < 1) ns = 1;', sp)
        self.assertIn('pv_stby_ren_sum = pv_stby_fl_sum = 0;', sp)
        self.assertIn('v184b fl_avg=%d', sp)
        self.assertIn('pv_cap_seq % ns', sp)
        self.assertIn('CreateTask("M10PvS", 0x1E, 0x1000, pv_stby_task)', sp)
        i = sp.index('x_px = 0;')
        self.assertTrue(sp[i:].startswith('x_px = 0;'))
        nxt = sp.index('pv_mask_opaque(', i)
        self.assertTrue(sp[nxt:].startswith('pv_mask_opaque(pv_has_img ? 0 : 1)'), 'REC -> Standby must not black out')
        self.assertIn('sh_pv_key != 1 && sh_pv_key != 2) pv_mask_opaque(1)', sp)
        st = v185_norm(self.fn('pv_stby_task'))
        self.assertIn('pv_stby_n++; pv_has_img = 1;', st)
        self.assertIn('if (pv_mode == 2) { pv_mask_dirty = 1; pv_has_img = 0; continue; }', st)
        mc = strip_comments(self.fn('pv_mask_clear'))
        self.assertLess(mc.index('pv_has_img = 0;'), mc.index('if (!pv_ok()) return;'))

    def test_stby_timing(self):   # v184b
        st = v185_norm(strip_comments(self.fn('pv_stby_task')))
        i_f, i_r = st.index('pv_dflush_m1('), st.index('pv_render_m1(')
        self.assertLess(i_f, i_r)
        self.assertIn('tf = get_tick_count();', st[i_f:i_r])
        self.assertIn('fl = tf - t; t = get_tick_count() - tf;', st)
        self.assertIn('pv_stby_fl_sum += fl;', st)
        self.assertIn('pv_stby_ren_sum += t;', st)
        self.assertRegex(st, r'vid_bitmap_refresh\(\);\s*\n\s*msleep\(5\);')
        self.assertIn('if (pv_cap_seq - f >= (ns > 1 ? ns - 1 : 1)) { pv_stby_torn++; continue; }', st)
        self.assertIn('pv_stby_ns = 8', self.text)

    def test_unload_guards(self):
        for n in ('_module_can_unload', '_module_exit_alt'):
            m = re.search(rf'^int {n}\(\)[^\n]*', self.text, re.M)
            self.assertIsNotNone(m)
            self.assertIn('pv_stby_done', m.group(0))
            self.assertIn('pv_rec_done', m.group(0))

    def test_halfpress_toggle(self):
        k = strip_comments(self.fn('sh_keywatch_task'))
        for s in ('kbd_is_key_pressed(KEY_SHOOT_HALF)', 'hp && !hp_prev', 'hp_prev = hp;', 'sh_is_m1()',
                  '(sh_pv || sh_rec_on)', 'pv_mode = (pv_mode == 1) ? 0 : 1;', 'pv_mode != 2', 'pv_hud_dirty = 1;'):
            self.assertIn(s, k)
        self.assertNotIn('SH_IPC_AF', k)
        self.assertNotIn('sh_af_req', k)
        self.assertNotRegex(self.code, r'sh_pv_key\s*==?\s*8\b')
        self.assertEqual(len(re.findall(r'\bSH_IPC_AF\b', self.code)), 1, 'SH_IPC_AF only #defined, never issued')


IDENT_MAIN = r'''
static void mock_flush(unsigned s, unsigned len) { (void)s; (void)len; }
static unsigned rs = 12345u;
static unsigned rnd(void) { rs = rs * 1103515245u + 12345u; return rs >> 8; }
int main(void) {
    static unsigned a[PV_BW * 240];
    unsigned combos = 0;
    for (unsigned bpp = 10; bpp <= 12; bpp += 2) {
        size_t lb = 1920 * bpp / 8, fsz = 1440 * lb;
        for (unsigned k = 0; k < 4; k++) {
            unsigned char *f = malloc(fsz);
            assert(f);
            for (size_t i = 0; i < fsz; i++) {
                unsigned v = k == 0 ? rnd() : k == 1 ? (rnd() | 0xe0) : k == 2 ? (unsigned)(i * 7 + (i / lb) * 13) : ((i / 97) & 1 ? 0xff : rnd() & 0x3f);
                f[i] = (unsigned char)v;
            }
            for (unsigned mode = 0; mode < 3; mode++)
                for (int hr = 0; hr < 2; hr++)
                    for (unsigned pk = 0; pk < 2; pk++)
                        for (unsigned zb = 0; zb < 2; zb++)
                            for (unsigned fi = 0; fi < 8; fi += 3) {
                                unsigned ca, s0a, s2a;
                                pv_mode = mode; pv_peak = pk; pv_zebra = zb;
                                memset(fake_rgba, 0x5a, sizeof(fake_rgba));
                                pv_stat[0] = fi; pv_stat[2] = 777; pv_clip_pct = 999;
                                pv_render_m1_ref((const char *)f, bpp, hr);
                                memcpy(a, fake_rgba, sizeof(a)); ca = pv_clip_pct; s0a = pv_stat[0]; s2a = pv_stat[2];
                                memset(fake_rgba, 0x5a, sizeof(fake_rgba));
                                pv_stat[0] = fi; pv_stat[2] = 777; pv_clip_pct = 999;
                                pv_render_m1((const char *)f, bpp, hr);
                                if (memcmp(a, fake_rgba, sizeof(a)) || ca != pv_clip_pct || s0a != pv_stat[0] || s2a != pv_stat[2]) {
                                    printf("MISMATCH bpp=%u k=%u mode=%u hr=%d pk=%u zb=%u fi=%u\n", bpp, k, mode, hr, pk, zb, fi);
                                    return 1;
                                }
                                combos++;
                            }
            free(f);
        }
    }
    printf("v184c identical combos=%u\n", combos);
    return 0;
}
'''


class TestV184cIdentical(unittest.TestCase):
    """v184c pv_render_m1 must be bit-identical to the archived v184b one (pixels, clip %, stats)."""
    def test_bit_identical_to_v184b(self):
        old = Path(os.environ.get('M10_BUILDS', ROOT / 'builds')) / 'v184b/m10_cine.c'   # archived build (not public)
        if not old.exists():
            self.skipTest('builds/v184b/m10_cine.c missing (set M10_BUILDS)')
        text = C_SRC.read_text()
        ref = func_def(old.read_text(), 'pv_render_m1')
        self.assertIsNotNone(ref)
        ref = ref.replace('pv_render_m1(', 'pv_render_m1_ref(', 1)
        funcs = [func_def(text, n) for n in ('pv_sqrt_m1', 'pv_build_m1_luts', 'pv_render_m1')]
        self.assertTrue(all(funcs))
        decls = []
        for n in ('pv_stat', 'pv_lut', 'pv_lut_r', 'pv_m1_lut_ok', 'pv_zebra', 'pv_peak', 'pv_mode'):
            d = decl(text, n)
            if d not in decls:
                decls.append(d)
        prefix = HARNESS.split('@@FUNCS@@')[0].replace('@@DECLS@@', '\n'.join(decls))
        res = run_c(prefix + '\n'.join(funcs + [ref]) + IDENT_MAIN)
        print(res.stdout, end='')
        self.assertIn('v184c identical combos=576', res.stdout)


class TestV184cContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = C_SRC.read_text()

    def fn(self, name):
        d = func_def(self.text, name)
        self.assertIsNotNone(d, f'{name} not found')
        return strip_comments(d)

    def test_banner(self):
        self.assertRegex(self.text[:24], r'^/\*\n \* v18(4c|5b?|6\w*) ')
        st = self.fn('shell_task')
        self.assertRegex(st, r'slog\("v18(4c|5b?|6\w*) shell start", 0, 0\);')
        self.assertNotIn('v183d shell start', st)

    def test_pwr_lock_apo(self):
        p = self.fn('sh_pwr_lock')
        i_lock, i_apo, i_un = p.index('((fn0)FN_LOCK_PWR)();'), p.index('((fn1)0xfc1fb4dd)(0);'), p.index('FN_UNLOCK_PWR')
        self.assertLess(i_lock, i_apo)
        self.assertLess(i_apo, i_un, 'SetAutoShutdownTime(0) only on lock')
        stubs = CHDK_TRUNK / 'platform/m10/sub/110d/stubs_entry.S'
        if not stubs.exists():
            self.skipTest('CHDK platform stubs missing (set M10_CHDK); C-side lock/APO order checked above')
        self.assertIn('NHSTUB(SetAutoShutdownTime                    ,0xfc1fb4dd)', stubs.read_text())

    def test_key5_diag(self):
        sp = self.fn('sh_preview')
        i = sp.index('sh_pv_key = 5;')
        seg = sp[i:sp.index('break;', i)]
        self.assertIn('slog("v184c key=5 is=%d tg=%d", *(volatile unsigned *)0x865c, *(volatile unsigned *)0xe664);', seg)
        self.assertIn('slog("  dss=%x rec=%d", *(volatile unsigned *)DSS_FLAGS', seg)
        self.assertIn('camera_info.state.mode_rec', seg)

    def test_ipc_rec_guard(self):
        st = self.fn('shell_task')
        i = st.index('sh_ipc_req(SH_IPC_REC, 8000);')
        before, after = st[st.rindex('sh_hud(1);', 0, i):i], st[i:i + 80]
        self.assertIn('wb_wd_force = 1; wb_kick_now();', before)
        self.assertIn('if (*(volatile unsigned *)0x865c == 1) { sh_m1_restore_tables(); sh_expo_off(); sh_ipc_req(SH_IPC_M1_OFF, 5000); }', before)
        self.assertLess(before.index('wb_kick_now();'), before.index('0x865c == 1'))
        self.assertIn('wb_wd_force = 0;', after)

    def test_fc3c_reenter(self):
        st = self.fn('shell_task')
        i = st.index('sh_next_take()')
        seg = st[i:st.index('lv_x3();', i)]
        self.assertNotIn('sh_poke(0xfc3c', seg, 'pre-take: no blind [0xfc3c] poke')
        self.assertIn('slog("v184c fc3c reset=%d -> re-enter", *(volatile unsigned *)0xfc3c, 0);', seg)
        self.assertRegex(seg, r're-enter", \*\(volatile unsigned \*\)0xfc3c, 0\);\s*sh_m1_enter\(\);\s*if \(!sh_m1_ok\) continue;')

    def test_exit_sequence(self):
        st = self.fn('shell_task')
        o = st[st.index('out:'):]
        seq = ['wb_wd_force = 1; wb_kick_now();', 'sh_m1_leave();', 'msleep(400);', 'wb_wd_force = 0;', 'wb_wd_end();',
               'sh_ipc_req(SH_IPC_END', 'while (kbd_is_key_pressed(KEY_MENU) && get_tick_count() - t < 3000) msleep(20);',
               'sh_on = 0;', 'exit_alt();']
        pos = [o.index(s) for s in seq]
        self.assertEqual(pos, sorted(pos), 'exit order')

    def test_render_split(self):
        body = strip_comments(func_def(self.text, 'pv_render_m1'))
        self.assertEqual(self.text.count('static PV_HOT void pv_render_m1('), 1)
        self.assertIn('else if (st == 1) {', body)
        self.assertEqual(body.count('q[lb_hw]'), 2)
        self.assertIn('n += (W + 3) >> 2;', body)
        self.assertEqual(body.count('if (!(x & 3)) n--;'), 2)
        i = body.index('else if (st == 1) {'); j = body.index('} else {', i); k = body.index('else { M1_ROW(10', j)
        fast, peak = body[i:j], body[j:k]
        for bad in ('pk_prev', 'g_left', 'st == 2', 'do_peak && ', 'mx', '/'):
            self.assertNotIn(bad, fast, f'{bad} in the 10b fast row')
        for bad in ('st == 2', 'mx', '/', 'col_x'):
            self.assertNotIn(bad, peak, f'{bad} in the 10b peak row')
        self.assertIn('pk_prev[x] = (unsigned short)g; g_left = g;', peak)



class TestV185Dispatch(unittest.TestCase):
    """v185/v186: pv_m1_* dispatch cleanly between Wide 1:3 and 1:1 arbitrary-geometry renderers."""
    def test_dispatchers(self):
        text = C_SRC.read_text()
        for s in ('static void pv_m1_mask(int full) { if (sh_m1_wide()) pv_mask_opaque_wide(full, sh_m1_h()); else pv_mask_opaque(full, sh_m1_w(), sh_m1_h()); }',
                  'static void pv_m1_dflush(unsigned phys, unsigned lb, unsigned mode, int hr) { if (sh_m1_wide()) pv_dflush_m1_wide(phys, lb, mode, hr, sh_m1_w(), sh_m1_h()); else pv_dflush_m1(phys, lb, mode, hr, sh_m1_w(), sh_m1_h()); }',
                  'static void pv_m1_render(const char *frame, unsigned bpp, int hr) { if (sh_m1_wide()) pv_render_m1_wide(frame, bpp, hr, sh_m1_w(), sh_m1_h()); else pv_render_m1(frame, bpp, hr, sh_m1_w(), sh_m1_h()); }',
                  'static unsigned sh_m1_wide(void) { return sh_on && sh_prof()->kind == SH_M1 && sh_prof()->m1_wide; }'):
            self.assertIn(s, text)

if __name__ == '__main__':
    unittest.main(verbosity=2)
