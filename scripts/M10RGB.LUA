--[[
@title M10 RGB plane hunt
@chdk_version 1.5
@param f MB for port 0x36 (1-8)
@default f 4
]]

-- One-shot capture for the colour-plane test (scene: red, green, blue).
-- Port 0x36 = 868x490 @25fps, two 434-wide planes per line: probe10 showed
-- A (words 0-433) = green, B (words 434-867) = red. This script grabs 0x36
-- plus the other slow / unidentified ports in a single run, each into its
-- own file, so the missing G2/B planes can be located on the Mac.

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

local log = io.open("A/M10RGB.TXT", "w")
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
local function shamem_read(reg)
    return call_func_ptr(FN_ENGDRV_READ, reg)
end
local scratch = buf + 0x00f00000
local function eng_out(reg, val)
    poke(scratch, reg, 4)
    poke(scratch + 4, val, 4)
    call_func_ptr(FN_ENGDRV_OUT, scratch)
end

logf("=== M10RGB buf=0x%08x dss_flags=0x%08x ===", buf, peek(0x00028738, 4))
logf("6800=0x%08x 6804=0x%08x 6008=0x%08x 6014=0x%08x",
     shamem_read(0xc0f06800), shamem_read(0xc0f06804),
     shamem_read(0xc0f06008), shamem_read(0xc0f06014))

-- Safety: never touch EDMAC/crossbar when the imaging engine is off (playback).
if shamem_read(0xc0f06804) == 0 or peek(0x00028738, 4) == 0 then
    logf("ABORT: LiveView inactive")
    print("LiveView inactif: passer en mode prise de vue")
    call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
    log:close()
    sleep(3000)
    return
end

if f < 1 then f = 1 end
if f > 8 then f = 8 end

-- {port, MB}; total must stay below 15 MB (scratch lives at +15 MB)
local jobs = {
    {0x36, f},
    {0x35, 1},
    {0x28, 1},
    {0x06, 1},
    {0x02, 1},
    {0x4f, 1},
}

local CH12   = 0xc0f26500
local XBAR12 = 0xc0f05210
local XB     = 4096
local phys   = bitand(buf, 0x3fffffff)

local function capture(port, mb)
    local size = mb * 0x100000
    local yb = (size / XB) - 1
    for k = 0, (size / 4096) - 1 do
        poke(buf + k * 4096, 0xdeadbeef, 4)
    end
    eng_out(CH12 + 0x40, 0)
    eng_out(CH12 + 0x04, 0x20000000)             -- EDMAC_2_BYTES_PER_TRANSFER
    eng_out(CH12 + 0x08, phys)
    eng_out(CH12 + 0x0c, 0)
    eng_out(CH12 + 0x10, bitor(bitshl(yb, 16), XB))
    eng_out(CH12 + 0x14, bitor(bitshl(yb, 16), XB))
    for off = 0x18, 0x28, 4 do
        eng_out(CH12 + off, 0)
    end
    logf("try port=0x%02x mb=%d", port, mb)
    local t0 = get_tick_count()
    eng_out(XBAR12, port)
    eng_out(CH12 + 0x00, 1)
    local samples = {}
    local ctl, n = 1, 0
    while ctl ~= 0 and n < 60 do                 -- max 600 ms per port
        sleep(10)
        ctl = peek(CH12 + 0x00, 4)
        n = n + 1
        if (n % 2) == 0 then
            samples[#samples + 1] = string.format("%d:%d", get_tick_count() - t0,
                bitand(peek(CH12 + 0x08, 4), 0x3fffffff) - phys)
        end
    end
    eng_out(CH12 + 0x00, 2)
    eng_out(XBAR12, 0x80000000)
    local dt = get_tick_count() - t0
    local written = 0
    for k = 0, (size / 4096) - 1 do
        if peek(buf + k * 4096, 4) ~= 0xdeadbeef then
            written = written + 1
        end
    end
    logf("port=0x%02x done %d ms ctl=0x%x 4KB_written=%d/%d", port, dt, ctl, written, size / 4096)
    logf("PTR %s", table.concat(samples, " "))
    local name = string.format("A/P%02X.BIN", port)
    local fd = call_func_ptr(FN_OPEN, name, 0x301, 511)
    if fd >= 0 then
        local w = call_func_ptr(FN_WRITE, fd, buf, size)
        call_func_ptr(FN_CLOSE, fd)
        logf("Saved %s (%d bytes)", name, w)
    end
    return written
end

for i, j in ipairs(jobs) do
    print(string.format("%d/%d port 0x%02x", i, #jobs, j[1]))
    capture(j[1], j[2])
end

call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
log:close()
print("OK, voir M10RGB.TXT")
sleep(2000)
