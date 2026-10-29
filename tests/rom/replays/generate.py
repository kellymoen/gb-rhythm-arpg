"""Record the combat-scene replays in this directory (lab replay format, docs/lab.md).

    uv run python tests/rom/replays/generate.py        # after `make PLACEHOLDERS=only DEBUG=1`

Each replay boots the placeholders-only DEBUG ROM from blank cartridge RAM, enters the combat scene
from the main menu, walks up to the training dummy and plays one combo string on the beat, timing
each press from the ROM's beat clock exactly like tests/rom/test_combat.py. It is recorded the way the
lab records (inputs as held-button changes, every judged press, the final screen's SHA-1), so
`python -m lab replay FILE --check` and tests/rom/test_combat.py::test_replay replay it, and the lab's
Play button shows it in real time.

Re-run this after an intended change to the combat scene's look or timing; review the diff of the
`expect` blocks (the presses must stay as they were unless the timing rules changed).
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(REPO / "tools"), str(HERE.parent)]

from lab.replay import WARMUP, PbMemory, PressLogReader, Recorder, new_pyboy, screen_sha1  # noqa: E402
from lab.symbols import load_symbols  # noqa: E402

from test_combat import STRINGS, Driver  # noqa: E402

ROM = REPO / "build/ph/beatarpg-debug.gbc"
MENU_FRAMES = 2  # the main menu's first row is the combat scene: press A at frame 2
TAIL = 60  # frames after the last press: hits, counters and popups settle


def record(name: str, steps: list) -> None:
    syms = load_symbols(ROM)
    pb = new_pyboy(ROM, "cgb")
    pb.set_emulation_speed(0)
    pb.tick(WARMUP, False, False)
    rec = Recorder("cgb")
    mem = PbMemory(pb)
    reader = PressLogReader(syms, mem.read)
    presses = []
    d = Driver(pb, syms, tick=lambda: pb.tick(1, True, False), on_frame=rec.held)

    def tick():
        pb.tick(1, True, False)
        presses.extend(reader.poll(d.frame))

    d.tick = tick
    d.step(n=MENU_FRAMES)
    d.step({"a"})
    d.step(n=40)
    d.step({"up"}, 8)
    d.step({"right"}, 44)
    d.step(n=4)
    d.play(steps, d.slot_now() + 2)
    d.step(n=TAIL)
    replay = rec.finish(d.frame, presses, screen_sha1(pb), ROM)
    replay.notes = f"{name}: walk to the dummy, play the string on the beat (generate.py)"
    pb.stop(save=False)
    out = HERE / f"combat_{name}.json"
    replay.save(out)
    print(f"wrote {out.relative_to(REPO)}: {len(presses)} presses, {d.frame} frames")


def main() -> int:
    if not ROM.exists():
        print(f"{ROM.relative_to(REPO)} missing: run `make PLACEHOLDERS=only DEBUG=1`", file=sys.stderr)
        return 1
    for name, (steps, _damage) in STRINGS.items():
        record(name, steps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
