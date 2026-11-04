"""Making a Stump on a Freenove ESP32-S3-CAM, from the handheld, offline.

The same steps as Team Stump's Arborist (SandBox_Stump_On scripts/arborist/
repl.js, page.html), in Python, from the bundle their release ships
(firmware/stump/, see scripts/fetch_stump_bundle.py):

  make     erase the board, write MicroPython, copy the Stump (each file
           checked on the board by SHA-256), write its config.py from the
           scrubbed template with your answers, restart;
  update   copy a new release, keeping config.py, the identity, the card;
  settings read and change its config.py, by the Stump's own settings.py
           (what /admin uses);
  check    restart it and listen to it start.

MicroPython's raw REPL over the serial line, raw-paste with its flow
control when the board has it, as mpremote and Arborist do.
"""

import base64
import gzip
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor"))
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_DIR = os.environ.get("PROVISIONER_STUMP", os.path.join(HERE, "firmware", "stump"))
RAW_BANNER = b"raw REPL; CTRL-B to exit\r\n>"
QUIET_WATCHDOG = "try:\n import machine\n machine.WDT(timeout=7200000).feed()\nexcept Exception:\n pass\n"
FEATURES = ["chat", "billboard", "files", "about"]
THEMES = ["paper", "amber", "phosphor", "oled"]
MODES = ["open", "hybrid", "mandatory"]
RADIO_BW = [7800, 10400, 15600, 20800, 31250, 41700, 62500, 125000, 250000, 500000]
# LaBuche's mesh: what a new Stump starts from (it must match the mesh), as in Arborist.
RADIO_DEFAULT = {"frequency": 868800000, "bandwidth": 125000, "sf": 8, "cr": 5, "txpower": 22}


class StumpError(Exception):
    pass


# -- the bundle ---------------------------------------------------------------
class Bundle:
    def __init__(self, path):
        with open(path, "rb") as f:
            raw = gzip.decompress(f.read())
        n = int.from_bytes(raw[:4], "little")
        self.head = json.loads(raw[4:4 + n])
        body = raw[4 + n:]
        self.files = {}
        for name, off, length, sha in self.head["files"]:
            data = body[off:off + length]
            if hashlib.sha256(data).hexdigest() != sha:
                raise StumpError("the Stump bundle is damaged (%s)" % name)
            self.files[name] = (data, sha)
        self.release = self.head["release"]
        self.micropython = self.head.get("micropython", "")
        self.mpy = self.head.get("mpy")
        self.template = self.head["config_template"]
        meta = os.path.splitext(path)[0] + ".json"
        try:
            with open(meta, encoding="utf-8") as f:
                self.meta = json.load(f)
        except (OSError, ValueError):
            self.meta = {}
        # In the bundle's own header from 1.0.0-beta.48; the fetch script's notes before that.
        self.default_ssid = self.head.get("default_ssid") or self.meta.get("default_ssid") or "Stump"

    def app(self):
        """[(path on the board, bytes, sha256)]"""
        return [(n[4:], d, s) for n, (d, s) in sorted(self.files.items()) if n.startswith("app/")]

    def app_bytes(self):
        return sum(len(d) for _, d, _ in self.app())


def find_bundle(d=None):
    d = d or BUNDLE_DIR
    try:
        names = sorted(f for f in os.listdir(d) if f.startswith("stump-") and f.endswith(".bundle"))
    except OSError:
        return None
    return Bundle(os.path.join(d, names[-1])) if names else None


# -- the serial line ---------------------------------------------------------
class SerialLink:
    """A board's USB serial line at 115200, read in the background. DTR and
    RTS held low from before it opens: on a USB-serial chip they're the
    board's RESET and BOOT lines."""

    def __init__(self, port, baud=115200):
        import serial
        s = serial.Serial()
        s.port, s.baudrate, s.timeout = port, baud, 0.05
        s.dtr = False
        s.rts = False
        s.open()
        self.s = s
        self.on_bytes = None
        self.dead = None
        self._stop = threading.Event()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while not self._stop.is_set():
            try:
                b = self.s.read(512)
            except Exception as e:
                self.dead = e
                if self.on_bytes:
                    self.on_bytes(b"")
                return
            if b and self.on_bytes:
                self.on_bytes(b)

    def write(self, b):
        self.s.write(b)
        self.s.flush()

    def close(self):
        self._stop.set()
        time.sleep(0.1)
        try:
            self.s.close()
        except Exception:
            pass


class Repl:
    """MicroPython's raw REPL over a link with write(bytes), whose reads
    come in through feed()."""

    def __init__(self, link, log=None, raw_paste=None):
        self.link = link
        self.buf = b""
        self.cv = threading.Condition()
        self.raw_paste = raw_paste
        self.log = log or (lambda s: None)
        self.text = []                       # everything the board said (a boot's lines, for check)
        link.on_bytes = self.feed

    def feed(self, b):
        with self.cv:
            self.buf += b
            if b:
                self.text.append(b)
            self.cv.notify_all()

    def write(self, b):
        self.link.write(b.encode() if isinstance(b, str) else b)

    def drain(self):
        with self.cv:
            b, self.buf = self.buf, b""
        return b

    def _dead(self):
        return getattr(self.link, "dead", None)

    def read_until(self, pat, secs=5.0):
        pat = pat.encode() if isinstance(pat, str) else pat
        end = time.time() + secs
        with self.cv:
            while True:
                i = self.buf.find(pat)
                if i >= 0:
                    out, self.buf = self.buf[:i + len(pat)], self.buf[i + len(pat):]
                    return out
                if self._dead():
                    raise StumpError("the board went away (cable out?)")
                left = end - time.time()
                if left <= 0:
                    raise StumpError("the board didn't answer (waited for %r; it said %r)"
                                     % (pat.decode("latin-1"), self.buf[-120:].decode("utf-8", "replace")))
                self.cv.wait(min(left, 0.2))

    def read_n(self, n, secs=5.0):
        end = time.time() + secs
        with self.cv:
            while len(self.buf) < n:
                if self._dead():
                    raise StumpError("the board went away (cable out?)")
                left = end - time.time()
                if left <= 0:
                    raise StumpError("the board didn't answer")
                self.cv.wait(min(left, 0.2))
            out, self.buf = self.buf[:n], self.buf[n:]
            return out

    def enter_raw(self, secs=5.0):
        """Stop whatever runs (a Stump's main loop too) and enter the raw REPL."""
        for _ in range(3):
            self.write(b"\r\x03")
            time.sleep(0.15)
        self.drain()
        self.write(b"\r\x01")
        self.read_until(RAW_BANNER, secs)

    def soft_reset(self, secs=10.0):
        self.write(b"\x04")
        self.read_until(b"soft reboot\r\n", secs)
        self.read_until(RAW_BANNER, secs)

    def _paste(self, data):
        w = self.read_n(2)
        win = w[0] | (w[1] << 8)
        remain, i = win, 0
        while i < len(data):
            while remain == 0 or self.buf:
                b = self.read_n(1, 10)[0]
                if b == 1:
                    remain += win
                elif b == 4:
                    self.write(b"\x04")
                    raise StumpError("the board stopped taking the code")
                else:
                    raise StumpError("the board said something unexpected (%d)" % b)
            n = min(remain, len(data) - i)
            self.write(data[i:i + n])
            remain -= n
            i += n
        self.write(b"\x04")
        self.read_until(b"\x04", 10)

    def exec(self, code, secs=30.0):
        """(out, err) of code run on the board (err: the traceback, or "")."""
        data = code.encode() if isinstance(code, str) else code
        plain = self.raw_paste is False
        if not plain:
            self.write(b"\x05A\x01")
            r = self.read_n(2, 3)
            if r == b"R\x01":
                self.raw_paste = True
                self._paste(data)
            else:
                self.raw_paste, plain = False, True
                if r != b"R\x00":
                    self.read_until(b"w REPL; CTRL-B to exit\r\n>", 3)
        if plain:
            for k in range(0, len(data), 256):
                self.write(data[k:k + 256])
                time.sleep(0.01)
            self.write(b"\x04")
            if self.read_n(2, 5) != b"OK":
                raise StumpError("the board didn't take the code")
        out = self.read_until(b"\x04", secs)[:-1]
        err = self.read_until(b"\x04", secs)[:-1]
        self.read_until(b">", 5)
        return out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def run(self, code, secs=30.0):
        out, err = self.exec(code, secs)
        if err.strip():
            raise StumpError(err.strip().splitlines()[-1])
        return out


def py(s):
    return json.dumps(str(s))                # a JSON string is a Python string literal


def prepare(repl, secs=5.0):
    """A running Stump stopped, its watchdog given 2 hours (it can't be turned
    off, and a reset mid-copy would cut it), a clean interpreter."""
    repl.enter_raw(secs)
    repl.run(QUIET_WATCHDOG)
    repl.soft_reset()


def restart(repl):
    """Back to the friendly REPL, then a reset: the board starts the Stump."""
    repl.write(b"\x02")
    time.sleep(0.3)
    repl.write(b"import machine; machine.reset()\r\n")
    time.sleep(0.3)


def board_info(repl):
    out = repl.run("import sys\nv=getattr(sys.implementation,'_mpy',0)\n"
                   "print('INFO', '.'.join(str(x) for x in sys.implementation.version[:3]), "
                   "'%d.%d' % (v & 0xff, (v >> 8) & 3))\n")
    m = re.search(r"INFO (\S+) (\S+)", out)
    return {"release": m.group(1), "mpy": m.group(2)} if m else {"release": "", "mpy": ""}


def has_stump(repl):
    return "YES" in repl.run("import os\ntry:\n os.stat('config.py')\n print('YES')\nexcept OSError:\n print('NO')\n")


def upload(repl, files, progress=None, chunk=3072):
    """files: [(path, bytes, sha256)]. Folders first; each file in chunks to
    <file>.part, its SHA-256 checked on the board, then renamed over the old
    one (a cut cable never leaves half a module). A module arriving as .mpy
    has its .py removed, and the other way round."""
    progress = progress or (lambda done, total, path: None)
    total = sum(len(d) for _, d, _ in files)
    dirs = set()
    for p, _, _ in files:
        parts = p.split("/")
        for k in range(1, len(parts)):
            dirs.add("/".join(parts[:k]))
    if dirs:
        dl = sorted(dirs, key=lambda d: (d.count("/"), d))
        repl.run("import os\nfor d in %s:\n try:\n  os.mkdir(d)\n except OSError:\n  pass\n" % json.dumps(dl))
    done = 0
    for path, data, sha in files:
        tmp = path + ".part"
        progress(done, total, path)
        if not data:
            repl.run("open(%s,'wb').close()\n" % py(tmp))
        for off in range(0, len(data), chunk):
            b64 = base64.b64encode(data[off:off + chunk]).decode()
            repl.run("import binascii\nf=open(%s,'%s')\nf.write(binascii.a2b_base64('%s'))\nf.close()\n"
                     % (py(tmp), "ab" if off else "wb", b64))
            done += min(chunk, len(data) - off)
            progress(done, total, path)
        repl.run("import os,hashlib,binascii\nh=hashlib.sha256()\nf=open(%s,'rb')\nwhile 1:\n b=f.read(2048)\n"
                 " if not b:\n  break\n h.update(b)\nf.close()\nd=binascii.hexlify(h.digest()).decode()\n"
                 "if d!=%s:\n os.remove(%s)\n raise OSError(%s)\n"
                 "try:\n os.remove(%s)\nexcept OSError:\n pass\nos.rename(%s,%s)\n"
                 % (py(tmp), py(sha), py(tmp), py(path + " arrived damaged"), py(path), py(tmp), py(path)), 60)
    gone = []
    for path, _, _ in files:
        if path.endswith(".mpy"):
            gone.append(path[:-4] + ".py")
        elif path.endswith(".py") and not re.search(r"(^|/)(boot|main|config)\.py$", path):
            gone.append(path[:-3] + ".mpy")
    if gone:
        repl.run("import os\nfor p in %s:\n try:\n  os.remove(p)\n except OSError:\n  pass\n" % json.dumps(gone))
    progress(total, total, "")


# -- settings (config.py), by the Stump's own settings.py ---------------------
KEYS = ["NODE_NAME", "BOT_NAME", "MESH_GREETING", "WIFI_SSID", "AUTH_MODE", "FEATURES", "THEME", "SSID_NAME",
        "CHAIN_ENABLED", "CHAIN_UPLINK_SSID", "CHAIN_UPLINK_PASS", "CHAIN_SUBNET", "CHAIN_CHANNEL", "CHAIN_SECRET"]


def read_settings(repl):
    out = repl.run(
        "import json\nimport config as c\nb=[i for i in c.CONFIG.get('interfaces',[]) if i.get('name')=='Heltec Bridge']\n"
        "b=b[0] if b else {}\nd={}\nfor k in %s:\n d[k]=getattr(c,k,None)\n"
        "d['HAS_ADMIN_PASSWORD']=bool(getattr(c,'AUTH_ADMIN_PASSWORD',''))\n"
        "d['HAS_OP_PASSWORD']=bool(getattr(c,'FSERVBOT_OP_PASSWORD',''))\n"
        "d['HAS_WIFI_PASS']=bool(getattr(c,'WIFI_PASS',''))\n"
        "d['HELTEC']={'there':bool(b),'enabled':bool(b.get('enabled')),'host':b.get('target_host',''),"
        "'port':b.get('target_port',7633)}\nprint('CFG'+json.dumps(d))\n" % json.dumps(KEYS), 30)
    m = re.search(r"CFG(\{.*\})", out)
    if not m:
        raise StumpError("couldn't read its settings")
    return json.loads(m.group(1))


def write_settings(repl, values):
    """values: {KEY: value} for config.py, and HELTEC: {enabled, host, port}.
    config.py.bak kept; a result that isn't Python is put back."""
    top = {k: v for k, v in values.items() if k != "HELTEC"}
    h = values.get("HELTEC")
    code = (
        "import json, os, settings\nch=json.loads(%s)\nH=json.loads(%s)\n" % (py(json.dumps(top)), py(json.dumps(h))) +
        "src=open('config.py').read()\nf=open('config.py.bak','w')\nf.write(src)\nf.close()\n"
        "if ch and not settings.write_config(ch,'config.py'):\n raise OSError('config.py not written')\n"
        "if H:\n L=open('config.py').read().split('\\n')\n blk=False\n done=0\n for i in range(len(L)):\n"
        "  l=L[i]\n  s=l.lstrip()\n  ind=l[:len(l)-len(s)]\n  if 'Heltec Bridge' in l:\n   blk=True\n  if not blk:\n   continue\n"
        "  if s.startswith('\"enabled\"'):\n   L[i]=ind+'\"enabled\": %r,' % bool(H['enabled'])\n   done+=1\n"
        "  elif s.startswith('\"target_host\"'):\n   L[i]=ind+'\"target_host\": %r,' % H['host']\n   done+=1\n"
        "  elif s.startswith('\"target_port\"'):\n   L[i]=ind+'\"target_port\": %d,' % int(H['port'])\n   done+=1\n"
        "   blk=False\n"
        " if done!=3:\n  raise OSError('no Heltec Bridge in config.py to set')\n f=open('config.py.tmp','w')\n"
        " f.write('\\n'.join(L))\n f.close()\n os.rename('config.py.tmp','config.py')\n"
        "try:\n compile(open('config.py').read(),'config.py','exec')\nexcept SyntaxError as e:\n"
        " f=open('config.py','w')\n f.write(src)\n f.close()\n raise OSError('the new config.py was not Python: put back as it was')\n"
        "print('SAVED')\n")
    if "SAVED" not in repl.run(code, 30):
        raise StumpError("its settings weren't saved")


def read_radio(repl):
    out = repl.run("import json, store, radio\nprint('RAD'+json.dumps(store.load_json(radio.SETTINGS_FILE, None)))\n")
    m = re.search(r"RAD(null|\{.*\})", out)
    return json.loads(m.group(1)) if m and m.group(1) != "null" else None


def write_radio(repl, settings):
    out = repl.run("import json, radio\nprint('RSAVE' + ('1' if radio.save(json.loads(%s)) else '0'))\n"
                   % py(json.dumps(settings)))
    return "RSAVE1" in out


def _ctl(s):
    return bool(re.search(r"[\x00-\x1f\x7f]", s or ""))


def settings_from(a):
    """The form's answers -> {"values"} for write_settings, or {"error"};
    {"warn"} too. Arborist's rules (settingsFrom), which are /admin's and
    the Provisioner's."""
    v, warn = {}, []

    def no(e):
        return {"error": e}
    name = (a.get("name") or "").strip()
    if not name or len(name) > 20 or _ctl(name):
        return no("The name: 1 to 20 characters.")
    v["NODE_NAME"] = name
    bot = (a.get("bot") or "BarKeep").strip()
    if not bot or len(bot) > 24 or _ctl(bot):
        return no("The bot's name: 1 to 24 characters.")
    v["BOT_NAME"] = bot
    greet = re.sub(r"[\r\n]+", " ", a.get("greeting") or "").strip()
    if len(greet) > 200:
        return no("The greeting: at most 200 characters.")
    v["MESH_GREETING"] = greet
    pw, pw2 = a.get("pw") or "", a.get("pw2") or ""
    if pw or pw2:
        if len(pw) < 4 or len(pw) > 64:
            return no("The admin password: 4 to 64 characters.")
        if pw != pw2:
            return no("The two admin passwords aren't the same.")
        v["AUTH_ADMIN_PASSWORD"] = pw
    opw = a.get("opw") or ""
    if opw:
        if len(opw) < 4 or len(opw) > 64:
            return no("The BarKeep operator password: 4 to 64 characters.")
        v["FSERVBOT_OP_PASSWORD"] = opw
    if a.get("requireAdmin") and not v.get("AUTH_ADMIN_PASSWORD") and not a.get("hasPw") \
            and not v.get("FSERVBOT_OP_PASSWORD") and not a.get("hasOpPw"):
        return no("Set an admin password.")
    ssid = (a.get("ssid") or "").strip()
    if len(ssid) > 32 or _ctl(ssid):
        return no("The home Wi-Fi's name: at most 32 characters.")
    v["WIFI_SSID"] = ssid
    if not (a.get("keepWifiPass") and not a.get("wpass")):
        wp = a.get("wpass") or ""
        if wp and not ssid:
            return no("A Wi-Fi password, but no Wi-Fi name.")
        if wp and (len(wp) < 8 or len(wp) > 63):
            return no("A Wi-Fi password is 8 to 63 characters.")
        v["WIFI_PASS"] = wp
    feats = [f for f in FEATURES if f in (a.get("features") or [])]
    if not feats:
        warn.append("No features chosen: its pages offer nothing but /admin.")
    v["FEATURES"] = feats
    theme, mode = a.get("theme") or "paper", a.get("mode") or "open"
    if theme not in THEMES:
        return no("Unknown theme.")
    if mode not in MODES:
        return no("Unknown access mode.")
    v["THEME"], v["AUTH_MODE"] = theme, mode
    hs = (a.get("hotspot") or "").strip()
    if len(hs) > 32 or _ctl(hs):
        return no("The Wi-Fi name it shows: at most 32 characters.")
    v["SSID_NAME"], v["SSID_INCLUDE_IP"] = hs or None, False
    subnet = 4
    chain = a.get("chain") or "none"
    if chain in ("first", "member"):
        secret = (a.get("secret") or "").strip()
        if len(secret) > 64 or re.search(r"['\"\\]", secret) or _ctl(secret):
            return no("The chain secret: at most 64 characters, no quotes or backslashes.")
        if not secret:
            warn.append("No chain secret: anyone on a Stump's Wi-Fi could join the chain.")
        v["CHAIN_ENABLED"], v["CHAIN_SECRET"] = True, secret
        if chain == "first":
            try:
                ch = int(a.get("channel") or 11)
            except ValueError:
                ch = 0
            if not 1 <= ch <= 13:
                return no("The chain's Wi-Fi channel: 1 to 13.")
            v.update(CHAIN_UPLINK_SSID="", CHAIN_UPLINK_PASS="", CHAIN_SUBNET=4, CHAIN_CHANNEL=ch)
        else:
            up = (a.get("upSsid") or "").strip()
            if not up or len(up) > 32 or _ctl(up):
                return no("The Wi-Fi name of the Stump it joins: 1 to 32 characters.")
            s = str(a.get("subnet") or "").strip()
            if not s.isdigit() or not 5 <= int(s) <= 254:
                return no("This Stump's number in the chain: 5 to 254, a different one on each Stump.")
            subnet = int(s)
            v.update(CHAIN_UPLINK_SSID=up, CHAIN_UPLINK_PASS=a.get("upPass") or "", CHAIN_SUBNET=subnet, CHAIN_CHANNEL=0)
    else:
        v["CHAIN_ENABLED"] = False
    radio = a.get("radio") or "none"
    if radio == "lan":
        host = (a.get("hhost") or "").strip()
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host) or any(int(x) > 255 for x in host.split(".")):
            return no("The Heltec's address looks like 192.168.1.50.")
        if not ssid:
            return no("A Heltec on the home Wi-Fi needs the home Wi-Fi's name.")
        v["HELTEC"] = {"enabled": True, "host": host, "port": 7633}
    elif radio == "ap":
        v["HELTEC"] = {"enabled": True, "host": "192.168.%d.2" % subnet, "port": 7633}
    else:
        hh = a.get("hhost") or ""
        v["HELTEC"] = {"enabled": False, "host": hh if re.match(r"^[\d.]+$", hh) else "192.168.%d.2" % subnet,
                       "port": 7633}
    return {"values": v, "warn": warn}


def answers_from(c):
    """What read_settings found -> the form's answers."""
    chain = "none" if not c.get("CHAIN_ENABLED") else ("member" if c.get("CHAIN_UPLINK_SSID") else "first")
    subnet = c.get("CHAIN_SUBNET") if chain == "member" else 4
    h = c.get("HELTEC") or {}
    radio = "none" if not h.get("enabled") else ("ap" if h.get("host") == "192.168.%s.2" % subnet else "lan")
    return {"name": c.get("NODE_NAME") or "", "bot": c.get("BOT_NAME") or "BarKeep",
            "greeting": c.get("MESH_GREETING") or "", "ssid": c.get("WIFI_SSID") or "", "radio": radio,
            "hhost": h.get("host", "") if radio == "lan" else "",
            "features": c.get("FEATURES") if isinstance(c.get("FEATURES"), list) else FEATURES[:3],
            "theme": c.get("THEME") or "paper", "mode": c.get("AUTH_MODE") or "open", "hotspot": c.get("SSID_NAME") or "",
            "chain": chain, "channel": c.get("CHAIN_CHANNEL") or 11, "upSsid": c.get("CHAIN_UPLINK_SSID") or "",
            "upPass": c.get("CHAIN_UPLINK_PASS") or "", "subnet": c.get("CHAIN_SUBNET") or 5,
            "secret": c.get("CHAIN_SECRET") or "", "hasPw": bool(c.get("HAS_ADMIN_PASSWORD")),
            "hasOpPw": bool(c.get("HAS_OP_PASSWORD")), "hasWifiPass": bool(c.get("HAS_WIFI_PASS"))}


def boot_summary(text):
    """What a Stump says as it starts -> {release, micropython, serving, problems, notes}."""
    out = {"release": None, "micropython": None, "serving": False, "problems": [], "notes": []}
    m = re.search(r"Project Stump -- (.+?) \(([^)]+)\)", text)
    if m:
        out["release"] = m.group(2)
    m = re.search(r"MicroPython (v[\w.\-]+)", text)
    if m:
        out["micropython"] = m.group(1)
    out["serving"] = "[web] serving" in text
    for line in text.replace("\r", "").split("\n"):
        if re.search(r"Traceback|Error|FAILED|rescue start|couldn't|not armed", line, re.I):
            if len(out["problems"]) < 12:
                out["problems"].append(line.strip())
        elif re.search(r"WiFi unavailable|\[watchdog\] armed|\[chain\]|\[radio\]|\[sd\]", line, re.I):
            if len(out["notes"]) < 12:
                out["notes"].append(line.strip())
    return out


def random_secret():
    return secrets.token_hex(8)


# -- the jobs (one call each, from the app's background task) ---------------
def ready_repl(open_link, log=None, secs=40.0):
    """The REPL, the board ready: a running Stump stopped, a clean interpreter.
    open_link() opens the serial line (retried: after a reset, a board on its
    own USB comes back as a new device)."""
    link, last, end = None, None, time.time() + secs
    while time.time() < end:
        try:
            link = open_link()
            break
        except Exception as e:
            last = e
            time.sleep(0.5)
    if link is None:
        raise StumpError("Can't open the board's port: %s" % last)
    repl = Repl(link, log)
    time.sleep(1.5)
    while time.time() < end:
        try:
            prepare(repl, 4)
            return repl
        except StumpError as e:
            last = e
            if repl._dead():
                raise StumpError("The board went away (cable out?)")
            log and log("waiting for the board: %s" % e)
    link.close()
    raise StumpError("The board doesn't answer on USB: %s" % last)


def make(bundle, answers, open_link, flash_micropython, step, progress, log, update=False):
    """A new Stump (erases the board) or an update. (ok, message)."""
    s = rad = None
    if not update:
        s = settings_from(dict(answers, requireAdmin=True))
        if s.get("error"):
            return False, s["error"]
        if (answers.get("radio") or "none") != "none":
            rad = dict(RADIO_DEFAULT)
        step("Erasing the board, writing MicroPython %s" % bundle.micropython)
        with tempfile.TemporaryDirectory(prefix="provisioner-mp-") as tmp:
            img = os.path.join(tmp, "micropython.bin")
            with open(img, "wb") as f:
                f.write(bundle.files["micropython.bin"][0])
            ok, msg = flash_micropython(img)
        if not ok:
            return False, msg
        step("Restarting it")
    step("Connecting")
    repl = ready_repl(open_link, log)
    try:
        info = board_info(repl)
        log("MicroPython %s, .mpy %s" % (info["release"], info["mpy"]))
        if update and bundle.mpy and info["mpy"] != bundle.mpy:
            return False, ("This board has MicroPython %s; Stump %s needs %s. Choose Make a Stump (it erases the "
                           "board: it gets a new identity)." % (info["release"], bundle.release, bundle.micropython))
        if update and not has_stump(repl):
            return False, "There's no Stump on this board to update (no config.py): choose Make a Stump."
        step("Copying the Stump %s" % bundle.release)
        t0 = time.time()

        def prog(done, total, path):
            progress(int(done * 100 / max(1, total)))
            sec = time.time() - t0
            if path and done and sec > 5:
                left = int((total - done) / (done / sec))
                log("%d of %d KB · about %s left · %s" % (done // 1024, total // 1024,
                                                           "%d min" % (left // 60) if left > 90 else "%d s" % left, path))
        upload(repl, bundle.app(), prog)
        if not update:
            step("Its settings")
            tpl = bundle.template.encode()
            upload(repl, [("config.py", tpl, hashlib.sha256(tpl).hexdigest())])
            write_settings(repl, s["values"])
            if rad and not write_radio(repl, rad):
                log("note: the radio settings weren't saved to the board")
        step("Restarting it")
        restart(repl)
    finally:
        repl.link.close()
    if update:
        return True, "Updated to %s; its settings, identity and card kept. It restarts." % bundle.release
    v = s["values"]
    return True, ("Your Stump is starting (about a minute the first time). From a phone, join the Wi-Fi \u201c%s\u201d: "
                  "a page opens. /admin takes the password you chose." % (v.get("SSID_NAME") or bundle.default_ssid))


def read_job(open_link, log):
    repl = ready_repl(open_link, log)
    try:
        if not has_stump(repl):
            return None
        c = read_settings(repl)
        c["RADIO"] = read_radio(repl)
        restart(repl)
        return c
    finally:
        repl.link.close()


def save_job(answers, open_link, step, log):
    s = settings_from(answers)
    if s.get("error"):
        return False, s["error"]
    step("Connecting")
    repl = ready_repl(open_link, log)
    try:
        if not has_stump(repl):
            return False, "There's no Stump on this board (no config.py)."
        step("Saving its settings")
        write_settings(repl, s["values"])
        step("Restarting it")
        restart(repl)
    finally:
        repl.link.close()
    return True, "Saved; config.py.bak kept on the board. It restarts with them."


def check_job(open_link, step, log, secs=60.0):
    step("Restarting it, listening")
    repl = ready_repl(open_link, log)
    try:
        repl.text = []
        restart(repl)
        end = time.time() + secs
        while time.time() < end:
            time.sleep(0.5)
            text = b"".join(repl.text).decode("utf-8", "replace")
            if "[web] serving" in text:
                time.sleep(3)
                break
        text = b"".join(repl.text).decode("utf-8", "replace")
    finally:
        repl.link.close()
    for line in text.replace("\r", "").split("\n")[-40:]:
        if line.strip():
            log(line)
    b = boot_summary(text)
    if b["serving"]:
        msg = "It started: Stump %s on MicroPython %s, serving." % (b["release"] or "?", b["micropython"] or "?")
        if b["problems"]:
            msg += " But: " + b["problems"][0]
        return not b["problems"], msg
    return False, ("It didn't get to serving in %d s. %s" % (secs, b["problems"][0] if b["problems"]
                                                               else "Nothing went wrong that it said."))
