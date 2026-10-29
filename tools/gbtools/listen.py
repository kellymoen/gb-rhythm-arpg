"""Record what a ROM sounds like: run it headless in PyBoy and write a WAV.

    python -m gbtools.listen <rom> <out.wav> [seconds] [--combat]

It opens the Rhythm Test from the main menu (Down there switches to the combat song with --combat).

For checking a Logic export the way the Game Boy actually plays it (`make listen`). PyBoy is a dev
dependency, so this needs `uv sync` with the default dev group.
"""

import sys
import wave

import numpy as np
from pyboy import PyBoy

RATE = 48000
FPS = 4194304 / 70224


def main(argv: list[str]) -> int:
    combat = "--combat" in argv
    argv = [a for a in argv if a != "--combat"]
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    rom, out = argv[0], argv[1]
    seconds = float(argv[2]) if len(argv) == 3 else 20.0
    pb = PyBoy(rom, window="null", cgb=not rom.endswith(".gb"), sound_emulated=True,
               sound_sample_rate=RATE)
    pb.tick(120, False)  # boot to the main menu (src/scenes/menu.c: Combat, Calibrate, Rhythm Test)
    for button in ["down", "down", "a"] + (["down"] if combat else []):
        pb.button(button)
        pb.tick(10, False)
    pb.sound.ndarray  # drop the menu's silence
    chunks = []
    for _ in range(int(seconds * FPS)):
        pb.tick(1, False, True)
        chunks.append(pb.sound.ndarray.astype(np.int16))
    pb.stop(save=False)
    pcm = np.concatenate(chunks).reshape(-1, 2) * 256  # PyBoy gives signed 8-bit samples
    with wave.open(out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.clip(-32768, 32767).astype("<i2").tobytes())
    print(f"wrote {out} ({seconds:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
