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
            "plugins": [], "card": [], "by_reader": [], "theme": spec.get("theme") or None,
            "names": [], "questions": []}
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
        plan["names"].append(pn)
        qs = questions_of(pn, ps)
        if qs["prompts"]:
            plan["questions"].append(qs)
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


# A plugin's setup questions (plugin.json "wizard", 1.0.0-beta.64), as Arborist
# takes them: only settings of its own (its name in capitals first), into
# config.py, never one of the Stump's (passwords, Wi-Fi, chain).
NEVER_KEYS = re.compile(r"^(AUTH_|WIFI_|CHAIN_|FSERVBOT_OP|NODE_NAME$|ADMIN|STUMP_)")


def questions_of(pn, ps):
    w = ps.get("wizard") if isinstance(ps.get("wizard"), dict) else {}
    own, out = pn.upper() + "_", {"plugin": pn, "prompts": [], "refused": []}
    for q in w.get("prompts") if isinstance(w.get("prompts"), list) else []:
        if not isinstance(q, dict) or not isinstance(q.get("key"), str):
            continue
        k = q["key"]
        if not re.match(r"^[A-Z][A-Z0-9_]{1,47}$", k) or not k.startswith(own) or NEVER_KEYS.match(k) or \
                (q.get("writes_to") or "config.py") != "config.py":
            out["refused"].append(k)
            continue
        kind = q.get("type") if q.get("type") in ("choice", "int") else "string"
        options = [str(o) for o in q.get("options") or []] if kind == "choice" else None
        if kind == "choice" and not options:
            options = [str(q.get("default", ""))]
        out["prompts"].append({"key": k, "prompt": str(q.get("prompt") or k), "type": kind, "options": options,
                               "default": q.get("default", 0 if kind == "int" else ""),
                               "min": q.get("min") if isinstance(q.get("min"), (int, float)) else None,
                               "max": q.get("max") if isinstance(q.get("max"), (int, float)) else None,
                               "advanced": bool(q.get("advanced"))})
    return out


def question_values(questions, current, answers=None):
    """The settings to write for a pack's questions (Arborist's packValues): a
    setting already on the board stays unless answered here; one not marked
    advanced, missing on the board, gets its answer or default. ({KEY: value}, error)."""
    answers, out = answers or {}, {}
    for g in questions:
        for q in g["prompts"]:
            k = q["key"]
            if k not in answers and (k in current or q["advanced"]):
                continue
            raw = answers.get(k, q["default"])
            if q["type"] == "choice":
                val = str(raw)
                if val not in q["options"]:
                    return {}, "%s: one of %s." % (k, ", ".join(q["options"]))
            elif q["type"] == "int":
                if not re.match(r"^-?\d+$", str(raw).strip()):
                    return {}, "%s: a whole number." % k
                val = int(str(raw).strip())
                if (q["min"] is not None and val < q["min"]) or (q["max"] is not None and val > q["max"]):
                    return {}, "%s: %s to %s." % (k, q["min"] if q["min"] is not None else "…",
                                                  q["max"] if q["max"] is not None else "…")
            else:
                val = str(raw)
                if len(val) > 200 or re.search(r"[\n\r]", val):
                    return {}, "%s: one line, 200 characters at most." % k
            if k in current and current[k] == val:
                continue
            out[k] = val
    return out, ""


def _current(repl, keys):
    """What the board's config.py has for these keys."""
    if not keys:
        return {}
    out = repl.run("import json\ntry:\n import config\n c={k:getattr(config,k) for k in json.loads(%s) "
                   "if hasattr(config,k)}\nexcept Exception:\n c={}\nprint('J'+json.dumps(c))\n"
                   % stump.py(json.dumps(keys)), 15)
    m = re.search(r"J(\{.*\})", out)
    try:
        return json.loads(m.group(1)) if m else {}
    except ValueError:
        return {}


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


def install(plan, open_link, step, progress, log, answers=None, builtins=None, result=None):
    """Puts a checked pack on a Stump (new, or an update: the same steps),
    recorded in each of its plugin folders; its questions' settings written
    where the board has none (answers: {KEY: value} given here). With
    builtins, result["installed"] gets the board's packs after. (ok, message)."""
    step("Connecting")
    repl = stump.ready_repl(open_link, log)
    try:
        if not stump.has_stump(repl):
            return False, "There's no Stump on this board (no config.py): make one first."
        _, err = question_values(plan["questions"], {}, answers)
        if err:
            return False, "%s: a setup question the pack gets wrong (%s). Nothing was copied." % (plan["name"], err)
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
        rec = json.dumps(record(plan)).encode("utf-8")
        stump.upload(repl, [(n + "/" + PACK_MARK, rec, sha(rec)) for n in plan["names"]])
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
        written = []
        if plan["questions"]:
            keys = [q["key"] for g in plan["questions"] for q in g["prompts"]]
            values, err = question_values(plan["questions"], _current(repl, keys), answers)
            if err:
                stump.restart(repl)                       # never left stopped
                return False, err
            if values:
                step("Its settings")
                stump.write_settings(repl, values)
                written = sorted(values)
        installed = None
        if builtins is not None:
            try:
                installed = board_packs(repl, builtins)
            except stump.StumpError as e:     # it's on the board (each file checked): only the list is missing
                log("its packs couldn't be listed after: %s" % e)
        step("Restarting it")
        stump.restart(repl)
    finally:
        repl.link.close()
    if result is not None:
        result["installed"] = installed
    msg = "%s %s is on the Stump; it starts now, with the Stump." % (plan["name"], plan["version"])
    if written:
        msg += " Set in its config.py: %s." % ", ".join(written)
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


# -- a board's packs (1.0.0-beta.75) ----------------------------------------------
# What a pack installs is recorded in each of its plugin folders (.from_pack,
# as Team Stump's provisioner.py and Arborist write it): which pack, which
# version, its Tools section, home files and theme, so it's updated and
# removed whole.
PACK_MARK = ".from_pack"
NOT_PACKS = ["rns", "sd", "__pycache__", "lib", "urns", "web", "peripherals"]


def record(plan):
    tools, home = set(), []
    for path in [p for p, _, _ in plan["card"]] + list(plan["by_reader"]):
        m = re.match(r"^tools/([^/]+)/", path)
        if m:
            tools.add("tools/" + m.group(1))
        elif path.startswith("home/"):
            home.append(path[5:])
    return {"pack": plan["name"], "version": str(plan["version"]), "plugins": list(plan["names"]),
            "theme": (plan["theme"] or {}).get("name") or None, "tools": sorted(tools), "home": sorted(home)}


def builtins_of(bundle):
    """The Stump's built-in plugins: the bundle says (1.0.0-beta.74 on), else
    from its files."""
    out = set(BUILTIN_ALWAYS) | set(known_names(bundle)["builtin"])
    if bundle and bundle.builtins:
        out |= set(bundle.builtins)
    return sorted(out)


BUILTIN_ALWAYS = ("fservbot", "stumpid")    # every Stump's own plugins, whatever copy is on the shelf


def board_packs(repl, builtins):
    """{plugin: its record, or None (installed before 1.0.0-beta.75, or by
    hand)} for the board's plugins that aren't built in."""
    skip = list(builtins or []) + NOT_PACKS
    m = stump.asked(repl,
        "import os,json\nout={}\nfor n in os.listdir():\n if n in %s:\n  continue\n ok=False\n"
        " for f in ('/install.py','/install.mpy'):\n  try:\n   os.stat(n+f)\n   ok=True\n  except OSError:\n   pass\n"
        " if not ok:\n  continue\n r=None\n try:\n  with open(n+'/%s') as f:\n   r=json.loads(f.read())\n"
        " except Exception:\n  pass\n out[n]=r\nprint('PACKS'+json.dumps(out))\n" % (json.dumps(skip), PACK_MARK),
        r"PACKS(\{.*\})", secs=30)
    try:
        found = json.loads(m.group(1))
    except ValueError:
        raise stump.StumpError("couldn't read its packs (its answer came back cut)")
    return dict((k, v if isinstance(v, dict) else None) for k, v in found.items())


def groups(found):
    """{plugin: record or None} -> [{name, plugins, record}], one per pack (a
    plugin with no record is its own)."""
    out, by = [], {}
    for pn in sorted(found):
        r = found[pn]
        if r and r.get("pack"):
            g = by.get(r["pack"])
            if g is None:
                g = by[r["pack"]] = {"name": str(r["pack"]), "plugins": [], "record": r}
                out.append(g)
            g["plugins"].append(pn)
        else:
            out.append({"name": pn, "plugins": [pn], "record": None})
    return out


def rows(available, found):
    """One row per pack, the ones here and the ones it has (Team Stump's
    pack_rows): {name, plan (here, or None), plugins, here (its version, ""
    if not recorded, None if not on it), record, state: new, same, update,
    yours (on it, not among the packs here)}."""
    gs, used, out = groups(found), set(), []
    for plan in sorted(available, key=lambda p: p["name"]):
        g = next((g for g in gs if g["name"] == plan["name"]
                  or (g["record"] is None and set(g["plugins"]) <= set(plan["names"]))), None)
        if g is None:
            out.append({"name": plan["name"], "plan": plan, "plugins": list(plan["names"]), "here": None,
                        "record": None, "state": "new"})
            continue
        used.add(id(g))
        here = str((g["record"] or {}).get("version", ""))
        out.append({"name": plan["name"], "plan": plan, "plugins": sorted(set(g["plugins"]) | set(plan["names"])),
                    "here": here, "record": g["record"], "state": "same" if here and here == plan["version"] else "update"})
    for g in gs:
        if id(g) not in used:
            out.append({"name": g["name"], "plan": None, "plugins": g["plugins"],
                        "here": str((g["record"] or {}).get("version", "")), "record": g["record"], "state": "yours"})
    return out


def keeps(row):
    """What a pack keeps besides its plugins (for "delete those too?"): its
    saved data, Tools sections, home files (paths on the card), its theme."""
    rec = row["record"] or (record(row["plan"]) if row.get("plan") else {})
    tools = [t for t in _list(rec.get("tools")) if TOOLS_PATH.match(t) and t not in ("tools/.", "tools/..")]
    home = ["home/" + h for h in _list(rec.get("home")) if _safe_rel(h)]
    theme = rec.get("theme") if isinstance(rec.get("theme"), str) and rec.get("theme") else None
    return ["plugins/" + p for p in _plugins(row)], tools, home, theme


# A record is read from the board: only a pack's own places on the card are
# taken from it (never the card itself, plugins/ or home/ whole).
TOOLS_PATH = re.compile(r"^tools/[A-Za-z0-9_.-]{1,64}$")


def _list(v):
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _safe_rel(p):
    parts = p.split("/")
    return 0 < len(p) <= 200 and all(x and x not in (".", "..") and "\\" not in x for x in parts)


def _plugins(row):
    return [p for p in row["plugins"] if isinstance(p, str) and re.match(r"^[a-z][a-z0-9_]{1,23}$", p)
            and p not in RESERVED and p not in BUILTIN_ALWAYS]


def keeps_text(row):
    data, tools, home, theme = keeps(row)
    out = ["its saved data"]
    if tools:
        out.append("its Tools page section%s" % ("s" if len(tools) > 1 else ""))
    if home:
        out.append("%d home file%s" % (len(home), "s" if len(home) > 1 else ""))
    if theme:
        out.append("its theme (%s)" % theme)
    return ", ".join(out)


def remove_from(repl, row, also):
    """A pack off the board: its plugin folders; with also, what it keeps too.
    How many paths went."""
    plugins = _plugins(row)
    data, tools, home, theme = keeps(row)
    code = ("import os\nn=0\ndef rm(p):\n global n\n try:\n  for e in os.listdir(p):\n   rm(p+'/'+e)\n  os.rmdir(p)\n"
            "  n+=1\n except OSError:\n  try:\n   os.remove(p)\n   n+=1\n  except OSError:\n   pass\n"
            "def rmfile(p):\n global n\n try:\n  os.remove(p)\n  n+=1\n except OSError:\n  pass\n"
            "for p in %s:\n rm(p)\n" % json.dumps(plugins))
    if also and (data or tools or home):                 # folders whole; home files one by one
        code += ("try:\n import fserv\n fserv.mount_sd()\nexcept Exception:\n pass\nfor p in %s:\n rm(%s+'/'+p)\n"
                 "for p in %s:\n rmfile(%s+'/'+p)\n"
                 % (json.dumps(data + tools), stump.py(CARD_ROOT), json.dumps(home), stump.py(CARD_ROOT)))
    if also and theme:
        code += ("import json\ntry:\n d=json.load(open('themes.json'))\n d.pop(%s,None)\n f=open('themes.json','w')\n"
                 " f.write(json.dumps(d))\n f.close()\nexcept Exception:\n pass\n" % stump.py(theme))
    out = repl.run(code + "print('GONE%d' % n)\n", 120)
    m = re.search(r"GONE(\d+)", out)
    return int(m.group(1)) if m else 0


def list_job(open_link, step, log, builtins):
    """Reads a board's packs. (ok, message, {plugin: record})."""
    step("Connecting")
    repl = stump.ready_repl(open_link, log)
    try:
        if not stump.has_stump(repl):
            return False, "There's no Stump on this board (no config.py): make one first.", None
        step("Reading its packs")
        found = board_packs(repl, builtins)
        step("Restarting it")
        stump.restart(repl)
    finally:
        repl.link.close()
    n = len(groups(found))
    return True, ("%d pack%s on this Stump." % (n, "" if n == 1 else "s")) if n else "No packs on this Stump.", found


def remove_job(row, also, open_link, step, log, builtins):
    """Removes a pack from a board. (ok, message, {plugin: record} after)."""
    step("Connecting")
    repl = stump.ready_repl(open_link, log)
    try:
        step("Removing %s" % row["name"])
        n = remove_from(repl, row, also)
        log("%d paths removed" % n)
        found = board_packs(repl, builtins)
        step("Restarting it")
        stump.restart(repl)
    finally:
        repl.link.close()
    if any(p in found for p in row["plugins"]):
        return False, "%s: not all of it could be removed." % row["name"], found
    return True, ("%s is off the Stump%s The Stump restarts." % (
        row["name"], ", with what it kept." if also else "; what it kept (its saved data) stays.")), found
