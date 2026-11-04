# What's in it, and whose

| | |
|---|---|
| `provisioner/` | the app: boards and flashing (`boards`, `flasher`, `catalog`, `images`), the Stump on a board (`stump`, `packs`), the shelf (`shelf`, `installers`), this handheld's Stump (`handheld`), the serial log, the S3 adapter's page (`s3wifi`), the screens (`ui/`) |
| `scripts/fill_shelf.py` | fills `firmware/shelf/` from the Official and Sandbox releases |
| `vendor/` | esptool 4.8.1 (GPL-2.0), pyserial (BSD-3), intelhex (BSD): run as they are; licences in `vendor/LICENSES/` |
| `firmware/` | the catalogue; WLED 16.0.1 (EUPL-1.2) and MicroPython 1.29.0 (MIT), official builds, licences in `firmware/licenses/` |
| `firmware/shelf/` | the shelf it carries: the Stump (Official and Sandbox bundles and packs; MIT, MicroPython MIT), R36MAX-Stump, FireFly; each with where it came from (`meta.json`) |
| `firmware/s3_usb_wifi/` | the S3 USB Wi-Fi adapter's image, built from `s3_usb_wifi/` (the CI checks it's that source's) |
| `s3_usb_wifi/` | that firmware's source (ESP-IDF v5.3; esp_tinyusb Apache-2.0 and TinyUSB MIT vendored), its tests and build |
| `tests/stump_fixtures/` | Team Stump's pretend board and four Stump modules, for the tests (MIT, credited) |
| `assets/cockpit_font.bin` | DejaVu Sans Mono, pre-rendered (the Stump cockpit's; `FONT_LICENSE`) |

## Licences

The Provisioner's own code (`provisioner/`, `scripts/`, `tests/`,
`s3_usb_wifi/main/`, the launcher and scripts) is **MIT**
([LICENSE](LICENSE)). Everything else keeps its own licence, next to its
files, and is shipped **side by side as separate programs or data**, never
merged into our code (the S3 image is the one exception: it's built with
ESP-IDF's Apache-2.0 and MIT parts, which allow that):

| | Licence | How it's used |
|---|---|---|
| esptool, pyserial, intelhex | GPL-2.0, BSD-3, BSD | run as their own program / imported as published (`vendor/LICENSES/`) |
| WLED, MicroPython | EUPL-1.2, MIT | images written to boards (`firmware/licenses/`) |
| The Stump bundles and their packs (Tavern, rnfs), test fixtures | MIT (Team Stump) | copied to boards / used by the tests (`firmware/shelf/stump/`) |
| FireFly RK3326 | MIT (Team FireFly) | its release zip, installed by its own installer (`firmware/shelf/firefly/`) |
| R36MAX-Stump (the handheld's Stump) | ours, no licence file yet | its release tarball, run by its own installer (`firmware/shelf/handheld/`) |
| The S3 USB Wi-Fi image | MIT (ours), built on ESP-IDF (Apache-2.0, lwIP BSD-3, FreeRTOS MIT), esp_tinyusb (Apache-2.0), TinyUSB (MIT) | an image written to boards; licences in `firmware/licenses/` (`S3-USB-WiFi-NOTICE.txt`), source in `s3_usb_wifi/` |
| *Coming:* RNode firmware | GPL-3.0 | an image written to the Heltec, shipped with **its full source** for that version |
| *Coming:* RNS (`rnodeconf`) | Reticulum License (MIT terms + no systems built to harm people, no use in creating AI/ML models) | bundled as published, run as its own program |

The approach (bundled esptool, offline catalogue, read-back) comes from
[R36S-ESP32-Flasher](https://github.com/ruderigo/R36S-ESP32-Flasher); the
mesh jobs from Team Stump's Provisioner in
[SandBox_Stump_On](https://github.com/ruderigo/SandBox_Stump_On).
