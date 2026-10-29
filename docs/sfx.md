# Sound effects: author guide

Each sound effect is one TOML file in `assets/sfx/`, written at register level: you say which channel it
plays on, how important it is, and what the APU registers do frame by frame. The build turns
`assets/sfx/<name>.toml` into the id `SFX_<NAME>` (ADR 0006). Claude's placeholders are
`<name>_genplaceholder.toml`. To replace one, save your own as `<name>.toml` (ADR 0007).

To audition effects, open **RHYTHM TEST**. **Left/Right** pick an effect, **Up** plays it and **Down**
switches the song (the rhythm-test loop or the combat loop). In DEBUG builds the feel lab can edit every
step live (`build/gen/sfx.lab.json`); see "Live editing" below.

## Example

```toml
# assets/sfx/hit_heavy.toml
channel = "NOISE"   # P1, P2, WAVE or NOISE
priority = 7        # 1-15

[[step]]            # a snap: one trigger, held 2 frames
frames = 2
volume = 15
noise_shift = 2
noise_width = 7

[[step]]            # retrigger: a decaying crunch
frames = 4
volume = 15
env_pace = 2
noise_shift = 5
noise_width = 15
noise_divisor = 1

[[step]]            # no volume: changes the running noise without retriggering
frames = 10
noise_shift = 7
```

## How an effect plays

- An effect is a list of up to **16 steps**. Each step lasts `frames` VBlanks (about 1/60 s each). After
  the last step the effect ends, the channel is silenced and the music gets it back.
- **A step that sets `volume` triggers the channel** (a new note): it writes the envelope, the hardware
  length and the P1 sweep, then restarts the sound. **A step without `volume` changes the running sound**
  (pitch, duty, noise) without restarting it, so legato arpeggios and noise "darkening" are possible.
  The keys marked *trigger* below only work on a trigger step, and the converter rejects them on
  other steps.
- Anything a step leaves out keeps the value from the previous step: pitch, duty and noise settings
  carry over. Trigger keys (envelope, length, sweep) don't carry over. Each trigger sets them again and
  they default to off.
- The first step must trigger, and on P1/P2/WAVE it must set `pitch`.

## Channels and priority

An effect **steals** its channel. While it plays, the music keeps running silently on that channel, so it
never loses its place. When the effect ends, the music's **next note** on that channel brings it back
with the right duty, envelope and wave shape. A note that was already sounding is not resumed.

`priority` (1-15) decides between effects. A new effect takes a busy channel only if its priority is
**equal or higher**; otherwise it is dropped. Musical hits (combo hits played at the song's `HITS`
pitches) play on P2 at priority **8**.

Placeholder layout (PROVISIONAL): swings and impacts on NOISE (they briefly replace drum hits), dodge,
perfect sting, menu sounds and the calibration click on P1, the string-break sound on WAVE, and musical
hits on P2. When you choose channels, think about which part of your song can drop out for a moment.

| priority | placeholder effects |
|----------|---------------------|
| 12 | `calib_click` |
| 10 | `perfect` |
| 8 | musical hits (P2) |
| 7 / 6 | `hit_heavy` / `hit`, `dodge` |
| 5 / 4 | `swing_heavy`, `string_break` / `swing_light`, `menu_select` |
| 3 | `menu_move` |

## Keys

Top level:

| key | values | notes |
|-----|--------|-------|
| `channel` | `"P1"`, `"P2"`, `"WAVE"`, `"NOISE"` | |
| `priority` | 1-15 | higher steals from lower; equal steals too |
| `waves` | list of 1-4 strings of 32 hex digits | WAVE only: the shapes its steps play (one 4-bit sample per digit) |

Per `[[step]]`:

| key | channels | values | register | notes |
|-----|----------|--------|----------|-------|
| `frames` | all | 1-255 (default 1) | | how long this step lasts |
| `volume` | all | 0-15 | NRx2 / NR32 | **triggers** the channel. On WAVE it is the music's mapping: 12-15 → 100%, 6-11 → 50%, 1-5 → 25%, 0 → mute |
| `env_dir` | P1, P2, NOISE | `"down"` (default), `"up"` | NRx2 bit 3 | *trigger* |
| `env_pace` | P1, P2, NOISE | 0-7 (default 0 = hold) | NRx2 bits 0-2 | *trigger*; 1 is fastest, one volume step per 1/64 s × pace |
| `length` | all | 1-64 (WAVE 1-255) | NRx1 + NRx4 bit 6 | *trigger*; the hardware cuts the sound after `length`/256 s, for clicks shorter than a frame |
| `duty` | P1, P2 | 0-3 (default 2) | NRx1 bits 6-7 | 12.5%, 25%, 50%, 75% |
| `pitch` | P1, P2, WAVE | note name (`"A4"`, `"C#5"`, `"Bb3"`) or raw period 0-2047 | NRx3/NRx4 | note names give true pitch on each channel (WAVE uses its half-speed clock). Lowest: C2 pulse, C1 wave |
| `slide` | P1, P2, WAVE | -128-127 (default 0) | NRx3/NRx4 | added to the period on every frame of the step after its first. Positive raises the pitch. Not a trigger |
| `sweep_pace` | P1 | 0-7 (default 0 = off) | NR10 bits 4-6 | *trigger* |
| `sweep_dir` | P1 | `"up"` (default), `"down"` | NR10 bit 3 | *trigger* |
| `sweep_step` | P1 | 0-7 | NR10 bits 0-2 | *trigger*; an upward sweep that overflows silences the channel (a natural cut-off) |
| `noise_shift` | NOISE | 0-15 (first step default 0) | NR43 bits 4-7 | higher = lower; 14-15 stop the noise |
| `noise_width` | NOISE | 15 (default) or 7 | NR43 bit 3 | 7 = short, metallic / tonal LFSR |
| `noise_divisor` | NOISE | 0-7 (first step default 0) | NR43 bits 0-2 | |
| `wave` | WAVE | index into `waves` (first step default 0) | wave RAM | *trigger*; loading a shape turns the wave DAC off for an instant (a small click) |

Mistakes stop the build with the file, step and fix, e.g.
`assets/sfx/hit.toml: step 2: 'env_pace' only takes effect when the step triggers the channel; add 'volume'
to this step or remove 'env_pace'`.

## Recipes

- **Click** (precise onset, shorter than a frame): one trigger with `length = 2..6` (`calib_click`).
- **Rising whoosh on pulse**: P1 sweep up with `sweep_pace` 1-3 and `sweep_step` 3-5 (`dodge`).
- **Whoosh on noise**: trigger with `env_dir = "up"`, then non-trigger steps that raise `noise_shift`,
  then a retrigger that fades out (`swing_light`).
- **Legato arpeggio**: one trigger, then steps that set only `pitch` (`perfect`).
- **Pitch fall**: `slide` with a negative value (`string_break`), or P1 `sweep_dir = "down"`.
- **Duty shimmer**: steps that alternate only `duty`.

## Live editing (feel lab, DEBUG builds)

DEBUG builds keep every effect in a RAM table (`_sfx_table`), and `build/gen/sfx.lab.json` describes it
(ADR 0008). Edits apply the next time the effect plays. Every effect has room for 16 steps, so the lab
can add steps by raising the effect's step count. Format notes for the lab:

- Each field has its own `"source"` file, because the table spans many TOML files.
- `"none": 255` (or `65535` for `pitch`) means "key absent: keep the running value". Saving that value
  should delete the key from the step.
- `pitch` is saved as a raw period even where the file had a note name.
- The `["step"]` field with `"array_length": true` is the number of `[[step]]` tables. Raising it
  plays slots past the file's last step, which must be appended as new `[[step]]` tables on save.
- Trigger-only keys appear only for steps that trigger.
- `"layout"` gives the record sizes (effect 196 bytes = 4-byte header + 16 × 12-byte steps), so a tool
  can address slots that aren't listed. Byte layout: `src/audio/sfxdata.h`.

## Trade-offs (why it is this way)

- **One byte per field, with "keep" sentinels**, not packed register bytes, so the lab can edit each
  value in place and save it back to the TOML key it came from. The driver packs registers on the fly,
  which costs a few cycles per step.
- **A fixed 16 steps per effect** keeps live editing simple. In release builds the table lives in a ROM
  bank, at about 200 bytes per effect. DEBUG builds copy it to WRAM, also about 200 bytes per effect
  (2 KB for the ten placeholders).
- **`volume` is the trigger** instead of a separate `trigger = true` key. Envelope, length and sweep
  only latch on a trigger on real hardware anyway, so this keeps the files short and makes a
  forgotten trigger impossible. You can't change NRx2 without a trigger ("zombie mode").
- **WAVE `volume` uses the music's 0-15 mapping** to the channel's 4 levels, so every channel reads
  the same.
- **Release silences the channel** and the music returns on its next note, so a sustained music note
  under a long effect stays silent until the next note. Resuming mid-note would re-attack decaying
  notes audibly.
- **A non-trigger `duty` change rewrites NRx1**, which also restarts a running hardware length.
