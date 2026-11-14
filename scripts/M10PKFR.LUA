--[[
@title M10 PACK32 RAW trame v3
@chdk_version 1.5
@param c Lignes par morceau
@default c 554
@param k Nombre de morceaux
@default k 2
@param r Relance (1 reprog 2 +reset 3 +reset+xbar)
@default r 2
]]

-- Full zoom x5 frame (1107 lines x 5184 B = 5.74 MB) in k chained EDMAC
-- transfers of c lines each, every one far below the 4 MiB limit found in
-- probe32 (800 lines = 4 147 200 B ok, 810 lines = 4 199 040 B stalled at 0).
-- Path = M10PK32 v6/v7: CH12 + Canon resource lock + PACK32 16 bpp + 4-byte
-- transfers, port 0. Between two pieces the script only re-arms the channel
-- (r=0: the address register already points past the previous piece; r=1:
-- rewrite it explicitly) in a tight loop, to lose as few lines as possible.
-- Tests: does a >4 MiB total work when split? how many lines are lost at a
-- re-arm? A stall ends the session (no re-arm on a stuck head).
-- v2 (probe33): piece 1 ok (554 lines, 20 ms); re-arming with ctl=1 alone
-- finished piece 2 instantly with 0 bytes: the size counters are consumed.
-- Canon's own StartEDmac (110f 0xfc37570a) clears flag bit 29 then writes
-- ctl=1, after SetEDmac rewrote address + sizes. v2 rewrites before every
-- piece: r=1 address + 0x10/0x14 sizes, r=2 also flags/0x40/0x18-0x28.
-- ctl is sampled right after the start write.
-- v3 (probe34): even a full reprogram leaves ctl=0 right after ctl=1: the
-- channel refuses to start again after a completed transfer. In M10PKSW the
-- next attempt always started, and between attempts the script had written
-- ctl=2 (abort/reset) and cycled the crossbar. v3 re-arm modes:
--   r=1 reprogram only, r=2 ctl=2 + wait idle + reprogram (default),
--   r=3 r=2 + crossbar off/on. The time gap between pieces is logged.
-- Output: A/PKFR.TXT, A/PKFR.BIN

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

local log = io.open("A/PKFR.TXT", "w")
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

-- one attempt; returns "ok" | "stall" | "fatal" | "skip"

local function live_ok()
    return shamem_read(0xc0f06804) ~= 0 and peek(0x00028738, 4) ~= 0
end

logf("=== M10PKFR c=%d k=%d r=%d dss=%08x wh=%dx%d 6800=%08x 6804=%08x ===", c, k, r,
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
local h = bitshru(r6804, 16) - bitshru(r6800, 16)
local XBY = w * 2
if c * XBY >= 0x400000 then bye("morceau >= 4 Mio refuse") return end
if k * c * XBY > 0x00e00000 then bye("total trop grand") return end
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

local total = k * c * XBY
for q = 0, (total + 4095) / 4096 - 1 do poke(buf + q * 4096, 0xdeadbeef, 4) end
local PHYS = bitand(buf, 0x3fffffff)
local XYB = bitor(bitshl(c - 1, 16), XBY)
eng_out(BASE + 0x40, 0)
eng_out(BASE + 0x04, 0x40000000)
eng_out(BASE + 0x08, PHYS)
eng_out(BASE + 0x0c, 0)
eng_out(BASE + 0x10, XYB)
eng_out(BASE + 0x14, XYB)
for off = 0x18, 0x28, 4 do eng_out(BASE + off, 0) end
logf("piece %d lines x %d B = %d B, total %d lines (%dx%d) %s", c, XBY, c * XBY, k * c, w, h, regs_str())
eng_out(XR, 0x00)

local res = {}
local status = "ok"
local t0 = get_tick_count()
for piece = 1, k do
    local tg = get_tick_count()
    if piece > 1 and r >= 2 then
        eng_out(BASE + 0x00, 2)
        local tr = get_tick_count()
        while peek(BASE, 4) ~= 0 and get_tick_count() - tr < 50 do end
        if r == 3 then
            eng_out(XR, 0x80000000)
            eng_out(XR, 0x00)
        end
    end
    if piece > 1 then
        if r >= 2 then
            eng_out(BASE + 0x40, 0)
            eng_out(BASE + 0x04, 0x40000000)
            eng_out(BASE + 0x0c, 0)
            for off = 0x18, 0x28, 4 do eng_out(BASE + off, 0) end
        end
        eng_out(BASE + 0x08, PHYS + (piece - 1) * c * XBY)
        eng_out(BASE + 0x10, XYB)
        eng_out(BASE + 0x14, XYB)
    end
    local pstart = peek(BASE + 8, 4)
    local ts = get_tick_count()
    eng_out(BASE + 0x00, 1)
    local ctl0 = peek(BASE, 4)
    local polls, lastp, tmove = 0, -1, ts
    while true do
        polls = polls + 1
        if peek(BASE, 4) == 0 then break end
        local p, now = peek(BASE + 8, 4), get_tick_count()
        if p ~= lastp then lastp, tmove = p, now
        elseif now - tmove > 60 then status = "stall" break end
    end
    res[#res + 1] = string.format("piece %d: rearm %d ms ctl0=%x start ptr +%x at %d ms, end ptr +%x at %d ms, polls %d, %s",
        piece, ts - tg, ctl0, pstart - PHYS, ts - t0, peek(BASE + 8, 4) - PHYS, get_tick_count() - t0, polls, status)
    if status ~= "ok" then break end
end
local stall_regs = (status ~= "ok") and regs_str() or ""
local stopped, tstop = stop_dma()
call_func_ptr(FN_PK_OFF)
eng_out(0xc0f37014, s14)
eng_out(0xc0f37074, s74)
for i, off in ipairs(CHREGS) do eng_out(BASE + off, saved[i]) end
call_func_ptr(FN_RES_UNLOCK, RESLIST)
for _, l in ipairs(res) do logf("%s", l) end
if status ~= "ok" then logf("STALL regs %s", stall_regs) end
logf("stop=%s %d ms", tostring(stopped), tstop)

local wb = 0
for q = 0, (total + 4095) / 4096 - 1 do
    if peek(buf + q * 4096, 4) ~= 0xdeadbeef then wb = wb + 1 end
end
logf("blocks written %d/%d", wb, (total + 4095) / 4096)
local fd = call_func_ptr(FN_OPEN, "A/PKFR.BIN", 0x301, 511)
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
bye(string.format("%s: %d Ko, %d morceau(x)", status, wb * 4, #res))
