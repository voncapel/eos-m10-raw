--[[
@title M10 2.5K RAW Capture Test
@chdk_version 1.5
@param r Dump 110d ROM 8MB (0/1)
@default r 1
@param m Switch to 2.5K Mode (0/1)
@default m 1
]]

-- Verified Canon EOS M10 1.10d addresses
local FN_ENGDRV_OUT  = 0xfc02109d -- EngDrvOut_FW(uint32_t pair[2])
local FN_ENGDRV_READ = 0xfc38d2b9 -- EngDrvRead(uint32_t reg)
local FN_OPEN        = 0xfc389801
local FN_WRITE       = 0xfc3898bd
local FN_CLOSE       = 0xfc389885
local FN_EXMEM_UALLOC= 0xfc08169d -- exmem_ualloc(type, size, 0)
local FN_EXMEM_UFREE = 0xfc081757 -- exmem_ufree(type)
local FN_HEAD_DIRECT = 0xfc5ba89f -- EnableHeadDirectCapturePath_FW()
local FN_MODE_25K    = 0xfc156ec7 -- ChangeImagerToLasVegasMagic_FW() -> 2592x1108

if type(call_func_ptr) ~= "function" then
    print("Activez Lua Native Calls !")
    sleep(3000)
    return
end

local log = io.open("A/M10RAW25.TXT", "w")
local function logf(fmt, ...)
    log:write(string.format(fmt, ...) .. "\n")
    log:flush()
end

local function dump_file(path, addr, size)
    local fd = call_func_ptr(FN_OPEN, path, 0x301, 511)
    if fd < 0 then return -1 end
    local w = call_func_ptr(FN_WRITE, fd, addr, size)
    call_func_ptr(FN_CLOSE, fd)
    return w
end

-- 1. Dump exact 110d ROM (8 MB from 0xfc000000) so we have exact 110d code on Mac
if r == 1 then
    print("1/3 Dump ROM 110d (8Mo)...")
    local w = dump_file("A/ROM110D.BIN", 0xfc000000, 0x800000)
    logf("ROM110D.BIN dumped: %d bytes", w)
end

-- 2. Allocate 16 MB uncached EXMEM buffer (EXMEM_FIRMUP = 5)
local EXMEM_TYPE = 5
local buf = call_func_ptr(FN_EXMEM_UALLOC, EXMEM_TYPE, 0x01000000, 0)
logf("exmem_ualloc(5, 16MB) = 0x%08x", buf)
if buf == 0 then
    print("Erreur alloc EXMEM !")
    log:close()
    sleep(3000)
    return
end

-- Scratch 8-byte pair at buf + 15MB for EngDrvOut_FW({reg, val})
local scratch = buf + 0x00f00000
local function eng_out(reg, val)
    poke(scratch, reg, 4)
    poke(scratch + 4, val, 4)
    call_func_ptr(FN_ENGDRV_OUT, scratch)
end

local function shamem_read(reg)
    return call_func_ptr(FN_ENGDRV_READ, reg)
end

local function capture_ch12_raw(tag, width_px, height_lines, out_name)
    -- Clear test marker words at start of buffer
    for i = 0, 15 do
        poke(buf + i * 4, 0xdeadbeef, 4)
    end

    local xb = (width_px * 14) / 8 -- 14-bit packed bytes per row
    local yb = height_lines - 1
    local xbyb = bitor(bitshl(yb, 16), xb)
    local phys_addr = bitand(buf, 0x3fffffff)

    -- Enable HeadDirectCapturePath & route sensor RAW to crossbar port 0 -> CH12 (0xc0f26500)
    call_func_ptr(FN_HEAD_DIRECT)
    local r37014 = shamem_read(0xc0f37014)
    eng_out(0xc0f37014, bitor(bitand(r37014, 0xffffffc0), 0x22))

    local base = 0xc0f26500 -- EDMAC Write Channel 12
    eng_out(base + 0x04, 0x00000000) -- Connect to port 0, pack flags 0
    eng_out(base + 0x40, 0x00000000)
    eng_out(base + 0x08, phys_addr)
    eng_out(base + 0x0c, 0x00000000)
    eng_out(base + 0x10, xbyb)
    eng_out(base + 0x14, xbyb)
    eng_out(base + 0x18, 0)
    eng_out(base + 0x1c, 0)
    eng_out(base + 0x20, 0)
    eng_out(base + 0x24, 0)
    eng_out(base + 0x28, 0)

    -- Start CH12 and pulse sensor Head->RAW trigger (0xc0f08090 bit 31)
    eng_out(base + 0x00, 1)
    local r8090 = shamem_read(0xc0f08090)
    eng_out(0xc0f08090, bitor(r8090, 0x80000000))
    eng_out(0xc0f08090, r8090)

    sleep(150)
    local w0 = peek(buf, 4)
    local w1 = peek(buf + 4, 4)
    local ctl_after = peek(base + 0x00, 4)
    logf("[%s] %dx%d (xb=%d) ctl_after=0x%x w0=0x%08x w1=0x%08x", tag, width_px, height_lines, xb, ctl_after, w0, w1)
    logf("  regs: 6008=0x%08x 6014=0x%08x 6800=0x%08x 6804=0x%08x",
         shamem_read(0xc0f06008), shamem_read(0xc0f06014),
         shamem_read(0xc0f06800), shamem_read(0xc0f06804))

    local frame_bytes = xb * height_lines
    local written = dump_file(out_name, buf, frame_bytes)
    logf("  saved %s (%d bytes)", out_name, written)
end

print("2/3 Capture LV 1808x1190...")
capture_ch12_raw("LV1808", 1808, 1190, "A/LV14_1808.RAW")

if m == 1 then
    print("3/3 Switch 2.5K 2592x1108...")
    local rc = call_func_ptr(FN_MODE_25K)
    logf("ChangeImagerToLasVegasMagic_FW rc=0x%x", rc)
    sleep(500)
    capture_ch12_raw("LV2592", 2592, 1108, "A/LV14_2592.RAW")
end

call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
log:close()
print("OK! Voir M10RAW25.TXT")
sleep(2000)
