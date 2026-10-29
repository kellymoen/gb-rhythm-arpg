-- Placeholder player: 24x32, 60 tags <action>_<facing> (12 actions x 5 drawn facings), 2-4 frames each.
-- Facing: head (hair/eyes/nose) and body lean; action: weapon pose, torso letter, effects.
--   aseprite -b --script-param root=. [--script-param force=1] --script tools/aseprite/player.lua
local root = app.params.root or "."
local C = dofile(root .. "/tools/aseprite/common.lua")

local path = C.target("player")
if not path then return end

local W, H = 24, 32
local PIVOT = { x = 12, y = 30 }
local FACINGS = { "s", "se", "e", "ne", "n" }
local LEAN = { s = { 0, 1 }, se = { 1, 1 }, e = { 1, 0 }, ne = { 1, -1 }, n = { 0, -1 } }

local function head(img, f, x, y, p)
  C.frame(img, x, y, x + 5, y + 6, p.line, p.fill)
  local eye = p.line
  if f == "n" then
    C.rect(img, x + 1, y + 1, x + 4, y + 5, 2)
  elseif f == "ne" then
    C.rect(img, x + 1, y + 1, x + 2, y + 5, 2)
    C.rect(img, x + 3, y + 1, x + 4, y + 2, 2)
    C.px(img, x + 6, y + 4, p.line)
  elseif f == "e" then
    C.rect(img, x + 1, y + 1, x + 4, y + 2, 2)
    C.rect(img, x + 1, y + 1, x + 2, y + 5, 2)
    C.px(img, x + 4, y + 3, eye)
    C.px(img, x + 6, y + 4, p.line) -- nose
  elseif f == "se" then
    C.rect(img, x + 1, y + 1, x + 4, y + 2, 2)
    C.px(img, x + 2, y + 4, eye)
    C.px(img, x + 4, y + 4, eye)
    C.px(img, x + 5, y + 5, p.line)
  else
    C.rect(img, x + 1, y + 1, x + 4, y + 2, 2)
    C.px(img, x + 1, y + 4, eye)
    C.px(img, x + 4, y + 4, eye)
  end
  if p.mood == "ouch" and f ~= "n" and f ~= "ne" then
    C.px(img, x + 2, y + 5, p.line)
    C.px(img, x + 3, y + 5, p.line)
    C.px(img, x + (f == "s" and 1 or 2), y + 3, eye)
    C.px(img, x + 4, y + 3, eye)
  end
end

local function weapon(img, f, p, sx, sy)
  local w = p.wp
  if not w then return end
  C.line(img, sx, sy, w[1], w[2], 3) -- arm
  C.line(img, w[1], w[2] + 1, w[3], w[4] + 1, 2) -- blade shading
  C.line(img, w[1], w[2], w[3], w[4], 3) -- blade
  C.rect(img, w[1] - 1, w[2] - 1, w[1], w[2], 3) -- hand
end

local function figure(img, f, p)
  p = p or {}
  p.line, p.fill = 3, 1
  if p.flash then p.line, p.fill = 1, 3 end
  local by = p.by or 0
  local lean = p.lean or 0
  local ox, oy = LEAN[f][1] * lean, by + LEAN[f][2] * lean
  local side = (f == "e")
  local tx0, tx1 = side and 9 or 8, side and 14 or 15

  -- legs (stride: +1 front leg forward / back leg lifted, -1 mirrored, 0 together)
  local top = 22 + by
  local stride = p.stride or 0
  local lend = stride == -1 and 27 or 29
  local rend = stride == 1 and 27 or 29
  if side then
    C.rect(img, 9, top, 11, lend, 2); C.rect(img, 12, top, 14, rend, 2)
    C.rect(img, 9, lend, 11, lend, 3); C.rect(img, 12, rend, 14, rend, 3)
  else
    C.rect(img, 8, top, 10, lend, 2); C.rect(img, 13, top, 15, rend, 2)
    C.rect(img, 8, lend, 10, lend, 3); C.rect(img, 13, rend, 15, rend, 3)
  end
  C.rect(img, 9, 30, 14, 30, 1) -- ground shadow under the pivot

  local sx, sy = tx1 + 1 + ox, 13 + oy -- right shoulder
  local behind = (f == "n" or f == "ne")
  if behind then weapon(img, f, p, sx, sy) end

  -- torso
  local ty0, ty1 = 11 + oy, 21 + oy
  C.frame(img, tx0 + ox, ty0, tx1 + ox, ty1, p.line, p.fill)
  if p.ghost then
    for y = ty0 + 1, ty1 - 1 do
      for x = tx0 + ox + 1, tx1 + ox - 1 do
        if (x + y) % 2 == 0 then C.px(img, x, y, 0) end
      end
    end
  end
  C.rect(img, tx0 + ox + 1, 19 + oy, tx1 + ox - 1, 19 + oy, p.line) -- belt
  if f == "n" or f == "ne" then C.rect(img, 11 + ox, ty0 + 1, 12 + ox, 17 + oy, 2) end -- back stripe
  if p.glyph then C.glyph(img, 10 + ox + (side and 0 or 0), 13 + oy, p.glyph, p.line) end

  -- left arm
  if p.armsup then
    C.line(img, tx0 + ox - 1, 13 + oy, 5, 7, 3)
  else
    C.rect(img, tx0 + ox - 2, 13 + oy, tx0 + ox - 1, 18 + oy, 2)
    C.rect(img, tx0 + ox - 2, 19 + oy, tx0 + ox - 1, 19 + oy, 3)
  end
  head(img, f, 9 + ox + (f == "se" and 1 or 0), 4 + oy, p)

  if not behind then
    if p.armsup then C.line(img, sx, sy, 18, 7, 3) else weapon(img, f, p, sx, sy) end
  end
  if p.fx then p.fx(img, f) end
end

-- Effects ---------------------------------------------------------------------------------------
local function lines(ys, x0, x1)
  return function(img)
    for _, y in ipairs(ys) do C.line(img, x0, y, x1, y, 2) end
  end
end
local function dots(list, c)
  return function(img)
    for _, d in ipairs(list) do C.px(img, d[1], d[2], c or 3) end
  end
end
local function both(a, b) return function(img, f) a(img, f); b(img, f) end end
local function ring(img)
  for _, d in ipairs({ { 3, 4 }, { 20, 4 }, { 3, 24 }, { 20, 24 }, { 2, 14 }, { 21, 14 } }) do
    C.px(img, d[1], d[2], 3); C.px(img, d[1] + 1, d[2], 3); C.px(img, d[1], d[2] + 1, 3)
  end
end

-- Actions: frames are poses (see figure()); ms are Aseprite frame durations (the weights that split
-- the tag's `dur`); data is the tag user data. Hit frame numbers are 1-based within the tag.
local ACTIONS = {
  { name = "idle", data = "dur=1/2 loop", ms = { 100, 100 }, poses = {
    { wp = { 17, 21, 19, 28 } },
    { wp = { 17, 22, 19, 29 }, by = 1 } } },
  { name = "walk", data = "dur=1/4 loop", ms = { 100, 100, 100, 100 }, poses = {
    { stride = 1, wp = { 17, 20, 19, 27 } },
    { stride = 0, by = 1, wp = { 17, 21, 19, 28 } },
    { stride = -1, wp = { 17, 20, 19, 27 } },
    { stride = 0, by = 1, wp = { 17, 21, 19, 28 } } } },
  { name = "dodge", data = "dur=1/8", ms = { 60, 60, 100 }, poses = {
    { by = 4, ghost = true, lean = 0, fx = lines({ 14, 18, 22 }, 0, 5) },
    { by = 6, ghost = true, lean = 1, fx = lines({ 16, 20, 24 }, 0, 6) },
    { by = 3, ghost = true, fx = lines({ 18 }, 0, 4) } } },
  { name = "hurt", data = "dur=1/8", ms = { 70, 110 }, poses = {
    { flash = true, armsup = true, mood = "ouch", lean = -1, fx = dots({ { 12, 1 }, { 8, 2 }, { 16, 2 } }) },
    { armsup = true, mood = "ouch", lean = -1, fx = dots({ { 5, 2 }, { 19, 3 } }) } } },
  { name = "light1", data = "dur=1/8 hit=2", ms = { 90, 60, 110 }, glyph = "1", poses = {
    { wp = { 17, 14, 21, 8 } },
    { lean = 1, wp = { 18, 18, 23, 18 }, fx = dots({ { 20, 13 }, { 22, 15 }, { 22, 21 } }) },
    { wp = { 17, 19, 21, 25 } } } },
  { name = "light2", data = "dur=1/8 hit=2", ms = { 90, 60, 110 }, glyph = "2", poses = {
    { wp = { 17, 19, 22, 25 } },
    { lean = 1, wp = { 18, 16, 23, 10 }, fx = dots({ { 21, 18 }, { 22, 14 }, { 20, 9 } }) },
    { wp = { 16, 12, 19, 5 } } } },
  { name = "light3", data = "dur=1/8 hit=2", ms = { 90, 60, 110 }, glyph = "3", poses = {
    { wp = { 17, 12, 18, 3 } },
    { lean = 1, wp = { 18, 14, 22, 20 }, fx = dots({ { 22, 8 }, { 23, 11 }, { 23, 16 } }) },
    { wp = { 18, 19, 19, 27 } } } },
  { name = "light4", data = "dur=1/8 hit=2", ms = { 90, 70, 100 }, glyph = "4", poses = {
    { wp = { 15, 17, 19, 17 } },
    { lean = 2, wp = { 19, 17, 23, 17 }, fx = lines({ 14, 17, 20 }, 3, 8) },
    { wp = { 17, 17, 21, 17 } } } },
  { name = "finisher", data = "dur=1/4 hit=3", ms = { 70, 70, 70, 110 }, glyph = "F", poses = {
    { wp = { 14, 17, 22, 17 }, fx = ring },
    { wp = { 12, 18, 12, 27 }, fx = ring },
    { lean = 1, wp = { 10, 17, 2, 17 }, fx = both(ring, dots({ { 1, 12 }, { 1, 22 }, { 12, 1 } })) },
    { wp = { 12, 16, 12, 8 } } } },
  { name = "heavy1", data = "dur=1/4 hit=3", ms = { 120, 100, 60, 160 }, glyph = "H", poses = {
    { wp = { 17, 10, 19, 1 } },
    { by = 1, wp = { 17, 10, 19, 1 }, fx = dots({ { 22, 3 }, { 22, 6 } }) },
    { lean = 1, wp = { 18, 20, 22, 29 }, fx = lines({ 29 }, 14, 23) },
    { wp = { 17, 20, 21, 28 } } } },
  { name = "heavy2", data = "dur=1/4 hit=2", ms = { 140, 70, 120 }, glyph = "W", poses = {
    { by = 2, wp = { 15, 20, 8, 25 } },
    { by = 2, lean = 1, wp = { 18, 23, 23, 25 }, fx = lines({ 26, 28 }, 14, 23) },
    { by = 2, wp = { 17, 22, 22, 22 } } } },
  { name = "lunge", data = "dur=1/8 hit=2", ms = { 80, 100 }, glyph = "L", poses = {
    { lean = 1, stride = 1, wp = { 18, 18, 22, 18 }, fx = lines({ 14, 18, 22 }, 2, 7) },
    { lean = 2, stride = -1, wp = { 18, 18, 23, 18 }, fx = lines({ 12, 16, 20, 24 }, 0, 5) } } },
}

-- Hitbox (x, y, w, h in canvas px) in front of the pivot, per facing; wide for heavy/lunge, a ring
-- for the finisher.
local REACH = {
  normal = { s = { 6, 22, 13, 9 }, se = { 13, 20, 10, 11 }, e = { 14, 14, 10, 12 }, ne = { 13, 8, 10, 12 }, n = { 6, 5, 13, 8 } },
  wide = { s = { 4, 21, 17, 10 }, se = { 12, 17, 12, 14 }, e = { 13, 11, 11, 17 }, ne = { 12, 6, 12, 14 }, n = { 4, 2, 17, 10 } },
  ring = { s = { 2, 8, 20, 23 }, se = { 2, 8, 20, 23 }, e = { 2, 8, 20, 23 }, ne = { 2, 8, 20, 23 }, n = { 2, 8, 20, 23 } },
}
local REACH_OF = { heavy1 = "wide", heavy2 = "wide", lunge = "wide", finisher = "ring" }

local tags, slices = {}, {
  { name = "pivot", rect = Rectangle(PIVOT.x, PIVOT.y, 1, 1) },
  { name = "hurtbox", rect = Rectangle(8, 5, 8, 25) },
}
for _, a in ipairs(ACTIONS) do
  for _, f in ipairs(FACINGS) do
    local frames = {}
    for i, pose in ipairs(a.poses) do
      local p = {}
      for k, v in pairs(pose) do p[k] = v end
      p.glyph = a.glyph
      frames[i] = { ms = a.ms[i], draw = function(img) figure(img, f, p) end }
    end
    local name = a.name .. "_" .. f
    tags[#tags + 1] = { name = name, data = a.data, frames = frames }
    if a.data:find("hit=") then
      local r = REACH[REACH_OF[a.name] or "normal"][f]
      slices[#slices + 1] = { name = "hitbox:" .. name, rect = Rectangle(r[1], r[2], r[3], r[4]) }
    end
  end
end

C.build({ w = W, h = H, tags = tags, slices = slices }, path)
