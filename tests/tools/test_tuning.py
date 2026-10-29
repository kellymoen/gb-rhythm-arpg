from pathlib import Path

import pytest

from gbtools import tuning
from gbtools.errors import ConvertError


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "tuning.toml"
    p.write_text(text)
    return p


def test_fields_are_table_prefixed_in_file_order(tmp_path):
    p = write(tmp_path, "[timing]\nperfect_window = 3\ngood_window = 6\n[input]\ndodge_grace = 2\n")
    assert tuning.parse(p) == [
        ("timing_perfect_window", 3),
        ("timing_good_window", 6),
        ("input_dodge_grace", 2),
    ]


def test_render_emits_struct_defaults_and_reset(tmp_path):
    param = tuning.Param("timing", "perfect_window", -3, -5, 5, "doc", "PERFE WIND")
    header, source = tuning.render([param], "data/tuning.toml")
    assert "int16_t timing_perfect_window;" in header
    assert "void tuning_reset(void);" in header
    assert "-3, /* timing_perfect_window */" in source
    assert "Do not edit" in header and "Do not edit" in source


@pytest.mark.parametrize(
    "text, message",
    [
        ("perfect_window = 3\n", "'perfect_window' must be a [table] of integer params; move it under one"),
        ("[timing]\nperfect_window = 1.5\n", "'timing.perfect_window' must be an integer"),
        ("[timing]\nflash = true\n", "'timing.flash' must be an integer"),
        ("[timing]\nbig = 40000\n", "does not fit in int16; use a value from -32768 to 32767"),
        ("[timing]\nBadName = 1\n", "'timing.BadName' must be lower_snake_case; rename it, e.g. badname"),
        ("[Timing]\nx = 1\n", "table name 'Timing' must be lower_snake_case; rename it, e.g. [timing]"),
        ("[timing\n", "invalid TOML"),
        ("[a_b]\nc = 1\n[a]\nb_c = 2\n", "'a.b_c' and 'a_b.c' both become the C field a_b_c; rename one"),
    ],
)
def test_errors_name_the_offending_param(tmp_path, text, message):
    p = write(tmp_path, text)
    with pytest.raises(ConvertError) as e:
        tuning.parse(p)
    assert str(e.value).startswith(f"{p}: ") and message in str(e.value)


def test_repo_tuning_file_converts():
    repo = Path(__file__).resolve().parents[2]
    names = [name for name, _ in tuning.parse(repo / "data" / "tuning.toml")]
    assert "timing_perfect_window" in names


# ---- ranges and the lab descriptor (ADR 0008) ----------------------------------------------------
import json  # noqa: E402


def test_parse_params_reads_range_and_doc(tmp_path):
    p = write(tmp_path, "[timing]\nperfect_window = 3   # [0..10] +/- frames that grade PERFECT\n")
    (param,) = tuning.parse_params(p)
    assert (param.name, param.value, param.min, param.max) == ("timing_perfect_window", 3, 0, 10)
    assert param.doc == "+/- frames that grade PERFECT"


def test_negative_and_spaced_ranges(tmp_path):
    p = write(tmp_path, "[timing]\nlatency = 0 # [ -15 .. 15 ] frames\n")
    (param,) = tuning.parse_params(p)
    assert (param.min, param.max, param.doc) == (-15, 15, "frames")


@pytest.mark.parametrize(
    "text, message",
    [
        ("[timing]\nperfect_window = 3\n", "'timing.perfect_window' needs its allowed range"),
        ("[timing]\nperfect_window = 3  # no range here\n", "'timing.perfect_window' needs its allowed range"),
        ("[timing]\nperfect_window = 3  # [0-10] wrong separator\n", "'timing.perfect_window' needs its allowed range"),
        ("[timing]\nperfect_window = 11  # [0..10] too big\n", "'timing.perfect_window' = 11 is outside its range [0..10]"),
        ("[timing]\nperfect_window = -1  # [0..10] too small\n", "= -1 is outside its range [0..10]"),
        ("[timing]\nperfect_window = 3  # [10..0] swapped\n", "minimum must not exceed the maximum, so swap them"),
    ],
)
def test_range_errors_name_file_key_and_fix(tmp_path, text, message):
    p = write(tmp_path, text)
    with pytest.raises(ConvertError) as e:
        tuning.parse_params(p)
    assert str(p) in str(e.value)
    assert message in str(e.value)


def test_range_error_suggests_the_fix(tmp_path):
    with pytest.raises(ConvertError, match=r"e\.g\. `perfect_window = 3  # \[0\.\.10\] what it does`"):
        tuning.parse_params(write(tmp_path, "[timing]\nperfect_window = 3\n"))
    with pytest.raises(ConvertError, match="change the value or widen the range"):
        tuning.parse_params(write(tmp_path, "[timing]\nperfect_window = 30  # [0..10] x\n"))


def test_same_key_in_two_tables_keeps_its_own_range(tmp_path):
    p = write(tmp_path, "[a]\nx = 1  # [0..5] first\n[b]\nx = 9  # [0..20] second\n")
    assert [(q.table, q.max, q.doc) for q in tuning.parse_params(p)] == [("a", 5, "first"), ("b", 20, "second")]


def test_lab_descriptor_offsets_follow_struct_order(tmp_path):
    p = write(tmp_path, "[timing]\na = 3  # [0..10] one\nb = -2  # [-5..5] two\n[input]\nc = 1  # [0..1] three\n")
    doc = json.loads(tuning.lab_descriptor(tuning.parse_params(p), "data/tuning.toml"))
    assert doc["source"] == "data/tuning.toml" and doc["symbol"] == "_tuning"
    assert [(f["path"], f["offset"], f["type"], f["default"], f["min"], f["max"], f["doc"]) for f in doc["fields"]] == [
        (["timing", "a"], 0, "i16", 3, 0, 10, "one"),
        (["timing", "b"], 2, "i16", -2, -5, 5, "two"),
        (["input", "c"], 4, "i16", 1, 0, 1, "three"),
    ]


def test_main_writes_descriptor_next_to_the_c_files(tmp_path):
    src = tmp_path / "tuning.toml"
    src.write_text("[timing]\na = 3  # [0..10] one\n")
    out = tmp_path / "gen"
    assert tuning.main([str(src), str(out)]) == 0
    assert sorted(f.name for f in out.iterdir()) == ["tuning.c", "tuning.h", "tuning.lab.json"]
    assert tuning.main([str(src), str(out / "x")]) == 0


def test_main_fails_without_writing_when_a_range_is_missing(tmp_path, capsys):
    src = tmp_path / "tuning.toml"
    src.write_text("[timing]\na = 3\n")
    assert tuning.main([str(src), str(tmp_path / "gen")]) == 1
    assert "needs its allowed range" in capsys.readouterr().err
    assert not (tmp_path / "gen").exists()


def test_repo_tuning_descriptor_matches_the_struct():
    repo = Path(__file__).resolve().parents[2]
    params = tuning.parse_params(repo / "data" / "tuning.toml")
    fields = json.loads(tuning.lab_descriptor(params, "data/tuning.toml"))["fields"]
    assert [f["offset"] for f in fields] == [2 * i for i in range(len(fields))]
    assert all(f["min"] <= f["default"] <= f["max"] for f in fields)
    header, _ = tuning.render(params, "data/tuning.toml")
    assert header.count("int16_t ") == len(fields)
    assert header.count("    X(") == len(fields)


# ---- debug menu (ADR 0004: every tuning param is tunable live in the debug menu) --------------------
def test_menu_labels_derive_from_the_key_and_fit_ten_columns(tmp_path):
    p = write(tmp_path, "[timing]\ngood_ticks = 1  # [0..9] a\nperfect_window = 3  # [0..10] b\nx = 1  # [0..1]\n")
    assert [q.label for q in tuning.parse_params(p)] == ["GOOD TICKS", "PERFE WIND", "X"]


def test_menu_label_override_in_braces_is_not_part_of_the_doc(tmp_path):
    p = write(tmp_path, "[timing]\nsteps_per_beat = 2  # [1..8] {STEPS/BEAT} slots per beat\n")
    (param,) = tuning.parse_params(p)
    assert (param.label, param.doc) == ("STEPS/BEAT", "slots per beat")


@pytest.mark.parametrize(
    "label, message",
    [
        ("{TOO LONG LABEL}", "debug menu label {TOO LONG LABEL} is 14 characters; at most 10 fit"),
        ("{lower}", "debug menu label {lower} uses 'e', 'l', 'o', 'r', 'w', which the font has no glyph for"),
        ("{A_B}", "uses '_', which the font has no glyph for; use only A-Z, 0-9, space and +-.:/!?%><"),
        ("{}", "debug menu label {} must be a non-empty string"),
    ],
)
def test_bad_menu_label_names_file_param_and_fix(tmp_path, label, message):
    p = write(tmp_path, f"[timing]\nperfect_window = 3  # [0..10] {label} doc\n")
    with pytest.raises(ConvertError) as e:
        tuning.parse_params(p)
    assert str(e.value).startswith(f"{p}: 'timing.perfect_window': ")
    assert message in str(e.value)
    assert "remove the {...} after the range to use 'PERFE WIND'" in str(e.value)


def test_menu_labels_must_differ_within_a_table(tmp_path):
    p = write(tmp_path, "[t]\nhit_flash_ticks = 1  # [0..9] a\nhit_flash_tick = 1  # [0..9] b\n[u]\nhit_flash_tick = 1  # [0..9]\n")
    with pytest.raises(ConvertError, match=r"'t\.hit_flash_tick' and 't\.hit_flash_ticks' share the debug menu label "
                                           r"'HIT FLA TI' on the \[t\] page; give one its own label"):
        tuning.parse_params(p)


def test_menu_macros_list_params_and_one_page_per_table(tmp_path):
    p = write(tmp_path, "[timing]\na = 3  # [0..10] {AAA} one\nb = -2  # [-5..5] two\n"
                        "[hit_stop]\nc = 1  # [0..1] three\n")
    header, _ = tuning.render(tuning.parse_params(p), "data/tuning.toml")
    assert '    X(timing_a, "AAA", "timing.a", 0, 10) \\\n' in header
    assert '    X(timing_b, "B", "timing.b", -5, 5) \\\n' in header
    assert '    X(hit_stop_c, "C", "hit_stop.c", 0, 1)\n' in header
    assert '    T("TIMING", 0, 2) \\\n    T("HIT STOP", 2, 1)\n' in header
    assert "#define TUNING_PARAM_COUNT 3\n" in header and "#define TUNING_TABLE_COUNT 2\n" in header


def test_repo_tuning_labels_are_unique_within_a_page():
    repo = Path(__file__).resolve().parents[2]
    params = tuning.parse_params(repo / "data" / "tuning.toml")
    for table in {p.table for p in params}:
        labels = [p.label for p in params if p.table == table]
        assert len(labels) == len(set(labels)), f"[{table}] has two params with the same menu label: {labels}"
