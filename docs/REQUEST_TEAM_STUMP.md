# Request to Team Stump: three things for making Stumps from the handheld

From Team RK3326 Provisioner · 2026-11-02 · about
[SandBox_RK3326_Provisioner](https://github.com/ruderigo/SandBox_RK3326_Provisioner) v0.2.0

## Where we are

The RK3326 Provisioner (an EmulationStation app on the R36MAX) now makes a
Stump on a Freenove ESP32-S3-CAM **offline, from the gamepad**: New, Update,
Settings and Check, the same steps as Arborist, ported to Python (raw REPL,
3 KB chunks to `<file>.part`, SHA-256 on the board, rename; settings by the
firmware's own `settings.write_config`; the same rules as `settingsFrom`).

It carries **your release, unchanged**: the bundle inside
`Arborist-1.0.0-beta.47.html`, the page checked against the release's
`SHA256SUMS`, every file against its SHA-256, MicroPython against your
pinned `67c19ae1…`, and the template against the names and passwords that
must never be in it. Tested on your `tests/arborist/board_sim.py` (copied,
credited, MIT), run by CPython standing in for MicroPython's Unix port.

## 1. The bundle as its own release file

**Ask:** attach `Stump-<release>.bundle` to each release — the blob
`build_arborist.pack()` already makes, byte for byte — and list it in
`SHA256SUMS`. Please also put the default Wi-Fi name in its header
(`"default_ssid": DEFAULT_SSID`).

**Why:** today we take it out of the Arborist page
(`scripts/fetch_stump_bundle.py`), which depends on the page's markup
(`<script id="payload">`, `var SSID = "…"`). A file of its own is a stable
interface, and nothing else changes for you.

## 2. The Heltec for a CAM, without a terminal and offline

**Ask:** what *A Heltec for a CAM* does, in a form the handheld can run with no
one typing into rnodeconf and no internet:

- the RNode firmware build the CAM's Heltec runs, as a release asset with its
  SHA-256 (GPL-3: we ship it with its licence and source link), and its
  flash layout (files and offsets for `esptool write_flash`);
- the exact non-interactive steps after flashing: the device provisioning
  that `--autoinstall` does (EEPROM: product, model, hardware revision,
  signing), then the settings your route sets: radio (`--freq --bw --txp
  --sf --cr`), the access code, and its Wi-Fi as a station on the CAM's
  own network at its fixed address (`-w STATION --ssid … --psk …`).

A `provisioner.py --heltec-for-cam PORT --answers FILE.json` mode would do
just as well; we'd call it.

**Why:** with this the handheld makes the whole CAM bundle, Freenove and
Heltec, in the field.

## 3. The computer wizard, answered from a file

**Ask:** `provisioner.py --pc --answers FILE.json`: the same questions as the
`--pc` wizard (folder, chain and its secret, the Heltec, start at login),
answered from a file, nothing asked on the terminal.

**Why:** the Provisioner shows the handheld's own Stump (release, name,
chain) and should install or update it from the gamepad too. R36MAX-Stump's
`install.sh` runs your wizard, which needs a terminal today.

## Not asked

Nothing in the firmware changes. We follow your releases: a new bundle is
`python3 scripts/fetch_stump_bundle.py v<release>` here, then our tests.
