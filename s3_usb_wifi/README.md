# FireFly S3 USB Wi-Fi

Firmware that makes an ESP32-S3 (the **Freenove ESP32-S3 WROOM CAM**, or any
S3 with its native USB wired out) the **Wi-Fi card of an RK3326 handheld**
whose own Wi-Fi dongle has no driver.

Plug it in, open the Provisioner's **S3 USB Wi-Fi** page, pick a network,
type its password with the gamepad, and the handheld is online through it.
It remembers the networks and rejoins by itself next time.

> **Sandbox, v0.2.0.** It builds and its DHCP server passes against three
> real Linux DHCP clients. It hasn't met a handheld yet: the bench test is
> below.

## How it works

```
handheld ──USB── S3 ))) Wi-Fi ))) your router / a Stump
10.77.0.2        10.77.0.1
```

The S3 does the Wi-Fi itself: it scans, joins and keeps the connection up.
To the handheld it's a USB Ethernet card (CDC-NCM): every Linux kernel already
has its driver (`cdc_ncm`), so there's no driver to install. A Wi-Fi dongle
like the Blueway is the other way round: the handheld drives it as `wlan0`,
which needs a driver for its chip.

The two ends of the USB link are 10.77.0.1 (the S3) and 10.77.0.2 (the
handheld). You never type them. The Provisioner finds the S3 there by itself.

| | |
|---|---|
| USB device | **CDC-NCM** on the S3's native USB port |
| The handheld gets | **10.77.0.2/24** by DHCP, with **the S3 as its router and DNS** (the default route is also in option 121) |
| Its internet | through the S3, NATed onto whatever network the S3 joined |
| DNS | the S3 passes the handheld's questions on to the joined network's DNS (no network yet: an immediate "no answer") |
| IPv6 | none |

None of that changes when the S3 moves from one network to another: the
handheld is never told anything new. If the handheld also has a working
`wlan0`, its network manager decides which default route wins (NetworkManager
prefers wired, so it's the S3).

Nothing on the Wi-Fi side can reach the handheld or the S3's USB side, even
by routing through the S3: the S3 drops it.

## Choosing a network: the Provisioner's page

In EmulationStation: **Ports → RK3326_Provisioner**. With the S3 plugged in,
**S3 USB Wi-Fi** is the first row, showing what it's connected to. Press
**A** to open its page:

- the networks the S3 sees, strongest first, with signal bars and tags:
  *connected*, *saved*, *open* or *password*, and saved ones that are out of
  range;
- **A** joins one. A network that needs a password opens FireFly's keyboard
  (**A** types, **B** deletes, **X** space, **Y** shift, **L/R** pages,
  **START** joins). An open or saved network joins straight away;
- the top shows *Joining …*, then *Connected to … · internet OK*, or why it
  failed (*wrong password?* asks for the password again next time);
- **Y** forgets a saved network (after asking), **X** looks again, **B** goes
  back.

The S3 keeps up to **8 networks** in its own memory, most recent first. On
power-up it joins whichever of them is in range, so it works on any handheld
it's plugged into, with no page needed. With none in range, it joins **an open
Stump hotspot** by itself: an open network whose gateway answers
`/node.json` with an `"lxmf"` key.

## Without the Provisioner

- **From a phone:** an open Wi-Fi called **`FireFly-S3-xxxx`** opens when no
  network is saved, after two minutes without a network, or when **BOOT is
  held for a second within four seconds of power-up** (holding it *during*
  power-up starts the chip's download mode instead). Join it and the setup
  page opens (or go to `http://10.77.1.1/`).
- **From the handheld's terminal**, the same page's API:

  ```sh
  curl http://10.77.0.1/status.json
  curl -d 'ssid=MyNetwork' -d 'password=its-password' http://10.77.0.1/join
  curl -d 'ssid=MyNetwork' http://10.77.0.1/forget
  ```

| | |
|---|---|
| `GET /status.json` | `ssid`, `rssi`, `ip`, `gateway`, `subnet` (null when not connected), `state` (`idle` / `joining` / `connected`), `target`, `error` (`wrong_password`, `not_found`, `security_mismatch`, `no_address`, `failed`), `dns`, `stump`, `firmware` |
| `GET /scan.json` | `[{"ssid", "rssi", "open", "saved"}]`, strongest first |
| `GET /networks.json` | the saved networks, most recent first |
| `POST /join` | `ssid`, `password` (empty for an open network; left out, a saved network keeps its own): remembers it and joins it now |
| `POST /forget` | `ssid`: forgets it; no `ssid`: forgets all |

POSTs are form-encoded and answer JSON with `Accept: application/json`. All of
this answers only on the USB side and the setup AP, never on the joined Wi-Fi.

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
  esptool.py --chip esp32s3 --port /dev/ttyACM0 write_flash 0x0 s3-usb-wifi-0.2.0.bin
  ```

  The image is `firmware/s3_usb_wifi/s3-usb-wifi-<version>.bin` in this
  repository (one file, written at 0x0). Its SHA-256 is in
  `firmware/catalog.json`.

To put a Stump (or anything else) back on the board, flash it through the
UART port as usual. If the board doesn't answer, hold BOOT and tap RESET. The
S3's log (115200) is on the UART port too.

## The bench test (R36MAX)

Plug the board's **USB** port into the handheld (its Blueway unplugged), then:

| | Check | Expect |
|---|---|---|
| 1 | `ip -4 addr` | a new interface (`usb0` or `eth…`) with **10.77.0.2/24** within 10 s |
| 2 | `dmesg \| tail` | `cdc_ncm` bound to *FireFly S3 USB Wi-Fi* |
| 3 | Provisioner → S3 USB Wi-Fi | your networks listed; join yours with its password: *Connected … internet OK* |
| 4 | `ip route`, `cat /etc/resolv.conf` | default via 10.77.0.1; nameserver 10.77.0.1 |
| 5 | `ping -c3 1.1.1.1`, `curl -I https://example.com` | answers: internet through the S3 |
| 6 | near a Stump, its hotspot | `curl http://<its gateway>/node.json` answers |
| 7 | unplug, replug (either way round, handheld on or off) | back as in 1, rejoined by itself |
| 8 | | LoRa unaffected |
| 9 | the setup page from a phone | lists networks, saves one, joins it |

## Building it

ESP-IDF **v5.3** (5.3.2 is what the CI uses), target esp32s3. Everything
else is in `components/`, and the component manager stays off:

```sh
. $IDF_PATH/export.sh
bash build.sh          # host tests, build, dist/s3-usb-wifi-<version>.bin + SHA256SUMS
```

The image comes out the same on any machine (paths are mapped out of it). The
CI rebuilds it and checks it's the one in `firmware/`.
`host_tests/image_fingerprint.sh` shows what went into a build, to compare
two that differ.

Tests that need no board:
- `bash host_tests/run.sh`: the DHCP server, the DNS forwarder's
  bookkeeping, the captive DNS, the saved-networks list, the helpers.
- `sudo bash host_tests/dhcp_clients.sh`: runs the firmware's DHCP code
  against **dhclient, dhcpcd and busybox udhcpc**, over a veth pair into a
  network namespace. It checks 10.77.0.2/24, the default route via
  10.77.0.1, 10.77.0.1 as DNS, and that renewals change nothing.
- The Provisioner's page is tested against `tests/fake_s3.py`, a pretend S3.

## Limits

- **NCM only.** ECM needs its own build of the USB stack; it comes if a
  handheld turns up without `cdc_ncm`.
- The S3's USB is full-speed (12 Mbit/s), so expect a few Mbit/s: fine for
  FireFly, scraping and updates, slow for big downloads.
- 2.4 GHz only (the ESP32-S3's radio); WPA2 and WPA3 personal, no enterprise
  (802.1X), no hidden networks.
- DNS over UDP only (no DNS over TCP from the handheld through the S3).
- Saved passwords are in the S3's flash unencrypted, like most ESP32
  devices: anyone with the board in hand can read them.

## Files

| | |
|---|---|
| `main/` | `usb_net.c` (NCM ↔ esp_netif), `netsvc.c` (DHCP, the DNS forwarder, the captive DNS, the input filter), `wifi_link.c` (the saved networks, joining, the setup AP), `web.c` + `setup.html`, and `dhcp_core.c` / `util_core.c` (no ESP-IDF: host-tested) |
| `components/` | esp_tinyusb 3.0.0 and TinyUSB, vendored ([VENDORED.md](components/VENDORED.md)) |
| `host_tests/` | the tests above |
| `build.sh` | the build, and the image for 0x0 |

## Licences

This firmware's code is **MIT**, like the rest of the repository. Built into
the image, each under its own licence: ESP-IDF (Apache-2.0, with lwIP
BSD-3-Clause and FreeRTOS MIT), esp_tinyusb (Apache-2.0), TinyUSB (MIT).
Their texts ship with the image (`firmware/licenses/`, listed in
`S3-USB-WiFi-NOTICE.txt`). The USB network approach follows Espressif's
[esp-iot-bridge](https://github.com/espressif/esp-iot-bridge) (Apache-2.0)
and the ESP-IDF `tusb_ncm` example; no code is copied from either.
