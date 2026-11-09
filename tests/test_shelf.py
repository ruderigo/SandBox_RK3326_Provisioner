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
import zipfile

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


def firefly_zip(version, install="#!/bin/bash\necho '== 1/5 Packages'\necho done\n"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("firefly/firefly/__init__.py", '__version__ = "%s"\n' % version)
        z.writestr("firefly/deploy/install.sh", install)
    return buf.getvalue()


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
        z = firefly_zip("0.9.0")
        gh = Pretend({"ruderigo/SandBox_FireFly_RK3326": [
            release("v0.8.1", {"FireFly-RK3326-0.8.1.zip": firefly_zip("0.8.1")}),
            release("v0.9.0", {"FireFly-RK3326-0.9.0.zip": z, "notes.txt": b"x"}),
            release("v1.0.0", {"something-else.zip": b"x"})]}, {})          # no FireFly zip: not a FireFly release
        r = shelf.online("firefly", "sandbox", get=gh)
        self.assertEqual((r["tag"], r["version"]), ("v0.9.0", "0.9.0"))
        self.assertEqual([a["name"] for a in r["assets"]], ["FireFly-RK3326-0.9.0.zip"])
        self.assertEqual(r["assets"][0]["sha256"], sha(z))
        self.assertIsNone(shelf.online("provisioner", "official", get=gh))       # no official Provisioner
        with self.assertRaises(shelf.ShelfError):
            shelf.online("firefly", "official", get=gh)                        # "no network"

    def test_fetch_checked_then_on_the_shelf(self):
        z = firefly_zip("0.9.0")
        rel = release("v0.9.0", {"FireFly-RK3326-0.9.0.zip": z})
        gh = Pretend({"ruderigo/SandBox_FireFly_RK3326": [rel]}, {"https://dl/v0.9.0/FireFly-RK3326-0.9.0.zip": z})
        r = shelf.online("firefly", "sandbox", get=gh)
        c = shelf.fetch("firefly", "sandbox", r, get=gh, env=self.env)
        self.assertEqual((c["version"], c["where"]), ("0.9.0", "card"))
        os.environ["PROVISIONER_SHELF"] = self.env["PROVISIONER_SHELF"]
        self.addCleanup(os.environ.pop, "PROVISIONER_SHELF", None)
        self.assertEqual(shelf.best("firefly", "sandbox")["version"], "0.9.0")
        with open(shelf.main_file(c), "rb") as f:
            self.assertEqual(f.read(), z)
        # Changed on the way: refused, nothing kept.
        gh.blobs["https://dl/v0.9.0/FireFly-RK3326-0.9.0.zip"] = z + b"!"
        shutil.rmtree(self.env["PROVISIONER_SHELF"])
        with self.assertRaises(shelf.ShelfError):
            shelf.fetch("firefly", "sandbox", r, get=gh, env=self.env)
        self.assertIsNone(shelf.best("firefly", "sandbox"))
        # Nothing to check it against: refused.
        bare = shelf.online("firefly", "sandbox", get=Pretend(
            {"ruderigo/SandBox_FireFly_RK3326": [release("v0.9.0", {"FireFly-RK3326-0.9.0.zip": z}, digest=False)]}, {}))
        with self.assertRaisesRegex(shelf.ShelfError, "no SHA-256"):
            shelf.fetch("firefly", "sandbox", bare, get=gh, env=self.env)

    def test_sha256sums_checked_too(self):
        t = tgz("R36MAX-Stump-2.3.0-r36max", {"handheld/VERSION": "2.3.0-r36max\n", "handheld/install.sh": "x"})
        name = "R36MAX-Stump-handheld-2.3.0-r36max.tar.gz"
        sums = ("%s  %s\n" % ("0" * 64, name)).encode()                   # disagrees with the file
        rel = release("v2.3.0-r36max", {name: t, "SHA256SUMS": sums})
        gh = Pretend({"ruderigo/SandBox_RK3326_Stump": [rel]}, {"https://dl/v2.3.0-r36max/" + name: t,
                                                                 "https://dl/v2.3.0-r36max/SHA256SUMS": sums})
        r = shelf.online("handheld", "sandbox", get=gh)
        with self.assertRaisesRegex(shelf.ShelfError, "doesn't match"):
            shelf.fetch("handheld", "sandbox", r, get=gh, env=self.env)

    def test_files_read_for_what_they_are(self):
        p = os.path.join(self.d, "anything.zip")
        with open(p, "wb") as f:
            f.write(firefly_zip("0.8.2"))
        c = shelf.from_file("firefly", p)
        self.assertEqual((c["version"], list(c["files"])), ("0.8.2", ["FireFly-RK3326-0.8.2.zip"]))
        with self.assertRaisesRegex(shelf.ShelfError, "is a"):
            shelf.from_file("provisioner", p)
        bad = os.path.join(self.d, "bad.tar.gz")
        with open(bad, "wb") as f:
            f.write(tgz("x", {"VERSION": "1\n"}))
        with self.assertRaisesRegex(shelf.ShelfError, "no install.sh"):
            shelf.from_file("provisioner", bad)
        with open(bad, "wb") as f:
            f.write(b"not a tarball")
        with self.assertRaises(shelf.ShelfError):
            shelf.from_file("handheld", bad)

    def test_the_built_in_shelf(self):
        os.environ.pop("PROVISIONER_BUILTIN_SHELF")
        for p, ch, v in (("stump", "official", "1.0.0-beta.48"), ("stump", "sandbox", "1.0.0-beta.61"),
                         ("firefly", "official", "0.8.1"), ("firefly", "sandbox", "0.9.3"),
                         ("handheld", "official", "2.0.0-r36max"), ("handheld", "sandbox", "2.5.0-b.55")):
            c = shelf.best(p, ch, env=self.env)
            self.assertEqual((c["version"], c["where"]), (v, "built-in"), (p, ch))
            with open(shelf.main_file(c), "rb") as f:
                data = f.read()
            shelf.check(p, {os.path.basename(shelf.main_file(c)): data})       # reads as what it is
        b = shelf.from_file("stump", shelf.main_file(shelf.best("stump", "sandbox", env=self.env)))
        self.assertEqual(b["version"], "1.0.0-beta.61")
        imgs = sorted(f for f in os.listdir(shelf.best("stump", "sandbox", env=self.env)["dir"]) if f.endswith(".bin"))
        self.assertEqual(imgs, ["stump-1.0.0-beta.61-s3cam.bin", "stump-1.0.0-beta.61-wrover.bin"])   # its images


class Installers(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="home-")
        self.addCleanup(shutil.rmtree, self.home, True)

    def copy(self, product, name, data, version):
        p = os.path.join(self.home, name)
        with open(p, "wb") as f:
            f.write(data)
        return {"product": product, "channel": "sandbox", "version": version, "files": {name: p}, "tag": "v" + version}

    def test_firefly(self):
        c = self.copy("firefly", "FireFly-RK3326-0.9.0.zip", firefly_zip("0.9.0"), "0.9.0")
        lines, steps = [], []
        ok, msg = installers.firefly_install(c, lines.append, steps.append, home=self.home)
        self.assertTrue(ok, lines)
        self.assertIn("1/5 Packages", steps)
        c = self.copy("firefly", "FireFly-RK3326-0.9.1.zip",
                      firefly_zip("0.9.1", "#!/bin/bash\necho 'ERROR: pygame 2 is required'\nexit 1\n"), "0.9.1")
        ok, msg = installers.firefly_install(c, lines.append, steps.append, home=self.home)
        self.assertEqual((ok, msg), (False, "ERROR: pygame 2 is required"))

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

    def test_marks(self):
        self.assertEqual(installers.marks(self.home), {})
        installers.mark("firefly", {"version": "0.9.0", "channel": "sandbox"}, home=self.home)
        self.assertEqual(installers.marks(self.home)["firefly"]["version"], "0.9.0")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(verbosity=1, exit=False).result.wasSuccessful() else 1)
