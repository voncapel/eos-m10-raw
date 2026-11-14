--[[
@title M10 Zoom5x Gate+Scan
@chdk_version 1.5
@param g Allumer canal (1=oui 0=non)
@default g 1
@param q First port (dec)
@default q 0
@param p Last port (dec, 127=0x7f)
@default p 127
]]

-- probe16 (EDREG): in Zoom x5 the EDMAC block of CH12 is not clocked:
-- registers programmed with EngDrvOut read back 0 directly from the hardware.
-- ROM 110d: 0xfc3763ac(idx) = Canon "enable channel" (sets the clock-gate bit
-- from RAM table 0x28e18[idx] in 0xc0f04f14 for idx 0..15, and 0x300000 in base+4).
-- 0xfc376452(idx) = matching "disable".
-- This script: logs the gate registers, calls Canon's enable for CH12 (g=1),
-- checks the readback, scans ports q..p, then calls Canon's disable.
-- Output: A/M10GATE.TXT + A/PGATE.BIN (64 KB per port)

local FN_ENGDRV_OUT  = 0xfc02109d
local FN_ENGDRV_READ = 0xfc38d2b9
local FN_OPEN        = 0xfc389801
local FN_WRITE       = 0xfc3898bd
local FN_CLOSE       = 0xfc389885
local FN_EXMEM_UALLOC= 0xfc08169d
local FN_EXMEM_UFREE = 0xfc081757
local FN_EDMAC_ON    = 0xfc3763ad   -- thumb
local FN_EDMAC_OFF   = 0xfc376453   -- thumb

if type(call_func_ptr) ~= "function" then
    print("Activez Lua Native Calls !")
    sleep(3000)
    return
end

local log = io.open("A/M10GATE.TXT", "w")
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

local CH, BASE = 12, 0xc0f26500
local XR = 0xc0f051e0 + CH * 4
local enabled = false

local function finish(msg)
    if enabled then
        call_func_ptr(FN_EDMAC_OFF, CH)
        logf("Canon disable(%d) called, gate f14=0x%08x", CH, shamem_read(0xc0f04f14))
    end
    call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
    log:close()
    print(msg)
    sleep(2500)
end

logf("=== M10GATE g=%d buf=0x%08x dss_flags=0x%08x dss_wh=%dx%d ===",
     g, buf, peek(0x00028738, 4), peek(0x001beb5c, 4), peek(0x001beb60, 4))

if shamem_read(0xc0f06804) == 0 or peek(0x00028738, 4) == 0 then
    logf("ABORT: LiveView inactive")
    finish("LiveView inactif: passer en mode prise de vue")
    return
end
logf("6800=0x%08x 6804=0x%08x 6008=0x%08x 6014=0x%08x",
     shamem_read(0xc0f06800), shamem_read(0xc0f06804),
     shamem_read(0xc0f06008), shamem_read(0xc0f06014))

-- gate registers (shadow) and RAM bit table
local function log_gates(tag)
    local s = {}
    for _, r in ipairs({0xc0f04f14, 0xc0f04f18, 0xc0f04f1c, 0xc0f04f20,
                        0xc0f04f24, 0xc0f04f28, 0xc0f58f14, 0xc0f58f1c}) do
        s[#s + 1] = string.format("%x=%08x", r, shamem_read(r))
    end
    logf("GATES %s %s", tag, table.concat(s, " "))
end
local tb = {}
for i = 0, 0x2f do
    tb[#tb + 1] = string.format("%x", peek(0x00028e18 + i * 4, 4))
end
logf("BITTABLE 0x28e18 %s", table.concat(tb, " "))
logf("bit for idx %d = 0x%08x", CH, peek(0x00028e18 + CH * 4, 4))
log_gates("before")

if shamem_read(XR) ~= 0x80000000 or peek(BASE, 4) ~= 0 then
    logf("CH%d busy (xbar=0x%08x ctl=0x%x), abort", CH, shamem_read(XR), peek(BASE, 4))
    finish("CH12 occupe, abandon")
    return
end

if g == 1 then
    call_func_ptr(FN_EDMAC_ON, CH)
    enabled = true
    log_gates("after_enable")
end

local SLOT = 0x10000
local XB = 4096
local YB = (SLOT / XB) - 1
local xbyb = bitor(bitshl(YB, 16), XB)

local function grab(port, dst)
    for k = 0, (SLOT / 1024) - 1 do
        poke(dst + k * 1024, 0xdeadbeef, 4)
    end
    eng_out(BASE + 0x40, 0)
    eng_out(BASE + 0x04, 0x20000000)
    eng_out(BASE + 0x08, bitand(dst, 0x3fffffff))
    eng_out(BASE + 0x0c, 0)
    eng_out(BASE + 0x10, xbyb)
    eng_out(BASE + 0x14, xbyb)
    for off = 0x18, 0x28, 4 do
        eng_out(BASE + off, 0)
    end
    local rb = peek(BASE + 0x08, 4)          -- direct readback: 0 = block not clocked
    eng_out(XR, port)
    eng_out(BASE + 0x00, 1)
    local ctl, loops = 1, 0
    while ctl ~= 0 and loops < 6 do
        sleep(10)
        ctl = peek(BASE + 0x00, 4)
        loops = loops + 1
    end
    eng_out(BASE + 0x00, 2)
    eng_out(XR, 0x80000000)
    local written = 0
    for k = 0, (SLOT / 1024) - 1 do
        if peek(dst + k * 1024, 4) ~= 0xdeadbeef then
            written = written + 1
        end
    end
    return written, ctl, loops, rb
end

-- test on port 0x04 (always active)
local kb, ctl, loops, rb = grab(0x04, buf)
logf("TEST port 0x04: readback=0x%08x kb_written=%d ctl=0x%x loops=%d w0=0x%08x",
     rb, kb, ctl, loops, peek(buf, 4))
if kb == 0 then
    finish(string.format("Echec: readback=%08x, 0 KB", rb))
    return
end
print("Canal OK ! scan...")

local n = 0
for port = q, p do
    local dst = buf + n * SLOT
    if (n + 1) * SLOT > 0x00e00000 then
        logf("buffer full, stop at port 0x%02x", port)
        break
    end
    logf("try port=0x%02x", port)
    kb, ctl, loops, rb = grab(port, dst)
    logf("slot=%d port=0x%02x rt=-1 ctl=0x%x loops=%d kb_written=%d w0=0x%08x w1=0x%08x",
         n, port, ctl, loops, kb, peek(dst, 4), peek(dst + 4, 4))
    n = n + 1
    if (n % 16) == 0 then
        print(string.format("port 0x%02x ...", port))
    end
end

local fd = call_func_ptr(FN_OPEN, "A/PGATE.BIN", 0x301, 511)
if fd >= 0 then
    local w = call_func_ptr(FN_WRITE, fd, buf, n * SLOT)
    call_func_ptr(FN_CLOSE, fd)
    logf("Saved A/PGATE.BIN (%d bytes, %d slots of %d)", w, n, SLOT)
end
log_gates("end")
finish("OK, voir M10GATE.TXT")
