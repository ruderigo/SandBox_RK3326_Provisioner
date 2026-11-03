"""A pretend S3 USB Wi-Fi adapter: its control port (ctl.c), as a pty that
pyserial opens like the real /dev/ttyACMx, answering one JSON line per
question, with networks to see and a Wi-Fi to join. Joining takes one status
question ("joining"), then connects; the password "wrongpass1" fails.

    s3 = FakeS3(); port = s3.port_record(); ... s3.stop()
"""

import json
import os
import select
import threading
import tty

NETS = [
    {"ssid": "HomeNet", "rssi": -48, "open": False},
    {"ssid": "Stump-Oak", "rssi": -60, "open": True},
    {"ssid": "Cafe", "rssi": -79, "open": False},
]


class FakeS3:
    def __init__(self):
        self.saved = {}                     # ssid -> password, most recent first
        self.state = {"state": "idle", "ssid": None, "target": None, "error": None}
        self.pending = None
        self.seen = False
        self.calls = []
        self.master, slave = os.openpty()
        tty.setraw(slave)
        self.path = os.ttyname(slave)
        self._slave = slave                 # kept open so the pty lives between opens
        self._stop = False
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    def port_record(self):
        return {"port": self.path, "usb": "303a:4002", "usb_chip": "FireFly S3 USB Wi-Fi",
                "product": "FireFly S3 USB Wi-Fi", "serial": "E8F60AA3BE24", "native": True}

    # -- the adapter's answers --
    def answer(self, req):
        cmd = req.get("cmd")
        self.calls.append(dict(req))
        if cmd == "status":
            self.tick()
            on = self.state["ssid"]
            return True, dict(self.state, rssi=-48 if on else None, channel=6 if on else None,
                              mac="e8:f6:0a:a3:be:24", link=bool(on), usb=True, setup_ap=False,
                              firmware="s3-usb-wifi 0.3.0")
        if cmd == "scan":
            return True, [dict(n, saved=n["ssid"] in self.saved) for n in NETS]
        if cmd == "saved":
            return True, list(self.saved)
        if cmd == "join":
            ssid, pw = req.get("ssid") or "", req.get("password")
            if not ssid:
                return False, "no_ssid"
            if pw is None:
                pw = self.saved.get(ssid, "")
            if pw and not 8 <= len(pw) <= 63:
                return False, "bad_password"
            self.saved.pop(ssid, None)
            self.saved = dict([(ssid, pw)] + list(self.saved.items()))
            self.state.update(state="joining", target=ssid, error=None)
            self.pending, self.seen = (ssid, pw), False
            return True, None
        if cmd == "forget":
            ssid = req.get("ssid")
            if ssid not in self.saved:
                return False, "not_saved"
            del self.saved[ssid]
            if self.state["ssid"] == ssid:
                self.state.update(state="idle", ssid=None)
            return True, None
        return False, "unknown_cmd"

    def tick(self):
        """Joining finishes on the status question after the one that saw "joining"."""
        if not self.pending:
            return
        if not self.seen:
            self.seen = True
            return
        ssid, pw = self.pending
        self.pending = None
        known = {n["ssid"]: n for n in NETS}
        if ssid not in known:
            self.state.update(state="idle", ssid=None, error="not_found")
        elif pw == "wrongpass1" or (not known[ssid]["open"] and not pw):
            self.state.update(state="idle", ssid=None, error="wrong_password")
        else:
            self.state.update(state="connected", ssid=ssid, error=None)

    # -- the line protocol --
    def _serve(self):
        buf = b""
        while not self._stop:
            r, _, _ = select.select([self.master], [], [], 0.1)
            if not r:
                continue
            try:
                chunk = os.read(self.master, 4096)
            except OSError:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    req = json.loads(line)
                except ValueError:
                    continue
                ok, data = self.answer(req)
                out = {"id": req.get("id", 0), "ok": ok}
                out.update({"data": data} if ok else {"error": data})
                os.write(self.master, (json.dumps(out) + "\n").encode())

    def stop(self):
        self._stop = True
        self._t.join(1)
        for fd in (self.master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass
