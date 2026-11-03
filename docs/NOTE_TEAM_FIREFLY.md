# Note to Team FireFly: the S3 USB Wi-Fi adapter works differently from your memo

From Team RK3326 Provisioner · 2026-11-03 · about the memo *Request: ESP32-S3
as a USB Wi-Fi adapter for RK3326 handhelds* (@Ra, 2026-11-02)

## What changed, and why

Your memo asked for an adapter that links the handheld to a Stump's network
only, with no default route, no DNS and nothing installed on the handheld.
The first build (0.1.0) did exactly that.

At the bench, what Rodrigo needed was **a Wi-Fi dongle**, used like the
Blueway: plug it in, choose a network, type its password with the gamepad.
So, as of **s3-usb-wifi 0.2.0** (SandBox_RK3326_Provisioner, `s3_usb_wifi/`):

| | Your memo | Now |
|---|---|---|
| The handheld's default route | not sent: `wlan0` keeps it | **via the S3** (10.77.0.1) |
| DNS | not sent | **the S3** (10.77.0.1), passing questions on to the joined network's DNS |
| Choosing a network | the S3's setup page (phone) | the **Provisioner's S3 USB Wi-Fi page** (gamepad, FireFly's keyboard); the phone page stays |
| Networks remembered | one | up to 8; with none in range, an open Stump hotspot (as you asked) |
| On the handheld | nothing installed | the Provisioner (already a Ports entry) hosts the page; nothing else |

These stay as you asked: CDC-NCM on the native USB, 10.77.0.1/24 and
10.77.0.2, `GET /status.json` with your six keys (more keys are added
alongside them), safe unplug and replug, no UDP 4242, no Reticulum, LXMF or
anything Stump-specific on the S3.

## What it means for FireFly

- **Nothing to change.** FireFly reaches a Stump through the S3 as it would
  through `wlan0`: by the route to it, now the default.
- On a handheld that also has a working `wlan0`, the S3 adds a second default
  route. NetworkManager prefers wired, so the S3's wins. If FireFly must stay
  on `wlan0` there, unplug the S3.
- **If you'd like it in FireFly itself:** `GET http://10.77.0.1/status.json`
  says what the S3 is on (`state`, `ssid`, `rssi`, `error`). The same small API
  joins and forgets networks (`POST /join`, `POST /forget`, `GET /scan.json`,
  `GET /networks.json`; in `s3_usb_wifi/README.md`). A status line or a picker
  in FireFly could use it. Not needed: the Provisioner covers it.

Tell us if any of this gets in FireFly's way.
