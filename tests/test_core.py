#!/usr/bin/env python3
"""The Provisioner's core without a board: detection from a fake /sys, the
catalogue and its checksums, and every flash path through a fake esptool.
    python3 tests/test_core.py
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["PROVISIONER_ESPTOOL"] = os.path.join(ROOT, "tests", "fake_esptool.py")
from provisioner import boards, catalog, flasher  # noqa: E402


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class FakeTty:
    def __init__(self):
        self.root = tempfile.mkdtemp()
        self.tty = os.path.join(self.root, "class", "tty")
        os.makedirs(self.tty)

    def plug(self, name, usb, product="", serial="0001"):
        vid, pid = usb.split(":")
        devdir = os.path.join(self.root, "devices", name)
        intf = os.path.join(devdir, name + ":1.0")
        os.makedirs(intf)
        _w(os.path.join(devdir, "idVendor"), vid)
        _w(os.path.join(devdir, "idProduct"), pid)
        _w(os.path.join(devdir, "product"), product)
        _w(os.path.join(devdir, "serial"), serial)
        os.makedirs(os.path.join(self.tty, name))
        os.symlink(intf, os.path.join(self.tty, name, "device"))


class Detect(unittest.TestCase):
    def test_ports_and_their_usb_chips(self):
        t = FakeTty()
        t.plug("ttyUSB0", "10c4:ea60", "CP2102 USB to UART Bridge Controller")
        t.plug("ttyACM0", "303a:1001", "USB JTAG/serial debug unit")
        os.makedirs(os.path.join(t.tty, "tty1"))                 # not a USB serial port
        ports = boards.list_ports(t.tty, "/dev")
        self.assertEqual([(p["port"], p["usb"], p["usb_chip"], p["native"]) for p in ports],
                         [("/dev/ttyACM0", "303a:1001", "ESP32-S3/C3 native USB", True),
                          ("/dev/ttyUSB0", "10c4:ea60", "CP210x USB-serial", False)])

    def test_the_chip_settles_the_board(self):
        for board, usb, want in (("heltec", "10c4:ea60", "heltec_v3"), ("esp32", "10c4:ea60", "esp32"),
                                 ("s3", "303a:1001", "esp32s3"), ("s3", "1a86:55d3", "esp32s3")):
            os.environ["FAKE_BOARD"] = board
            ok, out = flasher.probe("/dev/ttyUSB0")
            info = boards.parse_probe(out)
            self.assertEqual(boards.identify(info["chip"], usb)["id"], want, (board, usb))
        os.environ["FAKE_BOARD"] = "s3"
        info = boards.parse_probe(flasher.probe("/dev/ttyACM0")[1])
        self.assertEqual((info["flash_mb"], info["psram_mb"], info["mac"]), (16, 8, "24:6f:28:aa:bb:cc"))

    def test_a_classic_esp32_part_name_is_the_esp32_family(self):
        info = boards.parse_probe("Chip is ESP32-D0WD-V3 (revision v3.1)\nDetected flash size: 4MB\n")
        self.assertEqual((info["chip"], info["chip_text"], info["flash_mb"]), ("esp32", "ESP32-D0WD-V3", 4))


class Catalogue(unittest.TestCase):
    def test_every_ready_image_is_there_and_matches_its_sha256(self):
        entries = catalog.load()
        ready = [e for e in entries if e["status"] == "ready"]
        self.assertGreaterEqual(len(ready), 2)
        for e in ready:
            self.assertIsNone(catalog.check(e), e["id"])
            self.assertTrue(e.get("licence") and e.get("source"), e["id"])

    def test_what_fits_which_board(self):
        entries = catalog.load()
        ids = lambda b: [e["id"] for e in catalog.for_board(entries, b)]
        self.assertEqual(ids({"id": "esp32", "chip": "esp32"}), ["wled-16.0.1-esp32", "micropython-1.29.0-esp32"])
        self.assertEqual(ids({"id": "heltec_v3", "chip": "esp32s3"}), ["rnode-heltec-v3"])
        self.assertEqual(ids({"id": "esp32s3", "chip": "esp32s3"}), ["s3-usb-wifi"])

    def test_a_changed_image_is_refused(self):
        d = tempfile.mkdtemp()
        shutil.copytree(os.path.join(ROOT, "firmware"), os.path.join(d, "fw"))
        e = [x for x in catalog.load(os.path.join(d, "fw")) if x["id"].startswith("wled")][0]
        with open(e["path"], "ab") as f:
            f.write(b"x")
        self.assertIn("SHA-256", catalog.check(e))


class Flash(unittest.TestCase):
    def setUp(self):
        self.calls = os.path.join(tempfile.mkdtemp(), "calls")
        os.environ.update(FAKE_CALLS=self.calls, FAKE_BOARD="esp32")
        for k in ("FAKE_FAIL", "FAKE_TABLE", "FAKE_APP_SLOT_KB"):
            os.environ.pop(k, None)
        self.entries = {e["id"]: e for e in catalog.load()}
        self.board = {"id": "esp32", "chip": "esp32", "flash_mb": 4}

    def called(self):
        with open(self.calls) as f:
            return [l.split()[-1] if "write_flash" not in l else "write_flash" for l in f]

    def test_app_image_checks_the_table_writes_and_reads_back(self):
        steps, pcts = [], []
        ok, msg = flasher.flash("/dev/ttyUSB0", self.entries["wled-16.0.1-esp32"], self.board,
                                on_step=steps.append, on_progress=pcts.append)
        self.assertTrue(ok, msg)
        self.assertEqual(steps, ["Reading the partition table", "Writing WLED 16.0.1", "Reading it back"])
        self.assertEqual(pcts[-1], 100)
        self.assertIn(50, pcts)
        with open(self.calls) as f:
            calls = f.read()
        self.assertIn("read_flash 0x8000 0xC00", calls)
        self.assertIn("write_flash --flash_mode keep --flash_size keep 0x10000", calls)
        self.assertIn("verify_flash 0x10000", calls)
        self.assertNotIn("erase_flash", calls)                  # an app image never erases

    def test_app_image_too_big_for_the_slot_is_not_written(self):
        os.environ["FAKE_APP_SLOT_KB"] = "1024"
        ok, msg = flasher.flash("/dev/ttyUSB0", self.entries["wled-16.0.1-esp32"], self.board)
        self.assertFalse(ok)
        self.assertIn("bigger than the app slot", msg)
        with open(self.calls) as f:
            self.assertNotIn("write_flash", f.read())

    def test_no_partition_table_means_no_app_write(self):
        os.environ["FAKE_TABLE"] = "none"
        ok, msg = flasher.flash("/dev/ttyUSB0", self.entries["wled-16.0.1-esp32"], self.board)
        self.assertFalse(ok)
        with open(self.calls) as f:
            self.assertNotIn("write_flash", f.read())

    def test_full_image_erases_then_writes_at_0x1000(self):
        ok, msg = flasher.flash("/dev/ttyUSB0", self.entries["micropython-1.29.0-esp32"], self.board)
        self.assertTrue(ok, msg)
        with open(self.calls) as f:
            calls = f.read()
        self.assertLess(calls.index("erase_flash"), calls.index("write_flash"))
        self.assertIn("0x1000 ", calls)

    def test_full_image_needs_the_flash_it_says(self):
        ok, msg = flasher.flash("/dev/ttyUSB0", self.entries["micropython-1.29.0-esp32"], dict(self.board, flash_mb=2))
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.calls))            # nothing run at all

    def test_a_read_back_that_differs_is_a_failure(self):
        os.environ["FAKE_FAIL"] = "verify"
        ok, msg = flasher.flash("/dev/ttyUSB0", self.entries["wled-16.0.1-esp32"], self.board)
        self.assertFalse(ok)
        self.assertIn("read-back differs", msg)

    def test_a_board_that_doesnt_answer_says_what_to_do(self):
        os.environ["FAKE_FAIL"] = "connect"
        ok, msg = flasher.flash("/dev/ttyUSB0", self.entries["wled-16.0.1-esp32"], self.board)
        self.assertFalse(ok)
        self.assertIn("hold BOOT", msg)

    def test_progress_lines(self):
        self.assertEqual(flasher.progress_of("Writing at 0x00010000... (42 %)"), 42)
        self.assertEqual(flasher.progress_of("Writing at 0x00010000... (100%)"), 100)
        self.assertIsNone(flasher.progress_of("Chip is ESP32"))

    def test_the_real_bundled_esptool_runs(self):
        old = os.environ.pop("PROVISIONER_ESPTOOL")
        try:
            ok, out = flasher.run(["version"])
        finally:
            os.environ["PROVISIONER_ESPTOOL"] = old
        self.assertTrue(ok, out)
        self.assertIn("4.8.1", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
