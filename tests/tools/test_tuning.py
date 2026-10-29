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
    header, source = tuning.render([("timing_perfect_window", -3)], "data/tuning.toml")
    assert "int16_t timing_perfect_window;" in header
    assert "void tuning_reset(void);" in header
    assert "-3, /* timing_perfect_window */" in source
    assert "Do not edit" in header and "Do not edit" in source


@pytest.mark.parametrize(
    "text, message",
    [
        ("perfect_window = 3\n", "'perfect_window' must be a [table]"),
        ("[timing]\nperfect_window = 1.5\n", "'timing.perfect_window' must be an integer"),
        ("[timing]\nflash = true\n", "'timing.flash' must be an integer"),
        ("[timing]\nbig = 40000\n", "does not fit in int16"),
        ("[timing]\nBadName = 1\n", "lower_snake_case"),
        ("[timing\n", "invalid TOML"),
    ],
)
def test_errors_name_the_offending_param(tmp_path, text, message):
    with pytest.raises(ConvertError, match=message.replace("[", r"\[")):
        tuning.parse(write(tmp_path, text))


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
        ("[timing]\nperfect_window = 3  # [10..0] swapped\n", "minimum must not exceed the maximum"),
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
    header, _ = tuning.render([(p.name, p.value) for p in params], "data/tuning.toml")
    assert header.count("int16_t ") == len(fields)
