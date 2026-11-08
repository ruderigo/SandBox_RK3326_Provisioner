#!/usr/bin/env python3
"""A CH340 driven through libusb (provisioner/usbserial): its setup as
Linux's ch341.c does it, its speeds, DTR/RTS, data both ways, the ports
listed from sysfs, pyserial's ch340://, esptool's reset for it, the real
libusb-1.0 through ctypes (when this computer has it), and the Stump's
serial link to Team Stump's pretend board over a pretend CH340.
    python3 tests/test_usbserial.py
"""
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))
import serial  # noqa: E402
from provisioner import usbserial as U  # noqa: E402

TESTS = os.path.join(ROOT, "tests")


class FakeLib:
    """libusb as the CH340 needs it: controls recorded, bulk to a board."""

    def __init__(self, version=0x31, board=None):
        self.version, self.board = version, board
        self.controls, self.written, self.incoming = [], b"", b""
        self.cv = threading.Condition()
        self.claimed = self.released = 0
        self.gone = False

    def find(self, bus, address):
        if (bus, address) != (1, 4):
            raise U.LibusbError(-4, "no USB device %d-%d" % (bus, address))
        return "handle"

    def claim(self, h):
        self.claimed += 1

    def release(self, h):
        self.released += 1

    def control(self, h, rtype, req, value, index, length=0, timeout=1000):
        self.controls.append((rtype, req, value, index))
        return bytes([self.version, 0]) if req == U.REQ_READ_VERSION else b""

    def feed(self, b):
        with self.cv:
            self.incoming += b
            self.cv.notify_all()

    def bulk(self, h, ep, data=None, size=0, timeout=100):
        if self.gone:
            raise U.LibusbError(-4)
        if data is not None:
            self.written += data
            if self.board:
                self.board.stdin.write(bytes(data))
                self.board.stdin.flush()
            return len(data)
        with self.cv:
            if not self.incoming:
                self.cv.wait(timeout / 1000.0)
            out, self.incoming = self.incoming[:size], self.incoming[size:]
        return out

    def lines(self):
        """The modem line states sent, as (dtr, rts), from the inverted bits."""
        return [(not v & U.MODEM_DTR, not v & U.MODEM_RTS) for t, r, v, i in self.controls if r == U.REQ_MODEM_CTRL]


class TheChip(unittest.TestCase):
    def tearDown(self):
        U._LIB[:] = []

    def test_divisors_as_linux_computes_them(self):
        self.assertEqual(U.divisor(115200), 0xCC83)                  # the classic table's 0xCC, 3 (and bit 7)
        for baud in (9600, 74880, 115200, 230400, 460800, 921600, 2000000):
            v = U.divisor(baud)
            ps, fact, div = v & 3, (v >> 2) & 1, 0x100 - (v >> 8)
            got = U.CLKRATE / (U._clk_div(ps, fact) * div)
            self.assertLess(abs(got - baud) / baud, 0.04, (baud, got))   # within what a UART takes
            self.assertTrue(v & 0x80)

    def test_setup_lines_and_data(self):
        lib = FakeLib()
        c = U.CH340(1, 4, 460800, dtr=False, rts=False, lib=lib)
        reqs = [r for _, r, _, _ in lib.controls]
        self.assertEqual(reqs, [U.REQ_READ_VERSION, U.REQ_SERIAL_INIT, U.REQ_WRITE_REG, U.REQ_WRITE_REG,
                                U.REQ_MODEM_CTRL])
        self.assertEqual(lib.controls[2][2:], (U.REG_DIVISOR << 8 | U.REG_PRESCALER, U.divisor(460800)))
        self.assertEqual(lib.controls[3][2:], (U.REG_LCR2 << 8 | U.REG_LCR, U.LCR_8N1))
        self.assertEqual(lib.lines(), [(False, False)])
        c.set_lines(dtr=True)
        c.set_lines(rts=True)
        self.assertEqual(lib.lines()[1:], [(True, False), (True, True)])
        c.write(b"hello")
        self.assertEqual(lib.written, b"hello")
        lib.feed(b"abc")
        self.assertEqual(c.read(256, 50), b"abc")
        c.close()
        self.assertEqual((lib.claimed, lib.released), (1, 1))
        old = FakeLib(version=0x27)                                   # an older chip: no LCR register
        U.CH340(1, 4, 115200, lib=old)
        self.assertEqual([r for _, r, _, _ in old.controls].count(U.REQ_WRITE_REG), 1)

    def test_the_ports_listed_from_sysfs(self):
        d = tempfile.mkdtemp()
        for name, usb, driver in (("1-4", "1a86:7523", False), ("1-5", "1a86:7523", True), ("1-6", "10c4:ea60", False)):
            os.makedirs(os.path.join(d, name, name + ":1.0"))
            vid, pid = usb.split(":")
            for f, v in (("idVendor", vid), ("idProduct", pid), ("busnum", "1"), ("devnum", name[2:])):
                with open(os.path.join(d, name, f), "w") as fh:
                    fh.write(v + "\n")
            if driver:                                                # ch341 took this one: a /dev/ttyUSB instead
                os.symlink("/nowhere", os.path.join(d, name, name + ":1.0", "driver"))
        self.assertEqual(U.ports(d, check=lambda: True),
                         [{"port": "ch340://1-4", "usb": "1a86:7523", "bus": 1, "address": 4}])
        self.assertEqual(U.ports(d, check=lambda: False), [])         # no libusb: nothing offered
        self.assertEqual(U.parse("ch340://3-12"), (3, 12))
        with self.assertRaises(ValueError):
            U.parse("ch340://x")

    def test_pyserial_opens_ch340_urls(self):
        lib = FakeLib()
        U._LIB[:] = [lib]
        U.register()
        s = serial.serial_for_url("ch340://1-4", 115200, timeout=0.3)
        self.assertTrue(s.is_open)
        lib.feed(b"ESP-ROM:esp32\r\n")
        self.assertEqual(s.read(6), b"ESP-RO")
        self.assertEqual(s.in_waiting, 9)
        s.reset_input_buffer()
        t0 = time.time()
        self.assertEqual(s.read(4), b"")                               # nothing: after its timeout
        self.assertGreater(time.time() - t0, 0.25)
        s.write(b"\xc0sync\xc0")
        self.assertEqual(lib.written, b"\xc0sync\xc0")
        s.baudrate = 460800
        self.assertEqual(lib.controls[-2][3], U.divisor(460800))
        s.dtr, s.rts = False, True                                     # esptool's ClassicReset, step one
        self.assertEqual(lib.lines()[-1], (False, True))
        lib.gone = True                                                # unplugged
        time.sleep(0.2)
        with self.assertRaises(serial.SerialException):
            s.read(1)
        s.close()
        with self.assertRaises(serial.SerialException):
            serial.serial_for_url("ch340://2-9")                       # not there

    def test_esptool_resets_it_by_its_lines(self):
        from provisioner import esptool_main
        from esptool import reset

        class Port:
            port = "ch340://1-4"

        class Loader:
            _port = Port()
        seq = esptool_main._reset_sequence(Loader(), "default_reset")
        self.assertEqual([type(r) for r in seq], [reset.ClassicReset, reset.ClassicReset])
        out = subprocess.run([sys.executable, "-m", "provisioner.esptool_main", "version"], cwd=ROOT,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                             env=dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(ROOT, "vendor"), ROOT])))
        self.assertIn("4.8.1", out.stdout)

    @unittest.skipUnless(os.path.exists("/lib/x86_64-linux-gnu/libusb-1.0.so.0") or
                         os.path.exists("/lib/aarch64-linux-gnu/libusb-1.0.so.0"), "no libusb-1.0 here")
    def test_the_real_libusb(self):
        lib = U.Libusb()                                               # every signature bound, libusb_init ran
        with self.assertRaises(U.LibusbError) as e:
            lib.find(250, 127)
        self.assertEqual(e.exception.code, -4)
        self.assertTrue(U.available())


class OverAPretendCH340(unittest.TestCase):
    """The Stump's serial link, through ch340://, to Team Stump's pretend board."""

    def test_the_stump_link(self):
        from provisioner import stump
        p = subprocess.Popen([sys.executable, os.path.join(TESTS, "stump_fixtures", "board_sim.py"),
                              "--root", tempfile.mkdtemp(), "--micropython", os.path.join(TESTS, "fake_micropython.py")],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        lib = FakeLib(board=p)

        def pump():
            while True:
                b = os.read(p.stdout.fileno(), 4096)
                if not b:
                    return
                lib.feed(b)
        threading.Thread(target=pump, daemon=True).start()
        U._LIB[:] = [lib]
        try:
            repl = stump.ready_repl(lambda: stump.SerialLink("ch340://1-4"), None, secs=20)
            info = stump.board_info(repl)
            self.assertEqual(info["release"], "1.28.0")
            self.assertEqual(lib.lines()[0], (False, False))           # held low from the start: no reset
            repl.link.close()
            self.assertEqual(lib.released, 1)
        finally:
            U._LIB[:] = []
            p.kill()
            p.wait()
            p.stdin.close()
            time.sleep(0.1)
            p.stdout.close()


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=1, exit=False).result.wasSuccessful() else 1)
