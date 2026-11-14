--[[
@title M10 PACK32 RAW sweep v3
@chdk_version 1.5
@param a Lignes depart (x10)
@default a 80
@param d Pas (x10 lignes)
@default d 1
@param n Nombre d'essais
@default n 8
@param s Synchro trame (0 non 1 oui)
@default s 0
@param p Pause entre essais (ms)
@default p 600
]]

-- Size sweep of the validated PACK32 RAW path (M10PK32 v6/v7, probe28-29):
-- CH12 + Canon resource lock {0x61,0x5f,0x84} + 4-byte transfers, port 0.
-- One full setup/teardown per attempt, sizes a..z MB (zoom x5: 5184 B/line,
-- capped to one frame = 1107 lines). Each attempt line is flushed to the log
-- BEFORE the DMA starts, so after a shutdown the last line tells which size
-- killed the camera. The sweep stops at the first stalled transfer.
-- v3 (probe31): after ONE stall the head never restarts: every later
-- attempt wrote 0 lines and the 6th killed the camera. A stall must end
-- the run at once. v3 sweeps line counts (a*10, +d*10 ...) from 820 up and
-- stops at the first stall, then leaves PACK32 alone.
-- Hypothesis under test: 809 lines x 5184 B = 4 193 856 B < 4 MiB passed,
-- 1011 lines failed -> a 4 MiB (0x400000) limit per EDMAC transfer?
-- Default ladder 800, 810, 820 ... 870 lines: 810 lines is the first size
-- above 4 MiB. The CH8 "frame edge" proxy never fired (edge_wait=200 ms).
-- v2 (probe30: 3-4 MB ok, 5 MB stalled at line 424 after 20 ms, recovered
-- cleanly, no shutdown): n repeats of the same size, optionally started on
-- a frame edge. Frame-edge proxy = rising edge of Canon's own LV channel
-- CH8 (0xc0f26100 ctl 0->1), read-only. Logs the stall line each time to
-- tell a fixed-position stall (sensor/PACK32 timing) from a random one
-- (bus contention). Output: A/PKSW.TXT, A/PKSW<k>.BIN (k = attempt).

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

local log = io.open("A/PKSW.TXT", "w")
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
local function wait_edge()
    local C8, t1 = 0xc0f26100, get_tick_count()
    while peek(C8, 4) ~= 0 and get_tick_count() - t1 < 100 do end
    while peek(C8, 4) == 0 and get_tick_count() - t1 < 200 do end
    return get_tick_count() - t1
end

local function attempt(mb, k, sync)
    local r6800, r6804 = shamem_read(0xc0f06800), shamem_read(0xc0f06804)
    local w = (bitand(r6804, 0xffff) - bitand(r6800, 0xffff)) * 4
    local h = bitshru(r6804, 16) - bitshru(r6800, 16)
    local XBY = w * 2
    local NL = mb
    if NL > h then NL = h end
    if not live_ok() or not idle() then
        logf("[%d MB] skip: LV off or CH12 busy", mb)
        return "skip"
    end
    poke(RESLIST, 0x61, 4)
    poke(RESLIST + 4, 0x5f, 4)
    poke(RESLIST + 8, 0x84, 4)
    call_func_ptr(FN_RES_LOCK, RESLIST)
    if not clocked() then
        call_func_ptr(FN_RES_UNLOCK, RESLIST)
        logf("[%d MB] skip: CH12 not clocked", mb)
        return "skip"
    end
    local saved = {}
    for i, off in ipairs(CHREGS) do saved[i] = shamem_read(BASE + off) end
    if call_func_ptr(FN_PK_TAKE) ~= 0 then
        call_func_ptr(FN_RES_UNLOCK, RESLIST)
        logf("[%d MB] skip: PACK32 busy", mb)
        return "skip"
    end
    local s14, s74 = shamem_read(0xc0f37014), shamem_read(0xc0f37074)
    call_func_ptr(FN_PK_ON, 16, 0)
    local size = NL * XBY
    for k = 0, (size + 4095) / 4096 - 1 do poke(buf + k * 4096, 0xdeadbeef, 4) end
    eng_out(BASE + 0x40, 0)
    eng_out(BASE + 0x04, 0x40000000)
    eng_out(BASE + 0x08, bitand(buf, 0x3fffffff))
    eng_out(BASE + 0x0c, 0)
    eng_out(BASE + 0x10, bitor(bitshl(NL - 1, 16), XBY))
    eng_out(BASE + 0x14, bitor(bitshl(NL - 1, 16), XBY))
    for off = 0x18, 0x28, 4 do eng_out(BASE + off, 0) end
    logf("[#%d %d L] START sync=%d %d lines x %d B (%dx%d) %s", k, mb, sync, NL, XBY, w, h, regs_str())
    local tw = sync == 1 and wait_edge() or -1
    eng_out(XR, 0x00)
    local t0 = get_tick_count()
    eng_out(BASE + 0x00, 1)
    local ctl, lastp, tmove, smp = 1, -1, t0, {}
    while ctl ~= 0 and get_tick_count() - t0 < 1000 do
        sleep(5)
        ctl = peek(BASE, 4)
        local p, now = peek(BASE + 8, 4), get_tick_count()
        if p ~= lastp then lastp, tmove = p, now
        elseif now - tmove > 60 then break end
        if #smp < 30 then smp[#smp + 1] = string.format("%d:%x", now - t0, p - bitand(buf, 0x3fffffff)) end
    end
    local dt = get_tick_count() - t0
    local stall_regs = (ctl ~= 0) and regs_str() or ""
    local stopped, tstop = stop_dma()
    call_func_ptr(FN_PK_OFF)
    eng_out(0xc0f37014, s14)
    eng_out(0xc0f37074, s74)
    for i, off in ipairs(CHREGS) do eng_out(BASE + off, saved[i]) end
    call_func_ptr(FN_RES_UNLOCK, RESLIST)
    local wb = 0
    for k = 0, (size + 4095) / 4096 - 1 do
        if peek(buf + k * 4096, 4) ~= 0xdeadbeef then wb = wb + 1 end
    end
    local done = (lastp - bitand(buf, 0x3fffffff)) / XBY
    logf("[#%d %d L] END sync=%d edge_wait=%d ms ctl=%x %d ms, lines %d/%d, blocks %d/%d, stop=%s %d ms; ptr %s",
         k, mb, sync, tw, ctl, dt, done, NL, wb, (size + 4095) / 4096, tostring(stopped), tstop, table.concat(smp, " "))
    if ctl ~= 0 then logf("[#%d] STALL regs %s", k, stall_regs) end
    local fd = call_func_ptr(FN_OPEN, string.format("A/PKSW%d.BIN", k), 0x301, 511)
    if fd >= 0 then
        call_func_ptr(FN_WRITE, fd, buf, size)
        call_func_ptr(FN_CLOSE, fd)
    end
    if not stopped then return "fatal" end
    return (ctl == 0) and "ok" or "stall"
end

logf("=== M10PKSW3 a=%d d=%d n=%d s=%d p=%d dss=%08x wh=%dx%d 6800=%08x 6804=%08x ===", a, d, n, s, p,
     peek(0x00028738, 4), peek(0x001beb5c, 4), peek(0x001beb60, 4),
     shamem_read(0xc0f06800), shamem_read(0xc0f06804))
local best, verdict = 0, ""
for k = 1, n do
    local lines = (a + (k - 1) * d) * 10
    local r = attempt(lines, k, s)
    local th = get_tick_count()
    while get_tick_count() - th < p do
        sleep(200)
        logf("[#%d] alive +%d ms dss=%08x 6804=%08x 8090=%08x", k, get_tick_count() - th,
             peek(0x00028738, 4), shamem_read(0xc0f06804), shamem_read(0xc0f08090))
    end
    if r == "fatal" then
        logf("FATAL at attempt %d", k)
        log:close()
        print("DMA bloque: retirer la batterie")
        sleep(5000)
        return
    end
    if r ~= "ok" then
        verdict = string.format("max %d lignes, bloque a %d (%s)", best, lines, r)
        break
    end
    best = lines
    verdict = string.format("OK jusqu'a %d lignes", best)
end
logf("verdict: %s", verdict)
call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
log:close()
print(verdict)
sleep(3000)
