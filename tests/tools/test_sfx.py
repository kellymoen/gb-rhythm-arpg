import json
from pathlib import Path

import pytest

from gbtools import music, sfx
from gbtools.errors import ConvertError

REPO = Path(__file__).resolve().parents[2]
K = sfx.KEEP


def write(tmp_path, text, name="zap"):
    p = tmp_path / f"{name}.toml"
    p.write_text(text)
    return p


def load(tmp_path, text, name="zap"):
    return sfx.load_effect(write(tmp_path, text, name))


def test_pulse_steps_trigger_then_change_the_running_sound(tmp_path):
    e = load(tmp_path, """
channel = "P2"
priority = 5

[[step]]
frames = 3
volume = 12
env_dir = "up"
env_pace = 2
length = 10
duty = 1
pitch = "A4"
slide = -3

[[step]]
pitch = 1800
""")
    assert e.channel == "P2" and e.priority == 5
    # frames, volume, env_dir, env_pace, length, duty, pitch lo/hi, slide, sweep pace/dir/step
    assert e.steps[0] == bytes([3, 12, 1, 2, 10, 1, 1750 & 0xFF, 1750 >> 8, 0xFD, 0, 0, 0])
    assert e.steps[1] == bytes([1, K, 0, 0, 0, K, 1800 & 0xFF, 1800 >> 8, 0, 0, 0, 0])


def test_first_step_defaults(tmp_path):
    e = load(tmp_path, 'channel = "P1"\npriority = 1\n[[step]]\nvolume = 15\npitch = "C2"\n')
    assert e.steps[0] == bytes([1, 15, 0, 0, 0, 2, 44, 0, 0, 0, 0, 0])  # 50% duty, C2 = period 44


def test_p1_sweep(tmp_path):
    e = load(tmp_path, """
channel = "P1"
priority = 1
[[step]]
volume = 8
pitch = 1000
sweep_pace = 3
sweep_dir = "down"
sweep_step = 5
""")
    assert e.steps[0][9:] == bytes([3, 1, 5])


def test_noise_fields_and_keep(tmp_path):
    e = load(tmp_path, """
channel = "NOISE"
priority = 3
[[step]]
volume = 15
noise_shift = 2
noise_width = 7
[[step]]
frames = 4
noise_divisor = 5
""")
    assert e.steps[0] == bytes([1, 15, 0, 0, 0, 2, 7, 0, 0, 0, 0, 0])
    assert e.steps[1] == bytes([4, K, 0, 0, 0, K, K, 5, 0, 0, 0, 0])


def test_wave_note_names_use_the_wave_clock_and_shapes(tmp_path):
    e = load(tmp_path, """
channel = "WAVE"
priority = 2
waves = ["0123456789ABCDEFFEDCBA9876543210", "FFFFFFFF000000000000000000000000"]
[[step]]
volume = 15
pitch = "A3"
length = 200
[[step]]
volume = 8
wave = 1
""")
    a3 = round(2048 - 65536 / 220)
    assert e.steps[0] == bytes([1, 15, 0, 0, 200, 0, a3 & 0xFF, a3 >> 8, 0, 0, 0, 0])
    assert e.steps[1][:3] == bytes([1, 8, 1])
    assert e.waves[1] == bytes.fromhex("FFFFFFFF000000000000000000000000")


@pytest.mark.parametrize("note, midi", [("A4", 69), ("a4", 69), ("C#5", 73), ("Db5", 73), ("C7", 96),
                                        ("C2", 36), ("B-1", 11)])
def test_note_names_match_the_music_driver(tmp_path, note, midi):
    if midi < music.NOTE_BASE:
        with pytest.raises(ConvertError, match="below the lowest P1 pitch"):
            sfx.note_period(tmp_path, "step 1", note, "P1")
    else:
        assert sfx.note_period(tmp_path, "step 1", note, "P1") == music.note_freq(midi - music.NOTE_BASE)


def test_effects_are_sorted_and_name_comes_from_the_asset(tmp_path):
    a = write(tmp_path, 'channel = "P1"\npriority = 1\n[[step]]\nvolume = 1\npitch = 9\n', "zz_top_genplaceholder")
    b = write(tmp_path, 'channel = "P2"\npriority = 1\n[[step]]\nvolume = 1\npitch = 9\n', "aa")
    assert [e.name for e in sfx.load_effects([a, b])] == ["aa", "zz_top"]


GOOD = 'channel = "P1"\npriority = 4\n'
STEP = '[[step]]\nvolume = 10\npitch = "A4"\n'


@pytest.mark.parametrize("text, message", [
    ("channel = [", "invalid TOML"),
    (GOOD + "volume = 3\n" + STEP, "unknown key 'volume' \\(top-level keys"),
    ('channel = "P3"\npriority = 1\n' + STEP, "'channel' must be \"P1\", \"P2\", \"WAVE\" or \"NOISE\", got 'P3'"),
    ('channel = "P1"\n' + STEP, "'priority' must be an integer 1-15 \\(higher steals from lower\\), got None"),
    ('channel = "P1"\npriority = 16\n' + STEP, "'priority' must be an integer 1-15"),
    (GOOD, "no steps; add at least one \\[\\[step\\]\\] table"),
    (GOOD + STEP * 17, "17 steps \\(max 16\\)"),
    (GOOD + STEP + "[[step]]\nvolum = 3\n", "step 2: unknown key 'volum' \\(keys for P1: frames, volume"),
    (GOOD + STEP + "noise_shift = 3\n", "step 1: 'noise_shift' only applies to NOISE; this effect plays on P1"),
    ('channel = "P2"\npriority = 1\n' + STEP + "sweep_pace = 1\n", "step 1: 'sweep_pace' only applies to P1"),
    (GOOD + STEP + "[[step]]\nenv_pace = 2\n",
     "step 2: 'env_pace' only takes effect when the step triggers the channel; add 'volume'"),
    (GOOD + "[[step]]\npitch = 'A4'\n", "step 1: the first step must set 'volume'"),
    (GOOD + "[[step]]\nvolume = 3\n", "step 1: the first step must set 'pitch'"),
    (GOOD + "[[step]]\nvolume = 3\npitch = 'H4'\n", "step 1: 'pitch' = 'H4' is not a note name"),
    (GOOD + "[[step]]\nvolume = 3\npitch = 'B1'\n", "step 1: note B1 is below the lowest P1 pitch \\(C2\\)"),
    (GOOD + "[[step]]\nvolume = 3\npitch = 2048\n", "step 1: 'pitch' must be an integer 0-2047, got 2048"),
    (GOOD + STEP + "frames = 0\n", "step 1: 'frames' must be an integer 1-255, got 0"),
    (GOOD + "[[step]]\nvolume = 16\npitch = 9\n", "step 1: 'volume' must be an integer 0-15, got 16"),
    (GOOD + STEP + "duty = 4\n", "step 1: 'duty' must be an integer 0-3, got 4"),
    (GOOD + STEP + "length = 65\n", "step 1: 'length' must be an integer 1-64, got 65"),
    (GOOD + STEP + "slide = 200\n", "step 1: 'slide' must be an integer -128-127, got 200"),
    (GOOD + STEP + "env_dir = 'sideways'\n", "step 1: 'env_dir' must be \"down\" or \"up\", got 'sideways'"),
    (GOOD + STEP + "sweep_dir = 1\n", "step 1: 'sweep_dir' must be \"up\" or \"down\", got 1"),
    (GOOD + "step = 3\n", "no steps"),
    (GOOD + "step = [1]\n", "step 1: write each step as a \\[\\[step\\]\\] table"),
    ('channel = "NOISE"\npriority = 1\n[[step]]\nvolume = 9\nnoise_width = 8\n',
     "step 1: 'noise_width' must be 15 or 7, got 8"),
    ('channel = "NOISE"\npriority = 1\n[[step]]\nvolume = 9\nslide = 1\n', "'slide' only applies to P1 / P2 / WAVE"),
    ('channel = "WAVE"\npriority = 1\n' + STEP, "WAVE effects need 'waves'"),
    ('channel = "WAVE"\npriority = 1\nwaves = ["12"]\n' + STEP, "waves\\[0\\] must be exactly 32 hex digits"),
    ('channel = "WAVE"\npriority = 1\nwaves = []\n' + STEP, "'waves' must be a list of 1-4 shapes"),
    ('channel = "WAVE"\npriority = 1\nwaves = ["' + "0" * 32 + '"]\n' + STEP + "wave = 1\n",
     "step 1: 'wave' = 1 but the effect's 'waves' list has 1 shape\\(s\\)"),
    ('channel = "WAVE"\npriority = 1\nwaves = ["' + "0" * 32 + '"]\n' + STEP + "length = 256\n",
     "step 1: 'length' must be an integer 1-255"),
    ('channel = "WAVE"\npriority = 1\nwaves = ["' + "0" * 32 + '"]\n' + STEP + "env_pace = 1\n",
     "step 1: 'env_pace' only applies to P1 / P2 / NOISE"),
    (GOOD + 'waves = ["' + "0" * 32 + '"]\n' + STEP, "'waves' only applies to WAVE effects; this one plays on P1"),
])
def test_errors_name_the_file_step_and_fix(tmp_path, text, message):
    with pytest.raises(ConvertError, match=message) as err:
        load(tmp_path, text)
    assert str(err.value).startswith(str(tmp_path / "zap.toml") + ": ")


def test_bad_file_name(tmp_path):
    with pytest.raises(ConvertError, match="effect file name 'Big Zap' must be lower_snake_case"):
        load(tmp_path, GOOD + STEP, name="Big Zap")


def test_two_files_for_one_effect(tmp_path):
    a = write(tmp_path, GOOD + STEP, "zap")
    b = write(tmp_path, GOOD + STEP, "zap_genplaceholder")
    with pytest.raises(ConvertError, match="effect 'zap' is also defined by"):
        sfx.load_effects([a, b])


def test_generated_record_bytes_and_c(tmp_path):
    e = load(tmp_path, GOOD + STEP + "slide = -2\n")
    rec = sfx.effect_bytes(e, 0)
    assert len(rec) == sfx.EFFECT_SIZE == 4 + 16 * 12
    assert rec[:4] == bytes([0, 4, 1, 0])
    assert rec[4:16] == bytes([1, 10, 0, 0, 0, 2, 1750 & 0xFF, 1750 >> 8, 0xFE, 0, 0, 0])
    assert rec[16:] == bytes(15 * 12)
    c = sfx.render_c([e])
    assert "{ 0x01, 0x0A, 0x00, 0x00, 0x00, 0x02, 0xD6, 0x06, -2, 0x00, 0x00, 0x00 }" in c
    assert "sfx_t sfx_table[1];" in c and "#pragma bank 255" in c
    h = sfx.render_header([e])
    assert "#define SFX_ZAP 0" in h and "#define SFX_COUNT 1" in h and '"ZAP"' in h


def test_lab_descriptor_offsets_match_the_record(tmp_path):
    a = load(tmp_path, GOOD + STEP + "[[step]]\nduty = 3\n", "a")
    b = load(tmp_path, 'channel = "NOISE"\npriority = 2\n[[step]]\nvolume = 9\nnoise_shift = 3\n', "b")
    lab = json.loads(sfx.render_lab([a, b]))
    assert lab["symbol"] == "_sfx_table"
    memory = sfx.effect_bytes(a, 0) + sfx.effect_bytes(b, 0)
    for f in lab["fields"]:
        raw = memory[f["offset"]:f["offset"] + (2 if f["type"] == "u16" else 1)]
        value = int.from_bytes(raw, "little", signed=f["type"] == "i8")
        assert value == f["default"], f
    paths = {(f["source"].split("/")[-1], tuple(f["path"])) for f in lab["fields"]}
    assert ("a.toml", ("step", 1, "duty")) in paths
    assert ("a.toml", ("step", 1, "env_pace")) not in paths  # trigger-only: step 2 doesn't trigger
    assert ("b.toml", ("step", 0, "noise_shift")) in paths
    pitch = next(f for f in lab["fields"] if f["path"] == ["step", 1, "pitch"])
    assert pitch["default"] == pitch["none"] == 0xFFFF


def test_main_writes_outputs(tmp_path):
    p = write(tmp_path, GOOD + STEP)
    out = tmp_path / "gen"
    assert sfx.main([str(out), str(p)]) == 0
    assert {f.name for f in out.iterdir()} == {"sfx.h", "sfx_data.c", "sfx.lab.json"}
    assert sfx.main([str(out)]) == 0  # no effects still builds
    assert "#define SFX_COUNT 0" in (out / "sfx.h").read_text()


def test_repo_effects_convert():
    paths = sorted((REPO / "assets/sfx").glob("*.toml"))
    names = {sfx.asset_name(p) for p in paths}
    assert {"swing_light", "swing_heavy", "hit", "hit_heavy", "dodge", "perfect", "string_break",
            "menu_move", "menu_select", "calib_click"} <= names
    for e in sfx.load_effects([p for p in paths if p.stem.endswith("_genplaceholder")]):
        assert 1 <= len(e.steps) <= sfx.MAX_STEPS
