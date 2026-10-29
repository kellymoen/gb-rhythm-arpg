"""The lab against the real DEBUG ROM (headless PyBoy): WRAM addressing, replay determinism, the server."""

import json
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


def machine(rom, tables, tmp_path) -> Machine:
    return Machine(rom, tables, REPO, tmp_path / "replays", window="null", audio=False, realtime=False)


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
