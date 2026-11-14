--[[
@title M10 HeadDirect 14bit RAW
@chdk_version 1.5
@param mode 0=LV1808 1=Scope2592
@default mode 0
]]

-- Exact Canon EOS M10 1.10d addresses
local FN_ENGDRV_OUT  = 0xfc02109d
local FN_ENGDRV_READ = 0xfc38d2b9
local FN_OPEN        = 0xfc389801
local FN_WRITE       = 0xfc3898bd
local FN_CLOSE       = 0xfc389885
local FN_EXMEM_UALLOC= 0xfc08169d
local FN_EXMEM_UFREE = 0xfc081757
local FN_STOP_EVF    = 0xfc51587f -- LiveImageTool.StopEVF_FW
local FN_START_EVF   = 0xfc5157fb -- LiveImageTool.StartEVF_FW
local FN_HEAD_ON     = 0xfc5ba89f -- EnableHeadDirectCapturePath_FW
local FN_HEAD_OFF    = 0xfc5ba8a5 -- DisableHeadDirectCapturePath_FW
local FN_MODE_25K    = 0xfc156ec7 -- ChangeImagerToLasVegasMagic_FW (2592x1108)

if type(call_func_ptr) ~= "function" then
    print("Activez Lua Native Calls !")
    sleep(3000)
    return
end

local tag = (mode == 1) and "25K" or "LV"
local log = io.open("A/M10HD_" .. tag .. ".TXT", "w")
local function logf(fmt, ...)
    log:write(string.format(fmt, ...) .. "\n")
    log:flush()
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

local EXMEM_TYPE = 5
local buf = call_func_ptr(FN_EXMEM_UALLOC, EXMEM_TYPE, 0x01000000, 0)
logf("exmem_ualloc = 0x%08x", buf)
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

for i = 0, 31 do
    poke(buf + i * 4, 0xdeadbeef, 4)
end

print("1/4 StopEVF propre...")
logf("Before StopEVF: 37014=0x%08x e558=0x%x", shamem_read(0xc0f37014), peek(0x0000e558, 4))
call_func_ptr(FN_STOP_EVF)
sleep(400)

print("2/4 EnableHeadDirect...")
call_func_ptr(FN_HEAD_ON)
logf("After HeadOn: e558=0x%x", peek(0x0000e558, 4))

local w_px, h_ln
if mode == 1 then
    print("3/4 Start 2.5K (2592x1108)...")
    local rc = call_func_ptr(FN_MODE_25K)
    logf("LasVegasMagic rc=0x%x", rc)
    w_px, h_ln = 2592, 1108
else
    print("3/4 StartEVF HeadDirect...")
    local rc = call_func_ptr(FN_START_EVF)
    logf("StartEVF rc=0x%x", rc)
    w_px, h_ln = 1808, 1190
end
sleep(500)

logf("After Start: 37014(shamem)=0x%08x 37014(mmio)=0x%08x 6804=0x%08x 6008=0x%08x 6014=0x%08x",
     shamem_read(0xc0f37014), peek(0xc0f37014, 4),
     shamem_read(0xc0f06804), shamem_read(0xc0f06008), shamem_read(0xc0f06014))

-- Also log all active EDMAC channels after HeadDirect start
for _, base in ipairs({0xc0f04000,0xc0f04100,0xc0f04200,0xc0f04300,0xc0f04400,0xc0f04500,0xc0f04600,
                       0xc0f26000,0xc0f26100,0xc0f26200,0xc0f26300,0xc0f26400,0xc0f26500,0xc0f26600,
                       0xc0f30000,0xc0f30100,0xc0f30200,0xc0f30300,0xc0f30400,0xc0f30500,0xc0f30600,
                       0xc0f58000,0xc0f58100,0xc0f58200}) do
    local a = shamem_read(base + 0x08)
    local sz = shamem_read(base + 0x10)
    if a ~= 0 or sz ~= 0 then
        logf("  EDMAC 0x%08x: ctl=0x%x flg=0x%08x addr=0x%08x xbyb=0x%08x",
             base, shamem_read(base), shamem_read(base+4), a, sz)
    end
end

-- 4. Arm CH12 (0xc0f26500) on Port 0 for 14-bit RAW frame capture
print("4/4 Capture 14-bit RAW...")
local xb = (w_px * 14) / 8
local yb = h_ln - 1
local xbyb = bitor(bitshl(yb, 16), xb)
local base = 0xc0f26500

eng_out(base + 0x04, 0x00000000) -- Port 0
eng_out(base + 0x40, 0x00000000)
eng_out(base + 0x08, bitand(buf, 0x3fffffff))
eng_out(base + 0x0c, 0x00000000)
eng_out(base + 0x10, xbyb)
eng_out(base + 0x14, xbyb)
eng_out(base + 0x18, 0)
eng_out(base + 0x1c, 0)
eng_out(base + 0x20, 0)
eng_out(base + 0x24, 0)
eng_out(base + 0x28, 0)
eng_out(base + 0x00, 1)

-- Trigger Head->RAW pulse on 0xc0f08090 bit 31
local r8090 = shamem_read(0xc0f08090)
eng_out(0xc0f08090, bitor(r8090, 0x80000000))
eng_out(0xc0f08090, r8090)

sleep(200)
local w0 = peek(buf, 4)
local w1 = peek(buf + 4, 4)
local w2 = peek(buf + 8, 4)
logf("Capture result: ctl=0x%x w0=0x%08x w1=0x%08x w2=0x%08x", peek(base, 4), w0, w1, w2)

local out_raw = "A/HDRAW_" .. tag .. ".RAW"
local written = dump_file(out_raw, buf, xb * h_ln)
logf("Saved %s (%d bytes)", out_raw, written)

call_func_ptr(FN_HEAD_OFF)
call_func_ptr(FN_EXMEM_UFREE, EXMEM_TYPE)
log:close()
print("Termine ! w0=" .. string.format("%08x", w0))
sleep(2000)
