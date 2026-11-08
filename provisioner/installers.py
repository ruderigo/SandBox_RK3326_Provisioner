"""Installing from a shelf copy (or a chosen file) on this handheld:
FireFly, the handheld's Stump's installer, and the Provisioner itself.

Each runs the product's own installer, as its README says to over SSH
(FireFly: firefly/deploy/install.sh; the Provisioner: install.sh), with
nothing read from the keyboard, its lines shown as it goes.
"""

import os
import re
import shutil
import subprocess
import tarfile
import zipfile

from . import shelf

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def cache(home=None):
    d = os.path.join(home or os.path.expanduser("~"), ".cache", "rk3326-provisioner")
    os.makedirs(d, exist_ok=True)
    return d


def stream(cmd, line, step=None, step_pat=r"^(?:>>> |== )(.+)", env=None, cwd=None, popen=subprocess.Popen):
    """Runs cmd, every line to line() (colours taken out), the ones that
    look like steps to step(). (exit code, last lines)."""
    tail, sp = [], re.compile(step_pat)
    try:
        p = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=cwd,
                  env=env, universal_newlines=True, bufsize=1, errors="replace")
    except OSError as e:
        return 127, ["couldn't run %s: %s" % (cmd[0], e)]
    for raw in p.stdout:
        s = ANSI.sub("", raw.rstrip("\n")).replace("\r", "").strip()
        if not s:
            continue
        line(s)
        tail = (tail + [s])[-6:]
        m = sp.match(s)
        if m and step:
            step(m.group(1))
    p.stdout.close()
    return p.wait(), tail


def _extract_tar(path, dest):
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    with tarfile.open(path, "r:gz") as t:
        for m in t.getmembers():
            if m.name.startswith("/") or ".." in m.name.split("/") or m.issym() or m.islnk():
                raise shelf.ShelfError("a path that climbs out in the tarball: %s" % m.name)
        t.extractall(dest, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    tops = os.listdir(dest)
    return os.path.join(dest, tops[0]) if len(tops) == 1 else dest


def _extract_zip(path, dest):
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.startswith("/") or ".." in n.split("/"):
                raise shelf.ShelfError("a path that climbs out in the zip: %s" % n)
        z.extractall(dest)
    return dest


# -- FireFly -------------------------------------------------------------------
def firefly_installed(home=None):
    """FireFly's version on this handheld (~/firefly), or ''."""
    p = os.path.join(home or os.path.expanduser("~"), "firefly", "firefly", "__init__.py")
    try:
        with open(p, encoding="utf-8") as f:
            m = re.search(r'__version__\s*=\s*"([^"]+)"', f.read())
        return m.group(1) if m else "?"
    except OSError:
        return ""


def firefly_install(copy, line, step, home=None):
    """FireFly's own installer from its zip (an update keeps its identity,
    contacts, messages and settings: ~/.firefly). (ok, message)."""
    z = shelf.main_file(copy)
    dest = os.path.join(cache(home), "firefly-new")
    try:
        root = _extract_zip(z, dest)
    except (shelf.ShelfError, zipfile.BadZipFile, OSError) as e:
        return False, "Couldn't unpack it: %s" % e
    inst = os.path.join(root, "firefly", "deploy", "install.sh")
    if not os.path.isfile(inst):
        return False, "No firefly/deploy/install.sh in it"
    step("FireFly's installer")
    rc, tail = stream(["bash", inst], line, step, cwd=os.path.dirname(inst))
    shutil.rmtree(dest, ignore_errors=True)
    if rc == 0:
        return True, ("FireFly %s is installed (Ports -> FireFly). Its identity, contacts and messages stay. "
                      "A first install: reboot once for the serial port." % copy["version"])
    err = next((s for s in reversed(tail) if s.startswith("ERROR")), "")
    return False, err or ("FireFly's installer stopped (%d): %s" % (rc, " / ".join(tail[-2:])))


# -- the handheld's Stump --------------------------------------------------------
def handheld_installer(copy, home=None):
    """R36MAX-Stump's handheld/install.sh from a shelf copy (or a file),
    unpacked: {path, repo, version, answers}."""
    name = {"official": "Official", "sandbox": "Sandbox"}.get(copy["channel"], "the file's")
    dest = os.path.join(cache(home), "handheld-%s" % copy["channel"])
    root = _extract_tar(shelf.main_file(copy), dest)
    path = os.path.join(root, "handheld", "install.sh")
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    return {"path": path, "repo": "%s R36MAX-Stump" % name, "version": copy["version"], "answers": "--answers" in text}


# -- the Provisioner itself ------------------------------------------------------
def app_dir():
    return shelf.HERE


def previous_dir(app=None):
    return (app or app_dir()).rstrip("/") + ".previous"


def version_in(d):
    try:
        with open(os.path.join(d, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return ""


def self_update_why(app=None):
    """Why the Provisioner can't replace itself here, or ''."""
    app = app or app_dir()
    if os.path.isdir(os.path.join(app, ".git")):
        return "It runs from a git clone here: update it with git pull, then install.sh"
    if not os.access(os.path.dirname(app.rstrip("/")) or "/", os.W_OK) or not os.access(app, os.W_OK):
        return "Its folder %s can't be written here" % app
    return ""


def self_update(copy, line, step, app=None, home=None):
    """Installs another Provisioner over this one by its own install.sh; the
    one running now is kept as <app>.previous (Go back puts it back)."""
    app = app or app_dir()
    why = self_update_why(app)
    if why:
        return False, why
    dest = os.path.join(cache(home), "provisioner-new")
    try:
        root = _extract_tar(shelf.main_file(copy), dest)
    except (shelf.ShelfError, tarfile.TarError, OSError) as e:
        return False, "Couldn't unpack it: %s" % e
    step("Keeping this one (v%s) to go back to" % version_in(app))
    prev = previous_dir(app)
    shutil.rmtree(prev, ignore_errors=True)
    shutil.copytree(app, prev, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "provisioner.log"))
    step("Installing v%s" % copy["version"])
    env = dict(os.environ, PROVISIONER_PULLED="1", PROVISIONER_APP=app)
    rc, tail = stream(["bash", os.path.join(root, "install.sh")], line, step, env=env, cwd=root)
    shutil.rmtree(dest, ignore_errors=True)
    if rc == 0 and version_in(app) == copy["version"]:
        return True, ("The Provisioner v%s is installed. Close this one (A) and open it again from Ports. "
                      "The one before stays, to go back to." % copy["version"])
    return False, "Its installer stopped (%d): %s. Go back puts v%s back." % (
        rc, " / ".join(tail[-2:]), version_in(prev))


def rollback(app=None):
    """Swaps this Provisioner and the previous one (so it can be swapped back). (ok, message)."""
    app = app or app_dir()
    prev = previous_dir(app)
    if not os.path.isfile(os.path.join(prev, "VERSION")):
        return False, "There's no previous Provisioner here"
    why = self_update_why(app)
    if why:
        return False, why
    swap = app.rstrip("/") + ".swap"
    shutil.rmtree(swap, ignore_errors=True)
    os.rename(app, swap)
    os.rename(prev, app)
    os.rename(swap, prev)
    return True, "The Provisioner v%s is back (v%s is kept as the previous one). Close this one and open it again " \
                 "from Ports." % (version_in(app), version_in(prev))


# -- what was installed from here --------------------------------------------------
def marks_path(home=None):
    return os.path.join(home or os.path.expanduser("~"), ".config", "rk3326-provisioner", "installed.json")


def marks(home=None):
    """{product: {version, channel, when}} of what the Provisioner installed here."""
    import json
    try:
        with open(marks_path(home), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def mark(product, copy, home=None):
    import json
    import time
    d = marks(home)
    d[product] = {"version": copy["version"], "channel": copy["channel"], "when": time.strftime("%Y-%m-%d %H:%M")}
    p = marks_path(home)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, sort_keys=True)
    except OSError:
        pass
