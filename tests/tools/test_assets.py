from pathlib import Path

from gbtools import assets


def test_asset_name_strips_the_placeholder_suffix():
    assert assets.asset_name(Path("assets/ui/font_genplaceholder.png")) == "font"
    assert assets.asset_name(Path("assets/ui/font.png")) == "font"
    assert assets.is_placeholder(Path("x/combat_genplaceholder.mid"))
    assert not assets.is_placeholder(Path("x/combat.mid"))


def test_release_blocks_placeholders_and_names_the_fix(tmp_path, capsys):
    rc = assets.main([str(tmp_path / "list.txt"), "--release", "assets/ui/font_genplaceholder.png", "assets/ui/hud.png"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "assets/ui/font_genplaceholder.png  -> save your own as assets/ui/font.png" in err
    assert "hud" not in err


def test_release_passes_with_only_your_assets(tmp_path):
    assert assets.main([str(tmp_path / "list.txt"), "--release", "assets/ui/font.png"]) == 0


def test_report_counts_yours_and_rewrites_list_only_on_change(tmp_path, capsys):
    out = tmp_path / "list.txt"
    assets.main([str(out), "assets/ui/font.png", "assets/music/song_genplaceholder.mid"])
    assert "assets: yours 1/2 (font)" in capsys.readouterr().out
    before = out.stat().st_mtime_ns
    assets.main([str(out), "assets/ui/font.png", "assets/music/song_genplaceholder.mid"])
    assert out.stat().st_mtime_ns == before
