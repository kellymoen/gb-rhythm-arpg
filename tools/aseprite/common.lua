-- Shared helpers for the placeholder generators (loaded with dofile from player.lua / dummy.lua).
--
--   aseprite -b --script-param root=<repo> [--script-param force=1] --script tools/aseprite/player.lua
--
-- Writes assets/sprites/<name>_genplaceholder.aseprite following the sprite asset contract (ADR 0006,
-- docs/sprites.md). Never overwrites an existing placeholder unless force=1, and never writes one when
-- the author's assets/sprites/<name>.aseprite exists (ADR 0007).

local M = {}

-- 4 shades, index 0 = lightest = transparent (the converters' convention, tools/gbtools/tiles.py).
M.SHADES = { { 232, 240, 216 }, { 152, 184, 120 }, { 72, 104, 72 }, { 16, 32, 32 } }

local function exists(path)
  local f = io.open(path, "r")
  if f then f:close() return true end
  return false
end

-- Returns the output path, or nil (after printing why) when nothing should be written.
function M.target(name)
  local root = app.params.root
  if not root then error("pass --script-param root=<repo root>") end
  local mine = root .. "/assets/sprites/" .. name .. ".aseprite"
  local path = root .. "/assets/sprites/" .. name .. "_genplaceholder.aseprite"
  if exists(mine) then
    print("skip " .. path .. " (replaced by your " .. mine .. ")")
    return nil
  end
  if exists(path) and app.params.force ~= "1" then
    print("skip " .. path .. " (exists; use force to overwrite)")
    return nil
  end
  return path
end

-- Pixel helpers on an indexed Image (colour = palette index).
function M.px(img, x, y, c)
  if x >= 0 and y >= 0 and x < img.width and y < img.height then img:drawPixel(x, y, c) end
end

function M.rect(img, x0, y0, x1, y1, c)
  for y = y0, y1 do for x = x0, x1 do M.px(img, x, y, c) end end
end

function M.frame(img, x0, y0, x1, y1, line, fill)
  M.rect(img, x0, y0, x1, y1, line)
  if fill then M.rect(img, x0 + 1, y0 + 1, x1 - 1, y1 - 1, fill) end
end

function M.line(img, x0, y0, x1, y1, c)
  local dx, dy = math.abs(x1 - x0), -math.abs(y1 - y0)
  local sx, sy = x0 < x1 and 1 or -1, y0 < y1 and 1 or -1
  local err = dx + dy
  while true do
    M.px(img, x0, y0, c)
    if x0 == x1 and y0 == y1 then break end
    local e2 = 2 * err
    if e2 >= dy then err = err + dy; x0 = x0 + sx end
    if e2 <= dx then err = err + dx; y0 = y0 + sy end
  end
end

-- 3x5 glyphs for the action letters printed on the torso.
local GLYPHS = {
  ["1"] = { " # ", "## ", " # ", " # ", "###" },
  ["2"] = { "## ", "  #", " # ", "#  ", "###" },
  ["3"] = { "## ", "  #", " ##", "  #", "## " },
  ["4"] = { "# #", "# #", "###", "  #", "  #" },
  F = { "###", "#  ", "## ", "#  ", "#  " },
  H = { "# #", "# #", "###", "# #", "# #" },
  W = { "# #", "# #", "# #", "###", "# #" },
  L = { "#  ", "#  ", "#  ", "#  ", "###" },
}

function M.glyph(img, x, y, ch, c)
  local g = GLYPHS[ch]
  if not g then return end
  for r = 1, 5 do
    for k = 1, 3 do
      if g[r]:sub(k, k) == "#" then M.px(img, x + k - 1, y + r - 1, c) end
    end
  end
end

-- spec = {
--   name, w, h,
--   tags   = { { name = "idle_s", data = "dur=1/4 loop", frames = { {ms = 100, draw = function(img) end}, ... } }, ... },
--   slices = { { name = "pivot", rect = Rectangle(...) }, ... },
-- }
-- Frames are laid out tag after tag on the timeline.
function M.build(spec, path)
  local spr = Sprite(spec.w, spec.h, ColorMode.INDEXED)
  local pal = spr.palettes[1]
  pal:resize(4)
  for i, rgb in ipairs(M.SHADES) do
    pal:setColor(i - 1, Color { r = rgb[1], g = rgb[2], b = rgb[3], a = (i == 1) and 0 or 255 })
  end
  spr.transparentColor = 0

  local total = 0
  for _, t in ipairs(spec.tags) do total = total + #t.frames end
  for _ = 2, total do spr:newFrame() end

  local layer = spr.layers[1]
  layer.name = "body"
  local n = 0
  for _, t in ipairs(spec.tags) do
    for _, f in ipairs(t.frames) do
      n = n + 1
      local img = Image(spec.w, spec.h, ColorMode.INDEXED)
      f.draw(img)
      spr:newCel(layer, n, img, Point(0, 0))
      spr.frames[n].duration = f.ms / 1000
    end
  end

  n = 0
  for _, t in ipairs(spec.tags) do
    local tag = spr:newTag(n + 1, n + #t.frames)
    tag.name = t.name
    tag.data = t.data
    n = n + #t.frames
  end

  for _, s in ipairs(spec.slices) do
    local slice = spr:newSlice(s.rect)
    slice.name = s.name
  end

  spr:saveAs(path)
  print("wrote " .. path)
end

return M
