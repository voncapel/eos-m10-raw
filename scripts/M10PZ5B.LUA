--[[
@title M10 Zoom5x Scan v2
@chdk_version 1.5
@param q First port to scan (dec)
@default q 0
@param p Last port to scan (dec, 127=0x7f)
@default p 127
]]

-- In Zoom x5 (2592x1107 readout) CH12 stops instantly (ctl=0, nothing written)
-- on every port, even port 0x04 which is known active (probe14).
-- This version:
--   1. logs the state of every candidate write channel,
--   2. tries each idle candidate on port 0x04 to find one that really writes,
--   3. scans ports q..p with the first working channel.
-- Output: A/M10PZ5B.TXT + A/PZ5B.BIN (64 KB per port).

local FN_ENGDRV_OUT  = 0xfc02109d
local FN_ENGDRV_READ = 0xfc38d2b9
local FN_OPEN        = 0xfc389801
local FN_WRITE       = 0xfc3898bd
local FN_CLOSE       = 0xfc389885
local FN_EXMEM_UALLOC= 0xfc08169d
local FN_EXMEM_UFREE = 0xfc081757

if type(call_func_ptr) ~= "function" then
    print("Activez Lua Native Calls !")
    sleep(3000)
    return
end

local log = io.open("A/M10PZ5B.TXT", "w")
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

logf("=== M10PZ5B buf=0x%08x dss_flags=0x%08x dss_wh=%dx%d ===",
     buf, peek(0x00028738, 4), peek(0x001beb5c, 4), peek(0x001beb60, 4))

-- Safety: never touch EDMAC/crossbar when the imaging engine is off (playback).
if shamem_read(0xc0f06804) == 0 or peek(0x00028738, 4) == 0 then
    logf("ABORT: LiveView inactive")
    finish("LiveView inactif: passer en mode prise de vue")
    return
end
logf("6800=0x%08x 6804=0x%08x 6008=0x%08x 6014=0x%08x",
     shamem_read(0xc0f06800), shamem_read(0xc0f06804),
     shamem_read(0xc0f06008), shamem_read(0xc0f06014))

-- Write channels from the ROM table 0xfc6d87b8; crossbar reg = 0xc0f051e0 + ch*4 (ch >= 8)
local CHANNELS = {
    {8,  0xc0f26100}, {9,  0xc0f26200}, {10, 0xc0f26300}, {11, 0xc0f26400},
    {12, 0xc0f26500}, {13, 0xc0f26600}, {14, 0xc0f30000}, {17, 0xc0f30300},
    {18, 0xc0f30400}, {19, 0xc0f30500}, {20, 0xc0f30600},
}

local SLOT = 0x10000
local XB   = 4096
local YB   = (SLOT / XB) - 1
local xbyb = bitor(bitshl(YB, 16), XB)

-- 1. state of every candidate
local idle = {}
for _, c in ipairs(CHANNELS) do
    local ch, base = c[1], c[2]
    local xr = 0xc0f051e0 + ch * 4
    local xv = shamem_read(xr)
    local ctl = peek(base, 4)
    local addr = shamem_read(base + 0x08)
    logf("CH%02d base=0x%08x ctl=0x%x xbar=0x%08x addr=0x%08x size=0x%08x",
         ch, base, ctl, xv, addr, shamem_read(base + 0x10))
    if xv == 0x80000000 and ctl == 0 then
        idle[#idle + 1] = c
    end
end

-- one capture of SLOT bytes from `port` with channel c into dst; returns kb written, ctl, loops
local function grab(c, port, dst)
    local ch, base = c[1], c[2]
    local xr = 0xc0f051e0 + ch * 4
    for k = 0, (SLOT / 1024) - 1 do
        poke(dst + k * 1024, 0xdeadbeef, 4)
    end
    eng_out(base + 0x40, 0)
    eng_out(base + 0x04, 0x20000000)             -- EDMAC_2_BYTES_PER_TRANSFER
    eng_out(base + 0x08, bitand(dst, 0x3fffffff))
    eng_out(base + 0x0c, 0)
    eng_out(base + 0x10, xbyb)
    eng_out(base + 0x14, xbyb)
    for off = 0x18, 0x28, 4 do
        eng_out(base + off, 0)
    end
    eng_out(xr, port)
    eng_out(base + 0x00, 1)
    local ctl, loops = 1, 0
    while ctl ~= 0 and loops < 6 do
        sleep(10)
        ctl = peek(base + 0x00, 4)
        loops = loops + 1
    end
    eng_out(base + 0x00, 2)
    eng_out(xr, 0x80000000)
    local written = 0
    for k = 0, (SLOT / 1024) - 1 do
        if peek(dst + k * 1024, 4) ~= 0xdeadbeef then
            written = written + 1
        end
    end
    return written, ctl, loops
end

-- 2. find a channel that really writes port 0x04 (always active in LiveView)
local chosen = nil
for _, c in ipairs(idle) do
    logf("probe CH%02d on port 0x04", c[1])
    local kb, ctl, loops = grab(c, 0x04, buf)
    logf("probe CH%02d port 0x04: kb_written=%d ctl=0x%x loops=%d", c[1], kb, ctl, loops)
    if kb > 0 and chosen == nil then
        chosen = c
    end
end
if chosen == nil then
    logf("NO working channel in this mode")
    finish("Aucun canal libre ne marche")
    return
end
logf("CHOSEN CH%02d", chosen[1])
print(string.format("Canal CH%02d, scan...", chosen[1]))

-- 3. full scan with the working channel
local n = 0
for port = q, p do
    local dst = buf + n * SLOT
    if (n + 1) * SLOT > 0x00e00000 then
        logf("buffer full, stop at port 0x%02x", port)
        break
    end
    logf("try port=0x%02x", port)
    local kb, ctl, loops = grab(chosen, port, dst)
    logf("slot=%d port=0x%02x rt=-1 ctl=0x%x loops=%d kb_written=%d w0=0x%08x w1=0x%08x",
         n, port, ctl, loops, kb, peek(dst, 4), peek(dst + 4, 4))
    n = n + 1
    if (n % 16) == 0 then
        print(string.format("port 0x%02x ...", port))
    end
end

local fd = call_func_ptr(FN_OPEN, "A/PZ5B.BIN", 0x301, 511)
if fd >= 0 then
    local w = call_func_ptr(FN_WRITE, fd, buf, n * SLOT)
    call_func_ptr(FN_CLOSE, fd)
    logf("Saved A/PZ5B.BIN (%d bytes, %d slots of %d)", w, n, SLOT)
end
finish("OK, voir M10PZ5B.TXT")
