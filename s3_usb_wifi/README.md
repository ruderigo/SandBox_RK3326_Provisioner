# FireFly S3 USB Wi-Fi

Firmware that turns an ESP32-S3 (the **Freenove ESP32-S3 WROOM CAM**, or any
S3 with its native USB wired out) into a **USB network card** for RK3326
handhelds whose Wi-Fi dongle has no driver. The handheld sees an ordinary
USB Ethernet interface; the S3 joins a Wi-Fi by itself (a Stump's, for
FireFly) and routes the handheld to it.

> **Sandbox, v0.1.0: the first build.** It builds, its DHCP server passes
> against three real Linux DHCP clients, but it hasn't met a handheld yet:
> the bench test is below.

## What the handheld gets

| | |
|---|---|
| USB device | **CDC-NCM** (Linux `cdc_ncm`), on the S3's native USB port |
| Its address | **10.77.0.2/24**, by DHCP, 60 s leases; the S3 is **10.77.0.1** |
| Routes | only the network the S3 joined, via 10.77.0.1 (DHCP option 121) |
| Not sent | a default route (option 3), a DNS server (option 6), IPv6 router advertisements |
| Status | `GET http://10.77.0.1/status.json` → `{"ssid","rssi","ip","gateway","subnet","firmware"}` (nulls while not joined) |

The handheld's own default route stays where it was (its `wlan0`, or none):
the S3 only adds a route to the one network it's on. Nothing is installed or
changed on the handheld; it only needs the `cdc_ncm` module (dArkOS's
kernel 4.4 on the R36MAX has it) and a DHCP client on new interfaces.

Traffic to that network is NATed to the S3's Wi-Fi address. Nothing on the
Wi-Fi side can reach the handheld (or the S3's USB side and its setup page):
the S3 drops it, even if something routes through it.

## Which Wi-Fi it joins

1. **The saved network**, if there is one (set on the setup page; kept in
   the S3's NVS). It rejoins by itself whenever the link drops.
2. Otherwise, **an open hotspot that answers as a Stump**: it tries open
   networks, strongest first, asks the gateway for `/node.json`, and stays
   only if that has an `"lxmf"` key. One that doesn't is left alone for 5
   minutes.

When it moves to another network, the handheld's route follows within half a
lease (about 30 s): its next renewal is refused, it asks again and gets the
new route.

## The setup page

An open Wi-Fi, **`FireFly-S3-xxxx`** (the last four hex digits of its MAC),
opens:

- when no network is saved;
- when it has had no network for two minutes;
- when **BOOT is held for a second within the first four seconds after
  power-up** (holding it *during* power-up starts the chip's download mode
  instead).

Join it from a phone: the page opens by itself (or go to
`http://10.77.1.1/`). Pick a network, type its password, **Save and join**.
It closes a minute after the S3 is on a network (when opened with BOOT: after
a network is saved and joined).

The same page is at **`http://10.77.0.1/`** from the handheld, and works
without a browser:

```sh
curl http://10.77.0.1/status.json
curl -d 'ssid=MyNetwork' -d 'password=its-password' http://10.77.0.1/save
curl -X POST http://10.77.0.1/forget
```

## Flashing it

The Freenove board has two USB-C ports: **USB** (the S3's native USB, which
becomes the network card) and **UART** (a CH343 serial chip). **Flash
through the UART port**; plug the **USB** port into the handheld to use it.

- **From the handheld:** the RK3326 Provisioner (in this repository) offers
  *USB Wi-Fi adapter* for an ESP32-S3 on its CH343 port; it erases the board
  and writes the image (a Stump on that board is gone).
- **From a computer**, with esptool:

  ```sh
  esptool.py --chip esp32s3 --port /dev/ttyACM0 erase_flash
  esptool.py --chip esp32s3 --port /dev/ttyACM0 write_flash 0x0 s3-usb-wifi-0.1.0.bin
  ```

  The image is `firmware/s3_usb_wifi/s3-usb-wifi-<version>.bin` in this
  repository (one file, written at 0x0); its SHA-256 is in
  `firmware/catalog.json`, and each release lists it in `SHA256SUMS`.

To put a Stump (or anything else) back on the board later, flash it through
the UART port as usual; if the board doesn't answer, hold BOOT and tap
RESET. Its log (115200) is on the UART port too.

## The bench test (R36MAX)

Plug the board's **USB** port into the handheld, then:

| | Check | Expect |
|---|---|---|
| 1 | `ip -4 addr` | a new interface (`usb0` or `eth…`) with **10.77.0.2/24** within 10 s |
| 2 | `dmesg \| tail` | `cdc_ncm` bound to the device (*FireFly S3 USB Wi-Fi*) |
| 3 | `ip route` | the default route still only via `wlan0` (or none); a route to the S3's Wi-Fi via 10.77.0.1 |
| 4 | `curl http://10.77.0.1/status.json` | its SSID, RSSI, address, gateway, subnet, firmware |
| 5 | `curl http://<gateway>/node.json` | the Stump answers |
| 6 | unplug, replug (either way round, handheld on or off) | back as in 1 |
| 7 | | LoRa unaffected |
| 8 | the setup page from a phone | lists networks, saves one, joins it |

1–6 are the bar for a first release.

## Building it

ESP-IDF **v5.3** (5.3.2 is what the CI uses), target esp32s3. Everything
else is in `components/` (the component manager stays off):

```sh
. $IDF_PATH/export.sh
bash build.sh          # host tests, build, dist/s3-usb-wifi-<version>.bin + SHA256SUMS
```

Builds are reproducible: the CI rebuilds the image and checks it's the one
in `firmware/`.

Tests that need no board: `bash host_tests/run.sh` (the DHCP server, the
captive DNS, the helpers), and `sudo bash host_tests/dhcp_clients.sh`, which
runs the firmware's DHCP code against **dhclient, dhcpcd and busybox udhcpc**
over a veth pair into a network namespace: 10.77.0.2/24, the option 121
route, the default route left alone, no DNS, and the route following a
network change.

## Limits

- **NCM only** for now. ECM (the memo's fallback) needs its own build of the
  USB stack; it comes if a handheld turns up without `cdc_ncm`.
- The S3's USB is full-speed (12 Mbit/s): expect a few Mbit/s, plenty for
  FireFly and LXMF, slow for big downloads.
- If the Wi-Fi it joins overlaps 10.77.0.0/23, no route is sent (the S3 logs
  it).
- The saved password is in the S3's NVS unencrypted, like most ESP32
  devices: anyone with the board in hand can read it.
- It uses no UDP port but DHCP (67) and, on the setup AP only, DNS (53); no
  Reticulum, LXMF or anything else Stump-specific runs on it.

## Files

| | |
|---|---|
| `main/` | the firmware: `usb_net.c` (NCM ↔ esp_netif), `netsvc.c` (DHCP, captive DNS, the input filter), `wifi_link.c` (joining, NVS, the setup AP), `web.c` + `setup.html`, `dhcp_core.c` / `util_core.c` (no ESP-IDF: host-tested) |
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
