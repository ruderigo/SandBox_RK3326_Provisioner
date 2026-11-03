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
    if not inst and not any(os.path.isdir(r) for r in ("/roms", "/roms2", "/storage/roms")):
        return None                                     # not a handheld
    folder = os.path.join(home, STUMP)
    return {"installer": inst, "why": why, "folder": folder,
            "installed": os.path.isfile(os.path.join(folder, "stump_pc.py"))}


def form_defaults(here=None):
    here = here or {}
    return {"name": "" if here.get("none") else (here.get("name") or ""), "pw": "", "apw": "", "hotspot": "",
            "storage": "2048",
            "chain": "none", "parent": "", "secret": "", "heltec": "usb", "tavern": "no", "rnfs": "no"}


IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def current_passwords(folder, home=None):
    """Its passwords now, to send again when it's installed again (the wizard
    then rebuilds config.py from SandBox_Stump_On's): {pw: the one password
    (the fserv operator's), apw: a separate /admin one of its own, or ""}."""
    cfg = os.path.join(folder, "config.py")
    own = password_state(folder, "AUTH_ADMIN_PASSWORD", home) == "SET"
    op = _value_in(cfg, "FSERVBOT_OP_PASSWORD") or ""
    return {"pw": op if password_state(folder, "FSERVBOT_OP_PASSWORD", home) == "SET" else "",
            "apw": (_value_in(cfg, "AUTH_ADMIN_PASSWORD") or "") if own else ""}


def answers(a, folder, again=False, admin_state="SET", current=None):
    """The form's answers -> SandBox_Stump_On's wizard's answers file
    (`provisioner.py --pc --answers`: keys are its questions to their '?').
    {"error": why} when the form isn't complete."""
    name = (a.get("name") or "").strip()
    if not name:
        return {"error": "Its name is needed"}
    # Team Stump's design: one password, the fserv operator's, which /admin
    # takes too unless a separate one is set (stumpid check_admin_password).
    pw, apw = a.get("pw") or "", a.get("apw") or ""
    if again and current:                     # blank: its own, kept (sent again: the wizard rebuilds config.py)
        pw = pw or current.get("pw", "")
        apw = apw or current.get("apw", "")
    if not pw:
        return {"error": "Its password is needed (4+ characters): /admin and the fserv bot take it"}
    if not 4 <= len(pw) <= 64:
        return {"error": "Its password: 4 to 64 characters"}
    if apw and not 4 <= len(apw) <= 64:
        return {"error": "The separate /admin password: 4 to 64 characters"}
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
           # The one password: the fserv bot's operator's, and /admin's with the
           # separate one left blank. "Change any of those now?" yes, so the wizard
           # writes AUTH_ADMIN_PASSWORD (blank) instead of leaving SandBox_Stump_On's.
           "fserv bot operator password": pw, "change any of those now": True,
           "admin password for /admin": apw,
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


# -- its passwords ---------------------------------------------------------------
PASSWORDS = {"AUTH_ADMIN_PASSWORD": "separate /admin", "FSERVBOT_OP_PASSWORD": "fserv operator"}
# Team Stump's computer wizard leaves SandBox_Stump_On's final_firmware/config.py
# values in place where it doesn't ask: compared with that file (cloned by
# install.sh), so "still the repo's" is told apart from "its own".
REPO_CONFIG = os.path.join("SandBox_Stump_On", "final_firmware", "config.py")


def _value_in(path, key):
    import ast
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError, ValueError):
        return None
    found = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == key for t in node.targets):
            try:
                found = ast.literal_eval(node.value)
            except ValueError:
                found = None
    return found


def access_state(folder, home=None):
    """What /admin takes: SET (a password of its own: the separate one, or the
    fserv operator's), DEFAULT (SandBox_Stump_On's, left by the wizard), EMPTY
    (none: /admin can't be opened), NONE (no Stump)."""
    a = password_state(folder, "AUTH_ADMIN_PASSWORD", home)
    if a in ("NONE", "DEFAULT", "SET"):
        return a
    f = password_state(folder, "FSERVBOT_OP_PASSWORD", home)
    return "SET" if f == "SET" else ("DEFAULT" if f == "DEFAULT" else "EMPTY")


def password_state(folder, key="AUTH_ADMIN_PASSWORD", home=None):
    """SET (its own), DEFAULT (still SandBox_Stump_On's), EMPTY, or NONE (no Stump)."""
    cfg = os.path.join(folder, "config.py")
    if not os.path.isfile(cfg):
        return "NONE"
    v = _value_in(cfg, key)
    if not v:
        return "EMPTY"
    repo = _value_in(os.path.join(home or os.path.expanduser("~"), REPO_CONFIG), key)
    from . import stump
    known = [x.strip("'") for x in stump.FORBIDDEN_IN_TEMPLATE if x.startswith("'") or "_" in x]
    return "DEFAULT" if (repo and v == repo) or v in known else "SET"


SET_CODE = r"""
import json, os, shutil, sys
values = json.loads(sys.stdin.readline())
sys.path.insert(0, os.getcwd())
import settings
shutil.copy2("config.py", "config.py.bak")
if not settings.write_config(values, "config.py"):
    sys.exit("config.py wasn't written")
try:
    compile(open("config.py").read(), "config.py", "exec")
except SyntaxError:
    shutil.copy2("config.py.bak", "config.py")
    sys.exit("the new config.py wasn't Python: put back as it was")
print("SET")
"""


def write_values(folder, values, run=subprocess.run):
    """Writes values into its config.py with the Stump's own
    settings.write_config (what /admin uses; config.py.bak kept), by stdin:
    never on a command line or in a log. '' or why not."""
    py = os.path.join(folder, "venv", "bin", "python")
    if not os.path.isfile(os.path.join(folder, "config.py")) or not os.path.exists(py):
        return "No Stump in %s" % folder
    p = run([py, "-c", SET_CODE], input=json.dumps(values) + "\n", cwd=folder, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, universal_newlines=True)
    if "SET" not in (p.stdout or ""):
        return "Not set: %s" % ((p.stdout or "").strip()[-200:] or "the Stump's settings.py said no")
    return ""


def set_password(folder, key, pw, line, run=subprocess.run, home=None):
    """Sets one of its passwords, then restarts it. (ok, message). Its one
    password (the fserv operator's) also clears SandBox_Stump_On's
    AUTH_ADMIN_PASSWORD when the wizard left it, so /admin takes it."""
    if key not in PASSWORDS:
        return False, "not one of its passwords"
    if not 4 <= len(pw) <= 64:
        return False, "4 to 64 characters"
    values = {key: pw}
    if key == "FSERVBOT_OP_PASSWORD" and password_state(folder, "AUTH_ADMIN_PASSWORD", home) == "DEFAULT":
        values["AUTH_ADMIN_PASSWORD"] = ""
    why = write_values(folder, values, run)
    if why:
        return False, why
    line("its %s password is set (config.py.bak kept)" % PASSWORDS[key])
    return True, "Its %s password is set. %s" % (PASSWORDS[key], restart(line, run))


def clear_repo_admin(folder, line, run=subprocess.run, home=None):
    """The wizard left SandBox_Stump_On's AUTH_ADMIN_PASSWORD and its one
    password is set: cleared, so /admin takes that one. (changed, why not)."""
    if password_state(folder, "AUTH_ADMIN_PASSWORD", home) != "DEFAULT" or \
            password_state(folder, "FSERVBOT_OP_PASSWORD", home) != "SET":
        return False, ""
    why = write_values(folder, {"AUTH_ADMIN_PASSWORD": ""}, run)
    if not why:
        line("/admin takes its fserv operator password (SandBox_Stump_On's was left in config.py: cleared)")
    return not why, why


def restart(line, run=subprocess.run):
    """Restarts the handheld's Stump (its user service, or install.sh's system one)."""
    user = os.environ.get("USER") or ""
    for cmd in (["systemctl", "--user", "restart", "stump"], ["sudo", "-n", "systemctl", "restart", "stump-%s" % user]):
        try:
            p = run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if p.returncode == 0:
            line(" ".join(cmd))
            return "The Stump restarted with it."
    return "Restart the Stump for it to apply (Update does, or a reboot)."
