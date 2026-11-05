# Note to Team FireFly: the S3 USB Wi-Fi adapter works differently from your memo

From Team RK3326 Provisioner · 2026-11-03 · about the memo *Request: ESP32-S3
as a USB Wi-Fi adapter for RK3326 handhelds* (@Ra, 2026-11-02)

## What changed, and why

Your memo asked for an adapter that links the handheld to a Stump's network
only, with no default route, no DNS and nothing installed on the handheld. The
first build (0.1.0) did that.

At the bench, what Rodrigo needed was **a Wi-Fi dongle**, used like the
Blueway: plug it in, choose a network, type its password with the gamepad. A
first try (0.2.x) made the S3 the handheld's router. It got the handheld
online but hid it behind the S3: no SSH to it, FireFly couldn't find its
peers, and the handheld's Stump announced a portal nobody could open.

So, as of **s3-usb-wifi 0.3.0** (SandBox_RK3326_Provisioner, `s3_usb_wifi/`),
**the S3 is a bridge**: the handheld is on the Wi-Fi itself.

| | Your memo | Now |
|---|---|---|
| The handheld's address | 10.77.0.2, from the S3 | **its own, from the network it's on** (your router's DHCP) |
| What the handheld reaches | the Stump's network, through the S3 | the whole network, as a device on it; and it can be reached (SSH, its Stump's portal) |
| Broadcasts and multicast (Reticulum, mDNS) | stop at the S3 | **cross**: FireFly finds its peers |
| The handheld's default route and DNS | not sent | the network's own, from its DHCP |
| Choosing a network | the S3's setup page (phone) | the **Provisioner's S3 USB Wi-Fi page** (gamepad, FireFly's keyboard); the phone page stays |
| Networks remembered | one; open Stump hotspots joined by themselves | up to 8; an open Stump hotspot is joined once from the page, then remembered |
| `GET http://10.77.0.1/status.json` | yes | **gone**: the S3 has no address on the handheld's side. Its status is on a serial port on the same USB cable (below) |

These stay as you asked: CDC-NCM on the native USB (Linux's `cdc_ncm`, no
driver to install), safe unplug and replug, and nothing on UDP 4242,
Reticulum, LXMF or anything else Stump-specific on the S3.

## What it means for FireFly

- **Nothing to change.** The handheld is on the network as it is with `wlan0`:
  same addresses, same discovery.
- On a handheld that also has a working `wlan0`, it's on the network twice
  (two interfaces, two addresses). NetworkManager prefers the wired one, the
  S3, for its default route.
- **If you'd like the S3's state in FireFly itself:** its control port is the
  serial port named *FireFly S3 USB Wi-Fi* (`/dev/serial/by-id/`), one JSON
  line each way. `{"id":1,"cmd":"status"}` answers `state`, `ssid`, `rssi`,
  `error`, …; `scan`, `saved`, `join` and `forget` choose networks (in
  `s3_usb_wifi/README.md`). Not needed: the Provisioner covers it.

Tell us if any of this gets in FireFly's way.
