#!/bin/bash
# =============================================================================
# RK3326_Provisioner.sh — EmulationStation Ports launcher (roms/ports)
#
# Opens the Provisioner on the handheld's screen: plug an ESP32 board into the
# hub, it's recognised, and it can be flashed (offline). SELECT+START closes it.
# Installed by install.sh from github.com/ruderigo/SandBox_RK3326_Provisioner.
#
# ArkOS / dArkOS (as ark, sudo -n for the device files), AmberELEC (root,
# KMSDRM), ROCKNIX (root, EmulationStation under sway: Wayland first).
# RK3326 Linux: its dock runs this (install.sh copies it into the app's folder)
# with the screen already set up (SDL_VIDEODRIVER, the GPU's SDL2): taken as is.
# =============================================================================
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
export PYTHONUNBUFFERED=1 SDL_NOMOUSE=1

APP_DEFAULT="$HOME/rk3326_provisioner"
APP=""
for c in "${PROVISIONER_APP:-}" "$APP_DEFAULT" /home/ark/rk3326_provisioner /storage/rk3326_provisioner \
         "$HOME/rk3326_provisioner"; do
  [ -n "$c" ] && [ -f "$c/VERSION" ] && { APP="$c"; break; }
done
[ -n "$APP" ] || { echo "RK3326 Provisioner: not installed (bash install.sh)" >&2; exit 1; }
LOG="$APP/provisioner.log"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo -n"      # never "sudo -S" with data piped in

echo "=== RK3326 Provisioner $(cat "$APP/VERSION" 2>/dev/null), $(date) ===" > "$LOG"
{ echo "user: $(id)"; grep -h PRETTY_NAME /etc/os-release 2>/dev/null; python3 -V 2>&1
  ls -l /dev/dri/ /dev/ttyUSB* /dev/ttyACM* 2>&1; } >> "$LOG"

# A Wayland compositor (ROCKNIX runs EmulationStation under sway): its socket.
if [ -z "${WAYLAND_DISPLAY:-}" ]; then
  for d in "${XDG_RUNTIME_DIR:-}" /var/run/0-runtime-dir /run/0-runtime-dir "/run/user/$(id -u)"; do
    [ -n "$d" ] || continue
    for s in "$d"/wayland-[0-9]*; do
      case "$s" in *.lock) continue ;; esac
      [ -S "$s" ] && { export XDG_RUNTIME_DIR="$d" WAYLAND_DISPLAY="${s##*/}"; break 2; }
    done
  done
fi
DOCK=""; [ -d /usr/share/rk/apps ] && [ -n "${SDL_VIDEODRIVER:-}" ] && DOCK=1   # RK3326 Linux's dock
drivers="kmsdrm"
[ -n "${WAYLAND_DISPLAY:-}" ] && drivers="wayland kmsdrm"
[ -n "$DOCK" ] && echo "display: the dock's ($SDL_VIDEODRIVER)" >> "$LOG"
[ -z "$DOCK" ] && echo "display: trying ${drivers} then SDL's own choice${WAYLAND_DISPLAY:+ (Wayland: $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY)}" >> "$LOG"

# The screen and the gamepad.
if [ -z "$DOCK" ]; then                  # the dock's own system has given ark the screen and the pad
  $SUDO chmod 666 /dev/tty1 /dev/dri/card* /dev/dri/render* /dev/input/event* 2>/dev/null
  [ -z "${WAYLAND_DISPLAY:-}" ] && printf '\033[?25l' | $SUDO tee /dev/tty1 >/dev/null 2>&1
fi

cd "$APP" || exit 1
if [ -n "$DOCK" ]; then                  # under the dock: its screen setup, nothing else
  python3 -m provisioner >> "$LOG" 2>&1
else
  for driver in $drivers ""; do
    if [ -n "$driver" ]; then
      SDL_VIDEODRIVER="$driver" python3 -m provisioner >> "$LOG" 2>&1 && break
    else
      python3 -m provisioner >> "$LOG" 2>&1 && break
    fi
    echo "display driver '${driver:-default}' didn't work; trying the next" >> "$LOG"
  done
fi

sync
[ -z "$DOCK" ] && [ -z "${WAYLAND_DISPLAY:-}" ] && printf '\033c' | $SUDO tee /dev/tty1 >/dev/null 2>&1
echo "=== closed $(date) ===" >> "$LOG"
