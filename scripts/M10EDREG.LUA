--[[
@title M10 EDMAC Diag
@chdk_version 1.5
@param t Mode 0=LV normal 1=Zoom x5
@default t 0
@param c Canal a tester (8-20)
@default c 12
]]

-- Diagnostic: why does every write channel stop instantly (0 byte) in Zoom x5
-- while the same code works in normal LiveView?
-- Logs, for channel c on port 0x04:
--   - full register dump 0x00..0x7c (direct read) before / after programming,
--   - fast poll of ctl + current pointer right after start (no sleep),
--   - dump after stop,
-- plus read-only dumps of the channels Canon is using, and the whole crossbar.
-- Output: A/EDREG_LV.TXT or A/EDREG_Z5.TXT

local FN_ENGDRV_OUT  = 0xfc02109d
local FN_ENGDRV_READ = 0xfc38d2b9
local FN_EXMEM_UALLOC= 0xfc08169d
local FN_EXMEM_UFREE = 0xfc081757

if type(call_func_ptr) ~= "function" then
    print("Activez Lua Native Calls !")
    sleep(3000)
    return
end

local tag = (t == 1) and "Z5" or "LV"
local log = io.open("A/EDREG_" .. tag .. ".TXT", "w")
local function logf(fmt, ...)
    log:write(string.format(fmt, ...) .. "\n")
    log:flush()
end

local EXMEM_TYPE = 5
local buf = call_func_ptr(FN_EXMEM_UALLOC, EXMEM_TYPE, 0x01000000, 0)
if buf == 0 then
    print("Erreur EXMEM")
    log:close()
    return
end
local scratch = buf + 0x00f00000

local function eng_out(reg, val)
    poke(scratch, reg, 4)
    poke(scratch + 4, val, 4)
    call_func_ptr(FN_ENGDRV_OUT, scratch)
end
local function shamem_read(reg)
    return call_func_ptr(FN_ENGDRV_READ, reg)
end
local function finish(msg)
    call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
    log:close()
    print(msg)
    sleep(2500)
end

logf("=== M10EDREG %s ch=%d buf=0x%08x dss_flags=0x%08x dss_wh=%dx%d ===",
     tag, c, buf, peek(0x00028738, 4), peek(0x001beb5c, 4), peek(0x001beb60, 4))

-- Safety: never touch EDMAC/crossbar when the imaging engine is off (playback).
if shamem_read(0xc0f06804) == 0 or peek(0x00028738, 4) == 0 then
    logf("ABORT: LiveView inactive")
    finish("LiveView inactif: passer en mode prise de vue")
    return
end
logf("6800=0x%08x 6804=0x%08x 6008=0x%08x 6014=0x%08x",
     shamem_read(0xc0f06800), shamem_read(0xc0f06804),
     shamem_read(0xc0f06008), shamem_read(0xc0f06014))

-- ROM table 0xfc6d87b8: index -> base
local BASES = {
    [7]=0xc0f26000, [8]=0xc0f26100, [9]=0xc0f26200, [10]=0xc0f26300,
    [11]=0xc0f26400, [12]=0xc0f26500, [13]=0xc0f26600,
    [14]=0xc0f30000, [15]=0xc0f30100, [16]=0xc0f30200, [17]=0xc0f30300,
    [18]=0xc0f30400, [19]=0xc0f30500, [20]=0xc0f30600,
}

local function dump(label, base)
    local direct, shadow = {}, {}
    -- direct MMIO reads only on offsets the firmware itself programs (safe)
    for off = 0x00, 0x2c, 4 do
        direct[#direct + 1] = string.format("%08x", peek(base + off, 4))
    end
    direct[#direct + 1] = string.format("40:%08x", peek(base + 0x40, 4))
    -- shadow (RAM cache of EngDrvOut) is always safe to read
    for off = 0x00, 0x7c, 4 do
        shadow[#shadow + 1] = string.format("%08x", shamem_read(base + off))
    end
    logf("%s 0x%08x DIRECT %s", label, base, table.concat(direct, " "))
    logf("%s 0x%08x SHADOW %s", label, base, table.concat(shadow, " "))
end

-- 1. crossbar (shadow) 0xc0f05000..0xc0f0527c
local xb = {}
for r = 0xc0f05000, 0xc0f0527c, 4 do
    local v = shamem_read(r)
    if v ~= 0x80000000 and v ~= 0 then
        xb[#xb + 1] = string.format("%03x=%08x", r - 0xc0f05000, v)
    end
end
logf("XBAR(non-idle) %s", table.concat(xb, " "))

-- 2. read-only dump of every channel in the table (index 7..20)
for i = 7, 20 do
    dump(string.format("PRE  CH%02d", i), BASES[i])
end

-- 3. test channel c on port 0x04
local base = BASES[c]
if base == nil or c < 8 then
    logf("bad channel %d", c)
    finish("Canal invalide")
    return
end
local xr = 0xc0f051e0 + c * 4
local SLOT = 0x10000
local XB = 4096
local YB = (SLOT / XB) - 1
local xbyb = bitor(bitshl(YB, 16), XB)
for k = 0, (SLOT / 1024) - 1 do
    poke(buf + k * 1024, 0xdeadbeef, 4)
end

eng_out(base + 0x40, 0)
eng_out(base + 0x04, 0x20000000)
eng_out(base + 0x08, bitand(buf, 0x3fffffff))
eng_out(base + 0x0c, 0)
eng_out(base + 0x10, xbyb)
eng_out(base + 0x14, xbyb)
for off = 0x18, 0x28, 4 do
    eng_out(base + off, 0)
end
eng_out(xr, 0x04)
dump("PROG CH" .. c, base)
logf("xbar readback 0x%08x = 0x%08x (direct 0x%08x)", xr, shamem_read(xr), peek(xr, 4))

local t0 = get_tick_count()
eng_out(base + 0x00, 1)
-- fast poll without sleep: record transitions of ctl and pointer
local samples = {}
local last_ctl, last_ptr = -1, -1
for i = 1, 400 do
    local ctl = peek(base + 0x00, 4)
    local ptr = peek(base + 0x08, 4)
    if ctl ~= last_ctl or ptr ~= last_ptr then
        samples[#samples + 1] = string.format("i%d:t%d:ctl=%x:ptr=%08x", i,
            get_tick_count() - t0, ctl, ptr)
        last_ctl, last_ptr = ctl, ptr
        if #samples >= 40 then break end
    end
end
logf("POLL %s", table.concat(samples, " "))
dump("RUN  CH" .. c, base)
sleep(60)
dump("LATE CH" .. c, base)

eng_out(base + 0x00, 2)
eng_out(xr, 0x80000000)
dump("STOP CH" .. c, base)

local written = 0
for k = 0, (SLOT / 1024) - 1 do
    if peek(buf + k * 1024, 4) ~= 0xdeadbeef then
        written = written + 1
    end
end
logf("kb_written=%d w0=0x%08x w1=0x%08x", written, peek(buf, 4), peek(buf + 4, 4))

-- 4. Canon channels again (did our test disturb them?)
for i = 7, 20 do
    dump(string.format("POST CH%02d", i), BASES[i])
end

finish(string.format("OK %s: %d KB ecrits", tag, written))
