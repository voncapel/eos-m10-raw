--[[
@title M10 Port4 Bayer RAW Tap
@chdk_version 1.5
@param tag 0=LV 1=Zoom5x
@default tag 0
]]

-- Zero OS calls (no StopEVF/StartEVF -> zero DebugAssert!)
-- Directly taps Port 4 (live Bayer RAW sensor stream) onto idle EDMAC Write Ch 12 (0xc0f26500)
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
local log = io.open("A/M10TAP4_" .. suffix .. ".TXT", "w")
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
logf("=== M10TAP4 (%s) buf=0x%08x ===", suffix, buf)
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

-- Read current live geometry straight from CH22 (0xc0f58000) & sensor window (0xc0f06804)
local r10 = shamem_read(0xc0f58010)
local xb = bitand(r10, 0xffff)
local yb = bitshru(r10, 16)
local port_ch22 = shamem_read(0xc0f05238)
logf("Live CH22: port=0x%x xb=%d yb=%d 6800=0x%08x 6804=0x%08x e90=0x%08x",
     port_ch22, xb, yb, shamem_read(0xc0f06800), shamem_read(0xc0f06804), shamem_read(0xc0f58e90))

if xb == 0 or yb == 0 then
    xb = 3488
    yb = 971
end

local function setup_ch12()
    for i = 0, 31 do
        poke(buf + i * 4, 0xdeadbeef, 4)
    end
    local base = 0xc0f26500 -- Write Channel 12
    local xbyb = bitor(bitshl(yb, 16), xb)
    eng_out(base + 0x40, 0)
    eng_out(base + 0x04, 0x00001000) -- 16-byte burst / 16-bit mode (from FUN_fc3759f6)
    eng_out(base + 0x08, bitand(buf, 0x3fffffff))
    eng_out(base + 0x0c, 0)
    eng_out(base + 0x10, xbyb)
    eng_out(base + 0x14, xbyb)
    eng_out(base + 0x18, 0)
    eng_out(base + 0x1c, 0)
    eng_out(base + 0x20, 0)
    eng_out(base + 0x24, 0)
    eng_out(base + 0x28, 0)
end

-- TEST A: Passive multicast tap on Crossbar Port 4 (0xc0f05210 = port_ch22)
print("Test A: Tap passif Port 4...")
setup_ch12()
eng_out(0xc0f05210, port_ch22) -- Connect CH12 to Port 4 alongside CH22
eng_out(0xc0f26500, 1)         -- Start CH12
sleep(100)

local w0 = peek(buf, 4)
local w1 = peek(buf + 4, 4)
logf("Test A (multicast): ctl=0x%x w0=0x%08x w1=0x%08x", peek(0xc0f26500, 4), w0, w1)

-- Disconnect CH12 if still armed
eng_out(0xc0f26500, 2)
eng_out(0xc0f05210, 0x80000000)

-- TEST B: If multicast didn't fire, steal 1 single frame (60 ms) from Port 4 -> CH12, then restore CH22!
if w0 == 0xdeadbeef then
    print("Test B: Switch 1 trame (60ms)...")
    setup_ch12()
    eng_out(0xc0f05238, 0x80000000) -- Detach CH22 for 1 frame
    eng_out(0xc0f05210, port_ch22)  -- Attach CH12 to Port 4
    eng_out(0xc0f26500, 1)          -- Start CH12
    sleep(70)
    -- Immediately restore CH22 so LiveView keeps running!
    eng_out(0xc0f05210, 0x80000000)
    eng_out(0xc0f05238, port_ch22)
    w0 = peek(buf, 4)
    w1 = peek(buf + 4, 4)
    logf("Test B (1-frame steal): ctl=0x%x w0=0x%08x w1=0x%08x", peek(0xc0f26500, 4), w0, w1)
end

local frame_bytes = xb * (yb + 1)
if w0 ~= 0xdeadbeef then
    local out_raw = "A/TAP4_" .. suffix .. ".RAW"
    local written = dump_file(out_raw, buf, frame_bytes)
    logf("SUCCESS! Saved %s (%d bytes)", out_raw, written)
    print("BINGO RAW CAPTURE ! " .. string.format("%08x", w0))
else
    logf("Buffer unchanged (0xdeadbeef)")
    print("Toujours deadbeef (voir TXT)")
end

call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
log:close()
sleep(2500)
