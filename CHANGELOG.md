# Changelog

All notable changes to this project are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.0] - 2026-11-07

### Changed
- Setup is now a classic step-by-step wizard: Welcome, License, install folder (with Browse and free-space check),
  desktop / Start menu shortcut checkboxes, a Ready summary, a progress page and a Finish page with
  **Launch Dolby Access Custom now** (on by default). Still per-user with no admin; an update reuses the earlier
  install folder and remembers the desktop shortcut choice. `/silent [/dir="..."]` installs without questions.
- Apps & features now shows the version, size and install date; uninstall works from any install folder.
- Each pair of headphones remembers its own mode, used when the mode follows the default device.
- The guard also follows USB 7.1 headsets (only Bluetooth call endpoints are skipped).
- The 7.1 bridge runs without a window and writes bridge.log.

### Fixed
- The mode was silently off on headphones other than the first one connected (soundmode.txt now includes deact.txt).
- 7.1 page showed a wrong device format (16642 ch / 0.001 kHz) and reported HRIR files as missing.
- build.ps1 could save a SourceForge HTML page instead of the installer (now downloads with curl).

## [1.0.0] - 2026-11-07

### Added
- Sound modes rebuilt from Dolby Access measurements: Dynamic, Movie, Music, Game and Voice, with Intelligent EQ variants,
  a Dolby-matched leveler, adaptive IEQ and bass, and a peak limiter.
- Overlap guard listing every processing layer on each device, with **Turn off extra layers** / **Restore** and Nahimic stop/start.
- The power switch turns other layers off on the headphones in use and restores them when switched off.
- The mode follows the default headphones (Bluetooth Hands-Free endpoints are never used).
- In-app setup: installs Equalizer APO 1.4.2 and HeSuVi 2.0.0.1 and connects Equalizer APO to the chosen device
  without Device Selector or a reboot. **Disconnect** restores the device.
- 7.1 virtual surround through VB-CABLE with a speaker test.
- One-file per-user Setup (no admin) with Start menu and Desktop shortcuts, update in place and uninstall.

### Fixed
- Realtek processing-mode IDs and idle Windows WM LFX/GFX were reported as vendor layers.
- The pinned taskbar icon showed the Python logo.

[Unreleased]: https://github.com/QuanNH26/Dolby-Access-Custom/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/QuanNH26/Dolby-Access-Custom/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/QuanNH26/Dolby-Access-Custom/releases/tag/v1.0.0
