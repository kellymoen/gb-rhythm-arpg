"""Command line for the feel lab.

    python -m lab [serve]          run the lab (window + web UI); see --help
    python -m lab replay FILE      replay a recording headless; --check fails on any difference
"""

import argparse
import sys
import webbrowser
from pathlib import Path

from gbtools.errors import ConvertError

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROM = REPO / "build/beatarpg-debug.gbc"


def serve_cmd(args) -> int:
    from .descriptor import load_tables
    from .emu import Machine
    from .server import serve

    if not args.rom.exists():
        print(f"lab: {args.rom} not found; build it with `make DEBUG=1` (or run `make lab`)", file=sys.stderr)
        return 1
    tables = load_tables(args.gen)
    if not tables:
        print(f"lab: no *.lab.json in {args.gen}; run `make DEBUG=1` to generate them", file=sys.stderr)
        return 1
    m = Machine(
        args.rom, tables, REPO, args.replay_dir, window="null" if args.headless else "SDL2",
        audio=not args.mute, audio_frames=args.audio_frames, realtime=not args.fast, scale=args.scale,
    )
    srv, port = serve(m, args.port, REPO)
    url = f"http://localhost:{port}"
    print(f"lab: {url}   ({sum(len(t.fields) for t in tables)} tunable fields from {', '.join(t.name for t in tables)})", flush=True)
    for w in m.warnings:
        print(f"lab: warning: {w}", file=sys.stderr, flush=True)
    if m.windowed:
        print("lab: keys: arrows, A = A, S = B, Return = Start, Backspace = Select, Esc = quit "
              "(avoid P, Z, X, Space, C: PyBoy hotkeys that break recording)", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        m.run()
    except KeyboardInterrupt:
        m.closed = True
    finally:
        srv.shutdown()
    return 0


def replay_cmd(args) -> int:
    from .replay import compare, load_replay, run_replay
    from .symbols import load_symbols

    replay = load_replay(args.file)
    if not args.rom.exists():
        print(f"lab: {args.rom} not found; build it with `make DEBUG=1`", file=sys.stderr)
        return 1
    syms = load_symbols(args.rom)
    if args.window:
        from .emu import Machine

        m = Machine(args.rom, [], REPO, args.file.parent, window="SDL2", audio=not args.mute, scale=args.scale)
        m.play(replay, args.file.stem)
        while m.step() and m.player:
            pass
        result = m.replay_result
        m.closed = True
        if m.audio:
            m.audio.close()
        m.pb.stop(save=False)
        mismatches = result["mismatches"] if result else ["window closed before the replay finished"]
        presses = m.replay_presses
    else:
        res = run_replay(args.rom, replay, syms)
        mismatches, presses = res.mismatches, res.presses
    print(f"{args.file.name}: {replay.frames} frames, {len(presses)} presses judged")
    if replay.rom_sha1:
        from .replay import file_sha1

        if file_sha1(args.rom) != replay.rom_sha1:
            print("note: this ROM differs from the one the replay was recorded on")
    if replay.expect_presses is None and not replay.expect_screen_sha1:
        print("nothing recorded to compare against")
    elif mismatches:
        print("MISMATCH")
        for line in mismatches:
            print("  " + line)
    else:
        print("matches the recording")
    return 1 if (args.check and mismatches) else 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m lab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--rom", type=Path, default=DEFAULT_ROM, help="DEBUG ROM (default build/beatarpg-debug.gbc)")
        sp.add_argument("--mute", action="store_true", help="no audio output (the clock then paces the loop)")
        sp.add_argument("--scale", type=int, default=4, help="window scale (default 4)")

    s = sub.add_parser("serve", help="run the lab (the default)")
    common(s)
    s.add_argument("--port", type=int, default=8750)
    s.add_argument("--gen", type=Path, default=REPO / "build/gen", help="where *.lab.json live")
    s.add_argument("--replay-dir", type=Path, default=REPO / "build/lab/replays")
    s.add_argument("--audio-frames", type=float, default=1.5, help="audio queue target in frames (latency/safety)")
    s.add_argument("--headless", action="store_true", help="no SDL window (drive it from the web page)")
    s.add_argument("--fast", action="store_true", help="with --mute, run unthrottled")
    s.add_argument("--no-browser", action="store_true")
    r = sub.add_parser("replay", help="replay a recording")
    common(r)
    r.add_argument("file", type=Path)
    r.add_argument("--check", action="store_true", help="exit 1 if the replay differs from what was recorded")
    r.add_argument("--window", action="store_true", help="watch it in real time, with sound")
    args = p.parse_args(argv if argv and argv[0] in ("serve", "replay", "-h", "--help") else ["serve", *argv])
    try:
        return {"serve": serve_cmd, "replay": replay_cmd}[args.cmd](args)
    except ConvertError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
