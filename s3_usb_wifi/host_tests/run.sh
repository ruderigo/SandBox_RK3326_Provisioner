#!/usr/bin/env bash
# The firmware's ESP-free parts, built and tested on this computer.
set -euo pipefail
cd "$(dirname "$0")"
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
san=""
if cc -fsanitize=address,undefined -x c -o "$out/probe" - <<<'int main(void){return 0;}' 2>/dev/null; then
    san="-fsanitize=address,undefined"
fi
cc -std=c11 -Wall -Wextra -Werror $san -I../main -o "$out/test_core" \
    test_core.c ../main/dhcp_core.c ../main/util_core.c
"$out/test_core"
