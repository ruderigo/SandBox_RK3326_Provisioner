"""The file browser behind + From File: where to look on a handheld, and what
a folder holds (folders first, then the files it can use)."""

import glob
import os

USABLE = (".bin", ".zip")


def roots(home=None):
    """[(label, path)] that exist: the games partitions, the home folder, USB
    drives and other mounted cards."""
    home = home or os.path.expanduser("~")
    cands = [("Games card", "/roms"), ("Second card", "/roms2"), ("Games card", "/storage/roms"),
             ("Home", home)]
    for pat, label in (("/media/*", "Drive"), ("/run/media/*/*", "Drive"), ("/mnt/*", "Mounted"),
                       ("/storage/*", "Storage")):
        for p in sorted(glob.glob(pat)):
            if os.path.isdir(p) and not p.endswith("/storage/roms"):
                cands.append(("%s %s" % (label, os.path.basename(p)), p))
    out, seen = [], set()
    for label, p in cands:
        try:
            real = os.path.realpath(p)
        except OSError:
            continue
        if os.path.isdir(p) and real not in seen and os.access(p, os.R_OK | os.X_OK):
            seen.add(real)
            out.append((label, p))
    return out


def listdir(path, exts=USABLE, show_all=False, limit=500):
    """[{name, path, dir, size}]: folders first, then files ending in exts
    (any file with show_all), each sorted by name; hidden ones left out."""
    try:
        names = os.listdir(path)
    except OSError:
        return None
    dirs, files = [], []
    for n in names:
        if n.startswith("."):
            continue
        p = os.path.join(path, n)
        try:
            isdir = os.path.isdir(p)
            size = 0 if isdir else os.path.getsize(p)
        except OSError:
            continue
        if isdir:
            dirs.append({"name": n, "path": p, "dir": True, "size": 0})
        elif show_all or n.lower().endswith(exts):
            files.append({"name": n, "path": p, "dir": False, "size": size})
    key = lambda e: e["name"].lower()    # noqa: E731
    return (sorted(dirs, key=key) + sorted(files, key=key))[:limit]


def human(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "bytes" else ("%.1f %s" % (n, unit))
        n /= 1024.0
