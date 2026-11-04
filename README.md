# RK3326 Provisioner

An RK3326 handheld (R36MAX, R36S and the others) as the workbench of the
Stump/FireFly mesh, **offline and from the gamepad**: plug an ESP32 board into
the hub and it's recognised, given the firmware that fits, flashed and checked;
the handheld's own Stump, FireFly and the Provisioner itself install and
update from here too. It's an EmulationStation **Ports** entry.

> **Sandbox, v0.3.0-beta.10.** Tested on an R36MAX (dArkOS); other RK3326
> handhelds and systems in CI only ([docs/HANDHELDS.md](docs/HANDHELDS.md)).
> Plan and next steps: [docs/PLAN.md](docs/PLAN.md).

## What it does

| Onto | What | From | Status |
|---|---|---|---|
| **ESP32-S3** (Freenove CAM) | **Make a Stump**, update it, its settings, check it starts; add the **Tavern** or **rnfs** pack | Official / Sandbox / + From File (a `.bundle`, a pack's `.zip`) | tested on the R36MAX |
| | **USB Wi-Fi adapter**: the S3 becomes the handheld's Wi-Fi card ([below](#the-s3-as-the-handhelds-wi-fi-card)) | built here (`s3_usb_wifi/`) | 0.2.1 tested (internet through it); **0.3.0 to test** |
| **Classic ESP32** | WLED 16.0.1 (app slot), MicroPython 1.29.0 (full) | the catalogue / + From File (any `.bin`, read for what it is) | tested on the R36MAX |
| **Heltec V3** | RNode for a CAM, set for the mesh | | *coming* |
| **Any board** | the serial log (pause, a block, export); erase the flash | | tested on the R36MAX |
| **This handheld** | **its own Stump**: install (a form), update (everything kept), its password, check | Official / Sandbox / + From File (a `.tar.gz`) | tested on the R36MAX |
| | **FireFly**: install, update (its identity and messages kept) | Official / Sandbox / + From File (a `.zip`) | tested on the R36MAX |
| | **the Provisioner itself**: update, go back to the one before | Sandbox / + From File (a `.tar.gz`) | tested on the R36MAX |

**Official** is a project's public repo's newest release, **Sandbox** its
sandbox's newest (pre-releases included), **+ From File** a file from a card or
a USB drive:

| | Official | Sandbox |
|---|---|---|
| The Stump (CAM boards) | LaBuche-Stump | SandBox_Stump_On |
| This handheld's Stump | R36MAX-Stump | SandBox_RK3326_Stump |
| FireFly (RK3326) | FireFly_RK3326_R36MAX_R36S | SandBox_FireFly_RK3326 |
| The Provisioner | *(none yet)* | SandBox_RK3326_Provisioner |

**It works offline**: a copy of each, *the shelf*, comes with the Provisioner.
**When EmulationStation has the handheld on a network**, it says what's newer
on GitHub, and **X** takes it onto the shelf (`provisioner-shelf/` on the games
card), once every file matches the SHA-256 GitHub records for it and the
release's `SHA256SUMS`, and reads as what it should be. Offline from then on.

## Install

Over SSH, **from your computer** (the commands run on the handheld; on your
computer itself, `install.sh` refuses and changes nothing):

```sh
ssh -t ark@r36max.local 'git clone -b provisioner-next https://github.com/ruderigo/SandBox_RK3326_Provisioner.git ~/SandBox_RK3326_Provisioner && bash ~/SandBox_RK3326_Provisioner/install.sh'
```

With no internet on the handheld: copy a release's
`RK3326-Provisioner-<version>.tar.gz` over, then on it
`tar xzf RK3326-Provisioner-*.tar.gz && bash RK3326-Provisioner-*/install.sh`.
On AmberELEC or ROCKNIX, as `root@` (it lands in `/storage`).

Then **EmulationStation → Ports → RK3326_Provisioner** (restart
EmulationStation if it isn't listed). The version is at the top right.

**Updating**: from the Provisioner itself (*This handheld → The Provisioner*:
Sandbox, or a file; the one before is kept, *Go back* swaps them), or the
same command again with `cd ~/SandBox_RK3326_Provisioner && git pull && bash install.sh`.

## Using it

| Screen | Buttons |
|---|---|
| Boards | ↑↓ · A open (identifies it: the board resets) · X identify again · Y serial log. The last row is **This handheld** |
| A board | ↑↓ · A make a Stump / flash / pack / + From File / log / erase (asks first) · B back. On a CAM, the first row is the Stump it gets: ◀ ▶ Official / Sandbox, A its page |
| This handheld | ↑↓ the Provisioner, its Stump, FireFly, the Stump for CAMs · A open · Y look online · B back |
| A product's page | ↑↓ Official / Sandbox / + From File / its own jobs · A install (or use) · X get the newest online · Y new answers (its Stump) or look online · B back |
| A form | ↑↓ · A type (the keyboard) or next choice · ←→ choice · B back |
| The keyboard | A type · B delete · START OK · SELECT cancel · Y shift · X space · L/R page; or a USB keyboard |
| Asking | ←→ No / Yes · A accept · B cancel. Erasing defaults to **No** |
| + From File | ↑↓ · A open a folder / choose (read for what it is, then asks) · B up · Y every file · ←→ page |
| Serial log | A pause / resume · paused: ↑↓ line, ←→ page, X block, Y export (the block, or all) · running: Y export, X clear · B back |
| S3 USB Wi-Fi | ↑↓ · A join (a password on the keyboard) · Y forget · X look again · B back |
| Anywhere | SELECT+START closes it. A, B... are EmulationStation's buttons |

A port another program has open (the Stump's Heltec) is marked *in use* and
asks before anything touches it. A board that doesn't answer: hold BOOT, tap
RESET (or replug), try again.

## Making a Stump (a CAM board)

Plug the Freenove into the hub, choose it, then **Make a Stump**. The form:
its name, **its password** (for `/admin` and the fserv bot; a separate
`/admin` one is optional), the home Wi-Fi if any, its own Wi-Fi's name, the
chain (first, or joining another with its number and the chain's secret) and
the Heltec. It asks first, then in about five minutes erases the board, writes
MicroPython, copies the Stump (each file checked on the board), writes its
settings and restarts it. Join its Wi-Fi from a phone.

**Update its Stump** copies another release and keeps everything else; **Its
settings** reads, changes and saves them (as `/admin` does); **Check it
starts** restarts it and listens. The packs (Tavern, rnfs) add to a Stump
already there, every file checked against the pack's hashes.

## This handheld's Stump

*This handheld → This handheld's Stump.* **Install** asks its name, **its
password** (for `/admin` and the fserv bot; a separate `/admin` one is
optional), its Wi-Fi's name, storage, the chain (first, or joining another
by its address) and its secret, the Heltec (USB, Bluetooth, none) and the
packs, then runs R36MAX-Stump's installer with those answers: Team Stump's own
wizard, the walk-up extras and the cockpit (Ports → LaBuche_Stump). Once it's
there, **A updates it** (everything kept; **Y**: new answers), **Its
password** changes it, **Check it** asks it what it runs. The first install
needs internet (packages, SandBox_Stump_On, the Stump's Python).

ArkOS / dArkOS, as `ark` (apt and sudo): the same for **FireFly**, whose
own installer keeps its identity, contacts and messages on an update.

## The S3 as the handheld's Wi-Fi card

For a handheld whose Wi-Fi dongle has no driver. Flash **USB Wi-Fi adapter**
onto a Freenove ESP32-S3 CAM (through its UART port), then plug its **USB**
port into the handheld. **S3 USB Wi-Fi** appears at the top of the boards: **A**
lists its networks, A joins one (its password on the keyboard), Y forgets one;
it remembers 8 and rejoins by itself. The handheld is then on that network
itself, as with a dongle. How it works and its bench test:
[s3_usb_wifi/README.md](s3_usb_wifi/README.md).

## On a computer

The same code, with SDL2 (`brew install sdl2`, `apt install libsdl2-2.0-0`):

```sh
python3 -m provisioner            # the app, in a window (arrows, Enter, Esc, Q)
python3 -m provisioner list       # the boards on USB, identified
python3 -m provisioner catalog    # what it can flash
python3 -m provisioner flash /dev/ttyUSB0 wled-16.0.1-esp32
```

`PROVISIONER_SCREEN=640x480` shows another handheld's layout.

## Tests and releases

`bash tests/run_tests.sh` (with `STUMP_ON=path/to/SandBox_Stump_On`, Team
Stump's real wizard too): board detection, every flash path and failure (a
fake esptool), making a Stump on Team Stump's pretend board, the shelf with a
pretend GitHub, the installers, `install.sh` on each system's layout, and the
screens at every handheld size without a screen (`SHOTS=dir python3
tests/test_ui.py` keeps the screenshots). GitHub runs them on every push; a
tag `v<VERSION>` publishes a release (a beta as a pre-release: *Sandbox*).
Every change that goes onto the handheld bumps `VERSION` and has its line in
[CHANGELOG.md](CHANGELOG.md).

## Licences

The Provisioner's own code is **MIT** ([LICENSE](LICENSE)). esptool,
pyserial, WLED, MicroPython, the Stump releases, FireFly and the rest keep
their own licences and are shipped side by side, unmerged: the list, and
what's in each folder, is in [docs/CONTENTS.md](docs/CONTENTS.md). The
approach (bundled esptool, offline catalogue, read-back) comes from
[R36S-ESP32-Flasher](https://github.com/ruderigo/R36S-ESP32-Flasher); the
mesh jobs from Team Stump's Provisioner in
[SandBox_Stump_On](https://github.com/ruderigo/SandBox_Stump_On).
