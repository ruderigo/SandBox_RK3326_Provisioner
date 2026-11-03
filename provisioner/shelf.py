"""The shelf: offline copies of everything the Provisioner installs, each
from its official (public) repo and from its sandbox, and their updates
when the handheld is online (EmulationStation's network: Wi-Fi, a dongle,
the S3 adapter).

    the Stump (CAM boards)  LaBuche-Stump                SandBox_Stump_On
    this handheld's Stump   R36MAX-Stump                 SandBox_RK3326_Stump
    FireFly (RK3326)        FireFly_RK3326_R36MAX_R36S   SandBox_FireFly_RK3326
    the Provisioner         (none yet)                   SandBox_RK3326_Provisioner

"Official" is the public repo's newest release, "Sandbox" the sandbox's
newest (pre-releases included: Team Stump's are all betas). A copy is
taken only after every file matches the SHA-256 GitHub records for it, and
the release's SHA256SUMS when it has one; then it's read for what it is (a
Stump bundle and its packs, a tarball or zip with its installer). The
shelf on the games card (provisioner-shelf/) holds what was fetched; the
Provisioner carries its own (firmware/shelf/), so it works offline from the
start. + From File takes any such file from a card or a USB drive.

Layout: <shelf>/<product>/<channel>/<tag>/ the release's files + meta.json.
"""

import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILTIN = os.path.join(HERE, "firmware", "shelf")
CHANNELS = ("official", "sandbox")
CHANNEL_NAMES = {"official": "Official", "sandbox": "Sandbox", "file": "From a file"}
API = "https://api.github.com/repos/%s/releases?per_page=15"
UA = "RK3326-Provisioner"

PRODUCTS = {
    "stump": {"title": "The Stump (for the CAM boards)", "short": "Stump",
              "official": "ruderigo/LaBuche-Stump", "sandbox": "ruderigo/SandBox_Stump_On",
              "main": r"^Stump-(.+)\.bundle$", "assets": [r"^Stump-.+\.bundle$", r"^[a-z][a-z0-9_-]*-pack-.+\.zip$"],
              "file": (".bundle",)},
    "handheld": {"title": "This handheld's Stump", "short": "handheld Stump",
                 "official": "ruderigo/R36MAX-Stump", "sandbox": "ruderigo/SandBox_RK3326_Stump",
                 "main": r"^R36MAX-Stump-handheld-(.+)\.tar\.gz$", "assets": [r"^R36MAX-Stump-handheld-.+\.tar\.gz$"],
                 "file": (".tar.gz", ".tgz")},
    "firefly": {"title": "FireFly", "short": "FireFly",
                "official": "ruderigo/FireFly_RK3326_R36MAX_R36S", "sandbox": "ruderigo/SandBox_FireFly_RK3326",
                "main": r"^FireFly-RK3326-(.+)\.zip$", "assets": [r"^FireFly-RK3326-.+\.zip$"], "file": (".zip",)},
    "provisioner": {"title": "The Provisioner", "short": "Provisioner",
                    "official": None, "sandbox": "ruderigo/SandBox_RK3326_Provisioner",
                    "main": r"^RK3326-Provisioner-(.+)\.tar\.gz$", "assets": [r"^RK3326-Provisioner-.+\.tar\.gz$"],
                    "file": (".tar.gz", ".tgz")},
}
ORDER = ["provisioner", "handheld", "firefly", "stump"]


class ShelfError(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


def version_key(v):
    """1.0.0-beta.51 < 1.0.0; 2.3.0-r36max as 2.3.0; anything else after them, by its text."""
    v = (v or "").strip().lstrip("v")
    v = re.sub(r"-r36max$", "", v)
    main, _, pre = v.partition("-")
    try:
        nums = tuple(int(x) for x in main.split("."))
    except ValueError:
        return ((), 0, (), v)
    return (nums, 0 if pre else 1, tuple(int(x) for x in re.findall(r"\d+", pre)), v)


def card_shelf(env=None):
    """Where fetched copies go: the games card (a card reader reaches it), else home."""
    env = os.environ if env is None else env
    if env.get("PROVISIONER_SHELF"):
        return env["PROVISIONER_SHELF"]
    for roms in ("/roms", "/storage/roms", "/roms2"):
        if os.path.isdir(roms) and os.access(roms, os.W_OK):
            return os.path.join(roms, "provisioner-shelf")
    return os.path.join(os.path.expanduser("~"), "provisioner-shelf")


def roots(env=None):
    """The shelves, the card's first: (where, path)."""
    return [("card", card_shelf(env)), ("built-in", os.environ.get("PROVISIONER_BUILTIN_SHELF", BUILTIN))]


def local(product, channel, env=None):
    """The copies of a product's channel on the shelves, newest first:
    [{product, channel, tag, version, dir, files: {name: path}, where, repo}]."""
    out = []
    for where, root in roots(env):
        d = os.path.join(root, product, channel)
        try:
            tags = os.listdir(d)
        except OSError:
            continue
        for tag in tags:
            meta_path = os.path.join(d, tag, "meta.json")
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                continue
            files = {n: os.path.join(d, tag, n) for n in meta.get("files", {}) if os.path.isfile(os.path.join(d, tag, n))}
            if len(files) != len(meta.get("files", {})):
                continue                                    # something's missing: not a copy
            out.append({"product": product, "channel": channel, "tag": meta["tag"], "version": meta["version"],
                        "dir": os.path.join(d, tag), "files": files, "where": where, "repo": meta.get("repo", ""),
                        "fetched": meta.get("fetched", "")})
    out.sort(key=lambda c: (version_key(c["version"]), c["where"] == "card"), reverse=True)
    return out


def best(product, channel, env=None):
    got = local(product, channel, env)
    return got[0] if got else None


def main_file(copy):
    """The copy's main file (the bundle, the tarball, the zip)."""
    pat = re.compile(PRODUCTS[copy["product"]]["main"])
    return next((p for n, p in sorted(copy["files"].items()) if pat.match(n)), None)


# -- online -------------------------------------------------------------------
def _get(url, opener=None, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    op = opener or urllib.request.urlopen
    with op(req, timeout=timeout) as r:
        return r.read()


def online(product, channel, get=_get):
    """The channel's newest release online: {tag, version, prerelease, url,
    assets: [{name, url, sha256, size}]}, or None when it has none.
    ShelfError when GitHub can't be reached."""
    repo = PRODUCTS[product].get(channel)
    if not repo:
        return None
    try:
        rels = json.loads(get(API % repo).decode("utf-8"))
    except Exception as e:
        raise ShelfError("GitHub doesn't answer (%s)" % getattr(e, "reason", e))
    if not isinstance(rels, list):
        raise ShelfError("GitHub: %s" % (rels.get("message") if isinstance(rels, dict) else "an odd answer"))
    spec, found = PRODUCTS[product], []
    main = re.compile(spec["main"])
    for r in rels:
        if r.get("draft"):
            continue
        names = [a["name"] for a in r.get("assets", [])]
        m = next((main.match(n) for n in names if main.match(n)), None)
        if not m:
            continue
        keep = [a for a in r["assets"] if any(re.match(p, a["name"]) for p in spec["assets"]) or a["name"] == "SHA256SUMS"]
        found.append({"tag": r["tag_name"], "version": m.group(1), "prerelease": bool(r.get("prerelease")),
                      "url": r.get("html_url", ""), "repo": repo,
                      "assets": [{"name": a["name"], "url": a["browser_download_url"], "size": a.get("size", 0),
                                  "sha256": (a.get("digest") or "").replace("sha256:", "") or None} for a in keep]})
    found.sort(key=lambda r: version_key(r["version"]), reverse=True)
    return found[0] if found else None


def fetch(product, channel, rel, progress=None, log=None, get=_get, env=None):
    """Takes a release onto the card's shelf: every file checked against its
    SHA-256 (GitHub's record, and SHA256SUMS when there is one), then read
    for what it is. Returns the copy; ShelfError (and nothing kept) if not."""
    log = log or (lambda s: None)
    sums = {}
    s_asset = next((a for a in rel["assets"] if a["name"] == "SHA256SUMS"), None)
    if s_asset:
        text = get(s_asset["url"], timeout=60).decode("utf-8", "replace")
        if s_asset["sha256"] and sha(text.encode("utf-8")) != s_asset["sha256"]:
            raise ShelfError("SHA256SUMS doesn't match GitHub's record of it")
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                sums[parts[-1].lstrip("*")] = parts[0].lower()
    want = [a for a in rel["assets"] if a["name"] != "SHA256SUMS"]
    total = sum(a.get("size") or 0 for a in want) or 1
    done, got = 0, {}
    for a in want:
        expect = [x for x in (a["sha256"], sums.get(a["name"])) if x]
        if not expect:
            raise ShelfError("%s has no SHA-256 to check it against: not taken" % a["name"])
        log("getting %s (%d KB)" % (a["name"], (a.get("size") or 0) // 1024))
        data = get(a["url"], timeout=300)
        h = sha(data)
        if any(h != x for x in expect):
            raise ShelfError("%s doesn't match its SHA-256: not taken" % a["name"])
        got[a["name"]] = data
        done += len(data)
        if progress:
            progress(min(99, done * 100 // total))
        log("  %s: SHA-256 checked" % a["name"])
    return put(product, channel, rel["tag"], rel["version"], rel.get("repo", ""), got, env=env, log=log)


def put(product, channel, tag, version, repo, files, env=None, log=None):
    """Writes a copy onto the card's shelf (after reading it for what it is),
    replacing that channel's older ones there."""
    check(product, files)
    d = os.path.join(card_shelf(env), product, channel)
    tmp = os.path.join(d, ".new-%s" % tag)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for n, data in files.items():
        with open(os.path.join(tmp, n), "wb") as f:
            f.write(data)
    meta = {"product": product, "channel": channel, "tag": tag, "version": version, "repo": repo,
            "files": {n: sha(data) for n, data in files.items()}, "fetched": time.strftime("%Y-%m-%d %H:%M")}
    with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    final = os.path.join(d, tag)
    shutil.rmtree(final, ignore_errors=True)
    os.rename(tmp, final)
    for old in os.listdir(d):
        if old not in (tag,) and not old.startswith("."):
            shutil.rmtree(os.path.join(d, old), ignore_errors=True)
    if log:
        log("on the shelf: %s" % final)
    return next(c for c in local(product, channel, env) if c["dir"] == final)


# -- what a file is -----------------------------------------------------------
def check(product, files):
    """Reads a product's files for what they are; ShelfError if they aren't."""
    main = re.compile(PRODUCTS[product]["main"])
    names = [n for n in files if main.match(n)]
    if not names:
        raise ShelfError("no %s file among them" % PRODUCTS[product]["short"])
    data = files[names[0]]
    if product == "stump":
        bundle_info(data)
        from . import packs
        for n, d in files.items():
            if n.endswith(".zip"):
                try:
                    packs.plan_from(packs.read_zip(io.BytesIO(d)))
                except packs.PackError as e:
                    raise ShelfError("%s: %s" % (n, e))
    elif product == "firefly":
        zip_version(data, "firefly/firefly/__init__.py", r'__version__\s*=\s*"([^"]+)"', "firefly/deploy/install.sh")
    elif product == "handheld":
        tar_version(data, "handheld/VERSION", "handheld/install.sh")
    elif product == "provisioner":
        tar_version(data, "VERSION", "install.sh", also="provisioner/__main__.py")


def bundle_info(data):
    """(release, micropython) of a Stump bundle, its files checked."""
    import gzip
    from . import stump
    try:
        raw = gzip.decompress(data)
        n = int.from_bytes(raw[:4], "little")
        head = json.loads(raw[4:4 + n])
        body = raw[4 + n:]
        for name, off, length, s in head["files"]:
            if sha(body[off:off + length]) != s:
                raise ShelfError("the bundle's %s doesn't match its SHA-256" % name)
    except ShelfError:
        raise
    except Exception:
        raise ShelfError("that isn't a Stump bundle")
    tpl = head.get("config_template", "")
    for s in stump.FORBIDDEN_IN_TEMPLATE:
        if s in tpl:
            raise ShelfError("the bundle's config template holds a real name or password")
    return head["release"], head.get("micropython", "")


def tar_version(data, version_path, need, also=None):
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
            names = t.getnames()
            top = names[0].split("/")[0] if names else ""
            for n in names:
                if n.startswith("/") or ".." in n.split("/"):
                    raise ShelfError("a path that climbs out in the tarball: %s" % n)
            for p in [need] + ([also] if also else []):
                if "%s/%s" % (top, p) not in names:
                    raise ShelfError("no %s in it" % p)
            f = t.extractfile("%s/%s" % (top, version_path))
            return f.read().decode("utf-8", "replace").strip() if f else ""
    except (tarfile.TarError, OSError, EOFError):
        raise ShelfError("that isn't a .tar.gz this can read")
    except KeyError:
        raise ShelfError("no %s in it" % version_path)


def zip_version(data, version_path, pattern, need):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            for n in names:
                if n.startswith("/") or ".." in n.split("/"):
                    raise ShelfError("a path that climbs out in the zip: %s" % n)
            if need not in names:
                raise ShelfError("no %s in it" % need)
            m = re.search(pattern, z.read(version_path).decode("utf-8", "replace"))
            return m.group(1) if m else ""
    except (zipfile.BadZipFile, OSError):
        raise ShelfError("that isn't a zip this can read")
    except KeyError:
        raise ShelfError("no %s in it" % version_path)


def from_file(product, path, max_bytes=64 * 1024 * 1024):
    """A copy from a file the user chose (+ From File): read for what it is,
    left where it is. {product, channel: "file", tag, version, files, dir}."""
    if not path.lower().endswith(PRODUCTS[product]["file"]):
        raise ShelfError("a %s is a %s file" % (PRODUCTS[product]["short"], " or ".join(PRODUCTS[product]["file"])))
    if os.path.getsize(path) > max_bytes:
        raise ShelfError("too big")
    with open(path, "rb") as f:
        data = f.read()
    if product == "stump":
        version = bundle_info(data)[0]
        files = {"Stump-%s.bundle" % version: path}
    elif product == "firefly":
        version = zip_version(data, "firefly/firefly/__init__.py", r'__version__\s*=\s*"([^"]+)"',
                              "firefly/deploy/install.sh")
        files = {"FireFly-RK3326-%s.zip" % version: path}             # by its release name, whatever the file's
    elif product == "handheld":
        version = tar_version(data, "handheld/VERSION", "handheld/install.sh")
        files = {"R36MAX-Stump-handheld-%s.tar.gz" % version: path}
    else:
        version = tar_version(data, "VERSION", "install.sh", also="provisioner/__main__.py")
        files = {"RK3326-Provisioner-%s.tar.gz" % version: path}
    return {"product": product, "channel": "file", "tag": "v" + version, "version": version, "files": files,
            "dir": os.path.dirname(path), "where": "file", "repo": path, "file": path}


def describe(copy):
    if not copy:
        return "none"
    return "%s %s" % (CHANNEL_NAMES.get(copy["channel"], copy["channel"]), copy["version"])
