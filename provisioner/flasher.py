"""Flashing through esptool (bundled in vendor/, run as its own program):
probe a board, read its partition table, write an image, read it back.

Every step reports its lines and progress through callbacks, so the UI,
the command line and the tests all drive the same code.
"""

import os
import re
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(HERE, "vendor")
BAUD = int(os.environ.get("PROVISIONER_BAUD", "460800"))
SLOW_BAUD = 115200


def esptool_cmd(*args):
    """esptool as a program: PROVISIONER_ESPTOOL (tests), else the bundled one."""
    override = os.environ.get("PROVISIONER_ESPTOOL")
    if override:
        return [sys.executable, override] + list(args)
    return [sys.executable, "-m", "esptool"] + list(args)


def esptool_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = VENDOR + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def progress_of(line):
    """The percent in an esptool progress line ("Writing at 0x... (42 %)")."""
    m = re.search(r"\((\d{1,3})\s?%\)", line)
    return int(m.group(1)) if m else None


def run(args, on_line=None, timeout=300):
    """(ok, output) of one esptool command; each line (\\r or \\n ended) goes
    to on_line as it comes."""
    try:
        p = subprocess.Popen(esptool_cmd(*args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=esptool_env())
    except OSError as e:
        return False, "esptool didn't start: %s" % e
    out, buf = [], b""
    try:
        while True:
            chunk = p.stdout.read1(256) if hasattr(p.stdout, "read1") else p.stdout.read(1)
            if not chunk:
                break
            buf += chunk
            while True:
                m = re.search(rb"[\r\n]", buf)
                if not m:
                    break
                line = buf[:m.start()].decode("utf-8", "replace").strip()
                buf = buf[m.end():]
                if line:
                    out.append(line)
                    if on_line:
                        on_line(line)
        if buf.strip():
            line = buf.decode("utf-8", "replace").strip()
            out.append(line)
            if on_line:
                on_line(line)
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        return False, "\n".join(out + ["esptool timed out"])
    finally:
        p.stdout.close()
    return p.returncode == 0, "\n".join(out)


def explain(output):
    """A short, plain reason for an esptool failure."""
    t = (output or "").lower()
    if "permission denied" in t or "operation not permitted" in t:
        return "No permission for the serial port: run install.sh again (udev rule, dialout group)"
    if "failed to connect" in t or "no serial data received" in t or "wrong boot mode" in t:
        return "The board didn't answer: hold BOOT, tap RESET (or replug), then try again"
    if "could not open port" in t or "no such file" in t:
        return "The board went away (unplugged?)"
    lines = [l for l in (output or "").splitlines() if l.strip()]
    return lines[-1][:120] if lines else "esptool failed"


def probe(port, on_line=None):
    """(ok, text): esptool flash_id (chip, MAC, flash size), at a safe baud."""
    return run(["--port", port, "--baud", str(SLOW_BAUD), "flash_id"], on_line, timeout=60)


def parse_partitions(raw):
    """[(type, subtype, offset, size, label)] of an ESP partition table, or
    None if it isn't one."""
    out = []
    for off in range(0, min(len(raw), 0xC00), 32):
        magic, ptype, sub, start, size = struct.unpack_from("<HBBII", raw, off)
        if magic in (0xFFFF, 0xEBEB):          # end of table, MD5 row
            break
        if magic != 0x50AA:
            return None
        label = raw[off + 12:off + 28].split(b"\0", 1)[0].decode("ascii", "replace")
        out.append((ptype, sub, start, size, label))
    return out or None


def read_partitions(port, chip, on_line=None):
    """(table or None, output): the partition table at 0x8000."""
    with tempfile.TemporaryDirectory(prefix="provisioner-") as tmp:
        dest = os.path.join(tmp, "partitions.bin")
        ok, out = run(["--chip", chip, "--port", port, "--baud", str(SLOW_BAUD), "read_flash", "0x8000", "0xC00", dest],
                      on_line, timeout=90)
        if not ok or not os.path.isfile(dest):
            return None, out
        with open(dest, "rb") as f:
            return parse_partitions(f.read()), out


def app_slot_fits(table, offset, size):
    """None if an app partition starts at offset and holds size bytes, else why not."""
    for ptype, sub, start, psize, label in table or []:
        if ptype == 0 and start == offset:
            if size > psize:
                return "the image (%d KB) is bigger than the app slot %s (%d KB)" % (size // 1024, label, psize // 1024)
            return None
    return "no app partition at 0x%x on this board: it needs a full install, not this image" % offset


def flash(port, entry, board, on_line=None, on_step=None, on_progress=None):
    """Writes entry's image to the board and reads it back. (ok, message).
    on_step(text) says which step; on_progress(percent) the write's progress."""
    chip, offset = entry["chip"], int(entry["offset"], 16)
    size = os.path.getsize(entry["path"])
    step = on_step or (lambda s: None)
    prog = on_progress or (lambda p: None)

    def lines(line):
        if on_line:
            on_line(line)
        pct = progress_of(line)
        if pct is not None:
            prog(pct)

    if entry["mode"] == "full":
        need = entry.get("min_flash_mb") or 0
        if need and board.get("flash_mb") and board["flash_mb"] < need:
            return False, "This image needs %d MB of flash; the board has %g MB" % (need, board["flash_mb"])
        step("Erasing the whole flash")
        ok, out = run(["--chip", chip, "--port", port, "--baud", str(BAUD), "erase_flash"], lines, timeout=180)
        if not ok:
            return False, explain(out)
    else:
        step("Reading the partition table")
        table, out = read_partitions(port, chip, lines)
        if table is None:
            return False, explain(out) if "0x50aa" not in out.lower() else "No valid partition table on this board"
        why = app_slot_fits(table, offset, size)
        if why:
            return False, why[0].upper() + why[1:]
    step("Writing %s" % entry["title"])
    prog(0)
    args = ["--chip", chip, "--port", port, "--baud", str(BAUD), "write_flash", "--flash_mode", "keep",
            "--flash_size", "keep", entry["offset"], entry["path"]]
    ok, out = run(args, lines, timeout=600)
    if not ok and BAUD != SLOW_BAUD:
        step("Writing again, slower")
        ok, out = run(args[:5] + [str(SLOW_BAUD)] + args[6:], lines, timeout=900)
    if not ok:
        return False, explain(out)
    prog(100)
    step("Reading it back")
    ok, out = run(["--chip", chip, "--port", port, "--baud", str(BAUD), "verify_flash", entry["offset"], entry["path"]],
                  lines, timeout=300)
    # esptool: "-- verify OK (digest matched)"
    if not ok or not ("verify ok" in out.lower() or "digest matched" in out.lower()):
        return False, "Written, but the read-back differs: " + explain(out)
    return True, "%s written and verified" % entry["title"]


def erase(port, chip, on_line=None):
    ok, out = run(["--chip", chip, "--port", port, "--baud", str(BAUD), "erase_flash"], on_line, timeout=180)
    return ok, ("Flash erased" if ok else explain(out))
