"""Installing the Provisioner itself from a shelf copy (or a chosen file):
its own install.sh, as its README says to over SSH, with nothing read from
the keyboard, its lines shown as it goes; and going back to the one before.

(The handheld's Stump and FireFly install and update themselves.)
"""

import contextlib
import os
import re
import shutil
import subprocess
import tarfile
import tempfile

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


# -- sudo ----------------------------------------------------------------------
# Its installer uses sudo (the serial rule, the Ports entry). Over SSH it asks
# in the terminal; from here nobody could answer, so the password is typed on
# the Provisioner's screen and given to sudo through its askpass helper
# (`sudo -A`): a script printing a file only this user can read, both in a
# folder of their own, removed when the installer ends. Never piped into
# sudo -S, never logged, never on a command line.
ASKPASS_SCRIPT = '#!/bin/sh\ncat "$PROVISIONER_ASKPASS_FILE"\n'


def sudo_ok(run=subprocess.run):
    """True when sudo needs no password now (root, NOPASSWD, a ticket)."""
    if os.geteuid() == 0:
        return True
    try:
        return run(["sudo", "-n", "true"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@contextlib.contextmanager
def askpass(password, home=None):
    """The environment for an installer: sudo's askpass helper with this
    password ({} without one). Its files are gone once the block ends."""
    if not password:
        yield {}
        return
    d = tempfile.mkdtemp(prefix="askpass-", dir=cache(home))
    try:
        os.chmod(d, 0o700)
        helper, secret = os.path.join(d, "askpass"), os.path.join(d, "pw")
        fd = os.open(helper, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "w") as f:
            f.write(ASKPASS_SCRIPT)
        fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(password + "\n")
        yield {"SUDO_ASKPASS": helper, "PROVISIONER_ASKPASS_FILE": secret}
    finally:
        shutil.rmtree(d, ignore_errors=True)


# -- the Provisioner itself --------------------------------------------------------
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


def self_update_needs_password(copy, app=None, home=None):
    """True when the new Provisioner's install.sh would ask sudo for a
    password (its udev rule or Ports entry changed, and sudo has no ticket)."""
    dest = os.path.join(cache(home), "provisioner-check")
    try:
        root = _extract_tar(shelf.main_file(copy), dest)
        p = subprocess.run(["bash", os.path.join(root, "install.sh"), "--needs-sudo"], cwd=root,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           universal_newlines=True, timeout=60,
                           env=dict(os.environ, PROVISIONER_PULLED="1", PROVISIONER_APP=app or app_dir()))
        return p.stdout.strip().endswith("yes")
    except (shelf.ShelfError, tarfile.TarError, OSError, subprocess.TimeoutExpired):
        return False
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def self_update(copy, line, step, app=None, home=None, password=None):
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
    with askpass(password, home) as pw_env:
        env = dict(os.environ, PROVISIONER_PULLED="1", PROVISIONER_APP=app, **pw_env)
        rc, tail = stream(["bash", os.path.join(root, "install.sh")], line, step, env=env, cwd=root)
    shutil.rmtree(dest, ignore_errors=True)
    if rc == 0 and version_in(app) == copy["version"]:
        return True, ("The Provisioner v%s is installed. Close this one (A) and open it again (Ports, or the dock). "
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
                 "(Ports, or the dock)." % (version_in(app), version_in(prev))
