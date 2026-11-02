# RK3326 Provisioner

Turns an RK3326 handheld (R36MAX, R36S) into a workbench for the boards of
the Stump/FireFly mesh: plug an ESP32 board into the hub, it's recognised,
offered the firmware that fits, flashed and checked, **offline**, from the
gamepad. It's an EmulationStation **Ports** entry.

> **Sandbox.** Work in progress; the plan, decisions and next steps are in
> [docs/PLAN.md](docs/PLAN.md).

| Board | What it can be given (v0.1.0) |
|---|---|
| Classic ESP32 | WLED 16.0.1 (app slot only), MicroPython 1.29.0 (full install) |
| Heltec V3 | *coming*: RNode, set for the mesh |
| ESP32-S3 (Freenove CAM) | *coming*: a USB Wi-Fi adapter for the handheld |
| Any of them | the serial log (115200); erase the whole flash |

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
| A board | ↑↓ · A flash / log / erase (asks first) · B back |
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
| `assets/cockpit_font.bin` | DejaVu Sans Mono, pre-rendered (the Stump cockpit's; `FONT_LICENSE`) |

The approach (bundled esptool, offline catalogue, read-back) comes from
[R36S-ESP32-Flasher](https://github.com/ruderigo/R36S-ESP32-Flasher); the
mesh jobs from Team Stump's Provisioner in
[SandBox_Stump_On](https://github.com/ruderigo/SandBox_Stump_On).
