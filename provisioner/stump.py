"""Making a Stump on a Freenove ESP32-S3-CAM or an ESP32-WROVER, from the
handheld, offline.

The same steps as Team Stump's Arborist (SandBox_Stump_On scripts/arborist/
repl.js, page.html), in Python, from the bundle their release ships
(on the shelf, provisioner/shelf.py: Official from LaBuche-Stump, Sandbox from SandBox_Stump_On):

  make     erase the board, write the release's Stump image for its chip
           (MicroPython with the Stump built in, 1.0.0-beta.57 on: the
           S3-CAM's at 0x0, the WROVER's at 0x1000) or, with none, plain
           MicroPython; copy the files the image hasn't built in (each
           checked on the board by SHA-256), write its config.py from the
           scrubbed template with your answers, restart;
  update   a board on a Stump image with this release's partition layout:
           the new image written in place (no erase), then the rest; on
           plain MicroPython: the files copied. config.py, the identity
           and the card are kept. An older layout is refused (an erase
           would give it a new identity);
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
RAW_BANNER = b"raw REPL; CTRL-B to exit\r\n>"
QUIET_WATCHDOG = "try:\n import machine\n machine.WDT(timeout=7200000).feed()\nexcept Exception:\n pass\n"
FEATURES = ["chat", "billboard", "files", "about"]
THEMES = ["paper", "amber", "phosphor", "oled"]
MODES = ["open", "hybrid", "mandatory"]
RADIO_BW = [7800, 10400, 15600, 20800, 31250, 41700, 62500, 125000, 250000, 500000]
# LaBuche's mesh: what a new Stump starts from (it must match the mesh), as in Arborist.
RADIO_DEFAULT = {"frequency": 868800000, "bandwidth": 125000, "sf": 8, "cr": 5, "txpower": 22}


# The Stump images (SandBox_Stump_On image/README.md): which chip each is for,
# where it goes, and the board's name for it (Arborist's IMAGE_FOR).
IMAGE_FOR = {"s3cam": {"chip": "esp32s3", "offset": "0x0", "board": "the Freenove ESP32-S3-CAM"},
             "wrover": {"chip": "esp32", "offset": "0x1000", "board": "an ESP32-WROVER (the original ESP32, with PSRAM)"}}
KIND_OF_CHIP = {v["chip"]: k for k, v in IMAGE_FOR.items()}
IMAGE_NAME = re.compile(r"^stump-(.+)-(s3cam|wrover)\.bin$")
# Less memory than this at the prompt: no PSRAM (a WROOM gives MicroPython
# ~110 KB, PSRAM megabytes): it can't run a Stump.
PSRAM_MIN = 512 * 1024


def image_head(d):
    """What the release's stump_image.py (next to its images) says:
    {release, partitions, frozen}, or None. Read, never run."""
    import ast
    try:
        with open(os.path.join(d, "stump_image.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError, ValueError):
        return None
    vals = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                vals[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    if not isinstance(vals.get("PARTITIONS"), str) or not isinstance(vals.get("FROZEN"), list):
        return None
    return {"release": vals.get("RELEASE", ""), "partitions": vals["PARTITIONS"], "frozen": vals["FROZEN"]}


def images_in(d, release=None):
    """{kind: path} of the Stump images in folder d (this release's, if given)."""
    out = {}
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        m = IMAGE_NAME.match(n)
        if m and (release is None or m.group(1) == release):
            out[m.group(2)] = os.path.join(d, n)
    return out


def not_frozen(files, frozen):
    """The files left to copy beside an image: those it hasn't built in (a
    copy of a frozen module on the filesystem would be loaded instead)."""
    f = set(re.sub(r"\.(py|mpy)$", "", n) for n in frozen or [])
    return [x for x in files if not re.search(r"\.(py|mpy)$", x[0]) or re.search(r"(^|/)(boot|main|config)\.py$", x[0])
            or re.sub(r"\.(py|mpy)$", "", x[0]) not in f]


# Never in a release's config template (a real Stump's names and passwords).
FORBIDDEN_IN_TEMPLATE = ("Bob's Glitch", "SalutComment", "TeK_Knoh", "'TeK'", "'LaBuche'", "Concierge")


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
        self.path = path
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
        # The release's Stump images next to it (1.0.0-beta.57 on), with their stump_image.py
        d = os.path.dirname(os.path.abspath(path))
        self.image_head = image_head(d)
        self.images = images_in(d, self.release) if self.image_head else {}

    def release_at_least(self, release):
        from .shelf import version_key
        return version_key(self.release) >= version_key(release)

    def image_for(self, chip):
        """(path, offset) of this release's Stump image for the chip, or (None, offset)."""
        kind = KIND_OF_CHIP.get(chip)
        return (self.images.get(kind), IMAGE_FOR[kind]["offset"]) if kind else (None, "0x0")

    def app(self):
        """[(path on the board, bytes, sha256)]"""
        return [(n[4:], d, s) for n, (d, s) in sorted(self.files.items()) if n.startswith("app/")]

    def app_bytes(self):
        return sum(len(d) for _, d, _ in self.app())


def default_copy():
    """The shelf's Stump the boards get unless another is chosen: Official, else Sandbox."""
    from . import shelf
    return shelf.best("stump", "official") or shelf.best("stump", "sandbox")


def find_bundle(d=None):
    """The Stump bundle in folder d (a shelf copy's), by default the default copy's."""
    if d is None:
        if os.environ.get("PROVISIONER_STUMP"):
            d = os.environ["PROVISIONER_STUMP"]
        else:
            c = default_copy()
            if not c:
                return None
            d = c["dir"]
    try:
        names = sorted(f for f in os.listdir(d) if f.lower().startswith("stump-") and f.endswith(".bundle"))
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
    out = repl.run("import sys, os\nv=getattr(sys.implementation,'_mpy',0)\n"
                   "print('INFO', '.'.join(str(x) for x in sys.implementation.version[:3]), "
                   "'%d.%d' % (v & 0xff, (v >> 8) & 3), os.uname().machine.replace(' ', '_'))\n")
    m = re.search(r"INFO (\S+) (\S+) ?(\S*)", out)
    return {"release": m.group(1), "mpy": m.group(2), "machine": m.group(3).replace("_", " ")} if m else \
        {"release": "", "mpy": "", "machine": ""}


def chip_of(machine):
    """"esp32s3" or "esp32" from MicroPython's os.uname().machine."""
    m = (machine or "").upper().replace("-", "")
    return "esp32s3" if "ESP32S3" in m else "esp32" if "ESP32" in m else ""


def board_image(repl):
    """What a board running a Stump image says of it (stump_image.py, frozen
    in): {release, partitions, frozen}, or None (plain MicroPython)."""
    out = repl.run("import json\ntry:\n import stump_image as s\n print('IMG'+json.dumps({'release':s.RELEASE,"
                   "'partitions':s.PARTITIONS,'frozen':s.FROZEN}))\nexcept ImportError:\n print('IMGnone')\n")
    m = re.search(r"IMG(\{.*\})", out)
    try:
        return json.loads(m.group(1)) if m else None
    except ValueError:
        return None


def memory(repl):
    """Its memory at the prompt (bytes), or None: PSRAM gives megabytes."""
    m = re.search(r"MEM(\d+)", repl.run("import gc\ngc.collect()\nprint('MEM%d' % (gc.mem_free() + gc.mem_alloc()))\n"))
    return int(m.group(1)) if m else None


def remove_frozen_copies(repl, frozen):
    """Old copies of built-in modules removed from its filesystem (they'd be
    loaded instead), then the packages' folders left empty. How many went."""
    names = sorted(set(re.sub(r"\.(py|mpy)$", "", n) for n in frozen or []))
    dirs = sorted(set(n.rsplit("/", 1)[0] for n in frozen or [] if "/" in n), key=lambda d: -d.count("/"))
    out = repl.run("import os\nn=0\nfor m in %s:\n for p in (m+'.py',m+'.mpy'):\n  try:\n   os.remove(p)\n   n+=1\n"
                   "  except OSError:\n   pass\nfor d in %s:\n try:\n  if not os.listdir(d):\n   os.rmdir(d)\n"
                   " except OSError:\n  pass\nprint('GONE%%d' %% n)\n" % (json.dumps(names), json.dumps(dirs)), 60)
    m = re.search(r"GONE(\d+)", out)
    return int(m.group(1)) if m else 0


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
        "CHAIN_ENABLED", "CHAIN_UPLINK_SSID", "CHAIN_UPLINK_PASS", "CHAIN_SUBNET", "CHAIN_CHANNEL", "CHAIN_SECRET",
        "CHAIN_PARENT_IP"]
# The Heltec on the Stump's own hotspot: .200, past what the hotspot hands out
# (.2 before 1.0.0-beta.58, which a phone could take first); on the router,
# .222 for the first, its own for each next (Arborist's HELTEC_ON_HOTSPOT, HELTEC_FIRST).
HELTEC_ON_HOTSPOT, HELTEC_FIRST = 200, 222
# A chain member over the router with its home Wi-Fi password not typed again:
# the board's own WIFI_PASS is copied into CHAIN_UPLINK_PASS there (never read back).
FROM_WIFI_PASS = "\u0000WIFI_PASS"


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
        "if ch.get('CHAIN_UPLINK_PASS')==%s:\n import config as _c\n ch['CHAIN_UPLINK_PASS']=ch.get('WIFI_PASS',"
        "getattr(_c,'WIFI_PASS',''))\n" % py(FROM_WIFI_PASS) +
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
    # The admin password (/admin), required for a new Stump (1.0.0-beta.58);
    # the fserv bot takes the same one unless it has its own ("botpw": "own").
    # Blank means leave it (the template's blank, or what it has now).
    pw, pw2 = a.get("pw") or "", a.get("pw2") or ""
    if pw or pw2:
        if len(pw) < 4 or len(pw) > 64:
            return no("The admin password: 4 to 64 characters.")
        if pw != pw2:
            return no("The two admin passwords aren't the same.")
        v["AUTH_ADMIN_PASSWORD"] = pw
    opw = a.get("opw") or ""
    if a.get("botpw", "same") != "own":
        if v.get("AUTH_ADMIN_PASSWORD"):
            v["FSERVBOT_OP_PASSWORD"] = v["AUTH_ADMIN_PASSWORD"]
    elif opw:
        if len(opw) < 4 or len(opw) > 64:
            return no("The fserv bot's password: 4 to 64 characters.")
        v["FSERVBOT_OP_PASSWORD"] = opw
    if a.get("requireAdmin") and not v.get("AUTH_ADMIN_PASSWORD") and not a.get("hasPw"):
        return no("Set an admin password (for /admin).")
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
        v["CHAIN_ENABLED"], v["CHAIN_SECRET"], v["CHAIN_PARENT_IP"] = True, secret, ""
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
    elif chain == "lan":
        # A member over the router (chain.py's CHAIN_PARENT_IP, 1.0.0-beta.57): it
        # stays on the home Wi-Fi and links to the first Stump there.
        if a.get("lanOk") is False:
            return no("This Stump release is older than 1.0.0-beta.57: no chain over the router (a newer one on the shelf).")
        secret = (a.get("secret") or "").strip()
        if not secret:
            return no("Over the home Wi-Fi the first Stump only takes Stumps with the chain secret: type it in.")
        if len(secret) > 64 or re.search(r"['\"\\]", secret) or _ctl(secret):
            return no("The chain secret: at most 64 characters, no quotes or backslashes.")
        if not ssid:
            return no("Joining over the home Wi-Fi needs the home Wi-Fi's name.")
        pip = (a.get("parentIp") or "").strip()
        if not is_ip(pip):
            return no("The first Stump's address on the home Wi-Fi looks like 192.168.0.173.")
        s = str(a.get("subnet") or "").strip()
        if not s.isdigit() or not 5 <= int(s) <= 254:
            return no("This Stump's number in the chain: 5 to 254, a different one on each Stump.")
        subnet = int(s)
        v.update(CHAIN_ENABLED=True, CHAIN_SECRET=secret, CHAIN_PARENT_IP=pip, CHAIN_UPLINK_SSID=ssid,
                 CHAIN_UPLINK_PASS=a.get("wpass") or FROM_WIFI_PASS, CHAIN_SUBNET=subnet, CHAIN_CHANNEL=0)
    else:
        v["CHAIN_ENABLED"] = False
    radio = a.get("radio") or "none"
    on_ap = "192.168.%d.%d" % (subnet, HELTEC_ON_HOTSPOT)
    if radio == "lan":
        host = (a.get("hhost") or "").strip()
        if not is_ip(host):
            return no("The Heltec's address looks like 192.168.0.222.")
        if not ssid:
            return no("A Heltec on the home Wi-Fi needs the home Wi-Fi's name.")
        if not 2 <= int(host.split(".")[3]) <= 254:
            return no("The Heltec's address: its last number from 2 to 254 (.222 is a good one).")
        v["HELTEC"] = {"enabled": True, "host": host, "port": 7633}
    elif radio == "ap":
        v["HELTEC"] = {"enabled": True, "host": on_ap, "port": 7633}
    else:
        hh = a.get("hhost") or ""
        v["HELTEC"] = {"enabled": False, "host": hh if is_ip(hh) else on_ap, "port": 7633}
    return {"values": v, "warn": warn}


def is_ip(s):
    return bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}$", s or "")) and all(int(x) <= 255 for x in s.split("."))


def answers_from(c):
    """What read_settings found -> the form's answers."""
    chain = "none" if not c.get("CHAIN_ENABLED") else "lan" if c.get("CHAIN_PARENT_IP") else \
        "member" if c.get("CHAIN_UPLINK_SSID") else "first"
    subnet = c.get("CHAIN_SUBNET") if chain in ("member", "lan") else 4
    h = c.get("HELTEC") or {}
    # On its hotspot: .200, or .2 as before 1.0.0-beta.58 (saved again as .200).
    radio = "none" if not h.get("enabled") else ("ap" if h.get("host") in (
        "192.168.%s.%d" % (subnet, HELTEC_ON_HOTSPOT), "192.168.%s.2" % subnet) else "lan")
    return {"name": c.get("NODE_NAME") or "", "bot": c.get("BOT_NAME") or "BarKeep",
            "greeting": c.get("MESH_GREETING") or "", "ssid": c.get("WIFI_SSID") or "", "radio": radio,
            "hhost": h.get("host", "") if radio == "lan" else "",
            "features": c.get("FEATURES") if isinstance(c.get("FEATURES"), list) else FEATURES[:3],
            "theme": c.get("THEME") or "paper", "mode": c.get("AUTH_MODE") or "open", "hotspot": c.get("SSID_NAME") or "",
            "chain": chain, "channel": c.get("CHAIN_CHANNEL") or 11, "upSsid": c.get("CHAIN_UPLINK_SSID") or "",
            "subnet": c.get("CHAIN_SUBNET") or 5,
            "secret": c.get("CHAIN_SECRET") or "", "parentIp": c.get("CHAIN_PARENT_IP") or "",
            "upPass": "" if chain == "lan" else c.get("CHAIN_UPLINK_PASS") or "",
            "botpw": "own" if c.get("HAS_OP_PASSWORD") else "same", "hasPw": bool(c.get("HAS_ADMIN_PASSWORD")),
            "hasOpPw": bool(c.get("HAS_OP_PASSWORD")), "hasWifiPass": bool(c.get("HAS_WIFI_PASS"))}


IP = r"(\d{1,3}(?:\.\d{1,3}){3})"
LISTEN_S = float(os.environ.get("PROVISIONER_LISTEN_S", "90"))     # a setup listens this long at most


def boot_summary(text):
    """What a Stump says as it starts -> {release, micropython, serving,
    problems, notes, home, home_why, heap_kb, chain, heltec} (Arborist's
    bootSummary, 1.0.0-beta.60: its address on the home Wi-Fi or why it
    isn't on it, its place in the chain, its Heltec)."""
    out = {"release": None, "micropython": None, "serving": False, "problems": [], "notes": [],
           "home": None, "home_why": None, "heap_kb": None,
           "chain": {"root": False, "linked": None, "no_answer": None, "below": [], "refused": []},
           "heltec": {"ok": None, "fail": None}}
    m = re.search(r"Project Stump -- (.+?) \(([^)]+)\)", text)
    if m:
        out["release"] = m.group(2)
    m = re.search(r"MicroPython (v[\w.\-]+)", text)
    if m:
        out["micropython"] = m.group(1)
    out["serving"] = "[web] serving" in text
    m = (re.search(r"Connected! IP: " + IP, text) or re.search(r"over the home Wi-Fi: " + IP, text)
         or re.search(r"and on " + IP + r" \(the Wi-Fi it joined\)", text))
    if m:
        out["home"] = m.group(1)
    else:
        m = re.search(r"WiFi connection timed out: ([^)\n]+)", text)
        if m:
            out["home_why"] = m.group(1).strip()
        elif re.search(r"WiFi connection timed out|WiFi unavailable|isn't joined yet", text):
            out["home_why"] = "it didn't get on within its time"
    m = re.search(r"\[mem\] at boot: heap (\d+) KB", text)
    if m:
        out["heap_kb"] = int(m.group(1))
    c = out["chain"]
    c["root"] = "[chain] root on" in text
    m = re.search(r"Chain: linked to the Stump above at " + IP, text)
    c["linked"] = m.group(1) if m else None
    m = re.search(r"Chain: no answer from the Stump above at " + IP, text)
    c["no_answer"] = m.group(1) if m else None
    for ip in re.findall(r"Chain: " + IP + r" joined below this one", text):
        if ip not in c["below"]:
            c["below"].append(ip)
    for ip in re.findall(r"Chain hello from " + IP + r" refused", text):
        if ip not in c["refused"]:
            c["refused"].append(ip)
    m = re.search(r"WiFi Serial connected to " + IP, text)
    if m:
        out["heltec"]["ok"] = m.group(1)
    else:
        m = re.search(r"WiFi Serial (?:initial )?connect failed: ([^\n]+)", text)
        out["heltec"]["fail"] = m.group(1).strip() if m else None
    for line in text.replace("\r", "").split("\n"):
        if re.search(r"Traceback|Error|FAILED|rescue start|couldn't|not armed", line, re.I):
            if len(out["problems"]) < 12:
                out["problems"].append(line.strip())
        elif re.search(r"WiFi unavailable|\[watchdog\] armed|\[chain\]|\[radio\]|\[sd\]", line, re.I):
            if len(out["notes"]) < 12:
                out["notes"].append(line.strip())
    return out


def _member(v):
    return bool(v.get("CHAIN_ENABLED") and (v.get("CHAIN_UPLINK_SSID") or v.get("CHAIN_PARENT_IP")))


def enough_for(v):
    """What a setup waits to hear: the home Wi-Fi (joined, or why not), a
    member's link (made, or unanswered), the Heltec (reached), as Arborist."""
    home, member = bool(v.get("WIFI_SSID")), _member(v)
    heltec, first = bool((v.get("HELTEC") or {}).get("enabled")), bool(v.get("CHAIN_ENABLED")) and not _member(v)

    def enough(s):
        c = s["chain"]
        return (s["serving"] and (not home or s["home"] or s["home_why"]) and (not member or c["linked"] or c["no_answer"])
                and (not heltec or s["heltec"]["ok"]) and (not first or not home or s["home"]))
    return enough


def start_report(s, v, default_ssid="Stump"):
    """What it said as it started, for a setup: ([(what, says, "ok"|"warn"|"err"|"")], [notes])."""
    rows, notes = [], []
    member, first = _member(v), bool(v.get("CHAIN_ENABLED")) and not _member(v)
    ap = "192.168.%s.1" % (v.get("CHAIN_SUBNET") if member else 4)
    ssid = v.get("SSID_NAME") or default_ssid
    rows.append(("Its pages", "up" if s["serving"] else "not up yet", "ok" if s["serving"] else "warn"))
    rows.append(("Its own Wi-Fi", "\u201c%s\u201d · http://%s/" % (ssid, ap), ""))
    if v.get("WIFI_SSID"):
        if s["home"]:
            rows.append(("Home Wi-Fi", "http://%s/ · its admin page /admin" % s["home"], "ok"))
        elif s["home_why"]:
            rows.append(("Home Wi-Fi", "not joined (\u201c%s\u201d): %s" % (v["WIFI_SSID"], s["home_why"]), "err"))
        else:
            rows.append(("Home Wi-Fi", "not joined yet (\u201c%s\u201d)" % v["WIFI_SSID"], "warn"))
    c = s["chain"]
    if member:
        if c["linked"]:
            rows.append(("The chain", "linked to the Stump above at %s" % c["linked"], "ok"))
        elif c["no_answer"]:
            rows.append(("The chain", "no answer from %s: the first Stump's address, the same secret?" % c["no_answer"],
                         "err"))
        else:
            rows.append(("The chain", "not linked yet (to %s)" % (v.get("CHAIN_PARENT_IP") or "the Stump it joins"),
                         "warn"))
    if first and c["below"]:
        rows.append(("The chain", "%d Stump%s linked below it" % (len(c["below"]), "s" if len(c["below"]) > 1 else ""),
                     "ok"))
    if c["refused"]:
        rows.append(("Refused", "%s tried to join with another chain secret" % ", ".join(c["refused"]), "warn"))
    h = v.get("HELTEC") or {}
    if h.get("enabled"):
        if s["heltec"]["ok"]:
            rows.append(("Its Heltec", "answered at %s" % s["heltec"]["ok"], "ok"))
        else:
            rows.append(("Its Heltec", "nothing at %s yet%s: is it on, set to that address?" % (
                h.get("host"), " (%s)" % s["heltec"]["fail"] if s["heltec"]["fail"] else ""), "warn"))
    if v.get("WIFI_SSID") and not s["home"] and "wasn't found" in (s["home_why"] or ""):
        notes.append("This board only sees 2.4 GHz Wi-Fi: a 5 GHz-only network can't be joined.")
    if first and v.get("WIFI_SSID") and s["home"]:
        notes.append("For the next Stumps (\u201cJoins the first over the router\u201d): its address %s and the chain "
                     "secret. Reserve %s for it on the router." % (s["home"], s["home"]))
    elif first:
        notes.append("For the next Stumps: its Wi-Fi \u201c%s\u201d and the chain secret." % ssid)
    if h.get("enabled"):
        notes.append("Its Heltec: give it the address %s in its own setup%s" % (
            h.get("host"), "." if re.match(r"^192\.168\.\d+\.200$", h.get("host") or "") else
            "; the next Heltec on the router takes another one."))
    if not s["serving"] or (v.get("WIFI_SSID") and not s["home"]):
        notes.append("It may just need longer: Check it starts listens again.")
    return rows, notes


def listen(repl, open_link, log, secs, enough):
    """Restarts it and listens until enough(summary) or secs (a board on its
    own USB comes back as a new port: opened again). The summary, and every
    link it opened (the caller closes them)."""
    chunks, links = [], [repl.link]
    repl.text = []
    restart(repl)
    end = time.time() + secs
    s = boot_summary("")
    while time.time() < end:
        time.sleep(0.5)
        if repl._dead():
            chunks += repl.text
            try:
                link = open_link()
                links.append(link)
                repl = Repl(link, log)
            except Exception as e:
                log and log("reopening: %s" % e)
                time.sleep(1)
                continue
        s = boot_summary(b"".join(chunks + repl.text).decode("utf-8", "replace"))
        if enough(s):
            time.sleep(1.5)
            break
    text = b"".join(chunks + repl.text).decode("utf-8", "replace")
    for line in text.replace("\r", "").split("\n")[-40:]:
        if line.strip():
            log(line)
    return boot_summary(text), links


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


def make(bundle, answers, open_link, flash, step, progress, log, update=False, chip="esp32s3", report=None):
    """A new Stump (erases the board) or an update. flash(path, offset, erase)
    writes an image (erase=False: in place, the filesystem kept). chip: what
    esptool read ("esp32s3": the CAM, "esp32": a WROVER). A new Stump is
    listened to as it starts (up to LISTEN_S): report gets its rows. (ok, message)."""
    s = rad = None
    heard = None
    note = ""
    if not update:
        s = settings_from(dict(answers, requireAdmin=True))
        if s.get("error"):
            return False, s["error"]
        if (answers.get("radio") or "none") != "none":
            rad = dict(RADIO_DEFAULT)
        img, offset = bundle.image_for(chip)
        if img:
            step("Erasing the board, writing the Stump image %s" % bundle.release)
            ok, msg = flash(img, offset, True)
        elif chip != "esp32s3":
            return False, ("Stump %s has no image for %s: it takes a Stump image (1.0.0-beta.57 on). A newer Stump "
                           "onto the shelf: This handheld -> The Stump." % (bundle.release, IMAGE_FOR["wrover"]["board"]))
        else:
            step("Erasing the board, writing MicroPython %s" % bundle.micropython)
            with tempfile.TemporaryDirectory(prefix="provisioner-mp-") as tmp:
                mp = os.path.join(tmp, "micropython.bin")
                with open(mp, "wb") as f:
                    f.write(bundle.files["micropython.bin"][0])
                ok, msg = flash(mp, "0x0", True)
        if not ok:
            return False, msg
        step("Restarting it")
    step("Connecting")
    try:
        repl = ready_repl(open_link, log)
    except StumpError as e:
        if update or chip == "esp32s3":
            raise
        # An image built for PSRAM may not start at all on a board without it.
        raise StumpError("%s If it's an ESP32-WROOM (no PSRAM): a Stump needs an ESP32-WROVER." % e)
    links = [repl.link]
    try:
        info = board_info(repl)
        log("MicroPython %s, .mpy %s, %s" % (info["release"], info["mpy"], info["machine"] or "?"))
        files = bundle.app()
        if not update:
            mem = memory(repl)
            if mem is not None and mem < PSRAM_MIN:
                return False, ("This board has only %d KB of memory: no PSRAM (an ESP32-WROOM, or a CAM without it). "
                               "A Stump needs an ESP32-WROVER or the Freenove ESP32-S3-CAM." % (mem // 1024))
            im = board_image(repl)
            if im:
                files = not_frozen(files, im.get("frozen"))
                log("the Stump image %s: %d modules built in" % (im.get("release"), len(im.get("frozen") or [])))
        else:
            if not has_stump(repl):
                return False, "There's no Stump on this board to update (no config.py): choose Make a Stump."
            cur = board_image(repl)
            img, offset = bundle.image_for(chip_of(info["machine"]) or chip)
            head = bundle.image_head or {}
            if cur and img and cur.get("partitions") == head.get("partitions"):
                if cur.get("release") == bundle.release:
                    log("it runs the Stump image %s already" % bundle.release)
                else:
                    # In place: the image's bootloader, partition table and
                    # application; the filesystem after them (settings,
                    # identity, chat) kept.
                    step("Writing the Stump image %s in place" % bundle.release)
                    log("it runs the Stump image %s: the new one written in place" % cur.get("release"))
                    repl.link.close()
                    ok, msg = flash(img, offset, False)
                    if not ok:
                        return False, msg
                    step("Connecting")
                    repl = ready_repl(open_link, log)
                    links.append(repl.link)
                now = board_image(repl) or {}
                files = not_frozen(files, now.get("frozen"))
                gone = remove_frozen_copies(repl, now.get("frozen"))
                if gone:
                    log("%d old copies of built-in modules removed" % gone)
            elif cur and img:
                return False, ("Its Stump image has an older layout (%s): updating it means erasing it. Choose Make a "
                               "Stump (it erases the board: a new identity on the mesh)." % cur.get("partitions"))
            else:
                # Plain MicroPython (or no image for it in this release): the files copied, as before.
                if bundle.mpy and info["mpy"] != bundle.mpy and not cur:
                    return False, ("This board has MicroPython %s; Stump %s needs %s. Choose Make a Stump (it erases "
                                   "the board: it gets a new identity)." % (info["release"], bundle.release,
                                                                          bundle.micropython))
                if img and not cur:
                    note = (" It runs plain MicroPython, so the files were copied; made again it gets the Stump "
                            "image (faster, lighter on memory; it erases the board).")
        step("Copying the Stump %s" % bundle.release)
        t0 = time.time()

        def prog(done, total, path):
            progress(int(done * 100 / max(1, total)))
            sec = time.time() - t0
            if path and done and sec > 5:
                left = int((total - done) / (done / sec))
                log("%d of %d KB · about %s left · %s" % (done // 1024, total // 1024,
                                                           "%d min" % (left // 60) if left > 90 else "%d s" % left, path))
        upload(repl, files, prog)
        if not update:
            step("Its settings")
            tpl = bundle.template.encode()
            upload(repl, [("config.py", tpl, hashlib.sha256(tpl).hexdigest())])
            write_settings(repl, s["values"])
            if rad and not write_radio(repl, rad):
                log("note: the radio settings weren't saved to the board")
            step("Restarting it, listening to it start")
            heard, more = listen(repl, open_link, log, LISTEN_S, enough_for(s["values"]))
            links += more
        else:
            step("Restarting it")
            restart(repl)
    finally:
        for link in links:
            link.close()
    if update:
        return True, "Updated to %s; its settings, identity and card kept. It restarts.%s" % (bundle.release, note)
    v = s["values"]
    _report(report, heard, v, bundle.default_ssid)
    return True, ("Your Stump is %s. From a phone, join the Wi-Fi \u201c%s\u201d: a page opens. /admin takes the "
                  "password you chose." % ("running" if heard["serving"] else "starting (about a minute the first time)",
                                           v.get("SSID_NAME") or bundle.default_ssid))


def _report(report, heard, v, default_ssid):
    if report is not None and heard is not None:
        rows, notes = start_report(heard, v, default_ssid)
        report.extend(rows + [("", n, "") for n in notes])


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


def save_job(answers, open_link, step, log, report=None, default_ssid="Stump"):
    s = settings_from(answers)
    if s.get("error"):
        return False, s["error"]
    step("Connecting")
    repl = ready_repl(open_link, log)
    links = [repl.link]
    try:
        if not has_stump(repl):
            return False, "There's no Stump on this board (no config.py)."
        step("Saving its settings")
        write_settings(repl, s["values"])
        step("Restarting it, listening to it start")
        heard, more = listen(repl, open_link, log, LISTEN_S, enough_for(s["values"]))
        links += more
    finally:
        for link in links:
            link.close()
    _report(report, heard, s["values"], default_ssid)
    return True, "Saved; config.py.bak kept on the board. It %s with them." % (
        "runs" if heard["serving"] else "restarts")


def check_job(open_link, step, log, secs=60.0, report=None):
    step("Restarting it, listening")
    repl = ready_repl(open_link, log)
    links = [repl.link]
    try:
        b, more = listen(repl, open_link, log, secs, lambda s: s["serving"])
        links += more
    finally:
        for link in links:
            link.close()
    if report is not None:
        report.append(("Stump", b["release"] or "didn't say", "" if b["release"] else "warn"))
        report.append(("Its pages", "up" if b["serving"] else "not up within %d s" % secs, "ok" if b["serving"] else "err"))
        if b["home"]:
            report.append(("Home Wi-Fi", "http://%s/" % b["home"], "ok"))
        elif b["home_why"]:
            report.append(("Home Wi-Fi", "not joined: %s" % b["home_why"], "err"))
        c = b["chain"]
        if c["linked"]:
            report.append(("The chain", "linked to the Stump above at %s" % c["linked"], "ok"))
        elif c["no_answer"]:
            report.append(("The chain", "no answer from %s: its address, or the chain secret?" % c["no_answer"], "err"))
        if c["below"]:
            report.append(("The chain", "%d linked below it" % len(c["below"]), "ok"))
        if b["heltec"]["ok"]:
            report.append(("Its Heltec", "answered at %s" % b["heltec"]["ok"], "ok"))
        elif b["heltec"]["fail"]:
            report.append(("Its Heltec", "no answer: %s" % b["heltec"]["fail"], "warn"))
    if b["serving"]:
        msg = "It started: Stump %s on MicroPython %s, serving." % (b["release"] or "?", b["micropython"] or "?")
        if b["problems"]:
            msg += " But: " + b["problems"][0]
        return not b["problems"], msg
    return False, ("It didn't get to serving in %d s. %s" % (secs, b["problems"][0] if b["problems"]
                                                               else "Nothing went wrong that it said."))
