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
os.environ.setdefault("PROVISIONER_LISTEN_S", "6")    # a setup listens 90 s at most; here less
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

    def flash(self, path, offset="0x0", erase=True):
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
        img = BUNDLE.image_for("esp32s3")[0]
        if img:                                                                    # its Stump image (beta.57 on)
            with open(img, "rb") as f:
                self.assertEqual(self.flashed, [hashlib.sha256(f.read()).hexdigest()])
        else:                                                                      # MicroPython, the pinned one
            self.assertEqual(self.flashed, [BUNDLE.files["micropython.bin"][1]])
        on_board = self.board_files()
        for path, data, sha in BUNDLE.app():
            self.assertEqual(on_board.get(path), sha, path)                       # every file, as released
        self.assertFalse([p for p in on_board if p.endswith(".part")])
        cfg = read(self.root, "config.py")
        compile(cfg, "config.py", "exec")
        self.assertIn("NODE_NAME = 'TestStump'", cfg)
        self.assertIn("AUTH_ADMIN_PASSWORD = 'hunter22'", cfg)
        self.assertRegex(cfg, r'"name": "Heltec Bridge",\s*"enabled": True,')
        self.assertIn('"target_host": \'192.168.4.200\'', cfg)                # its Heltec at .200 (beta.58)
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
        # Another board (or its config.py changed since it was read): nothing saved.
        with open(os.path.join(self.root, "config.py"), "a") as f:
            f.write("# another board\n")
        ok, msg = stump.save_job(a, self.open_link, self.steps.append, self.log.append)
        self.assertFalse(ok)
        self.assertIn("isn't the one read earlier", msg)
        self.assertIn("NODE_NAME = 'Renamed'", read(self.root, "config.py"))

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
                        (answers(chain="member", upSsid="Up", subnet="1"), "2 to 254")):
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


@unittest.skipIf(BUNDLE is None, "no Stump bundle in firmware/stump/")
class StumpImages(unittest.TestCase):
    """The release's Stump images (beta.57 on), as Arborist writes them: the
    S3-CAM's at 0x0, the WROVER's at 0x1000, then only the files the image
    hasn't built in; updated in place when the layout matches."""
    FROZEN = ["admin_web.py", "announcer.py"]

    def setUp(self):
        self.root, self.frozen, self.rel = (tempfile.mkdtemp(prefix=p) for p in ("board-", "frozen-", "rel-"))
        self.links, self.steps, self.log, self.flags, self.flashed = [], [], [], [], []
        self.env = dict(os.environ)
        os.environ.update(FAKE_MPY="6.3", FAKE_FROZEN=self.frozen)
        r = BUNDLE.release
        shutil.copy(BUNDLE.path, os.path.join(self.rel, "Stump-%s.bundle" % r))
        self.head = "RELEASE = %r\nPARTITIONS = 'stump-9eba0468'\nFROZEN = %r\n" % (r, self.FROZEN)
        for kind in ("s3cam", "wrover"):
            with open(os.path.join(self.rel, "stump-%s-%s.bin" % (r, kind)), "wb") as f:
                f.write(b"\xe9" + kind.encode() * 100)

    def tearDown(self):
        for link in self.links:
            link.close()
        os.environ.clear()
        os.environ.update(self.env)
        for d in (self.root, self.frozen, self.rel):
            shutil.rmtree(d, ignore_errors=True)

    def bundle(self, images=True):
        head = os.path.join(self.rel, "stump_image.py")
        if images:
            with open(head, "w") as f:
                f.write(self.head)
        elif os.path.exists(head):
            os.remove(head)
        b = stump.find_bundle(self.rel)
        keep = ["app/admin_web.mpy", "app/announcer.mpy", "app/main.py", "app/barkeep.mpy", "micropython.bin"]
        b.files = {n: b.files[n] for n in keep if n in b.files}
        return b

    def open_link(self):
        link = PipeLink(self.root, *self.flags)
        self.links.append(link)
        return link

    def flash(self, path, offset, erase):
        """An image's stump_image.py and the modules it builds in; an erase empties the filesystem."""
        self.flashed.append((os.path.basename(path), offset, erase))
        if erase:
            shutil.rmtree(self.root)
            os.makedirs(self.root)
        shutil.rmtree(self.frozen)
        os.makedirs(self.frozen)
        if os.path.basename(path).startswith("stump-"):
            with open(os.path.join(self.frozen, "stump_image.py"), "w") as f:
                f.write(self.head)
        return True, "written and verified"

    def make(self, b, a=None, update=False, chip="esp32s3"):
        return stump.make(b, a or answers(), self.open_link, self.flash, self.steps.append, lambda p: None,
                          self.log.append, update=update, chip=chip)

    def on_board(self):
        return sorted(os.path.relpath(os.path.join(d, f), self.root) for d, _, fs in os.walk(self.root) for f in fs)

    def test_a_new_cam_and_its_update_in_place(self):
        b = self.bundle()
        ok, msg = self.make(b)
        self.assertTrue(ok, msg)
        self.assertEqual(self.flashed, [("stump-%s-s3cam.bin" % b.release, "0x0", True)])
        files = self.on_board()
        self.assertNotIn("admin_web.mpy", files)                       # built in: not copied
        self.assertIn("barkeep.mpy", files)
        self.assertIn("main.py", files)
        self.assertIn("config.py", files)
        self.assertTrue(any("modules built in" in line for line in self.log))
        # Update: an older image with this layout, a stale copy of a built-in module.
        with open(os.path.join(self.frozen, "stump_image.py"), "w") as f:
            f.write(self.head.replace(repr(b.release), "'1.0.0-beta.57'"))
        with open(os.path.join(self.root, "announcer.py"), "w") as f:
            f.write("stale = True\n")
        open(os.path.join(self.root, "identity.key"), "w").close()
        self.flashed = []
        ok, msg = self.make(b, update=True)
        self.assertTrue(ok, msg)
        self.assertEqual(self.flashed, [("stump-%s-s3cam.bin" % b.release, "0x0", False)])     # in place
        files = self.on_board()
        self.assertNotIn("announcer.py", files)                        # the stale copy removed
        self.assertIn("identity.key", files)
        self.assertIn("config.py", files)
        # The same image already: nothing written
        self.flashed = []
        ok, msg = self.make(b, update=True)
        self.assertTrue(ok, msg)
        self.assertEqual(self.flashed, [])

    def test_an_older_layout_is_refused(self):
        b = self.bundle()
        with open(os.path.join(self.root, "config.py"), "w") as f:
            f.write("NODE_NAME = 'x'\n")
        with open(os.path.join(self.frozen, "stump_image.py"), "w") as f:
            f.write(self.head.replace("stump-9eba0468", "stump-0ld"))
        ok, msg = self.make(b, update=True)
        self.assertFalse(ok)
        self.assertIn("older layout", msg)
        self.assertEqual(self.flashed, [])

    def test_plain_micropython_is_updated_file_by_file(self):
        b = self.bundle()
        with open(os.path.join(self.root, "config.py"), "w") as f:
            f.write("NODE_NAME = 'x'\n")
        ok, msg = self.make(b, update=True)
        self.assertTrue(ok, msg)
        self.assertEqual(self.flashed, [])
        self.assertIn("admin_web.mpy", self.on_board())
        self.assertIn("made again it gets the Stump image", msg)

    def test_an_update_on_a_full_board(self):
        """As Arborist from 1.0.0-beta.65 (a WROVER with packs): the same files
        aren't written again, the room is worked out first, a full board said."""
        files = [("app/x.mpy", b"x" * 30000), ("app/y.mpy", b"y" * 20000)]
        files = [(p, d, hashlib.sha256(d).hexdigest()) for p, d in files]

        def up(**env):
            os.environ.update(env)
            link = self.open_link()
            try:
                repl = stump.ready_repl(lambda: link, None, secs=20)
                return stump.upload(repl, files)
            finally:
                link.close()
                for k in env:
                    os.environ.pop(k, None)
        self.assertEqual(up(), {"written": 2, "skipped": 0})
        self.assertEqual(up(), {"written": 0, "skipped": 2})          # the same: nothing written
        files[1] = ("app/y.mpy", b"Y" * 20000, hashlib.sha256(b"Y" * 20000).hexdigest())
        with open(os.path.join(self.root, "app", "z.py.part"), "w") as f:
            f.write("a write cut short")
        with self.assertRaises(stump.StumpError) as e:
            up(FAKE_FREE="20000")                                     # needs 20 KB + 16 KB: short
        self.assertIn("storage is full", str(e.exception))
        self.assertIn("Nothing was written", str(e.exception))
        self.assertIn("(after removing 1 leftovers)", str(e.exception))
        self.assertIn("app/", str(e.exception))                       # what takes the room
        with open(os.path.join(self.root, "app", "y.mpy"), "rb") as f:
            self.assertEqual(f.read(), b"y" * 20000)                  # untouched
        with self.assertRaises(stump.StumpError) as e:
            up(FAKE_FULL="app/y.mpy")                                 # fills up while writing it
        self.assertIn("filled up while writing app/y.mpy", str(e.exception))
        with open(os.path.join(self.root, "app", "y.mpy"), "rb") as f:
            self.assertEqual(f.read(), b"y" * 20000)                  # the old one kept
        self.assertEqual(up(), {"written": 1, "skipped": 1})          # room again: only the changed one

    def test_a_board_on_an_image_and_a_release_without_one(self):
        """The release chosen has no image (an older one): its files would hide the
        built-in modules, so a newer image on the board is refused, and the
        .mpy is checked as on plain MicroPython."""
        b = self.bundle(images=False)
        with open(os.path.join(self.root, "config.py"), "w") as f:
            f.write("NODE_NAME = 'x'\n")
        with open(os.path.join(self.frozen, "stump_image.py"), "w") as f:
            f.write(self.head.replace(repr(b.release), "'9.9.9'"))
        ok, msg = self.make(b, update=True)
        self.assertFalse(ok)
        self.assertIn("can't go back", msg)
        with open(os.path.join(self.frozen, "stump_image.py"), "w") as f:
            f.write(self.head.replace(repr(b.release), "'1.0.0-beta.1'"))
        os.environ["FAKE_MPY"] = "6.2"
        ok, msg = self.make(b, update=True)
        self.assertFalse(ok)
        self.assertIn("Make a Stump", msg)
        self.assertEqual(self.on_board(), ["config.py"])

    def test_another_releases_stump_image_py_is_not_used(self):
        with open(os.path.join(self.rel, "stump_image.py"), "w") as f:
            f.write(self.head.replace(repr(BUNDLE.release), "'1.0.0-beta.1'"))
        b = stump.find_bundle(self.rel)
        self.assertEqual((b.image_head, b.images), (None, {}))

    def test_a_wrover(self):
        os.environ["FAKE_MACHINE"] = "Generic ESP32 module with SPIRAM with ESP32"
        b = self.bundle()
        ok, msg = self.make(b, chip="esp32")
        self.assertTrue(ok, msg)
        self.assertEqual(self.flashed, [("stump-%s-wrover.bin" % b.release, "0x1000", True)])

    def test_a_wrover_needs_an_image_and_a_wroom_is_refused(self):
        ok, msg = self.make(self.bundle(images=False), chip="esp32")
        self.assertFalse(ok)
        self.assertIn("no image", msg)
        self.assertEqual((self.flashed, self.links), ([], []))
        os.environ.update(FAKE_MACHINE="Generic ESP32 module with ESP32", FAKE_MEM=str(110 * 1024))
        ok, msg = self.make(self.bundle(images=True), chip="esp32")
        self.assertFalse(ok)
        self.assertIn("no PSRAM", msg)
        self.assertNotIn("config.py", self.on_board())


class Rules(unittest.TestCase):
    def test_settings_rules(self):
        v = stump.settings_from(answers(chain="member", upSsid="LaBuche3-Stump", subnet="7", secret="s3cret",
                                        radio="ap"))["values"]
        self.assertEqual((v["CHAIN_ENABLED"], v["CHAIN_SUBNET"], v["CHAIN_CHANNEL"]), (True, 7, 0))
        self.assertEqual(v["HELTEC"], {"enabled": True, "host": "192.168.7.200", "port": 7633})
        r = stump.settings_from(answers(chain="first", secret=""))
        self.assertEqual(r["values"]["CHAIN_CHANNEL"], 11)
        self.assertTrue(any("chain secret" in w for w in r["warn"]))
        self.assertIn("error", stump.settings_from(answers(chain="first", secret="it's")))
        self.assertNotIn("WIFI_PASS", stump.settings_from(answers(keepWifiPass=True))["values"])
        for bad in ("007", "²5", " 5x"):                                    # as Arborist: digits, no leading 0
            self.assertIn("2 to 254", stump.settings_from(answers(chain="member", upSsid="U", subnet=bad))["error"])
        self.assertIn("1 to 13", stump.settings_from(answers(chain="first", channel="0x"))["error"])

    def test_answers_from_what_the_board_says(self):
        a = stump.answers_from({"NODE_NAME": "N", "CHAIN_ENABLED": True, "CHAIN_UPLINK_SSID": "Up", "CHAIN_SUBNET": 9,
                                "HELTEC": {"enabled": True, "host": "192.168.9.2"}, "HAS_ADMIN_PASSWORD": True})
        self.assertEqual((a["chain"], a["subnet"], a["radio"], a["hasPw"]), ("member", 9, "ap", True))

    def test_boot_summary(self):
        b = stump.boot_summary("MicroPython v1.28.0 on x\r\nProject Stump -- Beta A (1.0.0-beta.47)\r\n"
                               "[web] serving on 192.168.4.1:80\r\nTraceback (most recent call last):\r\n")
        self.assertEqual((b["release"], b["micropython"], b["serving"]), ("1.0.0-beta.47", "v1.28.0", True))
        self.assertTrue(b["problems"])

    def test_passwords_as_beta58(self):
        v = stump.settings_from(answers())["values"]                          # the bot takes the same one
        self.assertEqual((v["AUTH_ADMIN_PASSWORD"], v["FSERVBOT_OP_PASSWORD"]), ("hunter22", "hunter22"))
        v = stump.settings_from(answers(botpw="own", opw="bot-pass"))["values"]
        self.assertEqual((v["AUTH_ADMIN_PASSWORD"], v["FSERVBOT_OP_PASSWORD"]), ("hunter22", "bot-pass"))
        v = stump.settings_from(answers(botpw="own", opw=""))["values"]       # its own, blank: editing off
        self.assertNotIn("FSERVBOT_OP_PASSWORD", v)
        r = stump.settings_from(answers(pw="", pw2="", opw="bot-pass", requireAdmin=True))
        self.assertIn("admin password", r["error"])                          # the bot's alone no longer does
        self.assertIn("4 to 64", stump.settings_from(answers(botpw="own", opw="abc"))["error"])
        v = stump.settings_from(answers(pw="", pw2="", hasPw=True, botpw="own"))["values"]   # settings: both kept
        self.assertNotIn("AUTH_ADMIN_PASSWORD", v)
        self.assertNotIn("FSERVBOT_OP_PASSWORD", v)

    def test_a_chain_over_the_router_and_the_heltecs_addresses(self):
        a = answers(chain="lan", ssid="Home Net", wpass="longenough", parentIp="192.168.0.173", subnet="8",
                    secret="s3cret", radio="lan", hhost="192.168.0.222")
        v = stump.settings_from(a)["values"]
        self.assertEqual((v["CHAIN_PARENT_IP"], v["CHAIN_UPLINK_SSID"], v["CHAIN_UPLINK_PASS"], v["CHAIN_SUBNET"]),
                         ("192.168.0.173", "Home Net", "longenough", 8))
        self.assertEqual(v["HELTEC"]["host"], "192.168.0.222")
        kept = stump.settings_from(dict(a, wpass="", keepWifiPass=True))["values"]
        self.assertEqual(kept["CHAIN_UPLINK_PASS"], stump.FROM_WIFI_PASS)    # copied from WIFI_PASS on the board
        self.assertIn("home Wi-Fi's name", stump.settings_from(dict(a, ssid="", wpass="", radio="none"))["error"])
        for k, bad, want in (("secret", "", "chain secret"),
                             ("parentIp", "192.168.0", "192.168.0.173"), ("subnet", "1", "2 to 254"),
                             ("lanOk", False, "older than 1.0.0-beta.57"), ("hhost", "192.168.0.1", "2 to 254")):
            self.assertIn(want, stump.settings_from(dict(a, **{k: bad}))["error"], k)
        self.assertEqual(stump.settings_from(answers(chain="first", secret="x"))["values"]["CHAIN_PARENT_IP"], "")
        c = {"NODE_NAME": "N", "CHAIN_ENABLED": True, "CHAIN_PARENT_IP": "192.168.0.173", "CHAIN_UPLINK_SSID": "Home Net",
             "CHAIN_SUBNET": 8, "HELTEC": {"enabled": True, "host": "192.168.8.200"}, "HAS_OP_PASSWORD": True}
        a = stump.answers_from(c)
        self.assertEqual((a["chain"], a["parentIp"], a["subnet"], a["radio"], a["botpw"]),
                         ("lan", "192.168.0.173", 8, "ap", "own"))

    def test_its_number_language_and_name_as_beta64_67(self):
        """Every Stump has a number (its Wi-Fi at 192.168.<number>.1), a language,
        and its address shown in its Wi-Fi's name if wanted (32 characters at most)."""
        v = stump.settings_from(answers(chain="none", subnet="7", radio="ap"))["values"]
        self.assertEqual((v["CHAIN_SUBNET"], v["HELTEC"]["host"], v["DEFAULT_LANG"]), (7, "192.168.7.200", "fr"))
        self.assertEqual(stump.settings_from(answers(chain="none", subnet=""))["values"]["CHAIN_SUBNET"], 4)
        self.assertEqual(stump.settings_from(answers(chain="first", secret="x", subnet="9"))["values"]["CHAIN_SUBNET"], 9)
        self.assertIn("older than 1.0.0-beta.64",
                      stump.settings_from(answers(chain="none", subnet="7", numberOk=False))["error"])
        self.assertNotIn("error", stump.settings_from(answers(chain="member", upSsid="U", subnet="7", numberOk=False)))
        w = stump.settings_from(answers(chain="member", upSsid="U", subnet="4"))["warn"]
        self.assertTrue(any("number of its own" in x for x in w), w)
        self.assertEqual(stump.settings_from(answers(lang="en"))["values"]["DEFAULT_LANG"], "en")
        self.assertIn("Unknown language", stump.settings_from(answers(lang="de"))["error"])
        v = stump.settings_from(answers(hotspot="Cafe", hotspotIp=True, subnet="12"))["values"]
        self.assertEqual((v["SSID_NAME"], v["SSID_INCLUDE_IP"]), ("Cafe", True))
        err = stump.settings_from(answers(hotspot="Le Café du Coin de la Place", hotspotIp=True, subnet="12"))["error"]
        self.assertIn("too long (32 at most)", err)
        a = stump.answers_from({"NODE_NAME": "N", "CHAIN_SUBNET": 7, "DEFAULT_LANG": "es", "SSID_INCLUDE_IP": True,
                                "HELTEC": {"enabled": True, "host": "192.168.7.200"}})
        self.assertEqual((a["subnet"], a["lang"], a["hotspotIp"], a["radio"], a["chain"]), (7, "es", True, "ap", "none"))
        rows, _ = stump.start_report(stump.boot_summary("[web] serving\n"), dict(v, CHAIN_ENABLED=False), "Stump")
        self.assertIn("http://192.168.12.1/", dict((k, t) for k, t, _ in rows)["Its own Wi-Fi"])

    def test_the_boot_report(self):
        v = stump.settings_from(answers(chain="lan", ssid="Home Net", wpass="longenough", parentIp="192.168.0.173",
                                        subnet="8", secret="s3cret", radio="lan", hhost="192.168.0.223"))["values"]
        enough = stump.enough_for(v)
        ok = stump.boot_summary("[mem] at boot: heap 4077 KB, 93 KB in use\nConnected! IP: 192.168.0.181 (esp32)\n"
                                "[1][NOTE] Chain: linked to the Stump above at 192.168.0.173\n"
                                "[2][NOTE] WiFi Serial connected to 192.168.0.223:7633\n[web] serving on port 80\n")
        self.assertEqual((ok["home"], ok["chain"]["linked"], ok["heltec"]["ok"], ok["heap_kb"]),
                         ("192.168.0.181", "192.168.0.173", "192.168.0.223", 4077))
        self.assertTrue(enough(ok))
        rows, notes = stump.start_report(ok, v, "Stump")
        self.assertEqual([lvl for _, _, lvl in rows], ["ok", "", "ok", "ok", "ok"])
        bad = stump.boot_summary("WiFi unavailable (WiFi connection timed out: the password is wrong)\n"
                                 "[3][WARN] Chain: no answer from the Stump above at 192.168.0.170 yet: is that its address\n"
                                 "[4][ERR] WiFi Serial initial connect failed: [Errno 113] EHOSTUNREACH\n[web] serving\n")
        self.assertEqual((bad["home"], bad["home_why"], bad["chain"]["no_answer"], bad["heltec"]["fail"]),
                         (None, "the password is wrong", "192.168.0.170", "[Errno 113] EHOSTUNREACH"))
        self.assertFalse(enough(bad))                                        # its Heltec not reached yet: listens on
        rows, notes = stump.start_report(bad, v, "Stump")
        self.assertIn("the password is wrong", dict((k, t) for k, t, _ in rows)["Home Wi-Fi"])
        self.assertTrue(any("longer" in n for n in notes))
        root = stump.boot_summary("[chain] root on 192.168.4.1, channel 11 and on 192.168.0.173 (the Wi-Fi it joined)\n"
                                  "[5][NOTE] Chain: 192.168.0.179 joined below this one\n"
                                  "[6][WARN] Chain hello from 192.168.0.190 refused (wrong chain secret)\n[web] serving\n")
        self.assertEqual((root["home"], root["chain"]["root"], root["chain"]["below"], root["chain"]["refused"]),
                         ("192.168.0.173", True, ["192.168.0.179"], ["192.168.0.190"]))
        first = stump.settings_from(answers(chain="first", secret="s3cret", ssid="Home Net", radio="none"))["values"]
        rows, notes = stump.start_report(root, first, "Stump")
        self.assertTrue(any("192.168.0.173" in n and "Reserve" in n for n in notes))

    def test_the_bundle_is_team_stumps_release(self):
        self.assertIsNotNone(BUNDLE)
        self.assertEqual(BUNDLE.head["micropython_sha256"],
                         "67c19ae123d84152019b57526ed5291dd0a2b4edd87655c5f76b46c9a62ff5dd")
        self.assertGreater(len(BUNDLE.app()), 50)
        for s in ("Bob's Glitch", "SalutComment", "TeK_Knoh", "'TeK'"):
            self.assertNotIn(s, BUNDLE.template)


if __name__ == "__main__":
    unittest.main(verbosity=1)
