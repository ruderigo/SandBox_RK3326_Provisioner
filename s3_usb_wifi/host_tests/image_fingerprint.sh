#!/usr/bin/env bash
# What went into the image, to compare two builds that differ: tool
# versions, each ELF section's SHA-256, and the paths left in the image.
#   bash host_tests/image_fingerprint.sh   (after build.sh, ESP-IDF exported)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
elf=build/s3_usb_wifi.elf
echo "IDF $(cd "$IDF_PATH" && git describe --tags --dirty 2>/dev/null)"
xtensa-esp32s3-elf-gcc --version | head -1
python -c "import importlib.metadata as m; print('esp-idf-kconfig', m.version('esp-idf-kconfig'))" 2>/dev/null
sha256sum sdkconfig build/config/sdkconfig.h build/bootloader/bootloader.bin build/partition_table/partition-table.bin build/s3_usb_wifi.bin
tmp=$(mktemp -d)
for s in $(xtensa-esp32s3-elf-readelf -SW "$elf" | sed -n 's/^ *\[ *[0-9]*\] //p' | awk '$2 != "NOBITS" && $1 ~ /^\.(flash|iram|dram|rtc)/ {print $1}'); do
    xtensa-esp32s3-elf-objcopy -O binary -j "$s" "$elf" "$tmp/s" 2>/dev/null && echo "$(sha256sum < "$tmp/s" | cut -c1-16) $s"
done
rm -rf "$tmp"
echo "paths in the image:"
strings -n 6 build/s3_usb_wifi.bin | grep -E '^/|/[a-z_]+/[a-z_]+\.[ch]' | sort -u | head -40
