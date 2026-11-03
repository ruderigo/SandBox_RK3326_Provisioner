#!/usr/bin/env python3
"""Takes the Stump a SandBox_Stump_On release ships, for the Provisioner to
put on boards offline.

    python3 scripts/fetch_stump_bundle.py v1.0.0-beta.48 [--from FILE --sums SHA256SUMS]

Since 1.0.0-beta.48 each SandBox_Stump_On release has
Stump-<release>.bundle (asked by this team): one file, built by Team Stump's
CI, holding MicroPython (pinned by SHA-256 in their build), the Stump
compiled for it, a config.py template with every name, password and Wi-Fi
taken out, and the default Wi-Fi name. Older releases carry the same bundle
inside Arborist-<release>.html, which is used for them. This script:

  1. downloads the bundle (or the page) and the release's SHA256SUMS (from
     GitHub; or takes them from --from / --sums), and checks it against them;
  2. checks every file in the bundle against its SHA-256, and the template
     against the names and passwords that must never be in it;
  3. writes firmware/stump/stump-<release>.bundle (the bundle as Team
     Stump built it, unchanged) and stump-<release>.json (where it came
     from, its hashes), replacing older ones.

Nothing is rebuilt here: what goes on a board is what Team Stump released.
"""
import base64
import gzip
import hashlib
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "firmware", "stump")
REPO = "ruderigo/SandBox_Stump_On"
# Never in a template (a real Stump's names and passwords).
FORBIDDEN = ("Bob's Glitch", "SalutComment", "TeK_Knoh", "'TeK'", "'LaBuche'", "Concierge")


def unpack(blob):
    raw = gzip.decompress(blob)
    n = int.from_bytes(raw[:4], "little")
    head = json.loads(raw[4:4 + n])
    body = raw[4 + n:]
    return head, body


def check_bundle(blob):
    """(head, files {name: bytes}) or SystemExit with why."""
    head, body = unpack(blob)
    files = {}
    for name, off, length, sha in head["files"]:
        data = body[off:off + length]
        if len(data) != length or hashlib.sha256(data).hexdigest() != sha:
            raise SystemExit("bundle: %s doesn't match its SHA-256" % name)
        files[name] = data
    mp = files.get("micropython.bin")
    if not mp or mp[:1] != b"\xe9" or hashlib.sha256(mp).hexdigest() != head.get("micropython_sha256"):
        raise SystemExit("bundle: no MicroPython image, or not the one its build pinned")
    tpl = head.get("config_template", "")
    for k in ("NODE_NAME", "WIFI_SSID", "WIFI_PASS", "AUTH_ADMIN_PASSWORD", "FSERVBOT_OP_PASSWORD"):
        if "\n%s = ''\n" % k not in tpl:
            raise SystemExit("bundle: the template's %s isn't empty" % k)
    for s in FORBIDDEN:
        if s in tpl:
            raise SystemExit("bundle: the template still holds %r" % s)
    compile(tpl, "config.py", "exec")
    if not any(n.startswith("app/") for n in files):
        raise SystemExit("bundle: no Stump files in it")
    return head, files


def from_page(page):
    m = re.search(r'<script type="application/octet-stream" id="payload">([A-Za-z0-9+/=\s]+)</script>', page)
    if not m:
        raise SystemExit("that page has no Stump bundle in it")
    blob = base64.b64decode(m.group(1))
    ssid = re.search(r'var SSID = "([^"]*)";', page)
    return blob, (ssid.group(1) if ssid else "")


def gh_asset(tag, name):
    """A release asset's bytes, by GitHub's public download URL."""
    url = "https://github.com/%s/releases/download/%s/%s" % (REPO, tag, name)
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main(argv):
    if not argv or argv[0].startswith("-"):
        raise SystemExit(__doc__)
    tag = argv[0]
    rel = tag[1:] if tag.startswith("v") else tag
    args = dict(zip(argv[1::2], argv[2::2]))
    sums = open(args["--sums"], encoding="utf-8").read() if "--sums" in args else gh_asset(tag, "SHA256SUMS").decode()
    listed = [l.split()[-1].lstrip("*") for l in sums.splitlines() if l.strip()]
    # The bundle file (beta.48 on), else the Arborist page that carries it.
    src_name = "Stump-%s.bundle" % rel
    if src_name not in listed:
        src_name = "Arborist-%s.html" % rel
    if "--from" in args:
        src_name = os.path.basename(args["--from"])
        data = open(args["--from"], "rb").read()
    else:
        data = gh_asset(tag, src_name)
    want = next((l.split()[0] for l in sums.splitlines() if l.strip().endswith(src_name)), None)
    got = hashlib.sha256(data).hexdigest()
    if want != got:
        raise SystemExit("%s: SHA-256 %s, the release says %s" % (src_name, got, want))
    if src_name.endswith(".bundle"):
        blob = data
        head, files = check_bundle(blob)
        ssid = head.get("default_ssid", "")
    else:
        blob, ssid = from_page(data.decode("utf-8"))
        head, files = check_bundle(blob)
    if head["release"] != rel:
        raise SystemExit("the page holds %s, not %s" % (head["release"], rel))
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.startswith("stump-"):
            os.remove(os.path.join(OUT, f))
    path = os.path.join(OUT, "stump-%s.bundle" % rel)
    with open(path, "wb") as f:
        f.write(blob)
    meta = {"release": rel, "source": "https://github.com/%s/releases/tag/%s" % (REPO, tag),
            "taken_from": src_name, "taken_from_sha256": got, "bundle_sha256": hashlib.sha256(blob).hexdigest(),
            "micropython": head["micropython"], "micropython_sha256": head["micropython_sha256"],
            "mpy": head.get("mpy"), "default_ssid": ssid,
            "files": len([n for n in files if n.startswith("app/")]),
            "app_bytes": sum(len(d) for n, d in files.items() if n.startswith("app/"))}
    with open(os.path.join(OUT, "stump-%s.json" % rel), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
        f.write("\n")
    print("firmware/stump/stump-%s.bundle: %d files, MicroPython %s, %d KB" % (
        rel, meta["files"], meta["micropython"], len(blob) // 1024))


if __name__ == "__main__":
    main(sys.argv[1:])
