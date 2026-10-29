import json
import re
from pathlib import Path

import pytest

from gbtools import combos
from gbtools.errors import ConvertError

REPO = Path(__file__).resolve().parents[2]

ATTACKS = """
[[attack]]
name = "jab1"
anim = "light1"
damage = 2
lunge = 4

[[attack]]
name = "jab2"
anim = "light2"
damage = 3

[[attack]]
name = "wide"
anim = "finisher"
damage = 8
sfx = "swing"
"""

STRINGS = """
[[string]]
name = "rush"
steps   = ["A",    "A",    "A"]
attacks = ["jab1", "jab2", "jab1"]

[[string]]
name = "pause"
steps   = ["A",    "A",    ".", "A"]
attacks = ["jab1", "jab2", "",  "wide"]
"""


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "combos.toml"
    p.write_text(text)
    return p


def parse(tmp_path: Path, text: str) -> combos.Combos:
    return combos.parse(write(tmp_path, text))


# --- parsing -------------------------------------------------------------------------------------


def test_steps_encode_button_direction_rest_and_end(tmp_path):
    c = parse(tmp_path, ATTACKS + STRINGS)
    rush, pause = c.strings
    assert rush.steps == [0x01, 0x01, 0x01, 0, 0, 0, 0, 0]
    assert pause.steps == [0x01, 0x01, 0x03, 0x01, 0, 0, 0, 0]
    assert rush.attacks == [0, 1, 0, 255, 255, 255, 255, 255]
    assert pause.attacks == [0, 1, 255, 2, 255, 255, 255, 255]
    assert rush.unlock == 0


@pytest.mark.parametrize(
    "token, code",
    [("A", 0x01), ("B", 0x02), ("fA", 0x05), ("fB", 0x06), ("bA", 0x09), ("bB", 0x0A),
     ("sA", 0x0D), ("sB", 0x0E), (".", 0x03), ("-", 0x00)],
)
def test_token_codes(token, code):
    assert combos.TOKENS[token] == code


def test_trailing_end_padding_is_allowed(tmp_path):
    text = ATTACKS + '[[string]]\nname = "x"\nsteps = ["B", "-", "-"]\nattacks = ["jab1"]\n'
    (s,) = parse(tmp_path, text).strings
    assert s.steps[:3] == [0x02, 0, 0]


def test_anims_and_sfx_are_enumerated_in_first_use_order(tmp_path):
    c = parse(tmp_path, ATTACKS + STRINGS)
    assert c.anims == ["light1", "light2", "finisher"]
    assert c.sfx == ["swing"]
    assert [(a.anim, a.damage, a.lunge, a.sfx) for a in c.attacks] == [
        (0, 2, 4, 255), (1, 3, 0, 255), (2, 8, 0, 0)]


def test_direction_variants_may_diverge_from_their_plain_step(tmp_path):
    text = ATTACKS + """
[[string]]
name = "crush"
steps = ["B", ".", "B"]
attacks = ["jab1", "", "jab2"]

[[string]]
name = "crush_lunge"
steps = ["B", ".", "fB"]
attacks = ["jab1", "", "wide"]
"""
    c = parse(tmp_path, text)
    assert c.strings[1].steps[2] == 0x06


def test_repo_combos_file_converts():
    c = combos.parse(REPO / "data" / "combos.toml")
    names = [s.name for s in c.strings]
    assert names == ["rush", "pause", "crush", "crush_lunge"]
    assert c.strings[1].steps[:4] == [0x01, 0x01, 0x03, 0x01]


# --- rendering -----------------------------------------------------------------------------------


def test_render_header_declares_enums_tables_and_ram_copy(tmp_path):
    header, source, _ = combos.render(parse(tmp_path, ATTACKS + STRINGS), "data/combos.toml")
    assert "Do not edit" in header and "Do not edit" in source
    assert "#define COMBO_MAX_STEPS 8" in header
    assert "COMBO_STRING_RUSH," in header and "COMBO_STRING_COUNT" in header
    assert "COMBO_ATTACK_WIDE," in header
    assert "COMBO_ANIM_FINISHER," in header
    assert "#define COMBO_ANIM_LIST(X) X(LIGHT1) X(LIGHT2) X(FINISHER)" in header
    assert "#define COMBO_SFX_LIST(X) X(SWING)" in header
    assert "#if defined(DEBUG) || !defined(__SDCC)" in header
    assert "void combos_reset(void);" in header
    assert "#define COMBO_STRING_SIZE 17" in header
    assert "const combos_t combos_defaults" in source
    assert "{ 0x01, 0x01, 0x03, 0x01, 0x00, 0x00, 0x00, 0x00 }" in source


def test_lab_descriptor_offsets_match_the_struct_layout(tmp_path):
    _, _, lab_text = combos.render(parse(tmp_path, ATTACKS + STRINGS), "data/combos.toml")
    lab = json.loads(lab_text)
    assert lab["source"] == "data/combos.toml"
    assert lab["symbol"] == "_combos"
    by_path = {tuple(f["path"]): f for f in lab["fields"]}
    assert len(lab["fields"]) == 2 * (8 + 8 + 1) + 3 * 4

    step = by_path[("string", 1, "steps", 2)]
    assert step["offset"] == 17 + 2 and step["type"] == "enum"
    assert step["values"]["."] == 3 and step["values"]["fB"] == 6 and step["values"]["-"] == 0
    assert step["default"] == "." and "absent" not in step

    padded = by_path[("string", 0, "steps", 5)]
    assert padded["default"] == "-" and padded["absent"] is True

    attack = by_path[("string", 1, "attacks", 3)]
    assert attack["offset"] == 17 + 8 + 3
    assert attack["values"] == {"": 255, "jab1": 0, "jab2": 1, "wide": 2}
    assert attack["default"] == "wide"

    assert by_path[("string", 1, "unlock")]["offset"] == 17 + 16

    base = 2 * 17
    damage = by_path[("attack", 2, "damage")]
    assert damage["offset"] == base + 2 * 4 + 1 and damage["type"] == "u8"
    assert (damage["default"], damage["min"], damage["max"]) == (8, 0, 99)
    assert by_path[("attack", 0, "anim")]["values"] == {"light1": 0, "light2": 1, "finisher": 2}
    assert by_path[("attack", 0, "sfx")]["values"] == {"": 255, "swing": 0}
    assert by_path[("attack", 0, "sfx")]["absent"] is True
    assert by_path[("attack", 2, "lunge")]["offset"] == base + 2 * 4 + 2


def test_main_writes_c_header_and_lab_descriptor(tmp_path):
    src = write(tmp_path, ATTACKS + STRINGS)
    out = tmp_path / "gen"
    assert combos.main([str(src), str(out)]) == 0
    assert (out / "combos.h").exists() and (out / "combos.c").exists()
    json.loads((out / "combos.lab.json").read_text())


def test_main_reports_errors_without_writing(tmp_path, capsys):
    src = write(tmp_path, ATTACKS)
    out = tmp_path / "gen"
    assert combos.main([str(src), str(out)]) == 1
    assert "no [[string]] tables" in capsys.readouterr().err
    assert not out.exists()


# --- validation: every message names the file, the element and the fix ---------------------------


def string(steps: str, attacks: str, name: str = "rush", extra: str = "") -> str:
    return f'[[string]]\nname = "{name}"\nsteps = {steps}\nattacks = {attacks}\n{extra}'


ERRORS = [
    ("[[attack]\n", "invalid TOML"),
    ("speed = 3\n" + ATTACKS + STRINGS, "unknown top-level key 'speed'; use [[attack]] and [[string]] tables"),
    ('attack = 3\n' + STRINGS, "'attack' must be an array of [[attack]] tables"),
    (STRINGS, "no [[attack]] tables; add at least one"),
    (ATTACKS, "no [[string]] tables; add at least one"),
    ('[[attack]]\nanim = "light1"\ndamage = 1\n' + STRINGS, "attack 1 has no name; add name = "),
    ('[[attack]]\nname = "Jab"\nanim = "light1"\ndamage = 1\n', "attack name 'Jab' must be lower_snake_case"),
    ('[[attack]]\nname = "count"\nanim = "light1"\ndamage = 1\n', "attack name 'count' is reserved"),
    (ATTACKS + '[[attack]]\nname = "jab1"\nanim = "light1"\ndamage = 1\n', "attack 'jab1' is defined twice"),
    ('[[attack]]\nname = "jab1"\ndamage = 1\n', "attack 'jab1': missing anim; add anim = "),
    ('[[attack]]\nname = "jab1"\nanim = "light1"\n', "attack 'jab1': missing damage; add damage = "),
    ('[[attack]]\nname = "jab1"\nanim = "light1"\ndamage = 1\ndmg = 2\n',
     "attack 'jab1': unknown key 'dmg'; allowed: name, anim, damage, lunge, sfx"),
    ('[[attack]]\nname = "jab1"\nanim = "Light 1"\ndamage = 1\n',
     "attack 'jab1': anim 'Light 1' must be lower_snake_case"),
    ('[[attack]]\nname = "jab1"\nanim = "light1"\ndamage = 100\n',
     r"attack 'jab1': damage = 100 is out of range [0..99]"),
    ('[[attack]]\nname = "jab1"\nanim = "light1"\ndamage = true\n', "attack 'jab1': damage must be an integer"),
    ('[[attack]]\nname = "jab1"\nanim = "light1"\ndamage = 1\nlunge = -1\n',
     r"attack 'jab1': lunge = -1 is out of range [0..48]"),
    ('[[attack]]\nname = "jab1"\nanim = "light1"\ndamage = 1\nsfx = 3\n',
     "attack 'jab1': sfx must be a sound effect name"),
    ('[[attack]]\nname = "jab1"\nanim = "light1"\ndamage = 1\nsfx = "Big Swing"\n',
     "attack 'jab1': sfx 'Big Swing' must be lower_snake_case"),
    (ATTACKS + '[[string]]\nname = "rush"\nattacks = ["jab1"]\n', "string 'rush': missing steps; add steps = "),
    (ATTACKS + '[[string]]\nname = "rush"\nsteps = ["A"]\n', "string 'rush': missing attacks; add attacks = "),
    (ATTACKS + string('["A"]', '["jab1"]', extra="combo = 1\n"),
     "string 'rush': unknown key 'combo'; allowed: name, steps, attacks, unlock"),
    (ATTACKS + string('"A A A"', '["jab1"]'), "string 'rush': steps must be an array of step strings"),
    (ATTACKS + string('["A"]', '"jab1"'), "string 'rush': attacks must be an array of attack names"),
    (ATTACKS + string('["A"]', '["jab1"]', name="Rush"), "string name 'Rush' must be lower_snake_case"),
    (ATTACKS + string('["A"]', '["jab1"]') + string('["B"]', '["jab1"]'), "string 'rush' is defined twice"),
    (ATTACKS + string('["A"]', '["jab1"]', extra="unlock = 256\n"),
     r"string 'rush': unlock = 256 is out of range [0..255]"),
    (ATTACKS + string('["A","A","A","A","A","A","A","A","A"]', '[]'),
     "string 'rush': 9 steps, at most 8 fit; shorten it"),
    (ATTACKS + string('["A", "C"]', '["jab1", "jab1"]'),
     "string 'rush' step 2: unknown step 'C'; use A or B, optionally after f/b/s"),
    (ATTACKS + string('[".", "A"]', '["", "jab1"]'), "string 'rush' step 1: a string can't start with a rest"),
    (ATTACKS + string('["A", "."]', '["jab1", ""]'), "string 'rush' step 2: a string can't end with a rest"),
    (ATTACKS + string('["A", "-", "A"]', '["jab1", "", "jab1"]'),
     "string 'rush' step 3: 'A' after '-'; '-' may only pad the end"),
    (ATTACKS + string('["-"]', '[]'), "string 'rush' has no steps; add at least one A or B"),
    (ATTACKS + string('["A"]', '["jab1", "jab2"]'), "string 'rush': 2 attacks for 1 steps; give one per step"),
    (ATTACKS + string('["A", "A"]', '["jab1"]'),
     "string 'rush' step 2 \\('A'\\) has no attack; add one as entry 2 of attacks"),
    (ATTACKS + string('["A", "A"]', '["jab1", ""]'),
     "string 'rush' step 2 \\('A'\\) has no attack; add one as entry 2 of attacks"),
    (ATTACKS + string('["A", ".", "A"]', '["jab1", "jab1", "jab2"]'),
     "string 'rush' step 2 \\('.'\\): rests and '-' have no attack; make entry 2 of attacks \"\""),
    (ATTACKS + string('["A"]', '["jab9"]'),
     "string 'rush' step 1: unknown attack 'jab9'; define it in an \\[\\[attack\\]\\] or use one of jab1, jab2, wide"),
    (ATTACKS + string('["A"]', '[3]'), "string 'rush': attacks must be an array of attack names"),
    (ATTACKS + "".join(string('["A"]', '["jab1"]', name=f"s{i}") for i in range(9)),
     "9 strings, at most 8 fit"),
    (ATTACKS + string('["A", "A"]', '["jab1", "jab2"]', name="short")
     + string('["A", "A", "B"]', '["jab1", "jab2", "jab1"]', name="long"),
     "string 'short' is the start of string 'long'"),
    (ATTACKS + string('["A", "B"]', '["jab1", "jab2"]', name="one")
     + string('["A", "B"]', '["jab1", "jab2"]', name="two"),
     "string 'one' is the start of string 'two'"),
    (ATTACKS + string('["A", "A", "A"]', '["jab1", "jab2", "jab1"]', name="rush")
     + string('["A", "B", ".", "A"]', '["jab1", "jab2", "", "wide"]', name="other")
     + string('["A", "A", ".", "A"]', '["jab1", "jab1", "", "wide"]', name="pause"),
     "strings 'rush' and 'pause' start with the same steps, but step 2 is attack 'jab2' in 'rush' and "
     "'jab1' in 'pause'; use the same attack until their steps differ"),
]


@pytest.mark.parametrize("text, message", ERRORS)
def test_errors_name_the_file_element_and_fix(tmp_path, text, message):
    pattern = message if "\\" in message else re.escape(message)
    with pytest.raises(ConvertError, match=pattern) as info:
        parse(tmp_path, text)
    assert str(tmp_path / "combos.toml") in str(info.value)
