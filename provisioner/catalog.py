"""The firmware the Provisioner offers: firmware/catalog.json, each image
pinned by its SHA-256, and which boards it fits."""

import hashlib
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE_DIR = os.environ.get("PROVISIONER_FIRMWARE", os.path.join(HERE, "firmware"))


def load(firmware_dir=None):
    d = firmware_dir or FIRMWARE_DIR
    with open(os.path.join(d, "catalog.json"), encoding="utf-8") as f:
        entries = json.load(f)["firmware"]
    for e in entries:
        e.setdefault("status", "ready")
        e.setdefault("mode", "app")
        if e.get("file"):
            e["path"] = os.path.join(d, e["file"])
    return entries


def for_board(entries, board):
    """The entries that fit this board (by its id, else its chip)."""
    return [e for e in entries if board.get("id") in e.get("boards", ()) or
            (not e.get("boards") and e.get("chip") == board.get("chip"))]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def check(entry):
    """None if the image is there and is the one pinned, else why not."""
    p = entry.get("path")
    if not p or not os.path.isfile(p):
        return "the image file is missing"
    if sha256(p) != entry.get("sha256"):
        return "the image doesn't match its SHA-256: not flashed"
    return None
