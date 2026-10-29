"""Lab descriptors, TOML saving, replay files, press-log reading: everything that needs no ROM."""

import json
from pathlib import Path

import pytest

from gbtools.errors import ConvertError
from lab.descriptor import Field, load_table, load_tables
from lab.replay import (
    BUTTONS, Player, PressLogReader, Press, Recorder, Replay, compare, load_replay, mask_to_names,
)
from lab.tomlio import save_values

REPO = Path(__file__).resolve().parents[2]


def descriptor(tmp_path, fields, name="demo.lab.json", **extra) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({"source": "data/demo.toml", "symbol": "_demo", "fields": fields, **extra}))
    return p


def fld(path=("a", "b"), **kw):
    return {"path": list(path), "offset": 0, "type": "u8", "default": 1, "min": 0, "max": 9, "doc": "d", **kw}


# ---- loading and validating ----------------------------------------------------------------------
def test_loads_every_type_and_nested_path(tmp_path):
    p = descriptor(tmp_path, [
        fld(("string", 0, "steps", 1), offset=3, type="i8", default=-1, min=-5, max=5),
        fld(("w",), offset=4, type="u16", default=300, min=0, max=60000, restart=True),
        fld(("v",), offset=6, type="i16", default=-300, min=-1000, max=1000),
        fld(("kind",), offset=8, type="enum", default="PULSE", min=0, max=3, values={"SWEEP": 1, "PULSE": 2}),
    ])
    t = load_table(p)
    assert (t.name, t.source, t.symbol) == ("demo", "data/demo.toml", "_demo")
    steps, w, v, kind = t.fields
    assert steps.path == ("string", 0, "steps", 1) and steps.id == "demo:string.0.steps.1"
    assert w.restart and not steps.restart
    assert kind.default == 2  # enum default given by name
    assert [f.size for f in t.fields] == [1, 2, 2, 1]


def test_codec_little_endian_and_ranges(tmp_path):
    t = load_table(descriptor(tmp_path, [
        fld(("i",), type="i16", default=0, min=-1000, max=1000),
        fld(("u",), type="u16", default=0, min=0, max=60000),
        fld(("s",), type="i8", default=0, min=-100, max=100),
        fld(("e",), type="enum", default=1, min=0, max=3, values={"A": 1, "B": 2}),
    ]))
    i, u, s, e = t.fields
    assert i.encode(-2) == b"\xfe\xff" and i.decode(b"\xfe\xff") == -2
    assert u.encode(0x1234) == b"\x34\x12" and u.decode(b"\x34\x12") == 0x1234
    assert s.encode(-1) == b"\xff" and s.decode(b"\xff") == -1
    assert e.encode(2) == b"\x02" and e.toml_value(2) == "B"
    for field, bad in ((i, 1001), (u, -1), (s, 101)):
        with pytest.raises(ValueError, match="outside its range"):
            field.encode(bad)
    with pytest.raises(ValueError, match="not one of"):
        e.encode(3)
    with pytest.raises(ValueError, match="not an integer"):
        i.encode("3")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "fields, extra, message",
    [
        ([fld(type="f32")], {}, "type 'f32' must be one of i8, u8, i16, u16, enum"),
        ([fld(default=99)], {}, "default 99 is outside its range"),
        ([fld(min=5, max=1)], {}, "must satisfy min <= max"),
        ([fld(type="u8", max=300)], {}, "fit in u8"),
        ([fld(type="i8", min=-200)], {}, "fit in i8"),
        ([fld(type="enum")], {}, "enum fields need a non-empty 'values'"),
        ([fld(values={"A": 1})], {}, "'values' is only valid on enum fields"),
        ([fld(), fld()], {}, "appears twice"),
        ([fld(path=[])], {}, "non-empty list"),
        ([{"path": ["a"], "offset": 0}], {}, "missing 'type'"),
        ([fld(offset=-1)], {}, "'offset' must not be negative"),
        ([fld(offset="x")], {}, "must be integers"),
    ],
)
def test_descriptor_errors_name_file_and_field(tmp_path, fields, extra, message):
    p = descriptor(tmp_path, fields, **extra)
    with pytest.raises(ConvertError) as e:
        load_table(p)
    assert str(p) in str(e.value) and message in str(e.value)


def test_descriptor_needs_source_symbol_and_fields(tmp_path):
    p = tmp_path / "x.lab.json"
    p.write_text('{"source": "a.toml", "fields": []}')
    with pytest.raises(ConvertError, match="missing 'symbol'"):
        load_table(p)
    p.write_text("{nope")
    with pytest.raises(ConvertError, match="invalid JSON"):
        load_table(p)


def test_load_tables_puts_tuning_first(tmp_path):
    for n in ("sfx", "combos", "tuning"):
        descriptor(tmp_path, [fld()], name=f"{n}.lab.json")
    assert [t.name for t in load_tables(tmp_path)] == ["tuning", "combos", "sfx"]


# ---- saving back to TOML -------------------------------------------------------------------------
TOML = """# header comment
[timing]
perfect_window = 3   # [0..10] +/- frames that grade PERFECT
latency_offset = 0   # [-15..15] frames subtracted

# combo strings
[[string]]
kind = "SWEEP"  # how it moves
steps = [1, 2, 3]  # slots

[[string]]
kind = "PULSE"
steps = [4, 5]
"""


def test_save_changes_only_edited_values_and_keeps_comments(tmp_path):
    f = tmp_path / "t.toml"
    f.write_text(TOML)
    pw = Field("t:timing.perfect_window", ("timing", "perfect_window"), 0, "i16", 3, 0, 10)
    lat = Field("t:timing.latency_offset", ("timing", "latency_offset"), 2, "i16", 0, -15, 15)
    assert save_values(f, [(pw, 3), (lat, -12)]) == 1  # perfect_window unchanged
    new = f.read_text()
    old_lines, new_lines = TOML.splitlines(), new.splitlines()
    diff = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
    assert len(old_lines) == len(new_lines) and len(diff) == 1
    assert diff[0][1].startswith("latency_offset = -12") and "# [-15..15] frames subtracted" in diff[0][1]
    assert new.startswith("# header comment") and "# combo strings" in new


def test_save_keeps_the_comment_column_when_it_fits(tmp_path):
    f = tmp_path / "t.toml"
    f.write_text(TOML)
    pw = Field("t:p", ("timing", "perfect_window"), 0, "i16", 3, 0, 10)
    save_values(f, [(pw, 10)])
    line = next(ln for ln in f.read_text().splitlines() if ln.startswith("perfect_window"))
    assert line.index("#") == TOML.splitlines()[2].index("#")


def test_save_nested_paths_arrays_of_tables_and_enum_names(tmp_path):
    f = tmp_path / "t.toml"
    f.write_text(TOML)
    step = Field("t:s", ("string", 1, "steps", 0), 0, "u8", 4, 0, 9)
    kind = Field("t:k", ("string", 0, "kind"), 0, "enum", 1, 0, 3, values={"SWEEP": 1, "PULSE": 2})
    assert save_values(f, [(step, 9), (kind, 2)]) == 2
    new = f.read_text()
    assert 'kind = "PULSE"  # how it moves' in new and "steps = [9, 5]" in new
    assert "steps = [1, 2, 3]  # slots" in new  # the other string is untouched


def test_enum_fields_take_their_range_from_values(tmp_path):
    f = {"path": ["s"], "offset": 0, "type": "enum", "default": "B", "values": {"-": 0, "A": 1, "B": 2}}
    (field,) = load_table(descriptor(tmp_path, [f])).fields
    assert (field.min, field.max, field.default) == (0, 2, 2)


def test_save_adds_absent_slots_padding_arrays_with_the_default(tmp_path):
    src = tmp_path / "combos.toml"
    src.write_text('[[string]]\nname = "rush"  # keep\nsteps = ["A", "A"]\n')
    values = {"-": 0, "A": 1, "B": 2}
    t = load_table(descriptor(tmp_path, [
        {"path": ["string", 0, "steps", 3], "offset": 3, "type": "enum", "default": "-",
         "values": values, "absent": True},
        {"path": ["string", 0, "steps", 4], "offset": 4, "type": "enum", "default": "-",
         "values": values, "absent": True},
        {"path": ["string", 0, "sfx"], "offset": 9, "type": "u8", "default": 0, "min": 0, "max": 9,
         "absent": True},
    ]))
    step3, step4, sfx = t.fields
    assert save_values(src, [(step3, 2), (step4, 0), (sfx, 3)]) == 2
    text = src.read_text()
    assert 'steps = ["A", "A", "-", "B"]' in text
    assert "sfx = 3" in text and "# keep" in text


def test_save_errors_name_file_and_field(tmp_path):
    f = tmp_path / "t.toml"
    f.write_text(TOML)
    bad = Field("t:g", ("nope", "x"), 0, "u8", 0, 0, 9)
    with pytest.raises(ConvertError, match=r"t\.toml: no \[nope\.x\]: 'nope' not found"):
        save_values(f, [(bad, 1)])
    assert f.read_text() == TOML  # nothing half-written
    ghost = Field("t:g", ("timing", "ghost"), 0, "u8", 0, 0, 9)
    assert save_values(f, [(ghost, 0)]) == 0  # a key the file leaves out, still at its default: nothing to do
    assert save_values(f, [(ghost, 1)]) == 1 and "ghost = 1" in f.read_text()  # changed: added
    with pytest.raises(ConvertError, match="cannot read"):
        save_values(tmp_path / "missing.toml", [(ghost, 1)])


def test_save_repo_tuning_roundtrip_changes_one_line(tmp_path):
    src = (REPO / "data/tuning.toml").read_text()
    f = tmp_path / "tuning.toml"
    f.write_text(src)
    t = load_table(_repo_descriptor(tmp_path))
    lat = t.find(("timing", "latency_offset"))
    save_values(f, [(lat, 4)])
    changed = [(a, b) for a, b in zip(src.splitlines(), f.read_text().splitlines()) if a != b]
    assert len(changed) == 1 and changed[0][1].startswith("latency_offset = 4")


def _repo_descriptor(tmp_path) -> Path:
    from gbtools import tuning

    out = tmp_path / "gen"
    assert tuning.main([str(REPO / "data/tuning.toml"), str(out)]) == 0
    return out / "tuning.lab.json"


def test_repo_descriptor_loads_and_every_field_has_a_slider_range(tmp_path):
    t = load_table(_repo_descriptor(tmp_path))
    assert t.symbol == "_tuning" and len(t.fields) >= 15
    assert t.find(("timing", "perfect_window")).max == 10


# ---- replay files --------------------------------------------------------------------------------
def sample_replay() -> Replay:
    return Replay(
        frames=100,
        inputs=[(10, frozenset({"a"})), (14, frozenset())],
        pokes=[],
        rom_name="beatarpg-debug.gbc",
        expect_presses=[Press(11, BUTTONS["a"], 2, -1)],
        expect_screen_sha1="ab" * 20,
    )


def test_replay_roundtrip(tmp_path):
    rec = Recorder()
    rec.poke(0, "_tuning", 6, "i16", -2, ("timing", "latency_offset"))
    r = sample_replay()
    r.pokes = rec.pokes
    p = tmp_path / "r.json"
    r.save(p)
    doc = json.loads(p.read_text())
    assert doc["format"] == "beatarpg-replay" and doc["version"] == 1 and doc["warmup_frames"] == 120
    assert doc["inputs"] == [{"f": 10, "held": ["a"]}, {"f": 14, "held": []}]
    assert doc["expect"]["presses"] == [{"f": 11, "buttons": ["a"], "grade": "PERFECT", "frames": -1}]
    back = load_replay(p)
    assert (back.frames, back.inputs, back.pokes, back.expect_presses) == (r.frames, r.inputs, r.pokes, r.expect_presses)
    assert back.expect_screen_sha1 == r.expect_screen_sha1


def test_recorder_stores_only_changes():
    rec = Recorder()
    for f, held in enumerate([[], [], ["a"], ["a"], ["a", "right"], [], []]):
        rec.held(f, held)
    assert rec.inputs == [(2, frozenset({"a"})), (4, frozenset({"a", "right"})), (5, frozenset())]


def bad_replay(tmp_path, **patch) -> Path:
    doc = sample_replay().to_json()
    doc.update(patch)
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(doc))
    return p


@pytest.mark.parametrize(
    "patch, message",
    [
        ({"format": "x"}, "not a replay file"),
        ({"version": 99}, "version 99 is not supported"),
        ({"frames": 0}, "'frames' must be a positive integer"),
        ({"model": "gba"}, "'model' is 'gba'"),
        ({"inputs": [{"f": 5, "held": ["x"]}]}, "unknown button 'x'"),
        ({"inputs": [{"f": 5, "held": []}, {"f": 5, "held": []}]}, "must be increasing"),
        ({"inputs": [{"f": 100, "held": []}]}, "below 'frames'"),
        ({"inputs": [{"f": 1}]}, "inputs[0] must look like"),
        ({"pokes": [{"f": 0}]}, "pokes[0] needs"),
        ({"expect": {"presses": [{"f": 1}]}}, "expect.presses[0] must look like"),
        ({"warmup_frames": -1}, "'warmup_frames'"),
    ],
)
def test_replay_errors_name_file_and_fix(tmp_path, patch, message):
    p = bad_replay(tmp_path, **patch)
    with pytest.raises(ConvertError) as e:
        load_replay(p)
    assert str(p) in str(e.value) and message in str(e.value)


def test_replay_file_that_is_not_json(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("{")
    with pytest.raises(ConvertError, match="cannot read replay"):
        load_replay(p)


def test_compare_reports_the_first_differences():
    want = [Press(5, 16, 2, 0), Press(9, 16, 1, 3)]
    r = Replay(frames=10, expect_presses=want, expect_screen_sha1="x")
    assert compare(r, want, "x") == []
    out = compare(r, [Press(5, 16, 2, 0), Press(9, 16, 0, 5)], "y")
    assert "press #1" in out[0] and "GOOD +3" in out[0] and "OFFBEAT +5" in out[0]
    assert "final screen" in out[1]
    assert "got none" in compare(r, want[:1], "x")[0]


def test_mask_names_cover_every_button():
    assert mask_to_names(0xFF) == list(BUTTONS)


# ---- driving a machine / reading the press log (fake memory) --------------------------------------
class FakeMem:
    def __init__(self):
        self.b = bytearray(0x10000)

    def read(self, a, n):
        return bytes(self.b[a : a + n])

    def write(self, a, data):
        self.b[a : a + len(data)] = data


def test_player_applies_pokes_and_input_edges_on_the_right_frames():
    mem, events = FakeMem(), []
    r = Replay(
        frames=20,
        inputs=[(3, frozenset({"a"})), (5, frozenset({"a", "up"})), (8, frozenset())],
        pokes=[],
    )
    rec = Recorder()
    rec.poke(2, "_tuning", 4, "i16", -300, ("x",))
    r.pokes = rec.pokes
    pl = Player(r, {"_tuning": 0xC100}, lambda n: events.append(("+", n)), lambda n: events.append(("-", n)), mem.write)
    log = {}
    for f in range(12):
        pl.before_tick(f)
        log[f] = (tuple(sorted(pl.held)), mem.read(0xC104, 2))
    assert log[1][1] == b"\x00\x00" and log[2][1] == (-300).to_bytes(2, "little", signed=True)  # poke lands at f=2
    assert [e for e in events if e[0] == "+"] == [("+", "a"), ("+", "up")]
    assert sorted(e for e in events if e[0] == "-") == [("-", "a"), ("-", "up")]
    assert log[4][0] == ("a",) and log[5][0] == ("a", "up") and log[8][0] == ()


def test_player_rejects_an_unknown_symbol():
    rec = Recorder()
    rec.poke(0, "_gone", 0, "u8", 1)
    r = Replay(frames=5, pokes=rec.pokes, rom_name="x.gbc")
    with pytest.raises(ConvertError, match="'_gone' is not in the ROM's .noi"):
        Player(r, {}, print, print, print)


def test_press_log_reader_handles_wrap_and_overrun():
    mem = FakeMem()
    syms = {"_press_log": 0xC200, "_press_log_head": 0xC240}
    rd = PressLogReader(syms, mem.read)

    def put(head, frame, buttons, grade, err):
        slot = head & 15
        mem.b[0xC200 + slot * 4 : 0xC204 + slot * 4] = bytes([frame, buttons, grade, err & 0xFF])
        mem.b[0xC240] = (head + 1) & 0xFF

    put(0, 10, 0x10, 2, -3)
    assert rd.poll(7) == [Press(7, 0x10, 2, -3)]
    assert rd.poll(8) == []
    put(1, 20, 0x20, 1, 4)
    put(2, 21, 0x10, 0, 0)
    assert [(p.grade, p.frames) for p in rd.poll(9)] == [(1, 4), (0, 0)]
    # head wraps past 255 and the ring overruns: only the newest 16 survive
    mem.b[0xC240] = 250
    rd.last = 250
    for h in range(250, 250 + 20):
        put(h, h & 0xFF, 0x10, 2, 1)
    got = rd.poll(1)
    assert len(got) == 16 and rd.last == (250 + 20) & 0xFF


def test_press_log_reader_without_symbols_is_empty():
    rd = PressLogReader({}, FakeMem().read)
    assert not rd.available and rd.poll(0) == []


# ---- descriptor extensions: source, none, step, array_length, layout (ADR 0008) -----------------
import shutil  # noqa: E402

from gbtools import sfx  # noqa: E402
from lab.descriptor import synthesize  # noqa: E402


def test_fields_of_different_sources_may_share_a_path(tmp_path):
    p = descriptor(tmp_path, [
        fld(("priority",), source="assets/sfx/a.toml"),
        fld(("priority",), source="assets/sfx/b.toml", offset=4),
    ])
    a, b = load_table(p).fields
    assert (a.source, b.source) == ("assets/sfx/a.toml", "assets/sfx/b.toml")
    assert a.id != b.id and a.id == "demo:assets/sfx/a.toml:priority"


def test_same_source_and_path_twice_is_an_error(tmp_path):
    p = descriptor(tmp_path, [fld(source="x.toml"), fld(source="x.toml", offset=1)])
    with pytest.raises(ConvertError, match="appears twice"):
        load_table(p)
    p = descriptor(tmp_path, [fld(), fld(offset=1)])  # no per-field source: hint at adding one
    with pytest.raises(ConvertError, match="need their own 'source'"):
        load_table(p)


def test_fields_without_a_source_use_the_tables_and_keep_the_plain_id(tmp_path):
    (f,) = load_table(descriptor(tmp_path, [fld()])).fields
    assert f.source == "data/demo.toml" and f.id == "demo:a.b"


def test_none_sentinel_is_writable_and_validated(tmp_path):
    t = load_table(descriptor(tmp_path, [
        fld(("p",), type="u16", default=65535, min=0, max=2047, none=65535),
        fld(("q",), default=3, min=0, max=15, none=255, step=8),
    ]))
    p, q = t.fields
    assert p.encode(65535) == b"\xff\xff" and p.decode(b"\xff\xff") == 65535 and p.default == p.none
    assert q.encode(255) == b"\xff" and q.encode(3) == b"\x03" and q.step == 8
    with pytest.raises(ValueError, match="outside its range"):
        q.encode(100)  # the sentinel is the only value outside the range


@pytest.mark.parametrize(
    "field, message",
    [
        (fld(none=5), "'none' = 5 must lie outside the range [0..9]"),
        (fld(none=300), "fit in u8"),
        (fld(none=True), "'none' must be an integer"),
        (fld(type="enum", values={"A": 1}, none=255), "not valid on enum fields"),
        (fld(step=0), "'step' must be a positive integer"),
        (fld(array_length=True, path=["step", 0]), "'array_length' belongs on a numeric field"),
        (fld(source=""), "'source' must be the path"),
    ],
)
def test_extension_errors_name_file_and_field(tmp_path, field, message):
    p = descriptor(tmp_path, [field])
    with pytest.raises(ConvertError) as e:
        load_table(p)
    assert str(p) in str(e.value) and message in str(e.value)


def test_layout_must_be_an_object_and_is_kept(tmp_path):
    assert load_table(descriptor(tmp_path, [fld()], layout={"effect_size": 196})).layout == {"effect_size": 196}
    with pytest.raises(ConvertError, match="'layout' must be an object"):
        load_table(descriptor(tmp_path, [fld()], layout=[1]))


def steps_descriptor(tmp_path, count=1, layout=True):
    fields = [{"source": "a.toml", "path": ["step"], "offset": 2, "type": "u8", "default": count, "min": 1,
               "max": 4, "array_length": True}]
    for n in range(count):
        base = 4 + 6 * n
        fields += [
            {"source": "a.toml", "path": ["step", n, "frames"], "offset": base, "type": "u8", "default": 2,
             "min": 1, "max": 255},
            {"source": "a.toml", "path": ["step", n, "volume"], "offset": base + 1, "type": "u8", "default": 15,
             "min": 0, "max": 15, "none": 255},
        ]
    return load_table(descriptor(tmp_path, fields, **({"layout": {"step_size": 6}} if layout else {})))


def test_slots_past_the_listed_steps_are_synthesised_from_step_zero(tmp_path):
    t = steps_descriptor(tmp_path, count=1)
    synth = [f for f in t.fields if f.synth]
    assert [f.path for f in synth] == [("step", n, k) for n in (1, 2, 3) for k in ("frames", "volume")]
    frames, volume = synth[0], synth[1]
    assert (frames.offset, volume.offset, synth[2].offset) == (10, 11, 16)  # the layout's step_size stride
    assert (frames.default, volume.default, volume.none) == (1, 255, 255) and frames.absent and volume.absent
    assert frames.id == "demo:a.toml:step.1.frames"


def test_no_synthesis_without_a_step_size_or_when_all_slots_are_listed(tmp_path):
    assert not any(f.synth for f in steps_descriptor(tmp_path, count=1, layout=False).fields)
    assert not any(f.synth for f in steps_descriptor(tmp_path, count=4).fields)
    t = steps_descriptor(tmp_path, count=2)
    synthesize(t)  # idempotent: nothing left to add
    assert len([f for f in t.fields if f.synth]) == 4


# ---- saving: none, array_length, pitch ------------------------------------------------------------
EFFECT = """channel = "P1"
priority = 5

[[step]]  # the sting
frames = 2
volume = 15
duty = 1
pitch = "A4"  # a note name
sweep_pace = 2

[[step]]
frames = 3
pitch = 900
duty = 3
"""
SFX_SRC = Path(__file__).resolve().parents[2] / "assets/sfx"


def sfx_fields(tmp_path, effect_text=EFFECT, name="demo"):
    """The real converter's descriptor for one effect file, and the file."""
    f = tmp_path / f"{name}.toml"
    f.write_text(effect_text)
    sfx.main([str(tmp_path / "gen"), str(f)])
    # the converter records the source as given on its command line
    return f, load_table(tmp_path / "gen/sfx.lab.json")


def edit(t, f, **by_path):
    """[(field, value)] from {"step.1.duty": 2, ...}."""
    return [(next(x for x in t.fields if x.label == k.replace("__", ".")), v) for k, v in by_path.items()]


def test_unset_deletes_the_key_and_a_real_value_adds_it_back(tmp_path):
    f, t = sfx_fields(tmp_path)
    duty = t.find(("step", 1, "duty"))
    assert save_values(f, [(duty, duty.none)]) == 1
    assert "duty = 3" not in f.read_text() and f.read_text().count("duty") == 1  # step 0's stays
    assert save_values(f, [(duty, duty.none)]) == 0  # already unset: nothing to do
    assert save_values(f, [(duty, 2)]) == 1
    assert f.read_text().rstrip().endswith("duty = 2")
    sfx.load_effect(f)  # still a valid effect


def test_pitch_saves_as_a_number_even_where_the_file_had_a_note_name(tmp_path):
    f, t = sfx_fields(tmp_path)
    pitch = t.find(("step", 0, "pitch"))
    assert save_values(f, [(pitch, 1800)]) == 1
    assert "pitch = 1800  # a note name" in f.read_text()  # the comment survives


def test_raising_the_step_count_appends_empty_step_tables(tmp_path):
    f, t = sfx_fields(tmp_path)
    count = t.find(("step",))
    assert count.array_length and count.default == 2
    assert save_values(f, [(count, 4)]) == 1
    assert f.read_text().count("[[step]]") == 4
    assert len(sfx.load_effect(f).steps) == 4  # empty steps are valid: they play 1 frame and change nothing


def test_new_steps_get_the_keys_the_author_set_and_only_those(tmp_path):
    f, t = sfx_fields(tmp_path)
    by = {x.label: x for x in t.fields}
    assert by["step.2.frames"].synth and by["step.2.frames"].absent
    edits = [(by["step"], 4), (by["step.2.frames"], 6), (by["step.2.volume"], 9), (by["step.2.env_pace"], 3),
             (by["step.2.pitch"], 1000), (by["step.3.frames"], by["step.3.frames"].default)]
    assert save_values(f, edits, validate=sfx.load_effect) == 5
    text = f.read_text()
    assert text.count("[[step]]") == 4
    e = sfx.load_effect(f)
    assert len(e.steps) == 4
    assert e.steps[2][:2] == bytes([6, 9]) and e.steps[2][3] == 3  # frames, volume, env_pace
    assert e.steps[3][0] == 1  # step 4 kept the empty-step default


def test_lowering_the_step_count_drops_the_tail_and_ignores_its_edits(tmp_path):
    f, t = sfx_fields(tmp_path)
    by = {x.label: x for x in t.fields}
    assert save_values(f, [(by["step"], 1), (by["step.1.duty"], 0)]) == 1
    assert f.read_text().count("[[step]]") == 1 and "duty = 3" not in f.read_text()
    sfx.load_effect(f)


def test_an_edit_in_an_element_the_file_lacks_is_an_error_unless_untouched(tmp_path):
    f, t = sfx_fields(tmp_path)
    by = {x.label: x for x in t.fields}
    frames = by["step.2.frames"]
    assert save_values(f, [(frames, frames.default)]) == 0  # untouched: fine
    with pytest.raises(ConvertError, match="raise the count that covers it"):
        save_values(f, [(frames, 5)])


def test_save_refuses_a_file_the_converter_would_reject(tmp_path):
    f, t = sfx_fields(tmp_path)
    before = f.read_text()
    vol = t.find(("step", 0, "volume"))
    with pytest.raises(ConvertError) as e:  # unset volume while the step still has trigger keys
        save_values(f, [(vol, vol.none)], validate=sfx.load_effect)
    assert str(f) in str(e.value) and "not saved" in str(e.value) and "only takes effect" in str(e.value)
    assert f.read_text() == before
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".lab-check")] == []  # cleaned up


def test_every_placeholder_effect_still_converts_after_its_step_count_is_raised(tmp_path):
    """Callers (Machine.save) pass only fields whose value differs from the default; raising the count
    of each real placeholder effect must give a file the converter accepts."""
    files = sorted(SFX_SRC.glob("*.toml"))
    assert files
    for src in files:
        f = tmp_path / src.name
        shutil.copy(src, f)
        sfx.main([str(tmp_path / "gen"), str(f)])
        t = load_table(tmp_path / "gen/sfx.lab.json")
        before = f.read_text()
        assert save_values(f, []) == 0 and f.read_text() == before
        count = t.find(("step",))
        assert save_values(f, [(count, min(count.default + 2, 16))], validate=sfx.load_effect) == 1
        assert len(sfx.load_effect(f).steps) == min(count.default + 2, 16)


def test_synthesised_enum_slots_default_to_the_zero_value(tmp_path):
    fields = [
        {"source": "a.toml", "path": ["step"], "offset": 2, "type": "u8", "default": 1, "min": 1, "max": 3,
         "array_length": True},
        {"source": "a.toml", "path": ["step", 0, "dir"], "offset": 4, "type": "enum", "default": "down",
         "values": {"up": 0, "down": 1}},
        {"source": "a.toml", "path": ["step", 0, "sweep"], "offset": 5, "type": "enum", "default": "x",
         "values": {"x": 7, "y": 3}},
    ]
    t = load_table(descriptor(tmp_path, fields, layout={"step_size": 4}))
    d1, s1 = [f for f in t.fields if f.synth][:2]
    assert (d1.default, s1.default) == (0, 3)  # 0 where the enum has it, else its smallest value
