"""A Stump's identity kept in a file (SandBox_Stump_On 1.0.0-beta.76): its
Reticulum keys and its propagation mailbox's, as Team Stump's provisioner.py
and Arborist write them (<its name>.stump-identity, JSON, the files in
base64). Saved from a CAM, brought back onto one (the identity it had saved
first), read from a keepsake or an old Stump's folder. Only the identity:
settings are typed again. No passphrase: whoever has the file can be that
Stump on the mesh, so it's written for its owner only.
"""

import base64
import binascii
import hashlib
import json
import os
import re
import time

from . import stump

IDENTITY_FILES = ("rns/identity", "pn_mailbox_identity")   # its address; its mailbox's (propagation)
EXT = ".stump-identity"
NOTE = ("A Stump's identity: whoever has this file can be that Stump on the mesh. "
        "Keep it safe, and don't share it.")


class IdentityError(Exception):
    pass


def whole(files):
    return bool(files) and len(files.get("rns/identity") or b"") == 64


def fingerprint(files):
    h = hashlib.sha256(files["rns/identity"]).hexdigest()[:16]
    return " ".join(h[i:i + 4] for i in range(0, 16, 4))


def keepsake_bytes(files, name, release=""):
    return (json.dumps({"stump_identity": 1, "name": name or "", "saved": time.strftime("%Y-%m-%d"),
                        "release": release or "", "fingerprint": fingerprint(files), "note": NOTE,
                        "files": dict((k, base64.b64encode(v).decode()) for k, v in sorted(files.items()))},
                       indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def file_name(name):
    return (re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "Stump").strip(" .") or "Stump") + EXT


def save(files, name, where, release=""):
    """Writes the keepsake, for its owner only. where: a folder (the file
    named after the Stump, never over another one) or a file. Its path."""
    path = where
    if os.path.isdir(where):
        path = os.path.join(where, file_name(name))
        base, k = path[:-len(EXT)], 2
        while os.path.exists(path):
            path, k = "%s (%d)%s" % (base, k, EXT), k + 1
    data = keepsake_bytes(files, name, release)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _folder_name(folder):
    try:
        with open(os.path.join(folder, "config.py"), encoding="utf-8", errors="replace") as f:
            m = re.search(r'^NODE_NAME\s*=\s*([\'"])(.*?)\1', f.read(), re.M)
        return m.group(2) if m else None
    except OSError:
        return None


def read_source(src):
    """A keepsake file, or an old Stump's folder: ({path: bytes}, its name).
    IdentityError, with why, for anything else."""
    src = os.path.expanduser(str(src).strip())
    if os.path.isdir(src):
        files = {}
        for rel in IDENTITY_FILES:
            try:
                with open(os.path.join(src, rel), "rb") as f:
                    files[rel] = f.read()
            except OSError:
                pass
        if not whole(files):
            raise IdentityError("%s has no Stump identity in it (rns/identity)." % os.path.basename(src.rstrip("/")))
        return files, _folder_name(src)
    try:
        if os.path.getsize(src) > 64 * 1024:
            raise IdentityError("That file isn't a saved Stump identity.")
        with open(src, encoding="utf-8") as f:
            d = json.load(f)
    except OSError:
        raise IdentityError("No file or folder there.")
    except (ValueError, UnicodeDecodeError):
        raise IdentityError("That file isn't a saved Stump identity.")
    if not isinstance(d, dict) or d.get("stump_identity") != 1 or not isinstance(d.get("files"), dict):
        raise IdentityError("That file isn't a saved Stump identity.")
    try:
        files = dict((k, base64.b64decode(v, validate=True)) for k, v in d["files"].items() if k in IDENTITY_FILES)
    except (ValueError, TypeError, binascii.Error):
        raise IdentityError("That file is damaged: its identity won't read.")
    if not whole(files):
        raise IdentityError("That file is damaged: its identity isn't whole.")
    return files, (d.get("name") or None) if isinstance(d.get("name"), str) else None


# -- on a board ------------------------------------------------------------------
def board_read(repl, tries=2):
    """{path: bytes} of the board's identity, or None (it makes one as it
    first starts). Each file comes with its size and SHA-256 from the board
    and the copy is checked against them (Team Stump's beta.84), read again
    once: one that won't read whole is never taken for "none"."""
    code = ("import binascii,json,hashlib\nd={}\nfor p in %s:\n try:\n  b=open(p,'rb').read()\n"
            "  d[p]=[binascii.b2a_base64(b).decode().strip(),len(b),binascii.hexlify(hashlib.sha256(b).digest()).decode()]\n"
            " except OSError:\n  pass\nprint('ID'+json.dumps(d))\n" % json.dumps(list(IDENTITY_FILES)))
    for n in range(tries):
        try:                                  # whole (its length and checksum), or asked again
            got = stump.asked_json(repl, code, "ID", 30)
        except stump.StumpError:
            continue
        try:
            files = {}
            for k, (v, size, digest) in got.items():
                if k in IDENTITY_FILES:
                    b = base64.b64decode(v)
                    if len(b) != size or hashlib.sha256(b).hexdigest() != digest:
                        raise ValueError
                    files[k] = b
        except (ValueError, TypeError, binascii.Error, AttributeError):
            continue
        if files.get("rns/identity") and not whole(files):
            raise stump.StumpError("its identity on the board isn't whole: nothing changed")
        return files if whole(files) else None
    # Not read (a garbled line): never taken for "none", or a restore would write over it unsaved.
    raise stump.StumpError("its identity couldn't be read back over USB: try again")


def board_put(repl, files):
    repl.run("import os\ntry:\n os.mkdir('rns')\nexcept OSError:\n pass\n")
    stump.upload(repl, [(k, v, hashlib.sha256(v).hexdigest()) for k, v in sorted(files.items())])
    if "pn_mailbox_identity" not in files:       # the old one's would go with another Stump's address
        repl.run("import os\ntry:\n os.remove('pn_mailbox_identity')\nexcept OSError:\n pass\n")


def _name(repl):
    try:
        return stump.asked_json(repl, "import json\ntry:\n import config\n n=getattr(config,'NODE_NAME','')\n"
                                      "except Exception:\n n=''\nprint('NAME'+json.dumps(n if isinstance(n,str) else ''))\n",
                                "NAME", 20, empty=r'".*"') or None
    except stump.StumpError:
        return None


def save_job(open_link, step, log, where, release=""):
    """Reads a CAM's identity into a keepsake in folder where. (ok, message, path)."""
    step("Connecting")
    repl = stump.ready_repl(open_link, log)
    try:
        if not stump.has_stump(repl):
            return False, "There's no Stump on this board (no config.py): make one first.", None
        step("Reading its identity")
        files, name = board_read(repl), _name(repl)
        step("Restarting it")
        stump.restart(repl)
    finally:
        repl.link.close()
    if not files:
        return False, ("It has no identity yet: a Stump makes it the first time it starts. Let it start once "
                       "(Check it starts), then save it."), None
    path = save(files, name, where, release)
    log("saved: %s" % path)
    return True, ("Its identity is saved: %s (fingerprint %s). Whoever has this file can be this Stump: keep it "
                  "safe (a USB key, a password manager), don't share it." % (path, fingerprint(files))), path


def restore_job(files, name, open_link, step, log, keep_dir, release=""):
    """Brings a saved identity back onto a CAM; the one it had, if another,
    saved first in keep_dir. (ok, message)."""
    step("Connecting")
    repl = stump.ready_repl(open_link, log)
    kept = None
    try:
        if not stump.has_stump(repl):
            return False, "There's no Stump on this board (no config.py): make one first, then bring it back."
        step("Saving the one it has")
        cur = board_read(repl)
        if cur and cur != files:                  # another identity, or its mailbox's key: kept first
            here = _name(repl) or "Stump"
            kept = save(cur, "%s (replaced %s)" % (here, time.strftime("%Y-%m-%d %H%M")), keep_dir, release)
            log("the identity it had, saved first: %s" % kept)
        step("Bringing it back")
        board_put(repl, files)
        step("Restarting it")
        stump.restart(repl)
    finally:
        repl.link.close()
    return True, ("It's %s again: it restarts with that identity (fingerprint %s).%s"
                  % (name or "that Stump", fingerprint(files),
                     " The identity it had is saved: %s." % kept if kept else ""))
