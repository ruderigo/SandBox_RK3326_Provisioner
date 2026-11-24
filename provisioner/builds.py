"""A build's files in a .zip (+ From File): what ESP-IDF, PlatformIO and the
Arduino IDE make when you build your own firmware, flashed in one go.

A build is several files, each with its own address: the bootloader, the
partition table, the program, and sometimes the OTA data or a filesystem
image. Where each goes is read, in this order, from:

1. **flasher_args.json** (ESP-IDF's build folder): its "flash_files";
2. **flash_args** (ESP-IDF): one "0x10000 app.bin" line per file;
3. **the files' names** (PlatformIO's .pio/build/<env>, the Arduino IDE's
   "Export compiled binary"): `*bootloader.bin` at the chip's bootloader
   address, `*partitions.bin` (or `partition-table.bin`) at 0x8000, the one
   program at the table's first app partition, `boot_app0.bin` at its OTA
   data, `littlefs.bin` / `spiffs.bin` / `fatfs.bin` at its data partition.

Nothing is guessed beyond that, and nothing is written until all of it is
checked: every file is in the zip, none overlap, all fit the board's flash,
there is a bootloader at the right address and a partition table, every
image is built for the board's chip, and every program fits the app
partition it lands on. A build is a full install: the whole flash is erased
first, then every file written and read back.
"""

import json
import os
import posixpath
import re

from . import flasher, images

BOOT_AT = {"esp32": 0x1000, "esp32s2": 0x1000, "esp32p4": 0x2000, "esp32c5": 0x2000}   # others: 0x0
TABLE_AT = 0x8000
SKIP = re.compile(r"(\.merged|\.factory|[._-]merged|[._-]factory)\.bin$", re.I)           # one-file images
FS_NAMES = {"littlefs.bin": (0x82, 0x83), "spiffs.bin": (0x82,), "fatfs.bin": (0x81,)}


class BuildError(Exception):
    pass


def boot_at(chip):
    return BOOT_AT.get(chip, 0x0)


def looks_like(files):
    """True when a zip's names look like a build rather than a Stump pack."""
    base = [posixpath.basename(n) for n in files]
    if "flasher_args.json" in base or "flash_args" in base:
        return True
    return (any(b.endswith("bootloader.bin") for b in base)
            and any(b.endswith("partitions.bin") or b == "partition-table.bin" for b in base))


def _num(s):
    try:
        return int(str(s), 0)
    except ValueError:
        raise BuildError("%r isn't an address" % s)


def _rel(d, rel):
    return posixpath.normpath(posixpath.join(d, rel) if d else rel)


def _from_json(files, name):
    d = posixpath.dirname(name)
    try:
        j = json.loads(files[name].decode("utf-8"))
        flash = j["flash_files"]
        assert isinstance(flash, dict) and flash
    except (ValueError, KeyError, AssertionError, AttributeError, UnicodeDecodeError):
        raise BuildError("its flasher_args.json has no flash_files")
    chip = (j.get("extra_esptool_args") or {}).get("chip") if isinstance(j.get("extra_esptool_args"), dict) else None
    return [(_num(o), _rel(d, p)) for o, p in flash.items()], chip


def _from_flash_args(files, name):
    d = posixpath.dirname(name)
    parts = []
    for line in files[name].decode("utf-8", "replace").splitlines():
        words = line.split()
        if not words or words[0].startswith("-"):
            continue                                   # --flash_mode dio --flash_size 4MB ...
        if len(words) != 2:
            raise BuildError("its flash_args has a line it can't read: %r" % line.strip())
        parts.append((_num(words[0]), _rel(d, words[1])))
    if not parts:
        raise BuildError("its flash_args lists no files")
    return parts, None


def _first(table, ptype, subs=None):
    for t, s, start, size, label in table:
        if t == ptype and (subs is None or s in subs):
            return start
    return None


def _from_names(files, d):
    here = {posixpath.basename(n): n for n in files if posixpath.dirname(n) == d and n.lower().endswith(".bin")}
    boot = [n for b, n in here.items() if b.endswith("bootloader.bin")]
    table = [n for b, n in here.items() if b.endswith("partitions.bin") or b == "partition-table.bin"]
    if len(boot) != 1 or len(table) != 1:
        raise BuildError("it needs one bootloader.bin and one partitions.bin side by side")
    boot, table = boot[0], table[0]
    h = images._header(files[boot], 0)
    if not h or images._is_app(files[boot], 0):
        raise BuildError("%s isn't a bootloader" % posixpath.basename(boot))
    rows = flasher.parse_partitions(files[table])
    if not rows:
        raise BuildError("%s isn't a partition table" % posixpath.basename(table))
    parts = [(boot_at(h[0]), boot), (TABLE_AT, table)]
    used = {boot, table}
    apps = [n for b, n in here.items() if n not in used and not SKIP.search(b) and images._is_app(files[n], 0)]
    if len(apps) != 1:
        raise BuildError("it needs exactly one program next to its bootloader (found %d)" % len(apps))
    at = _first(rows, 0)
    if at is None:
        raise BuildError("its partition table has no app partition")
    parts.append((at, apps[0]))
    used.add(apps[0])
    if "boot_app0.bin" in here:
        parts.append((_first(rows, 1, (0,)) or 0xE000, here["boot_app0.bin"]))
    for b, subs in FS_NAMES.items():
        if b in here:
            at = _first(rows, 1, subs)
            if at is None:
                raise BuildError("%s has no data partition to go to in its table" % b)
            parts.append((at, here[b]))
    return parts, None


def _candidates(files):
    """[(how, where)]: each folder in the zip that holds a build."""
    found = {}
    for n in files:
        b, d = posixpath.basename(n), posixpath.dirname(n)
        if b == "flasher_args.json":
            found[d] = ("json", n)
        elif b == "flash_args" and found.get(d, ("",))[0] != "json":
            found[d] = ("args", n)
    listed = list(found)                               # their subfolders (bootloader/, ...) are theirs

    def theirs(d):
        return any(D == "" or d == D or d.startswith(D + "/") for D in listed)
    for n in files:
        d = posixpath.dirname(n)
        if posixpath.basename(n).endswith("bootloader.bin") and d not in found and not theirs(d):
            found[d] = ("names", d)
    return [found[d] for d in sorted(found)]


def _read(files, how, where):
    if how == "json":
        return _from_json(files, where)
    if how == "args":
        return _from_flash_args(files, where)
    return _from_names(files, where)


def plan(files, chip, flash_mb=0):
    """The build in a zip ({name: bytes}, from packs.read_zip) for a board of
    this chip and flash size (MB, 0 if not known): {"parts": [{"offset",
    "name", "size", "what"}], "chip", "name", "version", "data": {name: bytes},
    "end"}. Anything that doesn't add up raises BuildError, saying why."""
    builds = _candidates(files)
    if not builds:
        raise BuildError("no build in it (no flasher_args.json, flash_args, or bootloader.bin)")
    tried = []
    for how, where in builds:
        try:
            return _check(files, *_read(files, how, where), chip=chip, flash_mb=flash_mb)
        except BuildError as e:
            tried.append((where or "(top)", e))
    if len(tried) == 1:
        raise tried[0][1]
    fits = [w for w, e in tried if "built for the" not in str(e)]
    if not fits:
        raise BuildError("none of its %d builds is for the %s" % (len(tried), chip.upper()))
    raise BuildError("%s: %s" % tried[[w for w, e in tried].index(fits[0])])


def _check(files, parts, said_chip, chip, flash_mb):
    if said_chip and said_chip.replace("-", "") != chip:
        raise BuildError("it's built for the %s; this board is an %s" % (said_chip.upper(), chip.upper()))
    data, out = {}, []
    for off, name in sorted(parts):
        if name not in files:
            raise BuildError("%s is listed but not in the zip" % name)
        if off % 0x1000:
            raise BuildError("%s would go at 0x%X, not on a 4 KB boundary" % (posixpath.basename(name), off))
        b = files[name]
        if not b:
            raise BuildError("%s is empty" % posixpath.basename(name))
        data[name] = b
        out.append({"offset": off, "name": name, "size": len(b), "what": "data"})
    for a, b in zip(out, out[1:]):
        if a["offset"] + a["size"] > b["offset"]:
            raise BuildError("%s and %s overlap" % (posixpath.basename(a["name"]), posixpath.basename(b["name"])))
    end = out[-1]["offset"] + out[-1]["size"]
    table = None
    for p in out:
        b = data[p["name"]]
        if images._has_table(b, 0) and flasher.parse_partitions(b):
            p["what"], table = "partition table", table or flasher.parse_partitions(b)
            continue
        h = images._header(b, 0)
        if not h:
            continue                                   # OTA data, a filesystem image, NVS: data
        if h[0] != chip:
            raise BuildError("%s is built for the %s; this board is an %s" % (
                posixpath.basename(p["name"]), h[0].upper(), chip.upper()))
        p["what"] = "program" if images._is_app(b, 0) else "bootloader"
    boots = [p for p in out if p["what"] == "bootloader"]
    if not boots:
        raise BuildError("it has no bootloader")
    if boots[0]["offset"] != boot_at(chip):
        raise BuildError("its bootloader would go at 0x%X; the %s's goes at 0x%X" % (
            boots[0]["offset"], chip.upper(), boot_at(chip)))
    if table is None:
        raise BuildError("it has no partition table")
    progs = [p for p in out if p["what"] == "program"]
    if not progs:
        raise BuildError("it has no program")
    for p in progs:
        slot = [(start, size, label) for t, s, start, size, label in table if t == 0 and start == p["offset"]]
        if not slot:
            raise BuildError("%s would go at 0x%X, where its partition table has no app partition" % (
                posixpath.basename(p["name"]), p["offset"]))
        if p["size"] > slot[0][1]:
            raise BuildError("%s (%d KB) is bigger than its app partition %s (%d KB)" % (
                posixpath.basename(p["name"]), p["size"] // 1024, slot[0][2], slot[0][1] // 1024))
    have = int(flash_mb * 1024 * 1024) if flash_mb else 0
    if have and end > have:
        raise BuildError("it needs %.1f MB of flash; the board has %g MB" % (end / 1048576.0, flash_mb))
    if have:
        for t, s, start, size, label in table:
            if start + size > have:
                raise BuildError("its partition %s ends past the board's %g MB of flash" % (label, flash_mb))
    name, ver = images._app_name(data[progs[0]["name"]], 0)
    return {"parts": out, "chip": chip, "name": name, "version": ver, "data": data, "end": end}


def describe(p):
    """The lines a person reads before saying yes: one per file, its address,
    size and name (what it is when the name doesn't say)."""
    what = ("%s %s" % (p["name"], p["version"])).strip()
    lines = ["A build%s for the %s, %d files: erases the board, then writes" % (
        " (%s)" % what if what else "", p["chip"].upper(), len(p["parts"]))]
    for x in p["parts"]:
        name = posixpath.basename(x["name"])
        tag = x["what"].split()[0]
        lines.append("0x%05X · %s · %s%s" % (x["offset"], "%d KB" % max(1, x["size"] // 1024), name,
                                             "" if tag in name.lower() or x["what"] == "data" else " (%s)" % x["what"]))
    return lines


def extract(p, folder):
    """Writes each file of the plan into folder: [("0x...", path)] for esptool."""
    pairs = []
    for i, x in enumerate(p["parts"]):
        path = os.path.join(folder, "%02d-%s" % (i, re.sub(r"[^A-Za-z0-9._-]", "_", posixpath.basename(x["name"]))))
        with open(path, "wb") as f:
            f.write(p["data"][x["name"]])
        pairs.append(("0x%X" % x["offset"], path))
    return pairs
