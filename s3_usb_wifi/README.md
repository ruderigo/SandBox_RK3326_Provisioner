# FireFly S3 USB Wi-Fi

Firmware that makes an ESP32-S3 (the **Freenove ESP32-S3 WROOM CAM**, or any
S3 with its native USB wired out) the **Wi-Fi card of an RK3326 handheld**
whose own Wi-Fi dongle has no driver.

Plug it in, open the Provisioner's **S3 USB Wi-Fi** page, pick a network and
type its password with the gamepad. The handheld is then **on that network**,
like with a Wi-Fi dongle: it gets its own address there, SSH reaches it,
FireFly and Reticulum find their peers, and a Stump on the handheld serves
its portal. The S3 remembers the networks and rejoins by itself.

> **Sandbox, v0.3.0.** It builds, and its parts that don't need a board are
> tested. 0.2.x (a router, not a bridge) got the R36MAX online but hid it
> from its network; 0.3.0 bridges instead. The bench test is below.

## How it works

```
handheld usb0 ══USB══ S3 ))) Wi-Fi ))) your router, phones, Stumps
192.168.0.x   (the handheld's own address on your network)
```

The S3 joins the Wi-Fi and **bridges** it to its USB port. Frames go across
unchanged, so the handheld is a device on that network itself.

- **The USB device:** a CDC-NCM network card. Every Linux kernel has its
  driver (`cdc_ncm`), so there's no driver to install. A Wi-Fi dongle like
  the Blueway is different: the handheld drives it as `wlan0`, which needs a
  driver for its chip.
- **The handheld's address:** from your network's own DHCP (your router),
  like any device there.
- **Its MAC:** the S3's own Wi-Fi MAC. Wi-Fi allows one MAC per client, so the
  S3 and the handheld share it. The S3 has no address of its own on the
  network.
- **The link:** the handheld sees its link up only while the S3 is on a
  network. Joining one makes its network manager ask for an address there;
  leaving one drops it.
- **Choosing a network:** a serial port on the same USB cable (`/dev/ttyACMx`,
  "FireFly S3 USB Wi-Fi"). The Provisioner talks to the S3 through it.

ES's own Wi-Fi screen doesn't list it: to the handheld it's a wired card
(`usb0`), not `wlan0`. If the handheld also has a working `wlan0`, both are on
the network; NetworkManager prefers the wired one for its default route.

## Choosing a network: the Provisioner's page

In EmulationStation: **Ports → RK3326_Provisioner**. With the S3 plugged in by
its USB port, **S3 USB Wi-Fi** is the first row, showing what it's on. Press
**A** to open its page:

- the networks the S3 sees, strongest first, with signal bars and tags:
  *connected*, *saved*, *open* or *password*, and saved ones that are out of
  range;
- **A** joins one. A network that needs a password opens FireFly's keyboard
  (**A** types, **B** deletes, **X** space, **Y** shift, **L/R** pages,
  **START** joins). An open or saved network joins straight away;
- the top shows *Joining …*, then *Connected to …*, the handheld's address on
  that network and *internet OK*, or why it failed (*wrong password?* asks
  for the password again next time);
- **Y** forgets a saved network (after asking), **X** looks again, **B** goes
  back.

The S3 keeps up to **8 networks** in its own memory, most recent first. On
power-up it joins whichever of them is in range, so it works on any handheld
it's plugged into, with no page needed.

## Without the Provisioner

**From a phone:** an open Wi-Fi called **`FireFly-S3-xxxx`** opens when no
network is saved, after two minutes without a network, or when **BOOT is held
for a second within four seconds of power-up**. Holding it *during* power-up
starts the chip's download mode instead. Join it and the setup page opens, or
go to `http://10.77.1.1/`. It lists networks, joins and forgets them. The
`FireFly-S3-…` Wi-Fi closes a minute after the S3 is on a network.

**From a terminal on the handheld:** the control port speaks one JSON line
each way, the same protocol the Provisioner uses (`main/ctl_core.h`):

```sh
port=/dev/ttyACM1     # the "FireFly S3 USB Wi-Fi" one: ls -l /dev/serial/by-id/
stty -F $port raw -echo; exec 3<>$port
echo '{"id":1,"cmd":"status"}' >&3; head -1 <&3
echo '{"id":2,"cmd":"join","ssid":"MyNetwork","password":"its-password"}' >&3; head -1 <&3
```

| Command | |
|---|---|
| `status` | `state` (`idle` / `joining` / `connected`), `ssid`, `rssi`, `channel`, `target`, `error` (`wrong_password`, `not_found`, `security_mismatch`, `failed`), `mac`, `link`, `usb`, `setup_ap`, `frames` (counters), `firmware` |
| `scan` | `[{"ssid", "rssi", "open", "saved"}]`, strongest first |
| `saved` | the saved networks, most recent first |
| `join` | `ssid`, `password` (empty for an open network; left out, a saved network keeps its own): remembers it and joins it now |
| `forget` | `ssid`: forgets it; no `ssid`: forgets all |

Answers are `{"id":…,"ok":true,"data":…}` or `{"id":…,"ok":false,"error":"…"}`.
The setup page's HTTP API (`/status.json`, `/scan.json`, `/networks.json`,
`POST /join`, `POST /forget`) answers on the setup AP only.

## Flashing it

The Freenove board has two USB-C ports: **USB** (the S3's native USB, which
becomes the Wi-Fi card) and **UART** (a CH343 serial chip). **Flash through
the UART port**, then plug the **USB** port into the handheld.

- **From the handheld:** the Provisioner offers *USB Wi-Fi adapter* for an
  ESP32-S3 on its UART port. It erases the board and writes the image, so a
  Stump on that board is gone.
- **From a computer**, with esptool:

  ```sh
  esptool.py --chip esp32s3 --port /dev/ttyACM0 erase_flash
  esptool.py --chip esp32s3 --port /dev/ttyACM0 write_flash 0x0 s3-usb-wifi-0.3.0.bin
  ```

  The image is `firmware/s3_usb_wifi/s3-usb-wifi-<version>.bin` in this
  repository (one file, written at 0x0). Its SHA-256 is in
  `firmware/catalog.json`.

To put a Stump (or anything else) back on the board, flash it through the
UART port as usual. If the board doesn't answer, hold BOOT and tap RESET. The
S3's log (115200) is on the UART port too. Plug both ports in to watch it
while the USB port works.

## The bench test (R36MAX)

Plug the board's **USB** port into the handheld:

| | Check | Expect |
|---|---|---|
| 1 | `dmesg \| tail` | `cdc_ncm` binds *FireFly S3 USB Wi-Fi* (`usb0`), and `cdc_acm` gives it a `ttyACM` |
| 2 | Provisioner → S3 USB Wi-Fi | your networks; join yours with its password: *Connected*, the handheld's address, *internet OK* |
| 3 | `ip -4 addr show usb0` | an address from your router (192.168.0.x), not 10.77.x |
| 4 | from your computer: `ssh ark@<that address>` (or `r36max.local`) | it answers, **with the Blueway unplugged** |
| 5 | FireFly on the handheld | finds the others on that network |
| 6 | the handheld's Stump | its portal opens from a phone on that network |
| 7 | unplug, replug (either way round, handheld on or off) | back as in 3, rejoined by itself |
| 8 | | LoRa unaffected |
| 9 | the setup page from a phone | lists networks, saves one, joins it |

## Building it

ESP-IDF **v5.3** (5.3.2 is what the CI uses), target esp32s3. Everything else
is in `components/`, and the component manager stays off:

```sh
. $IDF_PATH/export.sh
bash build.sh          # host tests, build, dist/s3-usb-wifi-<version>.bin + SHA256SUMS
```

The image comes out the same on any machine (paths are mapped out of it). The
CI rebuilds it and checks it's the one in `firmware/`.
`host_tests/image_fingerprint.sh` shows what went into a build, to compare
two that differ.

Tests that need no board:
- `bash host_tests/run.sh`: the control protocol (parsing, escapes, UTF-8,
  bad lines, answers), the saved-networks list, the setup AP's DHCP and
  captive DNS, the helpers.
- `sudo bash host_tests/dhcp_clients.sh`: the setup AP's DHCP against real
  Linux clients (dhclient, dhcpcd, busybox udhcpc) in a network namespace.
- The Provisioner's page is tested against `tests/fake_s3.py`, a pretend S3
  on a pseudo-terminal.

## Limits

- **NCM only.** ECM needs its own build of the USB stack; it comes if a
  handheld turns up without `cdc_ncm`.
- The S3's USB is full-speed (12 Mbit/s), so expect a few Mbit/s: fine for
  FireFly, SSH, scraping and updates, slow for big downloads.
- 2.4 GHz only (the ESP32-S3's radio); WPA2 and WPA3 personal, no enterprise
  (802.1X), no hidden networks.
- **One device behind it:** the handheld, with the S3's MAC. If the handheld
  changes its interface's MAC (MAC randomisation), its replies won't come
  back; the S3 logs it.
- Saved passwords are in the S3's flash unencrypted, like most ESP32 devices:
  anyone with the board in hand can read them.
- With no network saved, it doesn't join anything by itself: an open Stump
  hotspot is joined once from the page (one press), then remembered.

## Files

| | |
|---|---|
| `main/` | `usb_net.c` (the NCM card, bridged to the Wi-Fi), `ctl.c` + `ctl_core.c` (the control port and its protocol), `api.c` (what both the control port and the setup page say), `wifi_link.c` (the saved networks, joining, the setup AP), `netsvc.c` (the setup AP's DHCP and captive DNS), `web.c` + `setup.html`, and `dhcp_core.c` / `util_core.c` / `ctl_core.c` (no ESP-IDF: host-tested) |
| `components/` | esp_tinyusb 3.0.0 and TinyUSB, vendored ([VENDORED.md](components/VENDORED.md)) |
| `host_tests/` | the tests above |
| `build.sh` | the build, and the image for 0x0 |

## Licences

This firmware's code is **MIT**, like the rest of the repository. Built into
the image, each under its own licence: ESP-IDF (Apache-2.0, with lwIP
BSD-3-Clause and FreeRTOS MIT), esp_tinyusb (Apache-2.0), TinyUSB (MIT).
Their texts ship with the image (`firmware/licenses/`, listed in
`S3-USB-WiFi-NOTICE.txt`). The bridge follows the ESP-IDF `tusb_ncm` example
and Espressif's [esp-iot-bridge](https://github.com/espressif/esp-iot-bridge)
(Apache-2.0); no code is copied from either.
