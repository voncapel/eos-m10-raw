--[[
@title M10 Clock Map
@chdk_version 1.5
]]

-- probe17 (M10GATE): calling Canon's 0xfc3763ac(12) only sets an interrupt
-- mask bit (0xc0f04f14 |= 0x03000000); CH12 registers still read back 0 in
-- Zoom x5. The channel block itself is not clocked/powered.
-- Pwrcnt.c (0xfc375588 / 0xfc373f9e) drives clock/power registers 0xc0f01xxx
-- listed in ROM tables 0xfc6dd9a4 and 0xfc6ddf50; Edmac.c writes 0xc0f01074.
-- This script (read-mostly, no DMA started):
--   1. dumps all those clock registers, DIRECT and SHADOW,
--   2. for every idle channel idx 7..20: writes a test address into base+8,
--      reads it back directly (0 = not clocked), restores the shadow value.
-- Output: A/PWR_<dss width>.TXT (PWR_1728 = LV normal, PWR_1032 = Zoom x5)

local FN_ENGDRV_OUT  = 0xfc02109d
local FN_ENGDRV_READ = 0xfc38d2b9
local FN_EXMEM_UALLOC= 0xfc08169d
local FN_EXMEM_UFREE = 0xfc081757

if type(call_func_ptr) ~= "function" then
    print("Activez Lua Native Calls !")
    sleep(3000)
    return
end

-- file name chosen from the live DSS width (1728/1032...), no parameter to set
local tag = tostring(peek(0x001beb5c, 4))
local log = io.open("A/PWR_" .. tag .. ".TXT", "w")
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

logf("=== M10PWR %s dss_flags=0x%08x dss_wh=%dx%d ===",
     tag, peek(0x00028738, 4), peek(0x001beb5c, 4), peek(0x001beb60, 4))
if shamem_read(0xc0f06804) == 0 or peek(0x00028738, 4) == 0 then
    logf("ABORT: LiveView inactive")
    finish("LiveView inactif: passer en mode prise de vue")
    return
end
logf("6800=0x%08x 6804=0x%08x", shamem_read(0xc0f06800), shamem_read(0xc0f06804))

-- 1. clock / power registers (addresses taken from the ROM tables)
-- Pwrcnt.c reads the table registers directly (0xfc38d2a6): safe to peek
local regs = {}
for i = 0, 59 do regs[#regs + 1] = peek(0xfc6dd9a4 + i * 4, 4) end
for i = 0, 15 do regs[#regs + 1] = peek(0xfc6ddf50 + i * 4, 4) end
for _, r in ipairs(regs) do
    if r >= 0xc0f00000 and r < 0xc0f60000 then
        logf("REG %08x D=%08x S=%08x", r, peek(r, 4), shamem_read(r))
    end
end
-- other clock / gate registers: shadow only (no direct MMIO read)
for _, r in ipairs({0xc0f0100c, 0xc0f01074, 0xc0f01094, 0xc0f010a4,
                    0xc0f010c0, 0xc0f010c4, 0xc0f010c8, 0xc0f010cc,
                    0xc0f010d0, 0xc0f010d4, 0xc0f010d8, 0xc0f010dc,
                    0xc0f010e0, 0xc0f010e4, 0xc0f010e8, 0xc0f010ec,
                    0xc0f010f0, 0xc0f010f4, 0xc0f010f8,
                    0xc0f04f14, 0xc0f04f18, 0xc0f04f1c, 0xc0f04f20,
                    0xc0f04f24, 0xc0f04f28, 0xc0f58f14, 0xc0f58f1c}) do
    logf("SREG %08x S=%08x", r, shamem_read(r))
end

-- 2. per-channel clock test (address register write/readback, no start)
local BASES = {
    [7]=0xc0f26000, [8]=0xc0f26100, [9]=0xc0f26200, [10]=0xc0f26300,
    [11]=0xc0f26400, [12]=0xc0f26500, [13]=0xc0f26600,
    [14]=0xc0f30000, [15]=0xc0f30100, [16]=0xc0f30200, [17]=0xc0f30300,
    [18]=0xc0f30400, [19]=0xc0f30500, [20]=0xc0f30600,
}
local TEST = bitand(buf, 0x3fffffff)
for i = 7, 20 do
    local base = BASES[i]
    local xv = shamem_read(0xc0f051e0 + i * 4)
    local ctl = peek(base, 4)
    if xv == 0x80000000 and ctl == 0 then
        local old = shamem_read(base + 0x08)
        eng_out(base + 0x08, TEST)
        local rb = peek(base + 0x08, 4)
        eng_out(base + 0x08, old)
        logf("CHK idx%02d base=%08x readback=%08x %s", i, base, rb,
             (rb == TEST) and "CLOCKED" or "DEAD")
    else
        logf("CHK idx%02d base=%08x busy xbar=%08x ctl=%x ptr=%08x", i, base, xv, ctl,
             peek(base + 0x08, 4))
    end
end

finish("OK " .. tag)
