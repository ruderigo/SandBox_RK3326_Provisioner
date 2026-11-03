"""The S3 USB Wi-Fi adapter, from the handheld (s3_usb_wifi/ in this
repository). Its USB cable carries two things: the network card (the
handheld's usb0, bridged to the Wi-Fi the S3 joined, so the handheld is on
that network itself) and a serial port, where the S3 answers one JSON line
per question. The Provisioner's Wi-Fi page uses it to list networks, join one
(with a password typed on FireFly's keyboard) and forget one.

    find(ports)       the adapter's serial port among boards.list_ports(), or None
    status(port)      {"state", "ssid", "rssi", "channel", "target", "error", "link", ...} or None
    scan(port)        [{"ssid", "rssi", "open", "saved"}], strongest first
    saved(port)       ["ssid", ...], most recent first
    join(port, ssid, pw)  (True, None) or (False, why); pw None: a saved one keeps its own
    forget(port, ssid)    (True, None) or (False, why)
    handheld_address()    the handheld's IPv4 address on the adapter's interface, or None
    internet()        True if the handheld reaches the internet (through whatever route it has)
"""

import fcntl
import itertools
import json
import os
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor"))

PRODUCT = "FireFly S3 USB Wi-Fi"
VID = "303a"

ERRORS = {
    "wrong_password": "wrong password?",
    "not_found": "it's not in range",
    "security_mismatch": "its security isn't one the S3 supports",
    "failed": "it didn't work",
    "bad_password": "a password is 8 to 63 characters",
    "bad_ssid": "a network name is 1 to 32 bytes",
    "no_ssid": "no network name",
    "not_saved": "it isn't saved",
    "not_stored": "the S3 couldn't store it",
    "unreachable": "the adapter didn't answer",
}

_lock = threading.Lock()          # one question at a time on the port
_ids = itertools.count(1)


def explain(code):
    return ERRORS.get(code or "", code or "it didn't work")


def find(ports):
    """The adapter's serial port in boards.list_ports()'s list, or None."""
    for p in ports:
        if (p.get("usb") or "").startswith(VID + ":") and PRODUCT in (p.get("product") or ""):
            return p["port"]
    return None


def is_adapter(p):
    return find([p]) is not None


def ask(port, cmd, timeout=3.0, **fields):
    """One question, its answer: (True, data) or (False, error word)."""
    if not port:
        return False, "unreachable"
    req = dict(fields, id=next(_ids), cmd=cmd)
    line = (json.dumps(req, ensure_ascii=True) + "\n").encode()
    with _lock:
        try:
            import serial
            with serial.Serial(port, 115200, timeout=0.2, write_timeout=2) as s:
                s.reset_input_buffer()
                s.write(line)
                end, buf = time.time() + timeout, b""
                while time.time() < end:
                    buf += s.read(512)
                    while b"\n" in buf:
                        one, buf = buf.split(b"\n", 1)
                        try:
                            a = json.loads(one.decode("utf-8", "replace"))
                        except ValueError:
                            continue
                        if isinstance(a, dict) and a.get("id") == req["id"]:
                            return (True, a.get("data")) if a.get("ok") else (False, a.get("error") or "failed")
        except Exception:
            return False, "unreachable"
    return False, "unreachable"


def status(port, timeout=2.0):
    ok, d = ask(port, "status", timeout)
    return d if ok and isinstance(d, dict) and "firmware" in d else None


def scan(port, timeout=10.0):
    ok, d = ask(port, "scan", timeout)
    return [n for n in d if isinstance(n, dict) and n.get("ssid")] if ok and isinstance(d, list) else []


def saved(port, timeout=3.0):
    ok, d = ask(port, "saved", timeout)
    return [s for s in d if isinstance(s, str) and s] if ok and isinstance(d, list) else []


def join(port, ssid, password=None, timeout=5.0):
    fields = {"ssid": ssid}
    if password is not None:
        fields["password"] = password
    ok, d = ask(port, "join", timeout, **fields)
    return (True, None) if ok else (False, d)


def forget(port, ssid, timeout=5.0):
    ok, d = ask(port, "forget", timeout, ssid=ssid)
    return (True, None) if ok else (False, d)


def interface(sys_net="/sys/class/net"):
    """The handheld's network interface on the adapter (usb0, usually), or None."""
    try:
        names = sorted(os.listdir(sys_net))
    except OSError:
        return None
    for name in names:
        dev = os.path.realpath(os.path.join(sys_net, name, "device"))
        # .../1-1.4/1-1.4:1.2 (the interface) -> .../1-1.4 (the USB device)
        try:
            with open(os.path.join(os.path.dirname(dev), "product")) as f:
                if PRODUCT in f.read():
                    return name
        except OSError:
            continue
    return None


def handheld_address(iface=None):
    iface = iface or interface()
    if not iface:
        return None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            r = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", iface[:15].encode()))   # SIOCGIFADDR
        finally:
            s.close()
        return socket.inet_ntoa(r[20:24])
    except OSError:
        return None


def internet(timeout=3):
    """A DNS answer and a TCP connection out: enough to say "internet OK"."""
    try:
        addr = socket.getaddrinfo("connectivitycheck.gstatic.com", 80, socket.AF_INET, socket.SOCK_STREAM)[0][4]
        with socket.create_connection(addr, timeout=timeout):
            return True
    except Exception:
        return False


def bars(rssi):
    """0 to 4, as a phone shows it."""
    if rssi is None:
        return 0
    return 4 if rssi >= -55 else 3 if rssi >= -67 else 2 if rssi >= -75 else 1
