## s3-usb-wifi 0.1.0

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
