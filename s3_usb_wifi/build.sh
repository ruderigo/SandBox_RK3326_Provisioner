#!/usr/bin/env bash
# Builds the firmware and its one-file image for writing at 0x0:
#   dist/s3-usb-wifi-<version>.bin  and  dist/SHA256SUMS
# Needs ESP-IDF v5.3 in the environment (. $IDF_PATH/export.sh), or runs in
# the espressif/idf:v5.3.2 container as the CI does. Also runs the host tests.
set -euo pipefail
cd "$(dirname "$0")"
export IDF_COMPONENT_MANAGER=0   # everything it needs is in components/

if command -v cc >/dev/null; then
    bash host_tests/run.sh
else
    echo "no C compiler for the host tests: skipped"
fi

[ -f sdkconfig ] || idf.py set-target esp32s3
idf.py build

ver=$(sed -n 's/^set(PROJECT_VER "\(.*\)")/\1/p' CMakeLists.txt)
mkdir -p dist
out="dist/s3-usb-wifi-${ver}.bin"
# merged by the Provisioner's own esptool (4.8.1), the same everywhere
(cd build && PYTHONPATH=../../vendor python3 -m esptool --chip esp32s3 merge_bin -o "../${out}" @flash_args)
(cd dist && sha256sum "s3-usb-wifi-${ver}.bin" > SHA256SUMS && cat SHA256SUMS)
