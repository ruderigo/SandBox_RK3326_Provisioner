# RK3326 Provisioner: changes

A tag `v<VERSION>` (VERSION) runs the tests and publishes a release with
`RK3326-Provisioner-<VERSION>.tar.gz` and its `SHA256SUMS`; the section
below is its notes.

## v0.2.0

**Make a Stump, from the handheld, offline.** The Provisioner's main job:
a Freenove ESP32-S3-CAM on the hub becomes a Stump, the same steps as Team
Stump's Arborist, from the gamepad.

- **Make a Stump**: a form (name, admin password, home Wi-Fi, its own Wi-Fi's
  name, chain: none / first / joins another with its number and secret, the
  Heltec: on its own Wi-Fi / on the home Wi-Fi / none), asked first with "No"
  highlighted; then the board erased, MicroPython 1.28 written and read back,
  the Stump copied over the raw REPL (each file's SHA-256 checked on the
  board), its config.py written from the scrubbed template by the Stump's own
  settings.py, the mesh's radio settings saved, and it restarts.
- **Update its Stump** (settings, identity and card kept; refused when the
  board's MicroPython doesn't match), **Its settings** (read, change, save;
  config.py.bak kept), **Check it starts** (restarted, listened to).
- **FireFly's keyboard** for the form: real upper and lower case, symbols,
  accents; a USB keyboard types straight in.
- **The Stump is Team Stump's release, unchanged**: SandBox_Stump_On
  1.0.0-beta.48's `Stump-1.0.0-beta.48.bundle` (MicroPython pinned by their
  build), checked against the release's `SHA256SUMS` and file by file
  (`scripts/fetch_stump_bundle.py`; older releases from their Arborist page).
  Bench-tested on 1.0.0-beta.47; beta.48 changes only the release number on
  the board (`example_node.mpy`).
- **The Provisioner is MIT** ([LICENSE](LICENSE)); every other part keeps its
  own licence, shipped side by side (README, Licences).
- **This handheld's own Stump** shown at the top of the boards (release,
  name, chain).
- Tests: a whole Stump made from the real bundle on Team Stump's pretend
  board (raw REPL, raw-paste, soft reset), updated, its settings changed,
  checked; every refusal; the form and keyboard through the screens.
- `docs/REQUEST_TEAM_STUMP.md`: the bundle as its own release file and the
  computer wizard answered from a file (both answered in Team Stump's
  1.0.0-beta.48), the Heltec for a CAM offline (on hold on their side).

## v0.1.0

The first version: the handheld as a workbench for ESP32 boards, offline.

- **Boards on the hub**, by their serial port and USB chip; identified only
  when you choose one (it resets the board), and named by USB id and chip
  (Heltec V3, ESP32-S3, classic ESP32), with flash size, PSRAM and MAC.
- **A board another program is using asks first** (the Stump's Heltec).
- **Flashing** from a SHA-256-pinned catalogue: app-only images after a
  check of the board's partition table, full installs after an erase (asked
  with "No" highlighted); progress on screen, a slower retry, a read-back.
  Classic ESP32: WLED 16.0.1, MicroPython 1.29.0.
- **Coming, listed already**: the S3 as a USB Wi-Fi adapter, the Heltec V3
  as an RNode.
- **Erase** and a **serial log** (115200) for any board.
- FireFly's look, 720x720, drawn through the system's SDL2 (KMSDRM); the
  R36MAX's buttons. EmulationStation Ports launcher and installer.
- On a computer: the same app in a window; `list`, `catalog`, `flash`.
- Tests: detection, catalogue, every flash path and failure (a fake
  esptool), the screens and buttons headless with screenshots.
