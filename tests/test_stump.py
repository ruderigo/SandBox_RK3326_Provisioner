#!/usr/bin/env python3
"""Making a Stump, on Team Stump's pretend board (stump_fixtures/board_sim.py:
MicroPython's raw REPL, raw-paste and soft reset), with the real bundle from
firmware/stump/ (SandBox_Stump_On's release): make, update, settings,
check, and what's refused.
    python3 tests/test_stump.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from provisioner import stump  # noqa: E402

TESTS = os.path.join(ROOT, "tests")
BUNDLE = stump.find_bundle()


class PipeLink:
    """The pretend board as a serial line."""

    def __init__(self, root, *flags):
        self.p = subprocess.Popen([sys.executable, os.path.join(TESTS, "stump_fixtures", "board_sim.py"), "--root", root,
                                   "--micropython", os.path.join(TESTS, "fake_micropython.py")] + list(flags),
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self.on_bytes, self.dead = None, None
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            b = self.p.stdout.read1(4096) if hasattr(self.p.stdout, "read1") else os.read(self.p.stdout.fileno(), 4096)
            if not b:
                self.dead = "closed"
                if self.on_bytes:
                    self.on_bytes(b"")
                return
            if self.on_bytes:
                self.on_bytes(b)

    def write(self, b):
        self.p.stdin.write(b)
        self.p.stdin.flush()

    def close(self):
        try:
            self.p.stdin.close()
        except OSError:
            pass
        self.p.kill()
        self.p.wait()
        self.p.stdout.close()


def answers(**kw):
    a = {"name": "TestStump", "pw": "hunter22", "pw2": "hunter22", "ssid": "", "wpass": "", "radio": "ap",
         "chain": "none", "features": ["chat", "billboard", "files"]}
    a.update(kw)
    return a


def read(root, name):
    with open(os.path.join(root, name), encoding="utf-8") as f:
        return f.read()


@unittest.skipIf(BUNDLE is None, "no Stump bundle in firmware/stump/")
class MakeAStump(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="board-")
        self.links, self.steps, self.log, self.flags = [], [], [], []
        self.flashed = []
        os.environ["FAKE_MPY"] = "6.3"

    def tearDown(self):
        for link in self.links:
            link.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def open_link(self):
        link = PipeLink(self.root, *self.flags)
        self.links.append(link)
        return link

    def flash(self, path):
        with open(path, "rb") as f:
            self.flashed.append(hashlib.sha256(f.read()).hexdigest())
        return True, "written and verified"

    def make(self, a=None, update=False):
        return stump.make(BUNDLE, a or answers(), self.open_link, self.flash, self.steps.append,
                          lambda p: None, self.log.append, update=update)

    def board_files(self):
        out = {}
        for d, _, fs in os.walk(self.root):
            for f in fs:
                p = os.path.relpath(os.path.join(d, f), self.root)
                with open(os.path.join(d, f), "rb") as fh:
                    out[p] = hashlib.sha256(fh.read()).hexdigest()
        return out

    def test_a_new_stump_from_the_real_bundle(self):
        ok, msg = self.make()
        self.assertTrue(ok, msg)
        self.assertEqual(self.flashed, [BUNDLE.files["micropython.bin"][1]])     # MicroPython, the pinned one
        on_board = self.board_files()
        for path, data, sha in BUNDLE.app():
            self.assertEqual(on_board.get(path), sha, path)                       # every file, as released
        self.assertFalse([p for p in on_board if p.endswith(".part")])
        cfg = read(self.root, "config.py")
        compile(cfg, "config.py", "exec")
        self.assertIn("NODE_NAME = 'TestStump'", cfg)
        self.assertIn("AUTH_ADMIN_PASSWORD = 'hunter22'", cfg)
        self.assertRegex(cfg, r'"name": "Heltec Bridge",\s*"enabled": True,')
        self.assertIn('"target_host": \'192.168.4.2\'', cfg)
        for s in ("Bob's Glitch", "SalutComment", "TeK_Knoh", "'TeK'"):
            self.assertNotIn(s, cfg)
        self.assertIn('"frequency": 868800000', read(self.root, "radio.json"))
        self.assertIn(BUNDLE.default_ssid, msg)
        self.assertEqual(self.steps[0][:7], "Erasing")

        # Update: the release copied again, its settings and identity kept.
        cfg_before = read(self.root, "config.py")
        with open(os.path.join(self.root, "identity.key"), "w") as f:
            f.write("its identity")
        self.flashed, self.steps = [], []
        ok, msg = self.make(update=True)
        self.assertTrue(ok, msg)
        self.assertEqual(self.flashed, [])                                         # nothing erased
        self.assertEqual(read(self.root, "config.py"), cfg_before)
        self.assertEqual(read(self.root, "identity.key"), "its identity")

        # Settings: read, change, saved by the Stump's own settings.py.
        c = stump.read_job(self.open_link, self.log.append)
        self.assertEqual((c["NODE_NAME"], c["HAS_ADMIN_PASSWORD"], c["HELTEC"]["enabled"]), ("TestStump", True, True))
        a = stump.answers_from(c)
        a.update(name="Renamed", ssid="HomeNet", wpass="longenough", radio="none")
        ok, msg = stump.save_job(a, self.open_link, self.steps.append, self.log.append)
        self.assertTrue(ok, msg)
        cfg = read(self.root, "config.py")
        self.assertIn("NODE_NAME = 'Renamed'", cfg)
        self.assertIn("WIFI_SSID = 'HomeNet'", cfg)
        self.assertIn("AUTH_ADMIN_PASSWORD = 'hunter22'", cfg)                    # blank password: kept
        self.assertRegex(cfg, r'"name": "Heltec Bridge",\s*"enabled": False,')
        self.assertEqual(read(self.root, "config.py.bak"), cfg_before)

        # Check: restarted, it says it's serving.
        ok, msg = stump.check_job(self.open_link, self.steps.append, self.log.append, secs=10)
        self.assertTrue(ok, msg)
        self.assertIn("serving", msg)


@unittest.skipIf(BUNDLE is None, "no Stump bundle in firmware/stump/")
class Refused(MakeAStump):
    test_a_new_stump_from_the_real_bundle = None

    def small(self):
        """The bundle with three of its files (fast)."""
        b = stump.find_bundle()
        keep = [n for n in sorted(b.files) if n.startswith("app/")][:3] + ["micropython.bin"]
        b.files = {n: b.files[n] for n in keep}
        return b

    def test_an_update_needs_a_stump_on_the_board(self):
        global BUNDLE
        b, BUNDLE = BUNDLE, self.small()
        try:
            ok, msg = self.make(update=True)
        finally:
            BUNDLE = b
        self.assertFalse(ok)
        self.assertIn("no config.py", msg)

    def test_an_update_needs_the_same_micropython(self):
        os.environ["FAKE_MPY"] = "6.2"
        with open(os.path.join(self.root, "config.py"), "w") as f:
            f.write("NODE_NAME = 'x'\n")
        ok, msg = self.make(update=True)
        self.assertFalse(ok)
        self.assertIn("Make a Stump", msg)
        self.assertEqual(self.board_files(), {"config.py": hashlib.sha256(b"NODE_NAME = 'x'\n").hexdigest()})

    def test_bad_answers_never_touch_the_board(self):
        for a, want in ((answers(name=""), "name"), (answers(pw2="other"), "aren't the same"),
                        (answers(pw="", pw2=""), "admin password"), (answers(ssid="X", wpass="short"), "8 to 63"),
                        (answers(radio="lan", hhost="192.168.1.50"), "home Wi-Fi's name"),
                        (answers(chain="member", upSsid="Up", subnet="3"), "5 to 254")):
            ok, msg = self.make(a)
            self.assertFalse(ok)
            self.assertIn(want, msg)
        self.assertEqual(self.flashed, [])
        self.assertEqual(self.links, [])

    def test_a_running_stump_is_stopped_first_and_plain_raw_mode_works(self):
        global BUNDLE
        self.flags = ["--running", "--no-paste"]
        b, BUNDLE = BUNDLE, self.small()
        try:
            ok, msg = self.make()
        finally:
            BUNDLE = b
        self.assertTrue(ok, msg)
        self.assertIn("NODE_NAME = 'TestStump'", read(self.root, "config.py"))


class Rules(unittest.TestCase):
    def test_settings_rules(self):
        v = stump.settings_from(answers(chain="member", upSsid="LaBuche3-Stump", subnet="7", secret="s3cret",
                                        radio="ap"))["values"]
        self.assertEqual((v["CHAIN_ENABLED"], v["CHAIN_SUBNET"], v["CHAIN_CHANNEL"]), (True, 7, 0))
        self.assertEqual(v["HELTEC"], {"enabled": True, "host": "192.168.7.2", "port": 7633})
        r = stump.settings_from(answers(chain="first", secret=""))
        self.assertEqual(r["values"]["CHAIN_CHANNEL"], 11)
        self.assertTrue(any("chain secret" in w for w in r["warn"]))
        self.assertIn("error", stump.settings_from(answers(chain="first", secret="it's")))
        self.assertNotIn("WIFI_PASS", stump.settings_from(answers(keepWifiPass=True))["values"])

    def test_answers_from_what_the_board_says(self):
        a = stump.answers_from({"NODE_NAME": "N", "CHAIN_ENABLED": True, "CHAIN_UPLINK_SSID": "Up", "CHAIN_SUBNET": 9,
                                "HELTEC": {"enabled": True, "host": "192.168.9.2"}, "HAS_ADMIN_PASSWORD": True})
        self.assertEqual((a["chain"], a["subnet"], a["radio"], a["hasPw"]), ("member", 9, "ap", True))

    def test_boot_summary(self):
        b = stump.boot_summary("MicroPython v1.28.0 on x\r\nProject Stump -- Beta A (1.0.0-beta.47)\r\n"
                               "[web] serving on 192.168.4.1:80\r\nTraceback (most recent call last):\r\n")
        self.assertEqual((b["release"], b["micropython"], b["serving"]), ("1.0.0-beta.47", "v1.28.0", True))
        self.assertTrue(b["problems"])

    def test_the_bundle_is_team_stumps_release(self):
        self.assertIsNotNone(BUNDLE)
        self.assertEqual(BUNDLE.head["micropython_sha256"],
                         "67c19ae123d84152019b57526ed5291dd0a2b4edd87655c5f76b46c9a62ff5dd")
        self.assertGreater(len(BUNDLE.app()), 50)
        for s in ("Bob's Glitch", "SalutComment", "TeK_Knoh", "'TeK'"):
            self.assertNotIn(s, BUNDLE.template)


if __name__ == "__main__":
    unittest.main(verbosity=1)
