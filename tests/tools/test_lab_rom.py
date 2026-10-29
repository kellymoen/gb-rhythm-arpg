"""The lab against the real DEBUG ROM (headless PyBoy): WRAM addressing, replay determinism, the server."""

import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lab.descriptor import load_tables
from lab.emu import Machine
from lab.replay import Recorder, Replay, WARMUP, load_replay, new_pyboy, run_replay
from gbtools import sfx
from lab.server import serve
from lab.symbols import load_symbols

REPO = Path(__file__).resolve().parents[2]
ROM = REPO / "build/ph/beatarpg-debug.gbc"
GEN = REPO / "build/ph/gen"


@pytest.fixture(scope="session")
def rom():
    """The placeholders-only DEBUG ROM (the one the ROM tests use), built here if `make test-tools` runs first."""
    subprocess.run(["make", "--no-print-directory", "PLACEHOLDERS=only", "DEBUG=1", "build/ph/gen/tuning.lab.json"], cwd=REPO, check=True, capture_output=True)
    subprocess.run(["make", "--no-print-directory", "PLACEHOLDERS=only", "DEBUG=1"], cwd=REPO, check=True, capture_output=True)
    return ROM


@pytest.fixture()
def tables(rom):
    return load_tables(GEN)


def machine(rom, tables, tmp_path, repo=REPO) -> Machine:
    return Machine(rom, tables, repo, tmp_path / "replays", window="null", audio=False, realtime=False)


def scratch_repo(tmp_path) -> Path:
    """A copy of the TOML sources, so saving never touches the real assets/ and data/."""
    repo = tmp_path / "repo"
    shutil.copytree(REPO / "assets/sfx", repo / "assets/sfx")
    shutil.copytree(REPO / "data", repo / "data")
    return repo


def script(machine_obj, steps):
    """Run `steps`: ints are frames to wait, strings are button names to tap for 6 frames."""
    for s in steps:
        if isinstance(s, int):
            for _ in range(s):
                machine_obj.step()
        else:
            machine_obj.set_virtual({s})
            for _ in range(6):
                machine_obj.step()
            machine_obj.set_virtual(set())
            machine_obj.step()


RHYTHM_TEST = ["down", 3, "down", 3, "a", 90] + ["a", 11] * 8  # menu -> rhythmtest scene, then tap


def test_noi_has_the_symbols_the_lab_needs(rom):
    syms = load_symbols(rom)
    assert {"_tuning", "_press_log", "_press_log_head"} <= set(syms)


def test_field_poke_lands_at_symbol_plus_offset(rom, tables):
    syms = load_symbols(rom)
    t = tables[0]
    pb = new_pyboy(rom)
    try:
        pb.tick(WARMUP, False, False)
        from lab.replay import PbMemory

        mem = PbMemory(pb)
        for f in t.fields:
            addr = syms[t.symbol] + f.offset
            assert f.decode(mem.read(addr, f.size)) == f.default, f.label  # the ROM boots with the TOML defaults
        lat = t.find(("timing", "latency_offset"))
        mem.write(syms[t.symbol] + lat.offset, lat.encode(-7))
        assert lat.decode(mem.read(syms[t.symbol] + lat.offset, 2)) == -7
        # neighbours are untouched
        good = t.find(("timing", "good_window"))
        assert good.decode(mem.read(syms[t.symbol] + good.offset, 2)) == good.default
    finally:
        pb.stop(save=False)


def test_machine_set_value_reset_and_range(rom, tables, tmp_path):
    m = machine(rom, tables, tmp_path)
    try:
        fid = "tuning:timing.good_window"
        assert m.set_value(fid, 12) == 12 and m.values()[fid] == 12
        with pytest.raises(ValueError, match="outside its range"):
            m.set_value(fid, 21)
        with pytest.raises(KeyError):
            m.set_value("tuning:nope", 1)
        assert m.reset() == 1 and m.values()[fid] == 6
    finally:
        m.pb.stop(save=False)


def test_a_poke_changes_how_the_rom_grades(rom, tables, tmp_path):
    """The ROM reads tuning every frame: widening the windows turns an OFFBEAT press into a graded one."""
    def grades(perfect, good):
        m = machine(rom, tables, tmp_path)
        try:
            m.set_value("tuning:timing.perfect_window", perfect)
            m.set_value("tuning:timing.good_window", good)
            script(m, RHYTHM_TEST)
            return [p["grade"] for p in m.presses]
        finally:
            m.pb.stop(save=False)

    narrow, wide = grades(0, 0), grades(10, 20)
    assert len(narrow) == len(wide) >= 8
    assert wide.count("PERFECT") > narrow.count("PERFECT")


def test_record_then_replay_is_deterministic_everywhere(rom, tables, tmp_path):
    m = machine(rom, tables, tmp_path)
    try:
        m.set_value("tuning:timing.latency_offset", -2)
        m.start_recording()
        script(m, RHYTHM_TEST[:6])
        m.set_value("tuning:timing.perfect_window", 5)  # a mid-recording slider change is recorded too
        script(m, RHYTHM_TEST[6:])
        path = m.stop_recording("session")
    finally:
        m.pb.stop(save=False)

    replay = load_replay(path)
    assert replay.frames > 200 and replay.expect_presses and len(replay.expect_presses) >= 8
    assert [(p.f, p.value, p.path[-1]) for p in replay.pokes][0] == (0, -2, "latency_offset")
    assert any(p.f > 0 and p.path[-1] == "perfect_window" and p.value == 5 for p in replay.pokes)

    syms = load_symbols(rom)
    first = run_replay(rom, replay, syms)  # headless from a fresh boot
    assert first.ok, first.mismatches
    assert run_replay(rom, replay, syms).screen_sha1 == first.screen_sha1  # twice: identical

    # ...and inside the lab (restoring the boot snapshot, windowed-style loop) it is identical too.
    m2 = machine(rom, tables, tmp_path)
    try:
        m2.set_value("tuning:timing.good_window", 9)  # the author's own values must not leak into a replay
        m2.start_replay("session")
        while m2.player:
            m2.step()
        assert m2.replay_result == {"name": "session", "ok": True, "mismatches": []}
        assert m2.values()["tuning:timing.good_window"] == 9  # restored afterwards
    finally:
        m2.pb.stop(save=False)


def test_a_replay_detects_a_changed_grade(rom, tmp_path):
    syms = load_symbols(rom)
    r = Replay(frames=300, inputs=[(130, frozenset({"down"})), (136, frozenset())])
    res = run_replay(rom, r, syms)
    wrong = Replay(frames=300, inputs=r.inputs, expect_presses=res.presses, expect_screen_sha1="0" * 40)
    out = run_replay(rom, wrong, syms)
    assert not out.ok and out.mismatches == ["final screen differs from the recorded one"]


def test_replay_cli_check_exit_codes(rom, tables, tmp_path):
    syms = load_symbols(rom)
    rec = Recorder()
    rec.held(130, {"down"})
    rec.held(136, set())
    r = Replay(frames=200, inputs=rec.inputs)
    r.expect_screen_sha1 = run_replay(rom, r, syms).screen_sha1
    f = tmp_path / "ok.json"
    r.save(f)
    cmd = ["uv", "run", "--quiet", "python", "-m", "lab", "replay", str(f), "--rom", str(rom), "--check"]
    env = {"PYTHONPATH": str(REPO / "tools"), "PATH": __import__("os").environ["PATH"], "HOME": __import__("os").environ["HOME"]}
    ok = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "matches the recording" in ok.stdout
    r.expect_screen_sha1 = "0" * 40
    r.save(f)
    bad = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
    assert bad.returncode == 1 and "MISMATCH" in bad.stdout


# ---- the HTTP server -----------------------------------------------------------------------------
@pytest.fixture()
def lab_server(rom, tables, tmp_path):
    m = machine(rom, tables, tmp_path)
    srv, port = serve(m, 18750, REPO)
    t = threading.Thread(target=m.run, daemon=True)
    t.start()
    yield m, port
    m.running = False
    t.join(5)
    srv.shutdown()


def http(port, path, body=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if body is not None:
        h["X-Lab"] = "1"
    req = urllib.request.Request(f"http://localhost:{port}{path}", None if body is None else json.dumps(body).encode(), h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read()) if r.headers["Content-Type"].startswith("application/json") else r.read()
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_server_state_set_values_and_errors(lab_server):
    m, port = lab_server
    code, st = http(port, "/api/state")
    assert code == 200 and st["tables"][0]["name"] == "tuning" and st["tables"][0]["available"]
    fid = "tuning:timing.good_window"
    assert http(port, "/api/set", {"id": fid, "value": 11}) == (200, {"value": 11})
    assert http(port, "/api/values")[1]["values"][fid] == 11
    code, err = http(port, "/api/set", {"id": fid, "value": 99})
    assert code == 400 and "outside its range [0..20]" in err["error"]
    assert http(port, "/api/set", {"id": "tuning:nope", "value": 1})[0] == 400
    assert http(port, "/api/reset", {"table": "tuning"})[1]["changed"] == 1
    code, img = http(port, "/screen.png")
    assert code == 200 and img[:4] == b"\x89PNG"
    assert http(port, "/")[0] == 200 and http(port, "/app.js")[0] == 200
    assert http(port, "/../Makefile")[0] in (404, 400)


def test_server_rejects_foreign_pages(lab_server):
    _, port = lab_server
    # a POST without the custom header (what a cross-site form could send) is refused
    req = urllib.request.Request(f"http://localhost:{port}/api/reset", b"{}", {"Content-Type": "text/plain"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403
    # a rebinding page arrives with its own Host
    code, err = http(port, "/api/state", headers={"Host": "evil.example:18750"})
    assert code == 403


def test_server_record_replay_and_press_stream(lab_server):
    m, port = lab_server
    assert http(port, "/api/record", {"action": "start"})[0] == 200
    for button in ["down", "down", "a", "a", "a"]:  # the machine runs unthrottled, so timing is arbitrary
        http(port, "/api/input", {"held": [button]})
        time.sleep(0.05)
        http(port, "/api/input", {"held": []})
        time.sleep(0.05)
    code, err = http(port, "/api/record", {"action": "stop", "name": "../evil"})
    assert code == 400 and "letters, digits" in err["error"]
    code, saved = http(port, "/api/record", {"action": "stop", "name": "s1"})
    assert code == 200 and saved["replays"] == ["s1"]
    assert http(port, "/api/presses?after=0")[1]["seq"] >= 0
    assert http(port, "/api/replay/check", {"name": "s1"})[1]["ok"] is True
    assert http(port, "/api/replay/check", {"name": "missing"})[0] == 404


# ---- the sfx and combos descriptors (ADR 0008 extensions) -----------------------------------------
def by_label(m: Machine, table: str, source_part: str = ""):
    return {f.label: f for t, f in m.fields.values() if t.name == table and source_part in f.source}


def test_all_three_descriptors_load_with_symbols_in_the_rom(rom, tables):
    syms = load_symbols(rom)
    assert [t.name for t in tables] == ["tuning", "combos", "sfx"]
    assert all(t.symbol in syms for t in tables)
    sfx_t = tables[2]
    assert len(sfx_t.sources()) == 10 and len([f for f in sfx_t.fields if not f.synth]) > 200
    assert len(tables[1].fields) > 90


def test_unset_writes_the_sentinel_to_wram_and_back(rom, tables, tmp_path):
    m = machine(rom, tables, tmp_path)
    try:
        vol = by_label(m, "sfx", "/calib_click")["step.0.volume"]
        t, _ = m.fields[vol.id]
        assert m.set_value(vol.id, 255) == 255 and m.mem.read(m.addr(vol, t), 1) == b"\xff"
        assert m.set_value(vol.id, 7) == 7
        pitch = by_label(m, "sfx", "/calib_click")["step.0.pitch"]
        assert m.set_value(pitch.id, 65535) == 65535 and m.mem.read(m.addr(pitch, t), 2) == b"\xff\xff"
        with pytest.raises(ValueError, match="outside its range"):
            m.set_value(vol.id, 100)
    finally:
        m.pb.stop(save=False)


def test_raising_a_step_count_lists_and_initialises_the_new_slots(rom, tables, tmp_path):
    m = machine(rom, tables, tmp_path)
    try:
        f = by_label(m, "sfx", "/calib_click")
        count = f["step"]
        before = {x.id for _, x in m.listed()}
        assert f["step.1.frames"].id not in before  # not offered until the length reaches it
        m.set_value(count.id, 3)
        t = m.fields[count.id][0]
        assert {f["step.1.frames"].id, f["step.2.frames"].id} <= {x.id for _, x in m.listed()}
        assert m.read_field(t, f["step.1.frames"]) == 1 and m.read_field(t, f["step.2.volume"]) == 255  # not zeros
        m.set_value(count.id, 1)  # lowering hides but keeps them listed (the UI hides the rows)
        assert f["step.2.frames"].id in {x.id for _, x in m.listed()} and not m.in_use(f["step.2.frames"])
        assert f["step.0.frames"].id in m.values()
    finally:
        m.pb.stop(save=False)


def test_a_saved_effect_converts_to_the_bytes_the_lab_put_in_wram(rom, tables, tmp_path):
    """Raise the step count, edit the new steps, unset a key, save, run the real converter on the file:
    the effect's step bytes equal what the ROM table holds."""
    repo = scratch_repo(tmp_path)
    m = machine(rom, tables, tmp_path, repo)
    try:
        for name in ("calib_click", "swing_light"):
            f = by_label(m, "sfx", f"/{name}_")
            t = m.fields[f["step"].id][0]
            src = repo / f["step"].source
            n = f["step"].default
            m.set_value(f["step"].id, n + 2)
            m.set_value(f[f"step.{n}.frames"].id, 6)
            m.set_value(f[f"step.{n}.volume"].id, 9)
            key = "pitch" if "step.0.pitch" in f else "noise_shift"
            m.set_value(f[f"step.{n}.{key}"].id, 700 if key == "pitch" else 5)
            m.set_value(f[f"step.{n + 1}.frames"].id, 3)  # a step that only waits
            res = m.save("sfx", f["step"].source)
            assert res["errors"] == [] and res["saved"]["sfx"] >= 4, res
            effect = sfx.load_effect(src)
            assert len(effect.steps) == n + 2
            base = f["priority"].offset - 1
            ram = m.mem.read(m.symbols[t.symbol] + base, 4 + 12 * 16)
            assert ram[2] == len(effect.steps)  # the count byte
            for i, step in enumerate(effect.steps):
                assert ram[4 + 12 * i : 4 + 12 * (i + 1)] == step, (name, i)
            assert m.save("sfx", f["step"].source) == {"saved": {}, "errors": []}  # defaults moved: nothing left to save
    finally:
        m.pb.stop(save=False)
    # the real placeholders were never touched
    assert subprocess.run(["git", "status", "--porcelain", "assets", "data"], cwd=REPO, capture_output=True, text=True).stdout == ""


def test_a_save_the_converter_would_reject_is_refused_and_reported(rom, tables, tmp_path):
    repo = scratch_repo(tmp_path)
    m = machine(rom, tables, tmp_path, repo)
    try:
        f = by_label(m, "sfx", "/calib_click_")
        src = repo / f["step"].source
        before = src.read_text()
        m.set_value(f["step.0.volume"].id, 255)  # unset the trigger while env/length keys remain
        res = m.save("sfx", f["step"].source)
        assert res["saved"] == {} and len(res["errors"]) == 1
        assert "not saved" in res["errors"][0] and "step 1" in res["errors"][0] and str(src) in res["errors"][0]
        assert src.read_text() == before
    finally:
        m.pb.stop(save=False)


def test_combos_save_adds_absent_keys_and_is_vetted_by_the_converter(rom, tables, tmp_path):
    from gbtools import combos

    repo = scratch_repo(tmp_path)
    m = machine(rom, tables, tmp_path, repo)
    try:
        f = by_label(m, "combos")
        # an attack whose TOML has no `sfx` key yet: setting one adds the key
        sfx_field = next(x for x in f.values() if x.absent and x.path[0] == "attack" and x.path[-1] == "sfx")
        m.set_value(sfx_field.id, next(v for n, v in sfx_field.values.items() if n))
        m.set_value(f["string.0.unlock"].id, 4)
        res = m.save("combos")
        assert res["errors"] == [] and res["saved"]["combos"] == 2, res
        combos.parse(repo / "data/combos.toml")
        assert "unlock = 4" in (repo / "data/combos.toml").read_text()
        # a step with no attack is the converter's business: the save is refused, the file untouched
        k = next(x.path[-1] for x in f.values() if x.absent and x.path[:3] == ("string", 0, "steps"))
        before = (repo / "data/combos.toml").read_text()
        m.set_value(f[f"string.0.steps.{k}"].id, f[f"string.0.steps.{k}"].values["A"])
        res = m.save("combos")
        assert res["saved"] == {} and "has no attack" in res["errors"][0]
        assert (repo / "data/combos.toml").read_text() == before
    finally:
        m.pb.stop(save=False)


def test_reset_and_save_can_target_one_source(rom, tables, tmp_path):
    m = machine(rom, tables, tmp_path)
    try:
        a, b = by_label(m, "sfx", "/hit_h")["priority"], by_label(m, "sfx", "/dodge")["priority"]
        m.set_value(a.id, 1)
        m.set_value(b.id, 1)
        assert m.reset("sfx", a.source) == 1
        assert m.values()[a.id] == a.default and m.values()[b.id] == 1
    finally:
        m.pb.stop(save=False)


def test_the_state_endpoint_describes_sources_none_step_and_arrays(lab_server):
    m, port = lab_server
    code, st = http(port, "/api/state")
    sfx_t = next(t for t in st["tables"] if t["name"] == "sfx")
    assert len(sfx_t["sources"]) == 10 and all(f["source"] for f in sfx_t["fields"])
    width = next(f for f in sfx_t["fields"] if f["label"] == "step.0.noise_width")
    assert (width["step"], width["none"], width["min"], width["max"]) == (8, 255, 7, 15)
    count = next(f for f in sfx_t["fields"] if f["path"] == ["step"])
    assert count["array_length"]
    step = next(f for f in sfx_t["fields"] if f["source"] == count["source"] and f["path"] == ["step", 0, "frames"])
    assert step["array"] == {"length": count["id"], "index": 0}
    # raising the count lists new slots; they are marked absent (the file has no such step yet)
    http(port, "/api/set", {"id": count["id"], "value": count["default"] + 1})
    code, st2 = http(port, "/api/state")
    sfx2 = next(t for t in st2["tables"] if t["name"] == "sfx")
    new = [f for f in sfx2["fields"] if f["source"] == count["source"] and f["path"][:2] == ["step", count["default"]]]
    assert new and all(f["absent"] for f in new)
    assert http(port, "/api/values")[1]["values"][new[0]["id"]] == 1
