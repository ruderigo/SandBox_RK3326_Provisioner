"""Stump packs (Team Stump's plugins, a theme, files for the SD card), checked
and put on a Stump the way Arborist does it (SandBox_Stump_On
scripts/arborist/repl.js, packFrom and installPack), offline.

A pack is a zip from a Stump release (tavern-pack-1.1.zip, rnfs-pack-1.1.zip):
pack.json, one folder per plugin (each with plugin.json listing its files and
their hashes), and optionally tools/ and home/ for the card. Every file is
checked against its hash before anything is copied; one that doesn't match,
is missing, or has no hash refuses the whole pack. Plugins go on the board's
flash, tools/ and home/ on its SD card, the theme into themes.json. Plugin
settings keep their defaults (as Arborist does); /admin changes them.
"""

import hashlib
import json
import os
import re
import zipfile

from . import stump

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD_ROOT = "/sd"
CARD_MOUNT = "import fserv\nif not fserv.sd_ok:\n fserv.mount_sd()\n"
USB_MAX = 1000000                       # bigger files: by card reader (USB to the board is ~1 KB/s... per chunk)
RESERVED = ["urns", "lib", "peripherals", "web", "docs", "third_party", "tools_payload", "sd", "rns", "tls",
            "plugins_state", "boot", "main", "config"]


class PackError(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read_zip(path, max_bytes=64 * 1024 * 1024):
    """{name: bytes}. A path that climbs out (absolute, "..", "\\", ":")
    refuses the whole zip, as Arborist and Team Stump's Provisioner do."""
    out, total = {}, 0
    try:
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                name = info.filename
                if name.endswith("/"):
                    continue
                if name.startswith("/") or re.search(r"(^|/)\.\.(/|$)", name) or "\\" in name or ":" in name:
                    raise PackError("a path that climbs out in the zip: %s" % name)
                total += info.file_size
                if total > max_bytes:
                    raise PackError("too big to be a pack")
                out[name] = z.read(info)
    except zipfile.BadZipFile:
        raise PackError("that isn't a zip file")
    except (zipfile.LargeZipFile, NotImplementedError, RuntimeError) as e:
        raise PackError("a zip this can't read: %s" % e)
    return out


def known_names(bundle):
    """The Stump's own modules (a pack's plugin can't take their names) and
    its built-in plugins (nor theirs), from the bundle's files."""
    core, dirs, builtin = set(), set(), set()
    for n in (bundle.files if bundle else {}):
        m = re.match(r"^app/([^/]+)$", n)
        if m:
            core.add(re.sub(r"\.(py|mpy)$", "", m.group(1)))
        m = re.match(r"^app/([^/]+)/(.+)$", n)
        if m:
            dirs.add(m.group(1))
            if re.match(r"^install\.(py|mpy)$", m.group(2)):
                builtin.add(m.group(1))
    core |= dirs - builtin
    return {"core": sorted(core), "builtin": sorted(builtin)}


def plan_from(zipped, known=None):
    """A pack's zip contents -> a plan, or PackError with why.
    plan: {name, version, author, license, description, credits, plugins:
    [(path, bytes, sha256)] for the flash, card: [...] for the SD card,
    by_reader: [card paths too big for USB], theme}."""
    names = list(zipped)
    base = None
    for n in names:
        m = re.match(r"^(?:([^/]+)/)?pack\.json$", n)
        if m and (base is None or not m.group(1)):
            base = m.group(1) + "/" if m.group(1) else ""
    if base is None:
        raise PackError("No pack.json in that zip: it isn't a Stump pack.")
    try:
        spec = json.loads(zipped[base + "pack.json"].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise PackError("Its pack.json won't read.")
    miss = [k for k in ("name", "version", "author", "license") if not spec.get(k)]
    if miss:
        raise PackError("Its pack.json has no %s." % ", ".join(miss))
    if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", str(spec["name"])):
        raise PackError("The pack's name isn't a plain name.")
    known = known or {}
    plan = {"name": spec["name"], "version": str(spec["version"]), "author": spec["author"],
            "license": spec["license"], "description": spec.get("description", ""),
            "credits": spec.get("credits", ""), "stump_api": int(spec.get("stump_api", 1)),
            "plugins": [], "card": [], "by_reader": [], "theme": spec.get("theme") or None}
    for pn in spec.get("plugins") or []:
        if not isinstance(pn, str) or not re.match(r"^[a-z][a-z0-9_]{1,23}$", pn):
            raise PackError("A plugin's name is 2-24 lowercase letters, digits or _.")
        if pn in RESERVED or pn in known.get("core", ()):
            raise PackError("%s is a part of the Stump's own code: a pack can't replace it." % pn)
        if pn in known.get("builtin", ()):
            raise PackError("%s is a built-in plugin: a pack can't replace it." % pn)
        pj = zipped.get(base + pn + "/plugin.json")
        if pj is None:
            raise PackError("%s: no plugin.json." % pn)
        want = (spec.get("plugin_hashes") or {}).get(pn)
        if not want or sha(pj)[:16] != want:
            raise PackError("%s/plugin.json doesn't match the pack's hash." % pn)
        try:
            ps = json.loads(pj.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise PackError("%s/plugin.json won't read." % pn)
        hashes = ps.get("hashes") or {}
        if isinstance(ps.get("files"), list) and ps["files"]:
            files = [f for f in ps["files"] if isinstance(f, str) and f.startswith(pn + "/")
                     and not re.search(r"(^|/)\.\.?(/|$)", f) and (base + f) in zipped]
        else:
            files = [n[len(base):] for n in names if n.startswith(base + pn + "/")
                     and not re.search(r"__pycache__|\.(pyc|bak|orig|swp)$|\.DS_Store$", n)]
        for f in files:
            if f == pn + "/plugin.json":
                continue
            if not hashes.get(f):
                raise PackError("%s has no hash in its plugin.json." % f)
            if sha(zipped[base + f])[:16] != hashes[f]:
                raise PackError("%s changed since it was hashed: not installed." % f)
        for f in hashes:
            if (base + f) not in zipped:
                raise PackError("%s is missing from the pack." % f)
        for f in files:
            if re.search(r"(^|/)plugin\.json$", f) or f.endswith(".md"):
                continue                                  # not for the board
            d = zipped[base + f]
            plan["plugins"].append((f, d, sha(d)))
    pack_hashes = spec.get("hashes") or {}
    for sub in ("tools", "home"):
        if spec.get(sub) is False:
            continue
        pre = base + sub + "/"
        here = sorted(n for n in names if n.startswith(pre) and "/" not in n[len(pre):]
                      and not n[len(pre):].startswith("."))
        for n in here:
            rel, fname, data = n[len(base):], n[len(pre):], zipped[n]
            if not pack_hashes.get(rel):
                raise PackError("%s has no hash in the pack.json." % rel)
            if sha(data)[:16] != pack_hashes[rel]:
                raise PackError("%s changed since the pack was hashed: not installed." % rel)
            dest = ("tools/%s/%s" % (spec["name"], fname)) if sub == "tools" else ("home/" + fname)
            if len(data) > USB_MAX:
                plan["by_reader"].append(dest)
            else:
                plan["card"].append((dest, data, sha(data)))
    return plan


def plan_file(path, known=None):
    return plan_from(read_zip(path), known)


def bundled(d=None):
    """[(path, plan or None, error or None)] for the packs next to the Stump
    the boards get (a shelf copy: the packs of that release)."""
    out = []
    if d is None:
        c = stump.default_copy()
        if not c:
            return out
        d = c["dir"]
    try:
        names = sorted(f for f in os.listdir(d) if f.endswith(".zip") and "-pack-" in f)
    except OSError:
        return out
    known = known_names(stump.find_bundle(d))
    for f in names:
        p = os.path.join(d, f)
        try:
            out.append((p, plan_file(p, known), None))
        except PackError as e:
            out.append((p, None, str(e)))
    return out


def summary(plan):
    flash = sum(len(d) for _, d, _ in plan["plugins"])
    card = sum(len(d) for _, d, _ in plan["card"])
    bits = ["%d KB for the board" % max(1, flash // 1024)]
    if card:
        bits.append("%d KB for its SD card" % max(1, card // 1024))
    if plan["theme"]:
        bits.append("a theme")
    return ", ".join(bits)


def install(plan, open_link, step, progress, log):
    """Puts a checked pack on a Stump. (ok, message)."""
    step("Connecting")
    repl = stump.ready_repl(open_link, log)
    try:
        if not stump.has_stump(repl):
            return False, "There's no Stump on this board (no config.py): make one first."
        api = plan.get("stump_api", 1)
        have = _plugin_api(repl)
        if have < api:
            return False, ("%s needs the Stump's plugin API %d; this Stump has %s: update its Stump first."
                           % (plan["name"], api, have or "none"))

        def prog(done, total, path):
            progress(int(done * 100 / max(1, total)))
        if plan["plugins"]:
            step("Copying %s %s to the board" % (plan["name"], plan["version"]))
            stump.upload(repl, plan["plugins"], prog)
        no_card = False
        if plan["card"]:
            step("Copying its files to the SD card")
            out = repl.run(CARD_MOUNT + "import os\ntry:\n os.stat(%s)\n print('HASCARD')\nexcept OSError:\n pass\n"
                           % stump.py(CARD_ROOT), 30)
            if "HASCARD" in out:
                stump.upload(repl, [(CARD_ROOT + "/" + p, d, s) for p, d, s in plan["card"]], prog)
            else:
                # Best effort, as Team Stump's provisioner: the plugins run without them
                # (Bavard plays its built-in scene), and the Stump is restarted all the same.
                no_card = True
                log("no SD card: its files for the card skipped")
        if plan["theme"] and plan["theme"].get("name"):
            step("Adding its theme")
            out = repl.run("import json\ntry:\n d=json.load(open('themes.json'))\nexcept Exception:\n d={}\n"
                           "print('TH'+json.dumps(d))\n")
            m = re.search(r"TH(\{.*\})", out)
            try:
                cur = json.loads(m.group(1)) if m else {}
            except ValueError:
                cur = {}
            t = plan["theme"]
            cur[t["name"]] = {"label": t.get("label") or t["name"], "colors": t.get("colors") or {}}
            data = json.dumps(cur, ensure_ascii=False).encode("utf-8")
            stump.upload(repl, [("themes.json", data, sha(data))])
        step("Restarting it")
        stump.restart(repl)
    finally:
        repl.link.close()
    msg = "%s %s is on the Stump; it starts now, with the Stump." % (plan["name"], plan["version"])
    if no_card:
        msg += (" No SD card in it (or it can't be read), so its files for the card (%d KB) aren't there: "
                "add a card and install it again for them." % (sum(len(d) for _, d, _ in plan["card"]) // 1024))
    if plan["by_reader"]:
        msg += " Too big for USB, copy by card reader: %s." % ", ".join(plan["by_reader"])
    return True, msg


def _plugin_api(repl):
    """The plugin API the board's Stump offers (plugins.API_VERSION), 0 if none."""
    out = repl.run("try:\n import plugins\n print('API', getattr(plugins, 'API_VERSION', 0))\n"
                   "except Exception:\n print('API 0')\n")
    m = re.search(r"API (\d+)", out)
    return int(m.group(1)) if m else 0
