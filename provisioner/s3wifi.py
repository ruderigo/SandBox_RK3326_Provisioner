"""The S3 USB Wi-Fi adapter, from the handheld: it's at 10.77.0.1 on its USB
link (s3_usb_wifi/ in this repository) and says what it sees and does over
plain HTTP. The Provisioner's Wi-Fi page uses this to list networks, join one
(with a password typed on FireFly's keyboard) and forget one.

    status()          {"state", "ssid", "rssi", "ip", "target", "error", ...} or None (not plugged in)
    scan()            [{"ssid", "rssi", "open", "saved"}], strongest first
    saved()           ["ssid", ...], most recent first
    join(ssid, pw)    (True, None) or (False, why); pw None: a saved one keeps its own
    forget(ssid)      (True, None) or (False, why)
    internet()        True if the handheld reaches the internet (through whatever route it has)
"""

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request

DEFAULT = "http://10.77.0.1"


def base():
    return os.environ.get("PROVISIONER_S3_URL", DEFAULT)


_op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

ERRORS = {
    "wrong_password": "wrong password?",
    "not_found": "it's not in range",
    "security_mismatch": "its security isn't one the S3 supports",
    "no_address": "it gave no address (DHCP)",
    "failed": "it didn't work",
    "bad_password": "a password is 8 to 63 characters",
    "no_ssid": "no network name",
    "not_saved": "the S3 couldn't store it",
    "not_stored": "the S3 couldn't store it",
    "unreachable": "the adapter didn't answer",
}


def explain(code):
    return ERRORS.get(code or "", code or "it didn't work")


def _get(path, timeout):
    with _op.open(base() + path, timeout=timeout) as r:
        return json.load(r)


def _post(path, fields, timeout):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(base() + path, data=data, headers={
        "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with _op.open(req, timeout=timeout) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except Exception:
            body = {"ok": False, "error": "failed"}
    except Exception:
        return False, "unreachable"
    return bool(body.get("ok")), body.get("error")


def status(timeout=1.5):
    try:
        s = _get("/status.json", timeout)
    except Exception:
        return None
    return s if isinstance(s, dict) and "firmware" in s else None


def scan(timeout=8):
    try:
        lst = _get("/scan.json", timeout)
    except Exception:
        return []
    return [n for n in lst if isinstance(n, dict) and n.get("ssid")]


def saved(timeout=3):
    try:
        lst = _get("/networks.json", timeout)
    except Exception:
        return []
    return [s for s in lst if isinstance(s, str) and s]


def join(ssid, password=None, timeout=5):
    fields = {"ssid": ssid}
    if password is not None:
        fields["password"] = password
    return _post("/join", fields, timeout)


def forget(ssid, timeout=5):
    return _post("/forget", {"ssid": ssid}, timeout)


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
