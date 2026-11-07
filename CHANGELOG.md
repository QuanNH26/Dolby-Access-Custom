# Changelog

All notable changes to this project are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/QuanNH26/Dolby-Access-Custom/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/QuanNH26/Dolby-Access-Custom/releases/tag/v1.0.0
