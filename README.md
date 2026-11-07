# Dolby Access Custom

A Windows app that recreates Dolby Access sound modes (Dynamic, Movie, Music, Game, Voice + Intelligent EQ) on any
headphones, on top of Equalizer APO + HeSuVi. Everything is set up from inside the app: it installs what is missing,
connects Equalizer APO to the headphones you pick, follows you when you switch headphones, and turns off other
sound-processing layers (Nahimic, Realtek, Windows enhancements) while it is on, putting them back when switched off.

## For users

Download `DolbyAccessCustom-Setup-<version>.exe` from [Releases](../../releases) and run it.
No admin needed for the app itself (installs to `%LOCALAPPDATA%\Programs\Dolby Access Custom`, adds Start menu and
Desktop shortcuts). On first start the app offers **Set up**: pick your headphones, approve one Windows admin prompt,
done. Running a newer Setup updates the app and keeps your settings. Uninstall from *Settings > Apps*.

## For development

The source runs as-is from this folder:

```
powershell -ExecutionPolicy Bypass -File build.ps1 -SkipSetup   # builds the exes + portable Python once
"Dolby Access Custom.exe"                                         # start the app from source
powershell -ExecutionPolicy Bypass -File build.ps1              # also builds dist\DolbyAccessCustom-Setup-<version>.exe
```

Bump `VERSION` before building a release.

| Folder | What |
|---|---|
| `gui/` | window (`main.py`, pywebview) + `api.py` + the page in `web/` |
| `soundmode/` | modes engine, device / layer detection, overlap guard, Dolby measurement; `native/` C# helpers and the admin scripts (install, attach, Nahimic) |
| `modes/` | the sound modes (`mode.json` + `mode.txt` each) |
| `hesuvi-control/` | HeSuVi config templates (`golden/`) and the live check |
| `dolby-probe/` | Dolby Access measurement tool used by *Measure Dolby* |
| `launcher/` | launcher exe source, icon, portable Python builder |
| `installer/` | Setup exe source |
| `tools/` | optional logon tasks (background guard, 7.1 bridge) |
| `docs/` | design notes |

Not in git (rebuilt by `build.ps1` or created at run time): `runtime/`, `vendor/installers/`, `dist/`, `state.json`,
`backups/`, `dolby-probe/runs/`.

## Third-party parts

- [Equalizer APO](https://sourceforge.net/projects/equalizerapo/) and [HeSuVi](https://sourceforge.net/projects/hesuvi/)
  (GPL), downloaded by `build.ps1` and bundled unchanged in the Setup.
- TDR Nova (Tokyo Dawn Records, freeware) in `vendor/VST`.
- VB-CABLE (VB-Audio, donationware) is optional for 7.1 and is not redistributed; get it from vb-audio.com.
