# RK3326 Provisioner: changes

A tag `v<VERSION>` (VERSION) runs the tests and publishes a release with
`RK3326-Provisioner-<VERSION>.tar.gz` and its `SHA256SUMS`; the section
below is its notes.

**Every change that goes onto the handheld bumps VERSION** (and gets its line
here), so the version at the top right of the screen says what's installed:
`0.3.0-beta.1`, `beta.2`, … then `0.3.0`. The CI refuses a pull request that
changes the app without changing VERSION. The S3 firmware does the same with
its own version (`s3_usb_wifi/CMakeLists.txt`, shown on its row).

## v0.3.0-beta.4

- **The serial log: pause, look, export.** Paused, a cursor line moves with
  the D-pad (←→ or L/R a page), a scrollbar shows where it is in the log, and
  a line too long for the screen is spelled out in full below it. X marks a
  block from the cursor, Y exports it (or everything) to a text file, each
  line with the time it arrived: `provisioner-logs/` on the games partition
  (`/roms`, by card reader or SSH), else in the home folder. Running, Y
  exports everything. The log keeps reading while the screen is paused
  (it used to drop what came in), up to 5000 lines.

## v0.3.0-beta.3

- **USB Wi-Fi adapter 0.3.0: the handheld is on the Wi-Fi itself.** The S3
  bridges it, so the handheld gets its own address from your network: SSH
  reaches it, FireFly and Reticulum find their peers, a Stump on the handheld
  serves its portal. 0.2.x hid it behind the S3 (seen on the bench).
- The S3 USB Wi-Fi page talks to the S3 over the serial port on the same
  cable (the S3 has no address of its own now). That port isn't listed as a
  board to flash. The page shows the handheld's address on that network.

## v0.3.0-beta.2

- **USB Wi-Fi adapter 0.2.1**: the handheld now takes it as a network card.
  On the R36MAX (kernel 4.4), `cdc_ncm` refused 0.2.0 with "bind() failure":
  its MAC address string was empty (see the firmware's changelog).

## v0.3.0-beta.1

The S3 as the handheld's Wi-Fi card.

- **USB Wi-Fi adapter** 0.2.0 in the catalogue (`s3_usb_wifi/`: ESP-IDF
  firmware, built here, its image checked by the CI). Flashed onto a
  Freenove S3 and plugged into the handheld by its USB port, it's the
  handheld's network card: router and DNS for it, up to 8 networks
  remembered.
- **The S3 USB Wi-Fi page**: the adapter at the top of the boards (what it's
  connected to). Its networks with signal bars, A to join one (a password on
  FireFly's keyboard), Y to forget one, *Connected · internet OK* or why not.
- **Flashing: the board isn't started before the read-back any more.** A full
  image covers the S3's settings area. The adapter's firmware started right
  after the write and wrote its settings there, so the read-back said "Verify
  failed" though the image was fine (seen on the bench, 2026-11-03).
- Tests: the page against a pretend S3 (`tests/fake_s3.py`), flashing the
  image.

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
