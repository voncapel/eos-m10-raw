--[[
@title M10 Canon DMA Spy
@chdk_version 1.5
@param m Taille dump par canal (Ko)
@default m 2048
]]

-- probe19 (M10PZ5C): in Zoom x5 even CH8 reads back DEAD, though M10PWR saw it
-- CLOCKED 10 min earlier: Canon only clocks a channel while it transfers.
-- So we stop starting our own DMA and spy on Canon's own channels instead.
-- READ-ONLY: no EngDrvOut, no DMA start, no crossbar change.
--   1. for all 25 write channels of ROM table 0xfc6d87b8 (idx 0..24):
--      shadow flags/addr/size and crossbar port,
--   2. fast sampling (direct ctl + current pointer) to see which ones run,
--   3. dump m KB of RAM at every distinct Canon buffer address.
-- Output: A/SPY_<dss width>.TXT + A/S<dss>_<idx>.BIN

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

local dssw = peek(0x001beb5c, 4)
local tag = tostring(dssw)
local log = io.open("A/SPY_" .. tag .. ".TXT", "w")
local function logf(fmt, ...)
    log:write(string.format(fmt, ...) .. "\n")
    log:flush()
end
local function finish(msg)
    log:close()
    print(msg)
    sleep(2500)
end

logf("=== M10WSAMP %s dss_flags=0x%08x dss_wh=%dx%d ===",
     tag, peek(0x00028738, 4), dssw, peek(0x001beb60, 4))
if shamem_read(0xc0f06804) == 0 or peek(0x00028738, 4) == 0 then
    logf("ABORT: LiveView inactive")
    finish("LiveView inactif: passer en mode prise de vue")
    return
end
logf("6800=0x%08x 6804=0x%08x 6008=0x%08x 6014=0x%08x",
     shamem_read(0xc0f06800), shamem_read(0xc0f06804),
     shamem_read(0xc0f06008), shamem_read(0xc0f06014))

-- write channels idx 0..24 from the ROM table (12 bytes per entry: irq, base, cbr)
local CH = {}
for i = 0, 24 do
    CH[i] = peek(0xfc6d87b8 + i * 12 + 4, 4)
end
local function xbar_reg(i)
    if i < 8 then return 0xc0f05000 + i * 4 end
    return 0xc0f051e0 + i * 4
end

-- 1. static shadow state
for i = 0, 24 do
    local b = CH[i]
    local xr = (i <= 20) and shamem_read(xbar_reg(i)) or -1
    logf("CH%02d base=%08x xbar=%08x flags=%08x addr=%08x xn=%08x s10=%08x s14=%08x o18=%08x o1c=%08x o20=%08x o24=%08x o28=%08x",
         i, b, xr, shamem_read(b + 4), shamem_read(b + 8), shamem_read(b + 0x0c),
         shamem_read(b + 0x10), shamem_read(b + 0x14), shamem_read(b + 0x18),
         shamem_read(b + 0x1c), shamem_read(b + 0x20), shamem_read(b + 0x24),
         shamem_read(b + 0x28))
end

-- 2. fast sampling: direct ctl and pointer, shadow addr (Canon reprograms each frame)
local runs, ptrmin, ptrmax, addrs = {}, {}, {}, {}
for i = 0, 24 do
    runs[i] = 0
    ptrmin[i] = 0xffffffff
    ptrmax[i] = 0
    addrs[i] = {}
end
local t0 = get_tick_count()
local N = 300
for n = 1, N do
    for i = 0, 24 do
        local b = CH[i]
        -- direct MMIO read only on the main EDMAC blocks (idx 0..20), as Canon does
        local ctl = (i <= 20) and peek(b, 4) or 0
        if ctl ~= 0 then
            runs[i] = runs[i] + 1
            local p = peek(b + 8, 4)
            if p ~= 0 then
                if p < ptrmin[i] then ptrmin[i] = p end
                if p > ptrmax[i] then ptrmax[i] = p end
            end
        end
        local a = shamem_read(b + 8)
        if a ~= 0 then addrs[i][a] = true end
    end
end
logf("sampling: %d rounds in %d ms", N, get_tick_count() - t0)
for i = 0, 24 do
    local al = {}
    for a, _ in pairs(addrs[i]) do al[#al + 1] = string.format("%08x", a) end
    table.sort(al)
    logf("RUN CH%02d active=%d/%d ptr=[%08x..%08x] addrs=%s", i, runs[i], N,
         (ptrmin[i] == 0xffffffff) and 0 or ptrmin[i], ptrmax[i], table.concat(al, ","))
end

-- 3. dump m KB at every distinct buffer address (RAM read only)
local size = m * 1024
local done = {}
local nf = 0
for i = 0, 24 do
    for a, _ in pairs(addrs[i]) do
        local key = bitand(a, 0xfff00000)
        if not done[key] and a >= 0x00100000 and a < 0x40000000 and nf < 12 then
            done[key] = true
            nf = nf + 1
            local name = string.format("A/S%s_%02d.BIN", tag, i)
            local fd = call_func_ptr(FN_OPEN, name, 0x301, 511)
            if fd >= 0 then
                -- uncached view of the buffer (same convention as EXMEM 0x5c758000)
                local w = call_func_ptr(FN_WRITE, fd, bitor(a, 0x40000000), size)
                call_func_ptr(FN_CLOSE, fd)
                logf("DUMP CH%02d addr=%08x -> %s (%d bytes)", i, a, name, w)
            end
            break
        end
    end
end

finish("OK " .. tag .. ", " .. nf .. " dumps")
