--[[
@title M10 Zoom5x Port Scan
@chdk_version 1.5
@param q First port to scan (dec)
@default q 0
@param p Last port to scan (dec, 127=0x7f)
@default p 127
@param r Raw-type pass on port 0 (0/1)
@default r 0
]]

-- Goal: find which crossbar source actually carries Bayer RAW in LiveView.
-- Probe 1-6 showed that port 4 (CH22) carries UYVY 4:2:2 8-bit, NOT Bayer.
-- For each source port, CH12 (0xc0f26500) is connected for a short 64 KB burst,
-- then disconnected. All slots are written to A/PORTS.BIN (64 KB per slot),
-- metadata to A/M10PORTS.TXT. Analyse on the Mac with scripts/analyze_ports.py.

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

local log = io.open("A/M10PZ5.TXT", "w")
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

local SLOT   = 0x10000          -- 64 KB per test
local XB     = 4096             -- bytes per "line" (source width unknown: plain stream)
local YB     = (SLOT / XB) - 1  -- 15
local CH12   = 0xc0f26500
local XBAR12 = 0xc0f05210
local RAWTYPE_REG = 0xc0f37014

logf("=== M10PZ5 buf=0x%08x dss_flags(0x28738)=0x%08x dss_wh=%dx%d ===", buf, peek(0x00028738, 4), peek(0x001beb5c, 4), peek(0x001beb60, 4))

-- Safety: touching EDMAC/crossbar while the imaging engine is off (playback mode)
-- froze the camera on 2026-11-06. Refuse to run unless LiveView is streaming.
if shamem_read(0xc0f06804) == 0 or peek(0x00028738, 4) == 0 then
    logf("ABORT: LiveView inactive (6804=0x%08x dss_flags=0x%08x)",
         shamem_read(0xc0f06804), peek(0x00028738, 4))
    print("LiveView inactif: passer en mode prise de vue")
    call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
    log:close()
    sleep(3000)
    return
end
logf("6800=0x%08x 6804=0x%08x 37014=0x%08x 6008=0x%08x 6014=0x%08x",
     shamem_read(0xc0f06800), shamem_read(0xc0f06804), shamem_read(RAWTYPE_REG),
     shamem_read(0xc0f06008), shamem_read(0xc0f06014))
-- Full crossbar map, write channels 0..31
for ch = 0, 31 do
    local v = shamem_read(0xc0f051e0 + ch * 4)
    if v ~= 0x80000000 and v ~= 0 then
        logf("XBAR ch%02d (0x%08x) = 0x%08x", ch, 0xc0f051e0 + ch * 4, v)
    end
end

-- Build the test list: {port, rawtype or -1}
local tests = {}
for port = q, p do
    tests[#tests + 1] = {port, -1}
end
if r == 1 then
    for _, rt in ipairs({0x10, 0x12, 0x22, 0x04, 0x07, 0x0b, 0x01}) do
        tests[#tests + 1] = {0, rt}
    end
end
if #tests * SLOT > 0x00e00000 then
    print("Trop de tests")
    log:close()
    call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
    return
end

local rt_saved = shamem_read(RAWTYPE_REG)
local xbyb = bitor(bitshl(YB, 16), XB)

for i, t in ipairs(tests) do
    local port, rt = t[1], t[2]
    local dst = buf + (i - 1) * SLOT
    -- 1 marker word per KB, so the Mac side can measure how much was written
    for k = 0, (SLOT / 1024) - 1 do
        poke(dst + k * 1024, 0xdeadbeef, 4)
    end
    -- logged before touching hardware, so a freeze points at the guilty port
    logf("try slot=%d port=0x%02x rt=%d", i - 1, port, rt)
    if rt >= 0 then
        eng_out(RAWTYPE_REG, rt)
    end

    eng_out(CH12 + 0x40, 0)
    eng_out(CH12 + 0x04, 0x20000000)            -- EDMAC_2_BYTES_PER_TRANSFER
    eng_out(CH12 + 0x08, bitand(dst, 0x3fffffff))
    eng_out(CH12 + 0x0c, 0)
    eng_out(CH12 + 0x10, xbyb)
    eng_out(CH12 + 0x14, xbyb)
    for off = 0x18, 0x28, 4 do
        eng_out(CH12 + off, 0)
    end

    eng_out(XBAR12, port)
    eng_out(CH12 + 0x00, 1)
    local ctl, loops = 1, 0
    while ctl ~= 0 and loops < 6 do
        sleep(10)
        ctl = peek(CH12 + 0x00, 4)
        loops = loops + 1
    end
    eng_out(CH12 + 0x00, 2)
    eng_out(XBAR12, 0x80000000)
    if rt >= 0 then
        eng_out(RAWTYPE_REG, rt_saved)
    end

    local written = 0
    for k = 0, (SLOT / 1024) - 1 do
        if peek(dst + k * 1024, 4) ~= 0xdeadbeef then
            written = written + 1
        end
    end
    logf("slot=%d port=0x%02x rt=%d ctl=0x%x loops=%d kb_written=%d w0=0x%08x w1=0x%08x",
         i - 1, port, rt, ctl, loops, written, peek(dst, 4), peek(dst + 4, 4))
    if (i % 8) == 0 then
        print(string.format("port 0x%02x ...", port))
    end
end

local fd = call_func_ptr(FN_OPEN, "A/PZ5.BIN", 0x301, 511)
if fd >= 0 then
    local w = call_func_ptr(FN_WRITE, fd, buf, #tests * SLOT)
    call_func_ptr(FN_CLOSE, fd)
    logf("Saved A/PZ5.BIN (%d bytes, %d slots of %d)", w, #tests, SLOT)
end

call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
log:close()
print("OK, voir M10PZ5.TXT")
sleep(2000)
