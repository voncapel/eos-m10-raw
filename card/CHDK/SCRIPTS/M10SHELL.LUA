--[[
@title M10 Cine shell unifie (v183)
@chdk_version 1.4
]]
-- v183 : requete IPC 5 = do_af (AF Canon Hybrid CMOS AF II, one-shot, petite plongee en Photo M) :
--   le C fait sh_m1_restore_tables() + sh_expo_off() avant SH_IPC_AF = 5, puis sh_m1_enter() apres.
--   do_af : m1_off (ImgSens 3 + MV_START -> PDAF + contraste actifs), shoot_half, attente get_shooting()
--   (<= 1,8 s), get_focus_ok(), release. Accuse v182 inchange : af_ok dans le bit 9 (ok) de +0x224.
--   Toujours 0 acces FS dans la boucle principale.
-- Autostart script (CHDK: Script > Autostart = Always, file A/CHDK/SCRIPTS/M10SHELL.LUA).
-- Lance m10cine.flt (v182) en mode shell autonome (A/M10SH.CFG present). Le module rend la main tout
-- de suite et tourne dans ses propres taches (touches gardees par son gui_handler).
--
-- v182 (work/v182_audit_spec.md C.2-C.4) :
--  * demarrage sur dans n'importe quel mode : USB -> rien ; Lecture -> set_record(true) ;
--    boucle d'attente (sans error()) jusqu'a Photo M (ImgSens 3, tg 3 stables 750 ms),
--    SET = continuer quand meme (Film 1x3), MENU = quitter ;
--  * IPC en RAM dans l'en-tete siohook6 (aucun io.open / os.stat pendant la boucle normale) :
--      hook+0x220 = requete (C -> Lua) : 1 m1_on, 2 m1_off, 3 rec, 4 play, 5 do_af (v183), 0xE0 fin du shell
--      hook+0x224 = accuse  (Lua -> C) : code | 0x100 | ok<<9 | (ImgSens&0xff)<<16 | (tg&0xff)<<24
--    Le Lua remet +0x220 a 0 PUIS ecrit +0x224 (dernier store). Le C doit mettre +0x224 = 0 avant
--    d'ecrire une nouvelle requete et attendre (ack & 0x1ff) == (code | 0x100).
--  * les ChangeMode (ImgMode 1 <-> 3) restent cote Lua : depuis la tache du module ils eteignent
--    le boitier (v178b). Les kicks WBInteg sont faits par le chien de garde C (M10WB), plus ici.
--  * A/M10USB.OK present = essais bureau cable branche (l'USB n'arrete ni n'empeche le shell).

-- ===== adresses 1.10d (identiques a M10M1.LUA / scripts PTP) =====
local MODULE_RUN  = 0x3e8c71        -- CHDK core module_run(char *name), Thumb
local FN_MALLOC   = 0xfc38d3f1
local STOP_MODE   = 0xfc1efc0d
local CHG_MODE    = 0xfc1efb33
local NOOP_CB     = 0xfc1edecf
local MV_STOP     = 0xfc0dc01d      -- MotionVector_Stop : libere l'EDMAC 0x23 pour l'encodeur
local MV_START    = 0xfc0dbfc9
local AF_STOP     = 0xfc0fa287      -- StopContinuousAF/MovieAF (1.10d, si [0x85b8] == 7 ou 8 -> evite ASSERT ContinuousAF.c:1354 a +10 s)
local AF_STATE    = 0x85b8          -- [0x8594+0x24] : 7 = ContinuousAF, 8 = MovieAF
local CDS_WRITE   = 0xfc414d25
local SIO_PTR     = 0x9b50
local SIO_ORIG    = 0x121
local M6          = 0x364f4953      -- 'SIO6'
local IMGSENS_M   = 0x8650 + 0xc    -- 0x865c : ImgSens courant (3 visee photo, 1 ImgMode 1)
local TGSTATE     = 0xe664          -- 3 = TG en marche
local FC3C        = 0xfc3c          -- HivShdManLeo : c0f04a10 = table[7058] - 2*[0xfc3c]
local FC3C_M1     = (7058 - 2 * 1456) / 2   -- 2073 -> hauteur de tete 1456
local HE_CNT      = 0xfa84
local REQ_OFF     = 0x220
local ACK_OFF     = 0x224
local REQ_END     = 0xE0
local ARG_OFF     = 0x280           -- v185 : pad siohook6, argument C -> Lua ([0xfc3c] pour m1_on)
local last_fc3c   = FC3C_M1         -- v185 : derniere valeur [0xfc3c] posee par m1_on

local usb_ok = os.stat("A/M10USB.OK") and true or false

local function usb_now() return get_usb_power(1) == 1 and not usb_ok end
local function imgsens() return peek(IMGSENS_M) end
local function tg() return peek(TGSTATE) end
local function call(...) return call_func_ptr(...) end

-- attend cond() (pas de step ms) au plus ms ; renvoie cond()
local function wait_until(cond, ms, step)
  local t0 = get_tick_count()
  step = step or 100
  while not cond() and get_tick_count() - t0 < ms do sleep(step) end
  return cond()
end

local function say(l1, l2, l3)
  -- 360 x 240, police 8 px : 45 caracteres. Blanc (258) sur noir (257).
  pcall(draw_string, 8, 96, string.format("%-42s", l1 or ""), 258, 257)
  pcall(draw_string, 8, 114, string.format("%-42s", l2 or ""), 258, 257)
  pcall(draw_string, 8, 132, string.format("%-42s", l3 or ""), 258, 257)
end

local function quit(msg)
  if msg then print(msg) end
  pcall(draw_clear)
  exit_alt()                         -- rend toutes les touches a Canon
end

-- ===== 1. cable USB branche : le boitier reste un simple appareil PTP =====
if get_usb_power(1) == 1 and not usb_ok then
  print("USB: shell non lance")
  return
end

-- ===== 2. Lecture -> prise de vue =====
if not get_mode() then
  set_record(true)
  wait_until(function() return get_mode() and tg() == 3 end, 5000, 100)
end

-- ===== 3. attente de Photo M (sans error()) =====
do
  local okc, capmode = pcall(require, "capmode")
  local t_ok = nil
  local go = false
  while true do
    if usb_now() then quit("USB: shell non lance") return end
    if is_pressed("menu") then quit("M10 shell : abandon (MENU)") return end
    if not get_mode() then set_record(true) sleep(500) end
    local m, t = imgsens(), tg()
    if m == 3 and t == 3 then
      if not t_ok then t_ok = get_tick_count() end
      if get_tick_count() - t_ok >= 750 then go = true break end
    else
      t_ok = nil
      local name = "?"
      if okc and capmode then
        local okn, n = pcall(capmode.get_name)
        if okn and n then name = tostring(n) end
      end
      say("M10 1440p : mettre molette sur M",
          "Photo M requis (MENU = quitter)",
          string.format("mode %s ImgSens %d tg %d  SET=forcer", name, m, t))
      if is_pressed("set") then
        while is_pressed("set") do sleep(50) end
        break                        -- ex. Film 1x3 : le shell C gere l'etat
      end
    end
    sleep(250)
  end
  pcall(draw_clear)
  if go then print("M10 shell : Photo M ok") else print("M10 shell : lancement force (SET)") end
end

-- ===== 4. fichiers residuels + marqueur shell =====
for _, fn in ipairs({ "A/M10X3.CFG", "A/M10RUN.ASY", "A/M10X3.REQ", "A/M10X3.ACK", "A/M10SH.END" }) do
  if os.stat(fn) then os.remove(fn) end
end
do
  local f = io.open("A/M10SH.CFG", "w")
  if f then f:write("1\n") f:close() end
end

-- ===== 5. module_run =====
if peek(MODULE_RUN - 1) ~= 0x41f0e92d then
  say("M10 shell : module_run introuvable", "(CHDK different de 1.7.0 ?)", "")
  sleep(3000)
  quit("module_run introuvable")
  return
end
set_exit_key("shoot_full")
collectgarbage("collect")            -- r159 : le module (~400 Kio contigus) doit pouvoir se charger
local r = call(MODULE_RUN, "m10cine.flt")
print("m10cine shell:", r)
if r == -1 then
  say("m10cine.flt NON CHARGE", "(memoire ? fichier absent ?)", "")
  sleep(3000)
  os.remove("A/M10SH.CFG")
  quit("module_run=-1")
  return
end

-- ===== 6. crochet siohook6 (installe par le module, <= 5 s) =====
local function hook_find()
  local p = peek(SIO_PTR)
  if p == SIO_ORIG then return nil end
  local b = bitand(p, bitnot(1)) - 0x10
  if peek(b + 0x200) ~= M6 then return nil end
  return b
end

local b = nil
wait_until(function() b = hook_find() return b ~= nil end, 5000, 100)

-- ===== requetes =====
local cds_buf = nil
local mv_stopped = false
local fc3c0 = nil

local function chg_mode(m, ms)
  call(STOP_MODE)
  call(CHG_MODE, m, m, 0, 0, NOOP_CB, 0, NOOP_CB, 0)
  return wait_until(function() return imgsens() == m end, ms, 40)
end

local function write_cds()
  if not cds_buf then cds_buf = call(FN_MALLOC, 64) end
  if cds_buf == 0 then cds_buf = nil return false end
  local regs = { 0xc03a, 0xc03c, 0xc040, 0xc042, 0xc044 }
  for i, reg in ipairs(regs) do
    local a = cds_buf + 4 * (i - 1)
    poke(a, bitor(reg, bitshl(0x0247, 16)))   -- <HH reg, val (lclk 732)
    call(CDS_WRITE, a)
  end
  return true
end

local function m1_on()
  local afs = peek(AF_STATE)
  if afs == 7 or afs == 8 then call(AF_STOP, NOOP_CB, 0) sleep(100) end   -- coupe ContinuousAF/MovieAF avant ImgMode 1
  if not mv_stopped then call(MV_STOP) mv_stopped = true end
  if imgsens() == 1 then chg_mode(3, 2000) sleep(150) end   -- recommit propre (comme switch_m1)
  chg_mode(1, 3000)
  sleep(250)
  write_cds()
  sleep(150)
  if fc3c0 == nil then fc3c0 = peek(FC3C) end
  local fw = peek(b + ARG_OFF)      -- v185 : valeur fournie par le C (hauteur de tete du profil)
  if fw < 100 or fw > 3500 then fw = FC3C_M1 end
  last_fc3c = fw
  poke(FC3C, last_fc3c)            -- correctif 1-sur-3 (r158) : ChangeMode remet [0xfc3c] = 24
  sleep(100)
  poke(HE_CNT, 0)
  return (imgsens() == 1 and tg() == 3) and 1 or 0
end

local function m1_off()
  if imgsens() == 1 then
    chg_mode(3, 2000)
    sleep(300)
  end
  if fc3c0 ~= nil then
    if peek(FC3C) == last_fc3c then poke(FC3C, fc3c0) end
    fc3c0 = nil
  end
  if mv_stopped then call(MV_START) mv_stopped = false end
  return (imgsens() == 3 and tg() == 3) and 1 or 0
end

local function do_rec()            -- Film 1x3 : entree en prise de vue (corps v178d)
  press("shoot_half") sleep(800) release("shoot_half") sleep(500)
  set_record(true)
  wait_until(function() return get_mode() end, 8000, 100)
  sleep(2500)
  return get_mode() and 1 or 0
end

local function do_play()           -- Film 1x3 : passage en lecture (corps v178d)
  if get_mode() then
    set_record(false)
    wait_until(function() return not get_mode() end, 8000, 100)
    sleep(1500)
  end
  return (not get_mode()) and 1 or 0
end

local function do_af()             -- v183: AF Canon Hybrid (Photo M) en standby 1440p
  m1_off()                         -- retour Photo M (ImgSens 3 + MV_START -> PDAF+contraste actifs)
  if imgsens() ~= 3 or tg() ~= 3 then return 0 end
  sleep(250)                       -- v183c: Photo M settle before the half-press
  press("shoot_half")
  local locked = wait_until(function() return get_shooting() end, 1500, 40)   -- v183c: 1800 -> 1500 (dip << 2.2 s)
  local fok = locked
  if type(get_focus_ok) == "function" then
    local okf, r = pcall(get_focus_ok)
    if okf then fok = r and true or false end
  end
  release("shoot_half")
  -- v183d: wait for Canon to leave CancelPre (ImgSens 14) and reach _EntryIdleShoot (ImgSens 3) before acking:
  -- an M1_ON sent mid-CancelPre crashed WBInteg.c:2197 (flag 0x2000)
  wait_until(function() return not get_shooting() and imgsens() == 3 and tg() == 3 end, 3500, 50)
  sleep(350)
  return fok and 1 or 0
end

local HANDLERS = { [1] = m1_on, [2] = m1_off, [3] = do_rec, [4] = do_play, [5] = do_af }

local function ack(code, ok)
  local a = bitor(code, 0x100)
  a = bitor(a, bitshl(ok, 9))
  a = bitor(a, bitshl(bitand(imgsens(), 0xff), 16))
  a = bitor(a, bitshl(bitand(tg(), 0xff), 24))
  poke(b + REQ_OFF, 0)               -- requete consommee...
  poke(b + ACK_OFF, a)               -- ...puis accuse, en dernier
end

-- ===== 7. boucle principale (peek + get_usb_power uniquement) =====
local module_gone = false
if b then
  local hook_ptr = bitor(b + 0x10, 1)
  local usb_deadline = nil
  while true do
    sleep(100)
    local p = peek(SIO_PTR)
    if p == SIO_ORIG then module_gone = true break end       -- le module s'est desinstalle
    if p ~= hook_ptr then                                    -- crochet reinstalle ailleurs
      local nb = hook_find()
      if not nb then module_gone = true break end
      b = nb hook_ptr = bitor(b + 0x10, 1)
    end
    local code = peek(b + REQ_OFF)
    if code == REQ_END then
      poke(b + REQ_OFF, 0)
      poke(b + ACK_OFF, bitor(REQ_END, 0x100))
      module_gone = true
      break
    end
    local h = HANDLERS[code]
    if h then
      local ok = h()
      ack(code, ok)
      if usb_deadline and usb_deadline - get_tick_count() < 500 then usb_deadline = get_tick_count() + 500 end
    end
    if usb_now() then
      -- le module voit l'USB lui aussi : il arrete la prise, demande m1_off puis 0xE0
      if not usb_deadline then usb_deadline = get_tick_count() + 3000 end
      if get_tick_count() > usb_deadline then break end
    end
  end
else
  -- repli : pas de siohook6 (module anterieur a v182, ex. --flt v181c) -> protocole fichiers v178d
  print("M10 shell : siohook6 absent, protocole fichiers")
  local function legacy_req(step)
    local res
    if step == "play" then res = do_play() elseif step == "rec" then res = do_rec() else res = 0 end
    local a = io.open("A/M10X3.ACK", "w")
    if a then a:write(step, " ", tostring(res), " ", tostring(get_mode()), "\n") a:close() end
  end
  while not usb_now() do
    if os.stat("A/M10SH.END") then break end
    local q = io.open("A/M10X3.REQ", "r")
    if q then
      local step = q:read("*l") or ""
      q:close()
      os.remove("A/M10X3.REQ")
      legacy_req(step)
    end
    sleep(200)
  end
end

-- ===== 8. sortie =====
-- Filet de securite : le module est parti (ou l'USB a expire) en laissant ImgMode 1 / MotionVector arrete.
if imgsens() == 1 or mv_stopped then
  print("M10 shell : ImgMode 1 laisse (module_gone=" .. tostring(module_gone) .. ") -> m1_off")
  m1_off()
end
if os.stat("A/M10SH.CFG") then os.remove("A/M10SH.CFG") end   -- les outils PTP ne doivent pas heriter du mode shell
quit("M10 shell : fin")
