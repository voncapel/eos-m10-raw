--[[
@title M10 RAW & EDMAC Probe
@chdk_version 1.5
@param d Dump Active Buffers (0/1)
@default d 1
@param m Test 2.5K Mode (0/1)
@default m 0
]]

-- Exact Canon EOS M10 1.10d firmware function addresses (Thumb bit = 1)
local FN_ENGDRV_READ = 0xfc38d2b9
local FN_OPEN        = 0xfc389801
local FN_WRITE       = 0xfc3898bd
local FN_CLOSE       = 0xfc389885
local FN_MODE_25K    = 0xfc156ec7 -- ChangeImagerToLasVegasMagic_FW (Spec 36: 2592x1108)

if type(call_func_ptr) ~= "function" then
    print("ERREUR: Activez Lua Native Calls")
    print("Menu -> Misc -> Enable Lua Native")
    sleep(4000)
    return
end

local function shamem_read(reg)
    return call_func_ptr(FN_ENGDRV_READ, reg)
end

local function dump_ram_to_file(path, addr, size)
    -- O_WRONLY | O_CREAT | O_TRUNC = 0x301, mode = 0777 (511)
    local fd = call_func_ptr(FN_OPEN, path, 0x301, 511)
    if fd < 0 then
        return -1
    end
    -- Uncached alias on M10 is 0x40000000 (already set on 0x4xxxxxxx buffers)
    local written = call_func_ptr(FN_WRITE, fd, addr, size)
    call_func_ptr(FN_CLOSE, fd)
    return written
end

local write_channels = {
    {0,  0xc0f04000}, {1,  0xc0f04100}, {2,  0xc0f04200}, {3,  0xc0f04300},
    {4,  0xc0f04400}, {5,  0xc0f04500}, {6,  0xc0f04600},
    {7,  0xc0f26000}, {8,  0xc0f26100}, {9,  0xc0f26200}, {10, 0xc0f26300},
    {11, 0xc0f26400}, {12, 0xc0f26500}, {13, 0xc0f26600},
    {14, 0xc0f30000}, {15, 0xc0f30100}, {16, 0xc0f30200}, {17, 0xc0f30300},
    {18, 0xc0f30400}, {19, 0xc0f30500}, {20, 0xc0f30600},
    {22, 0xc0f58000}, {23, 0xc0f58100}, {24, 0xc0f58200}
}

local log = io.open("A/M10PROBE.TXT", "w")
local function logf(fmt, ...)
    local s = string.format(fmt, ...)
    log:write(s .. "\n")
end

local function scan_edmac(tag, do_dump)
    logf("=== SCAN: %s (tick=%d) ===", tag, get_tick_count())
    local misc_regs = {
        0xc0f06008, 0xc0f0600c, 0xc0f06014,
        0xc0f06800, 0xc0f06804, 0xc0f37014,
        0xc0f58e80, 0xc0f58e90, 0xc0f58e94
    }
    for _, r in ipairs(misc_regs) do
        logf("  REG 0x%08x = 0x%08x", r, shamem_read(r))
    end

    local active_count = 0
    for _, entry in ipairs(write_channels) do
        local ch = entry[1]
        local base = entry[2]
        local r00 = shamem_read(base + 0x00)
        local r04 = shamem_read(base + 0x04)
        local addr = shamem_read(base + 0x08)
        local r0c = shamem_read(base + 0x0c)
        local r10 = shamem_read(base + 0x10)
        local off1a = shamem_read(base + 0x14)
        local off1b = shamem_read(base + 0x18)
        local off2a = shamem_read(base + 0x1c)

        if addr ~= 0 or r10 ~= 0 or r00 ~= 0 then
            local xb = bitand(r10, 0xffff)
            local yb = bitshru(r10, 16)
            local xn = bitand(r0c, 0xffff)
            local yn = bitshru(r0c, 16)
            logf(
                "  CH%02d @0x%08x: ctl=0x%x flg=0x%08x addr=0x%08x xnyn=%dx%d xbyb=%dx%d off=(0x%x,0x%x,0x%x)",
                ch, base, r00, r04, addr, xn, yn, xb, yb, off1a, off1b, off2a
            )
            active_count = active_count + 1

            -- Dump candidate frame buffers in 0x01000000..0x1fffffff or 0x40000000..0x5fffffff
            local is_ram = (addr >= 0x01000000 and addr < 0x20000000) or (addr >= 0x40000000 and addr < 0x60000000)
            if do_dump == 1 and is_ram and xb > 0 then
                local h = yb
                if h == 0 then h = yn end
                if h == 0 then h = 1200 end
                local dump_sz = (xb + 0) * (h + 1)
                if dump_sz < 524288 then dump_sz = 2097152 end
                if dump_sz > 8388608 then dump_sz = 8388608 end
                local fname = string.format("A/CH%02d_%s.RAW", ch, tag)
                local w = dump_ram_to_file(fname, addr, dump_sz)
                logf("    -> DUMPED %s (%d bytes)", fname, w)
            end
        end
    end
    print(string.format("%s: %d ch actifs", tag, active_count))
end

print("Sonde EDMAC LiveView...")
sleep(300)
scan_edmac("LV", d)

if m == 1 then
    print("Switch capteur 2.5K (Spec 36)...")
    local rc = call_func_ptr(FN_MODE_25K)
    logf("ChangeImagerToLasVegasMagic_FW rc=0x%x", rc)
    sleep(600)
    scan_edmac("M25K", d)
end

log:close()
print("Termine ! Voir M10PROBE.TXT")
sleep(2000)
