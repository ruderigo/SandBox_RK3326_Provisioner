# RK3326 Provisioner: changes

A tag `v<VERSION>` (VERSION) runs the tests and publishes a release with
`RK3326-Provisioner-<VERSION>.tar.gz` and its `SHA256SUMS`; the section
below is its notes.

**Every change that goes onto the handheld bumps VERSION** (and gets its line
here), so the version at the top right of the screen says what's installed:
`0.3.0-beta.1`, `beta.2`, … then `0.3.0`. The CI refuses a pull request that
changes the app without changing VERSION. The S3 firmware does the same with
its own version (`s3_usb_wifi/CMakeLists.txt`, shown on its row).

## v0.3.0-beta.25

- **+ From File looks on the part of the card a computer reads.** On RK3326
  Linux 1.3.0 and later that is RKSHARE (`/share`): "Shared card (what a
  computer shows)", listed first. Drop a `.bin` or a `.zip` there from a Mac
  or a PC and pick it on the handheld. A card set up before 1.3.0 has no
  RKSHARE and shows a computer only its boot partition: that one is listed
  then ("Boot (what a computer shows)"), and never written to.
- **Exported serial logs go there too**: `/share/provisioner-logs` when the
  card has RKSHARE, so they can be read on a computer. On arkos4clone and
  dArkOS nothing changes (`/roms/provisioner-logs`).

## v0.3.0-beta.24

- **A CH340 read without a gap** (a Freenove WROVER, on the systems with no
  kernel driver for it). The Provisioner's own driver asked the chip for
  bytes one transfer at a time; between two, nothing was reading, and a
  CH340 holds only a few dozen bytes, so a long answer lost some whenever
  the program was busy for a few milliseconds (the screen redrawing): "its
  answer didn't come through whole" at the end of *Make a Stump*, the pack
  list cut, the module list short. Now 32 transfers wait in the kernel at
  once, each one packet, as Linux's own driver does. Should this libusb not
  allow it, it reads as before; `PROVISIONER_CH340_ONE_AT_A_TIME=1` forces
  that. Not yet run against a real CH340: tested with libusb's calls by hand.
- **`python3 -m provisioner linktest`** shows what a board's serial line
  loses: it prints numbered lines at once and in small pieces, then its
  Stump image's list, and every line that didn't arrive as sent is printed
  with what came instead (`--one-at-a-time` for the CH340's old reading).
- **An answer that never came whole is kept**: everything the board sent,
  each try, in `/tmp/provisioner-last-answer.txt` (the log says so).
- **A newer Stump online is said on the board's page.** Its first row turns
  to "Sandbox 1.0.0-beta.89 is online: X gets it" when GitHub has a release
  newer than every one on the shelf; X fetches it and comes back to the
  page, and the board gets that one.
- **The built-in Sandbox Stump is 1.0.0-beta.88** (was beta.86).
- **What a board prints by itself isn't taken for its answer.** A Stump
  turns its Wi-Fi on as it starts, and ESP-IDF says so on the same serial
  line; arriving while the Provisioner asked its MicroPython version, it
  read an empty answer ("MicroPython , .mpy , ?") and *Update the Stump*
  then refused with "needs 1.28.0" (R36MAX, WROVER, beta.23). Now what it
  printed in between is cleared before each question and skipped when it
  comes with the answer, the question is asked again when the answer
  doesn't come through, and if it never does it says so ("its answers
  didn't come through: unplug it, plug it back in, try again") instead of
  a wrong reason.
- **A nearly full board can still be updated.** Each file used to be
  written beside the old one before the swap, so the biggest needed its
  room on top (a WROVER with its packs: "needs 843 KB, it has 48 KB",
  updating the Stump and its packs alike). When only that copy doesn't fit,
  each file is now written over the old one: the room needed is only what
  the update adds. Its settings and identity (`config.py`, `rns/`) are
  never written that way. Still short: it says how many files are new and
  how many changed, and what takes the room; the message shows whole now
  (a long one used to be cut after four lines).
- **A pack's list read again.** After a pack is copied (each file checked),
  its list of packs is asked for again when the answer doesn't come
  through; if it never does, the pack still counts as installed, noted in
  the log ("couldn't read its packs" after 100 % on a WROVER, 2026-11-24).
  When an answer doesn't come through, the log shows what the board said
  instead.

- **Answers read whole, or asked again.** A line the board printed by
  itself landing in the middle of an answer ("Expecting ',' delimiter: line 1
  column 1342" updating a WROVER, 2026-11-24): every answer read as JSON
  (its files, settings, radio, themes, packs, image) is now asked again when
  it doesn't read whole, and never guessed: a pack's settings read back
  empty would have had its defaults written over the board's, its themes
  read back empty would have written the others away. And ESP-IDF's own log
  is turned off while the Provisioner talks to the board.
- **Every answer comes with its length and checksum.** A WROVER's
  USB-serial chip (CH340) on the RK3326's USB lost bytes from what the board
  sent. Some answers then failed to read; one still read, a few names short:
  the Stump image's list of built-in modules, so a file of the built-in
  `urns` was copied beside the image, hid the built-in package, and the new
  Stump stopped at its start on "no module named 'urns.mem'". The board's
  `print` is now replaced while the Provisioner talks to it: each line ends
  with its checksum and length and goes out a few bytes at a time; only a
  line that matches is an answer, anything else is asked again, slower each
  time (4 tries), and never guessed. Its settings, files, packs, themes,
  radio, identity, stamps, memory and SD card are all read that way.
- **The modules built into an image: the release's own list** (the
  `stump_image.py` on the shelf with it) when the board runs that release's
  image, not what came over USB.
- **"Checking it starts" took a harmless line for a failure.** "[adc_reader]
  battery init failed (non-fatal, continuing without it)" (a WROVER has no
  battery pin) made a Stump that started fine read "It didn't work". A line
  that says it's non-fatal is a note now. And "MicroPython ?" there: the
  version the board gave is used when its start banner is missed.

- **A WROVER gets the Stump copy that has an image for it.** On a fresh
  install the boards got Official (1.0.0-beta.48), which has no WROVER image
  and no chain over the router: *Make a Stump* answered "older than
  1.0.0-beta.57: no …", cut at one line. A board that only takes a Stump
  image now starts on the first copy that has one for it (Sandbox today);
  one chosen by hand stays. Messages at the top of the screen show whole (up
  to four lines), and that one says where to choose.
- **Its code checked before it restarts.** After copying, the Provisioner
  imports the Stump's mesh code on the board (`urns.mem`, `boot_common`, as
  far as the release has them) before restarting it: a Stump that would stop
  at its start ("ImportError: no module named 'urns.mem'" after Make a Stump
  on a WROVER, 2026-11-24) is said there, with where `urns` came from and
  where it looked, instead of a Stump whose pages never come up.



- **The board bench only.** The Provisioner is now about ESP32 boards:
  identifying, making a Stump, packs on a board, a board's identity, + From
  File (a `.bin`, your own build's `.zip`), the serial log, erase, the S3 as
  a USB Wi-Fi card, and the Library of board firmware. *This handheld* is
  gone: the handheld's own Stump and FireFly install, set up and update
  themselves (their own installers; on RK3326 Linux its Apps window and
  Stump setup), and the handheld Stump's packs, password and identity move
  to its cockpit (OWNER). Its last row on Boards is **The Provisioner**: its
  own updates and going back to the one before, as before. Smaller too: the
  handheld Stump's and FireFly's copies are off its shelf.
- **RK3326 Linux**: `install.sh` puts it on the dock (Workshop, `chip`
  icon: `/data/ark/apps/provisioner.json`, unless the image carries its
  own), with no `/roms/ports` needed. Under the dock its launcher takes the
  screen as the dock gives it (no driver of its own, no tty). + From File
  also looks in `/data/ark` (*Data*), and the shelf and exported logs go
  there when there's no games card to write to. The gamepad needs no
  EmulationStation config (its table for these pads, as before).



- **Your own firmware build, from a `.zip`** (+ From File on a board's page):
  what ESP-IDF, PlatformIO and the Arduino IDE make, several files each with
  its own address, flashed in one go. Where each goes comes from ESP-IDF's
  `flasher_args.json` or `flash_args`, or from the names PlatformIO and the
  Arduino IDE give them (bootloader, partition table, the program, OTA data,
  a LittleFS/SPIFFS/FAT image at its data partition). Before anything is
  written: every file there, no overlaps, all within the board's flash, the
  bootloader at the chip's address, a partition table, every image for the
  board's chip, every program fitting its app partition; anything else is
  refused, saying why. It shows each file with its address and size and asks;
  then the whole flash is erased, every file written and read back. A Stump
  pack's `.zip` still goes to its packs, as before.

## v0.3.0-beta.21

Documentation:

- **A new [QUICKSTART.md](QUICKSTART.md)**: install, the screens and
  buttons, a first board, the handheld's apps, their sound, help.
- **The README has a Sound section**: the Provisioner plays none (it opens
  the screen only), neither do the Stump boards it makes; what FireFly and
  the handheld's Stump cockpit play, where, how to turn it off, and what
  they install for it.
- The README's banner said beta.10: it says this version now.


Caught up with SandBox_Stump_On 1.0.0-beta.86 and Reticulum 1.6.1:

- **Work out its announce stamps** (Stump beta.86). Reticulum 1.6.1 puts a
  proof of work on announces, and a node can be set to ignore announces
  without one. A Stump with *Announce stamps* ticked in its /admin (Stump
  settings -> Announcing) lists what it announces; a board finds its stamps
  slowly. A CAM's new row works them out on this handheld, every core on
  them (a minute or more each; the board runs meanwhile), and copies them
  over: Team Stump's `--stamp-announces`, checked by its own code. For this
  handheld's Stump, Team Stump's tool itself (a computer Stump also finds
  them in the background on its own). A Stump that hasn't listed them yet
  says what to tick.
- **A board's identity is read with its size and SHA-256** and checked (read
  twice), as Team Stump's beta.84 does: one that won't read whole stops a
  restore.
- **The shelf at Sandbox 1.0.0-beta.86**, with **all seven packs**: Meter 1.4
  (`/meter ann`) and Marco Polo 1.0 are back (rehashed in beta.83). FireFly's
  Sandbox at 0.9.8 (packed text, Reticulum 1.6.1 and LXMF 1.3.1), the
  handheld's at 2.5.4-b.86.
- Checked against b86 with no change needed: Team Stump's wizard with the
  form's answers, pack records and removal (beta.84's rules are the ones
  this already kept), Reticulum 1.6.1 (the Stump's business on a board; a
  computer Stump installs it itself).
- Tests: `stamps` (new: the check, the search, a CAM's missing stamps over
  the pretend board, Team Stump's code checking ours and running for a
  computer Stump); `screens` (both stamp rows).

## v0.3.0-beta.19

Caught up with SandBox_Stump_On 1.0.0-beta.82 (Team Stump's Arborist and
provisioner.py the reference):

- **Updates clean up after themselves** (Stump beta.74). Updating a CAM now
  removes the files an earlier release put there and this one no longer has
  (the list the bundle carries: `flasher_ui.py`, the native ed25519 module),
  and names them. Only those: settings, identity, data and packs are never
  touched, nor a file inside a pack's folder.
- **Its packs, on their own** (beta.75). A CAM's row *Its packs* reads what
  the board has, then shows each pack here and each one it has, with the
  version on it: **A** installs, updates or installs again, **X** removes and
  asks whether what the pack keeps goes too (its saved data, Tools section,
  home files, theme). Every install records the pack in its plugin folders
  (`.from_pack`, as Team Stump writes it), so it's updated and removed whole;
  a pack from before shows its version as not recorded. As many packs as
  there are. A pack's setup question that isn't marked advanced gets its
  default where the board has none (Bavard's "talk from the start": off), as
  Arborist does.
- **This handheld's Stump's packs** go through Team Stump's own code (its
  clone's provisioner.py, as `--packs FOLDER`): the same page, install,
  update, remove, nothing else asked or changed. With a clone older than
  beta.75, the page is as before (checked, then added by an Update).
- **A Stump's identity, kept in a file** (beta.76): *Save its identity* and
  *Bring back a saved identity*, for a CAM and for this handheld's Stump.
  The file is Team Stump's `<its name>.stump-identity` (each side reads the
  other's: tested), written in your home folder for you only, never over
  another one. Bringing one back takes the file, or an old Stump's folder
  (X in it), and saves the identity it had first. Only the identity: its
  settings stay. Whoever has the file can be that Stump: keep it safe.
- **The shelf at Sandbox 1.0.0-beta.82** (bundle, both images, Bavard 1.3,
  NomadNet, rnfs, Simple, Tavern), the handheld's Sandbox at 2.5.2-b.62,
  FireFly's at 0.9.6. **Meter 1.3 and Marco Polo 1.0 are left off**: in the
  b82 release their files don't match their own hashes (Team Stump's checker
  only warns; Arborist and this refuse). A pack that fails its check is now
  left off a shelf copy, said and noted, instead of the whole release being
  refused.
- Checked against b82 with no change needed: Team Stump's wizard with the
  form's answers (the handheld's Stump), the boot report, packed text (the
  Stump's business: nothing for a CAM's setup).
- From an independent review, before release: a pack's record is read from
  the board, so only the pack's own places on the card are taken from it
  (`tools/<name>`, files under `home/`, removed one by one): a crafted one
  can't empty the card. "Delete what it keeps too?" starts on *Keep them*.
  A board's identity that won't read back is never taken for none (nothing
  written); a different mailbox key alone is saved first too. On the
  handheld the identity it had is saved under a name never used before (two
  restores in a minute kept both). A pack's setup question with a bad
  default stops it before anything is copied. fservbot and stumpid are never
  offered for removal, whatever shelf copy. The handheld's packs are read in
  the background.
- Tests: `identity` (new: the pretend board, damaged files, an old folder,
  Team Stump's code reading ours and ours theirs); `stump` (retired files,
  not inside a pack); `screens` (the packs page on a CAM: install, record,
  update, remove with and without what it keeps; a pack installed by hand;
  the handheld's packs and identity by Team Stump's code); `handheld` (Team
  Stump's real code on a computer Stump's folder); `shelf` (a broken pack
  left off).

## v0.3.0-beta.18

Caught up with SandBox_Stump_On 1.0.0-beta.63 to 67 (Team Stump's Arborist
the reference, as before):

- **Updating a Stump on a full board** (Stump beta.65, kit finding 15: a
  WROVER with packs stopped with `OSError: 28`). Like Arborist now: a file
  already on the board and the same isn't written again (updates are faster
  too); the room an update needs is worked out first, the safe leftovers
  cleared if it's short (a write cut short, an old .py beside its .mpy),
  and still short it stops before writing anything and says what takes the
  room; filling up while writing is said in plain words, the old file kept.
  Packs' files go the same way.
- **Its number, for every Stump** (beta.64): 2 to 254, 4 by default, its own
  Wi-Fi at 192.168.<number>.1 in a chain or not (on its own it used to be
  192.168.4.1 whatever the number); asked once in the form, not per chain
  choice (members were 5 to 254, the first always 4). The Heltec on its
  Wi-Fi follows (.200), and the end of a setup gives that address. A
  release before beta.64 keeps number 4 on its own: refused otherwise.
- **Its address in its Wi-Fi's name** (`SSID_INCLUDE_IP`), a choice: the name
  with the address counted, refused over 32 characters (the Stump would cut it).
- **Its language** (beta.67, `DEFAULT_LANG`: Français, English, Español;
  French by default): for visitors who haven't picked one and for what's
  posted for everyone. Read back in Its settings. (This handheld's own
  Stump: Team Stump's computer wizard doesn't ask it yet; /admin sets it.)
- **The shelf at Sandbox 1.0.0-beta.67**: its bundle, both images, its packs
  (Bavard 1.2, NomadNet 1.2, Tavern 1.2, rnfs 1.2, Simple 1.0).
- Checked against b67 with no change needed: Team Stump's wizard with the
  handheld's answers; the handheld repo's cockpit and FireFly against real
  b67 Stumps (ops and mods, beta.64, show in /names as the Stump writes them).

## v0.3.0-beta.17

- **Its packs, a page of their own** (This handheld → its Stump → Its
  packs): every pack its wizard offers, however many, a check box each;
  those its Stump has are marked installed (each Update brings them up to
  date); the ones checked are added by an Update that keeps its settings,
  identity, files and chain, each pack with its own settings at their
  defaults. Before, packs were only switches inside the new-answers form.
- **The Provisioner's page, when it's newer than the shelf** (run from a
  clone of main, say): the top line says this one is newer than any copy on
  the shelf, the shelf's copy is marked "older: A goes back to it" (not "the
  newest"), and A asks "Go back to the Provisioner …?".

## v0.3.0-beta.16

- **The sudo password, typed on the Provisioner's screen.** Its installers
  use sudo (its own: the serial rule, the Ports entry; FireFly's and the
  handheld Stump's: packages and more). Over SSH sudo asks in the terminal;
  from the Provisioner nobody could answer, so updating it from itself
  stopped with "sudo requires a password". Now, when sudo would ask, the
  Provisioner asks first (its keyboard), and the installer gets it through
  sudo's askpass helper (`sudo -A`): a file only this user can read,
  removed when the installer ends; never piped into `sudo -S`, never
  logged. A wrong one stops the installer before it changes anything.
- **install.sh asks for sudo only for what changes**: the udev rule, the
  dialout group, the Ports entry, each compared first. An update that
  changes none of them (most) needs no password at all.
  `install.sh --needs-sudo` says whether it would ask.
- FireFly's and the handheld Stump's installers take the password the same
  way from their next releases (`sudo -A` when given the helper).

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
