# 0007 — Placeholders carry `_genplaceholder`; only the author's assets ship

**Status:** accepted (2026-10-29)

The author wants to be sure every shipped asset is their own work. Everything Claude generates under
`assets/` is therefore named `<name>_genplaceholder.<ext>`. Any other file under `assets/` belongs to the
author, and agents never create, edit or delete one.

- **Resolution:** for each asset name the build uses `<name>.<ext>` if it exists, otherwise the
  placeholder. To replace one, open the placeholder, paint or compose, and *Save As* without the suffix.
  `make` prints `assets: yours N/M (...)` and lists placeholders your files have made unused. Converters
  name things after the asset name, so `font.png` and `font_genplaceholder.png` both become `ui_font`.
- **Release gate:** `make release` fails, listing every placeholder that would ship.
- **Tests:** `make PLACEHOLDERS=only` builds into `build/ph/`, preferring placeholders. Golden screenshots
  use those ROMs, so replacing art never breaks them. The ROM built from your assets gets smoke tests
  only: it boots, every scene runs, and no frame is missed.
- **Generated exports:** files the build derives from an asset (e.g. Aseprite sheet PNG + JSON, which CI
  cannot produce without Aseprite) are committed under `exports/`, never under `assets/`. Each export
  records a hash of its source, and CI fails if one is stale.
- **Not assets:** `data/*.toml` is design data. Claude may change it; unconfirmed design values are
  listed in `docs/decisions-pending.md`.
- `make placeholders` never writes a placeholder when the author's file already exists.
