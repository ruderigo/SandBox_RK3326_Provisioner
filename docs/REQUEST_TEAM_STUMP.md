# Request to Team Stump: three things for making Stumps from the handheld

> **Answered in SandBox_Stump_On 1.0.0-beta.48 (2026-11-03):**
> 1. **Done:** `Stump-<release>.bundle` on each release, in `SHA256SUMS`, with
>    `default_ssid` in its header. The Provisioner takes it from there now.
> 2. **On hold on their side:** `--heltec-for-cam` is a placeholder (exits 2).
>    The RNode firmware stays out of their releases (GPL-3); they'd publish its
>    upstream version, SHA-256 and flash layout. See the plan for what we do.
> 3. **Done:** `provisioner.py --pc --answers FILE.json` (and
>    `--answers-template`), keyed by each question's own text.

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
  SHA-256, **and the exact source it was built from** (that version's
  source archive), and its flash layout (files and offsets for
  `esptool write_flash`);
- the exact non-interactive `rnodeconf` commands after flashing: the device
  provisioning that `--autoinstall` does (EEPROM: product, model, hardware
  revision, signing), then the settings your route sets: radio (`--freq
  --bw --txp --sf --cr`), the access code, and its Wi-Fi as a station on
  the CAM's own network at its fixed address (`-w STATION --ssid … --psk …`).

A `provisioner.py --heltec-for-cam PORT --answers FILE.json` mode would do
just as well; we'd call it.

**Licences, and how we'd keep them apart.** RNode firmware is GPL-3.0;
`rnodeconf` is part of RNS, under the Reticulum License (MIT's terms plus two
restrictions: no systems built to harm people, no use in creating AI/ML
models). The Provisioner is MIT. We keep them as separate programs side by
side (GPL-3's "aggregate"), as esptool (GPL-2.0) already is:

- the RNode binary ships with **its full source** for that exact version in
  our release (not only a link), and its GPL-3.0 text;
- RNS is bundled **as published** (its wheel, its licence), and `rnodeconf`
  is **run as its own program**: none of its code is copied into ours;
- each licence sits next to its files (`firmware/licenses/`,
  `vendor/LICENSES/`).

If you'd rather a different arrangement (e.g. you publish the firmware and
its source together and we fetch both by SHA-256), tell us.

**Why:** with this the handheld makes the whole CAM bundle, Freenove and
Heltec, in the field.

## 3. The computer wizard, answered from a file

**Ask:** `provisioner.py --pc --answers FILE.json`: the same questions as the
`--pc` wizard (folder, chain and its secret, the Heltec, start at login),
answered from a file, nothing asked on the terminal.

**Why:** the Provisioner shows the handheld's own Stump (release, name,
chain) and should install or update it from the gamepad too. R36MAX-Stump's
`install.sh` runs your wizard, which needs a terminal today.

## 4. The passwords in `final_firmware/config.py` (asked 2026-11-03)

**Found:** your design is one password: /admin takes the fserv operator
password unless `AUTH_ADMIN_PASSWORD` is set (stumpid `check_admin_password`;
its plugin.json: "one password, two capabilities"). The `--pc` wizard asks
the fserv one, but writes `AUTH_ADMIN_PASSWORD` only when "Change any of
those now?" gets a yes; otherwise `config.py` keeps the repo's, and in
`final_firmware/config.py` it isn't blank (a real password; so is
`FSERVBOT_OP_PASSWORD`). A computer Stump set up with the defaults then has
/admin on that password, not the one the wizard asked. The CAM bundles are
fine: their template is blanked, and we refuse one that isn't.

**Ask:**
1. `final_firmware/config.py` with both passwords blank (as the bundle's
   template and stumpid's plugin.json have them).
2. Optionally, the wizard says /admin takes the fserv operator password.

**Until then:** our answers say yes and give /admin's blank, and both R36MAX-Stump's
`install.sh` (v2.4.0-r36max) and the RK3326 Provisioner clear a repo
`AUTH_ADMIN_PASSWORD` left after the wizard, with your `settings.write_config`.

## Not asked

Nothing in the firmware changes. We follow your releases: a new bundle is
`python3 scripts/fill_shelf.py` here (or the handheld fetches it), then our tests.
