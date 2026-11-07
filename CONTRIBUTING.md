# Contributing

Thanks for helping. Bug reports with a screenshot of the **Devices & overlap guard** page are the most useful.

## Run from source

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1 -SkipSetup   # once: launcher, C# helpers, portable Python in runtime\
& ".\Dolby Access Custom.exe"
```

Python edits take effect the next time you start the app (close it first: only one window runs at a time).
Page edits (`gui/web`) take effect too, because the app clears its web cache on start.

## Project layout

| Path | What |
|---|---|
| `gui/main.py` | the window (pywebview / WebView2), single instance, taskbar identity |
| `gui/api.py` | everything the page can call: state, modes, guard actions, setup, devices |
| `gui/web/` | the page (`index.html`, `app.js`, `app.css`) |
| `soundmode/engine.py` | mode library, writes `HeSuVi\soundmode.txt`, on/off, follow headphones |
| `soundmode/detect.py` | read-only scan of the processing layers on every playback device |
| `soundmode/guard.py` | overlap guard policy (auto pause & resume / warn only) |
| `soundmode/measure.py`, `*probe.py`, `*model.py` | Dolby Access measurement and mode fitting |
| `soundmode/native/` | C# helpers (`audiohelper`, `bridge`, `play71`) and the elevated scripts: `install.ps1`, `attach.ps1`, `nahimic.ps1` |
| `modes/` | one folder per sound mode: `mode.json` (name, Dolby profile / IEQ) + `mode.txt` (Equalizer APO filters) |
| `hesuvi-control/` | HeSuVi config templates (`golden/`) and the live check |
| `dolby-probe/` | measurement tool used by *Measure Dolby* |
| `launcher/` | launcher exe source and the portable Python builder |
| `installer/setup.cs` | the one-file Setup / uninstaller |
| `tools/` | optional logon tasks (background guard, 7.1 bridge) |
| `docs/` | design notes and screenshots |

## Ground rules

- **Never activate a Bluetooth Hands-Free endpoint** (no audio client on it): doing so switches the headset to call
  quality. Detection only opens property stores; the device picker hides Hands-Free endpoints.
- Anything that changes the system (registry outside the app, services, Equalizer APO) must be reversible, ask in the
  UI first, and run through one elevated script with a backup.
- The UI is in English. Keep everything portable inside the project folder; per-PC data goes in `state.json` (not in git).

## Pull requests

Keep them focused, describe how you tested, and add a line under *Unreleased* in `CHANGELOG.md`.

## Releasing

1. Bump `VERSION` and move the *Unreleased* notes to a new version section in `CHANGELOG.md`.
2. Commit, then `git tag v<version>` and `git push --tags`.
3. GitHub Actions (`.github/workflows/release.yml`) builds the Setup and publishes the release, using that CHANGELOG
   section as the release notes.
