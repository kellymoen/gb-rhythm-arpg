# Sprites: drawing over the placeholder

Character art is one `.aseprite` per character in `assets/sprites/`. The build exports it with Aseprite,
converts it to banked C data and links it into the ROM. Contract: ADR 0006 (structure), ADR 0007 (naming,
`exports/`). C layout: `src/gb/spritedata.h`. Budgets: `src/core/budgets.h`.

## Replacing a placeholder

Claude's placeholders are `assets/sprites/player_genplaceholder.aseprite` and
`dummy_genplaceholder.aseprite`. Open one, paint over it (keep the tags, slices and canvas size), and
*Save As* `assets/sprites/player.aseprite`. Your file wins; `make` prints `assets: yours N/M (...)`.

Then run `make` **on a machine with Aseprite** and commit `exports/sprites/<your file>.{png,json,sha1}`
beside the `.aseprite`. CI has no Aseprite; it uses the committed export and fails if its hash no longer
matches your `.aseprite` (`... changed since player.png was exported ... run make with Aseprite installed
and commit exports/`).

`make placeholders` regenerates missing placeholders from `tools/aseprite/*.lua`. It never overwrites an
existing one (`make placeholders FORCE_PLACEHOLDERS=1` does) and never writes one next to your own file.

## The file

- **Mode:** Indexed, **4 colours**. Index 0 is the transparent shade, 1-3 are light to dark. The shades
  become the DMG greys and the CGB palette at runtime. Any index above 3 is an error.
- **Canvas:** width a multiple of 8, height a multiple of 16 (8x16 sprites), at most 24x32 for `player` and
  16x32 for every other character (`BUDGET_PLAYER_*`, `BUDGET_ENEMY_*`). All frames share the canvas.
- **Budget per frame:** at most 12 tiles = 6 OBJs (`BUDGET_FRAME_TILES`, `BUDGET_PLAYER_OBJS`). The canvas
  is cut into 8x16 parts on its own grid; fully transparent parts cost nothing, so keep art inside as few
  parts as you can.
- **Layers:** any; the export flattens them. Every frame used by a tag must have something on it.

### Tags: `<action>_<facing>`

Facings are `s se e ne n` (the five drawn ones). `sw w nw` are the horizontal flips of `se e ne`, drawn at
runtime; a tag with one of those suffixes is an error.

`player` needs the actions `idle walk dodge hurt light1 light2 light3 light4 finisher heavy1 heavy2` x all five
facings, and may have `lunge`. `dummy` needs `idle hurt`. A character not in that list (`tools/gbtools/sprites.py`,
`KNOWN_SPRITES`) gets exactly the actions you tag. Any action in the file becomes `SPRITE_<NAME>_<ACTION>`.

- **Single-facing actions:** a tag with no suffix (`idle`) uses the same art for all five facings. Don't
  mix `idle` with `idle_s` ... in one file. The dummy works this way.
- **Optional actions:** an action in the converter's optional list (`lunge` on the player) may have no tags at
  all. For any action, put the word `optional` in the user data of its tags to allow missing facings; the
  runtime gets NULL for those and must cope. Otherwise a missing tag is an error naming it.
- Tag direction must be Forward. A tag's frames are its slice of the timeline.

### Tag user data

Whitespace-separated words in the tag's user data (right-click the tag > Properties > User Data):

| word | meaning |
|---|---|
| `dur=<n>/<d>` | **required.** Musical length of the *whole tag* as a note value: `1/4` = one beat (48 song ticks), `1/8` = 24, `1/16` = 12, `1/12` = 16, `1/2` = two beats. `dur=2` = two whole notes. Must be a whole number of ticks. |
| `hit=<k>` | attack tags: the k-th frame of the tag (**1 = the tag's first frame**) is the one whose hitbox is live. |
| `loop` | restart after the last frame (idle, walk). |
| `optional` | see above. |

Frame durations in Aseprite only set the **proportions** inside the tag: with `dur=1/8` and frames of
90/60/110 ms the frames last 8/6/10 ticks (8, 14, 24 cumulative). A frame must get at least one tick.

### Slices

Slices use sprite coordinates. All positions are stored relative to the **pivot**.

- `pivot`: required. The character's feet. A 1x1 slice on the ground pixel is simplest; for a bigger slice the
  pivot is its bottom-centre pixel. Metasprite parts, hitbox and hurtbox are all measured from it.
- `hurtbox`: required. Where the character can be hit.
- `hitbox`: required on each tag's hit frame (`hit=`). Where the attack hurts. Ignored on other frames.

A slice's key applies from its frame until the next key, so one slice with several keys changes between
frames. To give a single tag its own box, name the slice `<kind>:<tag>`, e.g. `hitbox:light1_se`; it wins
over plain `hitbox` for that tag. The placeholder uses this because the Lua scripting API cannot make
per-frame keys.

## What the build does with it

1. `tools/gbtools/export.py` runs `aseprite -b` for every resolved `.aseprite`: a one-row sheet PNG plus
   JSON (frames, durations, tags, user data, slices) and a `.sha1` of the source into `exports/sprites/`. It
   reruns only when the source's hash changed.
2. `tools/gbtools/sprites.py` reads only that PNG + JSON (no Aseprite) and writes `build/gen/sprite_<name>.h`,
   `sprite_<name>.c` and `spritebank_<name>_{1,2,3}.c`.

### For the C runtime

- `sprite_<name>.h` declares the enum `SPRITE_<NAME>_<ACTION>` (+ `_ACTION_COUNT`), `sprite_<name>`
  (`sprite_t`, per `spritedata.h`) and `BANKREF_EXTERN(sprite_<name>)`.
- The data is split over up to four ROM banks when it does not fit one (the player placeholder needs three):
  1. `SWITCH_ROM(BANK(sprite_<name>))`; read `sprite_<name>.anims[action * DRAWN_FACINGS + facing]`
     and `sprite_<name>_anim_bank[same index].bank`.
  2. `SWITCH_ROM` to that bank; everything the `sprite_anim_t` points at (frames, `ends`, tiles, metasprites) is there.
  A NULL anim has bank 0. For a small sprite all entries equal `sprite_t.bank`.
- Metasprite tile indices are 0, 2, 4, ... for the 8x16 parts of a frame, relative to the frame's VRAM slot;
  the slot's base tile must be even. Each frame's tiles are `tile_count * 16` bytes, top tile then bottom tile
  of each part.
- `ends[i]` are cumulative song ticks (`BEAT_TICKS` = 48 per beat); the last is the whole tag's length.
  Only the hit frame has a hitbox (others are `w == 0`).

## Errors you may see

Each message starts with the source file name and says what to change.

| message | fix |
|---|---|
| `tag light2_ne frame 1: 13 tiles, budget is 12 (BUDGET_FRAME_TILES); trim the frame` | erase pixels so fewer 8x16 parts are touched |
| `... N OBJs, budget is 6 (BUDGET_PLAYER_OBJS)` | same |
| `canvas is 32x32, budget is 24x32 (BUDGET_PLAYER_W/H)` | Sprite > Canvas Size |
| `canvas is 20x32; width must be a multiple of 8 and height of 16` | Sprite > Canvas Size |
| `tag walk_ne frame 3: tile (8,16) uses palette index 5` | repaint with the first four palette colours (or convert to Indexed with 4 colours) |
| `missing tag idle_n` | draw it, or add `optional` to the action's tags |
| `tag X: no dur=` / `unknown user data` / `hit=3 but the tag has 2 frames` | fix the tag's user data |
| `dur=1/7 is not a whole number of song ticks` | use 1/4, 1/8, 1/16, 1/12, 1/32 ... |
| `would last 0 ticks` | lengthen `dur`, lengthen that frame's duration, or drop frames |
| `no pivot slice` / `no hurtbox slice` / `hit frame has no hitbox slice` | add the slice |
| `tag idle_w: W is drawn by flipping E` | delete the tag; draw `idle_e` |
| `sprite data is ~N bytes; the converter supports 4 ROM banks` | fewer frames or smaller art |
| `... changed since X.png was exported ... run make with Aseprite installed and commit exports/` | run `make` where Aseprite is installed and commit `exports/` |

## The placeholders

`tools/aseprite/player.lua` and `dummy.lua` (shared helpers in `common.lua`) draw them. Facing is the head
(hair, eyes, nose); the action is the weapon pose, a letter on the torso (1-4 light, F finisher, H heavy1,
W heavy2, L lunge) and effects (speed lines for dodge/lunge, sparks for hurt). Player: 60 tags, 180 frames,
2-4 frames each; idle `dur=1/2 loop` (two beats), walk `dur=1/4 loop`, light attacks `dur=1/8`, finisher and
heavies `dur=1/4`. All of it is PROVISIONAL timing for the combat feel pass.
