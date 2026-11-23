#!/usr/bin/env python3
"""Host regression & contract test suite for m10cine.flt v183 + M10SHELL.LUA (no USB).

v183: focus peaking in the ImgMode 1 standby preview, SH_RECIPE_M1 retune (x_pbl 220; v183b: 350),
IPC 5 = do_af (Canon Hybrid CMOS AF II one-shot dip into Photo M), jitter-free VIDF timestamps.
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
HOSTLUA = CHDK_TRUNK / 'tools/hostlua/lua'
HOSTLUAC = CHDK_TRUNK / 'tools/hostlua/luac'

PEAK_PX = 0xFF00FF40
ZEBRA_PX = 0xFFFF2800


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


def func_def(text: str, name: str):
    """Full definition (signature + body) of a top-level `static ... name(...)` function, or None."""
    for m in re.finditer(rf'^static[^\n;{{]*\b{name}\s*\(', text, re.M):
        nl = text.find('\n', m.end())
        line_tail = text[m.end():nl] if nl >= 0 else text[m.end():]
        if ';' in line_tail.split('//')[0]:
            continue   # prototype
        brace = text.find('{', nl if nl >= 0 else m.end())
        if brace < 0:
            continue
        depth, end = 1, brace + 1
        while depth:
            depth += (text[end] == '{') - (text[end] == '}')
            end += 1
        return text[m.start():end]
    return None


def run_c(code: str, extra_flags=()):
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / 'test.c'
        exe = Path(d) / 'test'
        src.write_text(code)
        cmd = ['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Wno-unused-function', '-Wno-unused-variable',
               *extra_flags, str(src), '-o', str(exe)]
        subprocess.run(cmd, check=True)
        return subprocess.run([str(exe)], check=True, timeout=20, capture_output=True, text=True)


def recipe_fields(text: str, name: str):
    m = re.search(rf'^#define\s+{name}\b(?:[^\n]*\\\n)*[^\n]*', text, re.M)
    assert m, f'{name} missing'
    joined = ''.join(re.findall(r'"([^"]*)"', m.group(0)))
    return joined.replace('\\n', '').split()


# ---------------------------------------------------------------------------------------------------
class TestV183Peaking(unittest.TestCase):
    HARNESS_KNOWN = {'pv_get10', 'pv_get12', 'pv_make_lut', 'pv_fill', 'pv_m1_rect', 'pv_m1_ylim', 'pv_mask_opaque', 'pv_render_m1',
                     'pv_ok', 'pv_lut', 'pv_stat', 'pv_mode', 'pv_zebra', 'pv_clip_pct',
                     'pv_lut_r', 'pv_lut_g', 'pv_lut_b', 'pv_m1_lut_ok'}   # v184a: declared verbatim below

    def _support(self, text: str, render: str):
        """Helper pv_* functions / globals / PV_* macros the v183 render body references."""
        funcs, globs, seen = [], [], set(self.HARNESS_KNOWN)
        todo = [render]
        while todo:
            src = todo.pop()
            for ident in sorted(set(re.findall(r'\bpv_\w+', src))):
                if ident in seen:
                    continue
                seen.add(ident)
                d = func_def(text, ident)
                if d is not None:
                    funcs.append(d)
                    todo.append(d)
                elif re.search(rf'\b{ident}\s*\[', src):
                    globs.append(f'static unsigned {ident}[4096];')
                else:
                    globs.append(f'static volatile unsigned {ident} = 1;   /* v183 toggle: on */')
        skip = {'PV_RGBA', 'PV_BW', 'PV_BLACK', 'PV_M1_X', 'PV_M1_W', 'PV_M1_H', 'PV_HOT'}
        macros = [m.group(0) for m in re.finditer(r'^#define (PV_\w+)\b[^\n]*', text, re.M)
                  if m.group(1) not in skip]
        return '\n'.join(macros), '\n'.join(globs), '\n'.join(reversed(funcs))

    def test_peaking_asan(self):
        text = C_SRC.read_text()
        render = func_def(text, 'pv_render_m1')
        self.assertIsNotNone(render)
        self.assertIn('0xFF00FF40', render, 'v183 focus peaking (0xFF00FF40) not in pv_render_m1 yet')
        macros, globs, helpers = self._support(text, render)
        m1_row = re.search(r'^#define\s+M1_ROW\b(?:[^\n]*\\\n)*[^\n]*', text, re.M).group(0)
        defs = '\n'.join(func_def(text, n) for n in ('pv_get10', 'pv_get12', 'pv_make_lut', 'pv_fill', 'pv_m1_rect', 'pv_mask_opaque'))
        # v184a: fixed REC-view LUT globals, copied verbatim (pv_build_m1_luts / pv_sqrt_m1 come in as helpers)
        lut_decl = '\n'.join(re.search(p, text, re.M).group(0) for p in (
            r'^static unsigned pv_lut_r\[1024\][^\n]*', r'^static unsigned pv_m1_lut_ok\b[^\n]*'))

        program = f'''
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
static unsigned fake_rgba[PV_BW * 240];
#define PV_RGBA fake_rgba
{macros}
#define PV_HOT
{lut_decl}
static void pv_build_m1_luts(void);
static struct {{ int buffer_width; }} camera_screen = {{ 360 }};
static unsigned char pv_lut[1024];
static unsigned pv_stat[3] = {{ 0, 127, 300 }};
static volatile unsigned pv_mode = 0, pv_zebra = 1, pv_clip_pct = 0;
static volatile unsigned sh_field = 0, sh_rec_on = 0;
static unsigned pv_m1_ylim(void) {{ return (sh_field == 4 && !sh_rec_on) ? 200u : 220u; }}
{globs}
static int refresh_n = 0;
static void vid_bitmap_refresh(void) {{ refresh_n++; }}
static int pv_ok(void) {{ return camera_screen.buffer_width == PV_BW; }}
{defs}
{helpers}
{m1_row}
{render}
#undef M1_ROW

static void pack_row(unsigned short *dst, const unsigned *vals, unsigned n, unsigned bpp) {{
    unsigned m = (1u << bpp) - 1;
    memset(dst, 0, n * bpp / 8 + 4);
    for (unsigned c = 0; c < n; c++) {{
        unsigned b = c * bpp, w = b >> 4, sh = b & 15, v = vals[c] & m, top = 16 - bpp;
        if (sh <= top) dst[w] |= (unsigned short)(v << (top - sh));
        else {{ dst[w] |= (unsigned short)(v >> (sh - top)); dst[w + 1] |= (unsigned short)(v << (16 + top - sh)); }}
    }}
}}
/* kind 0: step edge at column 960 (lo | hi); 1: flat 300 + low noise; scale = 1 (10b) or 4 (12b) */
static char *make_frame(unsigned bpp, int kind, unsigned lo, unsigned hi) {{
    size_t lb = 1920 * bpp / 8;
    char *f = calloc(1441, lb);
    static unsigned tmp[1920];
    unsigned seed = 12345;
    for (unsigned r = 0; r < 1440; r++) {{
        for (unsigned c = 0; c < 1920; c++) {{
            if (kind == 0) tmp[c] = c < 960 ? lo : hi;
            else {{ seed = seed * 1103515245u + 12345u; tmp[c] = lo + ((seed >> 16) % 3); }}
        }}
        pack_row((unsigned short *)(f + r * lb), tmp, 1920, bpp);
    }}
    return f;
}}
static unsigned count(unsigned v) {{
    unsigned n = 0;
    for (unsigned y = 20; y < 220; y++)
        for (unsigned x = PV_M1_X; x < PV_M1_X + PV_M1_W; x++) n += fake_rgba[y * PV_BW + x] == v;
    return n;
}}

int main(void) {{
    pv_make_lut(127, 300);
    pv_mode = 0; pv_zebra = 1;

    /* 1. sharp step edge, standby (half_res = 0): green peaks in 10 and 12 bit */
    char *e10 = make_frame(10, 0, 127, 600), *e12 = make_frame(12, 0, 127 * 4, 600 * 4);
    memset(fake_rgba, 0, sizeof(fake_rgba));
    pv_render_m1(e10, 10, 0, 1920, 1440);
    unsigned p10 = count({PEAK_PX:#x}u);
    memset(fake_rgba, 0, sizeof(fake_rgba));
    pv_render_m1(e12, 12, 0, 1920, 1440);
    unsigned p12 = count({PEAK_PX:#x}u);
    printf("edge peaks 10b=%u 12b=%u\\n", p10, p12);
    assert(p10 > 0 && p12 > 0);
    assert(p10 < PV_M1_W * PV_M1_H / 4 && p12 < PV_M1_W * PV_M1_H / 4);   /* edge only, not the flats */

    /* 2. flat, low-noise frame: no peaks */
    char *fl = make_frame(10, 1, 300, 0);
    memset(fake_rgba, 0, sizeof(fake_rgba));
    pv_render_m1(fl, 10, 0, 1920, 1440);
    printf("flat peaks=%u\\n", count({PEAK_PX:#x}u));
    assert(count({PEAK_PX:#x}u) == 0);

    /* 3. edge into clipped highlights: zebra wins over peaking */
    char *ec = make_frame(10, 0, 127, 1023);
    unsigned s0 = pv_stat[0];
    memset(fake_rgba, 0, sizeof(fake_rgba));
    pv_render_m1(ec, 10, 0, 1920, 1440);
    unsigned zc = count({ZEBRA_PX:#x}u);
    printf("clip zebra=%u peaks=%u\\n", zc, count({PEAK_PX:#x}u));
    assert(zc > 0);
    for (unsigned y = 0; y < PV_M1_H; y++)
        for (unsigned x = 0; x < PV_M1_W; x++) {{
            unsigned c = (x * 1920 / PV_M1_W) & ~1u;
            if (c >= 960 && (((x + y) + s0) & 7) < 4)
                assert(fake_rgba[(20 + y) * PV_BW + PV_M1_X + x] == {ZEBRA_PX:#x}u);
        }}

    /* 4. REC (half_res = 1): peaking disabled */
    memset(fake_rgba, 0, sizeof(fake_rgba));
    pv_render_m1(e10, 10, 1, 1920, 1440);
    assert(count({PEAK_PX:#x}u) == 0);
    memset(fake_rgba, 0, sizeof(fake_rgba));
    pv_render_m1(e12, 12, 1, 1920, 1440);
    assert(count({PEAK_PX:#x}u) == 0);

    free(e10); free(e12); free(fl); free(ec);
    printf("peaking ok\\n");
    return 0;
}}
'''
        res = run_c(program, extra_flags=['-fsanitize=address,undefined', '-fno-sanitize-recover=undefined'])
        self.assertIn('peaking ok', res.stdout)


# ---------------------------------------------------------------------------------------------------
class TestV183Recipe(unittest.TestCase):
    def test_recipe_v183(self):
        text = C_SRC.read_text()
        f = recipe_fields(text, 'SH_RECIPE_M1')
        self.assertEqual(len(f), len(recipe_fields(text, 'SH_RECIPE')))
        fl = int(f[5])
        self.assertEqual(fl, 553650560)
        self.assertEqual(fl & (1 << 25), 0, 'fl bit 25 must be clear')
        self.assertEqual(f[53], '350', 'field 54 (0-idx 53, x_pbl) must be 350 (v183b)')
        self.assertIn('x_pbl = v', text)   # field still parsed into x_pbl


# ---------------------------------------------------------------------------------------------------
LUA_MOCK = r'''
local FOCUS_OK = __FOCUS_OK__
local mem = {}
local HOOK = 0x12340000
local REQ, ACK = HOOK + 0x220, HOOK + 0x224
local files = {}
local calls = {}
local fs_during_loop = 0
local in_loop = false
local tick = 0
local rec_mode = true
local alt_exited = false
local half_t = nil

mem[0x3e8c70] = 0x41f0e92d
mem[0x9b50] = 0x121
mem[0x865c] = 3
mem[0xe664] = 3
mem[0xfc3c] = 24
mem[0xfa84] = 0
mem[0x85b8] = 7     -- ContinuousAF running in Photo M

function peek(a) return mem[a] or 0 end
function poke(a, v) mem[a] = v end
if not bitand then
  local function bits32(x)
    local t = {}
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
    local ta, tb, tr = bits32(a), bits32(b), {}
    for i = 1, 32 do tr[i] = (ta[i] == 1 and tb[i] == 1) and 1 or 0 end
    return from32(tr)
  end
  function bitor(a, b)
    local ta, tb, tr = bits32(a), bits32(b), {}
    for i = 1, 32 do tr[i] = (ta[i] == 1 or tb[i] == 1) and 1 or 0 end
    return from32(tr)
  end
  function bitnot(a) return -1 - a end
  function bitshl(a, n)
    local ta, tr = bits32(a), {}
    for i = 1, 32 do tr[i] = (i > n) and ta[i - n] or 0 end
    return from32(tr)
  end
end

local function log(s) table.insert(calls, s) end
function get_tick_count() return tick end
function get_usb_power(x) return 0 end
function get_mode() return rec_mode end
function set_record(v) rec_mode = v; log("set_record:" .. tostring(v)) end
function is_pressed(k) return false end
function press(k) log("press:" .. k); if k == "shoot_half" then half_t = tick end end
function release(k) log("release:" .. k); if k == "shoot_half" then half_t = nil end end
function get_shooting()
  local s = half_t ~= nil and tick - half_t >= 400 and mem[0x865c] == 3
  if s and calls[#calls] ~= "get_shooting:true" then log("get_shooting:true") end
  return s
end
function get_focus_ok() log("get_focus_ok"); return FOCUS_OK end
function draw_string(...) end
function draw_clear() end
function set_exit_key(k) end
function exit_alt() alt_exited = true end
function print(...) end
package.loaded["capmode"] = { get_name = function() return "M" end }

io.open = function(p, m)
  if in_loop then fs_during_loop = fs_during_loop + 1 end
  if m == "w" then
    files[p] = ""
    return { write = function(self, ...) files[p] = files[p] .. table.concat({...}) end, close = function() end }
  elseif m == "r" then
    if not files[p] then return nil end
    return { read = function() return files[p] end, close = function() end }
  end
  return nil
end
os.stat = function(p)
  if in_loop then fs_during_loop = fs_during_loop + 1 end
  return files[p] and { size = #files[p] } or nil
end
os.remove = function(p)
  if in_loop then fs_during_loop = fs_during_loop + 1 end
  files[p] = nil
end

-- IPC driver (plays the C side): 1 m1_on -> 5 do_af -> 1 m1_on -> 0xE0
local SEQ = { 1, 5, 1, 0xE0 }
local seq_i, cur, idle, acks = 0, nil, 0, {}
local function issue()
  seq_i = seq_i + 1
  cur = SEQ[seq_i]
  log("REQ:" .. cur)
  mem[ACK] = 0
  mem[REQ] = cur
  if cur == 0xE0 then in_loop = false end
end
function sleep(ms)
  tick = tick + ms
  if not in_loop or (mem[REQ] or 0) ~= 0 then return end
  if cur == nil then
    idle = idle + 1
    if idle >= 3 then issue() end
  elseif bitand(mem[ACK], 0x1ff) == bitor(cur, 0x100) then
    acks[seq_i] = mem[ACK]
    log("ACK:" .. cur)
    if cur == 5 then
      assert(mem[0x865c] == 3 and mem[0xe664] == 3, "do_af must stay in Photo M ImgMode 3")
      assert(mem[0xfc3c] == 24, "do_af must restore 0xfc3c")
    end
    if cur == 1 then assert(mem[0x865c] == 1 and mem[0xfc3c] == 2073, "m1_on state wrong") end
    issue()
  end
end

function call_func_ptr(fn, a1, a2)
  if fn == 0x3e8c71 then
    assert(a1 == "m10cine.flt")
    mem[HOOK + 0x200] = 0x364f4953
    mem[0x9b50] = HOOK + 0x11
    in_loop = true
    return 0
  elseif fn == 0xfc38d3f1 then return 0x20000000
  elseif fn == 0xfc0dc01d then log("MV_STOP"); return 0
  elseif fn == 0xfc0dbfc9 then log("MV_START"); return 0
  elseif fn == 0xfc0fa287 then log("AF_STOP"); mem[0x85b8] = 0; return 0
  elseif fn == 0xfc1efc0d then log("STOP_MODE"); return 0
  elseif fn == 0xfc1efb33 then mem[0x865c] = a1; log("CHG_MODE:" .. tostring(a1)); return 0
  elseif fn == 0xfc414d25 then log("CDS_WRITE"); return 0
  end
  return 0
end

dofile("__LUA_SRC__")

assert(alt_exited, "exit_alt not called")
assert(fs_during_loop == 0, "FS access during IPC loop: " .. tostring(fs_during_loop))
assert(not files["A/M10SH.CFG"], "M10SH.CFG not cleaned up")
assert(seq_i == 4 and bitand(mem[ACK], 0x1ff) == 0x1E0, "REQ_END ack missing")
assert(bitand(acks[1], 0x3ff) == 0x301, "1st m1_on ack: " .. tostring(acks[1]))
assert(bitand(acks[3], 0x3ff) == 0x301, "2nd m1_on ack: " .. tostring(acks[3]))
local a5 = acks[2]
assert(a5 and bitand(a5, 0x1ff) == bitor(5, 0x100), "do_af ack code: " .. tostring(a5))
local af_bit = bitand(a5, 0x200) ~= 0 and 1 or 0
assert(af_bit == (FOCUS_OK and 1 or 0), "do_af af_ok bit 9 = " .. af_bit)
assert(bitand(a5, 0xff0000) == 0x30000, "do_af ack ImgSens field must be 3")
assert(bitand(a5, 0x7f000000) == 0x3000000, "do_af ack tg field must be 3")

-- ordered trace of the do_af request
local s, e
for i, c in ipairs(calls) do
  if c == "REQ:5" then s = i end
  if c == "ACK:5" then e = i end
end
assert(s and e and e > s, "REQ:5 / ACK:5 not found")
local want = { "CHG_MODE:3", "MV_START", "press:shoot_half", "get_shooting:true", "get_focus_ok", "release:shoot_half" }
local j = 1
for i = s, e do if calls[i] == want[j] then j = j + 1 end end
assert(j == #want + 1, "do_af trace missing " .. tostring(want[j]) .. " : " .. table.concat(calls, ",", s, e))
for i = s, e do assert(calls[i] ~= "MV_STOP" and calls[i] ~= "CHG_MODE:1", "do_af must not re-enter ImgMode 1") end
io.stdout:write("lua af ok focus=" .. tostring(FOCUS_OK) .. " ack5=" .. string.format("%08x", a5) .. "\n")
'''


class TestV183LuaAF(unittest.TestCase):
    def _run(self, focus_ok: bool):
        harness = LUA_MOCK.replace('__FOCUS_OK__', 'true' if focus_ok else 'false').replace('__LUA_SRC__', str(LUA_SRC))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'run_mock.lua'
            p.write_text(harness)
            res = subprocess.run([str(HOSTLUA), str(p)], capture_output=True, text=True, timeout=20)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn('lua af ok', res.stdout)

    def test_lua_af_ipc(self):
        lua_txt = LUA_SRC.read_text()
        self.assertIn('@title M10 Cine shell unifie (v183)', lua_txt)
        self.assertIn('[5] = do_af', lua_txt)
        if not (HOSTLUA.exists() and HOSTLUAC.exists()):
            self.skipTest('hostlua missing (set M10_CHDK to a CHDK checkout)')
        subprocess.run([str(HOSTLUAC), '-p', str(LUA_SRC)], check=True)
        self._run(True)
        self._run(False)


# ---------------------------------------------------------------------------------------------------
class TestV183FpsAndTimestamps(unittest.TestCase):
    PERIOD = 1000000 / 24   # 41666.67 us

    @staticmethod
    def old_fps1000(ticks):
        return (len(ticks) - 1) * 1000000 // (ticks[-1] - ticks[0])

    @staticmethod
    def sim_ticks(n, drop_every):
        """Sensor at 24.03 fps (41.614 ms); the writer keeps frames except every drop_every-th; ms ticks with jitter."""
        sens = 1000.0 / 24.03
        ticks, idx = [], []
        for s in range(n):
            if drop_every and s % drop_every == drop_every - 1:
                continue
            ticks.append(int(s * sens + (7 if s % 3 == 0 else 0)))   # 0..7 ms scheduling jitter
            idx.append(s)
        return ticks, idx

    def test_reference_model(self):
        ticks, _ = self.sim_ticks(500, 0)
        self.assertAlmostEqual(self.old_fps1000(ticks), 24030, delta=30)
        ticks, _ = self.sim_ticks(500, 50)   # ~2 % drops: the v182 formula slides to ~23.5 fps
        self.assertLess(self.old_fps1000(ticks), 23600)

    def test_fps_and_timestamps(self):
        text = C_SRC.read_text()
        vf = func_def(text, 'xr_vidf_us')
        self.assertIsNotNone(vf, 'v183 xr_vidf_us() not in m10_cine.c yet')
        for fn in ('lj_vidf', 'mlv_frame_hdr'):
            d = func_def(text, fn)
            if d and 'put32(h + 8' in d:
                self.assertNotIn('(xr_tick[k]) * 1000', d, f'{fn} still stamps VIDF from the ms tick')
        self.assertNotIn('put32(h + 8, (xr_tick[k]) * 1000)', text)
        i_nd = text.index('lm2.ndone = xr_wr;')
        m_fin = re.search(r'if\s*\(xr_mlv\)\s*mlv_finalize', text[i_nd:])
        self.assertIsNotNone(m_fin, 'mlv_finalize call not found after lm2.ndone = xr_wr;')
        fps_blk = text[i_nd:i_nd + m_fin.start()]
        self.assertIn('xr_drop_at', fps_blk, 'mlv_fps1000 block must account for drops via xr_drop_at')
        self.assertIn('1000000000u / per_us', fps_blk, 'mlv_fps1000 must derive fps from measured sensor period')

        # C unit test of the real xr_vidf_us: globals it touches are copied verbatim from m10_cine.c
        sig = re.match(r'static[^(]*\(([^)]*)\)', vf).group(1)
        nparams = 0 if sig.strip() in ('', 'void') else sig.count(',') + 1
        args = {0: '', 1: 'k', 2: 'k, idx[k]'}.get(nparams)
        self.assertIsNotNone(args, f'unexpected xr_vidf_us signature: ({sig})')
        ticks, idx = self.sim_ticks(400, 37)
        program = f'''
#include <assert.h>
#include <stdio.h>
#define XR_MAX 4096
static unsigned xr_tick[XR_MAX];
static unsigned short xr_drop_at[XR_MAX];
static unsigned x_m1 = 1, lj_on = 1, x_per = 41666;
{vf}
static const unsigned tk[] = {{ {", ".join(map(str, ticks))} }};
static const unsigned idx[] = {{ {", ".join(map(str, idx))} }};
int main(void) {{
    unsigned n = sizeof(tk) / sizeof(tk[0]), gaps = 0;
    unsigned long long prev = 0;
    for (unsigned k = 0; k < n; k++) {{
        xr_tick[k] = tk[k];
        xr_drop_at[k] = (unsigned short)(idx[k] - k);
    }}
    for (unsigned k = 0; k < n; k++) {{
        unsigned long long t = xr_vidf_us({args});
        if (k) {{
            unsigned long long d = t - prev, m = (d + 20833) / 41666;
            assert(t > prev);                              /* monotonic */
            assert(m >= 1);
            assert(d == m * 41666ULL);                     /* exact 41666 us multiples, zero jitter */
            gaps += m > 1;
        }}
        prev = t;
    }}
    assert(gaps >= 8);                                     /* drops reflected as exact 2x period gaps */
    /* Also verify measured fps formula stays ~24030 even with drops */
    unsigned span_ms = tk[n - 1] - tk[0];
    unsigned slots = (n - 1) + (unsigned)(xr_drop_at[n - 1] - xr_drop_at[0]);
    unsigned per_us = (span_ms * 1000u) / slots;
    unsigned fps1000 = 1000000000u / per_us;
    assert(fps1000 >= 23980 && fps1000 <= 24080);
    printf("vidf ok n=%u gaps=%u fps1000=%u\\n", n, gaps, fps1000);
    return 0;
}}
'''
        res = run_c(program, extra_flags=['-fsanitize=address,undefined', '-fno-sanitize-recover=undefined'])
        self.assertIn('vidf ok', res.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
