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
