# RK3326 handhelds and systems

| | |
|---|---|
| Screens | 720x720 (R36MAX, R36Pro, K36) and 854x480 (OGS, RGB10 Max) drawn 1:1; 640x480 (R36S, R33S, R35S, RG351V/MP, RGB20S, RGB10X, XU10, Chi) and 480x320 (OGA, RK2020, RGB10, RG351P/M) a little scaled, never below 0.8 so it stays readable; 1024x768 too. A panel mounted sideways is turned (the device tree's `rotation`, else 270°; `PROVISIONER_ROTATE=0/90/180/270` to change it) |
| Buttons | EmulationStation's own mapping (`es_input.cfg`), so A is ES's A on every pad; else a table per pad (the RG351's OSH pad, the XU10's swapped A/B). Check over SSH: `python3 -m provisioner controls` |
| ArkOS, dArkOS, stock R36S | as `ark` (sudo once); `~/rk3326_provisioner`, `/roms/ports` and `/roms2/ports`, KMSDRM |
| AmberELEC | as root; `/storage/rk3326_provisioner`, `/storage/roms/ports`, udev rules in `/storage/.config`, KMSDRM |
| ROCKNIX | as root; same paths as AmberELEC; EmulationStation runs under sway, so the launcher uses Wayland first |
| Python | 3.6 or newer (ArkOS has 3.7, ROCKNIX 3.14); any SDL2 from 2.0 on |
| USB-serial | CDC-ACM (ESP32-S3/C3 native USB, CH343/CH9102) works on all of them. ArkOS, dArkOS and AmberELEC also have CP210x, FTDI and PL2303, **none has the CH340's driver** (ch341), and ROCKNIX has no USB-serial driver but CDC-ACM. A board the system can't talk to is named on the boards screen with the driver it lacks. A **CH340** is the exception from 0.3.0-beta.14: the Provisioner drives it itself through libusb-1.0 (`ch340://<bus>-<address>`; ArkOS and dArkOS have libusb) |

Bench-tested on the R36MAX. The other screens, systems and pads are
laid out, tested in CI (every size above, both install layouts, the button
tables) and built from those systems' sources, but not yet run on the
devices themselves: their `provisioner.log` (in the app's folder) says what
screen, driver and buttons it found.

What each system needs is in the README's *Install*; the launcher's log (`provisioner.log` in the app's folder) says what it found on a handheld.
