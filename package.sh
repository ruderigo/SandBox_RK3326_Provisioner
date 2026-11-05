#!/bin/bash
# The release: dist/RK3326-Provisioner-<VERSION>.tar.gz, SHA256SUMS, notes.
#   bash package.sh              (tests first)
#   bash package.sh --no-tests   (CI has tested already)
# On a tag in CI, the tag must be v<VERSION>.
set -eu
ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
NAME="RK3326-Provisioner-$VERSION"
DIST="$ROOT/dist"
die() { echo "package.sh: $*" >&2; exit 1; }
if [ "${GITHUB_REF_TYPE:-}" = "tag" ] && [ "${GITHUB_REF_NAME:-}" != "v$VERSION" ]; then
  die "tag ${GITHUB_REF_NAME:-?} isn't v$VERSION (VERSION)"
fi
[ "${1:-}" = "--no-tests" ] || bash "$ROOT/tests/run_tests.sh" || die "the tests failed"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME"
(cd "$ROOT" && git ls-files -co --exclude-standard) | while IFS= read -r f; do
  case "$f" in dist/*|tests/*|.github/*|s3_usb_wifi/*) continue ;; esac  # the firmware's source stays in the repo; its image is in firmware/
  mkdir -p "$STAGE/$NAME/$(dirname "$f")"
  cp -p "$ROOT/$f" "$STAGE/$NAME/$f"
done
find "$STAGE" \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} +
for f in install.sh VERSION provisioner/__main__.py firmware/catalog.json assets/cockpit_font.bin; do
  [ -f "$STAGE/$NAME/$f" ] || die "$f missing from the package"
done
mkdir -p "$DIST"
awk -v h="## v$VERSION" '$0 == h || index($0, h " ") == 1 {on=1; next} on && /^## / {exit} on' \
  "$ROOT/CHANGELOG.md" > "$DIST/RELEASE_NOTES.md"
[ -s "$DIST/RELEASE_NOTES.md" ] || die "CHANGELOG.md has no '## v$VERSION'"
printf '\n---\n\n**On the handheld** (as `ark`; no internet needed):\n\n```sh\ntar xzf %s.tar.gz && bash %s/install.sh\n```\n' \
  "$NAME" "$NAME" >> "$DIST/RELEASE_NOTES.md"
STAMP="$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)"
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$STAMP" -C "$STAGE" -cf - "$NAME" \
  | gzip -n -9 > "$DIST/$NAME.tar.gz"
(cd "$DIST" && sha256sum "$NAME.tar.gz" > SHA256SUMS)
echo "dist/$NAME.tar.gz ($(du -k "$DIST/$NAME.tar.gz" | cut -f1) KB)"
