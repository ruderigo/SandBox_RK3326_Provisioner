"""This handheld's Stump: finding R36MAX-Stump's installer, the wizard's
answers from the form, and running `install.sh --answers` (a pretend one).

With STUMP_ON=path/to/SandBox_Stump_On, the answers also go through Team
Stump's real wizard (`provisioner.py --pc --answers`, into a scratch folder;
it makes the Stump's venv: pip needs internet the first time)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from provisioner import handheld as H  # noqa: E402

FAKE = r'''#!/bin/bash
[ "$1" = "--answers" ] || { echo "[x] no --answers"; exit 9; }
echo -e "\033[1;33m>>> 1/6 Packages\033[0m"
echo "mode $(stat -c %a "$2")"
python3 -c "import json,sys; print('name', json.load(open(sys.argv[1]))['node name'])" "$2"
cp "$2" "$(dirname "$0")/seen.json"
if [ -f "$(dirname "$0")/fail" ]; then echo -e "\033[31m[x] apt-get couldn't install: git (the first install needs internet)\033[0m"; exit 1; fi
echo -e ">>> Check"
echo -e "    \033[32m✓\033[0m Stump up: R36-Test 1.0.0-beta.50 on :80, no chain"
'''


def fake_repo(home, repo="SandBox_RK3326_Stump", version="2.3.0-r36max", answers=True):
    d = os.path.join(home, repo, "handheld")
    os.makedirs(d)
    with open(os.path.join(d, "install.sh"), "w") as f:
        f.write(FAKE if answers else "#!/bin/bash\necho old\n")
    with open(os.path.join(d, "VERSION"), "w") as f:
        f.write(version + "\n")
    return os.path.join(d, "install.sh")


class Handheld(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="home-")
        self.addCleanup(shutil.rmtree, self.home, True)

    def test_the_installer_that_takes_answers_first(self):
        self.assertIsNone(H.find_installer(self.home))
        fake_repo(self.home, "R36MAX-Stump", "2.0.0-r36max", answers=False)
        self.assertFalse(H.find_installer(self.home)["answers"])
        fake_repo(self.home)
        i = H.find_installer(self.home)
        self.assertEqual((i["repo"], i["version"], i["answers"]), ("SandBox_RK3326_Stump", "2.3.0-r36max", True))

    def test_where_it_has_a_row(self):
        apt = lambda n: "/usr/bin/" + n           # noqa: E731
        self.assertIn("root", H.system_why(euid=0, which=apt))
        self.assertIn("apt", H.system_why(euid=1000, which=lambda n: None))
        self.assertEqual(H.system_why(euid=1000, which=apt), "")
        fake_repo(self.home)
        st = H.state(self.home, euid=1000, which=apt)
        self.assertFalse(st["installed"])
        os.makedirs(os.path.join(self.home, "Stump"))
        open(os.path.join(self.home, "Stump", "stump_pc.py"), "w").close()
        self.assertTrue(H.state(self.home, euid=1000, which=apt)["installed"])
        self.assertIn("root", H.state(self.home, euid=0, which=apt)["why"])      # the installer's there: says why not

    def test_answers(self):
        a = dict(H.form_defaults(), name="R36", chain="member", parent="192.168.1.20", secret="s", tavern="yes",
                 pw="admin-pw", opw="oper-pw")
        ans = H.answers(a, "/home/ark/Stump")
        self.assertEqual((ans["_admin password"], ans["fserv bot operator password"]), ("admin-pw", "oper-pw"))
        self.assertIn("admin password is needed", H.answers(dict(a, pw=""), "/x")["error"])          # a new Stump
        self.assertNotIn("_admin password", H.answers(dict(a, pw=""), "/x", again=True))              # its own: kept
        self.assertIn("needed", H.answers(dict(a, pw=""), "/x", again=True, admin_state="DEFAULT")["error"])
        self.assertIn("4 to 64", H.answers(dict(a, pw="abc"), "/x")["error"])
        self.assertIn("fserv", H.answers(dict(a, opw="abc"), "/x")["error"])
        self.assertEqual(H.answers(dict(a, opw=""), "/x")["fserv bot operator password"], "")       # editing off
        self.assertEqual(ans["node name"], "R36")
        self.assertEqual(ans["the wi-fi name visitors join"], "R36")
        self.assertEqual(ans["that stump's address"], "192.168.1.20")
        self.assertEqual(ans["chain secret"], "s")
        self.assertTrue(ans["install tavern"])
        self.assertEqual(ans["the heltec"], "Plugged into this computer by USB")
        self.assertNotIn("change something", ans)
        self.assertEqual(H.answers(a, "/x", again=True)["change something"], "a")
        self.assertIn("name", H.answers(dict(a, name=" "), "/x")["error"])
        self.assertIn("address", H.answers(dict(a, parent="192.168.1"), "/x")["error"])
        self.assertIn("address", H.answers(dict(a, parent="300.1.1.1"), "/x")["error"])
        self.assertIn("MB", H.answers(dict(a, storage="lots"), "/x")["error"])
        first = H.answers(dict(a, chain="first"), "/x")
        self.assertEqual((first["its place in the chain"], "that stump's address" in first), ("The first", False))
        self.assertEqual(H.update_answers("/x")["change something"], "")
        self.assertEqual(H.form_defaults({"name": "LaBuche-R36"})["name"], "LaBuche-R36")

    def test_its_passwords(self):
        folder = os.path.join(self.home, "Stump")
        self.assertEqual(H.password_state(folder), "NONE")
        os.makedirs(os.path.join(folder, "venv", "bin"))
        os.symlink(sys.executable, os.path.join(folder, "venv", "bin", "python"))
        with open(os.path.join(folder, "settings.py"), "w") as f:
            f.write("def write_config(ch, path):\n    t = open(path).read()\n"
                    "    for k, v in ch.items():\n        t = '\\n'.join('%s = %r' % (k, v) if l.startswith(k + ' =') "
                    "else l for l in t.split('\\n'))\n    open(path, 'w').write(t)\n    return True\n")
        with open(os.path.join(folder, "config.py"), "w") as f:
            f.write("AUTH_ADMIN_PASSWORD = 'TeK'\nFSERVBOT_OP_PASSWORD = ''\n")
        self.assertEqual(H.password_state(folder), "DEFAULT")
        self.assertEqual(H.password_state(folder, "FSERVBOT_OP_PASSWORD"), "EMPTY")
        ran = []
        fake = lambda cmd, **kw: ran.append(cmd) or subprocess.run(cmd, **kw) if cmd[0].endswith("python") \
            else subprocess.CompletedProcess(cmd, 0, "")                                  # noqa: E731
        ok, msg = H.set_password(folder, "FSERVBOT_OP_PASSWORD", "op-pass", lambda s: None, run=fake)
        self.assertTrue(ok, msg)
        self.assertIn("restarted", msg)
        self.assertEqual(H.password_state(folder, "FSERVBOT_OP_PASSWORD"), "SET")
        self.assertFalse(any("op-pass" in " ".join(c) for c in ran))           # by stdin, not the command line
        self.assertFalse(H.set_password(folder, "NODE_NAME", "xxxxx", lambda s: None)[0])
        self.assertFalse(H.set_password(folder, "AUTH_ADMIN_PASSWORD", "abc", lambda s: None)[0])

    def test_run_install_sh(self):
        inst = H.find_installer(self.home) or dict(path=fake_repo(self.home), repo="SandBox_RK3326_Stump",
                                                     version="2.3.0-r36max", answers=True)
        lines, steps = [], []
        ok, msg = H.run(inst, {"node name": "R36-Test", "chain secret": "s3cret"}, lines.append, steps.append,
                        home=self.home)
        self.assertTrue(ok, lines)
        self.assertIn("The Stump is up: R36-Test 1.0.0-beta.50", msg)
        self.assertEqual(steps, ["1/6 Packages", "Check"])                 # colours gone
        self.assertIn("mode 600", lines)                                   # the file can hold the chain's secret
        self.assertIn("name R36-Test", lines)
        self.assertEqual(os.listdir(os.path.join(self.home, ".cache", "rk3326-provisioner")), [])   # and it's gone
        open(os.path.join(os.path.dirname(inst["path"]), "fail"), "w").close()
        ok, msg = H.run(inst, {"node name": "R36-Test"}, lines.append, steps.append, home=self.home)
        self.assertFalse(ok)
        self.assertEqual(msg, "apt-get couldn't install: git (the first install needs internet)")


@unittest.skipUnless(os.environ.get("STUMP_ON"), "STUMP_ON=path/to/SandBox_Stump_On runs Team Stump's real wizard")
class TeamStumpsWizard(unittest.TestCase):
    """The answers the form makes, through `provisioner.py --pc --answers`."""

    def wizard(self, folder, ans):
        ans = dict(ans, **{"start this stump automatically when you log in": False})
        path = os.path.join(os.path.dirname(folder), "answers.json")
        with open(path, "w") as f:
            json.dump(ans, f)
        p = subprocess.run([sys.executable, "provisioner.py", "--pc", folder, "--answers", path],
                           cwd=os.environ["STUMP_ON"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=1200)
        self.assertEqual(p.returncode, 0, p.stdout[-3000:])
        with open(os.path.join(folder, "config.py")) as f:
            return f.read()

    def install(self, folder, ans):
        """As install.sh does: the wizard, then the admin password it doesn't ask."""
        self.wizard(folder, ans)
        if ans.get("_admin password"):
            ok, msg = H.set_password(folder, "AUTH_ADMIN_PASSWORD", ans["_admin password"], lambda s: None)
            self.assertTrue(ok, msg)
        with open(os.path.join(folder, "config.py")) as f:
            return f.read()

    def test_new_again_update(self):
        d = tempfile.mkdtemp(prefix="stump-")
        self.addCleanup(shutil.rmtree, d, True)
        folder = os.path.join(d, "Stump")
        a = dict(H.form_defaults(), name="R36-Test", chain="member", parent="192.168.1.20", secret="s3cret-test",
                 heltec="none", tavern="yes", pw="admin-pw-1", opw="oper-pw-1")
        cfg = self.wizard(folder, H.answers(a, folder))
        for want in ("NODE_NAME = 'R36-Test'", "PC_CHAIN_PARENT_IP = '192.168.1.20'", "CHAIN_SECRET = 's3cret-test'",
                     "PC_STORAGE_MB = 2048", "FSERVBOT_OP_PASSWORD = 'oper-pw-1'"):
            self.assertIn(want, cfg)
        # The wizard leaves the repo's admin password (install.sh sets ours after it): it's told apart...
        self.assertEqual(H.password_state(folder), "DEFAULT")
        # ...and set with the Stump's own settings.py.
        lines = []
        ok, msg = H.set_password(folder, "AUTH_ADMIN_PASSWORD", "admin-pw-1", lines.append)
        self.assertTrue(ok, msg)
        self.assertEqual(H.password_state(folder), "SET")
        with open(os.path.join(folder, "config.py")) as f:
            self.assertIn("AUTH_ADMIN_PASSWORD = 'admin-pw-1'", f.read())
        self.assertFalse(any("admin-pw-1" in line for line in lines))        # never in its lines
        self.assertTrue(os.path.isdir(os.path.join(folder, "tavern")))
        again = H.answers(dict(a, name="R36-Again", chain="none", heltec="usb", pw="", opw=""), folder, again=True,
                          current=H.current_passwords(folder))
        self.assertEqual((again["_admin password"], again["fserv bot operator password"]), ("admin-pw-1", "oper-pw-1"))
        cfg = self.install(folder, again)
        self.assertIn("AUTH_ADMIN_PASSWORD = 'admin-pw-1'", cfg)            # sent again: still its own
        self.assertIn("FSERVBOT_OP_PASSWORD = 'oper-pw-1'", cfg)
        self.assertIn("NODE_NAME = 'R36-Again'", cfg)
        self.assertIn("RNodeSerialInterface", cfg)
        cfg = self.wizard(folder, H.update_answers(folder))
        self.assertIn("NODE_NAME = 'R36-Again'", cfg)                       # kept
        self.assertIn("AUTH_ADMIN_PASSWORD = 'admin-pw-1'", cfg)            # kept


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=1, exit=False).result.wasSuccessful() else 1)
