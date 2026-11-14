--[[
@title M10 Clean Full Bayer Frame
@chdk_version 1.5
@param tag 0=LV 1=Zoom5x
@default tag 0
]]

-- Exact 2-byte/pixel transfer (0x20000000) + fast 1-frame capture (<45ms) so CH22 watchdog never trips!
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

local suffix = (tag == 1) and "Z5X" or "LV"
local log = io.open("A/M10FRM_" .. suffix .. ".TXT", "w")
local function logf(fmt, ...)
    log:write(string.format(fmt, ...) .. "\n")
    log:flush()
end

local function shamem_read(reg)
    return call_func_ptr(FN_ENGDRV_READ, reg)
end

local function dump_file(path, addr, size)
    local fd = call_func_ptr(FN_OPEN, path, 0x301, 511)
    if fd < 0 then return -1 end
    local w = call_func_ptr(FN_WRITE, fd, addr, size)
    call_func_ptr(FN_CLOSE, fd)
    return w
end

local EXMEM_TYPE = 5
local buf = call_func_ptr(FN_EXMEM_UALLOC, EXMEM_TYPE, 0x01000000, 0)
logf("=== M10FRAME (%s) buf=0x%08x dss_flags(0x28738)=0x%08x ===",
     suffix, buf, peek(0x00028738, 4))
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

-- Read exact active pixel width & height from DirectSSCaptureDriver & CH22
local r10 = shamem_read(0xc0f58010)
local ch22_xb = bitand(r10, 0xffff)
local ch22_yb = bitshru(r10, 16)
local dss_w = peek(0x001beb5c, 4) -- 1728 in LV; will show exact width in Zoom5x!
local dss_h = peek(0x001beb60, 4) -- 972 in LV; will show exact height in Zoom5x!
local port_ch22 = shamem_read(0xc0f05238)

logf("DSS wxh=%dx%d CH22 xbyb=%dx%d port=0x%x 6800=0x%08x 6804=0x%08x e90=0x%08x",
     dss_w, dss_h, ch22_xb, ch22_yb, port_ch22,
     shamem_read(0xc0f06800), shamem_read(0xc0f06804), shamem_read(0xc0f58e90))

local xb = (dss_w > 0) and (dss_w * 2) or 3456
local yb = (dss_h > 0) and (dss_h - 1) or 971

for i = 0, 15 do
    poke(buf + i * 4, 0xdeadbeef, 4)
end

local base = 0xc0f26500 -- Write Channel 12
local xbyb = bitor(bitshl(yb, 16), xb)
eng_out(base + 0x40, 0)
eng_out(base + 0x04, 0x20000000) -- EDMAC_2_BYTES_PER_TRANSFER (tight 16-bit Bayer pixels, zero padding!)
eng_out(base + 0x08, bitand(buf, 0x3fffffff))
eng_out(base + 0x0c, 0)
eng_out(base + 0x10, xbyb)
eng_out(base + 0x14, xbyb)
eng_out(base + 0x18, 0)
eng_out(base + 0x1c, 0)
eng_out(base + 0x20, 0)
eng_out(base + 0x24, 0)
eng_out(base + 0x28, 0)

-- Atomic 1-frame capture: detach CH22, attach CH12, poll every 10ms until ctl==0, restore CH22 immediately!
local t0 = get_tick_count()
eng_out(0xc0f05238, 0x80000000)
eng_out(0xc0f05210, port_ch22)
eng_out(base + 0x00, 1)

local ctl = 1
local loops = 0
while ctl ~= 0 and loops < 8 do
    sleep(10)
    ctl = peek(base + 0x00, 4)
    loops = loops + 1
end

-- Restore CH22 immediately!
eng_out(base + 0x00, 2)
eng_out(0xc0f05210, 0x80000000)
eng_out(0xc0f05238, port_ch22)
local dt = get_tick_count() - t0

local w0 = peek(buf, 4)
local w1 = peek(buf + 4, 4)
logf("Capture done in %d ms (loops=%d ctl=0x%x): w0=0x%08x w1=0x%08x", dt, loops, ctl, w0, w1)

local frame_bytes = xb * (yb + 1)
if w0 ~= 0xdeadbeef then
    local out_raw = "A/FRM_" .. suffix .. ".RAW"
    local written = dump_file(out_raw, buf, frame_bytes)
    logf("Saved %s (%d bytes)", out_raw, written)
    print(string.format("OK %dx%d (%dms)", xb / 2, yb + 1, dt))
else
    print("Echec capture")
end

call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
log:close()
sleep(2000)
