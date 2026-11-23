"""Host tests (including compiled C under ASan+UBSan) for v186:
- Magic Lantern-style Size x Bit-Depth selector (10 ImgMode 1 profiles, sh_bpp 14/12/10,
  auto-clamp on SIZE change, skip unsupported on BIT step, zero sensor re-switch on BIT change)
- Generalized ImgMode 1 colour preview (pv_render_m1, pv_render_m1_wide, pv_dflush_m1,
  pv_mask_opaque) across 10/12/14-bit (including 3-halfword 14-bit pairs!), arbitrary W x H,
  FIT aspect-ratio letterboxing/pillarboxing, 1:1 720x400 focus zoom, and BIT-bar ylim=200
- LCLK_HOLD0 + ClockSave balanced turbo holds, dynamic x_lo/x_hi, lj_raw_n=3 for >4 MiB
"""
import os
import re
import subprocess
import tempfile
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
_PUB = os.path.join(BASE, '..', 'module', 'm10_cine.c')
SRC = _PUB if os.path.exists(_PUB) else os.path.join(BASE, '..', 'src', 'chdk', 'trunk', 'modules', 'm10_cine.c')


def _read_src():
    with open(SRC, encoding='utf-8', errors='replace') as fh:
        return fh.read()


def _extract_fn(src, sig_prefix):
    # Skip forward declarations ending with ';' — find the actual definition with '{'
    pos = 0
    while True:
        idx = src.index(sig_prefix, pos)
        eol = src.index('\n', idx)
        line = src[idx:eol]
        if ';' in line and '{' not in line:
            pos = eol + 1
            continue
        break
    b = src.index('{', idx)
    depth = 0
    for i in range(b, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[idx:i + 1]
    raise RuntimeError(f'unbalanced braces for {sig_prefix}')


def _extract_macro(src, name):
    pat = re.compile(rf'^#define\s+{name}\b(?:[^\n]*\\\n)*[^\n]*', re.M)
    m = pat.search(src)
    assert m, f'missing macro {name}'
    return m.group(0)


class TestV186Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read_src()

    def test_ml_profiles_table(self):
        m = re.search(r'static const sh_prof_t sh_profs\[\]\s*=\s*\{(.*?)\};', self.src, re.S)
        self.assertIsNotNone(m)
        rows = re.findall(r'\{\s*(\d+),\s*(\d+),\s*0x([0-9a-fA-F]+),\s*SH_M1,\s*(\d+),\s*(\d+),\s*0,\s*(\d+),\s*"([^"]+)",\s*(\d+),\s*(\d+),\s*(\d+),\s*0x([0-9a-fA-F]+),\s*0x([0-9a-fA-F]+),\s*(\d+),\s*"([^"]+)"\s*\}', m.group(1))
        self.assertEqual(len(rows), 10)
        # Check optical centring, lclk-x1 >= 54, short_tag <= 8 chars, and 10b-only bitmask on rows 8,9
        for idx, r in enumerate(rows):
            fps, bpp, rsel, fl, per, w, tag, h, lclk, wide, x0, c7, mask, short_tag = (
                int(r[0]), int(r[1]), int(r[2], 16), int(r[3]), int(r[4]), int(r[5]), r[6],
                int(r[7]), int(r[8]), int(r[9]), int(r[10], 16), int(r[11], 16), int(r[12]), r[13]
            )
            self.assertEqual(rsel, 0x10)
            self.assertEqual(w % 16, 0)
            self.assertGreaterEqual(x0, 0x30)
            self.assertGreaterEqual(lclk - (x0 + w // 4), 54, tag)
            self.assertLessEqual(len(short_tag), 8, short_tag)
            if idx < 8:
                self.assertEqual(mask, 7, tag)
            else:
                self.assertEqual(mask, 1, tag)   # 2.3K 3:2 & 2.6K 1.8: 10b only

    def test_turbo_clock_holds_balanced(self):
        self.assertIn('#define FN_LCLK_HOLD0   0xfc1803f3', self.src)
        self.assertIn('#define FN_LCLK_REL0    0xfc180429', self.src)
        self.assertIn('#define FN_CLKSAVE_TAKE 0xfc1ec6d7', self.src)
        self.assertIn('#define FN_CLKSAVE_REL  0xfc1ec6ed', self.src)
        lv = _extract_fn(self.src, 'static void lv_x3(')
        self.assertIn('FN_LCLK_HOLD0', lv)
        self.assertIn('FN_LCLK_REL0', lv)
        self.assertIn('FN_CLKSAVE_TAKE', lv)
        self.assertIn('FN_CLKSAVE_REL', lv)
        self.assertIn('turbo_held', lv)

    def test_exmem_3raw_above_4mib(self):
        lv = _extract_fn(self.src, 'static void lv_x3(')
        self.assertIn('if (x_m1 && xr_fb > 0x00400000)', lv)
        self.assertIn('lvn_bpp == 14 && enc_fb > 0x00400000', lv)

    def test_hud_nfield7_and_bit_bar(self):
        self.assertIn('#define SH_NFIELD 7', self.src)
        hud = _extract_fn(self.src, 'static void sh_hud(')
        self.assertIn('if (sh_field == 4)', hud)
        self.assertIn('COLOR_GREY_DK', hud)
        nav = _extract_fn(self.src, 'static int sh_handle_nav(')
        self.assertIn('sh_bpp_clamp(sh_prof())', nav)
        self.assertIn('sh_bpp_step(sh_prof(), d)', nav)
        self.assertIn('if (of == 4 && sh_field != 4)', nav)

    def test_sentinel_top_hud_bar(self):
        stby = _extract_fn(self.src, 'static void pv_stby_task(')
        self.assertIn('PV_RGBA[1 * PV_BW + 358] != PV_BLACK', stby)


class TestV186CompiledAsan(unittest.TestCase):
    def test_render_dflush_and_ml_selector_asan(self):
        src = _read_src()
        # Extract typedef sh_prof_t + sh_profs + bpp helpers + geom + preview functions directly from m10_cine.c
        m_prof = re.search(r'typedef struct \{[^{}]*const char \*short_tag;[^{}]*\} sh_prof_t;', src, re.S)
        m_arr = re.search(r'static const sh_prof_t sh_profs\[\]\s*=\s*\{.*?\};', src, re.S)
        assert m_prof and m_arr
        pieces = [
            m_prof.group(0),
            '#define SH_X5 0\n#define SH_X3 1\n#define SH_M1 2',
            m_arr.group(0),
            '#define SH_NPROF (sizeof(sh_profs) / sizeof(sh_profs[0]))',
            'static volatile unsigned sh_field = 0, sh_bpp = 14, sh_rec_on = 0;',
            _extract_fn(src, 'static int sh_bpp_ok('),
            _extract_fn(src, 'static void sh_bpp_clamp('),
            _extract_fn(src, 'static void sh_bpp_step('),
            _extract_fn(src, 'static unsigned sh_m1_geom('),
            '#define PV_BW 360\n#define PV_BLACK 0xFF000000u\n#define PV_HOT',
            'static unsigned fake_rgba[PV_BW * 240];\n#define PV_RGBA fake_rgba',
            'static unsigned pv_stat[3];\nstatic volatile unsigned pv_mode = 0, pv_zebra = 1, pv_peak = 0, pv_clip_pct = 0;',
            'static unsigned pv_lut_r[1024], pv_lut_g[1024], pv_lut_b[1024];\nstatic unsigned pv_m1_lut_ok = 0;',
            'static int pv_ok(void) { return 1; }\nstatic void vid_bitmap_refresh(void) {}',
            'static unsigned df_min = 0xffffffffu, df_max = 0, df_calls = 0;',
            'typedef void (*fn2)(unsigned, unsigned);',
            'static void fake_dflush(unsigned addr, unsigned len) { assert((addr & 31u) == 0); assert((len & 31u) == 0); if (addr < df_min) df_min = addr; if (addr + len > df_max) df_max = addr + len; df_calls++; }',
            '#define FN_DFLUSH fake_dflush',
            _extract_fn(src, 'static unsigned pv_sqrt_m1('),
            _extract_fn(src, 'static void pv_build_m1_luts('),
            _extract_fn(src, 'static void pv_fill('),
            _extract_fn(src, 'static void pv_m1_rect('),
            _extract_fn(src, 'static unsigned pv_m1_ylim('),
            _extract_fn(src, 'static void pv_mask_opaque('),
            _extract_macro(src, 'M1_ROW'),
            _extract_fn(src, 'static PV_HOT void pv_render_m1('),
            '#undef M1_ROW',
            _extract_fn(src, 'static void pv_dflush_m1('),
            _extract_fn(src, 'static void pv_mask_opaque_wide('),
            _extract_fn(src, 'static PV_HOT void pv_render_m1_wide('),
            _extract_fn(src, 'static void pv_dflush_m1_wide('),
        ]
        # Replace ((fn2)FN_DFLUSH) calls cleanly for host compilation
        code_body = '\n'.join(pieces).replace('((fn2)FN_DFLUSH)', 'fake_dflush')

        harness = f"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

{code_body}

static void pack_row(unsigned short *dst, const unsigned *vals, unsigned n, unsigned bpp) {{
    unsigned lb = n * bpp / 8;
    unsigned mask = (1u << bpp) - 1u;
    memset(dst, 0, lb);
    for (unsigned c = 0; c < n; c++) {{
        unsigned b = c * bpp, w = b >> 4, sh = b & 15, v = vals[c] & mask;
        if (sh + bpp <= 16) {{
            dst[w] |= (unsigned short)(v << (16 - sh - bpp));
        }} else {{
            unsigned hi = 16 - sh;
            unsigned lo = bpp - hi;
            dst[w] |= (unsigned short)(v >> lo);
            dst[w + 1] |= (unsigned short)(v << (16 - lo));
        }}
    }}
}}

static void test_geom(unsigned raw_w, unsigned raw_h, unsigned bpp, int wide) {{
    unsigned lb = raw_w * bpp / 8;
    unsigned bl = (bpp == 14) ? 2048u : (bpp == 12) ? 508u : 127u;
    unsigned hi = (bpp == 14) ? 11200u : (bpp == 12) ? 2800u : 700u;
    unsigned clp = (bpp == 14) ? 16350u : (bpp == 12) ? 4090u : 1022u;
    /* Exact frame buffer size (NO padding): ASan catches any out-of-bounds halfword read! */
    char *frame = (char *)malloc((size_t)raw_h * lb);
    unsigned *row = (unsigned *)malloc(raw_w * sizeof(unsigned));
    assert(frame && row);
    for (unsigned r = 0; r < raw_h; r++) {{
        int top = r < raw_h / 2;
        for (unsigned c = 0; c < raw_w; c++) {{
            int left = c < raw_w / 2;
            unsigned ch = ((r & 1u) << 1) | (c & 1u);
            if (top && left)       row[c] = (ch == 0) ? hi : bl;
            else if (top && !left) row[c] = (ch == 1 || ch == 2) ? hi : bl;
            else if (!top && left) row[c] = (ch == 3) ? hi : bl;
            else                   row[c] = clp;
        }}
        pack_row((unsigned short *)(frame + (size_t)r * lb), row, raw_w, bpp);
    }}

    /* 1. FIT mode (pv_mode = 0), full res & half res */
    pv_mode = 0; pv_peak = 0; pv_zebra = 1; sh_field = 0; sh_rec_on = 0;
    memset(fake_rgba, 0, sizeof(fake_rgba));
    if (wide) {{
        pv_mask_opaque_wide(0, raw_h);
        pv_render_m1_wide(frame, bpp, 0, raw_w, raw_h);
    }} else {{
        pv_mask_opaque(0, raw_w, raw_h);
        pv_render_m1(frame, bpp, 0, raw_w, raw_h);
    }}
    unsigned ox = 0, oy = 20, ow = PV_BW, oh = 200;
    if (wide) {{ oh = raw_h > 1440 ? 124 : 100; oy = 20 + (200 - oh) / 2; }}
    else pv_m1_rect(raw_w, raw_h, &ox, &oy, &ow, &oh);
    /* Every pixel in rows 20..219 is fully opaque */
    for (unsigned y = 20; y < 220; y++)
        for (unsigned x = 0; x < PV_BW; x++)
            assert((fake_rgba[y * PV_BW + x] >> 24) == 0xFF);
    /* Verify R, G, B quadrants inside the fitted image rect */
    unsigned px_r = fake_rgba[(oy + oh / 4) * PV_BW + (ox + ow / 4)];
    unsigned px_g = fake_rgba[(oy + oh / 4) * PV_BW + (ox + 3 * ow / 4)];
    unsigned px_b = fake_rgba[(oy + 3 * oh / 4) * PV_BW + (ox + ow / 4)];
    /* 14-bit black=2048 >> 4 = 128 vs LUT black=127 -> minor floor <= 10 */
    assert(((px_r >> 16) & 0xff) > 150 && ((px_r >> 8) & 0xff) < 12 && (px_r & 0xff) < 12);
    assert(((px_g >> 8) & 0xff) > 150 && ((px_g >> 16) & 0xff) < 12 && (px_g & 0xff) < 12);
    assert((px_b & 0xff) > 150 && ((px_b >> 16) & 0xff) < 12 && ((px_b >> 8) & 0xff) < 12);
    assert(pv_clip_pct >= 20 && pv_clip_pct <= 30);

    /* Half-res REC preview */
    if (wide) pv_render_m1_wide(frame, bpp, 1, raw_w, raw_h);
    else pv_render_m1(frame, bpp, 1, raw_w, raw_h);

    /* 2. 1:1 focus zoom (pv_mode = 1) + peaking */
    pv_mode = 1; pv_peak = 1;
    if (wide) pv_render_m1_wide(frame, bpp, 0, raw_w, raw_h);
    else pv_render_m1(frame, bpp, 0, raw_w, raw_h);

    /* 3. BIT selector bar active (sh_field == 4, standby): rows 200..219 MUST stay untouched! */
    sh_field = 4; sh_rec_on = 0; pv_mode = 1;
    for (unsigned y = 200; y < 220; y++)
        for (unsigned x = 0; x < PV_BW; x++)
            fake_rgba[y * PV_BW + x] = 0xDEADCAFEu;
    if (wide) pv_render_m1_wide(frame, bpp, 0, raw_w, raw_h);
    else pv_render_m1(frame, bpp, 0, raw_w, raw_h);
    for (unsigned y = 200; y < 220; y++)
        for (unsigned x = 0; x < PV_BW; x++)
            assert(fake_rgba[y * PV_BW + x] == 0xDEADCAFEu);

    /* 4. dflush bounds check (aligned, within frame + 32B cache line rounding) */
    for (unsigned m = 0; m < 2; m++) {{
        for (int hr = 0; hr < 2; hr++) {{
            df_min = 0xffffffffu; df_max = 0; df_calls = 0;
            unsigned base = 0x41000000u;
            if (wide) pv_dflush_m1_wide(base, lb, m, hr, raw_w, raw_h);
            else pv_dflush_m1(base, lb, m, hr, raw_w, raw_h);
            assert(df_calls > 0);
            assert(df_min >= base);
            assert(df_max <= base + ((raw_h * lb + 31u) & ~31u));
        }}
    }}

    free(row);
    free(frame);
}}

int main(void) {{
    /* ML-style Size x Bit-Depth state machine */
    assert(SH_NPROF == 10);
    sh_bpp = 14;
    const sh_prof_t *p0 = &sh_profs[0];   /* 1440 4:3, mask=7 */
    const sh_prof_t *p8 = &sh_profs[8];   /* 2.3K 3:2, mask=1 (10b only) */
    assert(sh_bpp_ok(p0, 14) && sh_bpp_ok(p0, 12) && sh_bpp_ok(p0, 10));
    assert(!sh_bpp_ok(p8, 14) && !sh_bpp_ok(p8, 12) && sh_bpp_ok(p8, 10));
    /* RIGHT steps 14 -> 12 -> 10, clamped at 10 */
    sh_bpp_step(p0, +1); assert(sh_bpp == 12);
    sh_bpp_step(p0, +1); assert(sh_bpp == 10);
    sh_bpp_step(p0, +1); assert(sh_bpp == 10);
    /* LEFT steps 10 -> 12 -> 14, clamped at 14 */
    sh_bpp_step(p0, -1); assert(sh_bpp == 12);
    sh_bpp_step(p0, -1); assert(sh_bpp == 14);
    sh_bpp_step(p0, -1); assert(sh_bpp == 14);
    /* Changing SIZE to 10b-only clamps 14 -> 10, stepping stays at 10 */
    sh_bpp_clamp(p8); assert(sh_bpp == 10);
    sh_bpp_step(p8, -1); assert(sh_bpp == 10);
    sh_bpp_step(p8, +1); assert(sh_bpp == 10);
    /* sh_m1_geom does not depend on sh_bpp */
    unsigned g0 = sh_m1_geom(p0);
    sh_bpp = 10; assert(sh_m1_geom(p0) == g0);
    sh_bpp = 14; assert(sh_m1_geom(p0) == g0);
    /* Distinct geometries have distinct sh_m1_geom */
    for (unsigned i = 0; i < SH_NPROF; i++)
        for (unsigned j = i + 1; j < SH_NPROF; j++)
            assert(sh_m1_geom(&sh_profs[i]) != sh_m1_geom(&sh_profs[j]));

    /* ASan/UBSan test across ALL 10 v186 profiles and all supported bit depths! */
    for (unsigned i = 0; i < SH_NPROF; i++) {{
        const sh_prof_t *p = &sh_profs[i];
        static const unsigned bpps[3] = {{ 14, 12, 10 }};
        for (unsigned k = 0; k < 3; k++) {{
            if (!sh_bpp_ok(p, bpps[k])) continue;
            test_geom(p->w, p->h, bpps[k], p->m1_wide);
        }}
    }}
    printf("v186_asan_all_10_profiles_ok\\n");
    return 0;
}}
"""
        with tempfile.TemporaryDirectory() as td:
            cpath = os.path.join(td, 'test_v186.c')
            bpath = os.path.join(td, 'test_v186')
            open(cpath, 'w').write(harness)
            subprocess.run(
                ['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                 '-fsanitize=address,undefined', '-fno-sanitize-recover=undefined',
                 cpath, '-o', bpath],
                check=True,
            )
            out = subprocess.check_output([bpath], text=True)
            self.assertIn('v186_asan_all_10_profiles_ok', out)


if __name__ == '__main__':
    unittest.main()
