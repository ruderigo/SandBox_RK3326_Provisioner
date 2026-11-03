"""install.sh on each kind of system, in a pretend root (PROVISIONER_TEST_ROOT):
ArkOS/dArkOS (a user's home, /roms and /roms2, /etc/udev) and AmberELEC/
ROCKNIX (everything under /storage, /roms a link to it, udev rules there)."""

import os
import shutil
import subprocess
import sys
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

    def test_no_ports_folder_says_so(self):
        code, out = run_install(self.r, self.mk("home", "ark"))
        self.assertIn("no roms/ports folder", out)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=1, exit=False).result.wasSuccessful() else 1)
