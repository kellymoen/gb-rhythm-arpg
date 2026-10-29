# M2 playtest: does combo combat feel good?

Play in **SameBoy** (`make run`, or open `build/beatarpg.gbc`). Use headphones on a wired output;
Bluetooth adds latency. Tune live with `make lab`. The lab's timing differs from SameBoy's, so set
latency with the calibration screen in SameBoy.

## 0. Calibrate first
1. Menu → **Calibrate**. Tap A on each click for 16 beats.
2. Accept if the median looks plausible and the spread is small. It's saved, and loaded at every boot.
3. Back in **Rhythm Test**, press A/B on the beat. You should mostly see PERFECT, with a frame error
   near 0. If not, calibrate again.

## 1. Combat (Menu → Combat)
Controls:
- **D-pad:** walk; it also sets your facing.
- **A:** light attack. **B:** heavy attack.
- **A+B:** dodge.
- **Start:** back to the menu.
- **Select** (DEBUG ROM only): timing overlay.

Strings, one step per 8th note:

| String | Steps |
|--------|-------|
| Rush | `A A A A` |
| Pause | `A A . A` (`.` = skip one 8th) |
| Crush | `B . B` |
| Crush Lunge | `B . B`, holding toward your facing on the last B |

Checklist:
1. Walk around the dummy in all 8 directions. Check that walk and idle switch cleanly and that you
   can't walk through it.
2. Next to the dummy, play **Rush** on the beat. You should get 4 PERFECT popups, musical hits
   rising in pitch, and "RUSH". Does it feel like *you* are playing the music?
3. Play **Pause**. The rest and then the wide finisher should feel deliberate, not like a dropped
   input.
4. Play **Crush**, then **Crush Lunge** from a few steps away. The lunge should close the gap.
5. **Hits:** the dummy flashes, both of you freeze briefly (hitstop), then the dummy flinches. Is
   the freeze weighty or sluggish? Does the animation stay on the beat afterwards?
6. **Off-beat:** press a little late on purpose. You should get OFF popups, about half the damage,
   no musical hit, and a lighter freeze. *Known issue:* after the tempo rises at bar 5, OFFBEAT
   can't happen (decision row 30).
7. **Break:** stop mid-string. You should see "BREAK", with a break sound after 2 or more hits.
8. **Dodge:** when "!" blinks over the dummy, its strike lands 2 beats later. Dodge on that beat. A
   PERFECT dodge dims the floor lines and gives about 2 beats where the dummy moves at half speed;
   the music must not slow. Then stand still through a strike and check "OUCH".
9. **Musical-hit timing:** with `feedback.quantize_hits = 1`, an early press's hit sounds on the
   beat. Try `quantize_hits = 0` in the lab and compare. Which feels better?
10. **Tempo and loop:** play across the tempo change at bar 5 and the song loop. Check for stutter
    and whether the anims stay locked to the beat.

## 2. What to tell me
- **Verdict:** does the core loop (on-beat combo strings with musical hits) feel good enough to
  build M3 on? It doesn't need to be polished, just promising.
- The three things that felt worst, and any tuning values you changed in the lab (saving writes
  them to `data/tuning.toml`).
- Answers to `docs/decisions-pending.md`: confirm or change rows 1–29, and answer rows 30–33. Look
  especially at the asset contracts in rows 8 (sprite tag data, see `docs/sprites.md`) and 12 (the SFX
  format, see `docs/sfx.md`).
- **M3 design** (see `docs/handover.md`):
  - What is the first real enemy, and what does it do?
  - Player and enemy health, and what happens at zero?
  - Arena size and layout?
