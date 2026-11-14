--[[
@title USB probe (live119)
@chdk_version 1.4
]]
-- Logs get_usb_power(1) and physw_status[0..2] (0x56bec) every 500 ms for 30 s to A/USBPROBE.TXT.
-- Start it WITHOUT cable, plug the USB cable at ~10 s, unplug at ~20 s.
local f = io.open("A/USBPROBE.TXT", "w")
for i = 1, 60 do
  local s = string.format("%d usb=%d p0=%08x p1=%08x p2=%08x\n", get_tick_count(), get_usb_power(1),
    peek(0x56bec), peek(0x56bec + 4), peek(0x56bec + 8))
  f:write(s) f:flush()
  print(s)
  sleep(500)
end
f:close()
