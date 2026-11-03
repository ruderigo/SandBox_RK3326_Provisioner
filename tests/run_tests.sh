#!/bin/bash
# Every test that needs no board:  bash tests/run_tests.sh
# Needs python3, and SDL2 for the screens (libsdl2-2.0-0); shellcheck if installed.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAILED=()
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
run() { local n="$1"; shift; if "$@"; then echo "ok: $n"; else echo "FAILED: $n"; FAILED+=("$n"); fi; }
cd "$ROOT" || exit 1

step "Version"
check_version() {
  local v; v="$(tr -d '[:space:]' < VERSION)"
  grep -q "^## v$v" CHANGELOG.md || { echo "CHANGELOG.md has no '## v$v'"; return 1; }
  [ "$(python3 -m provisioner --version)" = "$v" ] || { echo "the app doesn't say $v"; return 1; }
  echo "v$v"
}
run "version" check_version

step "Shell scripts"
lint() {
  local bad=0 f
  for f in install.sh package.sh ports/RK3326_Provisioner.sh tests/run_tests.sh; do bash -n "$f" || bad=1; done
  if command -v shellcheck >/dev/null; then
    shellcheck -S warning install.sh package.sh ports/RK3326_Provisioner.sh tests/run_tests.sh s3_usb_wifi/build.sh s3_usb_wifi/host_tests/*.sh || bad=1
  else echo "(no shellcheck: syntax only)"; fi
  return "$bad"
}
run "shell" lint

step "Python"
pyflakes_or_compile() {
  if python3 -m pyflakes --version >/dev/null 2>&1; then python3 -m pyflakes provisioner scripts tests/*.py
  else python3 -m compileall -q provisioner tests; fi
}
run "python" pyflakes_or_compile

step "Core: detection, catalogue, flashing (fake esptool)"
run "core" python3 -W error::ResourceWarning tests/test_core.py

step "Making a Stump (Team Stump's pretend board, the real bundle)"
run "stump" python3 -W error::ResourceWarning tests/test_stump.py

step "Screens and buttons (no screen: SDL's dummy driver)"
if python3 -c "import ctypes, ctypes.util; ctypes.CDLL(ctypes.util.find_library('SDL2') or 'libSDL2-2.0.so.0')" 2>/dev/null; then
  run "screens" python3 tests/test_ui.py
  run "smoke" python3 -m provisioner --smoke
else
  echo "FAILED: SDL2 isn't installed (apt install libsdl2-2.0-0)"; FAILED+=("screens")
fi

step "Every character the screens draw is in the font"
font_chars() {
  python3 - <<'PY'
import re, sys
sys.path.insert(0, ".")
from provisioner.ui.sdl import load_fonts
fonts = load_fonts("assets/cockpit_font.bin")
have = set.intersection(*(set(f["glyphs"]) for f in fonts))
missing = {}
for path in ("provisioner/ui/app.py", "provisioner/ui/keyboard.py", "provisioner/stump.py", "provisioner/flasher.py",
             "firmware/catalog.json"):
    src = open(path, encoding="utf-8").read()
    for i, line in enumerate(src.splitlines(), 1):
        for c in line:
            if ord(c) > 126 and ord(c) not in have:
                missing.setdefault(c, "%s:%d" % (path, i))
assert not missing, "not in the font: %s" % missing
print("all there")
PY
}
run "font" font_chars

echo
if [ "${#FAILED[@]}" -gt 0 ]; then echo "FAILED: ${FAILED[*]}"; exit 1; fi
echo "all passed"
