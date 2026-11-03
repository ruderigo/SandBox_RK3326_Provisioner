"""A pretend S3 USB Wi-Fi adapter: the HTTP the firmware serves (web.c), on
localhost, with networks to see and a Wi-Fi to join. Joining takes one
status poll ("joining"), then connects; the password "wrongpass1" fails.

    s3 = FakeS3(); os.environ["PROVISIONER_S3_URL"] = s3.url; ... s3.stop()
"""

import http.server
import json
import threading
import urllib.parse

NETS = [
    {"ssid": "HomeNet", "rssi": -48, "open": False},
    {"ssid": "Stump-Oak", "rssi": -60, "open": True},
    {"ssid": "Cafe", "rssi": -79, "open": False},
]


class FakeS3:
    def __init__(self):
        self.saved = {}                     # ssid -> password, in order
        self.state = {"state": "idle", "ssid": None, "target": None, "error": None}
        self.pending = None
        self.calls = []
        s3 = self

        class H(http.server.BaseHTTPRequestHandler):
            def reply(self, code, body):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_GET(self):
                s3.calls.append(("GET", self.path))
                if self.path == "/status.json":
                    s3.tick()
                    st = {k: v for k, v in s3.state.items() if not k.startswith("_")}
                    on = st["ssid"]
                    st.update(rssi=-48 if on else None, ip="192.168.1.37" if on else None,
                              gateway="192.168.1.1" if on else None, subnet="192.168.1.0/24" if on else None,
                              dns="192.168.1.1" if on else None, stump=False, firmware="s3-usb-wifi 0.2.0")
                    self.reply(200, st)
                elif self.path == "/scan.json":
                    self.reply(200, [dict(n, saved=n["ssid"] in s3.saved) for n in NETS])
                elif self.path == "/networks.json":
                    self.reply(200, list(s3.saved))
                else:
                    self.reply(404, {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                f = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode(), keep_blank_values=True).items()}
                s3.calls.append(("POST", self.path, f))
                if self.path == "/join":
                    ssid, pw = f.get("ssid", ""), f.get("password")
                    if not ssid:
                        return self.reply(400, {"ok": False, "error": "no_ssid"})
                    if pw is None:
                        pw = s3.saved.get(ssid, "")
                    if pw and not 8 <= len(pw) <= 63:
                        return self.reply(400, {"ok": False, "error": "bad_password"})
                    s3.saved.pop(ssid, None)
                    s3.saved = dict([(ssid, pw)] + list(s3.saved.items()))
                    s3.state.update(state="joining", target=ssid, error=None)
                    s3.pending = (ssid, pw)
                    return self.reply(200, {"ok": True})
                if self.path == "/forget":
                    ssid = f.get("ssid")
                    if ssid not in s3.saved:
                        return self.reply(404, {"ok": False, "error": "not_saved"})
                    del s3.saved[ssid]
                    if s3.state["ssid"] == ssid:
                        s3.state.update(state="idle", ssid=None)
                    return self.reply(200, {"ok": True})
                self.reply(404, {})

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tick(self):
        """Joining finishes on the poll after the one that saw "joining"."""
        if not self.pending:
            return
        if self.state.get("_seen"):
            ssid, pw = self.pending
            self.pending = None
            self.state.pop("_seen")
            known = {n["ssid"]: n for n in NETS}
            if ssid not in known:
                self.state.update(state="idle", ssid=None, error="not_found")
            elif pw == "wrongpass1" or (not known[ssid]["open"] and not pw):
                self.state.update(state="idle", ssid=None, error="wrong_password")
            else:
                self.state.update(state="connected", ssid=ssid, error=None)
        else:
            self.state["_seen"] = True

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()
