--[[
@title M10 Port 0x36 Long Capture
@chdk_version 1.5
@param s Source port (dec, 54=0x36)
@default s 54
@param m Megabytes to capture (1-12)
@default m 8
@param t Tag 0=LV 1=Zoom5x 2=Video
@default t 0
]]

-- Port 0x36 (found by M10PORTS on 2026-11-06) streams 16-bit words whose low
-- 2 bits are always 0 and whose floor is ~8160 (= 2040 << 2, CHDK black 2047):
-- candidate linear sensor RAW. No Canon channel consumes it, so CH12 can tap
-- it without disturbing LiveView. This script captures m MB in one go and
-- samples the EDMAC current pointer (base+0x08) every 10 ms, so the frame
-- size can be derived from bytes-per-frame-period (25 fps = 40 ms).

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

local TAGS = {[0]="LV", [1]="Z5", [2]="MV"}
local tag = TAGS[t] or "LV"
local log = io.open("A/M10P36" .. tag .. ".TXT", "w")
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

logf("=== M10P36 %s port=0x%02x buf=0x%08x dss_flags=0x%08x dss_wh=%dx%d ===", tag, s, buf, peek(0x00028738, 4), peek(0x001beb5c, 4), peek(0x001beb60, 4))
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

if m < 1 then m = 1 end
if m > 12 then m = 12 end
local XB   = 4096
local size = m * 0x100000
local YB   = (size / XB) - 1
local CH12   = 0xc0f26500
local XBAR12 = 0xc0f05210

-- one marker per 4 KB to measure what was really written
for k = 0, (size / 4096) - 1 do
    poke(buf + k * 4096, 0xdeadbeef, 4)
end

eng_out(CH12 + 0x40, 0)
eng_out(CH12 + 0x04, 0x20000000)             -- EDMAC_2_BYTES_PER_TRANSFER
eng_out(CH12 + 0x08, bitand(buf, 0x3fffffff))
eng_out(CH12 + 0x0c, 0)
eng_out(CH12 + 0x10, bitor(bitshl(YB, 16), XB))
eng_out(CH12 + 0x14, bitor(bitshl(YB, 16), XB))
for off = 0x18, 0x28, 4 do
    eng_out(CH12 + off, 0)
end

local phys0 = bitand(buf, 0x3fffffff)
local t0 = get_tick_count()
eng_out(XBAR12, s)
eng_out(CH12 + 0x00, 1)

-- sample the running pointer: up to 60 x 10 ms = 600 ms
local samples = {}
local ctl = 1
local n = 0
while ctl ~= 0 and n < 60 do
    sleep(10)
    ctl = peek(CH12 + 0x00, 4)
    local ptr = peek(CH12 + 0x08, 4)
    n = n + 1
    samples[n] = string.format("%d:%d", get_tick_count() - t0, bitand(ptr, 0x3fffffff) - phys0)
end
eng_out(CH12 + 0x00, 2)
eng_out(XBAR12, 0x80000000)
local dt = get_tick_count() - t0

logf("done in %d ms ctl=0x%x samples=%d", dt, ctl, n)
logf("PTR %s", table.concat(samples, " "))

local written = 0
local last = -1
for k = 0, (size / 4096) - 1 do
    if peek(buf + k * 4096, 4) ~= 0xdeadbeef then
        written = written + 1
        last = k
    end
end
logf("4KB blocks written=%d last=%d of %d", written, last, size / 4096)

local fname = "A/P36" .. tag .. ".BIN"
local fd = call_func_ptr(FN_OPEN, fname, 0x301, 511)
if fd >= 0 then
    local w = call_func_ptr(FN_WRITE, fd, buf, size)
    call_func_ptr(FN_CLOSE, fd)
    logf("Saved %s (%d bytes)", fname, w)
end

call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
log:close()
print(string.format("OK %d ms, %d/%d blocs", dt, written, size / 4096))
sleep(2000)
