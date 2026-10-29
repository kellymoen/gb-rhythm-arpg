-- Placeholder training dummy: 16x32, one facing. Tags carry no facing suffix (`idle`, `hurt`), which
-- means "the same art for all 5 drawn facings" (docs/sprites.md).
--   aseprite -b --script-param root=. [--script-param force=1] --script tools/aseprite/dummy.lua
local root = app.params.root or "."
local C = dofile(root .. "/tools/aseprite/common.lua")

local path = C.target("dummy")
if not path then return end

-- sway: horizontal shift of the top half; flash: inverted shades.
local function dummy(sway, flash)
  return function(img)
    local line, fill = 3, 1
    if flash then line, fill = 1, 3 end
    C.rect(img, 7, 10, 8, 29, 2) -- post
    C.frame(img, 3, 29, 12, 30, 3, 2) -- base
    local s = sway
    C.frame(img, 3 + s, 11, 12 + s, 21, line, fill) -- straw body
    C.rect(img, 4 + s, 15, 11 + s, 15, 2)
    C.rect(img, 4 + s, 18, 11 + s, 18, 2)
    C.frame(img, 4 + s, 3, 11 + s, 10, line, fill) -- head
    C.rect(img, 6 + s, 6, 6 + s, 7, 3) -- eyes
    C.rect(img, 9 + s, 6, 9 + s, 7, 3)
    C.line(img, 2 + s, 12, 0, 14, 2) -- arms
    C.line(img, 13 + s, 12, 15, 14, 2)
    if flash then C.px(img, 8 + s, 1, 3); C.px(img, 4, 2, 3); C.px(img, 12, 2, 3) end
  end
end

C.build({
  w = 16, h = 32,
  tags = {
    { name = "idle", data = "dur=1/2 loop", frames = {
      { ms = 100, draw = dummy(0, false) }, { ms = 100, draw = dummy(1, false) } } },
    { name = "hurt", data = "dur=1/8", frames = {
      { ms = 70, draw = dummy(-2, true) }, { ms = 110, draw = dummy(2, false) } } },
  },
  slices = {
    { name = "pivot", rect = Rectangle(8, 30, 1, 1) },
    { name = "hurtbox", rect = Rectangle(3, 3, 10, 28) },
  },
}, path)
