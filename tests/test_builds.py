#!/usr/bin/env python3
"""+ From File with your own build in a .zip (ESP-IDF, PlatformIO, Arduino):
where each file goes, everything that's refused, and the flashing (a fake
esptool). The builds are cut from the real MicroPython and WLED images.
    python3 tests/test_builds.py
"""
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["PROVISIONER_ESPTOOL"] = os.path.join(ROOT, "tests", "fake_esptool.py")
from provisioner import builds, flasher, packs  # noqa: E402

FW = os.path.join(ROOT, "firmware", "official")
with open(os.path.join(FW, "MicroPython_FullErase_v1.29.0.bin"), "rb") as _f:
    MPY = _f.read()                                     # a classic ESP32's full image, written at 0x1000
with open(os.path.join(FW, "WLED_16.0.1_ESP32.bin"), "rb") as _f:
    WLED = _f.read()                                    # a classic ESP32's app image
BOOT, TABLE, APP = MPY[:0x7000], MPY[0x7000:0x7C00], MPY[0xF000:]


def table(*rows):
    raw = b""
    for t, s, o, z, l in rows:
        raw += struct.pack("<HBBII", 0x50AA, t, s, o, z) + l.ljust(16, b"\0") + b"\0" * 4
    return raw.ljust(0xC00, b"\xff")


OTA_TABLE = table((1, 2, 0x9000, 0x5000, b"nvs"), (1, 0, 0xE000, 0x2000, b"otadata"),
                  (0, 0x10, 0x10000, 0x180000, b"app0"), (0, 0x11, 0x190000, 0x180000, b"app1"),
                  (1, 0x82, 0x310000, 0xE0000, b"spiffs"))


def zipped(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


def read(files):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "build.zip")
    with open(p, "wb") as f:
        f.write(zipped(files))
    return packs.read_zip(p)


def offsets(plan):
    return [(x["offset"], os.path.basename(x["name"]), x["what"]) for x in plan["parts"]]


class WhereEachFileGoes(unittest.TestCase):
    def test_arduino_export_by_names(self):
        files = read({"sketch.ino.bootloader.bin": BOOT, "sketch.ino.partitions.bin": TABLE,
                      "sketch.ino.bin": APP, "sketch.ino.merged.bin": MPY, "sketch.ino.elf": b"x"})
        self.assertTrue(builds.looks_like(files))
        p = builds.plan(files, "esp32", 4)
        self.assertEqual(offsets(p), [(0x1000, "sketch.ino.bootloader.bin", "bootloader"),
                                      (0x8000, "sketch.ino.partitions.bin", "partition table"),
                                      (0x10000, "sketch.ino.bin", "program")])     # the merged one left out
        self.assertEqual(builds.describe(p)[0], "A build for the ESP32, 3 files: erases the board, then writes")
        self.assertEqual(builds.describe(p)[1], "0x01000 · 28 KB · sketch.ino.bootloader.bin")
        self.assertEqual(builds.describe(p)[3], "0x10000 · 1688 KB · sketch.ino.bin (program)")

    def test_platformio_with_ota_data_and_a_filesystem(self):
        files = read({".pio/build/esp32dev/bootloader.bin": BOOT, ".pio/build/esp32dev/partitions.bin": OTA_TABLE,
                      ".pio/build/esp32dev/firmware.bin": WLED, ".pio/build/esp32dev/boot_app0.bin": b"\xff" * 8192,
                      ".pio/build/esp32dev/littlefs.bin": b"\0" * 4096})
        p = builds.plan(files, "esp32", 4)
        self.assertEqual([o for o, n, w in offsets(p)], [0x1000, 0x8000, 0xE000, 0x10000, 0x310000])
        self.assertEqual(p["parts"][3]["what"], "program")

    def test_esp_idf_flash_args(self):
        args = ("--flash_mode dio --flash_freq 40m --flash_size 4MB\n"
                "0x1000 bootloader/bootloader.bin\n0x10000 hello.bin\n0x8000 partition_table/partition-table.bin\n")
        files = read({"build/flash_args": args, "build/bootloader/bootloader.bin": BOOT, "build/hello.bin": APP,
                      "build/partition_table/partition-table.bin": TABLE, "build/hello.elf": b"x"})
        p = builds.plan(files, "esp32", 4)
        self.assertEqual([o for o, n, w in offsets(p)], [0x1000, 0x8000, 0x10000])

    def test_esp_idf_flasher_args_json_wins_and_says_its_chip(self):
        j = {"flash_files": {"0x1000": "bootloader/bootloader.bin", "0x8000": "partition_table/partition-table.bin",
                             "0x10000": "hello.bin"}, "extra_esptool_args": {"chip": "esp32"}}
        files = read({"flasher_args.json": json.dumps(j), "flash_args": "0x0 nothing.bin\n",
                      "bootloader/bootloader.bin": BOOT, "partition_table/partition-table.bin": TABLE,
                      "hello.bin": APP})
        self.assertEqual(len(builds.plan(files, "esp32", 4)["parts"]), 3)
        with self.assertRaisesRegex(builds.BuildError, "built for the ESP32; this board is an ESP32S3"):
            builds.plan(files, "esp32s3", 8)

    def test_two_builds_in_one_zip_the_one_for_this_chip(self):
        s3 = {"flasher_args.json": json.dumps({"flash_files": {"0x0": "b.bin"},
                                                "extra_esptool_args": {"chip": "esp32s3"}}), "b.bin": BOOT}
        files = read(dict({"s3/" + k: v for k, v in s3.items()},
                          **{"classic/bootloader.bin": BOOT, "classic/partitions.bin": TABLE, "classic/app.bin": APP}))
        self.assertEqual(builds.plan(files, "esp32", 4)["parts"][0]["name"], "classic/bootloader.bin")

    def test_a_pack_isnt_a_build(self):
        self.assertFalse(builds.looks_like({"pack.json": b"{}", "tavern/plugin.json": b"{}"}))


class Refused(unittest.TestCase):
    def base(self, **over):
        f = {"bootloader.bin": BOOT, "partitions.bin": TABLE, "firmware.bin": APP}
        f.update(over)
        return read({k: v for k, v in f.items() if v is not None})

    def refused(self, files, why, chip="esp32", mb=4):
        with self.assertRaisesRegex(builds.BuildError, why):
            builds.plan(files, chip, mb)

    def test_the_wrong_chip(self):
        self.refused(self.base(), "built for the ESP32; this board is an ESP32S3", chip="esp32s3", mb=8)

    def test_two_programs(self):
        self.refused(self.base(**{"other.bin": WLED}), "exactly one program")

    def test_no_bootloader_or_table(self):
        self.refused(self.base(**{"partitions.bin": None}), "no build in it|one bootloader.bin and one partitions")
        self.refused(read({"flash_args": "0x10000 a.bin\n0x8000 t.bin\n", "a.bin": APP, "t.bin": TABLE}),
                     "no bootloader")
        self.refused(read({"flash_args": "0x1000 b.bin\n0x10000 a.bin\n", "a.bin": APP, "b.bin": BOOT}),
                     "no partition table")

    def test_a_listed_file_missing(self):
        self.refused(read({"flash_args": "0x1000 b.bin\n0x8000 t.bin\n0x10000 gone.bin\n", "b.bin": BOOT,
                           "t.bin": TABLE}), "gone.bin is listed but not in the zip")

    def test_overlapping(self):
        self.refused(read({"flash_args": "0x1000 b.bin\n0x7000 t.bin\n0x10000 a.bin\n", "b.bin": BOOT,
                           "t.bin": TABLE, "a.bin": APP}), "overlap")

    def test_bootloader_at_the_wrong_address(self):
        self.refused(read({"flash_args": "0x0 b.bin\n0x8000 t.bin\n0x10000 a.bin\n", "b.bin": BOOT[:0x6000],
                           "t.bin": TABLE, "a.bin": APP}), "bootloader would go at 0x0; the ESP32's goes at 0x1000")

    def test_program_bigger_than_its_partition(self):
        small = table((1, 2, 0x9000, 0x5000, b"nvs"), (0, 0, 0x10000, 0x100000, b"factory"))
        self.refused(self.base(**{"partitions.bin": small}), "bigger than its app partition factory")

    def test_program_where_there_is_no_app_partition(self):
        self.refused(read({"flash_args": "0x1000 b.bin\n0x8000 t.bin\n0x20000 a.bin\n", "b.bin": BOOT,
                           "t.bin": TABLE, "a.bin": APP}), "no app partition")

    def test_too_big_for_the_boards_flash(self):
        self.refused(self.base(), "the board has 1 MB", mb=1)
        big = table((1, 2, 0x9000, 0x5000, b"nvs"), (0, 0, 0x10000, 0x1F0000, b"factory"), (1, 0x82, 0x200000, 0x10000, b"fs"))
        self.refused(self.base(**{"partitions.bin": big}), "partition fs ends past the board's 2 MB", mb=2)

    def test_not_on_a_4k_boundary(self):
        self.refused(read({"flash_args": "0x1000 b.bin\n0x8000 t.bin\n0x10000 a.bin\n0x9100 n.bin\n",
                           "b.bin": BOOT, "t.bin": TABLE, "a.bin": APP, "n.bin": b"\0" * 16}), "4 KB boundary")


class Flashing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.calls = os.path.join(self.dir, "calls")
        os.environ.update(FAKE_CALLS=self.calls, FAKE_BOARD="esp32")
        for k in ("FAKE_FAIL", "FAKE_TABLE"):
            os.environ.pop(k, None)
        files = read({"bootloader.bin": BOOT, "partitions.bin": TABLE, "firmware.bin": APP})
        self.plan = builds.plan(files, "esp32", 4)

    def test_erase_write_every_file_read_back(self):
        pairs = builds.extract(self.plan, self.dir)
        self.assertEqual([o for o, p in pairs], ["0x1000", "0x8000", "0x10000"])
        with open(pairs[2][1], "rb") as f:
            self.assertEqual(f.read(), APP)
        steps = []
        ok, msg = flasher.flash_build("/dev/ttyUSB0", "esp32", pairs, "mine.zip", on_step=steps.append)
        self.assertTrue(ok, msg)
        self.assertEqual(steps, ["Erasing the whole flash", "Writing mine.zip (3 files)", "Reading it back"])
        with open(self.calls) as f:
            calls = f.read().splitlines()
        self.assertTrue(calls[0].endswith("erase_flash"))
        self.assertIn("write_flash --flash_mode keep --flash_size keep 0x1000 %s 0x8000 %s 0x10000 %s" % (
            pairs[0][1], pairs[1][1], pairs[2][1]), calls[1])
        self.assertIn("verify_flash 0x1000", calls[2])

    def test_a_failed_erase_writes_nothing(self):
        os.environ["FAKE_FAIL"] = "erase_flash"
        ok, msg = flasher.flash_build("/dev/ttyUSB0", "esp32", builds.extract(self.plan, self.dir), "mine.zip")
        self.assertFalse(ok)
        with open(self.calls) as f:
            self.assertNotIn("write_flash", f.read())


if __name__ == "__main__":
    unittest.main(verbosity=1)
