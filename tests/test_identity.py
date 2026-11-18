#!/usr/bin/env python3
"""A Stump's identity in a file (SandBox_Stump_On 1.0.0-beta.76): saved from
Team Stump's pretend board, brought back onto it (the one it had saved
first), read from a keepsake or an old Stump's folder, damaged files refused;
and, with STUMP_ON set to a SandBox_Stump_On checkout of beta.76 or newer,
each file read by the other side's code (Team Stump's provisioner.py).
    python3 tests/test_identity.py
"""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from provisioner import identity as I  # noqa: E402
from test_stump import PipeLink  # noqa: E402

ONE, TWO = bytes(range(64)), bytes(range(64, 128))


def team_stump():
    d = os.environ.get("STUMP_ON")
    if not d or not os.path.isfile(os.path.join(d, "provisioner.py")):
        return None
    import importlib.util                       # under its own name: ours is "provisioner" too
    spec = importlib.util.spec_from_file_location("team_stump_provisioner", os.path.join(d, "provisioner.py"))
    P = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(P)
    return P if hasattr(P, "read_identity_source") else None


class OnTheBoard(unittest.TestCase):
    def setUp(self):
        os.environ["FAKE_MPY"] = "6.3"
        self.root, self.out = tempfile.mkdtemp(prefix="board-"), tempfile.mkdtemp(prefix="keep-")
        self.links, self.steps, self.log = [], [], []
        os.makedirs(os.path.join(self.root, "rns"))
        with open(os.path.join(self.root, "config.py"), "w") as f:
            f.write("NODE_NAME = 'Oak'\n")

    def tearDown(self):
        for link in self.links:
            link.close()
        shutil.rmtree(self.root, True)
        shutil.rmtree(self.out, True)

    def link(self):
        self.links.append(PipeLink(self.root))
        return self.links[-1]

    def put(self, rel, data):
        with open(os.path.join(self.root, rel), "wb") as f:
            f.write(data)

    def get(self, rel):
        with open(os.path.join(self.root, rel), "rb") as f:
            return f.read()

    def test_saved_then_brought_back(self):
        ok, msg, path = I.save_job(self.link, self.steps.append, self.log.append, self.out, "1.0.0-beta.82")
        self.assertFalse(ok)
        self.assertIn("no identity yet", msg)                       # it makes one as it first starts
        self.put("rns/identity", ONE)
        self.put("pn_mailbox_identity", b"m" * 64)
        ok, msg, path = I.save_job(self.link, self.steps.append, self.log.append, self.out, "1.0.0-beta.82")
        self.assertTrue(ok, msg)
        self.assertEqual(os.path.basename(path), "Oak.stump-identity")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(path) as f:
            d = json.load(f)
        self.assertEqual((d["stump_identity"], d["name"], d["release"]), (1, "Oak", "1.0.0-beta.82"))
        self.assertEqual(d["fingerprint"], I.fingerprint({"rns/identity": ONE}))
        self.assertIn(d["fingerprint"], msg)
        files, name = I.read_source(path)
        self.assertEqual((files["rns/identity"], files["pn_mailbox_identity"], name), (ONE, b"m" * 64, "Oak"))
        ok, msg, again = I.save_job(self.link, self.steps.append, self.log.append, self.out)
        self.assertEqual(os.path.basename(again), "Oak (2).stump-identity")      # never over the first
        # Another Stump's identity brought back: the one it had saved first.
        ok, msg = I.restore_job({"rns/identity": TWO}, "Elm", self.link, self.steps.append, self.log.append, self.out)
        self.assertTrue(ok, msg)
        self.assertEqual(self.get("rns/identity"), TWO)
        self.assertFalse(os.path.exists(os.path.join(self.root, "pn_mailbox_identity")))   # its mailbox went with it
        self.assertEqual(self.get("config.py"), b"NODE_NAME = 'Oak'\n")                    # settings stay
        kept = [f for f in os.listdir(self.out) if "(replaced" in f]
        self.assertEqual(len(kept), 1, os.listdir(self.out))
        self.assertTrue(kept[0].startswith("Oak (replaced "))
        self.assertEqual(I.read_source(os.path.join(self.out, kept[0]))[0]["rns/identity"], ONE)
        self.assertIn("It's Elm again", msg)
        # The same one again: nothing to keep.
        ok, msg = I.restore_job({"rns/identity": TWO}, "Elm", self.link, self.steps.append, self.log.append, self.out)
        self.assertTrue(ok, msg)
        self.assertEqual(len([f for f in os.listdir(self.out) if "(replaced" in f]), 1)

    def test_no_stump_no_change(self):
        os.remove(os.path.join(self.root, "config.py"))
        ok, msg = I.restore_job({"rns/identity": TWO}, "Elm", self.link, self.steps.append, self.log.append, self.out)
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(os.path.join(self.root, "rns", "identity")))


class Files(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="keep-")
        self.addCleanup(shutil.rmtree, self.d, True)

    def write(self, name, text):
        p = os.path.join(self.d, name)
        with open(p, "w") as f:
            f.write(text)
        return p

    def test_an_old_stump_folder(self):
        old = os.path.join(self.d, "Stump.old")
        os.makedirs(os.path.join(old, "rns"))
        with open(os.path.join(old, "rns", "identity"), "wb") as f:
            f.write(ONE)
        with open(os.path.join(old, "config.py"), "w") as f:
            f.write('NODE_NAME = "Birch"\n')
        self.assertEqual(I.read_source(old), ({"rns/identity": ONE}, "Birch"))
        with self.assertRaises(I.IdentityError):
            I.read_source(self.d)                                       # no identity in it

    def test_damaged_and_other_files_refused(self):
        good = json.loads(I.keepsake_bytes({"rns/identity": ONE}, "Oak").decode())
        cases = {"not json": "{", "another file": json.dumps({"hello": 1}),
                 "short": json.dumps(dict(good, files={"rns/identity": "AAAA"})),
                 "bad base64": json.dumps(dict(good, files={"rns/identity": "**"}))}
        for what, text in cases.items():
            with self.subTest(what):
                with self.assertRaises(I.IdentityError):
                    I.read_source(self.write("x.stump-identity", text))
        with self.assertRaises(I.IdentityError):
            I.read_source(os.path.join(self.d, "missing.stump-identity"))
        # Only the identity's two files are taken from a keepsake.
        files, _ = I.read_source(self.write("y.stump-identity", json.dumps(dict(good, files=dict(
            good["files"], **{"config.py": "eA=="})))))
        self.assertEqual(sorted(files), ["rns/identity"])

    def test_names(self):
        self.assertEqual(I.file_name('a/b:c*"'), "a_b_c__.stump-identity")
        self.assertEqual(I.file_name(""), "Stump.stump-identity")

    @unittest.skipUnless(team_stump(), "STUMP_ON isn't a SandBox_Stump_On of beta.76 or newer")
    def test_read_by_team_stumps_code_and_back(self):
        from pathlib import Path
        P = team_stump()
        ours = I.save({"rns/identity": ONE, "pn_mailbox_identity": TWO}, "Oak", self.d, "1.0.0-beta.82")
        files, name = P.read_identity_source(ours)
        self.assertEqual((files["rns/identity"], files["pn_mailbox_identity"], name), (ONE, TWO, "Oak"))
        self.assertEqual(P.identity_fingerprint(files), I.fingerprint(files))
        theirs = P.save_keepsake({"rns/identity": TWO}, "Elm", Path(self.d) / "theirs.stump-identity")
        self.assertEqual(I.read_source(str(theirs)), ({"rns/identity": TWO}, "Elm"))
        self.assertEqual(P.KEEPSAKE_EXT, I.EXT)
        self.assertEqual(tuple(P.IDENTITY_FILES), I.IDENTITY_FILES)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=1, exit=False).result.wasSuccessful() else 1)
