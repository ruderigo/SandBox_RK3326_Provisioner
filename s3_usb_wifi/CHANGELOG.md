## s3-usb-wifi 0.2.0

**The S3 is the handheld's Wi-Fi card**, driven from the gamepad. 0.1.0
followed the memo of 2026-11-02 (a link to the Stump's network only, no
default route, no DNS, nothing on the handheld). We changed that on
2026-11-03, so the S3 works like a Wi-Fi dongle: the handheld gets its
internet through it, and the Provisioner has a page to pick networks.

- **The handheld's router and DNS are the S3** (10.77.0.1): a default route
  (option 3, and in option 121), and DNS questions passed on to the joined
  network's DNS (SERVFAIL while there's none). They never change, whatever
  the S3 joins: no renewals refused, nothing for the handheld to catch up on.
  The 10-minute lease is ACKed on renewal.
- **Up to 8 saved networks** (NVS, most recent first). It joins whichever is
  in range, else an open Stump hotspot. 0.1.0's single network is carried
  over.
- **An API for the Provisioner's page:** `POST /join` (`ssid`, `password`;
  left out, a saved one keeps its own), `POST /forget` (one, or all),
  `GET /networks.json`, `scan.json` with `saved`, and `status.json` with
  `state`, `target`, `error` (`wrong_password`, `not_found`, …), `dns`,
  `stump`. JSON answers with `Accept: application/json`.
- The setup page lists the saved networks, each with a *forget* button.
- Tested against dhclient, dhcpcd and udhcpc: address, default route and DNS
  10.77.0.1, renewals changing nothing.

## s3-usb-wifi 0.1.0 (not released)

The first build of the ESP32-S3 USB Wi-Fi adapter for RK3326 handhelds
(Team RK3326 Provisioner memo, 2026-11-02).

- **CDC-NCM** on the S3's native USB; the S3 at 10.77.0.1/24.
- **Its own DHCP server**: 10.77.0.2, 60 s leases, no router, no DNS; the
  joined Wi-Fi's network as option 121 via 10.77.0.1, following it when the
  S3 moves (the next renewal is refused, the handheld asks again).
  Replies unicast to a client that has an address (RFC 2131). Tested
  against dhclient, dhcpcd and busybox udhcpc.
- **NAT** from USB to the joined Wi-Fi; nothing on the Wi-Fi side reaches
  the handheld or the S3's USB side.
- **Joins by itself**: the saved network (NVS), else an open hotspot that
  answers as a Stump (`/node.json` with `"lxmf"`).
- **Setup AP** `FireFly-S3-xxxx` (open, captive page at 10.77.1.1) when
  nothing is saved, after two minutes with no network, or with BOOT just
  after power-up; the same page at http://10.77.0.1/ from the handheld.
- `GET /status.json`: `ssid`, `rssi`, `ip`, `gateway`, `subnet`, `firmware`.
- One image for 0x0, reproducible; in the Provisioner's catalogue.

Not yet: ECM (the fallback), the bench test on an R36MAX.
