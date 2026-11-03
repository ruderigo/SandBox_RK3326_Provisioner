# Plan: the RK3326 Provisioner

One app that turns an RK3326 handheld (R36MAX, R36S) into a workbench for
the boards around the Stump/FireFly mesh: plug an ESP32 board into the hub,
it's recognised, it's offered the firmware that fits, flashed, checked and
set up, **offline**, from the gamepad. It fuses:

- **Team Stump's Provisioner** (SandBox_Stump_On `provisioner.py`): the board
  jobs of the mesh (Heltec V3 as an RNode, the CAM);
- **R36S-ESP32-Flasher**: flashing from the handheld itself, offline, with a
  bundled esptool, a SHA-256 catalogue and a read-back check;
- **the S3 USB Wi-Fi adapter** asked for in the memo of 2026-11-02 (FireFly's
  Wi-Fi on handhelds whose Wi-Fi dongles have no driver).

Priority: **the handheld, as an EmulationStation Ports entry**. The same
code runs on a computer (a window, or `list` / `catalog` / `flash` on the
command line) since it costs nothing extra.

## Decisions (2026-11-02)

| | |
|---|---|
| Repo | this one, SandBox_RK3326_Provisioner; the S3 adapter firmware in `s3_usb_wifi/` here (ESP-IDF, its own CI jobs), kept in this sandbox rather than a repo of its own |
| First version | S3 adapter + Heltec RNode + the classic-ESP32 catalogue; the full CAM Stump later (Arborist covers it from a computer) |
| Where | the handheld first; a computer gets the same app for free |
| Not carried over | the flasher's *SIGINT ESP32 Link* image (scans nearby Wi-Fi/BLE devices and reads them: device tracking, out of scope; prebuilt, no source). Its `app.py` code is not reused (no licence in the fork): only its approach, and the upstream libraries it bundles (esptool GPL-2, pyserial BSD, intelhex BSD) with their licences |

## How it works

- **Boards** are seen as serial ports (`/sys/class/tty`), with their USB chip.
  Nothing is touched until you choose one: identifying it (esptool
  `flash_id`) resets it. A board is named by its **USB id and its chip**:
  a CP2102 with an ESP32-S3 is a Heltec V3; with a classic ESP32, a dev board.
- **A port another program has open asks first** (the Stump has the
  Heltec's port open as its radio: going on resets it under the Stump).
- **The catalogue** (`firmware/catalog.json`): each image pinned by SHA-256,
  with the boards it fits, *app only* (written to the app slot after the
  board's partition table is checked) or *full* (erases first, asks with
  "No" highlighted), its licence and source.
- **Flashing**: the bundled esptool as its own program, progress on screen,
  a slower retry, then a read-back (`verify_flash`).
- **The screens** are FireFly's look (palette, DejaVu Sans Mono from the
  cockpit's font file, keycap hints), drawn through the system's SDL2 with
  KMSDRM like the Stump cockpit (no pygame: the black screen of v1.8); the
  gamepad read from evdev with the R36MAX's codes. 720x720, scaled to fit
  any other screen.

## Steps

Making a Stump is the Provisioner's main job (2026-11-02): it comes first.

- [x] v0.1.0: the app, board detection, busy-port guard, catalogue,
      flashing with progress and read-back, erase, serial log; classic ESP32
      (WLED, MicroPython); the Ports launcher and installer; tests; CI
- [x] **v0.2.0: Make a Stump (Freenove CAM)**: New / Update / Settings /
      Check as in Arborist, offline, from the gamepad; FireFly's keyboard;
      Team Stump's release bundle, checked; this handheld's Stump shown;
      tests on Team Stump's pretend board with the real bundle
- [ ] **The Heltec for that CAM**, offline. Team Stump keeps the RNode
      firmware out of their releases (beta.48: request 2 on hold); they'll
      publish its upstream version, SHA-256 and flash layout. With those, the
      Provisioner fetches that upstream release and its source itself (GPL-3,
      side by side, full source shipped), bundles RNS as published and runs
      `rnodeconf` as its own program
- [ ] **v0.3.0: this handheld's Stump, installed or updated from the
      gamepad**: possible now: Team Stump's `provisioner.py --pc --answers
      FILE.json` (beta.48) runs their wizard from a form's answers
- [x] **The S3 USB Wi-Fi adapter firmware** (`s3_usb_wifi/`): ESP-IDF
      5.3, esp_tinyusb, CDC-NCM, NAT, our own DHCP; in the catalogue.
      **2026-11-03: it's the handheld's Wi-Fi card** (0.2.0), not the memo's
      Stump-only link: the S3 is the handheld's router and DNS (a DNS
      forwarder), up to 8 saved networks, an API to join and forget
      (`docs/NOTE_TEAM_FIREFLY.md` tells Team FireFly)
- [x] **The Provisioner's S3 USB Wi-Fi page**: the adapter shown on the
      boards screen; its networks, join with a password on FireFly's
      keyboard, forget; tested against a pretend S3 (`tests/fake_s3.py`).
      **Bench test pending** (below)
- [ ] The adapter's ECM build (the memo's fallback), if a handheld lacks `cdc_ncm`
- [ ] Your own images: `.bin` files in `/roms/ESP32-Firmware/` (app only)
- [ ] 640x480 layout tuned for the R36S (it's scaled for now)
- [x] The bundle from its own release file (Team Stump's beta.48)

## Bench (on the R36MAX)

1. Install: `bash install.sh`; Ports → RK3326_Provisioner opens, the gamepad
   moves, SELECT+START closes it.
2. A classic ESP32 on the hub: identified, WLED flashed and verified.
3. The Heltec in use by the Stump: shown as *in use by stump_pc.py*, and
   choosing it asks first.
4. The Freenove S3: identified with its PSRAM; the CH343 port flashes it
   (needs the CH343's driver in dArkOS's kernel: `dmesg | tail` on plug-in).
5. **Make a Stump** on it: the form, about five minutes, then its Wi-Fi
   from a phone and `/admin` with the password chosen. Then Update, its
   Settings and Check.
   **Passed 2026-11-02** (v0.2.0): a CAM made by the handheld, linked to its
   Heltec V3 (set up by Team Stump's Provisioner on a computer), visible to
   visitors, to Android clients and to FireFly on the R36MAX.
6. **The S3 as the R36MAX's Wi-Fi card** (`s3_usb_wifi/README.md`, *The
   bench test*): flashed from the Provisioner through the CAM's UART port,
   then its USB port into the R36MAX: 10.77.0.2/24 within 10 s, `cdc_ncm` in
   dmesg; the Provisioner's S3 USB Wi-Fi page joins the home Wi-Fi with its
   password (*internet OK*); default route and DNS 10.77.0.1; a Stump's
   `/node.json` through it; unplug and replug. Then LoRa, and the setup page
   from a phone.
   **2026-11-03, v0.3.0-beta.2 / S3 0.2.1, with the Blueway still in:** `usb0`
   10.77.0.2/24 by DHCP; the network joined from the Provisioner's page;
   default route via 10.77.0.1 (metric 100, ahead of `wlan0`'s 600); DNS
   10.77.0.1 first; `curl --interface usb0 https://example.com`: HTTP/2 200
   (DNS, NAT and TLS through the S3). Found on the way: 0.2.0's empty MAC
   string ("bind() failure" in `cdc_ncm`), and the read-back after flashing.
   ES's network screen doesn't list it (it shows `wlan0` only). Next: without
   the Blueway (does ES let the scraper and updates run?), replug, LoRa.
