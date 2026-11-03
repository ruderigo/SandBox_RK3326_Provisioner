#!/usr/bin/env python3
"""The app's screens and buttons with no screen (SDL's dummy driver), fake
boards and the fake esptool. Screenshots go to $SHOTS (default: a temp dir).
    python3 tests/test_ui.py
"""
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ["PROVISIONER_ESPTOOL"] = os.path.join(ROOT, "tests", "fake_esptool.py")
from provisioner.ui import app as A  # noqa: E402
from provisioner.ui.gamepad import Gamepad  # noqa: E402
from provisioner.ui.sdl import Display, write_png  # noqa: E402

SHOTS = os.environ.get("SHOTS") or tempfile.mkdtemp(prefix="provisioner-shots-")
DISPLAY = None


def display():
    global DISPLAY
    if DISPLAY is None:
        DISPLAY = Display(os.path.join(ROOT, "assets", "cockpit_font.bin"), headless=True)
    return DISPLAY


def port(name, usb, chip):
    return {"port": name, "usb": usb, "usb_chip": chip, "product": "", "serial": "1", "native": False}


class Base(unittest.TestCase):
    def app(self, ports, users=None):
        self.ports = ports
        a = A.App(display(), version="0.2.0", ports_fn=lambda: [dict(p) for p in self.ports],
                  users_fn=lambda p: (users or {}).get(p, []))
        a.here_fn = None
        a.adapter_fn = None             # no S3 adapter unless a test plugs in the pretend one
        a.here = {"release": "1.0.0-beta.47", "name": "R36MAX", "chain": "chain member"}
        a.scan()
        return a

    def shot(self, a, name):
        a.draw()
        w, h, px = a.d.snapshot()
        write_png(os.path.join(SHOTS, name + ".png"), w, h, px)

    def wait(self, a):
        end = time.time() + 20
        while not a.task.done and time.time() < end:
            time.sleep(0.05)
        self.assertTrue(a.task.done)

    def setUp(self):
        for k in ("FAKE_FAIL", "FAKE_TABLE", "FAKE_APP_SLOT_KB", "FAKE_CALLS"):
            os.environ.pop(k, None)


class Screens(Base):
    def test_nothing_plugged_in(self):
        a = self.app([])
        self.shot(a, "01-empty")
        a.handle("a")
        self.assertEqual(a.screen, "boards")

    def test_identify_then_flash_wled_on_a_classic_esp32(self):
        os.environ["FAKE_BOARD"] = "esp32"
        a = self.app([port("/dev/ttyUSB0", "10c4:ea60", "CP210x USB-serial")])
        self.shot(a, "02-boards")
        a.handle("a")                                   # identify
        self.assertEqual(a.screen, "run")
        self.wait(a)
        self.shot(a, "03-identified")
        a.handle("a")
        self.assertEqual(a.screen, "jobs")
        self.shot(a, "04-jobs-esp32")
        self.assertEqual([r.get("entry", {}).get("id", r["kind"]) for r in a.jobs()],
                         ["wled-16.0.1-esp32", "micropython-1.29.0-esp32", "log", "erase"])
        a.handle("a")                                   # WLED: asks first, Yes highlighted (app only)
        self.assertEqual((a.confirm["title"], a.confirm["choice"]), ("Flash WLED 16.0.1?", 1))
        self.shot(a, "05-confirm-app")
        a.handle("a")
        self.assertEqual(a.screen, "run")
        time.sleep(0.15)
        self.shot(a, "06-flashing")
        self.wait(a)
        self.assertTrue(a.task.ok, a.task.msg)
        self.shot(a, "07-flashed")
        a.handle("a")
        self.assertEqual(a.screen, "jobs")

    def test_a_full_erase_defaults_to_no(self):
        os.environ["FAKE_BOARD"] = "esp32"
        a = self.app([port("/dev/ttyUSB0", "10c4:ea60", "CP210x USB-serial")])
        a.handle("a")
        self.wait(a)
        a.handle("a")
        a.handle("down")
        a.handle("a")                                   # MicroPython: full install
        self.assertEqual(a.confirm["choice"], 0)        # No, unless you move to Yes
        self.shot(a, "08-confirm-full")
        a.handle("a")
        self.assertIsNone(a.confirm)
        self.assertEqual(a.screen, "jobs")              # nothing ran

    def test_heltec_offers_rnode_coming_and_a_busy_port_asks_first(self):
        os.environ["FAKE_BOARD"] = "heltec"
        a = self.app([port("/dev/ttyUSB0", "10c4:ea60", "CP210x USB-serial")],
                     users={"/dev/ttyUSB0": [(812, "stump_pc.py")]})
        self.shot(a, "09-busy")
        a.handle("a")
        self.assertIn("stump_pc.py is using this board", a.confirm["title"])
        self.assertEqual(a.confirm["choice"], 0)
        self.shot(a, "10-busy-confirm")
        a.handle("b")
        self.assertEqual(a.screen, "boards")
        a.handle("a")
        a.handle("right")
        a.handle("a")                                   # use it anyway
        self.wait(a)
        a.handle("a")
        self.assertEqual(a.known["/dev/ttyUSB0"]["board"]["id"], "heltec_v3")
        self.shot(a, "11-jobs-heltec")
        a.handle("a")                                   # RNode: coming, nothing happens
        self.assertEqual(a.screen, "jobs")
        self.assertIn("Coming", a.toast_text)

    def test_s3_with_psram_lists_the_stump_jobs_then_the_adapter(self):
        os.environ["FAKE_BOARD"] = "s3"
        a = self.app([port("/dev/ttyACM0", "303a:1001", "ESP32-S3/C3 native USB")])
        a.handle("a")
        self.wait(a)
        a.handle("a")
        self.shot(a, "12-jobs-s3")
        self.assertEqual(a.known["/dev/ttyACM0"]["info"]["psram_mb"], 8)
        kinds = [r["kind"] for r in a.jobs()]
        self.assertEqual(kinds[:4], ["stump_new", "stump_update", "stump_settings", "stump_check"])
        self.assertEqual(a.jobs()[4]["entry"]["id"], "s3-usb-wifi")
        self.assertEqual(a.jobs()[4]["entry"]["status"], "ready")

    def test_a_failure_says_what_to_do(self):
        os.environ.update(FAKE_BOARD="esp32", FAKE_FAIL="connect")
        a = self.app([port("/dev/ttyUSB0", "10c4:ea60", "CP210x USB-serial")])
        a.handle("a")
        self.wait(a)
        self.assertFalse(a.task.ok)
        self.assertIn("hold BOOT", a.task.msg)
        self.shot(a, "13-failed")
        a.handle("b")
        self.assertEqual(a.screen, "boards")

    def test_unplugged_while_on_its_jobs(self):
        os.environ["FAKE_BOARD"] = "esp32"
        a = self.app([port("/dev/ttyUSB0", "10c4:ea60", "CP210x USB-serial")])
        a.handle("a")
        self.wait(a)
        a.handle("a")
        self.ports = []
        a.next_scan = 0
        a.scan()
        self.assertEqual(a.screen, "boards")
        self.assertIn("unplugged", a.toast_text)
        self.assertEqual(a.known, {})

    def test_serial_log_of_a_port_that_isnt_there(self):
        a = self.app([port("/dev/ttyNOPE0", "10c4:ea60", "CP210x USB-serial")])
        a.handle("y")
        time.sleep(0.3)
        self.assertEqual(a.screen, "log")
        self.assertIn("Can't open", a.log.error)
        self.shot(a, "14-log-error")
        a.handle("b")
        self.assertEqual(a.screen, "boards")
        self.assertIsNone(a.log)

    def test_this_handhelds_stump_from_its_own_pages(self):
        import http.server
        import json as J
        import threading as T

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = {"/node.json": {"release": "1.0.0-beta.47", "name": "R36MAX"},
                        "/chain.json": {"enabled": True, "role": "member"}}.get(self.path)
                self.send_response(200 if body else 404)
                self.end_headers()
                self.wfile.write(J.dumps(body or {}).encode())

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        T.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            import urllib.request
            real = urllib.request.OpenerDirector.open
            port = srv.server_address[1]
            urllib.request.OpenerDirector.open = lambda self, url, *a, **k: real(
                self, url.replace("127.0.0.1:80/", "127.0.0.1:%d/" % port), *a, **k)
            try:
                h = A.here_status()
            finally:
                urllib.request.OpenerDirector.open = real
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(h, {"release": "1.0.0-beta.47", "name": "R36MAX", "chain": "chain member"})

    def test_quit(self):
        a = self.app([])
        a.handle("quit")
        self.assertFalse(a.running)


class MakeAStumpOnScreen(Base):
    """The Stump's jobs through the screens and buttons, on the pretend board."""

    def setUp(self):
        super().setUp()
        import shutil
        from provisioner import stump
        from test_stump import PipeLink
        os.environ.update(FAKE_BOARD="s3", FAKE_MPY="6.3")
        self.root = tempfile.mkdtemp(prefix="board-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.links = []
        self.addCleanup(lambda: [l.close() for l in self.links])
        b = stump.find_bundle()
        keep = [n for n in sorted(b.files) if n.startswith("app/")][:3] + ["micropython.bin"]
        b.files = {n: b.files[n] for n in keep}            # three files: quick
        self.small = b
        self.PipeLink = PipeLink

    def board(self):
        a = self.app([port("/dev/ttyUSB1", "1a86:55d3", "CH343 USB-serial")])
        a._bundle = self.small
        a.open_link = lambda p: self.links.append(self.PipeLink(self.root)) or self.links[-1]
        a.handle("a")
        self.wait(a)
        a.handle("a")
        return a

    def type_in(self, a, text):
        a.handle("a")                                   # the field: the keyboard opens
        self.assertIsNotNone(a.kb)
        a.handle(("text", text))                        # a USB keyboard's typing
        a.handle("start")                               # OK

    def test_make_a_stump_with_the_gamepad(self):
        a = self.board()
        self.shot(a, "20-jobs-freenove")
        a.handle("a")                                   # Make a Stump
        self.assertEqual(a.screen, "form")
        self.shot(a, "21-form-new")
        a.handle("down")
        a.handle("down")
        a.handle("down")
        a.handle("down")
        a.handle("down")
        a.handle("down")                                # LoRa
        a.handle("down")                                # the button
        a.handle("a")
        self.assertIn("name", a.toast_text)             # no name: refused, nothing touched
        self.assertIsNone(a.confirm)
        a.form["sel"] = 0
        a.handle("a")                                   # the name, with the gamepad: Y then A types a capital
        a.kb.row, a.kb.col = 1, 3                       # "r"
        a.handle("y")
        a.handle("a")
        a.kb.row, a.kb.col = 1, 7                       # "i"
        a.handle("a")
        self.shot(a, "22-keyboard")
        a.handle(("text", "verside"))
        a.handle("start")
        self.assertEqual(a.form["a"]["name"], "Riverside")
        a.form["sel"] = 1
        self.type_in(a, "pass1234")
        a.form["sel"] = 5                               # Chain: right twice -> joins another Stump
        a.handle("right")
        a.handle("right")
        self.assertEqual(a.form["a"]["chain"], "member")
        rows = [r["key"] for r in a.form_rows()]
        self.assertEqual(rows[5:9], ["chain", "upSsid", "subnet", "secret"])
        a.form["sel"] = 8
        self.type_in(a, "s3cret")
        self.shot(a, "23-form-filled")
        a.form["sel"] = len(rows) - 1
        a.handle("a")
        self.assertEqual((a.confirm["title"], a.confirm["choice"]), ("Make a Stump on this board?", 0))
        self.shot(a, "24-confirm-make")
        a.handle("right")
        a.handle("a")
        self.assertEqual(a.screen, "run")
        self.wait(a)
        self.shot(a, "25-made")
        self.assertTrue(a.task.ok, a.task.msg)
        with open(os.path.join(self.root, "config.py")) as f:
            cfg = f.read()
        for want in ("NODE_NAME = 'Riverside'", "AUTH_ADMIN_PASSWORD = 'pass1234'", "CHAIN_ENABLED = True",
                     "CHAIN_SUBNET = 5", "CHAIN_SECRET = 's3cret'", "'192.168.5.2'"):
            self.assertIn(want, cfg)

        # Its settings, read back into the form, one changed, saved.
        a.handle("a")
        a.jsel = 2
        a.handle("a")
        self.wait(a)
        a.handle("a")
        self.assertEqual((a.screen, a.form["mode"], a.form["a"]["name"]), ("form", "settings", "Riverside"))
        self.assertEqual(a.form["a"]["pw"] if "pw" in a.form["a"] else "", "")
        self.shot(a, "26-form-settings")
        a.form["sel"] = 0
        a.handle("a")
        a.kb.text = ""
        a.handle(("text", "Riverbend"))
        a.handle("enter")
        a.form["sel"] = len(a.form_rows()) - 1
        a.handle("a")
        a.handle("a")                                   # Save: Yes highlighted
        self.wait(a)
        self.assertTrue(a.task.ok, a.task.msg)
        with open(os.path.join(self.root, "config.py")) as f:
            cfg = f.read()
        self.assertIn("NODE_NAME = 'Riverbend'", cfg)
        self.assertIn("AUTH_ADMIN_PASSWORD = 'pass1234'", cfg)      # blank: kept

        # Check it starts.
        a.handle("a")
        a.jsel = 3
        a.handle("a")
        self.wait(a)
        self.shot(a, "27-checked")
        self.assertTrue(a.task.ok, a.task.msg)

    def test_select_cancels_the_keyboard_and_letters_dont_press_buttons(self):
        a = self.board()
        a.handle("a")
        a.handle("a")
        a.handle(("text", "xy"))
        a.handle("kx")                                  # the x key's own name: no X (space) on top
        a.handle("select")
        self.assertIsNone(a.kb)
        self.assertEqual(a.form["a"]["name"], "")


class TheWifiAdapter(Base):
    """The S3 USB Wi-Fi adapter's page, against tests/fake_s3.py."""

    def setUp(self):
        super().setUp()
        from fake_s3 import FakeS3
        self.s3 = FakeS3()

    def tearDown(self):
        self.s3.stop()

    def plugged(self, ports=()):
        from provisioner import s3wifi
        a = self.app([self.s3.port_record()] + list(ports))
        a.adapter_fn = s3wifi.status
        a.internet_fn = lambda: True
        a.address_fn = lambda: "192.168.0.42"
        a._poll_adapter()
        return a

    def until(self, a, cond, secs=10):
        end = time.time() + secs
        while time.time() < end:
            a.scan()
            if cond():
                return True
            time.sleep(0.05)
        return False

    def test_it_shows_on_the_boards_screen_first(self):
        a = self.plugged([port("/dev/ttyUSB0", "10c4:ea60", "CP210x USB-serial")])
        self.assertEqual(len(a.rows()), 2)                 # its control port isn't a board
        self.assertTrue(a.rows()[0].get("adapter"))
        self.assertEqual([p["port"] for p in a.ports], ["/dev/ttyUSB0"])
        self.shot(a, "30-boards-with-the-adapter")
        a.handle("down")                                # the port's row still works as before
        a.handle("a")
        self.assertEqual(a.screen, "run")
        self.wait(a)

    def test_no_adapter_no_row(self):
        a = self.app([port("/dev/ttyACM0", "303a:1001", "ESP32-S3/C3 native USB")])   # an S3 in download mode
        self.assertIsNone(a.adapter_port)
        self.assertEqual(len(a.rows()), 1)

    def test_pick_a_network_type_its_password_and_join(self):
        a = self.plugged()
        a.handle("a")
        self.assertEqual(a.screen, "wifi")
        self.assertTrue(self.until(a, lambda: len(a.wifi_rows()) == 3))
        self.assertEqual([r["ssid"] for r in a.wifi_rows()], ["HomeNet", "Stump-Oak", "Cafe"])
        self.shot(a, "31-wifi-networks")
        a.handle("a")                                   # HomeNet needs a password: the keyboard
        self.assertIsNotNone(a.kb)
        a.handle(("text", "hunter22pw"))
        self.shot(a, "32-wifi-password")
        a.handle("start")
        self.assertIsNone(a.kb)
        self.assertTrue(self.until(a, lambda: a.wifi["status"].get("ssid") == "HomeNet"))
        self.assertIn({"ssid": "HomeNet", "password": "hunter22pw"}, self.joins())
        self.assertIn("Connected to HomeNet", a.toast_text)
        self.assertTrue(self.until(a, lambda: a.wifi_rows()[0]["saved"]))
        self.assertTrue(self.until(a, lambda: a.wifi["internet"] == "yes"))
        self.assertEqual(a.wifi["address"], "192.168.0.42")
        self.shot(a, "33-wifi-connected")
        # a saved network joins again with no password asked
        a.handle("a")
        self.assertIsNone(a.kb)
        self.assertTrue(self.until(a, lambda: {"ssid": "HomeNet"} in self.joins()))

    def test_an_open_network_joins_straight_away(self):
        a = self.plugged()
        a.handle("a")
        self.assertTrue(self.until(a, lambda: len(a.wifi_rows()) == 3))
        a.handle("down")
        a.handle("a")
        self.assertIsNone(a.kb)
        self.assertTrue(self.until(a, lambda: a.wifi["status"].get("ssid") == "Stump-Oak"))
        self.assertIn({"ssid": "Stump-Oak", "password": ""}, self.joins())

    def test_a_wrong_password_says_so_and_asks_again(self):
        a = self.plugged()
        a.handle("a")
        self.assertTrue(self.until(a, lambda: len(a.wifi_rows()) == 3))
        a.handle("a")
        a.handle(("text", "wrongpass1"))
        a.handle("start")
        self.assertTrue(self.until(a, lambda: "wrong password" in a.toast_text))
        self.assertIsNone(a.wifi["joining"])
        self.shot(a, "34-wifi-wrong-password")
        a.handle("a")                                   # saved, but its password failed: typed again
        self.assertIsNotNone(a.kb)
        a.handle("select")
        self.assertIsNone(a.kb)

    def test_a_short_password_isnt_sent(self):
        a = self.plugged()
        a.handle("a")
        self.assertTrue(self.until(a, lambda: len(a.wifi_rows()) == 3))
        a.handle("a")
        a.handle(("text", "short"))
        a.handle("start")
        self.assertIn("8 to 63", a.toast_text)
        self.assertFalse(self.joins())

    def test_forget_asks_first(self):
        self.s3.saved = {"Cafe": "cafepass99", "Gone": "gonepass99"}
        a = self.plugged()
        a.handle("a")
        self.assertTrue(self.until(a, lambda: len(a.wifi_rows()) == 4))
        self.assertEqual(a.wifi_rows()[3], {"ssid": "Gone", "rssi": None, "open": False, "saved": True, "here": False})
        self.shot(a, "35-wifi-saved-out-of-range")
        a.handle("y")                                   # HomeNet isn't saved
        self.assertIsNone(a.confirm)
        for _ in range(3):
            a.handle("down")
        a.handle("y")
        self.assertIn("Forget Gone?", a.confirm["title"])
        self.assertEqual(a.confirm["choice"], 1)
        a.handle("a")
        self.assertTrue(self.until(a, lambda: len(a.wifi_rows()) == 3))
        self.assertIn({"cmd": "forget", "ssid": "Gone"}, [{k: v for k, v in c.items() if k != "id"} for c in self.s3.calls])

    def test_unplugged_while_on_its_page(self):
        a = self.plugged()
        a.handle("a")
        self.ports = []                                 # its port is gone
        a.next_scan = 0
        self.assertTrue(self.until(a, lambda: a.screen == "boards"))
        self.assertIn("unplugged", a.toast_text)
        self.assertIsNone(a.adapter)

    def joins(self):
        return [{k: v for k, v in c.items() if k not in ("id", "cmd")} for c in self.s3.calls if c["cmd"] == "join"]


class Buttons(unittest.TestCase):
    def test_r36max_codes(self):
        g = Gamepad([])
        self.assertEqual(g.decode(1, 305, 1), ["a"])
        self.assertEqual(g.decode(1, 304, 1), ["b"])
        self.assertEqual(g.decode(1, 305, 0), [])                 # release
        self.assertEqual(g.decode(1, 545, 2), ["down"])           # D-pad repeat
        self.assertEqual(g.decode(1, 305, 2), [])                 # no A repeat
        self.assertEqual(g.decode(3, 16, -1), ["left"])
        self.assertEqual(g.decode(3, 17, 1), ["down"])
        self.assertEqual(g.decode(1, 30, 1), [])                  # a keyboard key: SDL's, not here
        self.assertEqual(g.decode(1, 314, 1), ["select"])
        self.assertEqual(g.decode(1, 315, 1), ["quit"])           # SELECT+START


if __name__ == "__main__":
    try:
        unittest.main(verbosity=1, exit=False)
    finally:
        print("screenshots:", SHOTS)
