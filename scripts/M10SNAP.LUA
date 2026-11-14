--[[
@title M10 Safe Bayer RAW Snap
@chdk_version 1.5
@param tag Mode Tag (0=LV, 1=Zoom5x)
@default tag 0
]]

-- 100% READ-ONLY SCRIPT: zero register writes, zero mode changes, cannot trigger DebugAssert!
local FN_ENGDRV_READ = 0xfc38d2b9
local FN_OPEN        = 0xfc389801
local FN_WRITE       = 0xfc3898bd
local FN_CLOSE       = 0xfc389885

if type(call_func_ptr) ~= "function" then
    print("Activez Lua Native Calls !")
    sleep(3000)
    return
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

local suffix = (tag == 1) and "Z5X" or "LV"
local log = io.open("A/M10SNAP_" .. suffix .. ".TXT", "w")
local function logf(fmt, ...)
    log:write(string.format(fmt, ...) .. "\n")
    log:flush()
end

logf("=== M10 SAFE BAYER SNAP (%s) ===", suffix)
for _, r in ipairs({0xc0f06008, 0xc0f0600c, 0xc0f06014, 0xc0f06800, 0xc0f06804, 0xc0f58004, 0xc0f58008, 0xc0f58010, 0xc0f58054, 0xc0f58e80, 0xc0f58e90, 0xc0f58e94}) do
    logf("  REG 0x%08x = 0x%08x", r, shamem_read(r))
end

-- Dump ring buffer pointer registers 0xc0f051e0..0xc0f05250
logf("--- Ring Buffer Table Registers (0xc0f051e0..0xc0f05250) ---")
for r = 0xc0f051e0, 0xc0f05250, 4 do
    local v = shamem_read(r)
    if v ~= 0 then
        logf("  RING 0x%08x = 0x%08x", r, v)
    end
end

-- Dump DirectSSCaptureDriver RAM struct around 0x001beb00..0x001bec00
logf("--- DirectSSCaptureDriver Struct (0x001beb00..0x001bec00) ---")
for a = 0x001beb00, 0x001bec00, 4 do
    local v = peek(a, 4)
    if v ~= 0 then
        logf("  RAM  0x%08x = 0x%08x", a, v)
    end
end

-- Resolve CH22 (0x16) live Bayer RAW buffer address
local r10 = shamem_read(0xc0f58010)
local xb = bitand(r10, 0xffff)
local yb = bitshru(r10, 16)
local ptr_reg = shamem_read(0xc0f05238)
local ptr_ram = peek(0x001beb30, 4)
logf("CH22 xbyb=%dx%d ptr_reg(0xc0f05238)=0x%08x ptr_ram(0x001beb30)=0x%08x", xb, yb, ptr_reg, ptr_ram)

-- Check if ptr_ram or ptr_reg is a direct frame buffer or a table of frame buffer pointers
local candidates = {}
local function check_candidate(label, p)
    if p >= 0x01000000 and p < 0x60000000 then
        -- Also log first 8 words at p in case p is a ring descriptor table!
        local w0 = peek(p, 4)
        local w1 = peek(p + 4, 4)
        local w2 = peek(p + 8, 4)
        local w3 = peek(p + 12, 4)
        logf("  [%s @ 0x%08x] words: 0x%08x 0x%08x 0x%08x 0x%08x", label, p, w0, w1, w2, w3)
        table.insert(candidates, {label, p})
        -- If w0 itself looks like a large RAM buffer (e.g. 0x1xxxxxxx or 0x4xxxxxxx aligned to 0x100)
        if (w0 >= 0x02000000 and w0 < 0x60000000) and bitand(w0, 0x3f) == 0 then
            table.insert(candidates, {label .. "_slot0", w0})
        end
    end
end

check_candidate("R5238", ptr_reg)
if ptr_ram ~= ptr_reg then
    check_candidate("RAM30", ptr_ram)
end

local frame_sz = xb * (yb + 1)
if frame_sz < 1048576 or frame_sz > 12582912 then
    frame_sz = 6291456 -- 6 MB fallback
end

for idx, c in ipairs(candidates) do
    local out = string.format("A/BAY_%s_%d.RAW", suffix, idx)
    print("Dump " .. out .. "...")
    local w = dump_file(out, c[2], frame_sz)
    logf("  -> Dumped %s from 0x%08x (%d bytes)", out, c[2], w)
end

log:close()
print("Capture RAW OK !")
sleep(1500)
