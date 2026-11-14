--[[
@title M10 PACK32 RAW v7
@chdk_version 1.5
@param b Bits par pixel (10/12/14/16)
@default b 16
@param t Type RAW force (0=Canon, 16=HEAD)
@default t 0
@param m Taille capture (Mo)
@default m 2
@param x Transfert DMA (0=2 octets 1=4 octets)
@default x 1
@param l Verrou ressources (0=auto 1=toujours)
@default l 0
@param c Canal (12=CH12)
@default c 12
]]

-- v7 (probe28): 4 bytes + CH12 + lock, 1 MB = 202 Bayer lines in 10 ms,
-- camera fine. Now 2 MB by default (404 lines) to find where the stream
-- freezes; on a stall the PACK32/head registers are logged before the stop.
-- v6 (probe27): CH8 is NOT free in zoom x5: it is Canon's own LV channel
-- (addr 0x17f38000), it only looks idle between two frames. v5 took it
-- (racy idle test), wrote nothing and was lucky. v6: CH12 only, and a
-- channel is "idle" only if it stays idle for 20 samples over ~100 ms.
-- v5 (probe26): 2-byte transfers are useless (only the RG sensor lines,
-- de-interleaved G|R halves, blue dropped: this was also the "no blue in LV"
-- artefact). 4-byte transfers give the real RGGB Bayer but a transfer still
-- armed at the end of a frame froze the sensor stream and the camera shut
-- down. Default is now 4 bytes and 1 MB (~200 zoom lines): the DMA ends
-- inside the current frame and is never left waiting.
-- v5: after the teardown the log keeps writing a heartbeat for 3 s
-- (DSS flags, LV regs) so a later shutdown can be located in time.
-- v4 (2026-11-07): v2/v3 (resource lock + 4-byte transfers) froze the DMA
-- after ~30 ms and the camera shut down; v1 (no lock, 2 bytes) never did.
-- Defaults are back to v1: 2-byte transfers, no lock when the channel is
-- already clocked. Auto channel: CH12 if clocked (LV), else CH8 if clocked
-- (Canon powers CH8 in zoom x5), else CH12 + resource lock. The borrowed
-- channel registers are restored at the end. A stalled DMA is aborted after
-- 100 ms without progress.

-- ROM 110d (2026-11-07): CaptureSystem.c builds Canon's own RAW path like this
--   0xfc22f738  take PACK32 semaphore (#6)
--   0xfc22f73e(bpp, pack) : raw type 0x12 (0x22 in head-direct mode) into
--                c0f37014[5:0], PACK32 config via 0xfc34d5b6 (bpp -> c0f08094),
--                then enable c0f08090 = 1
--   ConnectWriteEDmac(12, port 0)   (0xfc376022(0xc, 0))
--   0xfc22f7dc  disable PACK32 (c0f08090 = 0x80000000) + give semaphore
-- Earlier port-0 scans were mute because PACK32 was never enabled.
-- This script does the same in normal LiveView (CH12 is clocked there),
-- grabs m MB from port 0, restores everything.
-- Output: A/PK<bb><tt>.TXT + A/PK<bb><tt>.BIN (ex. PK1600 = 16 bits, type Canon)

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
-- Pwrcnt.c resource lock/unlock, exactly as CaptureSystem.c does for CH12/CH10:
-- list of resource ids (table 0xfc6dd8e4: CH12 -> 0x61, CH10 -> 0x5f), 0x84-terminated
local FN_RES_LOCK    = 0xfc373f9f
local FN_RES_UNLOCK  = 0xfc375589

if type(call_func_ptr) ~= "function" then
    print("Activez Lua Native Calls !")
    sleep(3000)
    return
end

local ZOOM = (peek(0x001beb5c, 4) ~= 1728)
local TAG = string.format("%02d%02d", b, t) .. (ZOOM and "Z" or "")
local log = io.open("A/PK" .. TAG .. ".TXT", "w")
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

local REGS = {0xc0f37014, 0xc0f37040, 0xc0f37074, 0xc0f370d4,
              0xc0f08090, 0xc0f08094, 0xc0f08264, 0xc0f08268, 0xc0f082bc, 0xc0f08bf0}
local function log_regs(tag)
    local s = {}
    for _, r in ipairs(REGS) do
        s[#s + 1] = string.format("%x=%08x", r, shamem_read(r))
    end
    logf("REGS %s %s", tag, table.concat(s, " "))
end

local sem_taken, pk_on, res_locked = false, false, false
local RESLIST = scratch + 0x100
local saved37014, saved37074 = nil, nil
local CH, BASE = 12, 0xc0f26500
local XR = 0xc0f051e0 + CH * 4
local CHREGS = {0x04, 0x08, 0x0c, 0x10, 0x14, 0x18, 0x1c, 0x20, 0x24, 0x28, 0x40}
local chsaved = nil
local function select_channel(n)
    CH = n
    BASE = 0xc0f26000 + (n - 7) * 0x100       -- write idx 7..13
    XR = 0xc0f051e0 + n * 4                   -- ch >= 8
end
local function clocked()
    local old8 = shamem_read(BASE + 0x08)
    eng_out(BASE + 0x08, bitand(buf, 0x3fffffff))
    local rb = peek(BASE + 0x08, 4)
    eng_out(BASE + 0x08, old8)
    return rb == bitand(buf, 0x3fffffff), rb
end
local function idle()
    for k = 1, 20 do
        if shamem_read(XR) ~= 0x80000000 or peek(BASE, 4) ~= 0 then return false end
        sleep(5)
    end
    return true
end

-- stop the channel and wait until it is really idle (direct peek, not the shadow)
local function stop_dma()
    local t1 = get_tick_count()
    eng_out(BASE + 0x00, 2)                 -- abort
    while peek(BASE, 4) ~= 0 and get_tick_count() - t1 < 300 do
        sleep(10)
        eng_out(BASE + 0x00, 2)
    end
    local ctl = peek(BASE, 4)
    if shamem_read(XR) ~= 0x80000000 then eng_out(XR, 0x80000000) end
    sleep(50)                               -- let PACK32 drain into nothing
    logf("stop CH%d: ctl=%x after %d ms", CH, ctl, get_tick_count() - t1)
    return ctl == 0
end

local dma_owned = false
local function finish(msg)
    if dma_owned then stop_dma() end
    if sem_taken then
        call_func_ptr(FN_PK_OFF)            -- disable PACK32 + give semaphore
        logf("PACK32 off, semaphore given")
    end
    if saved37014 ~= nil then
        eng_out(0xc0f37014, saved37014)
        eng_out(0xc0f37074, saved37074)
        logf("c0f37014/37074 restored to %08x/%08x", saved37014, saved37074)
    end
    if chsaved ~= nil then
        for i, off in ipairs(CHREGS) do eng_out(BASE + off, chsaved[i]) end
        logf("CH%d registers restored (flags=%08x addr=%08x)", CH, chsaved[1], chsaved[2])
    end
    if res_locked then
        call_func_ptr(FN_RES_UNLOCK, RESLIST)
        logf("resources CH12/CH10 unlocked")
    end
    log_regs("end")
    call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
    logf("EXMEM freed")
    local th = get_tick_count()
    for k = 1, 15 do
        sleep(200)
        logf("alive +%d ms dss=%08x wh=%dx%d 6804=%08x c0f08090=%08x",
             get_tick_count() - th, peek(0x00028738, 4), peek(0x001beb5c, 4),
             peek(0x001beb60, 4), shamem_read(0xc0f06804), shamem_read(0xc0f08090))
    end
    log:close()
    print(msg)
    sleep(2500)
end

local dssw = peek(0x001beb5c, 4)
logf("=== M10PK32 b=%d t=%d m=%d x=%d zoom=%s buf=0x%08x dss_flags=0x%08x dss_wh=%dx%d e558=%d e55c=%d ===",
     b, t, m, x, tostring(ZOOM), buf, peek(0x00028738, 4), dssw, peek(0x001beb60, 4),
     peek(0x0000e558, 4), peek(0x0000e55c, 4))
if shamem_read(0xc0f06804) == 0 or peek(0x00028738, 4) == 0 then
    logf("ABORT: LiveView inactive")
    finish("LiveView inactif: passer en mode prise de vue")
    return
end
local r6800, r6804 = shamem_read(0xc0f06800), shamem_read(0xc0f06804)
local w = (bitand(r6804, 0xffff) - bitand(r6800, 0xffff)) * 4
local h = bitshru(r6804, 16) - bitshru(r6800, 16)
logf("6800=0x%08x 6804=0x%08x -> readout %dx%d, %d bytes/line at %d bpp",
     r6800, r6804, w, h, w * b / 8, b)
log_regs("before")

-- pick an idle, already clocked channel (no resource lock if possible)
local picked = false
if c ~= 12 then
    finish("Seul CH12 est autorise (c=12)")
    return
end
local cands = {12}
for _, n in ipairs(cands) do
    select_channel(n)
    local isidle = idle()
    local ok, rb = clocked()
    logf("CH%d idle=%s readback=%08x %s", n, tostring(isidle), rb, ok and "CLOCKED" or "DEAD")
    if isidle and ok and l == 0 then
        picked = true
        break
    end
end
if not picked then
    select_channel((c ~= 0) and c or 12)
    if not idle() then
        logf("CH%d busy xbar=%08x ctl=%x", CH, shamem_read(XR), peek(BASE, 4))
        finish("Canal occupe par Canon")
        return
    end
    if CH ~= 12 then
        finish("Canal eteint")
        return
    end
    -- power/clock CH12 (and CH10) through Canon's resource manager, like CaptureSystem
    poke(RESLIST, 0x61, 4)
    poke(RESLIST + 4, 0x5f, 4)
    poke(RESLIST + 8, 0x84, 4)
    call_func_ptr(FN_RES_LOCK, RESLIST)
    res_locked = true
    local ok, rb = clocked()
    logf("resources CH12/CH10 locked (0x61,0x5f), readback=%08x %s", rb, ok and "CLOCKED" or "DEAD")
    if not ok then
        finish("CH12 reste eteint malgre le verrou")
        return
    end
end
logf("using CH%d base=%08x xbar=%08x lock=%s", CH, BASE, XR, tostring(res_locked))
dma_owned = true            -- from here the channel registers are ours
chsaved = {}
for i, off in ipairs(CHREGS) do chsaved[i] = shamem_read(BASE + off) end

-- 1. take PACK32 like Canon does
local r = call_func_ptr(FN_PK_TAKE)
logf("take PACK32 semaphore -> %d", r)
if r ~= 0 then
    finish("PACK32 deja utilise par Canon")
    return
end
sem_taken = true

-- 2. enable PACK32 (raw type + bit depth + enable)
saved37014 = shamem_read(0xc0f37014)
saved37074 = shamem_read(0xc0f37074)
call_func_ptr(FN_PK_ON, b, 0)
pk_on = true
if t ~= 0 then
    eng_out(0xc0f37014, bitor(bitand(shamem_read(0xc0f37014), 0xffffffc0), bitand(t, 0x3f)))
end
log_regs("pack32_on")

-- 3. grab m MB from port 0 with CH12 (2 bytes/transfer, 4096 x N)
local SIZE = m * 0x100000
if SIZE > 0x00e00000 then SIZE = 0x00e00000 end
-- v3: line geometry, at most one sensor frame (v2 asked 8 MB > one 5.7 MB
-- zoom frame and the channel never finished)
local XBY = w * b / 8
local NL = SIZE / XBY
if NL > h then NL = h end
local YB = NL - 1
logf("transfer %d lines x %d bytes = %d bytes", NL, XBY, NL * XBY)
for k = 0, (SIZE / 4096) - 1 do
    poke(buf + k * 4096, 0xdeadbeef, 4)
end
eng_out(BASE + 0x40, 0)
eng_out(BASE + 0x04, (x == 1) and 0x40000000 or 0x20000000)   -- Canon uses 4 bytes
eng_out(BASE + 0x08, bitand(buf, 0x3fffffff))
eng_out(BASE + 0x0c, 0)
eng_out(BASE + 0x10, bitor(bitshl(YB, 16), XBY))
eng_out(BASE + 0x14, bitor(bitshl(YB, 16), XBY))
for off = 0x18, 0x28, 4 do
    eng_out(BASE + off, 0)
end
dma_owned = true
eng_out(XR, 0x00)                  -- port 0 = sensor head through PACK32
local t0 = get_tick_count()
eng_out(BASE + 0x00, 1)
local samples = {}
local ctl = 1
local lastp, tmove = -1, t0
while ctl ~= 0 and get_tick_count() - t0 < 1000 do
    sleep(5)
    ctl = peek(BASE, 4)
    local p = peek(BASE + 8, 4)
    local now = get_tick_count()
    if p ~= lastp then
        lastp, tmove = p, now
    elseif now - tmove > 100 and now - t0 > 150 then
        break                                    -- stalled: do not wait 1 s armed
    end
    if #samples < 60 then
        samples[#samples + 1] = string.format("%d:%08x", now - t0, p)
    end
end
logf("DMA ctl=%x after %d ms; ptr %s", ctl, get_tick_count() - t0, table.concat(samples, " "))
if ctl ~= 0 then
    log_regs("stall")
    logf("stall 6800=%08x 6804=%08x ptr=%08x xbyb=%08x", shamem_read(0xc0f06800),
         shamem_read(0xc0f06804), peek(BASE + 8, 4), peek(BASE + 0x10, 4))
end
-- v3 safe teardown: the channel must be really idle before PACK32 and the
-- resources go back to Canon (v2 released them with ctl=1 -> camera error).
if not stop_dma() then
    logf("ABORT: channel still armed, PACK32/resources kept (battery pull needed)")
    print("DMA bloque: retirer la batterie")
    log:close()
    sleep(5000)
    return
end

local written, last = 0, -1
for k = 0, (SIZE / 4096) - 1 do
    if peek(buf + k * 4096, 4) ~= 0xdeadbeef then
        written = written + 1
        last = k
    end
end
logf("4KB blocks written=%d last=%d of %d; w0=%08x w1=%08x w2=%08x w3=%08x",
     written, last, SIZE / 4096, peek(buf, 4), peek(buf + 4, 4), peek(buf + 8, 4), peek(buf + 12, 4))

local fd = call_func_ptr(FN_OPEN, "A/PK" .. TAG .. ".BIN", 0x301, 511)
if fd >= 0 then
    local wr = call_func_ptr(FN_WRITE, fd, buf, NL * XBY)
    call_func_ptr(FN_CLOSE, fd)
    logf("Saved A/PK%s.BIN (%d bytes)", TAG, wr)
end

finish(string.format("OK: %d Ko ecrits", written * 4))
