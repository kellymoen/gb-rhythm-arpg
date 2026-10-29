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


def test_save_errors_name_file_and_field(tmp_path):
    f = tmp_path / "t.toml"
    f.write_text(TOML)
    ghost = Field("t:g", ("timing", "ghost"), 0, "u8", 0, 0, 9)
    with pytest.raises(ConvertError, match=r"t\.toml: 'timing\.ghost' not found"):
        save_values(f, [(ghost, 1)])
    bad = Field("t:g", ("nope", "x"), 0, "u8", 0, 0, 9)
    with pytest.raises(ConvertError, match="not found"):
        save_values(f, [(bad, 1)])
    assert f.read_text() == TOML  # nothing half-written
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
