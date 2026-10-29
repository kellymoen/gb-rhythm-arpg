"""Export step tests: hashing, staleness and the no-Aseprite (CI) path. A fake `aseprite` script stands in."""

import stat
import sys
from pathlib import Path

import pytest

from gbtools import export
from gbtools.errors import ConvertError

REPO = Path(__file__).resolve().parents[2]

FAKE = """#!{python}
import sys
a = sys.argv
src = a[a.index("-b") + 1]
png, js = a[a.index("--sheet") + 1], a[a.index("--data") + 1]
open(png, "wb").write(b"PNG of " + src.encode())
open(js, "w").write("{{}}")
open({log!r}, "a").write(" ".join(a[1:]) + "\\n")
"""


@pytest.fixture
def fake_aseprite(tmp_path):
    log = tmp_path / "calls.log"
    exe = tmp_path / "bin" / "aseprite"
    exe.parent.mkdir()
    exe.write_text(FAKE.format(python=sys.executable, log=str(log)))
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe, log


@pytest.fixture
def source(tmp_path):
    p = tmp_path / "assets" / "hero_genplaceholder.aseprite"
    p.parent.mkdir()
    p.write_bytes(b"ASE version 1")
    return p


def test_exports_png_json_and_hash_with_aseprite(tmp_path, source, fake_aseprite):
    exe, log = fake_aseprite
    out = tmp_path / "exports"
    assert export.export(source, out, str(exe)) == "exported"
    assert (out / "hero_genplaceholder.png").exists() and (out / "hero_genplaceholder.json").exists()
    assert (out / "hero_genplaceholder.sha1").read_text().strip() == export.source_hash(source)
    call = log.read_text()
    assert "--sheet-type horizontal" in call and "--list-tags" in call and "--list-slices" in call
    assert "--format json-array" in call


def test_fresh_export_is_not_redone_and_works_without_aseprite(tmp_path, source, fake_aseprite):
    exe, log = fake_aseprite
    out = tmp_path / "exports"
    export.export(source, out, str(exe))
    log.unlink()
    assert export.export(source, out, str(exe)) == "up to date"
    assert not log.exists()
    assert export.export(source, out, "/nonexistent/aseprite") == "up to date"  # CI


def test_changed_source_is_stale_and_ci_fails_with_the_fix(tmp_path, source, fake_aseprite):
    exe, _ = fake_aseprite
    out = tmp_path / "exports"
    export.export(source, out, str(exe))
    source.write_bytes(b"ASE version 2")
    fresh, reason = export.is_fresh(source, out)
    assert not fresh and "hash differs" in reason
    with pytest.raises(ConvertError) as e:
        export.export(source, out, "/nonexistent/aseprite")
    msg = str(e.value)
    assert msg.startswith(f"{source}: changed since hero_genplaceholder.png was exported")
    assert "run make with Aseprite installed and commit exports/" in msg


def test_missing_export_is_stale_and_names_the_missing_files(tmp_path, source):
    out = tmp_path / "exports"
    with pytest.raises(ConvertError, match=r"has no export \(hero_genplaceholder\.png, hero_genplaceholder\.json, "
                                           r"hero_genplaceholder\.sha1 missing.*run make with Aseprite installed"):
        export.export(source, out, None)


def test_stale_export_is_redone_when_aseprite_is_available(tmp_path, source, fake_aseprite):
    exe, log = fake_aseprite
    out = tmp_path / "exports"
    export.export(source, out, str(exe))
    source.write_bytes(b"ASE version 2")
    assert export.export(source, out, str(exe)) == "exported"
    assert (out / "hero_genplaceholder.sha1").read_text().strip() == export.source_hash(source)


def test_a_failing_aseprite_is_reported(tmp_path, source):
    exe = tmp_path / "aseprite"
    exe.write_text(f"#!{sys.executable}\nimport sys\nprint('boom', file=sys.stderr)\nsys.exit(3)\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(ConvertError, match=r"Aseprite export failed \(exit 3\): boom; open the file in Aseprite, "
                                           r"fix what it reports and save it, then run make again"):
        export.export(source, tmp_path / "exports", str(exe))


def test_aseprite_that_cannot_start_says_to_set_ASEPRITE(tmp_path, source):
    exe = tmp_path / "aseprite"
    exe.write_text("#!/nonexistent/interpreter\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(ConvertError, match=r"hero_genplaceholder\.aseprite: could not run Aseprite \(.*\): .*; point "
                                           r"ASEPRITE at the Aseprite executable"):
        export.export(source, tmp_path / "exports", str(exe))


def test_missing_source_names_it_and_the_fix(tmp_path):
    missing = tmp_path / "assets" / "ghost.aseprite"
    with pytest.raises(ConvertError, match=r"ghost\.aseprite: does not exist; check the path, or run `make "
                                           r"placeholders` to recreate a missing placeholder"):
        export.export(missing, tmp_path / "exports", None)


def test_main_reports_stale_on_stderr_and_exits_1(tmp_path, source, capsys):
    assert export.main(["--aseprite", "/nonexistent", str(tmp_path / "exports"), str(source)]) == 1
    assert "run make with Aseprite installed and commit exports/" in capsys.readouterr().err


def test_force_reexports(tmp_path, source, fake_aseprite):
    exe, log = fake_aseprite
    out = tmp_path / "exports"
    export.export(source, out, str(exe))
    assert export.export(source, out, str(exe), force=True) == "exported"
    assert len(log.read_text().splitlines()) == 2


@pytest.mark.parametrize("source", sorted((REPO / "assets/sprites").glob("*.aseprite")), ids=lambda p: p.name)
def test_committed_exports_match_their_sources(source):
    """The CI gate: change an .aseprite, forget to commit exports/ -> this fails."""
    fresh, reason = export.is_fresh(source, REPO / "exports/sprites")
    assert fresh, f"{source.name} {reason}; {export.STALE_FIX}"
