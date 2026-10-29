"""Sprite converter tests on synthetic PNG + JSON sheets (no Aseprite needed)."""

import json
from pathlib import Path

import pytest
from PIL import Image

from gbtools import sprites
from gbtools.errors import ConvertError

REPO = Path(__file__).resolve().parents[2]
BUDGETS = {
    # enemy canvas is as wide as the player's so one set of generic test sheets fits
    "BUDGET_PLAYER_W": 24, "BUDGET_PLAYER_H": 32, "BUDGET_PLAYER_OBJS": 6,
    "BUDGET_ENEMY_W": 24, "BUDGET_ENEMY_H": 32, "BUDGET_FRAME_TILES": 12,
}
PIVOT_SLICE = {"name": "pivot", "keys": [{"frame": 0, "bounds": {"x": 12, "y": 30, "w": 1, "h": 1}}]}
HURT_SLICE = {"name": "hurtbox", "keys": [{"frame": 0, "bounds": {"x": 8, "y": 5, "w": 8, "h": 25}}]}


class Sheet:
    """A horizontal sheet of `frames` canvases with Aseprite-style JSON."""

    def __init__(self, frames, w=24, h=32, name="hero", ms=100):
        self.w, self.h, self.n, self.name = w, h, frames, name
        self.img = Image.new("P", (w * frames, h), 0)
        self.img.putpalette([232, 240, 216, 152, 184, 120, 72, 104, 72, 16, 32, 32] + [255, 0, 0] * 4)
        self.durations = [ms] * frames
        self.tags: list[dict] = []
        self.slices = [PIVOT_SLICE, HURT_SLICE]

    def px(self, frame, x, y, v=3):
        self.img.putpixel((frame * self.w + x, y), v)
        return self

    def tag(self, name, first, last, data="dur=1/8", direction="forward"):
        self.tags.append({"name": name, "from": first, "to": last, "direction": direction, "data": data})
        return self

    def write(self, tmp_path, stem=None):
        stem = stem or f"{self.name}_genplaceholder"
        png, js = tmp_path / f"{stem}.png", tmp_path / f"{stem}.json"
        self.img.save(png)
        doc = {
            "frames": [
                {"filename": f"{stem} {i}.aseprite",
                 "frame": {"x": i * self.w, "y": 0, "w": self.w, "h": self.h}, "rotated": False, "trimmed": False,
                 "spriteSourceSize": {"x": 0, "y": 0, "w": self.w, "h": self.h},
                 "sourceSize": {"w": self.w, "h": self.h}, "duration": self.durations[i]}
                for i in range(self.n)
            ],
            "meta": {"image": png.name, "frameTags": self.tags, "slices": self.slices},
        }
        js.write_text(json.dumps(doc))
        return png, js


def all_facings(sheet, action, data="dur=1/8", frames_per_tag=1):
    """Tags <action>_<facing> for each drawn facing, one after another from frame 0."""
    for i, f in enumerate(sprites.FACINGS):
        sheet.tag(f"{action}_{f}", i * frames_per_tag, (i + 1) * frames_per_tag - 1, data)
    return sheet


def simple(tmp_path, **kw):
    """5 one-frame facing tags of one action `idle` with a pixel on every frame."""
    sh = Sheet(5, **kw)
    for fr in range(5):
        sh.px(fr, 4, sh.h - 3)
    all_facings(sh, "idle")
    return sh


def convert(sheet, tmp_path, budgets=BUDGETS):
    png, js = sheet.write(tmp_path)
    return sprites.convert(png, js, budgets, 48)


# --- tile slicing, metasprites, pivot ---------------------------------------------------------


def test_2bpp_tiles_are_sliced_top_then_bottom_per_8x16_part(tmp_path):
    sh = Sheet(5)
    for fr in range(5):
        sh.px(fr, 0, 0, 3).px(fr, 1, 8, 1)  # part (0,0): top tile pixel shade 3, bottom tile pixel shade 1
    all_facings(sh, "idle")
    f = convert(sh, tmp_path).slots[0][0].frames[0]
    assert f.parts == [(0 - 30, 0 - 12)]
    top, bottom = f.tiles[:16], f.tiles[16:]
    assert top[0:2] == bytes([0b10000000, 0b10000000])  # shade 3: both planes
    assert bottom[0:2] == bytes([0b01000000, 0])  # shade 1: low plane only, second pixel


def test_empty_parts_are_dropped_and_tiles_follow_part_order(tmp_path):
    sh = Sheet(5)
    for fr in range(5):
        sh.px(fr, 20, 17).px(fr, 3, 2)  # parts (16,0) bottom row and (0,0) top row; the other four are empty
    all_facings(sh, "idle")
    f = convert(sh, tmp_path).slots[0][0].frames[0]
    # row-major: top row first
    assert f.parts == [(0 - 30, 0 - 12), (16 - 30, 16 - 12)]
    assert len(f.tiles) == 2 * 32
    assert f.tiles[4:6] != bytes(2)  # first part holds the pixel at (3,2): row 2 = bytes 4-5


def test_metasprite_origin_is_the_pivot_and_tile_indices_step_by_two(tmp_path):
    sh = Sheet(5)
    for fr in range(5):
        sh.px(fr, 1, 1).px(fr, 9, 1).px(fr, 17, 17)
    all_facings(sh, "idle")
    spr = convert(sh, tmp_path)
    assert spr.slots[0][0].frames[0].parts == [(-30, -12), (-30, -4), (-14, 4)]
    text = sprites.render_sources(spr)["sprite_hero.c"]
    assert "METASPR_ITEM(-30, -12, 0, 0)," in text
    assert "METASPR_ITEM(-30, -4, 2, 0)," in text
    assert "METASPR_ITEM(-14, 4, 4, 0)," in text
    assert "METASPR_TERM" in text


def test_pivot_is_the_bottom_centre_of_the_slice_and_boxes_are_relative_to_it(tmp_path):
    sh = simple(tmp_path)
    sh.slices = [
        {"name": "pivot", "keys": [{"frame": 0, "bounds": {"x": 10, "y": 20, "w": 4, "h": 3}}]},  # -> (12, 22)
        {"name": "hurtbox", "keys": [{"frame": 0, "bounds": {"x": 8, "y": 6, "w": 8, "h": 16}}]},
    ]
    frame = convert(sh, tmp_path).slots[0][0].frames[0]
    assert (frame.hurtbox.x, frame.hurtbox.y, frame.hurtbox.w, frame.hurtbox.h) == (-4, -16, 8, 16)
    assert frame.parts == [(16 - 22, 0 - 12)]


def test_pivot_may_differ_per_frame_with_slice_keys(tmp_path):
    sh = Sheet(5)
    for fr in range(5):
        sh.px(fr, 12, 29)
    all_facings(sh, "idle", frames_per_tag=1)
    sh.slices = [
        {"name": "pivot", "keys": [{"frame": 0, "bounds": {"x": 12, "y": 30, "w": 1, "h": 1}},
                                   {"frame": 2, "bounds": {"x": 14, "y": 30, "w": 1, "h": 1}}]},
        HURT_SLICE,
    ]
    spr = convert(sh, tmp_path)
    assert spr.slots[0][1].frames[0].parts[0][1] == 8 - 12  # frame 1 still uses the key from frame 0
    assert spr.slots[0][2].frames[0].parts[0][1] == 8 - 14  # frame 2 uses the new key


def test_hitbox_only_on_the_hit_frame_and_tag_slice_overrides_generic(tmp_path):
    sh = Sheet(10)
    for fr in range(10):
        sh.px(fr, 12, 29)
    for i, f in enumerate(sprites.FACINGS):
        sh.tag(f"light1_{f}", 2 * i, 2 * i + 1, "dur=1/8 hit=2")
    sh.slices += [
        {"name": "hitbox", "keys": [{"frame": 0, "bounds": {"x": 14, "y": 18, "w": 6, "h": 4}}]},
        {"name": "hitbox:light1_e", "keys": [{"frame": 0, "bounds": {"x": 14, "y": 10, "w": 9, "h": 9}}]},
    ]
    spr = convert(sh, tmp_path)
    s = spr.slots[0][0]  # light1_s
    assert s.hit_frame == 1
    assert s.frames[0].hitbox is None
    assert (s.frames[1].hitbox.x, s.frames[1].hitbox.y, s.frames[1].hitbox.w) == (2, -12, 6)
    e = spr.slots[0][2]
    assert (e.frames[1].hitbox.y, e.frames[1].hitbox.h) == (-20, 9)
    text = sprites.render_sources(spr)["sprite_hero.c"]
    assert "ANIM_NO_HIT" not in text.split("sprite_hero_anim_light1_s")[1].split("\n")[0]


def test_hit_frame_without_a_hitbox_slice_is_an_error(tmp_path):
    sh = Sheet(5)
    for fr in range(5):
        sh.px(fr, 12, 29)
    all_facings(sh, "light1", "dur=1/8 hit=1")
    with pytest.raises(ConvertError, match=r"hero_genplaceholder\.aseprite: tag light1_s frame 1: hit frame has no `hitbox`"):
        convert(sh, tmp_path)


# --- ticks -------------------------------------------------------------------------------------


@pytest.mark.parametrize("dur,total", [("1/8", 24), ("1/4", 48), ("1/2", 96), ("1/16", 12), ("1/12", 16), ("3/8", 72), ("1", 192)])
def test_dur_is_the_whole_tag_in_song_ticks(tmp_path, dur, total):
    sh = Sheet(5)
    for fr in range(5):
        sh.px(fr, 12, 29)
    all_facings(sh, "idle", f"dur={dur}")
    assert convert(sh, tmp_path).slots[0][0].ends == [total]


def test_ends_split_the_total_by_frame_durations_and_the_last_end_is_exact(tmp_path):
    sh = Sheet(3)
    for fr in range(3):
        sh.px(fr, 12, 29)
    sh.durations = [90, 60, 110]  # 260 ms; 24 ticks -> 8.3, 13.8, 24
    sh.tag("idle", 0, 2, "dur=1/8")
    ends = convert(sh, tmp_path).slots[0][0].ends
    assert ends == [8, 14, 24]
    assert ends[-1] == 24


def test_ends_round_to_the_nearest_tick_and_stay_strictly_increasing():
    assert sprites.split_ticks(24, [100, 100, 100], "t", Path("x")) == [8, 16, 24]
    assert sprites.split_ticks(16, [100, 100, 100], "t", Path("x")) == [5, 11, 16]
    assert sprites.split_ticks(12, [100, 100, 100, 100], "t", Path("x")) == [3, 6, 9, 12]


def test_a_frame_that_would_last_zero_ticks_is_an_error():
    with pytest.raises(ConvertError, match=r"tag walk_s frame 2: would last 0 ticks of the tag's 6"):
        sprites.split_ticks(6, [1000, 1, 1000], "walk_s", Path("hero.aseprite"))


def test_dur_that_is_not_a_whole_number_of_ticks_is_an_error(tmp_path):
    sh = Sheet(5)
    for fr in range(5):
        sh.px(fr, 12, 29)
    all_facings(sh, "idle", "dur=1/7")
    with pytest.raises(ConvertError, match=r"tag idle_s: dur=1/7 is not a whole number of song ticks"):
        convert(sh, tmp_path)


def test_missing_dur_and_unknown_user_data_name_the_tag_and_the_fix(tmp_path):
    for data, msg in (("hit=1", r"tag idle_s: no dur=; set the tag's user data to e.g. `dur=1/8`"),
                      ("dur=1/8 hitt=1", r"tag idle_s: unknown user data `hitt=1`"),
                      ("dur=1/8 hit=3", r"tag idle_s: hit=3 but the tag has 1 frame"),
                      ("", r"no dur=")):
        sh = Sheet(5)
        for fr in range(5):
            sh.px(fr, 12, 29)
        all_facings(sh, "idle", data)
        with pytest.raises(ConvertError, match=msg):
            convert(sh, tmp_path)


def test_loop_flag_and_hit_frame_in_the_c(tmp_path):
    sh = Sheet(5)
    for fr in range(5):
        sh.px(fr, 12, 29)
    all_facings(sh, "idle", "dur=1/4 loop")
    text = sprites.render_sources(convert(sh, tmp_path))["sprite_hero.c"]
    assert "sprite_hero_anim_idle_s = { f_idle_s, e_idle_s, 1, ANIM_NO_HIT, ANIM_LOOP };" in text
    assert "static const uint16_t e_idle_s[] = { 48 };" in text


# --- budgets and errors -------------------------------------------------------------------------


def test_too_many_tiles_names_file_tag_frame_budget_and_fix(tmp_path):
    sh = Sheet(5)
    for fr in range(5):
        for x in (1, 9, 17):
            sh.px(fr, x, 1).px(fr, x, 17)  # all six parts: 12 tiles
    all_facings(sh, "idle")
    budgets = dict(BUDGETS, BUDGET_FRAME_TILES=10, BUDGET_PLAYER_OBJS=6)
    with pytest.raises(ConvertError) as e:
        convert(sh, tmp_path, budgets)
    assert str(e.value) == ("hero_genplaceholder.aseprite: tag idle_s frame 1: 12 tiles, budget is 10 "
                            "(BUDGET_FRAME_TILES); trim the frame")


def test_too_many_objs(tmp_path):
    sh = Sheet(5, name="player")
    for fr in range(5):
        for x in (1, 9, 17):
            sh.px(fr, x, 1).px(fr, x, 17)
    all_facings(sh, "idle")
    with pytest.raises(ConvertError, match=r"tag idle_s frame 1: 6 OBJs, budget is 4 \(BUDGET_PLAYER_OBJS\)"):
        convert(sh, tmp_path, dict(BUDGETS, BUDGET_PLAYER_OBJS=4))


def test_canvas_over_budget_and_not_8x16_aligned(tmp_path):
    with pytest.raises(ConvertError, match=r"canvas is 32x32, budget is 24x32 \(BUDGET_PLAYER_W/H\)"):
        convert(simple(tmp_path, w=32, name="player"), tmp_path)
    # non-player characters use the enemy budget
    with pytest.raises(ConvertError, match=r"canvas is 24x32, budget is 16x32 \(BUDGET_ENEMY_W/H\)"):
        convert(simple(tmp_path, w=24, name="goblin"), tmp_path, dict(BUDGETS, BUDGET_ENEMY_W=16))
    with pytest.raises(ConvertError, match=r"canvas is 20x32; width must be a multiple of 8 and height of 16"):
        convert(simple(tmp_path, w=20), tmp_path)
    with pytest.raises(ConvertError, match=r"canvas is 24x24; width must be a multiple of 8 and height of 16"):
        convert(simple(tmp_path, h=24), tmp_path)


def test_palette_index_above_3_names_the_tile(tmp_path):
    sh = simple(tmp_path)
    sh.px(0, 9, 20, 5)  # frame 0 = idle_s, tile (8,16)
    with pytest.raises(ConvertError, match=r"tag idle_s frame 1: tile \(8,16\) uses palette index 5; sprites have 4 shades"):
        convert(sh, tmp_path)


def test_empty_frame_is_an_error(tmp_path):
    sh = simple(tmp_path)
    sh.img.paste(0, (0, 0, 24, 32))  # blank frame 0
    with pytest.raises(ConvertError, match=r"tag idle_s frame 1: the frame is empty"):
        convert(sh, tmp_path)


def test_missing_pivot_and_hurtbox_slices(tmp_path):
    sh = simple(tmp_path)
    sh.slices = [HURT_SLICE]
    with pytest.raises(ConvertError, match=r"tag idle_s frame 1: no `pivot` slice"):
        convert(sh, tmp_path)
    sh.slices = [PIVOT_SLICE]
    with pytest.raises(ConvertError, match=r"tag idle_s frame 1: no `hurtbox` slice"):
        convert(sh, tmp_path)


def test_rgba_sheet_is_accepted_and_too_many_colours_are_not(tmp_path):
    png, js = simple(tmp_path).write(tmp_path)
    rgba = Image.new("RGBA", (120, 32), (0, 0, 0, 0))
    for fr in range(5):
        rgba.putpixel((fr * 24 + 12, 29), (16, 32, 32, 255))
    rgba.save(png)
    spr = sprites.convert(png, js, BUDGETS, 48)
    assert spr.slots[0][0].frames[0].tiles[0:32] != bytes(32)
    for i, c in enumerate([(10, 10, 10), (80, 80, 80), (150, 150, 150), (200, 200, 200), (30, 120, 30)]):
        rgba.putpixel((i, 0), c + (255,))
    rgba.save(png)
    with pytest.raises(ConvertError, match=r"hero_genplaceholder\.aseprite: has 6 colours"):
        sprites.convert(png, js, BUDGETS, 48)


# --- tags: facings, optional, single-facing ------------------------------------------------------


def test_missing_facing_names_the_tag(tmp_path):
    sh = Sheet(4)
    for fr in range(4):
        sh.px(fr, 12, 29)
    for i, f in enumerate(["s", "se", "e", "ne"]):
        sh.tag(f"idle_{f}", i, i)
    with pytest.raises(ConvertError, match=r"missing tag idle_n; draw it, or add the user data `optional`"):
        convert(sh, tmp_path)


def test_optional_action_may_miss_facings_and_those_anims_are_null(tmp_path):
    sh = Sheet(5)
    for fr in range(5):
        sh.px(fr, 12, 29)
    all_facings(sh, "idle")
    sh.tag("lunge_s", 0, 0, "dur=1/8 optional")
    spr = convert(sh, tmp_path)
    row = spr.slots[spr.actions.index("lunge")]
    assert row[0] is not None and row[1:] == [None] * 4
    text = sprites.render_sources(spr)["sprite_hero.c"]
    assert "    0,\n    0,\n    0,\n    0\n};" in text  # the last four table entries are NULL


def test_known_sprite_requires_its_actions_and_lists_optional_ones_in_the_enum(tmp_path):
    sh = Sheet(5, name="dummy", w=16)
    for fr in range(5):
        sh.px(fr, 8, 29)
    all_facings(sh, "idle")
    with pytest.raises(ConvertError, match=r"no tags for action `hurt`; draw hurt_s, hurt_se, hurt_e, hurt_ne, hurt_n"):
        convert(sh, tmp_path)


def test_untagged_facing_means_one_drawing_for_all_five_facings(tmp_path):
    sh = Sheet(2, w=16, name="dummy")
    sh.slices = [{"name": "pivot", "keys": [{"frame": 0, "bounds": {"x": 8, "y": 30, "w": 1, "h": 1}}]},
                 {"name": "hurtbox", "keys": [{"frame": 0, "bounds": {"x": 3, "y": 3, "w": 10, "h": 27}}]}]
    sh.px(0, 8, 20).px(1, 8, 21)
    sh.tag("idle", 0, 0, "dur=1/4 loop").tag("hurt", 1, 1)
    spr = convert(sh, tmp_path)
    assert spr.actions == ["idle", "hurt"]
    assert all(a is spr.slots[0][0] for a in spr.slots[0])
    files = sprites.render_sources(spr)
    text = files["sprite_dummy.c"]
    assert text.count("sprite_dummy_anim_idle,") == 5  # five table entries share one anim
    assert text.count("const sprite_anim_t sprite_dummy_anim_idle") == 1
    assert "SPRITE_DUMMY_HURT," in sprites.render_header(spr)


def test_mirrored_and_unknown_facings_and_odd_names(tmp_path):
    for tag, msg in (("idle_w", r"tag idle_w: W is drawn by flipping E at runtime; delete this tag and draw idle_e"),
                     ("idle_up", r"tag idle_up: unknown facing `up`"),
                     ("Idle_s", r"tag Idle_s: name must be <action>_<facing>")):
        sh = simple(tmp_path)
        sh.tags[0]["name"] = tag
        with pytest.raises(ConvertError, match=msg):
            convert(sh, tmp_path)


def test_mixing_all_facings_tag_and_facing_tags_is_an_error(tmp_path):
    sh = simple(tmp_path)
    sh.tag("idle", 0, 0)
    with pytest.raises(ConvertError, match=r"action idle: mixes `idle` \(all facings\) with per-facing tags"):
        convert(sh, tmp_path)


def test_reverse_tags_are_rejected(tmp_path):
    sh = simple(tmp_path)
    sh.tags[0]["direction"] = "reverse"
    with pytest.raises(ConvertError, match=r"tag idle_s: direction is reverse"):
        convert(sh, tmp_path)


def test_tag_defined_twice_says_which_to_remove(tmp_path):
    sh = simple(tmp_path)
    sh.tag("idle_s", 1, 1)
    with pytest.raises(ConvertError, match=r"hero_genplaceholder\.aseprite: tag idle_s is defined twice; delete or "
                                           r"rename one of the two idle_s tags"):
        convert(sh, tmp_path)


def test_export_without_frames_names_the_export_and_the_fix(tmp_path):
    sh = simple(tmp_path)
    png, js = sh.write(tmp_path)
    doc = json.loads(js.read_text())
    doc["frames"] = []
    js.write_text(json.dumps(doc))
    with pytest.raises(ConvertError, match=r"hero_genplaceholder\.aseprite: the export hero_genplaceholder\.json has "
                                           r"no frames; draw at least one frame in Aseprite, then run make with "
                                           r"Aseprite installed"):
        sprites.convert(png, js, BUDGETS, 48)


def test_box_too_far_from_the_pivot_says_how_far_and_what_to_move(tmp_path):
    sh = simple(tmp_path)
    sh.slices = [PIVOT_SLICE, {"name": "hurtbox", "keys": [{"frame": 0, "bounds": {"x": -200, "y": 5, "w": 8, "h": 9}}]}]
    with pytest.raises(ConvertError, match=r"tag idle_s frame 1: hurtbox at \(-200,5\) 8x9 is too far from the pivot "
                                           r"\(12,30\): its top-left corner is -212,-25 px away and must be within "
                                           r"-128\.\.127; move the `hurtbox` slice \(or the pivot\) closer"):
        convert(sh, tmp_path)


def test_box_too_big_says_to_resize_the_slice(tmp_path):
    sh = simple(tmp_path)
    sh.slices = [PIVOT_SLICE, {"name": "hurtbox", "keys": [{"frame": 0, "bounds": {"x": 0, "y": 0, "w": 300, "h": 9}}]}]
    with pytest.raises(ConvertError, match=r"tag idle_s frame 1: hurtbox at \(0,0\) is 300x9; a box is 1-255 px each "
                                           r"way, so resize the `hurtbox` slice"):
        convert(sh, tmp_path)


def test_pivot_too_far_from_the_art_says_to_move_the_pivot(tmp_path):
    sh = simple(tmp_path)
    sh.slices = [{"name": "pivot", "keys": [{"frame": 0, "bounds": {"x": 200, "y": 30, "w": 1, "h": 1}}]},
                 {"name": "hurtbox", "keys": [{"frame": 0, "bounds": {"x": 190, "y": 5, "w": 8, "h": 9}}]}]
    with pytest.raises(ConvertError, match=r"tag idle_s frame 1: pivot \(200,30\) is too far from the art \(the 8x16 "
                                           r"part at \(0,16\) is -200,-14 px away; at most 127 each way\); move the "
                                           r"`pivot` slice to the character's feet"):
        convert(sh, tmp_path)


def test_bad_sprite_name_suggests_a_file_name(tmp_path):
    png, js = simple(tmp_path).write(tmp_path)
    with pytest.raises(ConvertError, match=r"sprite name `Big-Hero` must be lowercase letters, digits and "
                                           r"underscores; rename the file, e.g. big_hero\.aseprite"):
        sprites.convert(png, js, BUDGETS, 48, name="Big-Hero")


def test_unknown_user_data_and_odd_tag_names_say_what_to_change(tmp_path):
    sh = simple(tmp_path)
    sh.tags[0]["data"] = "dur=1/8 fast"
    with pytest.raises(ConvertError, match=r"tag idle_s: unknown user data `fast`; remove it from the tag's user data"):
        convert(sh, tmp_path)
    sh = simple(tmp_path)
    sh.tags[0]["name"] = "Idle_s"
    with pytest.raises(ConvertError, match=r"facing one of s se e ne n; rename the tag, e.g. idle_s"):
        convert(sh, tmp_path)


def test_overlong_dur_says_to_shorten_it(tmp_path):
    sh = simple(tmp_path)
    sh.tags[0]["data"] = "dur=400"
    with pytest.raises(ConvertError, match=r"tag idle_s: dur=400/1 is 76800 ticks; the maximum is 65535, so shorten dur"):
        convert(sh, tmp_path)


def test_main_explains_a_json_that_is_not_an_aseprite_export(tmp_path, capsys):
    png, js = simple(tmp_path).write(tmp_path)
    js.write_text("{}")
    assert sprites.main([str(png), str(js), str(tmp_path / "gen")]) == 1
    err = capsys.readouterr().err
    assert f"{js}: missing 'frames': not an Aseprite --format json-array export" in err
    assert "run make with Aseprite installed and commit exports/" in err


# --- C output ------------------------------------------------------------------------------------


def test_header_has_enum_bankref_and_sprite_t(tmp_path):
    sh = simple(tmp_path)
    h = sprites.render_header(convert(sh, tmp_path))
    assert "SPRITE_HERO_IDLE," in h and "SPRITE_HERO_ACTION_COUNT" in h
    assert "BANKREF_EXTERN(sprite_hero)" in h
    assert "extern const sprite_t sprite_hero;" in h
    assert '#include "gb/spritedata.h"' in h


def test_sources_are_banked_and_record_their_bank(tmp_path):
    spr = convert(simple(tmp_path), tmp_path)
    files = sprites.render_sources(spr)
    assert sorted(files) == ["sprite_hero.c", "spritebank_hero_1.c", "spritebank_hero_2.c", "spritebank_hero_3.c"]
    c = files["sprite_hero.c"]
    assert "#pragma bank 255" in c
    assert "BANKREF(sprite_hero)" in c
    assert "const sprite_t sprite_hero = { anim_table, SPRITE_HERO_ACTION_COUNT, BANK(sprite_hero) };" in c
    assert "{ BANK(sprite_hero) }," in c
    for k in (1, 2, 3):
        assert "#pragma bank 255" in files[f"spritebank_hero_{k}.c"]


def test_identical_tiles_and_metasprites_are_shared_within_a_bank(tmp_path):
    spr = convert(simple(tmp_path), tmp_path)  # five frames, identical art
    c = sprites.render_sources(spr)["sprite_hero.c"]
    assert c.count("static const uint8_t t") == 1
    assert c.count("static const metasprite_t p") == 1


def test_large_sprites_spill_into_more_banks_and_the_bank_table_follows(tmp_path, monkeypatch):
    monkeypatch.setattr(sprites, "BANK_CAP", 400)
    sh = Sheet(5)
    for fr in range(5):
        sh.px(fr, 1 + fr, 1).px(fr, 9, 17)  # distinct tiles per frame, 2 parts each (~100 bytes per anim)
    all_facings(sh, "idle")
    spr = convert(sh, tmp_path)
    where = sprites.assign_banks(spr)
    assert sorted(set(where.values())) == [0, 1]
    files = sprites.render_sources(spr)
    c0, c1 = files["sprite_hero.c"], files["spritebank_hero_1.c"]
    for tag, bank in where.items():
        here, there = (c0, c1) if bank == 0 else (c1, c0)
        assert f"const sprite_anim_t sprite_hero_anim_{tag} =" in here
        assert f"const sprite_anim_t sprite_hero_anim_{tag} =" not in there
    assert "BANKREF(sprite_hero_b1)" in c1
    assert "BANKREF_EXTERN(sprite_hero_b1)" in c0
    assert "{ BANK(sprite_hero_b1) }" in c0
    assert "extern const sprite_anim_t sprite_hero_anim_idle_n;" in c0


def test_a_sprite_that_fits_no_bank_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(sprites, "BANK_CAP", 50)
    with pytest.raises(ConvertError, match=r"tag idle_s: its data is ~\d+ bytes, more than one ROM bank holds"):
        sprites.render_sources(convert(simple(tmp_path), tmp_path))


# --- command line --------------------------------------------------------------------------------


def test_budgets_h_is_parsed():
    b = sprites.read_defines(REPO / "src/core/budgets.h", "BUDGET_")
    assert b["BUDGET_PLAYER_W"] == 24 and b["BUDGET_FRAME_TILES"] == 12 and b["BUDGET_PLAYER_OBJS"] == 6
    assert sprites.read_defines(REPO / "src/core/beat.h", "BEAT_TICKS") == {"BEAT_TICKS": 48}


def test_main_writes_header_first_and_all_files(tmp_path):
    png, js = simple(tmp_path).write(tmp_path)
    out = tmp_path / "gen"
    budgets = tmp_path / "budgets.h"
    budgets.write_text("".join(f"#define {k} {v}\n" for k, v in BUDGETS.items()))
    assert sprites.main([str(png), str(js), str(out), "--budgets", str(budgets)]) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "sprite_hero.c", "sprite_hero.h", "spritebank_hero_1.c", "spritebank_hero_2.c", "spritebank_hero_3.c"]
    header = (out / "sprite_hero.h").stat().st_mtime_ns
    assert all((out / n).stat().st_mtime_ns >= header for n in ("sprite_hero.c", "spritebank_hero_1.c"))


def test_main_reports_errors_on_stderr_with_exit_1(tmp_path, capsys):
    sh = simple(tmp_path, w=32)
    png, js = sh.write(tmp_path)
    assert sprites.main([str(png), str(js), str(tmp_path / "gen")]) == 1  # 32 px wide: over the real budget
    assert "hero_genplaceholder.aseprite: canvas is 32x32" in capsys.readouterr().err
    assert not (tmp_path / "gen" / "sprite_hero.h").exists()


def test_unreadable_export_points_at_the_export_step(tmp_path):
    with pytest.raises(ConvertError, match="run make with Aseprite installed and commit exports/"):
        sprites.convert(tmp_path / "nope.png", tmp_path / "nope.json", BUDGETS, 48)


# --- the committed placeholder exports ----------------------------------------------------------


@pytest.mark.parametrize("stem,tags,max_frames", [("player_genplaceholder", 60, 4), ("dummy_genplaceholder", 2, 2)])
def test_committed_placeholders_convert_within_budget(stem, tags, max_frames):
    budgets = sprites.read_defines(REPO / "src/core/budgets.h", "BUDGET_")
    spr = sprites.convert(REPO / f"exports/sprites/{stem}.png", REPO / f"exports/sprites/{stem}.json", budgets, 48)
    anims = sprites.unique_anims(spr)
    assert len(anims) == tags
    assert all(2 <= len(a.frames) <= max_frames for a in anims)
    assert all(len(f.parts) * 2 <= budgets["BUDGET_FRAME_TILES"] for a in anims for f in a.frames)
    assert all(a.ends[-1] in (24, 48, 96) for a in anims)
    sprites.render_header(spr)
    sprites.render_sources(spr)


def test_player_placeholder_has_every_action_and_facing_and_marked_attacks():
    budgets = sprites.read_defines(REPO / "src/core/budgets.h", "BUDGET_")
    stem = "player_genplaceholder"
    spr = sprites.convert(REPO / f"exports/sprites/{stem}.png", REPO / f"exports/sprites/{stem}.json", budgets, 48)
    assert spr.actions == ["idle", "walk", "dodge", "hurt", "light1", "light2", "light3", "light4", "finisher",
                           "heavy1", "heavy2", "lunge"]
    assert all(a is not None for row in spr.slots for a in row)
    attacks = {a: spr.slots[spr.actions.index(a)][0] for a in spr.actions}
    assert attacks["idle"].loop and attacks["walk"].loop and not attacks["light1"].loop
    for a in ("light1", "light2", "light3", "light4", "finisher", "heavy1", "heavy2", "lunge"):
        anim = attacks[a]
        assert anim.hit_frame is not None and anim.frames[anim.hit_frame].hitbox is not None
    for a in ("idle", "walk", "dodge", "hurt"):
        assert attacks[a].hit_frame is None
