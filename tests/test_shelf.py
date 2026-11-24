"""The shelf (Official and Sandbox copies, offline, and their updates online)
and the installers that use them, with a pretend GitHub and pretend products."""

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from provisioner import installers, shelf  # noqa: E402


def sha(b):
    return hashlib.sha256(b).hexdigest()


def tgz(top, files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for n, text in files.items():
            data = text.encode()
            ti = tarfile.TarInfo("%s/%s" % (top, n))
            ti.size, ti.mode = len(data), 0o755
            t.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def prov_tgz(version, install="#!/bin/bash\necho '>>> The app'\necho done\n"):
    return tgz("RK3326-Provisioner-%s" % version, {"VERSION": version + "\n", "install.sh": install,
                                                    "provisioner/__main__.py": ""})


REPO = "ruderigo/SandBox_RK3326_Provisioner"


def name(v):
    return "RK3326-Provisioner-%s.tar.gz" % v


class Pretend:
    """GitHub's releases API and downloads, from a dict."""

    def __init__(self, releases, blobs):
        self.releases, self.blobs, self.calls = releases, blobs, []

    def __call__(self, url, timeout=10):
        self.calls.append(url)
        if url.startswith("https://api.github.com/"):
            repo = url.split("/repos/")[1].split("/releases")[0]
            if repo not in self.releases:
                raise OSError("no network")
            return json.dumps(self.releases[repo]).encode()
        return self.blobs[url]


def release(tag, assets, pre=True, digest=True):
    return {"tag_name": tag, "prerelease": pre, "draft": False, "html_url": "",
            "assets": [{"name": n, "browser_download_url": "https://dl/%s/%s" % (tag, n), "size": len(b),
                        "digest": ("sha256:" + sha(b)) if digest else None} for n, b in assets.items()]}


class Shelf(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="shelf-")
        self.addCleanup(shutil.rmtree, self.d, True)
        self.env = {"PROVISIONER_SHELF": os.path.join(self.d, "card")}
        os.environ["PROVISIONER_BUILTIN_SHELF"] = os.path.join(self.d, "builtin")
        self.addCleanup(os.environ.pop, "PROVISIONER_BUILTIN_SHELF", None)

    def test_versions(self):
        k = shelf.version_key
        self.assertLess(k("1.0.0-beta.48"), k("1.0.0-beta.51"))
        self.assertLess(k("1.0.0-beta.51"), k("1.0.0"))
        self.assertLess(k("v2.2.0-r36max"), k("2.3.0-r36max"))
        self.assertLess(k("0.3.0-beta.7"), k("0.3.0-beta.10"))
        self.assertLess(k("0.8.1"), k("0.10.0"))

    def test_online_newest_with_its_file(self):
        z = prov_tgz("0.3.0-beta.9")
        gh = Pretend({REPO: [
            release("v0.3.0-beta.8", {name("0.3.0-beta.8"): prov_tgz("0.3.0-beta.8")}),
            release("v0.3.0-beta.9", {name("0.3.0-beta.9"): z, "notes.txt": b"x"}),
            release("v1.0.0", {"something-else.zip": b"x"})]}, {})          # no tarball: not a Provisioner release
        r = shelf.online("provisioner", "sandbox", get=gh)
        self.assertEqual((r["tag"], r["version"]), ("v0.3.0-beta.9", "0.3.0-beta.9"))
        self.assertEqual([a["name"] for a in r["assets"]], [name("0.3.0-beta.9")])
        self.assertEqual(r["assets"][0]["sha256"], sha(z))
        self.assertIsNone(shelf.online("provisioner", "official", get=gh))       # no official Provisioner
        with self.assertRaises(shelf.ShelfError):
            shelf.online("stump", "official", get=gh)                          # "no network"

    def test_fetch_checked_then_on_the_shelf(self):
        v = "0.3.0-beta.9"
        z = prov_tgz(v)
        rel = release("v" + v, {name(v): z})
        url = "https://dl/v%s/%s" % (v, name(v))
        gh = Pretend({REPO: [rel]}, {url: z})
        r = shelf.online("provisioner", "sandbox", get=gh)
        c = shelf.fetch("provisioner", "sandbox", r, get=gh, env=self.env)
        self.assertEqual((c["version"], c["where"]), (v, "card"))
        os.environ["PROVISIONER_SHELF"] = self.env["PROVISIONER_SHELF"]
        self.addCleanup(os.environ.pop, "PROVISIONER_SHELF", None)
        self.assertEqual(shelf.best("provisioner", "sandbox")["version"], v)
        with open(shelf.main_file(c), "rb") as f:
            self.assertEqual(f.read(), z)
        # Changed on the way: refused, nothing kept.
        gh.blobs[url] = z + b"!"
        shutil.rmtree(self.env["PROVISIONER_SHELF"])
        with self.assertRaises(shelf.ShelfError):
            shelf.fetch("provisioner", "sandbox", r, get=gh, env=self.env)
        self.assertIsNone(shelf.best("provisioner", "sandbox"))
        # Nothing to check it against: refused.
        bare = shelf.online("provisioner", "sandbox", get=Pretend(
            {REPO: [release("v" + v, {name(v): z}, digest=False)]}, {}))
        with self.assertRaisesRegex(shelf.ShelfError, "no SHA-256"):
            shelf.fetch("provisioner", "sandbox", bare, get=gh, env=self.env)

    def test_sha256sums_checked_too(self):
        v = "0.3.0-beta.9"
        t = prov_tgz(v)
        sums = ("%s  %s\n" % ("0" * 64, name(v))).encode()                # disagrees with the file
        rel = release("v" + v, {name(v): t, "SHA256SUMS": sums})
        gh = Pretend({REPO: [rel]}, {"https://dl/v%s/%s" % (v, name(v)): t, "https://dl/v%s/SHA256SUMS" % v: sums})
        r = shelf.online("provisioner", "sandbox", get=gh)
        with self.assertRaisesRegex(shelf.ShelfError, "doesn't match"):
            shelf.fetch("provisioner", "sandbox", r, get=gh, env=self.env)

    def test_files_read_for_what_they_are(self):
        p = os.path.join(self.d, "anything.tar.gz")
        with open(p, "wb") as f:
            f.write(prov_tgz("0.3.0-beta.8"))
        c = shelf.from_file("provisioner", p)
        self.assertEqual((c["version"], list(c["files"])), ("0.3.0-beta.8", [name("0.3.0-beta.8")]))
        with self.assertRaisesRegex(shelf.ShelfError, "is a"):
            shelf.from_file("stump", p)
        self.assertEqual(shelf.ORDER, ["provisioner", "stump"])          # the handheld's apps: their own setup
        bad = os.path.join(self.d, "bad.tar.gz")
        with open(bad, "wb") as f:
            f.write(tgz("x", {"VERSION": "1\n"}))
        with self.assertRaisesRegex(shelf.ShelfError, "no install.sh"):
            shelf.from_file("provisioner", bad)
        with open(bad, "wb") as f:
            f.write(b"not a tarball")
        with self.assertRaises(shelf.ShelfError):
            shelf.from_file("provisioner", bad)

    def test_the_built_in_shelf(self):
        os.environ.pop("PROVISIONER_BUILTIN_SHELF")
        for p, ch, v in (("stump", "official", "1.0.0-beta.48"), ("stump", "sandbox", "1.0.0-beta.86")):
            c = shelf.best(p, ch, env=self.env)
            self.assertEqual((c["version"], c["where"]), (v, "built-in"), (p, ch))
            with open(shelf.main_file(c), "rb") as f:
                data = f.read()
            shelf.check(p, {os.path.basename(shelf.main_file(c)): data})       # reads as what it is
        b = shelf.from_file("stump", shelf.main_file(shelf.best("stump", "sandbox", env=self.env)))
        self.assertEqual(b["version"], "1.0.0-beta.86")
        imgs = sorted(f for f in os.listdir(shelf.best("stump", "sandbox", env=self.env)["dir"]) if f.endswith(".bin"))
        self.assertEqual(imgs, ["stump-1.0.0-beta.86-s3cam.bin", "stump-1.0.0-beta.86-wrover.bin"])   # its images


    def test_a_pack_that_fails_its_hashes_is_left_off(self):
        """b82's marcopolo-pack-1.0.zip: its install.py doesn't match its plugin.json.
        That pack stays off the shelf (said, noted); the Stump and the other packs go on."""
        import io
        import zipfile
        os.environ.pop("PROVISIONER_BUILTIN_SHELF")
        src = shelf.best("stump", "sandbox", env=self.env)
        files = {}
        for n in os.listdir(src["dir"]):
            if n != "meta.json":
                with open(os.path.join(src["dir"], n), "rb") as f:
                    files[n] = f.read()
        good = sorted(n for n in files if n.startswith("tavern-pack-"))[-1]
        bad, out = io.BytesIO(), io.BytesIO(files[good])
        with zipfile.ZipFile(out) as zin, zipfile.ZipFile(bad, "w") as zout:
            for i in zin.infolist():
                d = zin.read(i)
                zout.writestr(i, d + b"# changed\n" if i.filename.endswith("/install.py") else d)
        files["broken-pack-1.0.zip"] = bad.getvalue()
        said = []
        c = shelf.put("stump", "sandbox", src["tag"], src["version"], "", files, env=self.env, log=said.append)
        self.assertNotIn("broken-pack-1.0.zip", os.listdir(c["dir"]))
        self.assertIn(good, os.listdir(c["dir"]))
        self.assertTrue(any("left off: broken-pack-1.0.zip" in s and "changed since it was hashed" in s for s in said))
        with open(os.path.join(c["dir"], "meta.json")) as f:
            self.assertIn("broken-pack-1.0.zip", json.load(f)["left_off"])


class Installers(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="home-")
        self.addCleanup(shutil.rmtree, self.home, True)

    def copy(self, product, name, data, version):
        p = os.path.join(self.home, name)
        with open(p, "wb") as f:
            f.write(data)
        return {"product": product, "channel": "sandbox", "version": version, "files": {name: p}, "tag": "v" + version}

    def test_the_provisioner_replaces_itself_and_goes_back(self):
        app = os.path.join(self.home, "rk3326_provisioner")
        os.makedirs(app)
        with open(os.path.join(app, "VERSION"), "w") as f:
            f.write("0.3.0-beta.7\n")
        inst = '#!/bin/bash\necho ">>> The app"\nprintf "0.3.0-beta.8\\n" > "$PROVISIONER_APP/VERSION"\n'
        c = self.copy("provisioner", "RK3326-Provisioner-0.3.0-beta.8.tar.gz",
                      tgz("RK3326-Provisioner-0.3.0-beta.8", {"install.sh": inst, "VERSION": "0.3.0-beta.8\n",
                                                              "provisioner/__main__.py": ""}), "0.3.0-beta.8")
        ok, msg = installers.self_update(c, lambda s: None, lambda s: None, app=app, home=self.home)
        self.assertTrue(ok, msg)
        self.assertEqual(installers.version_in(app), "0.3.0-beta.8")
        self.assertEqual(installers.version_in(installers.previous_dir(app)), "0.3.0-beta.7")
        ok, msg = installers.rollback(app)
        self.assertTrue(ok, msg)
        self.assertEqual(installers.version_in(app), "0.3.0-beta.7")
        self.assertEqual(installers.version_in(installers.previous_dir(app)), "0.3.0-beta.8")   # to swap back
        os.makedirs(os.path.join(app, ".git"))
        self.assertIn("git clone", installers.self_update_why(app))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=1, exit=False).result.wasSuccessful() else 1)
