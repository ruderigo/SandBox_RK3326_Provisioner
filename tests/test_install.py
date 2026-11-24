"""install.sh on each kind of system, in a pretend root (PROVISIONER_TEST_ROOT):
ArkOS/dArkOS (a user's home, /roms and /roms2, /etc/udev), AmberELEC/
ROCKNIX (everything under /storage, /roms a link to it, udev rules there) and
RK3326 Linux (its dock: an entry in /data/ark/apps, no Ports folder needed)."""

import os
import shutil
import subprocess
import sys
import json
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_install(r, home):
    env = dict(os.environ, PROVISIONER_TEST_ROOT=r, HOME=home, PROVISIONER_PULLED="1")
    env.pop("SUDO_USER", None)
    p = subprocess.run(["bash", os.path.join(ROOT, "install.sh")], env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True, timeout=300)
    return p.returncode, p.stdout


class Install(unittest.TestCase):
    def setUp(self):
        self.r = tempfile.mkdtemp(prefix="sysroot-")
        self.addCleanup(shutil.rmtree, self.r, True)

    def mk(self, *parts):
        p = os.path.join(self.r, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def launcher_app(self, path):
        with open(path) as f:
            return [l for l in f if l.startswith("APP_DEFAULT=")][0]

    def test_arkos(self):
        home = self.mk("home", "ark")
        self.mk("roms", "ports")
        self.mk("roms2", "ports")
        self.mk("etc", "udev", "rules.d")
        with open(os.path.join(self.r, "etc", "os-release"), "w") as f:
            f.write('PRETTY_NAME="dArkOS"\n')
        code, out = run_install(self.r, home)
        self.assertEqual(code, 0, out)
        app = os.path.join(home, "rk3326_provisioner")
        self.assertTrue(os.path.isfile(os.path.join(app, "provisioner", "__main__.py")), out)
        for ports in ("roms", "roms2"):
            l = os.path.join(self.r, ports, "ports", "RK3326_Provisioner.sh")
            self.assertTrue(os.access(l, os.X_OK), out)
            self.assertIn('"%s"' % app, self.launcher_app(l))
        self.assertTrue(os.path.isfile(os.path.join(self.r, "etc", "udev", "rules.d", "99-rk3326-provisioner.rules")))
        self.assertIn("On dArkOS", out)
        # Again: the rule and the Ports entries are the same, so nothing for sudo to do.
        code, out = run_install(self.r, home)
        self.assertEqual(code, 0, out)
        self.assertIn("udev rule (%s, unchanged)" % os.path.join(self.r, "etc", "udev", "rules.d"), out)
        self.assertIn("RK3326_Provisioner.sh (unchanged)", out)

    def test_rocknix_and_amberelec(self):
        home = self.mk("storage")
        self.mk("storage", "roms", "ports")
        self.mk("storage", ".config")
        os.symlink(os.path.join(self.r, "storage", "roms"), os.path.join(self.r, "roms"))   # AmberELEC's /roms
        code, out = run_install(self.r, home)
        self.assertEqual(code, 0, out)
        app = os.path.join(home, "rk3326_provisioner")
        l = os.path.join(self.r, "storage", "roms", "ports", "RK3326_Provisioner.sh")
        self.assertIn('"%s"' % app, self.launcher_app(l))
        self.assertEqual(out.count("/ports/RK3326_Provisioner.sh"), 1, out)   # once: the link isn't a second card
        self.assertTrue(os.path.isfile(os.path.join(self.r, "storage", ".config", "udev.rules.d",
                                                    "99-rk3326-provisioner.rules")))
        self.assertFalse(os.path.exists(os.path.join(self.r, "etc", "udev")))   # read-only there

    def test_rk3326_linux(self):
        home = self.mk("home", "ark")
        self.mk("usr", "share", "rk", "apps")
        self.mk("data", "ark")
        self.mk("etc", "udev", "rules.d")
        with open(os.path.join(self.r, "etc", "os-release"), "w") as f:
            f.write('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n')
        code, out = run_install(self.r, home)
        self.assertEqual(code, 0, out)
        app = os.path.join(home, "rk3326_provisioner")
        entry = os.path.join(self.r, "data", "ark", "apps", "provisioner.json")
        with open(entry) as f:
            e = json.load(f)
        self.assertEqual((e["name"], e["icon"], e["group"], e["mouse"]), ("Provisioner", "chip", "Workshop", False))
        self.assertEqual(e["exec"], [os.path.join(app, "RK3326_Provisioner.sh")])
        self.assertTrue(os.access(e["exec"][0], os.X_OK))
        self.assertIn('"%s"' % app, self.launcher_app(e["exec"][0]))
        self.assertNotIn("EmulationStation (Ports)", out)            # no roms/ports there: not needed
        self.assertIn("The dock -> Workshop -> Provisioner", out)
        self.assertTrue(os.path.isfile(os.path.join(self.r, "etc", "udev", "rules.d", "99-rk3326-provisioner.rules")))
        code, out = run_install(self.r, home)
        self.assertEqual(code, 0, out)
        self.assertIn("provisioner.json (unchanged)", out)
        # The image has its own entry now: that one, and ours goes.
        with open(os.path.join(self.r, "usr", "share", "rk", "apps", "provisioner.json"), "w") as f:
            f.write("{}")
        code, out = run_install(self.r, home)
        self.assertEqual(code, 0, out)
        self.assertIn("on the dock already", out)
        self.assertFalse(os.path.exists(entry))
        # With a roms/ports folder too: both.
        self.mk("roms", "ports")
        code, out = run_install(self.r, home)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.r, "roms", "ports", "RK3326_Provisioner.sh")))

    def test_not_a_handheld_nothing_touched(self):
        home = self.mk("home", "ark")
        self.mk("etc", "udev", "rules.d")
        code, out = run_install(self.r, home)
        self.assertNotEqual(code, 0)
        self.assertIn("this isn't the handheld. Nothing was changed.", out)
        self.assertFalse(os.path.exists(os.path.join(home, "rk3326_provisioner")))
        self.assertEqual(os.listdir(os.path.join(self.r, "etc", "udev", "rules.d")), [])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=1, exit=False).result.wasSuccessful() else 1)
