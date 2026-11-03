# RK3326 Provisioner

Turns an RK3326 handheld (R36MAX, R36S) into a workbench for the boards of
the Stump/FireFly mesh: plug an ESP32 board into the hub, it's recognised,
offered the firmware that fits, flashed and checked, **offline**, from the
gamepad. It's an EmulationStation **Ports** entry.

> **Sandbox.** Work in progress; the plan, decisions and next steps are in
> [docs/PLAN.md](docs/PLAN.md).

| Board | What it can be given (v0.2.0) |
|---|---|
| **ESP32-S3 (Freenove CAM)** | **Make a Stump** (Stump 1.0.0-beta.47, offline), update its Stump, its settings, check it starts; *coming*: a USB Wi-Fi adapter for the handheld |
| Heltec V3 | *coming*: RNode for a CAM, set for the mesh |
| Classic ESP32 | WLED 16.0.1 (app slot only), MicroPython 1.29.0 (full install) |
| Any of them | the serial log (115200); erase the whole flash |

## Making a Stump

Plug the Freenove into the hub, choose it (it's identified), then **Make a
Stump**. A form asks its name, an admin password, and optionally the home
Wi-Fi, its own Wi-Fi's name, a chain (first Stump, or joining another with
its number and the chain's secret) and the Heltec. Text is typed on
FireFly's keyboard (A types, B deletes, X space, Y shift, L/R page, START
OK) or a USB keyboard. It asks first, then in about five minutes: erases the
board, writes MicroPython, copies the Stump (each file checked on the board),
writes its settings and restarts it. Join its Wi-Fi from a phone.

**Update its Stump** copies a newer release and keeps everything else;
**Its settings** reads, changes and saves them (as `/admin` does); **Check
it starts** restarts it and listens.

The Stump on the handheld is Team Stump's release, as they published it
(`firmware/stump/`, from SandBox_Stump_On's release page, checked file by
file). A newer one: `python3 scripts/fetch_stump_bundle.py v<release>`.

## Install on the handheld

With the handheld online once (to get this repo), or with a release
unpacked on it:

```sh
ssh -t ark@r36max.local 'git clone https://github.com/ruderigo/SandBox_RK3326_Provisioner.git ~/SandBox_RK3326_Provisioner && bash ~/SandBox_RK3326_Provisioner/install.sh'
```

From a release instead (no internet on the handheld): copy
`RK3326-Provisioner-<version>.tar.gz` over, then
`tar xzf RK3326-Provisioner-*.tar.gz && bash RK3326-Provisioner-*/install.sh`.
Run the same again to update.

Then **EmulationStation → Ports → RK3326_Provisioner** (restart
EmulationStation if it isn't listed).

## Using it

| Screen | Buttons |
|---|---|
| Boards | ↑↓ choose · A open (identifies it: the board resets) · X identify again · Y serial log |
| A board | ↑↓ · A make a Stump / flash / log / erase (asks first) · B back |
| A form | ↑↓ · A type (the keyboard) or next choice · ←→ choice · B back |
| Asking | ←→ No / Yes · A accept · B cancel. Erasing defaults to **No** |
| Flashing | progress, esptool's lines, then *written and verified* or what to do |
| Anywhere | SELECT+START closes it |

A port another program has open (the Stump's Heltec, its radio) is marked
*in use* and asks before anything touches it. A board that doesn't answer:
hold BOOT, tap RESET (or replug), try again.

## On a computer

The same code, with SDL2 installed (`brew install sdl2`, `apt install
libsdl2-2.0-0`):

```sh
python3 -m provisioner            # the app, in a window (arrows, Enter, Esc, Q)
python3 -m provisioner list       # the boards on USB, identified
python3 -m provisioner catalog    # what it can flash
python3 -m provisioner flash /dev/ttyUSB0 wled-16.0.1-esp32
```

## Tests and releases

`bash tests/run_tests.sh`: board detection, the catalogue's checksums,
every flash path and failure (with a fake esptool), and the screens and
buttons without a screen (SDL's dummy driver; screenshots with
`SHOTS=dir python3 tests/test_ui.py`). GitHub runs them on every push; a tag
`v<VERSION>` publishes a release (`package.sh`).

## What's in it, and whose

| | |
|---|---|
| `provisioner/` | the app (boards, catalogue, flashing, serial log, screens) |
| `vendor/` | esptool 4.8.1 (GPL-2.0), pyserial (BSD-3), intelhex (BSD): run as they are; licences in `vendor/LICENSES/` |
| `firmware/` | the catalogue; WLED 16.0.1 (EUPL-1.2) and MicroPython 1.29.0 (MIT), official builds, licences in `firmware/licenses/` |
| `firmware/stump/` | the Stump bundle from SandBox_Stump_On's release (MIT; MicroPython MIT), with where it came from |
| `tests/stump_fixtures/` | Team Stump's pretend board and four Stump modules, for the tests (MIT, credited) |
| `assets/cockpit_font.bin` | DejaVu Sans Mono, pre-rendered (the Stump cockpit's; `FONT_LICENSE`) |

The approach (bundled esptool, offline catalogue, read-back) comes from
[R36S-ESP32-Flasher](https://github.com/ruderigo/R36S-ESP32-Flasher); the
mesh jobs from Team Stump's Provisioner in
[SandBox_Stump_On](https://github.com/ruderigo/SandBox_Stump_On).
