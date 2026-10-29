"""Helpers every converter shares: identifier rule and lab descriptor fields (ADR 0008)."""

import pytest

from gbtools import combos, labdesc, music, sfx, sprites, tuning
from gbtools.names import IDENT


def test_one_identifier_rule_for_every_converter():
    assert IDENT.match("crush_lunge") and not IDENT.match("Crush") and not IDENT.match("1st")
    for module in (combos, music, sfx, sprites, tuning):
        assert module.IDENT is IDENT


def test_field_keys_follow_adr_0008_in_a_fixed_order():
    f = labdesc.field(["step", 0, "volume"], 5, "u8", 3, "doc", min=0, max=15, source="a.toml", none=255,
                      step=2, absent=True)
    assert list(f) == ["source", "path", "offset", "type", "default", "min", "max", "step", "none", "doc", "absent"]
    e = labdesc.field(["x"], 0, "enum", "A", "d", values={"A": 1}, array_length=False, restart=True)
    assert e == {"path": ["x"], "offset": 0, "type": "enum", "values": {"A": 1}, "default": "A", "doc": "d",
                 "restart": True}


@pytest.mark.parametrize("kwargs", [
    {"type": "f32", "min": 0, "max": 1},
    {"type": "enum"},
    {"type": "enum", "values": {"A": 1}, "min": 0, "max": 1},
    {"type": "enum", "values": {"A": 1}, "none": 255},
    {"type": "u8"},
    {"type": "u8", "min": 0, "max": 1, "values": {"A": 1}},
])
def test_field_rejects_shapes_the_lab_cannot_read(kwargs):
    with pytest.raises(ValueError):
        labdesc.field(["x"], 0, default=0, doc="d", **kwargs)
