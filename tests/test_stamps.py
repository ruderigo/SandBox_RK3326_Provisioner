#!/usr/bin/env python3
"""A Stump's announce stamps (SandBox_Stump_On 1.0.0-beta.86), worked out
here: Reticulum 1.6.1's proof of work, checked as Team Stump's code checks
it; a CAM's missing ones over the pretend board (a cheap cost, so the test
is quick).
    python3 tests/test_stamps.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from provisioner import stamps as S  # noqa: E402
from test_stump import PipeLink  # noqa: E402
from test_identity import team_stump  # noqa: E402

M1, M2 = bytes(range(64)), bytes(range(1, 65))
REAL = "eb806aa076b039964d4d8e3fc1b9"          # a 25-bit stamp for M1, worked out once


class TheStamp(unittest.TestCase):
    def test_check_and_find(self):
        self.assertTrue(S.ok(M1, bytes.fromhex(REAL)))
        self.assertFalse(S.ok(M2, bytes.fromhex(REAL)))
        self.assertFalse(S.ok(M1, bytes.fromhex(REAL)[:13]))
        s = S.find(M2, 14, workers=2)
        self.assertTrue(S.ok(M2, s, 14))
        self.assertEqual(S.missing({"aa": M1.hex(), "bb": M2.hex(), "cc": "zz"}, {"aa": REAL}), {"bb": M2})

    @unittest.skipUnless(team_stump(), "STUMP_ON isn't a SandBox_Stump_On of beta.76 or newer")
    def test_as_team_stump_checks_it(self):
        P = team_stump()
        if not hasattr(P, "_stamp_ok"):
            self.skipTest("STUMP_ON is older than 1.0.0-beta.86")
        self.assertEqual((P.STAMP_COST, P.STAMP_LEN), (S.COST, S.STAMP_LEN))
        self.assertTrue(P._stamp_ok(M1, bytes.fromhex(REAL)))
        self.assertTrue(P._stamp_ok(M2, S.find(M2, 14, workers=2), 14))


class OnTheBoard(unittest.TestCase):
    def setUp(self):
        os.environ["FAKE_MPY"] = "6.3"
        self.root = tempfile.mkdtemp(prefix="board-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.links = []
        self.addCleanup(lambda: [link.close() for link in self.links])
        os.makedirs(os.path.join(self.root, "rns"))
        with open(os.path.join(self.root, "config.py"), "w") as f:
            f.write("NODE_NAME = 'Oak'\n")
        self.steps, self.log = [], []

    def link(self):
        self.links.append(PipeLink(self.root))
        return self.links[-1]

    def put(self, name, d):
        with open(os.path.join(self.root, "rns", name), "w") as f:
            json.dump(d, f)

    def job(self):
        return S.board_job(self.link, self.steps.append, self.log.append, cost=12)

    def test_not_ticked_yet(self):
        ok, msg = self.job()
        self.assertFalse(ok)
        self.assertIn("Announce stamps", msg)

    def test_missing_ones_worked_out_and_copied(self):
        self.put("stamps_wanted.json", {"aa": M1.hex(), "bb": M2.hex()})
        self.put("stamps.json", {"aa": REAL})
        ok, msg = self.job()
        self.assertTrue(ok, msg)
        self.assertIn("1 announce stamp(s) worked out here", msg)
        with open(os.path.join(self.root, "rns", "stamps.json")) as f:
            got = json.load(f)
        self.assertEqual(got["aa"], REAL)                              # the one it had kept
        self.assertTrue(S.ok(M2, bytes.fromhex(got["bb"]), 12))
        ok, msg = self.job()
        self.assertEqual((ok, msg), (True, "Its 2 announce stamp(s) are all there."))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=1, exit=False).result.wasSuccessful() else 1)
