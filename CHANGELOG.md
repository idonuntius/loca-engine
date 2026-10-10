# Changelog

All notable changes to the Loca Location Engine (`loca-engine`).

## 0.1.2 — 2026-10-10

- **Held locations are re-sent every second.** While no new location is being sent, the engine
  re-sends the current coordinate once per second, like a real GPS emitting a fresh fix. Apps
  that ignore stale fixes (e.g. Flutter's `location` plugin drops fixes older than 15 s) now
  keep receiving the simulated location after a teleport instead of showing no location.
- **Much faster startup of the Homebrew binary.** The standalone engine is now a PyInstaller
  onedir bundle instead of a single self-extracting file, so it starts in well under a second
  (was 5–10 s per launch, paid again for every RSD tunnel), and stopping it no longer risks
  leaving an orphaned tunnel process behind.

## 0.1.1 — 2026-10-05

- Fix: the standalone engine binary can now open the RSD tunnel (frozen builds re-invoke a
  bundled pymobiledevice3 CLI instead of shelling out to a nonexistent
  `python -m pymobiledevice3`). Location simulation works in the Homebrew-distributed engine.

## 0.1.0 — 2026-10-05

- First public release of the Loca Location Engine (GPL-3.0-or-later).
