# 0004 — Music-locked beat grid drives combat

**Status:** accepted (2026-10-27)

The sound driver owns a **beat clock** (beat + 16-bit phase), advanced once per VBlank from the song's
tempo map. It is the only source of musical time. Combo **strings** (A light, B heavy, rests, direction
variants) are quantized to **step slots** (8th notes by default). Every input is graded against the
nearest step slot: PERFECT ±3 frames, GOOD ±6 frames, otherwise OFFBEAT. OFFBEAT inputs still act,
but weaker. A+B is a dodge; only a PERFECT dodge triggers slow-mo. Enemies telegraph on the beat.

Combat animations (and walk/idle cycles) are timed in beats, not frames, so they stay in sync at any
tempo. Input sampling, the beat clock and music always run at 60 Hz in the VBlank ISR; game logic
may drop to 30 fps without affecting grading.

Every number here is a tuning param (`data/tuning.toml`), tunable live in the debug menu.
