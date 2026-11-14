--[[
@title M10 PACK32 RAW 1 transfert
@chdk_version 1.5
@param L Lignes au total
@default L 1107
@param S Lignes par bloc
@default S 554
]]

-- One EDMAC transfer covering more than 4 MiB, using the 2-D geometry
-- (ML edmac.c edmac_get_total_size, xn = 0):
--   total = xb*(ya+1)*yn + xb*(yb+1)
-- 0x0c = yn<<16 | xn, 0x14 = ya<<16 | xa, 0x10 = yb<<16 | xb.
-- Every block (ya+1 or yb+1 lines) stays far below the 4 MiB stall found in
-- probe32, but the channel runs once: no re-arm, no lost samples (probe35
-- lost 288 samples at the re-arm). Default 554 + 553 = 1107 lines = 1 frame.
-- If the total limit is really 4 MiB, it stalls at 0 lines (battery pull).
-- Timing with the 20-bit microsecond counter 0xc0242014.
-- Output: A/PKYN.TXT, A/PKYN.BIN

local FN_ENGDRV_OUT  = 0xfc02109d
local FN_ENGDRV_READ = 0xfc38d2b9
local FN_OPEN        = 0xfc389801
local FN_WRITE       = 0xfc3898bd
local FN_CLOSE       = 0xfc389885
local FN_EXMEM_UALLOC= 0xfc08169d
local FN_EXMEM_UFREE = 0xfc081757
local FN_PK_TAKE     = 0xfc22f739
local FN_PK_ON       = 0xfc22f73f
local FN_PK_OFF      = 0xfc22f7dd
local FN_RES_LOCK    = 0xfc373f9f
local FN_RES_UNLOCK  = 0xfc375589

if type(call_func_ptr) ~= "function" then
    print("Activez Lua Native Calls !")
    sleep(3000)
    return
end

local log = io.open("A/PKYN.TXT", "w")
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
local RESLIST = scratch + 0x100
local function eng_out(reg, val)
    poke(scratch, reg, 4)
    poke(scratch + 4, val, 4)
    call_func_ptr(FN_ENGDRV_OUT, scratch)
end
local function shamem_read(reg)
    return call_func_ptr(FN_ENGDRV_READ, reg)
end

local CH, BASE, XR = 12, 0xc0f26500, 0xc0f05210
local CHREGS = {0x04, 0x08, 0x0c, 0x10, 0x14, 0x18, 0x1c, 0x20, 0x24, 0x28, 0x40}
local REGS = {0xc0f37014, 0xc0f37074, 0xc0f37274, 0xc0f08090, 0xc0f08094, 0xc0f082bc}
local function regs_str()
    local s = {}
    for _, r in ipairs(REGS) do s[#s + 1] = string.format("%x=%08x", r, shamem_read(r)) end
    return table.concat(s, " ")
end
local function idle()
    for k = 1, 20 do
        if shamem_read(XR) ~= 0x80000000 or peek(BASE, 4) ~= 0 then return false end
        sleep(5)
    end
    return true
end
local function clocked()
    local old8 = shamem_read(BASE + 0x08)
    eng_out(BASE + 0x08, bitand(buf, 0x3fffffff))
    local rb = peek(BASE + 0x08, 4)
    eng_out(BASE + 0x08, old8)
    return rb == bitand(buf, 0x3fffffff)
end
local function stop_dma()
    local t1 = get_tick_count()
    eng_out(BASE + 0x00, 2)
    while peek(BASE, 4) ~= 0 and get_tick_count() - t1 < 300 do
        sleep(10)
        eng_out(BASE + 0x00, 2)
    end
    if shamem_read(XR) ~= 0x80000000 then eng_out(XR, 0x80000000) end
    sleep(50)
    return peek(BASE, 4) == 0, get_tick_count() - t1
end


local function live_ok()
    return shamem_read(0xc0f06804) ~= 0 and peek(0x00028738, 4) ~= 0
end
local function usec() return bitand(peek(0xc0242014, 4), 0xfffff) end
local function udiff(a, b) return bitand(b - a, 0xfffff) end

logf("=== M10PKYN L=%d S=%d dss=%08x wh=%dx%d 6800=%08x 6804=%08x ===", L, S,
     peek(0x00028738, 4), peek(0x001beb5c, 4), peek(0x001beb60, 4),
     shamem_read(0xc0f06800), shamem_read(0xc0f06804))

local function bye(msg)
    call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
    logf("%s", msg)
    log:close()
    print(msg)
    sleep(3000)
end

local r6800, r6804 = shamem_read(0xc0f06800), shamem_read(0xc0f06804)
local w = (bitand(r6804, 0xffff) - bitand(r6800, 0xffff)) * 4
local XBY = w * 2
local q = (L + S - 1) / S                      -- number of blocks (integer Lua)
local yn = q - 1                               -- repeats of the ya block
local lastl = L - S * yn                       -- lines of the yb block
local total = L * XBY
if S * XBY >= 0x400000 or lastl * XBY >= 0x400000 then bye("bloc >= 4 Mio refuse") return end
if lastl < 1 or yn > 0xfff then bye("geometrie invalide") return end
if total > 0x00e00000 then bye("total trop grand") return end
if not live_ok() or not idle() then bye("LV inactive ou CH12 occupe") return end

poke(RESLIST, 0x61, 4)
poke(RESLIST + 4, 0x5f, 4)
poke(RESLIST + 8, 0x84, 4)
call_func_ptr(FN_RES_LOCK, RESLIST)
if not clocked() then
    call_func_ptr(FN_RES_UNLOCK, RESLIST)
    bye("CH12 non cadence")
    return
end
local saved = {}
for i, off in ipairs(CHREGS) do saved[i] = shamem_read(BASE + off) end
if call_func_ptr(FN_PK_TAKE) ~= 0 then
    call_func_ptr(FN_RES_UNLOCK, RESLIST)
    bye("PACK32 occupe")
    return
end
local s14, s74 = shamem_read(0xc0f37014), shamem_read(0xc0f37074)
call_func_ptr(FN_PK_ON, 16, 0)

for k = 0, (total + 4095) / 4096 - 1 do poke(buf + k * 4096, 0xdeadbeef, 4) end
local PHYS = bitand(buf, 0x3fffffff)
eng_out(BASE + 0x40, 0)
eng_out(BASE + 0x04, 0x40000000)
eng_out(BASE + 0x08, PHYS)
eng_out(BASE + 0x0c, bitshl(yn, 16))                       -- yn, xn = 0
eng_out(BASE + 0x14, bitor(bitshl(S - 1, 16), XBY))        -- ya, xa
eng_out(BASE + 0x10, bitor(bitshl(lastl - 1, 16), XBY))    -- yb, xb
for off = 0x18, 0x28, 4 do eng_out(BASE + off, 0) end
logf("geometry: %d blocks: yn=%d x (ya+1=%d) + (yb+1=%d) lines, xb=%d B, total %d B; 0c=%08x 10=%08x 14=%08x %s",
     q, yn, S, lastl, XBY, total, shamem_read(BASE + 0x0c), shamem_read(BASE + 0x10),
     shamem_read(BASE + 0x14), regs_str())
eng_out(XR, 0x00)
local u0 = usec()
local t0 = get_tick_count()
eng_out(BASE + 0x00, 1)
local ctl0 = peek(BASE, 4)
local smp, lastp, tmove, status, ctl = {}, -1, t0, "ok", 1
while true do
    ctl = peek(BASE, 4)
    if ctl == 0 then break end
    local p, now = peek(BASE + 8, 4), get_tick_count()
    if p ~= lastp then
        lastp, tmove = p, now
        if #smp < 40 then smp[#smp + 1] = string.format("%d:%x", udiff(u0, usec()), p - PHYS) end
    elseif now - tmove > 60 then status = "stall" break end
    if now - t0 > 1000 then status = "timeout" break end
end
local udone = udiff(u0, usec())
local endp = peek(BASE + 8, 4) - PHYS
local stall_regs = (status ~= "ok") and regs_str() or ""
local stopped, tstop = stop_dma()
call_func_ptr(FN_PK_OFF)
eng_out(0xc0f37014, s14)
eng_out(0xc0f37074, s74)
for i, off in ipairs(CHREGS) do eng_out(BASE + off, saved[i]) end
call_func_ptr(FN_RES_UNLOCK, RESLIST)
logf("ctl0=%x status=%s after %d us, end ptr +%x (%d lines); ptr(us:off) %s",
     ctl0, status, udone, endp, endp / XBY, table.concat(smp, " "))
if status ~= "ok" then logf("STALL regs %s", stall_regs) end
logf("stop=%s %d ms", tostring(stopped), tstop)
local wb = 0
for k = 0, (total + 4095) / 4096 - 1 do
    if peek(buf + k * 4096, 4) ~= 0xdeadbeef then wb = wb + 1 end
end
logf("blocks written %d/%d", wb, (total + 4095) / 4096)
local fd = call_func_ptr(FN_OPEN, "A/PKYN.BIN", 0x301, 511)
if fd >= 0 then
    call_func_ptr(FN_WRITE, fd, buf, total)
    call_func_ptr(FN_CLOSE, fd)
end
local th = get_tick_count()
while get_tick_count() - th < 1500 do
    sleep(250)
    logf("alive +%d ms dss=%08x 6804=%08x 8090=%08x", get_tick_count() - th,
         peek(0x00028738, 4), shamem_read(0xc0f06804), shamem_read(0xc0f08090))
end
if not stopped then
    logf("FATAL: channel still armed")
    log:close()
    print("DMA bloque: retirer la batterie")
    sleep(5000)
    return
end
bye(string.format("%s: %d Ko en %d us", status, wb * 4, udone))
