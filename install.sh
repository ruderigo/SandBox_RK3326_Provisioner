#!/bin/bash
# =============================================================================
# install.sh — installs the RK3326 Provisioner on the handheld (or updates it)
#
# On the handheld (from a clone of this repo, or an unpacked release):
#   bash install.sh
# Needs no internet: everything (esptool, the firmware) is in this folder.
#
# Any RK3326 handheld and system:
#   ArkOS, dArkOS (and the R36S/R36MAX stock ones)   as ark; asks for sudo once
#     ~/rk3326_provisioner/                the app
#     /roms/ports (and /roms2/ports)       the Ports entry
#     /etc/udev/rules.d                    serial access
#   AmberELEC, ROCKNIX                     as root (their only user)
#     /storage/rk3326_provisioner/         the app
#     /storage/roms/ports                  the Ports entry
#     /storage/.config/udev.rules.d        serial access (the system itself is read-only)
#
# PROVISIONER_TEST_ROOT=DIR puts every system path under DIR (the tests).
# =============================================================================
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
R="${PROVISIONER_TEST_ROOT:-}"
ok()   { printf '    \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[31m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m[x] %s\033[0m\n' "$*"; exit 1; }

# Who it's for: root on AmberELEC/ROCKNIX; on ArkOS/dArkOS the user (ark),
# also when run with sudo.
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
  if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != root ]; then
    ME="$SUDO_USER"; MYHOME="$(getent passwd "$ME" | cut -d: -f6)"
  else
    ME=root; MYHOME="$HOME"
  fi
else
  SUDO="sudo"; ME="$(id -un)"; MYHOME="$HOME"
fi
[ -n "$R" ] && SUDO=""
MYHOME="${MYHOME:-$HOME}"
APP="${PROVISIONER_APP:-$MYHOME/rk3326_provisioner}"
OS="$(. "$R/etc/os-release" 2>/dev/null; echo "${PRETTY_NAME:-${NAME:-this system}}")"

command -v python3 >/dev/null || die "python3 is needed"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 6))' || die "python3 is $(python3 -V 2>&1); 3.6 or newer is needed"
if [ -z "$R" ]; then
  python3 -c "import ctypes, ctypes.util; ctypes.CDLL(ctypes.util.find_library('SDL2') or 'libSDL2-2.0.so.0')" 2>/dev/null \
    || die "SDL2 (libSDL2-2.0.so.0) is needed: it's EmulationStation's, so this isn't the handheld's system?"
fi
# A git clone: update it first, then run the new copy of this script.
if [ -z "${PROVISIONER_PULLED:-}" ] && [ -d "$HERE/.git" ] && [ -z "$R" ]; then
  git -C "$HERE" pull --ff-only -q 2>/dev/null || true
  PROVISIONER_PULLED=1 exec bash "$HERE/install.sh" "$@"
fi
if [ -n "$SUDO" ]; then sudo -v || die "sudo is needed once (serial access rule, the Ports entry)"; fi
echo ">>> On $OS, for $ME"

echo ">>> The app"
mkdir -p "$APP" || die "can't make $APP"
for d in provisioner vendor firmware assets; do
  rm -rf "${APP:?}/$d"
  cp -r "$HERE/$d" "$APP/$d"
done
cp -f "$HERE/VERSION" "$HERE/README.md" "$HERE/LICENSE" "$APP/"
find "$APP" -name __pycache__ -prune -exec rm -rf {} +
[ "$(id -u)" -eq 0 ] && [ "$ME" != root ] && chown -R "$ME": "$APP" 2>/dev/null
if [ -z "$R" ]; then
  (cd "$APP" && python3 -m provisioner --smoke >/dev/null 2>&1) && ok "installed in $APP (v$(cat "$APP/VERSION"); it draws)" \
    || warn "installed in $APP, but its screen test failed: see 'cd $APP && python3 -m provisioner --smoke'"
else
  ok "installed in $APP (v$(cat "$APP/VERSION"))"
fi
(cd "$APP" && python3 - <<'PY'
from provisioner import catalog
bad = [e["id"] for e in catalog.load() if e["status"] == "ready" and catalog.check(e)]
raise SystemExit("firmware doesn't match its SHA-256: %s" % bad if bad else 0)
PY
) && ok "firmware checked (SHA-256)" || warn "some firmware didn't match its SHA-256 (it won't be offered)"

echo ">>> Serial access"
if [ -d "$R/storage/.config" ]; then UDEV="$R/storage/.config/udev.rules.d"; else UDEV="$R/etc/udev/rules.d"; fi
$SUDO mkdir -p "$UDEV" 2>/dev/null
if $SUDO install -m 0644 "$HERE/udev/99-rk3326-provisioner.rules" "$UDEV/99-rk3326-provisioner.rules"; then
  if [ -z "$R" ]; then
    $SUDO udevadm control --reload-rules 2>/dev/null; $SUDO udevadm trigger --subsystem-match=tty 2>/dev/null
  fi
  ok "udev rule ($UDEV)"
else
  warn "couldn't install the udev rule in $UDEV"
fi
if [ "$ME" != root ] && [ -z "$R" ]; then
  USERMOD="$(command -v usermod || echo /usr/sbin/usermod)"
  id -nG "$ME" | grep -qw dialout || { $SUDO "$USERMOD" -aG dialout "$ME" && ok "$ME added to dialout (from the next login)"; }
fi

echo ">>> EmulationStation (Ports)"
n=0; seen=" "
for ports in "$R/roms/ports" "$R/roms2/ports" "$R/storage/roms/ports"; do
  [ -d "$ports" ] || continue
  real="$(cd "$ports" && pwd -P)"
  case "$seen" in *" $real "*) continue ;; esac
  seen="$seen$real "
  tmp="$(mktemp)"
  sed "s|^APP_DEFAULT=.*|APP_DEFAULT=\"$APP\"     # written by install.sh|" "$HERE/ports/RK3326_Provisioner.sh" > "$tmp"
  $SUDO install -m 0755 "$tmp" "$ports/RK3326_Provisioner.sh" && ok "$ports/RK3326_Provisioner.sh" && n=$((n+1))
  rm -f "$tmp"
done
[ "$n" -gt 0 ] || warn "no roms/ports folder here (/roms/ports, /storage/roms/ports): is this the handheld?"

echo
echo "Done. EmulationStation -> Ports -> RK3326_Provisioner (restart EmulationStation if it isn't listed)."
echo "Over SSH: cd $APP && python3 -m provisioner controls   (the buttons it found)"
echo "On a computer instead: python3 -m provisioner (needs SDL2), or 'list' / 'catalog' / 'flash PORT ID'."
