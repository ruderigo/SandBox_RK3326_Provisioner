"""What an ESP firmware file is, from its own bytes, so a file chosen with
+ From File goes where it belongs (or isn't written at all):

- a **full image** (bootloader, partition table, app; what `esptool
  merge_bin` makes, or a MicroPython .bin): written whole after an erase, at
  0x0 (or 0x1000 on a classic ESP32 when the file starts with its
  bootloader);
- an **app image** (one program, e.g. WLED's .bin): written to the board's
  app slot, after its partition table is read and the slot is checked;
- anything else (a bootloader alone, a partition table, not an ESP image):
  refused.

The chip the image was built for (its header) must be the board's.
"""

import struct

ESP_MAGIC = 0xE9
APP_DESC_MAGIC = 0xABCD5432
PART_MAGIC = b"\xaa\x50"
CHIP_IDS = {0x0000: "esp32", 0x0002: "esp32s2", 0x0005: "esp32c3", 0x0009: "esp32s3", 0x000C: "esp32c2",
            0x000D: "esp32c6", 0x0010: "esp32h2", 0x0012: "esp32p4", 0x0014: "esp32c61", 0x0017: "esp32c5"}
FLASH_MB = {0: 1, 1: 2, 2: 4, 3: 8, 4: 16, 5: 32, 6: 64, 7: 128}
APP_SLOT = 0x10000


def _header(data, at):
    """(chip, flash_mb, segments) of the image header at `at`, or None."""
    if len(data) < at + 24 or data[at] != ESP_MAGIC:
        return None
    segments = data[at + 1]
    if not 1 <= segments <= 16:
        return None
    flash_mb = FLASH_MB.get(data[at + 3] >> 4)
    chip_id = struct.unpack_from("<H", data, at + 12)[0]
    return CHIP_IDS.get(chip_id, "unknown chip %d" % chip_id), flash_mb, segments


def _has_table(data, at):
    return len(data) >= at + 32 and data[at:at + 2] == PART_MAGIC


def _is_app(data, at):
    """An app image has its esp_app_desc_t right after the first segment's header."""
    return len(data) >= at + 0x24 and struct.unpack_from("<I", data, at + 0x20)[0] == APP_DESC_MAGIC


def _app_name(data, at):
    try:
        ver = data[at + 0x30:at + 0x50].split(b"\0")[0].decode("utf-8", "replace")
        name = data[at + 0x50:at + 0x70].split(b"\0")[0].decode("utf-8", "replace")
        return name, ver
    except Exception:
        return "", ""


def inspect(data):
    """{"kind": "full"|"app", "offset": int, "chip", "flash_mb", "name", "version"}
    or {"kind": "unknown", "why"}."""
    if len(data) < 256:
        return {"kind": "unknown", "why": "too small to be firmware"}
    # A full image for a chip whose bootloader is at 0x0 (S2, S3, C3, ...):
    # the partition table at 0x8000.
    h = _header(data, 0)
    if h and _has_table(data, 0x8000):
        app = _find_app(data)
        name, ver = _app_name(data, app) if app is not None else ("", "")
        return {"kind": "full", "offset": 0x0, "chip": h[0], "flash_mb": h[1], "name": name, "version": ver}
    # A classic ESP32's full image starting with its bootloader (written at
    # 0x1000): the table 0x7000 into the file.
    if h and h[0] == "esp32" and _has_table(data, 0x7000):
        app = _find_app(data, base=0x1000)
        name, ver = _app_name(data, app) if app is not None else ("", "")
        return {"kind": "full", "offset": 0x1000, "chip": h[0], "flash_mb": h[1], "name": name, "version": ver}
    # A classic ESP32's full image merged from 0x0: 4 KB of 0xFF, then its bootloader.
    h1 = _header(data, 0x1000)
    if h1 and data[:0x1000].count(0xFF) == 0x1000 and _has_table(data, 0x8000):
        app = _find_app(data)
        name, ver = _app_name(data, app) if app is not None else ("", "")
        return {"kind": "full", "offset": 0x0, "chip": h1[0], "flash_mb": h1[1], "name": name, "version": ver}
    if h and _is_app(data, 0):
        name, ver = _app_name(data, 0)
        return {"kind": "app", "offset": APP_SLOT, "chip": h[0], "flash_mb": h[1], "name": name, "version": ver}
    if _has_table(data, 0):
        return {"kind": "unknown", "why": "it's a partition table alone"}
    if h:
        return {"kind": "unknown", "why": "it's an ESP image but not a program or a full image (a bootloader alone?)"}
    return {"kind": "unknown", "why": "it isn't ESP firmware (no image header)"}


def _find_app(data, base=0):
    """The first app partition's image inside a full image (from its table)."""
    at = 0x8000 - base
    for k in range(0, 0xC00, 32):
        e = data[at + k:at + k + 32]
        if len(e) < 32 or e[:2] != PART_MAGIC:
            break
        ptype, offset = e[2], struct.unpack_from("<I", e, 4)[0]
        if ptype == 0 and _is_app(data, offset - base):
            return offset - base
    return None


def describe(info):
    """One line on what it is and where it goes."""
    if info["kind"] == "unknown":
        return info["why"]
    what = "%s %s" % (info["name"], info["version"]) if info.get("name") else "a program"
    if info["kind"] == "full":
        return "A full image (%s) for the %s: erases the board, written at 0x%X" % (
            what.strip(), info["chip"].upper(), info["offset"])
    return "An app image (%s) for the %s: written to the app slot, the board's settings kept" % (
        what.strip(), info["chip"].upper())
