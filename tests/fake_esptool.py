#!/usr/bin/env python3
"""A stand-in for esptool in the tests: answers like esptool 4.8 does for
the board named in FAKE_BOARD (esp32, heltec, s3), records each call in
FAKE_CALLS, and fails a step when FAKE_FAIL names it (e.g. "write_flash")."""
import os
import struct
import sys
import time

BOARD = os.environ.get("FAKE_BOARD", "esp32")
CHIPS = {
    "esp32": ("ESP32", "ESP32-D0WD-V3 (revision v3.1)", "4MB", "Features: WiFi, BT, Dual Core, 240MHz"),
    "heltec": ("ESP32-S3", "ESP32-S3 (QFN56) (revision v0.2)", "8MB", "Features: WiFi, BLE"),
    "s3": ("ESP32-S3", "ESP32-S3 (QFN56) (revision v0.2)", "16MB", "Features: WiFi, BLE, Embedded PSRAM 8MB (AP_3v3)"),
}
args = sys.argv[1:]
if os.environ.get("FAKE_CALLS"):
    with open(os.environ["FAKE_CALLS"], "a") as f:
        f.write(" ".join(args) + "\n")
cmd = next((a for a in args if a in ("flash_id", "read_flash", "write_flash", "erase_flash", "verify_flash")), "")
fam, chip, flash, feat = CHIPS[BOARD]
print("esptool.py v4.8.1")
print("Serial port %s" % args[args.index("--port") + 1])
print("Connecting....")
if os.environ.get("FAKE_FAIL") == "connect":
    print("A fatal error occurred: Failed to connect to ESP32: No serial data received.")
    sys.exit(2)
print("Detecting chip type... %s" % fam)
print("Chip is %s" % chip)
print(feat)
print("Crystal is 40MHz")
print("MAC: 24:6f:28:aa:bb:cc")
print("Uploading stub...")
if os.environ.get("FAKE_FAIL") == cmd:
    print("A fatal error occurred: %s failed (fake)" % cmd)
    sys.exit(2)
if cmd == "flash_id":
    print("Manufacturer: c8\nDevice: 4016\nDetected flash size: %s" % flash)
elif cmd == "read_flash":
    dest = args[-1]
    slot = int(os.environ.get("FAKE_APP_SLOT_KB", "1280")) * 1024
    rows = [(1, 2, 0x9000, 0x5000, b"nvs"), (1, 0, 0xE000, 0x2000, b"otadata"), (0, 0x10, 0x10000, slot, b"app0")]
    raw = b""
    if os.environ.get("FAKE_TABLE") != "none":
        for t, s, o, z, l in rows:
            raw += struct.pack("<HBBII", 0x50AA, t, s, o, z) + l.ljust(16, b"\0") + b"\0" * 4
    raw = raw.ljust(0xC00, b"\xff")
    with open(dest, "wb") as f:
        f.write(raw)
    print("Read 3072 bytes at 0x00008000 in 0.4 seconds (61.4 kbit/s)...")
elif cmd == "write_flash":
    for pct in (0, 25, 50, 75, 100):
        sys.stdout.write("Writing at 0x%08x... (%d %%)\r" % (0x10000 + pct * 100, pct))
        sys.stdout.flush()
        time.sleep(0.01)
    print("\nWrote 1304720 bytes (870000 compressed) at 0x00010000 in 20.1 seconds")
    print("Hash of data verified.")
elif cmd == "verify_flash":
    print("Verifying 0x13e890 (1304720) bytes @ 0x00010000 in flash against image...")
    if os.environ.get("FAKE_FAIL") == "verify":
        print("-- verify FAILED (digest mismatch)")
        sys.exit(2)
    print("-- verify OK (digest matched)")
elif cmd == "erase_flash":
    print("Erasing flash (this may take a while)...\nChip erase completed successfully in 9.1s")
print("Hard resetting via RTS pin...")
