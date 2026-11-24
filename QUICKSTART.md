# RK3326 Provisioner quick start

The Provisioner turns an RK3326 handheld (R36MAX, R36S...) into the mesh's
ESP32 board bench, offline and from the gamepad: plug an ESP32 board into
the hub and it's recognised, flashed and checked. (The handheld's own Stump
and FireFly install and update themselves.) This page gets you going; the
[README](README.md) has everything.

## Install

From your computer, with the handheld online:

```sh
ssh -t ark@r36max.local 'git clone https://github.com/ruderigo/SandBox_RK3326_Provisioner.git ~/SandBox_RK3326_Provisioner && bash ~/SandBox_RK3326_Provisioner/install.sh'
```

Then **EmulationStation → Ports → RK3326_Provisioner** (restart
EmulationStation if it isn't listed); on **RK3326 Linux**, the dock:
**Workshop → Provisioner**. The version is at the top right.

No internet on the handheld: copy a release's
`RK3326-Provisioner-<version>.tar.gz` over, then on the handheld:

```sh
tar xzf RK3326-Provisioner-*.tar.gz && bash RK3326-Provisioner-*/install.sh
```

## The screens

| Screen | What you do there |
|---|---|
| Boards | Every board on the hub; A opens one, Y its serial log, L the Library |
| A board | Make a Stump, flash, packs, + From File, its log, erase (asks first) |
| The Provisioner (last row of Boards) | Its own updates, and going back to the one before |
| Library (L) | Everything on the shelf, newer versions online |

SELECT + START closes it. B is back everywhere.

## A first Stump

1. Plug a Freenove ESP32-S3 CAM into the hub.
2. On **Boards**, A on it. It's identified (the board resets).
3. The first row is the Stump it gets: ◀ ▶ Official or Sandbox.
4. **Make a Stump**, answer the form (its name, the network, the chain),
   and it's flashed, set and checked: what it said as it started is shown.

## Your own firmware

On a board's page, **+ From File** flashes a `.bin` (a full image or one
program) or your own build zipped (ESP-IDF's `build` folder, PlatformIO's
`.pio/build/<env>`, the Arduino IDE's export): every file at its address,
checked first, then the board erased and written. More: the README's
[Your own firmware](README.md#your-own-firmware).

## Sound

**The Provisioner plays none**, and neither do the Stump boards it makes.

## It works offline

A copy of each project, *the shelf*, comes with it. When the handheld is
online, it says what's newer and **X** takes it onto the shelf, checked
against GitHub's checksums.

## If something's wrong

A board that doesn't answer: hold BOOT, tap RESET (or replug), try again. A
port another program has open (the Stump's Heltec) is marked *in use* and
asks before anything touches it. More in the [README](README.md).
