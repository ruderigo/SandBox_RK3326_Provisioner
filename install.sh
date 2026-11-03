#!/bin/bash
# =============================================================================
# install.sh — installs the RK3326 Provisioner on the handheld (or updates it)
#
# On the handheld, as ark (from a clone of this repo, or an unpacked release):
#   bash install.sh
# Needs no internet: everything (esptool, the firmware) is in this folder.
#
#   ~/rk3326_provisioner/          the app (on the ext4 partition)
#   /roms/ports/RK3326_Provisioner.sh   (and /roms2/ports with a second card)
#   /etc/udev/rules.d/99-rk3326-provisioner.rules   serial access
# =============================================================================
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ME="$(id -un)"
APP="$HOME/rk3326_provisioner"
ok()   { printf '    \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[31m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m[x] %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] && die "Run this as your user (ark), not root: it asks for sudo when it needs it."
command -v python3 >/dev/null || die "python3 is needed"
python3 -c "import ctypes, ctypes.util; ctypes.CDLL(ctypes.util.find_library('SDL2') or 'libSDL2-2.0.so.0')" 2>/dev/null \
  || die "SDL2 (libSDL2-2.0.so.0) is needed: it's EmulationStation's, so this isn't the handheld's system?"
# A git clone: update it first, then run the new copy of this script.
if [ -z "${PROVISIONER_PULLED:-}" ] && [ -d "$HERE/.git" ]; then
  git -C "$HERE" pull --ff-only -q 2>/dev/null || true
  PROVISIONER_PULLED=1 exec bash "$HERE/install.sh" "$@"
fi
sudo -v || die "sudo is needed once (serial access rule, the Ports entry)"

echo ">>> The app"
mkdir -p "$APP"
for d in provisioner vendor firmware assets; do
  rm -rf "${APP:?}/$d"
  cp -r "$HERE/$d" "$APP/$d"
done
cp -f "$HERE/VERSION" "$HERE/README.md" "$HERE/LICENSE" "$APP/"
find "$APP" -name __pycache__ -prune -exec rm -rf {} +
(cd "$APP" && python3 -m provisioner --smoke >/dev/null 2>&1) && ok "installed in $APP (v$(cat "$APP/VERSION"); it draws)" \
  || warn "installed in $APP, but its screen test failed: see 'cd $APP && python3 -m provisioner --smoke'"
(cd "$APP" && python3 - <<'PY'
from provisioner import catalog
bad = [e["id"] for e in catalog.load() if e["status"] == "ready" and catalog.check(e)]
raise SystemExit("firmware doesn't match its SHA-256: %s" % bad if bad else 0)
PY
) && ok "firmware checked (SHA-256)" || warn "some firmware didn't match its SHA-256 (it won't be offered)"

echo ">>> Serial access"
sudo install -m 0644 "$HERE/udev/99-rk3326-provisioner.rules" /etc/udev/rules.d/99-rk3326-provisioner.rules \
  && { sudo udevadm control --reload-rules 2>/dev/null; sudo udevadm trigger --subsystem-match=tty 2>/dev/null; ok "udev rule"; } \
  || warn "couldn't install the udev rule"
USERMOD="$(command -v usermod || echo /usr/sbin/usermod)"
id -nG "$ME" | grep -qw dialout || { sudo "$USERMOD" -aG dialout "$ME" && ok "$ME added to dialout (from the next login)"; }

echo ">>> EmulationStation (Ports)"
n=0
for ports in /roms/ports /roms2/ports; do
  [ -d "$ports" ] || continue
  sudo install -m 0755 "$HERE/ports/RK3326_Provisioner.sh" "$ports/RK3326_Provisioner.sh" && ok "$ports/RK3326_Provisioner.sh" && n=$((n+1))
done
[ "$n" -gt 0 ] || warn "no /roms/ports here: is this the handheld?"

echo
echo "Done. EmulationStation -> Ports -> RK3326_Provisioner (restart EmulationStation if it isn't listed)."
echo "On a computer instead: python3 -m provisioner (needs SDL2), or 'list' / 'catalog' / 'flash PORT ID'."
