"""This handheld's own Stump: installed, updated and checked from the
Provisioner, with the gamepad.

The handheld's Stump is Team Stump's computer Stump (SandBox_Stump_On's
`provisioner.py --pc`), set up by R36MAX-Stump's `handheld/install.sh`
(SandBox_RK3326_Stump while it's being tried): packages, the Stump in
~/Stump, its walk-up extras, the cockpit. From v2.3.0-r36max that installer
takes the wizard's answers from a file (`install.sh --answers FILE.json`),
and this module writes that file from the Provisioner's form and runs it.

ArkOS / dArkOS only (apt, NetworkManager, the user ark with sudo). The first
install needs internet; an update without it keeps what's there.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

REPOS = ["SandBox_RK3326_Stump", "R36MAX-Stump"]       # where install.sh may be, in ~ (the sandbox first)
STUMP = "Stump"                                        # ~/Stump: the handheld's Stump (install.sh's default)
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
GET = ("git clone -b answers https://github.com/ruderigo/SandBox_RK3326_Stump ~/SandBox_RK3326_Stump")


def find_installer(home=None):
    """{path, repo, version, answers} of the handheld's installer on this
    handheld (one that takes answers first), or None."""
    home = home or os.path.expanduser("~")
    found = []
    for repo in REPOS:
        path = os.path.join(home, repo, "handheld", "install.sh")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        try:
            with open(os.path.join(home, repo, "handheld", "VERSION")) as f:
                version = f.read().strip()
        except OSError:
            version = "?"
        found.append({"path": path, "repo": repo, "version": version, "answers": "--answers" in text})
    found.sort(key=lambda i: not i["answers"])
    return found[0] if found else None


def system_why(home=None, euid=None, which=shutil.which):
    """Why this system can't have the handheld's Stump installed from here, or ''."""
    euid = os.geteuid() if euid is None else euid
    if euid == 0:
        return "Runs as root here (AmberELEC, ROCKNIX?): the handheld's Stump installs on ArkOS / dArkOS, as ark"
    if not which("apt-get"):
        return "Needs ArkOS or dArkOS (apt): this system has none"
    return ""


def state(home=None, euid=None, which=shutil.which):
    """What the BOARDS screen's row shows: {installer, why, installed, folder},
    or None where it has no place (not a handheld: no installer, no apt)."""
    home = home or os.path.expanduser("~")
    inst = find_installer(home)
    why = system_why(home, euid, which)
    if not inst and (why or not (os.path.isdir("/roms") or os.path.isdir("/roms2"))):
        return None
    folder = os.path.join(home, STUMP)
    return {"installer": inst, "why": why, "folder": folder,
            "installed": os.path.isfile(os.path.join(folder, "stump_pc.py"))}


def form_defaults(here=None):
    here = here or {}
    return {"name": "" if here.get("none") else (here.get("name") or ""), "hotspot": "", "storage": "2048",
            "chain": "none", "parent": "", "secret": "", "heltec": "usb", "tavern": "no", "rnfs": "no"}


IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def answers(a, folder, again=False):
    """The form's answers -> SandBox_Stump_On's wizard's answers file
    (`provisioner.py --pc --answers`: keys are its questions to their '?').
    {"error": why} when the form isn't complete."""
    name = (a.get("name") or "").strip()
    if not name:
        return {"error": "Its name is needed"}
    try:
        mb = int(a.get("storage") or 2048)
    except ValueError:
        return {"error": "Storage is a number of MB"}
    if not 64 <= mb <= 1024 * 1024:
        return {"error": "Storage: 64 MB or more"}
    out = {"folder for this stump": folder, "node name": name,
           "the wi-fi name visitors join": (a.get("hotspot") or "").strip() or name,
           "storage for this stump, in mb": str(mb),
           "is this stump part of a chain": a.get("chain") in ("first", "member"),
           "the heltec": {"usb": "Plugged into this computer by USB", "ble": "Over Bluetooth",
                          "none": "None"}[a.get("heltec") or "usb"],
           "install rnfs": a.get("rnfs") == "yes", "install tavern": a.get("tavern") == "yes",
           "start this stump automatically when you log in": True,
           # Questions with no default of their own (the --answers-template values)
           "identity requirement": "open", "how should file sharing work": "Free", "theme": "Amber",
           # The chain check after a new chain: carry on (the installer checks the Stump at its end)
           "fix it, then check again": False}
    if again:
        out["change something"] = "a"                   # an existing Stump: all the questions again
    if a.get("heltec") == "usb":
        out["its usb port"] = "auto"
    if a.get("chain") == "first":
        out["its place in the chain"] = "The first"
        out["chain secret"] = a.get("secret") or ""
    elif a.get("chain") == "member":
        ip = (a.get("parent") or "").strip()
        m = IPV4.match(ip)
        if not m or not all(0 <= int(x) <= 255 for x in m.groups()):
            return {"error": "The Stump it joins: its address, like 192.168.1.20"}
        out["its place in the chain"] = "Joins another"
        out["how does this computer reach that stump"] = "On the Wi-Fi"
        out["that stump's address"] = ip
        out["chain secret"] = a.get("secret") or ""
    return out


def update_answers(folder):
    """An update: everything kept (a Heltec plugged in since isn't taken up)."""
    return {"folder for this stump": folder, "change something": "", "use it for this stump": False,
            "use a heltec over bluetooth instead": False, "fix it, then check again": False}


def run(installer, ans, line, step, home=None, popen=subprocess.Popen):
    """Runs `install.sh --answers FILE` (the file only lives while it runs:
    it may hold the chain's secret). (ok, message)."""
    home = home or os.path.expanduser("~")
    d = os.path.join(home, ".cache", "rk3326-provisioner")
    os.makedirs(d, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="stump-answers-", suffix=".json", dir=d)
    up, last_x, tail = "", "", []
    try:
        with os.fdopen(fd, "w") as f:                  # mkstemp: 0600
            json.dump(ans, f)
        try:
            p = popen(["bash", installer["path"], "--answers", path], stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=os.path.dirname(installer["path"]),
                      universal_newlines=True, bufsize=1, errors="replace")
        except OSError as e:
            return False, "Couldn't run %s: %s" % (installer["path"], e)
        for raw in p.stdout:                         # closed below
            s = ANSI.sub("", raw.rstrip("\n")).replace("\r", "").strip()
            if not s:
                continue
            line(s)
            tail = (tail + [s])[-4:]
            if s.startswith(">>> "):
                step(s[4:])
            elif s.startswith("[x] "):
                last_x = s[4:]
            elif s.startswith("✓ Stump up: "):
                up = s[len("✓ Stump up: "):]
        p.stdout.close()
        rc = p.wait()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if rc == 0:
        if up:
            return True, "The Stump is up: %s. Its cockpit: Ports -> LaBuche_Stump." % up
        return True, "Installed, but the Stump isn't answering yet: see ~/Stump/stump.log."
    return False, last_x or ("The installer stopped (%d): %s" % (rc, " / ".join(tail[-2:])))
