# RK3326 Provisioner: changes

A tag `v<VERSION>` (VERSION) runs the tests and publishes a release with
`RK3326-Provisioner-<VERSION>.tar.gz` and its `SHA256SUMS`; the section
below is its notes.

**Every change that goes onto the handheld bumps VERSION** (and gets its line
here), so the version at the top right of the screen says what's installed:
`0.3.0-beta.1`, `beta.2`, … then `0.3.0`. The CI refuses a pull request that
changes the app without changing VERSION. The S3 firmware does the same with
its own version (`s3_usb_wifi/CMakeLists.txt`, shown on its row).

## v0.3.0-beta.15

SandBox_Stump_On 1.0.0-beta.61 and 62: the **Bavard** pack, Tavern 1.2,
plugin API 4; rooms with a scope and tagged plugin bots (nothing to change here).

- **The shelf at Sandbox 1.0.0-beta.62**: its bundle, both Stump images, and
  its five packs: **Bavard 1.1** (a test bot that never stops talking: alone,
  lines of numbers; with another Bavard on another Stump, the two play
  Molière turn by turn; it starts paused), Tavern 1.2, rnfs 1.2, NomadNet
  1.1, Simple 1.0. Nothing else changed for the packs: they're read from the
  release as before (Bavard: 45 KB for the board, 853 KB of plays for its
  SD card).
- **Every pack, for this handheld's Stump too**: its form has a switch for
  each pack Team Stump's wizard will find, however many there are (those in
  packs/ of its SandBox_Stump_On clone; before the first install, the shelf
  Sandbox copy's), on for those its Stump has. It was Tavern and rnfs only.
  An update brings the installed ones up to date (the wizard does). The
  chosen packs' own settings are answered with their declared defaults: the
  b62 wizard asks a pack's choices without them, and stopped at Bavard's
  "Talk from the start?" (a pack nobody had picked from an answers file).
- **Bavard needs plugin API 4** (`stump.post()`, Stump beta.61): on an older
  Stump it's refused with "update its Stump first", as any pack is.
- **A pack on a Stump with no SD card** installs its plugins, skips its card
  files and restarts the Stump, saying what was left out (as Team Stump's
  provisioner does: Bavard plays its built-in scene without one). It used to
  stop with an error, the Stump not restarted.
- Checked against b62: Team Stump's wizard with the handheld's answers (new,
  again, Update); the Stump tests with the b62 copy.

## v0.3.0-beta.14

- **CH340 boards with no kernel driver** (a Freenove ESP32-WROVER carries
  one, and none of the RK3326 systems has ch341, its driver): the
  Provisioner drives the chip itself through libusb-1.0 (there on ArkOS and
  dArkOS), as Linux's ch341.c does: its speed, its DTR/RTS lines (the
  ESP32's EN and IO0, so esptool resets it into the bootloader by them) and
  its data. Such a board is the port `ch340://<bus>-<address>` on the boards
  screen ("no kernel driver: driven from here"): identify, flash, make a
  Stump, its settings and the serial log all go through it. Where ch341 is
  there, the board is its usual `/dev/ttyUSB*`; with no libusb, it's named
  as before, with the driver it lacks.
- install.sh's udev rule lets the handheld's user open a CH340 through
  libusb (the CH340/CH341 USB ids only).

## v0.3.0-beta.13

Caught up with SandBox_Stump_On 1.0.0-beta.56 to 60 and R36MAX-Stump 2.5.0,
as Team Stump's Arborist does it (the same steps over USB serial):

- **The Stump images.** Make a Stump writes the release's image for the
  board's chip (MicroPython with the Stump built in): the S3-CAM's at 0x0,
  the WROVER's at 0x1000, then only the files the image hasn't built in
  (b60: 17 files, 667 KB, not 93 and 1.3 MB). A release without images
  gets plain MicroPython and every file, as before.
- **Updates in place.** A Stump on an image with the same partition layout
  gets the new image written without an erase (its settings, identity and
  card stay), then the rest; old copies of built-in modules are removed. An
  older layout is refused, with why (an erase gives it a new identity). A
  Stump on plain MicroPython is updated file by file, and told that made
  again it gets the image.
- **The ESP32-WROVER is a Stump board.** A classic ESP32 gets the Stump's
  rows (and its packs); one without PSRAM (a WROOM) is refused once it
  answers; a WROVER needs a release with images.
- **The form as beta.58-60 ask it.** Its password (/admin) is needed; the
  fserv bot takes the same one unless it has its own. The chain gets
  **Joins the first over the router** (the first Stump's address on the home
  Wi-Fi, its number, the secret needed; the board stays on the home Wi-Fi).
  The Heltec on the Stump's own Wi-Fi is at .200 (past what the hotspot
  hands out; .2 read back as before); on the router .222 is suggested, its
  own for each.
- **It listens to the board start** after Make and Save (up to 90 s) and
  says, a row each: its pages, its own Wi-Fi, its address on the home Wi-Fi
  or why it didn't join (wrong password, not found), the chain linked or no
  answer, who joined below or was refused, its Heltec answered or not; then
  what to note down for the next Stumps. Check it starts reports the same.
- **Guards**: an update never puts an older release's files over a newer
  Stump image (they'd hide its built-in modules: Make a Stump goes back),
  and checks the board's .mpy as on plain MicroPython; a `stump_image.py`
  of another release next to a bundle is ignored (its partition layout
  isn't this one's); Save refuses when the board's `config.py` isn't the one
  read (another board on the port), as Arborist does.
- **The shelf** takes a release's images and its `stump_image.py`, checked
  (the same release as the bundle, ESP32 images). It carries Sandbox
  1.0.0-beta.60 (both images, its tavern, rnfs, nomadnet and simple packs)
  and the handheld's Sandbox 2.5.0-b.55.
- **This handheld's Stump, with beta.58+ and R36MAX-Stump 2.5.0.** The
  answers carry beta.58's "Admin password (/admin)" and "Use the same
  password for the fserv bot?" beside the old ones (Official b48 still gets
  the one password its way): Team Stump's real wizard takes them at b48, b51
  and b60, new, again and Update. With 2.5.0 the Stump runs only while its
  Port is open (never beside the Provisioner): its page says so instead of
  "not answering", and a new password applies when its Port opens next.

## v0.3.0-beta.12

- **The Library**: everything this Provisioner carries, with no board
  plugged in: the shelf (each product's Official and Sandbox, its version,
  built in or on the card, and what's newer online) and the catalogue
  (WLED, MicroPython, the S3 image: built in). **Y** opens it from the
  boards screen (**L** from a board's row, whose X and Y are the board's).
  **A** checks a row, **L** checks all or none, **X** refreshes the checked
  ones online onto the shelf, or, with none checked, everything newer; one
  task, a line per item, and what was taken, left as is or refused at the
  end. **Y** looks online again.

## v0.3.0-beta.11

- **FireFly 0.9.3 on the shelf it carries** (Sandbox, from
  SandBox_FireFly_RK3326; Official stays 0.8.1, FireFly_RK3326_R36MAX_R36S's
  newest): it installs offline, with no network to fetch it first.

## v0.3.0-beta.10

- **One password, as Team Stump means it, reaching /admin.** Their Stump
  takes the fserv operator password for /admin too, unless a separate
  `AUTH_ADMIN_PASSWORD` is set (stumpid's `check_admin_password`). Their
  computer wizard asks it, but leaves `AUTH_ADMIN_PASSWORD` as
  SandBox_Stump_On's `config.py` has it (not blank) unless "Change any of
  those now?" gets a yes: on the handheld, /admin took that one instead (found
  on the bench). Now:
  - the handheld's form asks for **its password** (needed: /admin and the
    fserv bot) and, optionally, **a separate /admin password**; the answers
    say yes to "Change any of those now?" and give /admin's (blank), so the
    wizard writes it instead of leaving the repo's;
  - after any install, a repo `AUTH_ADMIN_PASSWORD` left in place is
    cleared, so /admin takes its password;
  - its page has **Its password** and **A separate /admin password**: typed
    twice, set with the Stump's own `settings.write_config` (as /admin does;
    `config.py.bak` kept), then the Stump restarts. It says in red when
    /admin's password isn't its own;
  - installing again resends its passwords (the wizard rebuilds `config.py`).
- **The CAM's form**: **its password** (/admin and the fserv bot; the
  fserv operator's, which was missing) and an optional separate /admin one.
- Tests: through Team Stump's real wizard (new, again, update: /admin takes
  its password), a repo one cleared, setting one by stdin, the pages, the
  CAM's form.

## v0.3.0-beta.9

- **install.sh stops on anything that isn't the handheld, before touching
  anything**: not Linux (a Mac), or no `roms/ports` folder. Run on a Mac,
  beta.8 copied the app into the home folder and a udev rule into
  `/etc/udev/rules.d` before saying it wasn't the handheld. It now says how
  to run it on the handheld (over SSH) and that nothing was changed.

## v0.3.0-beta.8

- **Official, Sandbox, + From File, for everything it installs**, as every
  project here has them: the Stump for CAM boards (LaBuche-Stump /
  SandBox_Stump_On), this handheld's Stump (R36MAX-Stump /
  SandBox_RK3326_Stump), FireFly RK3326 (FireFly_RK3326_R36MAX_R36S /
  SandBox_FireFly_RK3326) and the Provisioner itself (its sandbox; no
  official repo yet).
- **The shelf**: an offline copy of each, carried by the Provisioner
  (`firmware/shelf/`: Stump 1.0.0-beta.48 and 1.0.0-beta.51 with their
  packs, R36MAX-Stump 2.0.0-r36max, FireFly 0.8.1 from both). When
  EmulationStation has a network, it asks GitHub for the newest of each,
  shows what's newer, and X takes it onto the shelf (`provisioner-shelf/` on
  the games card): every file checked against GitHub's SHA-256 for it and
  the release's SHA256SUMS, then read for what it is. Offline from then on.
- **This handheld** (the boards screen's last row) lists the four: what's
  installed, the shelf, what's newer online; each one's page installs from
  Official, Sandbox or a file.
- **The CAM's Stump**: Official (1.0.0-beta.48) by default, Sandbox
  (1.0.0-beta.51) or a `.bundle` file; a CAM board's page has the choice as
  its first row (◀ ▶). It was SandBox_Stump_On 1.0.0-beta.50 until now.
- **FireFly** installs and updates from here (its own installer).
- **The Provisioner updates itself** (its own install.sh), keeping the one
  before: Go back swaps them.
- **This handheld's Stump** installs from either release, a tarball or a
  clone, Update keeping everything (Y: new answers).
- Tests: the shelf with a pretend GitHub (the newest release with its file,
  a file changed on the way or with no SHA-256 refused, SHA256SUMS
  checked), what files are, the installers (FireFly's, the Provisioner's
  own with going back), the pages.
- `scripts/fill_shelf.py` fills the built-in shelf (it replaces
  `fetch_stump_bundle.py`).

## v0.3.0-beta.7

- **This handheld's Stump, from the gamepad.** On ArkOS / dArkOS the boards
  screen has a row for the handheld's own Stump (what it runs, or *None
  yet*). Its page installs one (a form: its name, its Wi-Fi's name, storage,
  the chain and its secret, the Heltec, the Tavern and rnfs packs), updates
  it (everything kept), or checks it answers. It runs R36MAX-Stump's
  installer, `handheld/install.sh --answers FILE.json` (SandBox_RK3326_Stump
  v2.3.0-r36max on), which hands the answers to Team Stump's own wizard
  (`provisioner.py --pc --answers`, 1.0.0-beta.48 on); the installer's
  steps and lines show as it goes. The answers file lives only while it
  runs (it can hold the chain's secret). The first install needs internet;
  an older installer, or root (AmberELEC, ROCKNIX), is said plainly.
- Tests: the answers through Team Stump's real wizard (a new chain member
  with Tavern, the same Stump again with new answers, an update that keeps
  them), a pretend installer (steps, its stop message, the file gone), and
  the screens from the boards row to the result.

## v0.3.0-beta.6

- **Every RK3326 handheld's screen.** The layout takes the screen's shape
  instead of scaling a 720x720 square: 640x480 (R36S and co.) is drawn on a
  720x540 canvas, 854x480 (OGS, RGB10 Max) 1:1, 480x320 (OGA, RK2020,
  RG351P/M) on 600x400, so the type stays readable everywhere. Lists show as
  many rows as fit; the confirm box, the keyboard and the hints fit short
  screens. A sideways panel (OGA, OGS, RGB10 Max, XU Mini M on systems
  that don't turn it) is turned. The canvas is scaled in one go (no seams).
- **Buttons from EmulationStation.** Its `es_input.cfg` decides which button
  is A, B, the D-pad, L/R, SELECT, START (SDL's numbering turned back into
  the pad's codes); else a table per pad: the RG351's OSH pad (its Y is
  another pad's L1, its D-pad a hat), the XU10 / XU Mini M (A and B
  swapped), the common one. Sticks and hats work. `python3 -m provisioner
  controls` shows what it found and what each press means.
- **ArkOS, dArkOS, AmberELEC, ROCKNIX.** install.sh runs as root too (their
  only user), puts the app in `/storage` and the udev rule in
  `/storage/.config/udev.rules.d` on the read-only systems, the Ports entry
  in `/storage/roms/ports` (once, even through the `/roms` link), and writes
  the app's path into the launcher. The launcher finds a Wayland compositor
  (ROCKNIX's sway) and uses it first, then KMSDRM.
- **A board with no driver is named.** A CH340 board on ArkOS (no ch341
  driver on any RK3326 system), any non-CDC chip on ROCKNIX: the boards
  screen says which chip and which driver is missing, instead of nothing.
- Checked for Python 3.6 and newer (vermin, in CI); only SDL 2.0.0
  functions.
- The log records the screen, canvas, rotation, display driver and where
  the buttons came from.

## v0.3.0-beta.5

- **+ From File.** A new row on every board: a file browser over the games
  card(s), the home folder and USB drives (folders, then `.bin` and `.zip`
  files; Y shows every file). A `.bin` is read for what it is before
  anything is written: a full image (bootloader, partition table, app; at
  0x0, or 0x1000 for a classic ESP32 image starting with its bootloader) or
  an app image (to the app slot, the board's settings kept). It's refused if
  it isn't ESP firmware, is built for another chip, or needs more flash than
  the board has. A pack's `.zip` goes onto a Stump.
- **Stump packs: Tavern and rnfs.** Team Stump's packs from 1.0.0-beta.50
  ship with the Provisioner (checked against that release's SHA256SUMS) and
  have their own rows on an S3: *Add the Tavern pack 1.1*, *Add the Rnfs
  pack 1.1*. Installed the way Arborist does it: every file checked against
  the pack's hashes first (one that doesn't match refuses the whole pack),
  plugins to the board's flash, `tools/` and `home/` to its SD card, the
  theme into `themes.json`, the Stump's settings kept. A file over 1 MB for
  the card is listed to copy by card reader. Any other pack: + From File.
- **The Stump bundle is 1.0.0-beta.50** (was beta.48).
- The confirm box fits its text (smaller type when it's long); it used to
  run under its buttons.
- Tests: the screen tests' runner now fails when a test fails (it always
  passed), with tests for + From File, a bin's kind, both packs and a
  changed pack.

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
