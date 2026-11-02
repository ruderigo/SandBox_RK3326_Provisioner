#!/bin/bash
# =============================================================================
# RK3326_Provisioner.sh — EmulationStation Ports launcher (/roms/ports)
#
# Opens the Provisioner on the handheld's screen: plug an ESP32 board into the
# hub, it's recognised, and it can be flashed (offline). SELECT+START closes it.
# Installed by install.sh from github.com/ruderigo/SandBox_RK3326_Provisioner.
# =============================================================================
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
export PYTHONUNBUFFERED=1 SDL_NOMOUSE=1

USER_NAME="${PROVISIONER_USER:-ark}"
[ "$(id -u)" -ne 0 ] && USER_NAME="$(id -un)"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"; USER_HOME="${USER_HOME:-/home/$USER_NAME}"
APP="$USER_HOME/rk3326_provisioner"
LOG="$APP/provisioner.log"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo -n"      # never "sudo -S" with data piped in

echo "=== RK3326 Provisioner $(cat "$APP/VERSION" 2>/dev/null), $(date) ===" > "$LOG"
{ echo "user: $(id)"; ls -l /dev/dri/ /dev/ttyUSB* /dev/ttyACM* 2>&1; } >> "$LOG"

# The screen and the gamepad (as the Stump cockpit's launcher does).
$SUDO chmod 666 /dev/tty1 /dev/dri/card* /dev/dri/render* /dev/input/event* 2>/dev/null
printf '\033[?25l' | $SUDO tee /dev/tty1 >/dev/null 2>&1

# The system's SDL2 with KMSDRM (EmulationStation's); then SDL's own choice.
cd "$APP" || exit 1
for driver in kmsdrm ""; do
  if [ -n "$driver" ]; then
    SDL_VIDEODRIVER="$driver" python3 -m provisioner >> "$LOG" 2>&1 && break
  else
    python3 -m provisioner >> "$LOG" 2>&1 && break
  fi
  echo "display driver '${driver:-default}' didn't work; trying the next" >> "$LOG"
done

sync
printf '\033c' | $SUDO tee /dev/tty1 >/dev/null 2>&1
echo "=== closed $(date) ===" >> "$LOG"
