#!/usr/bin/env python3
"""Host regression & contract test suite for m10cine.flt v182 + M10SHELL.LUA (no USB)."""
import os
import re
import struct
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
HOSTLUA = CHDK_TRUNK / 'tools/hostlua/lua'
HOSTLUAC = CHDK_TRUNK / 'tools/hostlua/luac'


def body_at(text: str, marker: str) -> str:
    start = text.index(marker)
    nl = text.index('\n', start)
    first = text.index('{', nl)
    depth = 1
    end = first + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[first:end]


def run_c(code: str, extra_flags=()):
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'test.c'
        exe = Path(d) / 'test'
        src.write_text(code)
        cmd = ['cc', '-std=c11', '-O2', '-Wall', '-Wextra', *extra_flags, str(src), '-o', str(exe)]
        subprocess.run(cmd, check=True)
        return subprocess.run([str(exe)], check=True, timeout=5, capture_output=True, text=True)


class TestV182Preview(unittest.TestCase):
    def test_pv_get10_get12_and_render_m1_asan(self):
        text = C_SRC.read_text()
        get10 = body_at(text, 'static inline unsigned pv_get10(')
        get12 = body_at(text, 'static inline unsigned pv_get12(')
        make_lut = body_at(text, 'static void pv_make_lut(')
        pv_fill = body_at(text, 'static void pv_fill(')
        pv_mask = body_at(text, 'static void pv_mask_opaque(')
        render_m1 = body_at(text, 'static PV_HOT void pv_render_m1(')   # v184a: PV_HOT scheduling attribute
        # v184a: fixed REC-view LUTs used by pv_render_m1 / pv_make_lut (copied verbatim from m10_cine.c)
        lut_decl = '\n'.join(re.search(p, text, re.M).group(0) for p in (
            r'^static unsigned pv_lut_r\[1024\][^\n]*', r'^static unsigned pv_m1_lut_ok\b[^\n]*'))
        sqrt_m1 = body_at(text, 'static unsigned pv_sqrt_m1(')
        build_luts = body_at(text, 'static void pv_build_m1_luts(')

        program = f'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PV_BW 360
#define PV_BLACK 0xFF000000u
#define PV_M1_X 46
#define PV_M1_W 268
#define PV_M1_H 200

static unsigned fake_rgba[PV_BW * 240];
#define PV_RGBA fake_rgba
static struct {{ int buffer_width; }} camera_screen = {{ 360 }};
static unsigned char pv_lut[1024];
static unsigned pv_stat[3] = {{ 0, 127, 300 }};
static volatile unsigned pv_mode = 0, pv_zebra = 1, pv_peak = 0, pv_clip_pct = 0;
static int refresh_n = 0;
static void vid_bitmap_refresh(void) {{ refresh_n++; }}
static int pv_ok(void) {{ return camera_screen.buffer_width == PV_BW; }}

#define PV_HOT
{lut_decl}
static unsigned pv_sqrt_m1(unsigned v)
{sqrt_m1}
static void pv_build_m1_luts(void)
{build_luts}

static inline unsigned pv_get10(const volatile unsigned short *p, unsigned c)
{get10}
static inline unsigned pv_get12(const volatile unsigned short *p, unsigned c)
{get12}
static void pv_make_lut(unsigned black, unsigned mean)
{make_lut}
static void pv_fill(unsigned y0, unsigned y1, unsigned x0, unsigned x1, unsigned v)
{pv_fill}
static void pv_mask_opaque(int full)
{pv_mask}
static PV_HOT void pv_render_m1(const char *frame, unsigned bpp, int half_res)
{render_m1}

static void pack_row_10(unsigned short *dst, const unsigned *vals, unsigned n) {{
    memset(dst, 0, n * 10 / 8);
    for (unsigned c = 0; c < n; c++) {{
        unsigned b = c * 10, w = b >> 4, sh = b & 15, v = vals[c] & 0x3ff;
        if (sh <= 6) {{
            dst[w] |= (unsigned short)(v << (6 - sh));
        }} else {{
            dst[w] |= (unsigned short)(v >> (sh - 6));
            dst[w + 1] |= (unsigned short)(v << (22 - sh));
        }}
    }}
}}
static void pack_row_12(unsigned short *dst, const unsigned *vals, unsigned n) {{
    memset(dst, 0, n * 12 / 8);
    for (unsigned c = 0; c < n; c++) {{
        unsigned b = c * 12, w = b >> 4, sh = b & 15, v = vals[c] & 0xfff;
        if (sh <= 4) {{
            dst[w] |= (unsigned short)(v << (4 - sh));
        }} else {{
            dst[w] |= (unsigned short)(v >> (sh - 4));
            dst[w + 1] |= (unsigned short)(v << (20 - sh));
        }}
    }}
}}

int main(void) {{
    /* 1. Bit-exact pv_get10 & pv_get12 round-trip */
    unsigned row10[64], row12[64];
    unsigned short buf10[64], buf12[64];
    for (unsigned i = 0; i < 64; i++) {{
        row10[i] = (i * 17 + 127) & 0x3ff;
        row12[i] = (i * 67 + 508) & 0xfff;
    }}
    pack_row_10(buf10, row10, 64);
    pack_row_12(buf12, row12, 64);
    for (unsigned i = 0; i < 64; i++) {{
        assert(pv_get10(buf10, i) == row10[i]);
        assert(pv_get12(buf12, i) == row12[i]);
    }}

    /* 2. Synthetic 1920x1440 10-bit RGGB frame:
     *    top-left: red, top-right: green, bottom-left: blue, bottom-right: clipped white */
    size_t lb10 = 1920 * 10 / 8;
    char *f10 = calloc(1440, lb10);
    unsigned tmp[1920];
    for (unsigned r = 0; r < 1440; r++) {{
        for (unsigned c = 0; c < 1920; c++) {{
            int top = r < 720, left = c < 960;
            unsigned ch = ((r & 1) << 1) | (c & 1); /* 0:R, 1:G1, 2:G2, 3:B */
            if (top && left)       tmp[c] = (ch == 0) ? 700 : 127;        /* Red */
            else if (top && !left) tmp[c] = (ch == 1 || ch == 2) ? 700 : 127; /* Green */
            else if (!top && left) tmp[c] = (ch == 3) ? 700 : 127;        /* Blue */
            else                   tmp[c] = 1022;                          /* Clipped */
        }}
        pack_row_10((unsigned short *)(f10 + r * lb10), tmp, 1920);
    }}

    pv_make_lut(127, 300);
    memset(fake_rgba, 0, sizeof(fake_rgba));
    pv_mode = 0;
    pv_mask_opaque(0);
    pv_render_m1(f10, 10, 0);

    /* Opaque pillarboxes and opaque image window */
    for (unsigned y = 20; y < 220; y++) {{
        for (unsigned x = 0; x < PV_M1_X; x++) assert(fake_rgba[y * PV_BW + x] == PV_BLACK);
        for (unsigned x = PV_M1_X + PV_M1_W; x < PV_BW; x++) assert(fake_rgba[y * PV_BW + x] == PV_BLACK);
        for (unsigned x = PV_M1_X; x < PV_M1_X + PV_M1_W; x++) assert((fake_rgba[y * PV_BW + x] >> 24) == 0xFF);
    }}
    /* Check R/G/B channel dominance in 0xAARRGGBB */
    unsigned px_r = fake_rgba[(20 + 40) * PV_BW + (PV_M1_X + 50)];
    unsigned px_g = fake_rgba[(20 + 40) * PV_BW + (PV_M1_X + 200)];
    unsigned px_b = fake_rgba[(20 + 150) * PV_BW + (PV_M1_X + 50)];
    assert(((px_r >> 16) & 0xff) > 150 && ((px_r >> 8) & 0xff) == 0 && (px_r & 0xff) == 0);
    assert(((px_g >> 8) & 0xff) > 150 && ((px_g >> 16) & 0xff) == 0 && (px_g & 0xff) == 0);
    assert((px_b & 0xff) > 150 && ((px_b >> 16) & 0xff) == 0 && ((px_b >> 8) & 0xff) == 0);
    assert(pv_clip_pct >= 20 && pv_clip_pct <= 30);

    /* Half-res 2x2 REC preview */
    pv_render_m1(f10, 10, 1);
    unsigned px_h = fake_rgba[(20 + 40) * PV_BW + (PV_M1_X + 50)];
    assert(px_h == fake_rgba[(20 + 41) * PV_BW + (PV_M1_X + 51)]);
    assert(((px_h >> 16) & 0xff) > 150);

    /* 1:1 focus zoom mode */
    pv_mode = 1;
    pv_render_m1(f10, 10, 0);
    for (unsigned y = 20; y < 220; y++)
        for (unsigned x = PV_M1_X; x < PV_M1_X + PV_M1_W; x++)
            assert((fake_rgba[y * PV_BW + x] >> 24) == 0xFF);

    /* OFF mode */
    pv_mode = 2;
    pv_mask_opaque(1);
    for (unsigned y = 20; y < 220; y++)
        for (unsigned x = 0; x < PV_BW; x++)
            assert(fake_rgba[y * PV_BW + x] == PV_BLACK);

    /* 12-bit frame */
    size_t lb12 = 1920 * 12 / 8;
    char *f12 = calloc(1440, lb12);
    for (unsigned r = 0; r < 1440; r++) {{
        for (unsigned c = 0; c < 1920; c++) {{
            unsigned ch = ((r & 1) << 1) | (c & 1);
            tmp[c] = (ch == 0) ? 2800 : 508;
        }}
        pack_row_12((unsigned short *)(f12 + r * lb12), tmp, 1920);
    }}
    pv_mode = 0;
    pv_make_lut(127, 300);
    pv_render_m1(f12, 12, 1);
    unsigned px12 = fake_rgba[(20 + 100) * PV_BW + (PV_M1_X + 100)];
    assert(((px12 >> 16) & 0xff) > 150 && ((px12 >> 8) & 0xff) == 0 && (px12 & 0xff) == 0);

    /* HDMI guard */
    memset(fake_rgba, 0x55, sizeof(fake_rgba));
    camera_screen.buffer_width = 480;
    pv_mask_opaque(1);
    pv_render_m1(f10, 10, 0);
    assert(fake_rgba[30 * PV_BW + 2] == 0x55555555u);

    free(f10);
    free(f12);
    printf("preview ok\\n");
    return 0;
}}
'''
        res = run_c(program, extra_flags=['-fsanitize=address,undefined'])
        self.assertIn('preview ok', res.stdout)


class TestV182WatchdogAndRoll(unittest.TestCase):
    def test_wb_watchdog_policy(self):
        text = C_SRC.read_text()
        body = body_at(text, 'static void wb_wd_task(void)')
        # Extract the loop condition & body and run deterministic tick simulation
        self.assertIn('(now - t5c > lim || now - t58 > lim) && now - wb_last_kick_ms > gap', body)
        self.assertIn('int rec = !sh_on || sh_rec_on;', body)
        self.assertIn('unsigned lim = rec ? 1200 : 600, gap = rec ? 900 : 500;', body)
        # Verify wb_kick_due is called on ring-full drop path
        self.assertIn('if (wb_due) wb_kick_due(fr);', text)
        # Verify _module_can_unload guards M10WB and M10Pv
        self.assertIn('!wb_wd_on && pv_rec_done', text)
        # Verify stacks bumped to 0x2000
        self.assertIn('CreateTask("M10Shell", 0x1A, 0x2000, shell_task);', text)
        self.assertIn('CreateTask("M10Cine", 0x1A, 0x2000, cine_task);', text)
        self.assertIn('CreateTask("M10XR", 0x1C, 0x2000, xr_task);', text)
        # Verify LockMainPower / UnlockMainPower 1.10d addresses
        self.assertIn('#define FN_LOCK_PWR    0xfc1fb48d', text)
        self.assertIn('#define FN_UNLOCK_PWR  0xfc1fb425', text)

    def test_sh_recipe_m1_fields(self):
        text = C_SRC.read_text()
        m = re.search(r'#define SH_RECIPE_M1 "([^"]+)"', text)
        self.assertIsNotNone(m)
        fields = m.group(1).replace('\\n', '').split()
        self.assertEqual(len(fields), 58)  # 58 space-separated tokens = fields 1..58? Wait let's check SH_RECIPE count!
        m_ref = re.search(r'#define SH_RECIPE "([^"]+)"', text)
        self.assertIsNotNone(m_ref)
        ref_fields = m_ref.group(1).replace('\\n', '').split()
        self.assertEqual(len(fields), len(ref_fields), f'M1 has {len(fields)} fields vs SH_RECIPE {len(ref_fields)}')
        self.assertEqual(fields[0], '3000')
        self.assertEqual(fields[1], '1440')
        self.assertEqual(fields[2], '10')
        self.assertEqual(int(fields[5]), 0x21000980)
        self.assertEqual(fields[7], '80000003')
        self.assertEqual(fields[8], '35166')
        self.assertEqual(fields[9], '39166')
        self.assertEqual(fields[11], '1436')
        self.assertEqual(fields[-2], '10')   # RSEL 0x10
        self.assertEqual(fields[-1], '1')    # x_he_fix = 1

    def test_mlv_finalize_multichunk_no_stdio(self):
        text = C_SRC.read_text()
        fin = body_at(text, 'static void mlv_finalize(')
        self.assertNotIn('fopen', fin)
        self.assertIn('O_RDWR', fin)

        program = f'''
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static unsigned xr_fileno = 2, xr_wr = 1500, xr_chunk_start = 1480;
static unsigned xr_fcount[16] = {{ 740, 740, 0 }};
static int xr_fd = -1;
static char xr_base[128];
static unsigned char mlv_hdr[512];
static void put16(unsigned char *p, unsigned v) {{ p[0] = v; p[1] = v >> 8; }}
static void put32(unsigned char *p, unsigned v) {{ p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }}
static void mlv_build_hdr(unsigned w, unsigned h, unsigned bpp, unsigned nframes) {{
    (void)w; (void)h; (void)bpp;
    memset(mlv_hdr, 0, 512);
    memcpy(mlv_hdr, "MLVI", 4);
    put32(mlv_hdr + 36, nframes);
}}
static void mlv_finalize(unsigned w, unsigned h, unsigned bpp, int lj_class)
{fin}

int main(void) {{
    char dir[] = "/tmp/m10fin_XXXXXX";
    assert(mkdtemp(dir) != NULL);
    assert(chdir(dir) == 0);
    strcpy(xr_base, "T");
    const char *names[3] = {{ "T.MLV", "T.M00", "T.M01" }};
    unsigned char z[512] = {{0}};
    for (int i = 0; i < 3; i++) {{
        int f = open(names[i], O_WRONLY | O_CREAT | O_TRUNC, 0666);
        assert(f >= 0);
        assert(write(f, z, 512) == 512);
        if (i < 2) close(f); else xr_fd = f;
    }}
    mlv_finalize(1920, 1440, 14, 1);
    assert(xr_fd == -1);
    unsigned want_cnt[3] = {{ 740, 740, 20 }};
    for (int i = 0; i < 3; i++) {{
        unsigned char b[512];
        int f = open(names[i], O_RDONLY);
        assert(f >= 0 && read(f, b, 512) == 512);
        close(f);
        assert(memcmp(b, "MLVI", 4) == 0);
        assert((unsigned)(b[24] | (b[25] << 8)) == (unsigned)i);
        assert((unsigned)(b[26] | (b[27] << 8)) == 3u);
        unsigned vc = (unsigned)b[36] | ((unsigned)b[37] << 8) | ((unsigned)b[38] << 16) | ((unsigned)b[39] << 24);
        assert(vc == want_cnt[i]);
        assert((unsigned)(b[32] | (b[33] << 8)) == 0x21u);
        unlink(names[i]);
    }}
    assert(chdir("/tmp") == 0);
    rmdir(dir);
    printf("finalize ok\\n");
    return 0;
}}
'''
        res = run_c(program)
        self.assertIn('finalize ok', res.stdout)


class TestV182LuaAndIPCContract(unittest.TestCase):
    def test_c_lua_ipc_constants_match(self):
        c_txt = C_SRC.read_text()
        lua_txt = LUA_SRC.read_text()
        for name, val in [
            ('SH_IPC_REQ_OFF', '0x220'),
            ('SH_IPC_ACK_OFF', '0x224'),
            ('SH_IPC_M1_ON', '1'),
            ('SH_IPC_M1_OFF', '2'),
            ('SH_IPC_REC', '3'),
            ('SH_IPC_PLAY', '4'),
            ('SH_IPC_END', '0xE0'),
        ]:
            self.assertRegex(c_txt, rf'#define\s+{name}\s+{re.escape(val)}\b')
        self.assertIn('local REQ_OFF     = 0x220', lua_txt)
        self.assertIn('local ACK_OFF     = 0x224', lua_txt)
        self.assertIn('local REQ_END     = 0xE0', lua_txt)
        self.assertIn('local HANDLERS = { [1] = m1_on, [2] = m1_off, [3] = do_rec, [4] = do_play', lua_txt)

    def test_lua_syntax_and_mock_lifecycle(self):
        if not (HOSTLUA.exists() and HOSTLUAC.exists()):
            self.skipTest('hostlua missing (set M10_CHDK to a CHDK checkout)')
        subprocess.run([str(HOSTLUAC), '-p', str(LUA_SRC)], check=True)
        harness = f'''
local mem = {{}}
local HOOK = 0x12340000
local files = {{}}
local calls = {{}}
local stat_during_loop = 0
local in_loop = false
local tick = 0
local rec_mode = false
local alt_exited = false

mem[0x3e8c70] = 0x41f0e92d
mem[0x9b50] = 0x121
mem[0x865c] = 36   -- start in Film mode!
mem[0xe664] = 3
mem[0xfc3c] = 24
mem[0xfa84] = 0

function peek(a) return mem[a] or 0 end
function poke(a, v) mem[a] = v end
if not bitand then
  local function bits32(x)
    local t = {{}}
    local neg = x < 0
    if neg then x = -1 - x end
    for i = 1, 31 do
      local b = x % 2
      t[i] = neg and (1 - b) or b
      x = (x - b) / 2
    end
    t[32] = neg and 1 or 0
    return t
  end
  local function from32(t)
    local v, p = 0, 1
    if t[32] == 1 then
      for i = 1, 31 do if t[i] == 0 then v = v + p end; p = p * 2 end
      return -1 - v
    else
      for i = 1, 31 do if t[i] == 1 then v = v + p end; p = p * 2 end
      return v
    end
  end
  function bitand(a, b)
    local ta, tb, tr = bits32(a), bits32(b), {{}}
    for i = 1, 32 do tr[i] = (ta[i] == 1 and tb[i] == 1) and 1 or 0 end
    return from32(tr)
  end
  function bitor(a, b)
    local ta, tb, tr = bits32(a), bits32(b), {{}}
    for i = 1, 32 do tr[i] = (ta[i] == 1 or tb[i] == 1) and 1 or 0 end
    return from32(tr)
  end
  function bitnot(a) return -1 - a end
  function bitshl(a, n)
    local ta, tr = bits32(a), {{}}
    for i = 1, 32 do tr[i] = (i > n) and ta[i - n] or 0 end
    return from32(tr)
  end
end

function get_tick_count() return tick end
function get_usb_power(x) return 0 end
function get_mode() return rec_mode end
function set_record(v) rec_mode = v; table.insert(calls, "set_record:" .. tostring(v)) end
function is_pressed(k) return false end
function press(k) table.insert(calls, "press:" .. k) end
function release(k) table.insert(calls, "release:" .. k) end
function draw_string(...) end
function draw_clear() end
function set_exit_key(k) end
function exit_alt() alt_exited = true end
package.loaded["capmode"] = {{ get_name = function() return mem[0x865c] == 3 and "M" or "VIDEO_STD" end }}

local real_open = io.open
io.open = function(p, m)
  if in_loop then stat_during_loop = stat_during_loop + 1 end
  if m == "w" then
    files[p] = ""
    return {{ write = function(self, ...) files[p] = files[p] .. table.concat({{...}}) end, close = function() end }}
  elseif m == "r" then
    if not files[p] then return nil end
    return {{ read = function() return files[p] end, close = function() end }}
  end
  return nil
end
os.stat = function(p)
  if in_loop then stat_during_loop = stat_during_loop + 1 end
  return files[p] and {{ size = #files[p] }} or nil
end
os.remove = function(p) files[p] = nil end

local step = 0
function sleep(ms)
  tick = tick + ms
  step = step + 1
  -- Simulate user turning dial from Film (36) -> Photo M (3) after 2 wait iterations
  if step == 3 and mem[0x865c] == 36 then mem[0x865c] = 3 end
  -- Once in main IPC loop, drive: idle ticks -> m1_on (1) -> idle REC ticks -> m1_off (2) -> end (0xE0)
  if in_loop then
    if step == 20 then mem[HOOK + 0x224] = 0; mem[HOOK + 0x220] = 1 end
    if step == 35 then
      assert(bitand(mem[HOOK + 0x224], 0x3ff) == 0x301, "m1_on ack failed: " .. tostring(mem[HOOK + 0x224]))
      assert(mem[0x865c] == 1 and mem[0xfc3c] == 2073, "m1_on state wrong")
    end
    if step == 40 then mem[HOOK + 0x224] = 0; mem[HOOK + 0x220] = 2 end
    if step == 50 then
      assert(bitand(mem[HOOK + 0x224], 0x3ff) == 0x302, "m1_off ack failed: " .. tostring(mem[HOOK + 0x224]))
      assert(mem[0x865c] == 3 and mem[0xfc3c] == 24, "m1_off restore wrong")
      mem[HOOK + 0x224] = 0; mem[HOOK + 0x220] = 0xE0
      in_loop = false
    end
  end
end

function call_func_ptr(fn, a1, a2)
  if fn == 0x3e8c71 then
    assert(a1 == "m10cine.flt")
    -- Module installs siohook6
    mem[HOOK + 0x200] = 0x364f4953
    mem[0x9b50] = HOOK + 0x11
    in_loop = true
    return 0
  elseif fn == 0xfc38d3f1 then return 0x20000000
  elseif fn == 0xfc0dc01d then table.insert(calls, "MV_STOP"); return 0
  elseif fn == 0xfc0dbfc9 then table.insert(calls, "MV_START"); return 0
  elseif fn == 0xfc1efc0d then table.insert(calls, "STOP_MODE"); return 0
  elseif fn == 0xfc1efb33 then mem[0x865c] = a1; table.insert(calls, "CHG_MODE:" .. tostring(a1)); return 0
  elseif fn == 0xfc414d25 then table.insert(calls, "CDS_WRITE"); return 0
  end
  return 0
end

dofile("{LUA_SRC}")
assert(alt_exited, "exit_alt not called")
assert(stat_during_loop == 0, "FS access during IPC loop: " .. tostring(stat_during_loop))
assert(not files["A/M10SH.CFG"], "M10SH.CFG not cleaned up")
assert(bitand(mem[HOOK + 0x224], 0x1ff) == 0x1E0, "REQ_END ack missing")
print("lua mock ok, calls=" .. #calls)
'''
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'run_mock.lua'
            p.write_text(harness)
            res = subprocess.run([str(HOSTLUA), str(p)], check=True, capture_output=True, text=True, timeout=10)
            self.assertIn('lua mock ok', res.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
