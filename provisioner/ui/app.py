"""The Provisioner's screens: the boards on the hub, what each can be given,
asking first, flashing with progress, a board's serial log, making a Stump
(a form, FireFly's keyboard), and the S3 USB Wi-Fi adapter's networks.

    BOARDS  --A-->  (identify)  -->  JOBS  --A-->  ask  -->  RUN  --B-->  JOBS
       |\\--Y--> LOG                      |\\--> LOG
       |                                 \\--> FORM (a Stump's answers) --> ask --> RUN
       \\--A on "S3 USB Wi-Fi"-->  WIFI (networks; A join, a password on the keyboard; Y forget)

Nothing touches a board until you choose it: identifying a board resets it,
so a port another program has open (the Stump and its Heltec) asks first.
"""

import os
import threading
import time

from .. import boards, catalog, files, flasher, handheld, images, installers, packs, s3wifi, shelf, stump
from ..seriallog import SerialLog
from . import keyboard
from .keyboard import Keyboard
from .sdl import F16, F20, F24, F30B, rgb

BG, PANEL, PANEL2, BORDER = rgb("1b1512"), rgb("2a2119"), rgb("221b15"), rgb("493c2e")
EMBER, EMBER_BRIGHT, TEXT, MUTED = rgb("d97a3a"), rgb("f0a050"), rgb("ecdfc8"), rgb("9c8d76")
ERROR, OK = rgb("e07a5a"), rgb("9cb876")
STUMP_BOARDS = ("esp32s3", "esp32")      # boards.py ids: the Freenove ESP32-S3-CAM, a classic ESP32 (a WROVER)
TOP = 96                                   # under the header
W = H = 720                                # the canvas: set from the display (set_canvas)
BOT = H - 38                               # the hints bar's top


def set_canvas(size):
    """The canvas the screens are laid out on (the display's: 600x400 to 854x720 on these handhelds)."""
    global W, H, BOT
    W, H = size
    BOT = H - 38
    keyboard.set_canvas(size)


def fits(top, rh, gap=6):
    """How many rows rh high fit from top to the hints bar."""
    return max(1, (BOT - gap - top) // rh)


def window(sel, n, vis, ahead=1):
    """The first row shown, so sel is in view with `ahead` rows after it when there are."""
    return max(0, min(sel - (vis - 1 - ahead), n - vis))
THEME = {"BG": BG, "PANEL": PANEL, "PANEL2": PANEL2, "BORDER": BORDER, "EMBER": EMBER, "TEXT": TEXT, "MUTED": MUTED}
CHAINS = [("none", "No chain"), ("first", "First Stump of a chain"), ("lan", "Joins the first over the router"),
          ("member", "Joins a Stump's own Wi-Fi")]
BOTPW = [("same", "The same password"), ("own", "Its own password")]
RADIOS = [("ap", "Heltec on its own Wi-Fi"), ("lan", "Heltec on the home Wi-Fi"), ("none", "No LoRa radio")]
HELTECS = [("usb", "Heltec on USB"), ("ble", "Heltec over Bluetooth"), ("none", "No Heltec")]
YESNO = [("no", "No"), ("yes", "Yes")]


class Task:
    """Something slow (esptool) in the background; the screen shows its state."""

    def __init__(self, title, fn):
        self.title, self.step, self.pct = title, "Starting", None
        self.lines, self.done, self.ok, self.msg, self.result = [], False, False, "", None
        self.report = []                             # [(what, says, "ok"|"warn"|"err"|"")]: a Stump's start, heard
        self._lock = threading.Lock()
        threading.Thread(target=self._run, args=(fn,), daemon=True).start()

    def _run(self, fn):
        try:
            self.ok, self.msg, self.result = fn(self)
        except Exception as e:                       # never leave the screen waiting
            self.ok, self.msg = False, "Stopped: %s" % e
        self.done = True

    def line(self, s):
        with self._lock:
            self.lines.append(s)
            del self.lines[:-200]

    def tail(self, n):
        with self._lock:
            return self.lines[-n:]


def here_status():
    """This handheld's own Stump (the R36MAX runs one), from its public
    /node.json and /chain.json on localhost: {release, name, chain}, or
    {"none": True}."""
    import json
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for port in (80, 8080):
        try:
            n = json.load(op.open("http://127.0.0.1:%d/node.json" % port, timeout=1))
        except Exception:
            continue
        chain = ""
        try:
            c = json.load(op.open("http://127.0.0.1:%d/chain.json" % port, timeout=1))
            if c.get("enabled"):
                chain = "chain %s" % (c.get("role") or "")
        except Exception:
            pass
        return {"release": n.get("release"), "name": n.get("name"), "chain": chain.strip()}
    return {"none": True}


def wrap(d, fid, text, width):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if cur and d.text_width(fid, t) > width:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


class App:
    def __init__(self, display, version="", firmware_dir=None, ports_fn=None, users_fn=None):
        self.d = display
        set_canvas(getattr(display, "size", (720, 720)))
        self.version = version
        self.entries = catalog.load(firmware_dir)
        self.ports_fn = ports_fn or boards.list_ports
        self.users_fn = users_fn or boards.port_users
        self.unbound_fn = boards.unbound
        self.nodriver = []              # USB-serial chips plugged in with no driver on this system
        self.screen = "boards"
        self.ports, self.sel, self.jsel = [], 0, 0
        self.known = {}                 # port -> {"board": {...}, "info": {...}} once identified
        self.cur = None                 # the port chosen
        self.confirm = None             # {"title", "lines", "danger", "yes", "go", "choice"}
        self.task = None
        self.log = None
        self.toast_text, self.toast_until = "", 0.0
        self.next_scan = 0.0
        self.running = True
        self.bundle_dir = None
        self._bundle = False            # loaded on first use (None: there's none)
        self.form = None                # {"mode": "new"|"settings", "a": answers, "sel": row}
        self.kb = None                  # the keyboard, while typing (and the field it fills)
        self.kb_key = None
        self.open_link = lambda port: stump.SerialLink(port)
        self.packs_fn = packs.bundled
        self.roots_fn = files.roots
        self._packs = None
        self.fb = None                  # the file browser (+ From File)
        self.open_serial_log = SerialLog
        self.log_dir = None             # None: seriallog.export_dir()
        self.logv = {"frozen": None, "cur": 0, "mark": None}
        self.here = None                # this handheld's own Stump: {release, name, chain} or {"none": True}
        self.here_fn = here_status
        self.next_here = 0.0
        self.kb_done = None             # what the keyboard's text goes to (None: the form)
        self.adapter = None             # the S3 USB Wi-Fi adapter's status, while it's plugged in
        self.adapter_port = None        # its control port (a serial port on the same cable)
        self.adapter_fn = s3wifi.status     # (port) -> status or None
        self.internet_fn = s3wifi.internet
        self.address_fn = s3wifi.handheld_address
        self.next_adapter = 0.0
        self.wifi = None                # the WIFI screen's state
        self.handheld_fn = handheld.state   # () -> this handheld's Stump row's state, or None (no row)
        self.handheld_run = handheld.run
        self.hh_inst = None             # the handheld's Stump's installer chosen (a shelf copy's, a clone)
        self.password_state_fn = handheld.password_state     # (folder, key=admin) -> SET / DEFAULT / EMPTY / NONE
        self.access_state_fn = handheld.access_state         # (folder) -> what /admin takes: SET / DEFAULT / EMPTY
        self.set_password_fn = handheld.set_password
        self.current_passwords_fn = handheld.current_passwords
        self.clear_repo_admin_fn = handheld.clear_repo_admin
        self.clones = True              # offer ~/SandBox_RK3326_Stump, ~/R36MAX-Stump when there
        self.online_fn = shelf.online   # (product, channel) -> the newest release online
        self.fetch_fn = shelf.fetch
        self.online_sync = False
        self.online, self.net, self.net_error, self.net_when = {}, None, "", 0.0
        self.firefly_fn = installers.firefly_installed
        self.marks_fn = installers.marks
        self.app_dir = installers.app_dir()
        self.prod, self.psel, self.prod_back = None, 0, "handheld"
        self.lib = {"sel": 0, "checked": set()}   # the Library: everything this Provisioner carries
        self.stump_src = None           # the Stump the boards get, if not the shelf's default (Official)
        self.handheld = None
        self.next_handheld = 0.0
        self.hsel = 0

    def bundle(self):
        if self._bundle is False:
            try:
                self._bundle = stump.find_bundle(self.bundle_dir or self.stump_dir())
            except Exception:
                self._bundle = None
        return self._bundle

    # -- state --
    def toast(self, text, secs=2.5):
        self.toast_text, self.toast_until = text, time.time() + secs

    def scan(self):
        if self.here_fn and time.time() >= self.next_here:
            self.next_here = time.time() + 10
            threading.Thread(target=lambda: setattr(self, "here", self.here_fn()), daemon=True).start()
        if self.adapter_fn and self.adapter_port and self.screen != "wifi" and time.time() >= self.next_adapter:
            self.next_adapter = time.time() + 3
            threading.Thread(target=self._poll_adapter, daemon=True).start()
        if self.screen == "wifi":
            self.wifi_refresh()
        if self.handheld_fn and time.time() >= self.next_handheld:
            self.next_handheld = time.time() + 5
            try:
                self.handheld = self.handheld_fn()
            except Exception:
                self.handheld = None
            self.sel = min(self.sel, max(0, len(self.rows()) - 1))
        if time.time() < self.next_scan:
            return
        self.next_scan = time.time() + 1.0
        ports = self.ports_fn()
        try:
            self.nodriver = self.unbound_fn() if self.unbound_fn else []
        except Exception:
            self.nodriver = []
        # the S3 USB Wi-Fi adapter's control port isn't a board to flash: it's the adapter's row
        port = s3wifi.find(ports)
        ports = [p for p in ports if p["port"] != port]
        if port != self.adapter_port:
            self.adapter_port, self.next_adapter = port, 0.0
            if not port:
                self.adapter = None
                if self.screen == "wifi" and self.wifi:
                    self.wifi["gone"] = True
        for p in ports:
            p["users"] = self.users_fn(p["port"])
        gone = set(self.known) - set(p["port"] for p in ports)
        for g in gone:                              # unplugged: forget what it was
            self.known.pop(g, None)
        if self.cur and self.cur["port"] in gone and self.screen in ("jobs", "log"):
            self.stop_log()
            self.screen = "boards"
            self.toast("The board was unplugged")
        new = [p["port"] for p in ports if p["port"] not in set(q["port"] for q in self.ports)]
        if self.ports and new:
            self.toast("Board plugged in: %s" % new[0])
        self.ports = ports
        self.sel = min(self.sel, max(0, len(self.rows()) - 1))

    def _poll_adapter(self):
        st = self.adapter_fn(self.adapter_port)
        if st and not self.adapter:
            self.toast("S3 USB Wi-Fi adapter plugged in")
        self.adapter = st
        self.sel = min(self.sel, max(0, len(self.rows()) - 1))

    def rows(self):
        """The BOARDS screen's rows: the Wi-Fi adapter (when it's there), the ports,
        then this handheld's own Stump (on ArkOS / dArkOS)."""
        return (([{"adapter": True}] if self.adapter else []) + self.ports +
                ([{"handheld": True}] if self.handheld else []))

    def jobs(self):
        """The rows of the JOBS screen for the current board."""
        b = self.known.get(self.cur["port"], {}).get("board", {})
        rows = []
        if b.get("id") in STUMP_BOARDS:        # the Freenove CAM, or a WROVER: a Stump
            rows.append({"kind": "src_stump"})
            rows += [{"kind": k} for k in ("stump_new", "stump_update", "stump_settings", "stump_check")]
            rows += [{"kind": "pack", "path": p, "plan": plan, "error": err} for p, plan, err in self.bundled_packs()]
        rows += [{"kind": "fw", "entry": e} for e in catalog.for_board(self.entries, b)]
        rows.append({"kind": "fromfile"})
        rows.append({"kind": "log"})
        rows.append({"kind": "erase"})
        return rows

    def stump_copy(self):
        """The Stump the boards get: the one chosen, else the shelf's (Official, else Sandbox)."""
        return self.stump_src or stump.default_copy()

    def stump_dir(self):
        c = self.stump_copy()
        return c["dir"] if c else None

    def stump_choices(self):
        out = [c for c in (shelf.best("stump", ch) for ch in shelf.CHANNELS) if c]
        if self.stump_src and self.stump_src["channel"] == "file":
            out.append(self.stump_src)
        return out

    def bundled_packs(self):
        if self._packs is None:
            try:
                self._packs = self.packs_fn(self.bundle_dir or self.stump_dir())
            except Exception:
                self._packs = []
        return self._packs

    # -- what the buttons do --
    def handle(self, act):
        if act == "quit":
            self.stop_log()
            self.running = False
            return
        if self.kb:
            if act in ("kx", "ky", "kq"):               # a keyboard's letters arrive as text too
                return
            r = self.kb.handle(act)
            if r == "ok":
                text, done = self.kb.text, self.kb_done
                self.kb, self.kb_done = None, None
                if done:
                    done(text)
                else:
                    self.form["a"][self.kb_key] = text
            elif r == "cancel":
                self.kb, self.kb_done = None, None
            return
        # A keyboard's keys, outside the on-screen keyboard: Enter is A, Esc is B.
        act = {"enter": "a", "escape": "b", "backspace": "b", "kx": "x", "ky": "y", "kq": "quit"}.get(act, act)
        if isinstance(act, tuple) or act in ("start", "select"):
            return
        if act == "quit":
            self.handle("quit")
            return
        if self.confirm:
            c = self.confirm
            if act in ("left", "up"):
                c["choice"] = 0
            elif act in ("right", "down"):
                c["choice"] = 1
            elif act in ("b", "y", "x"):
                self.confirm = None
                self.toast("Cancelled: nothing touched")
            elif act == "a":
                self.confirm = None
                if c["choice"] == 1:
                    c["go"]()
                else:
                    self.toast("Cancelled: nothing touched")
            return
        getattr(self, "on_" + self.screen)(act)

    def on_boards(self, act):
        rows = self.rows()
        n = len(rows)
        row = rows[self.sel] if n else {}
        if act in ("up", "down") and n:
            self.sel = (self.sel + (1 if act == "down" else -1)) % n
        elif act in ("l", "r") or (act == "y" and not (n and row.get("port"))):
            self.open_library()                 # Y where it's free; L anywhere (a board's row has X and Y)
        elif row.get("adapter"):
            if act == "a":
                self.open_wifi()
        elif row.get("handheld"):
            if act == "a":
                self.open_handheld()
        elif act in ("a", "x", "y") and n:
            p = rows[self.sel]
            self.cur = p
            go = self.open_log if act == "y" else (self.identify if act == "x" or p["port"] not in self.known
                                                   else self.open_jobs)
            if p.get("users") and go != self.open_jobs:
                who = ", ".join(sorted(set(u[1] for u in p["users"])))
                self.ask("%s is using this board" % who,
                         ["%s has %s open (the Stump's radio?)." % (who, p["port"]),
                          "Going on resets the board: %s loses it until it reconnects." % who],
                         "Use it anyway", go, danger=True)
            else:
                go()

    def identify(self):
        port = self.cur["port"]

        def work(t):
            t.step = "Asking the chip (the board resets)"
            ok, out = flasher.probe(port, t.line)
            if not ok:
                return False, flasher.explain(out), None
            info = boards.parse_probe(out)
            board = boards.identify(info["chip"], self.cur["usb"])
            self.known[port] = {"board": dict(board, flash_mb=info["flash_mb"]), "info": info}
            return True, "%s, %s, %g MB flash" % (board["name"], info["chip_text"], info["flash_mb"]), None
        self.task = Task("Identifying %s" % port, work)
        self.task.after = "jobs"
        self.screen = "run"

    def open_jobs(self):
        self.jsel = 1 if self.jobs()[:1] == [{"kind": "src_stump"}] else 0     # on Make a Stump, under its source
        self.screen = "jobs"

    def on_jobs(self, act):
        rows = self.jobs()
        if act in ("up", "down"):
            self.jsel = (self.jsel + (1 if act == "down" else -1)) % len(rows)
        elif act in ("left", "right") and rows[self.jsel]["kind"] == "src_stump":
            ch = self.stump_choices()
            if ch:
                cur = self.stump_copy()
                i = next((k for k, c in enumerate(ch) if cur and c["dir"] == cur["dir"] and c["tag"] == cur["tag"]), 0)
                self.stump_src = ch[(i + (1 if act == "right" else -1)) % len(ch)]
                self._bundle, self._packs = False, None
        elif act == "b":
            self.screen = "boards"
        elif act == "y":
            self.open_log()
        elif act == "a":
            r = rows[self.jsel]
            if r["kind"] == "src_stump":
                self.open_product("stump", back="jobs")
            elif r["kind"].startswith("stump_"):
                self.stump_job(r["kind"])
            elif r["kind"] == "log":
                self.open_log()
            elif r["kind"] == "erase":
                self.ask_erase()
            elif r["kind"] == "fromfile":
                self.open_files()
            elif r["kind"] == "pack":
                if r["plan"]:
                    self.ask_pack(r["plan"])
                else:
                    self.toast("%s: %s" % (os.path.basename(r["path"]), r["error"]), 4)
            elif r["entry"]["status"] != "ready":
                self.toast("Coming: %s" % r["entry"]["title"], 3)
            else:
                self.ask_flash(r["entry"])

    def ask(self, title, lines, yes, go, danger=False):
        self.confirm = {"title": title, "lines": lines, "yes": yes, "go": go, "danger": danger,
                        "choice": 0 if danger else 1}

    def ask_flash(self, e):
        why = catalog.check(e)
        if why:
            self.toast("%s: %s" % (e["title"], why), 4)
            return
        k = self.known[self.cur["port"]]
        what = ("Erases the whole flash first: everything on the board goes." if e["mode"] == "full"
                else "App slot only (%s): the board's partitions and settings stay." % e["offset"])
        self.ask("Flash %s?" % e["title"],
                 ["Onto: %s at %s" % (k["board"]["name"], self.cur["port"]), what,
                  "SHA-256 %s… checked" % e["sha256"][:16], "Licence: %s" % e.get("licence", "?")],
                 "Flash it", lambda: self.start_flash(e), danger=(e["mode"] == "full"))

    def start_flash(self, e):
        port, board = self.cur["port"], self.known[self.cur["port"]]["board"]

        def work(t):
            def step(s):
                t.step, t.pct = s, (0 if s.startswith("Writing") else None)
            def pct(p):
                t.pct = p
            ok, msg = flasher.flash(port, e, board, on_line=t.line, on_step=step, on_progress=pct)
            return ok, msg, None
        self.task = Task("Flashing %s" % e["title"], work)
        self.task.after = "jobs"
        self.screen = "run"

    def ask_erase(self):
        k = self.known[self.cur["port"]]
        self.ask("Erase the whole flash?",
                 ["%s at %s" % (k["board"]["name"], self.cur["port"]),
                  "Everything on the board goes: firmware, settings, files."], "Erase it", self.start_erase,
                 danger=True)

    def start_erase(self):
        port, chip = self.cur["port"], self.known[self.cur["port"]]["board"]["chip"]

        def work(t):
            t.step = "Erasing the whole flash"
            ok, msg = flasher.erase(port, chip, t.line)
            return ok, msg, None
        self.task = Task("Erasing %s" % port, work)
        self.task.after = "jobs"
        self.screen = "run"

    def on_run(self, act):
        t = self.task
        if not t or not t.done:
            if act == "b":
                self.toast("Working: it can't be stopped halfway safely")
            return
        if act in ("a", "b"):
            if t.ok and getattr(t, "after", "") == "form" and t.result is not None:
                self.open_form("settings", stump.answers_from(t.result))
            elif t.ok and getattr(t, "after", "") == "jobs":
                self.open_jobs()
            elif getattr(t, "after", "") == "quit" and t.ok:
                self.handle("quit")                             # a new Provisioner: open it again from Ports
            elif getattr(t, "after", "") in ("product", "quit", "library"):
                self.next_here = self.next_handheld = 0.0       # look again: it may have changed
                self.screen = "library" if t.after == "library" else "product"
            else:
                self.screen = "jobs" if self.cur and self.cur["port"] in self.known else "boards"

    # -- the S3 USB Wi-Fi adapter --
    def open_wifi(self):
        self.wifi = {"sel": 0, "status": self.adapter, "nets": [], "saved": [], "busy": False, "next": 0.0,
                     "next_scan": 0.0, "joining": None, "retype": set(), "internet": None, "address": None,
                     "loaded": False}
        if (self.adapter or {}).get("state") == "connected":
            self.wifi_check_internet()
        self.screen = "wifi"

    def wifi_refresh(self):
        w = self.wifi
        if w and w.get("gone"):
            self.wifi, self.adapter, self.screen = None, None, "boards"
            self.toast("The S3 USB Wi-Fi adapter was unplugged")
            return
        if not w or w["busy"] or time.time() < w["next"]:
            return
        w["busy"] = True
        do_scan = time.time() >= w["next_scan"]

        def work():
            try:
                port = self.adapter_port
                st = self.adapter_fn(port)
                if st is None:
                    w["gone"] = True
                    return
                w["saved"] = s3wifi.saved(port)
                if do_scan:
                    w["nets"] = s3wifi.scan(port)
                    w["next_scan"] = time.time() + 10
                    w["loaded"] = True
                self.wifi_status(st)
            finally:
                w["next"] = time.time() + (1.0 if w["joining"] else 2.5)
                w["busy"] = False
        threading.Thread(target=work, daemon=True).start()

    def wifi_status(self, st):
        """A new status.json: say how a join asked for turned out."""
        w = self.wifi
        was = (w["status"] or {}).get("ssid")
        w["status"] = self.adapter = st
        j = w["joining"]
        if j and st.get("state") == "connected" and st.get("ssid") == j:
            w["joining"] = None
            w["retype"].discard(j)
            self.toast("Connected to %s" % j, 3)
            self.wifi_check_internet()
        elif j and st.get("state") != "joining" and st.get("target") == j and st.get("error"):
            w["joining"] = None
            if st["error"] == "wrong_password":
                w["retype"].add(j)
            self.toast("Couldn't join %s: %s" % (j, s3wifi.explain(st["error"])), 4)
        elif st.get("ssid") and st.get("ssid") != was and not j:
            self.wifi_check_internet()

    def wifi_check_internet(self):
        """The handheld's address on the adapter (its network's DHCP gives it, a few
        seconds after the S3 joins), then whether the internet answers."""
        w = self.wifi
        w["internet"], w["address"] = "checking", None

        def work():
            for _ in range(20):
                w["address"] = self.address_fn()
                if w["address"]:
                    break
                time.sleep(1)
            w["internet"] = "yes" if self.internet_fn() else "no"
        threading.Thread(target=work, daemon=True).start()

    def wifi_rows(self):
        """What's in range (strongest first), then saved networks out of range."""
        w = self.wifi
        rows, seen = [], set()
        for n in w["nets"]:
            if n["ssid"] in seen:
                continue
            seen.add(n["ssid"])
            rows.append({"ssid": n["ssid"], "rssi": n.get("rssi"), "open": bool(n.get("open")),
                         "saved": n["ssid"] in w["saved"] or bool(n.get("saved")), "here": True})
        for ssid in w["saved"]:
            if ssid not in seen:
                rows.append({"ssid": ssid, "rssi": None, "open": False, "saved": True, "here": False})
        return rows

    def on_wifi(self, act):
        w, rows = self.wifi, self.wifi_rows()
        if act in ("up", "down") and rows:
            w["sel"] = (w["sel"] + (1 if act == "down" else -1)) % len(rows)
        elif act == "b":
            self.wifi, self.screen = None, "boards"
        elif act == "x":
            w["next_scan"] = w["next"] = 0.0
            self.toast("Looking for networks…")
        elif act == "y" and rows:
            r = rows[min(w["sel"], len(rows) - 1)]
            if not r["saved"]:
                self.toast("%s isn't saved: nothing to forget" % r["ssid"])
                return
            self.ask("Forget %s?" % r["ssid"], ["The S3 won't join it by itself any more.",
                                               "Its password goes too."],
                     "Forget it", lambda: self.wifi_forget(r["ssid"]))
        elif act == "a" and rows:
            r = rows[min(w["sel"], len(rows) - 1)]
            ssid = r["ssid"]
            if r["saved"] and ssid not in w["retype"]:
                self.wifi_join(ssid, None)
            elif r["open"]:
                self.wifi_join(ssid, "")
            else:
                self.kb = Keyboard("Password for %s" % ssid, "", 63, secret=True,
                                   hint="8 to 63 characters. START joins.")
                self.kb_done = lambda text: self.wifi_password(ssid, text)

    def wifi_password(self, ssid, text):
        if not 8 <= len(text.encode()) <= 63:
            self.toast("A Wi-Fi password is 8 to 63 characters: not joined", 4)
            return
        self.wifi_join(ssid, text)

    def wifi_join(self, ssid, password):
        w = self.wifi
        self.toast("Joining %s…" % ssid, 3)

        def work():
            ok, err = s3wifi.join(self.adapter_port, ssid, password)
            if ok:
                w["joining"], w["internet"] = ssid, None
                w["next"] = 0.0
            else:
                self.toast("Couldn't ask the S3 to join %s: %s" % (ssid, s3wifi.explain(err)), 4)
        threading.Thread(target=work, daemon=True).start()

    def wifi_forget(self, ssid):
        w = self.wifi

        def work():
            ok, err = s3wifi.forget(self.adapter_port, ssid)
            self.toast(("Forgot %s" % ssid) if ok else ("Couldn't forget %s: %s" % (ssid, s3wifi.explain(err))), 3)
            w["retype"].discard(ssid)
            w["next"] = 0.0
        threading.Thread(target=work, daemon=True).start()

    # -- + From File --
    def open_files(self, product=None):
        exts = shelf.PRODUCTS[product]["file"] if product else files.USABLE
        self.fb = {"path": None, "sel": 0, "entries": [], "show_all": False, "from": self.screen, "product": product,
                   "exts": exts}
        self.files_load(None)
        self.screen = "files"

    def files_load(self, path, select=None):
        fb = self.fb
        if path is None:
            fb["entries"] = [{"name": label, "path": p, "dir": True, "size": 0, "root": True}
                             for label, p in self.roots_fn()]
        else:
            got = files.listdir(path, exts=fb.get("exts", files.USABLE), show_all=fb["show_all"])
            if got is None:
                self.toast("Can't open %s" % path, 3)
                return
            fb["entries"] = got
        fb["path"], fb["sel"] = path, 0
        if select:
            fb["sel"] = next((i for i, e in enumerate(fb["entries"]) if e["path"] == select), 0)

    def at_root(self, path):
        return any(path == p for _, p in self.roots_fn())

    def on_files(self, act):
        fb = self.fb
        n = len(fb["entries"])
        page = 8
        step = {"up": -1, "down": 1, "left": -page, "right": page, "l": -page, "r": page}.get(act)
        if step and n:
            fb["sel"] = max(0, min(n - 1, fb["sel"] + step)) if act not in ("up", "down") \
                else (fb["sel"] + step) % n
        elif act == "b":
            if fb["path"] is None:
                self.fb, self.screen = None, fb["from"]
            elif self.at_root(fb["path"]):
                self.files_load(None, select=fb["path"])
            else:
                self.files_load(os.path.dirname(fb["path"]), select=fb["path"])
        elif act == "y" and fb["path"] is not None:
            fb["show_all"] = not fb["show_all"]
            self.files_load(fb["path"])
            self.toast("Showing every file" if fb["show_all"] else "Showing %s files" % " and ".join(fb["exts"]))
        elif act == "a" and n:
            e = fb["entries"][fb["sel"]]
            if e["dir"]:
                self.files_load(e["path"])
            else:
                self.choose_file(e["path"])

    def choose_file(self, path):
        if self.fb and self.fb.get("product"):
            try:
                c = shelf.from_file(self.fb["product"], path)
            except (shelf.ShelfError, OSError) as e:
                self.toast("Not used: %s" % e, 5)
                return
            self.fb, self.screen = None, "product"
            self.use_copy(c)
            return
        board = self.known[self.cur["port"]]["board"]
        if path.lower().endswith(".zip"):
            if board.get("id") not in STUMP_BOARDS:
                self.toast("A pack's .zip is for a Stump (an ESP32-S3-CAM or a WROVER)", 4)
                return
            try:
                plan = packs.plan_file(path, packs.known_names(self.bundle()))
            except packs.PackError as e:
                self.toast("Not installed: %s" % e, 5)
                return
            self.ask_pack(plan, os.path.basename(path))
            return
        try:
            if os.path.getsize(path) > 32 * 1024 * 1024:
                self.toast("Too big to be ESP firmware", 3)
                return
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            self.toast("Can't read it: %s" % (e.strerror or e), 4)
            return
        info = images.inspect(data)
        if info["kind"] == "unknown":
            self.toast("Not flashed: %s" % info["why"], 5)
            return
        if info["chip"] != board["chip"]:
            self.toast("Not flashed: it's built for the %s; this board is an %s" % (
                info["chip"].upper(), board["chip"].upper()), 5)
            return
        sha = packs.sha(data)
        entry = {"id": "file", "title": os.path.basename(path), "chip": board["chip"], "mode": info["kind"],
                 "offset": "0x%X" % info["offset"], "path": path, "sha256": sha, "status": "ready",
                 "min_flash_mb": info["flash_mb"] if info["kind"] == "full" else 0, "licence": "as its author says"}
        lines = [images.describe(info), "%s · %s" % (files.human(len(data)), path),
                 "SHA-256 %s…" % sha[:16]]
        need = info.get("flash_mb") or 0
        have = board.get("flash_mb") or 0
        if info["kind"] == "full" and need and have and need > have:
            self.toast("Not flashed: it's for %d MB of flash; the board has %g MB" % (need, have), 5)
            return
        self.ask("Flash %s?" % entry["title"], lines, "Flash it", lambda: self.start_flash(entry),
                 danger=(info["kind"] == "full"))

    def ask_pack(self, plan, src=""):
        lines = ["%s · by %s · %s" % (packs.summary(plan), plan["author"], plan["license"]),
                 plan["description"][:220] + ("…" if len(plan["description"]) > 220 else ""),
                 "Every file checked against the pack's hashes. It starts with the Stump; /admin changes its settings."]
        if plan["by_reader"]:
            lines.append("Too big for USB, to copy by card reader: %s" % ", ".join(plan["by_reader"]))
        port = self.cur["port"]
        self.ask("Add %s %s to its Stump?" % (plan["name"], plan["version"]), lines, "Add it",
                 lambda: self.run_stump("Adding %s %s" % (plan["name"], plan["version"]), lambda t: packs.install(
                     plan, self.link_for(port), self._step(t), self._pct(t), t.line)))

    # -- a Stump --
    def link_for(self, port):
        return lambda: self.open_link(port)

    def chip_of(self, port):
        return (self.known.get(port, {}).get("board") or {}).get("chip") or "esp32s3"

    def flash_for(self, port, t):
        """flash(path, offset, erase) for stump.make on this board's chip."""
        chip = self.chip_of(port)
        return lambda path, offset, erase: flasher.write_image(port, chip, path, offset, t.line, self._pct(t), erase)

    def stump_image_line(self, port):
        """What Make writes on this board: the Stump image, or MicroPython."""
        b, chip = self.bundle(), self.chip_of(port)
        img, offset = b.image_for(chip) if b else (None, "0x0")
        if img:
            return "Its Stump image %s (MicroPython %s with the Stump built in) at %s." % (b.release, b.micropython, offset)
        if chip != "esp32s3":
            return "Stump %s has no image for a WROVER: it can't be made a Stump from it." % (b.release if b else "?")
        return "Stump %s, MicroPython %s (no Stump image in this release: copied file by file)." % (
            b.release if b else "?", b.micropython if b else "?")

    def stump_job(self, kind):
        b = self.bundle()
        if not b:
            self.toast("No Stump on the shelf: This handheld -> The Stump gets one (online), or + From File", 5)
            return
        port = self.cur["port"]
        if kind == "stump_new":
            self.open_form("new", {"name": "", "pw": "", "opw": "", "botpw": "same", "parentIp": "", "ssid": "", "wpass": "",
                                   "hotspot": "", "chain": "none",
                                   "radio": "ap", "secret": "", "upSsid": b.default_ssid, "subnet": "5", "hhost": "",
                                   "features": list(stump.FEATURES[:3])})
        elif kind == "stump_update":
            self.ask("Update its Stump to %s?" % b.release,
                     ["Copies the new release onto the Stump on this board.",
                      "Its settings, its identity on the mesh and its card stay.", "About 4 minutes."],
                     "Update it", lambda: self.run_stump("Updating the Stump", lambda t: stump.make(
                         b, {}, self.link_for(port), self.flash_for(port, t), self._step(t), self._pct(t), t.line,
                         update=True, chip=self.chip_of(port))))
        elif kind == "stump_settings":
            def work(t):
                t.step = "Reading its settings (it restarts after)"
                c = stump.read_job(self.link_for(port), t.line)
                if c is None:
                    return False, "There's no Stump on this board (no config.py): Make a Stump first.", None
                return True, "Read from \u201c%s\u201d." % (c.get("NODE_NAME") or "its Stump"), c
            self.task = Task("Reading its settings", work)
            self.task.after = "form"
            self.screen = "run"
        elif kind == "stump_check":
            self.run_stump("Checking it starts", lambda t: stump.check_job(self.link_for(port), self._step(t), t.line,
                                                                            report=t.report))

    def _step(self, t):
        def step(s):
            t.step, t.pct = s, (0 if s.startswith(("Copying", "Erasing")) else None)
        return step

    def _pct(self, t):
        def pct(p):
            t.pct = p
        return pct

    def run_stump(self, title, fn):
        def work(t):
            ok, msg = fn(t)
            return ok, msg, None
        self.task = Task(title, work)
        self.task.after = "jobs"
        self.screen = "run"

    def open_form(self, mode, a, back="jobs"):
        self.form = {"mode": mode, "a": a, "sel": 0, "back": back}
        self.screen = "form"

    def form_rows(self):
        f, a = self.form, self.form["a"]
        if f["mode"] == "handheld":
            return self.handheld_form_rows(a)
        keep = f["mode"] == "settings"
        b = self.bundle()
        rows = [{"key": "name", "label": "Its name", "kind": "text", "max": 20, "blank": "needed"},
                {"key": "pw", "label": "Its password (/admin)", "kind": "secret", "max": 64,
                 "blank": "keeps the one it has" if keep else "needed"},
                {"key": "botpw", "label": "The fserv bot", "kind": "choice", "choices": BOTPW}]
        if a.get("botpw") == "own":
            rows += [{"key": "opw", "label": "The fserv bot's password", "kind": "secret", "max": 64,
                      "blank": "keeps the one it has" if keep else "none: editing off"}]
        rows += [
                {"key": "ssid", "label": "Home Wi-Fi (optional)", "kind": "text", "max": 32, "blank": "none"},
                {"key": "wpass", "label": "Home Wi-Fi password", "kind": "secret", "max": 63,
                 "blank": "keeps the one it has" if keep else "none"},
                {"key": "hotspot", "label": "Its own Wi-Fi's name", "kind": "text", "max": 32,
                 "blank": b.default_ssid if b else "the default"},
                {"key": "chain", "label": "Chain", "kind": "choice", "choices": CHAINS}]
        if a.get("chain") == "lan":
            rows += [{"key": "parentIp", "label": "The first Stump's address", "kind": "text", "max": 15,
                      "blank": "on the home Wi-Fi, like 192.168.0.173"},
                     {"key": "subnet", "label": "Its number (5-254)", "kind": "text", "max": 3}]
        if a.get("chain") == "member":
            rows += [{"key": "upSsid", "label": "Joins (its Wi-Fi)", "kind": "text", "max": 32},
                     {"key": "subnet", "label": "Its number (5-254)", "kind": "text", "max": 3}]
        if a.get("chain") in ("first", "member", "lan"):
            rows += [{"key": "secret", "label": "The chain's secret", "kind": "text", "max": 64,
                      "blank": "needed over the router" if a.get("chain") == "lan" else "none (open)"}]
        rows += [{"key": "radio", "label": "LoRa", "kind": "choice", "choices": RADIOS}]
        if a.get("radio") == "lan":
            rows += [{"key": "hhost", "label": "The Heltec's address", "kind": "text", "max": 15,
                      "blank": "on the home Wi-Fi: .222 is a good one, its own for each"}]
        rows += [{"key": "go", "label": "Make the Stump" if f["mode"] == "new" else "Save its settings", "kind": "button"}]
        return rows

    def on_form(self, act):
        rows = self.form_rows()
        f = self.form
        f["sel"] = min(f["sel"], len(rows) - 1)
        r = rows[f["sel"]]
        if act in ("up", "down"):
            f["sel"] = (f["sel"] + (1 if act == "down" else -1)) % len(rows)
        elif act in ("left", "right") and r["kind"] == "choice":
            keys = [k for k, _ in r["choices"]]
            i = keys.index(f["a"].get(r["key"], keys[0])) if f["a"].get(r["key"]) in keys else 0
            f["a"][r["key"]] = keys[(i + (1 if act == "right" else -1)) % len(keys)]
        elif act == "b":
            self.form, self.screen = None, self.form.get("back", "jobs")
        elif act == "a":
            if r["kind"] in ("text", "secret"):
                self.kb = Keyboard(r["label"], f["a"].get(r["key"]) or "", r["max"], secret=r["kind"] == "secret",
                                   hint=("Blank: " + r["blank"]) if r.get("blank") else "")
                self.kb_key = r["key"]
            elif r["kind"] == "choice":
                self.on_form("right")
            elif r["kind"] == "button":
                self.submit_form()

    def submit_form(self):
        if self.form["mode"] == "handheld":
            return self.submit_handheld()
        f, b, port = self.form, self.bundle(), self.cur["port"]
        a = dict(f["a"], pw2=f["a"].get("pw", ""), lanOk=bool(b and b.release_at_least("1.0.0-beta.57")))
        if f["mode"] == "settings":
            a["keepWifiPass"] = True
        s = stump.settings_from(dict(a, requireAdmin=f["mode"] == "new"))
        if s.get("error"):
            self.toast(s["error"], 4)
            return
        if f["mode"] == "new":
            info = self.known[port]["info"]
            lines = ["Erases everything on the board: a Stump on it now loses its identity.",
                     self.stump_image_line(port) + " About 5 minutes."]
            if not info.get("psram_mb") and self.chip_of(port) == "esp32s3":
                lines.append("esptool didn't report PSRAM: the Stump needs the octal-PSRAM board (Freenove N16R8).")
            elif self.chip_of(port) == "esp32":
                lines.append("A Stump needs PSRAM: an ESP32-WROVER (a WROOM is refused once it answers).")
            self.ask("Make a Stump on this board?", lines + s["warn"], "Make it", lambda: self.run_stump(
                "Making the Stump", lambda t: stump.make(
                    b, a, self.link_for(port), self.flash_for(port, t),
                    self._step(t), self._pct(t), t.line, chip=self.chip_of(port), report=t.report)), danger=True)
        else:
            self.ask("Save its settings?", ["Written by the Stump's own settings.py, as /admin does.",
                                            "Its config.py is kept as config.py.bak. It restarts."] + s["warn"],
                     "Save", lambda: self.run_stump("Saving its settings", lambda t: stump.save_job(
                         a, self.link_for(port), self._step(t), t.line, report=t.report,
                         default_ssid=b.default_ssid if b else "Stump")))

    def draw_form(self):
        d, f = self.d, self.form
        if self.kb:
            return
        a, rows = f["a"], self.form_rows()
        d.text(F16, 16, TOP + 4, {"new": "A NEW STUMP", "handheld": "THIS HANDHELD'S STUMP"}.get(f["mode"], "ITS SETTINGS"),
               EMBER)
        rh = 56
        lora = f["mode"] != "handheld" and a.get("radio") != "none"
        vis = max(1, (BOT - 6 - (TOP + 28) - (28 if lora else 0)) // rh)
        first = window(f["sel"], len(rows), vis)
        if first > 0:
            d.text(F16, W - 90, TOP + 4, "↑ more", MUTED)
        if first + vis < len(rows):
            d.text(F16, W - 90, TOP + 28 + vis * rh - 4, "↓ more", MUTED)
        for k, r in enumerate(rows[first:first + vis]):
            i = first + k
            y = TOP + 28 + k * rh
            sel = i == f["sel"]
            if r["kind"] == "button":
                d.fill_rrect(12, y + 4, W - 24, rh - 8, 8, EMBER if sel else BORDER)
                d.text(F24, W // 2 - d.text_width(F24, r["label"]) // 2, y + 13, r["label"], BG if sel else TEXT)
                continue
            if sel:
                d.stroke_rrect(12, y, W - 24, rh - 6, 8, EMBER, PANEL)
            v = a.get(r["key"])
            if r["kind"] == "choice":
                val = dict(r["choices"]).get(v, r["choices"][0][1])
                val = "◀ %s ▶" % val if sel else val
                vc = TEXT
            elif r["kind"] == "secret":
                val = ("•" * min(len(v), 12) + "  (%d)" % len(v)) if v else "blank: " + r.get("blank", "")
                vc = TEXT if v else MUTED
            else:
                val = v if v else "blank: " + r.get("blank", "")
                vc = TEXT if v else MUTED
            lw = min(300, W * 5 // 12)
            d.text(F20, 26, y + 13, r["label"], EMBER_BRIGHT if sel else TEXT, lw)
            vw = min(d.text_width(F20, val), W - lw - 60)
            d.text(F20, W - 28 - vw, y + 13, val, vc, W - lw - 60)
        if lora:
            d.text(F16, 16, BOT - 26, "LoRa: 868.8 MHz · 125 kHz · SF8 · CR 4/5 · 22 dBm (the mesh's)",
                   MUTED, W - 32)
        self.hints([("A", "type / choose"), ("←→", "choice"), ("↑↓", "move"), ("B", "back")])

    def open_log(self):
        self.stop_log()
        self.log = self.open_serial_log(self.cur["port"])
        self.logv = {"frozen": None, "cur": 0, "mark": None}
        self.log_from = self.screen if self.screen in ("boards", "jobs") else "boards"
        self.screen = "log"

    def stop_log(self):
        if self.log:
            self.log.stop()
            self.log = None

    LOG_ROW = 21

    def log_rows(self):
        """How many lines the log screen shows (fewer while a long line is spelled out)."""
        return (BOT - 6 - (TOP + 40)) // self.LOG_ROW

    def on_log(self, act):
        v, log = self.logv, self.log
        if act == "b":
            self.stop_log()
            self.screen = getattr(self, "log_from", "boards")
            return
        if not log:
            return
        if v["frozen"] is None:                      # running
            if act == "a":
                v["frozen"] = log.timed()
                v["cur"], v["mark"] = max(0, len(v["frozen"]) - 1), None
                log.paused = True
            elif act == "x":
                log.clear()
                self.toast("Cleared")
            elif act == "y":
                self.log_export(None)
            return
        n = len(v["frozen"])                         # paused: the cursor
        page = max(1, self.log_rows() - 4)
        step = {"up": -1, "down": 1, "left": -page, "right": page, "l": -page, "r": page}.get(act)
        if step and n:
            v["cur"] = max(0, min(n - 1, v["cur"] + step))
        elif act == "a":
            v["frozen"], v["mark"] = None, None
            log.paused = False
        elif act == "x" and n:
            if v["mark"] is None:
                v["mark"] = v["cur"]
                self.toast("Block from line %d: move, then Y exports it" % (v["cur"] + 1), 3)
            else:
                v["mark"] = None
                self.toast("Block cleared")
        elif act == "y":
            if v["mark"] is not None and n:
                a, b = sorted((v["mark"], v["cur"]))
                self.log_export(v["frozen"][a:b + 1], "lines %d-%d" % (a + 1, b + 1))
            else:
                self.log_export(v["frozen"])

    def log_export(self, lines, what=""):
        try:
            path = self.log.export(lines, folder=self.log_dir)
        except OSError as e:
            self.toast("Couldn't export: %s" % (e.strerror or e), 4)
            return
        short = os.path.join(os.path.basename(os.path.dirname(path)), os.path.basename(path))
        self.toast("Exported%s to %s" % (" " + what if what else "", short), 5)

    # -- drawing --
    def draw(self):
        d = self.d
        if self.kb:
            self.kb.draw(d, THEME)
            d.present()
            return
        d.clear(BG)
        self.draw_header()
        getattr(self, "draw_" + self.screen)()
        if self.confirm:
            self.draw_confirm()
        if self.toast_text and time.time() < self.toast_until:
            d.fill_rrect(30, 100, W - 60, 40, 8, EMBER)
            d.text(F20, 46, 108, self.toast_text, BG, W - 92)
        d.present()

    def draw_header(self):
        d = self.d
        d.fill(0, 0, W, 86, PANEL2)
        d.text(F30B, 14, 6, "Provisioner", EMBER)
        v = "RK3326 · v%s" % self.version if self.version else "RK3326"
        d.text(F16, W - 14 - d.text_width(F16, v), 16, v, MUTED)
        crumbs = {"boards": "Boards on the hub", "jobs": "Boards  ›  %s" % self.board_name(),
                  "run": self.task.title if self.task else "",
                  "form": ("This handheld  ›  Its Stump" if self.form and self.form["mode"] == "handheld" else
                           "%s  ›  %s" % (self.board_name(), "A new Stump" if self.form and self.form["mode"] == "new"
                                          else "Its settings")),
                  "handheld": "This handheld",
                  "library": "Library  ·  what this Provisioner carries",
                  "product": "This handheld  ›  %s" % (shelf.PRODUCTS[self.prod]["title"] if self.prod else ""), "files": "%s  ›  From File" % (shelf.PRODUCTS[self.fb["product"]]["short"] if self.fb and self.fb.get("product")
                                               else self.board_name()), "log": "Serial log  ·  %s  ·  115200"
                  % (self.cur["port"] if self.cur else ""), "wifi": "S3 USB Wi-Fi  ·  its networks"}[self.screen]
        d.text(F20, 16, 52, crumbs, TEXT, W - 32)
        d.fill(0, 86, W, 1, BORDER)

    def board_name(self):
        k = self.known.get(self.cur["port"]) if self.cur else None
        return k["board"]["name"] if k else (self.cur["usb_chip"] if self.cur else "")

    def hints(self, pairs):
        d, x = self.d, 12
        d.fill(0, BOT, W, H - BOT, PANEL2)
        for key, label in pairs:
            if x > W - 40:
                break
            if key:
                kw = d.text_width(F16, key) + 14
                d.fill_rrect(x, BOT + 8, kw, 24, 5, BORDER)
                d.text(F16, x + 7, BOT + 11, key, TEXT)
                x += kw + 6
            x += d.text(F16, x, BOT + 11, label, MUTED, W - 8 - x) + 16

    def nodriver_line(self):
        """One line on a board this system can't talk to (no driver for its USB chip)."""
        n = self.nodriver[0]
        return "%s plugged in, but this system has no driver for it (%s): no port to flash it by" % (
            n["usb_chip"], n["driver"])

    def draw_boards(self):
        d = self.d
        if self.nodriver:
            for i, s in enumerate(wrap(d, F16, self.nodriver_line(), W - 48)[:2]):
                d.text(F16, 24, BOT - 50 + i * 21, s, ERROR, W - 48)
        if not self.ports and not self.adapter:
            y0 = TOP + (120 if H >= 600 else 24)
            if self.handheld:                           # this handheld's Stump first, then how to plug a board
                d.text(F16, 16, TOP + 4, "THIS HANDHELD", EMBER)
                d.stroke_rrect(12, TOP + 28, W - 24, 78, 8, EMBER, PANEL)
                self.draw_handheld_row(TOP + 28, True)
                y0 = TOP + 28 + 84 + (40 if H >= 600 else 12)
            d.text(F24, 24, y0, "Plug a board into the hub", TEXT)
            text = [wrap(d, F16, t, W - 48) for t in (
                "With a data cable: a Heltec V3, an ESP32-S3 (Freenove CAM) or an ESP32-WROVER. "
                "It shows up here by itself.",
                "A board with two USB-C ports: either one flashes it; once it's a USB Wi-Fi adapter, "
                "use the serial chip's port.")]
            y = y0 + 40
            for para in text:
                for s in para:
                    d.text(F16, 24, y, s, MUTED, W - 48)
                    y += 22
                y += 8
            self.hints(([("A", "this handheld")] if self.handheld else []) + [("Y", "library"), ("SELECT+START", "quit")])
            return
        self.draw_here(TOP + 4)
        d.text(F16, 16, TOP + 4, "BOARDS ON THE HUB", EMBER)
        rh = 84
        rows = self.rows()
        vis = fits(TOP + 28, rh) - (1 if self.nodriver else 0)
        first = window(self.sel, len(rows), max(1, vis), ahead=0)
        for k, p in enumerate(rows[first:first + max(1, vis)]):
            i = first + k
            y = TOP + 28 + k * rh
            sel = i == self.sel
            if sel:
                d.stroke_rrect(12, y, W - 24, rh - 6, 8, EMBER, PANEL)
            if p.get("adapter"):
                self.draw_adapter_row(y, sel)
                continue
            if p.get("handheld"):
                self.draw_handheld_row(y, sel)
                continue
            known = self.known.get(p["port"])
            name = known["board"]["name"] if known else p["usb_chip"]
            d.text(F24, 26, y + 6, name, EMBER_BRIGHT if sel else TEXT, W - 60)
            if known:
                inf = known["info"]
                sub = "%s · %s · %g MB flash%s · %s" % (p["port"], inf["chip_text"], inf["flash_mb"],
                                                       " · PSRAM %d MB" % inf["psram_mb"] if inf["psram_mb"] else "",
                                                       inf["mac"])
            else:
                sub = "%s · %s · A to identify (resets it)" % (p["port"], p["usb"] or "USB")
            d.text(F16, 26, y + 36, sub, MUTED, W - 60)
            if p.get("users"):
                d.text(F16, 26, y + 56, "in use by %s" % ", ".join(sorted(set(u[1] for u in p["users"]))), ERROR,
                       W - 60)
        if rows and rows[min(self.sel, len(rows) - 1)].get("adapter"):
            self.hints([("A", "its networks"), ("Y", "library"), ("↑↓", "move"), ("SELECT+START", "quit")])
        elif rows and rows[min(self.sel, len(rows) - 1)].get("handheld"):
            self.hints([("A", "install, update, check"), ("Y", "library"), ("↑↓", "move"), ("SELECT+START", "quit")])
        else:
            self.hints([("A", "choose"), ("X", "identify again"), ("Y", "serial log"), ("L", "library"), ("↑↓", "move"),
                        ("SELECT+START", "quit")])

    def adapter_line(self, st):
        """One line on what the adapter is doing."""
        if not st:
            return "", MUTED
        if st.get("state") == "connected" and st.get("ssid"):
            rssi = st.get("rssi")
            return "Connected to %s%s" % (st["ssid"], " · %d dBm" % rssi if rssi is not None else ""), OK
        if st.get("state") == "joining":
            return "Joining %s…" % (st.get("target") or "?"), EMBER_BRIGHT
        if st.get("error") and st.get("target"):
            return "Couldn't join %s: %s" % (st["target"], s3wifi.explain(st["error"])), ERROR
        return "Not connected", MUTED

    def draw_bars(self, x, y, n, tone):
        """Signal strength as four bars (n lit)."""
        for i in range(4):
            h = 6 + i * 5
            self.d.fill(x + i * 8, y + 22 - h, 5, h, tone if i < n else BORDER)

    def draw_adapter_row(self, y, sel):
        d = self.d
        d.text(F24, 26, y + 6, "S3 USB Wi-Fi", EMBER_BRIGHT if sel else TEXT, W - 60)
        line, tone = self.adapter_line(self.adapter)
        d.text(F16, 26, y + 36, line, tone, W - 60)
        fw = (self.adapter or {}).get("firmware", "")
        d.text(F16, 26, y + 56, "%s · %s · A: its networks" % (self.adapter_port or "usb", fw), MUTED, W - 60)

    # -- this handheld: the Provisioner, its Stump, FireFly, the CAM's Stump (the shelf) --
    def installed(self, p):
        """What's installed / in use, for a product: its version, or ''."""
        if p == "provisioner":
            return self.version
        if p == "firefly":
            return self.firefly_fn() if self.firefly_fn else ""
        if p == "handheld":
            return (self.marks_fn().get("handheld") or {}).get("version", "") if self.marks_fn else ""
        c = self.stump_copy()
        return c["version"] if c else ""

    def installed_line(self, p):
        """(text, colour) on what this product is here now."""
        v = self.installed(p)
        if p == "provisioner":
            return "v%s, this one" % v, OK
        if p == "handheld":
            h, st = self.here, self.handheld or {}
            if st.get("installed") and self.admin_state() in ("DEFAULT", "EMPTY"):
                return "/admin's password isn't its own: set Its password (its page)", ERROR
            if h and not h.get("none"):
                return "Stump %s · %s%s%s" % (h.get("release", "?"), h.get("name", "?"),
                                             " · " + h["chain"] if h.get("chain") else "",
                                             " · installer %s" % v if v else ""), OK
            if st.get("installed") and st.get("port"):
                return "Installed%s · runs while its Port is open" % (" · installer %s" % v if v else ""), OK
            if st.get("installed"):
                return "Installed, not answering: ~/Stump/stump.log says why", ERROR
            return "None yet", MUTED
        if p == "firefly":
            return ("FireFly %s installed" % v, OK) if v else ("Not installed", MUTED)
        c = self.stump_copy()
        return ("The boards get %s" % shelf.describe(c), OK) if c else ("No Stump on the shelf", ERROR)

    def newer_online(self, p, ch):
        """The release online that the shelf doesn't have yet, or None."""
        o = self.online.get((p, ch))
        c = shelf.best(p, ch)
        if o and (not c or shelf.version_key(o["version"]) > shelf.version_key(c["version"])):
            return o
        return None

    def shelf_line(self, p):
        bits = []
        for ch in shelf.CHANNELS:
            if not shelf.PRODUCTS[p].get(ch):
                continue
            c, o = shelf.best(p, ch), self.newer_online(p, ch)
            s = "%s %s" % (shelf.CHANNEL_NAMES[ch], c["version"] if c else "none")
            if o:
                s += " (online: %s)" % o["version"]
            bits.append(s)
        return "Shelf: " + " · ".join(bits), (EMBER_BRIGHT if any(self.newer_online(p, ch) for ch in shelf.CHANNELS)
                                               else MUTED)

    def net_line(self):
        if self.net == "checking":
            return "Looking online (EmulationStation's network)…", EMBER_BRIGHT
        if self.net == "online":
            n = sum(1 for p in shelf.ORDER for ch in shelf.CHANNELS if self.newer_online(p, ch))
            return ("Online: %d newer on GitHub (X gets it)" % n if n
                    else "Online: the shelf has the newest of everything"), OK if not n else EMBER_BRIGHT
        if self.net == "offline":
            return "Offline (%s): the shelf and + From File" % (self.net_error or "no network"), MUTED
        return "The shelf (offline) and + From File", MUTED

    def look_online(self, force=False):
        """Asks GitHub (over EmulationStation's network) for every product's newest
        Official and Sandbox, in the background; at most every 10 minutes unless forced."""
        if not self.online_fn or self.net == "checking":
            return
        if not force and self.net_when and time.time() - self.net_when < 600:
            return
        self.net = "checking"

        def work():
            got, err = {}, ""
            for p in shelf.ORDER:
                for ch in shelf.CHANNELS:
                    if not shelf.PRODUCTS[p].get(ch):
                        continue
                    try:
                        got[(p, ch)] = self.online_fn(p, ch)
                    except Exception as e:
                        err = str(e)
                        break
                if err:
                    break
            self.online = got if not err else {}
            self.net_error, self.net_when = err, time.time()
            self.net = "offline" if err else "online"
        if self.online_sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def draw_handheld_row(self, y, sel):
        d = self.d
        d.text(F24, 26, y + 6, "This handheld", EMBER_BRIGHT if sel else TEXT, W - 60)
        hl, _ = self.installed_line("handheld")
        ff = self.installed("firefly")
        d.text(F16, 26, y + 36, "Provisioner v%s · %s · FireFly %s" % (self.version, hl if hl != "None yet" else
                                "no Stump", ff or "none"), MUTED, W - 60)
        line, tone = self.net_line()
        d.text(F16, 26, y + 56, line, tone, W - 60)

    def open_handheld(self):
        self.hsel = 0
        self.next_here = 0.0
        self.screen = "handheld"
        self.look_online()

    def on_handheld(self, act):
        n = len(shelf.ORDER)
        if act in ("up", "down"):
            self.hsel = (self.hsel + (1 if act == "down" else -1)) % n
        elif act == "b":
            self.screen = "boards"
        elif act == "y":
            self.look_online(force=True)
        elif act == "a":
            self.open_product(shelf.ORDER[self.hsel])

    def draw_handheld(self):
        d = self.d
        d.fill_rrect(12, TOP + 2, W - 24, 40, 8, PANEL)
        line, tone = self.net_line()
        d.text(F16, 26, TOP + 13, line, tone, W - 52)
        d.text(F16, 16, TOP + 54, "WHAT THIS HANDHELD INSTALLS", EMBER)
        rh = 84
        vis = fits(TOP + 78, rh)
        first = window(self.hsel, len(shelf.ORDER), vis, ahead=0)
        for k, p in enumerate(shelf.ORDER[first:first + vis]):
            i, y = first + k, TOP + 78 + k * rh
            sel = i == self.hsel
            if sel:
                d.stroke_rrect(12, y, W - 24, rh - 6, 8, EMBER, PANEL)
            d.text(F24, 26, y + 6, shelf.PRODUCTS[p]["title"], EMBER_BRIGHT if sel else TEXT, W - 60)
            line, tone = self.installed_line(p)
            d.text(F16, 26, y + 36, line, tone, W - 60)
            line, tone = self.shelf_line(p)
            d.text(F16, 26, y + 56, line, tone, W - 60)
        self.hints([("A", "open"), ("Y", "look online"), ("↑↓", "move"), ("B", "boards")])

    # -- the Library: everything this Provisioner carries, refreshed online by the batch --
    def open_library(self):
        self.lib["sel"] = 0
        self.screen = "library"
        self.look_online()

    def library_rows(self):
        """The shelf, (product, channel) by (product, channel); then the catalogue
        (built in: WLED, MicroPython, the S3 image; no online channel)."""
        rows = []
        for p in shelf.ORDER:
            for ch in shelf.CHANNELS:
                if shelf.PRODUCTS[p].get(ch):
                    rows.append({"kind": "shelf", "p": p, "ch": ch, "key": (p, ch)})
        for e in self.entries:
            rows.append({"kind": "fw", "entry": e, "key": ("fw", e["id"])})
        return rows

    def library_newer(self):
        """The (product, channel) pairs the shelf doesn't have the newest of."""
        return [r["key"] for r in self.library_rows() if r["kind"] == "shelf" and self.newer_online(r["p"], r["ch"])]

    def on_library(self, act):
        rows = self.library_rows()
        lib = self.lib
        lib["sel"] = min(lib["sel"], len(rows) - 1)
        r = rows[lib["sel"]]
        if act in ("up", "down"):
            lib["sel"] = (lib["sel"] + (1 if act == "down" else -1)) % len(rows)
        elif act == "b":
            self.screen = "boards"
        elif act == "a":
            if r["kind"] != "shelf":
                self.toast("Built into the Provisioner: it comes with it", 3)
            elif r["key"] in lib["checked"]:
                lib["checked"].discard(r["key"])
            else:
                lib["checked"].add(r["key"])
        elif act == "y":
            self.look_online(force=True)
            self.toast("Looking online…")
        elif act in ("l", "r"):                  # all, or none
            lib["checked"] = set() if lib["checked"] else set(k["key"] for k in rows if k["kind"] == "shelf")
        elif act == "x":
            self.refresh_library(sorted(lib["checked"]) if lib["checked"] else None)

    def refresh_library(self, keys=None):
        """Fetches the checked (product, channel) pairs onto the shelf, or, with
        none checked, everything newer online. One task, one line per item."""
        if self.net != "online":
            self.toast("Offline: no network from EmulationStation (Y looks again)" if self.net != "checking"
                       else "Still looking online…", 4)
            return
        todo = keys if keys is not None else self.library_newer()
        if not todo:
            self.toast("The shelf has the newest of everything", 3)
            return
        names = ["%s %s" % (shelf.PRODUCTS[p]["short"], shelf.CHANNEL_NAMES[ch]) for p, ch in todo]

        def work(t):
            got, skipped, failed = [], [], []
            for i, (p, ch) in enumerate(todo):
                o = self.online.get((p, ch))
                c = shelf.best(p, ch)
                what = "%s %s" % (shelf.PRODUCTS[p]["short"], shelf.CHANNEL_NAMES[ch])
                if not o:
                    skipped.append("%s: no release online" % what)
                    t.line("%s: no release online" % what)
                    continue
                if c and c["tag"] == o["tag"]:
                    skipped.append("%s: has %s already" % (what, o["version"]))
                    t.line("%s: the shelf has %s already" % (what, o["version"]))
                    continue
                t.step, t.pct = "%d/%d  %s %s" % (i + 1, len(todo), what, o["version"]), 0
                try:
                    self.fetch_fn(p, ch, o, self._pct(t), t.line)
                    got.append("%s %s" % (what, o["version"]))
                except Exception as e:
                    failed.append("%s: %s" % (what, e))
                    t.line("%s: not taken: %s" % (what, e))
                if p == "stump":
                    self._bundle, self._packs = False, None
            self.lib["checked"] = set()
            msg = []
            if got:
                msg.append("On the shelf (offline from now on): %s." % ", ".join(got))
            if skipped:
                msg.append("Left as is: %s." % "; ".join(skipped))
            if failed:
                msg.append("Not taken: %s." % "; ".join(failed))
            return not failed, " ".join(msg), None
        self.task = Task("Refreshing the library: %s" % ", ".join(names), work)
        self.task.after = "library"
        self.screen = "run"

    def draw_library(self):
        d, lib = self.d, self.lib
        rows = self.library_rows()
        d.fill_rrect(12, TOP + 2, W - 24, 40, 8, PANEL)
        line, tone = self.net_line()
        d.text(F16, 26, TOP + 13, line, tone, W - 52)
        n_checked = len(lib["checked"])
        d.text(F16, 16, TOP + 54, "THE SHELF AND THE CATALOGUE" + ("  ·  %d CHECKED" % n_checked if n_checked else ""),
               EMBER)
        rh = 62
        vis = fits(TOP + 78, rh)
        first = window(lib["sel"], len(rows), vis)
        for k, r in enumerate(rows[first:first + vis]):
            i, y = first + k, TOP + 78 + k * rh
            sel = i == lib["sel"]
            if sel:
                d.stroke_rrect(12, y, W - 24, rh - 6, 8, EMBER, PANEL)
            if r["kind"] == "shelf":
                p, ch = r["p"], r["ch"]
                c, o = shelf.best(p, ch), self.newer_online(p, ch)
                checked = r["key"] in lib["checked"]
                d.stroke_rrect(26, y + 12, 22, 22, 5, EMBER if (checked or sel) else BORDER, EMBER if checked else PANEL2)
                if checked:
                    d.text(F16, 29, y + 14, "✓", BG)
                title = "%s  ·  %s" % (shelf.PRODUCTS[p]["short"], shelf.CHANNEL_NAMES[ch])
                if c:
                    about = "%s · %s" % (c["version"], "on the card" if c["where"] == "card" else "built in")
                else:
                    about = "not on the shelf"
                if o:
                    tag, tc = "online: %s" % o["version"], EMBER_BRIGHT
                elif self.net == "online" and c:
                    tag, tc = "the newest", OK
                else:
                    tag, tc = "", MUTED
                about += " · " + shelf.PRODUCTS[p][ch].split("/")[-1]
            else:
                e = r["entry"]
                title = e["title"]
                about = "built in · %s · for %s" % ("full image" if e.get("mode") == "full" else "app image",
                                                     ", ".join(e.get("boards", [])))
                tag, tc = ("built in", MUTED) if e["status"] == "ready" else ("coming", MUTED)
            tw = d.text_width(F16, tag)
            d.text(F20, 60, y + 8, title, (EMBER_BRIGHT if sel else TEXT) if r["kind"] == "shelf" or r["entry"]["status"]
                   == "ready" else MUTED, W - 114 - tw)
            if tag:
                d.text(F16, W - 28 - tw, y + 11, tag, tc)
            d.text(F16, 60, y + 34, about, MUTED, W - 86)
        self.hints([("A", "check"), ("X", "refresh checked" if n_checked else "refresh all newer"), ("L", "all / none"),
                    ("Y", "look online"), ("B", "back")])

    # -- one product: Official, Sandbox, + From File (and its own jobs) --
    def open_product(self, p, back="handheld"):
        self.prod, self.psel, self.prod_back = p, 0, back
        self.screen = "product"
        self.look_online()

    def product_rows(self):
        p, rows = self.prod, []
        for ch in shelf.CHANNELS:
            if shelf.PRODUCTS[p].get(ch):
                rows.append({"kind": "src", "ch": ch})
        if p == "handheld":
            clone = handheld.find_installer() if self.clones else None
            if clone:
                rows.append({"kind": "clone", "inst": clone})
        rows.append({"kind": "fromfile"})
        if p == "handheld":
            if (self.handheld or {}).get("installed"):
                rows += [{"kind": "hh_pw", "key": "FSERVBOT_OP_PASSWORD"}, {"kind": "hh_pw", "key": "AUTH_ADMIN_PASSWORD"}]
            rows.append({"kind": "hh_check"})
        if p == "provisioner" and installers.version_in(installers.previous_dir(self.app_dir)):
            rows.append({"kind": "rollback"})
        return rows

    def system_why(self, p):
        """Why this product can't be installed on this handheld, or ''."""
        if p == "stump":
            return ""
        if p == "provisioner":
            return installers.self_update_why(self.app_dir)
        if self.handheld is not None:
            return self.handheld.get("why", "")
        return handheld.system_why()

    def on_product(self, act):
        rows = self.product_rows()
        self.psel = min(self.psel, len(rows) - 1)
        r, p = rows[self.psel], self.prod
        if act in ("up", "down"):
            self.psel = (self.psel + (1 if act == "down" else -1)) % len(rows)
        elif act == "b":
            self.screen = self.prod_back
        elif act == "x" and r["kind"] == "src":
            self.get_online(p, r["ch"])
        elif act == "y" and r["kind"] in ("src", "clone") and p == "handheld":
            self.handheld_source(r, new_answers=True)
        elif act == "y":
            self.look_online(force=True)
            self.toast("Looking online…")
        elif act == "a":
            if r["kind"] == "src":
                c = shelf.best(p, r["ch"])
                if not c:
                    o = self.newer_online(p, r["ch"])
                    self.toast(("Not on the shelf yet: X gets %s %s" % (shelf.CHANNEL_NAMES[r["ch"]], o["version"]))
                               if o else "Not on the shelf, and nothing online: + From File", 5)
                else:
                    self.use_copy(c)
            elif r["kind"] == "clone":
                self.handheld_source(r)
            elif r["kind"] == "fromfile":
                self.open_files(product=p)
            elif r["kind"] == "hh_check":
                self.check_handheld()
            elif r["kind"] == "hh_pw":
                self.ask_password(r["key"])
            elif r["kind"] == "rollback":
                prev = installers.version_in(installers.previous_dir(self.app_dir))
                self.ask("Go back to the Provisioner v%s?" % prev,
                         ["The one before the last update, kept for this.", "This one (v%s) is kept in its place, "
                          "to swap back." % self.version, "Then close it and open it again from Ports."],
                         "Go back", lambda: self.run_task("Going back to v%s" % prev,
                                                          lambda t: installers.rollback(self.app_dir), after="quit"))

    def get_online(self, p, ch):
        if self.net != "online":
            self.toast("Offline: no network from EmulationStation (Y looks again)" if self.net != "checking"
                       else "Still looking online…", 4)
            return
        o = self.online.get((p, ch))
        if not o:
            self.toast("No %s release online" % shelf.CHANNEL_NAMES[ch], 4)
            return
        c = shelf.best(p, ch)
        if c and c["tag"] == o["tag"]:
            self.toast("The shelf has %s already" % o["version"], 3)
            return
        self.run_task("Getting %s %s %s" % (shelf.PRODUCTS[p]["short"], shelf.CHANNEL_NAMES[ch], o["version"]),
                      lambda t: self._fetched(p, ch, o, t), after="product")

    def _fetched(self, p, ch, o, t):
        t.step, t.pct = "Downloading and checking (SHA-256)", 0
        try:
            c = self.fetch_fn(p, ch, o, self._pct(t), t.line)
        except Exception as e:
            return False, "Not taken: %s" % e
        if p == "stump":
            self._bundle, self._packs = False, None
        return True, "On the shelf (offline from now on): %s %s." % (shelf.CHANNEL_NAMES[ch], c["version"])

    def use_copy(self, c):
        """Installs (or, for the CAM's Stump, chooses) a shelf copy or a file."""
        p = c["product"]
        why = self.system_why(p)
        if why:
            self.toast(why, 6)
            return
        what = "%s (%s)" % (c["version"], "from a file" if c["channel"] == "file" else shelf.CHANNEL_NAMES[c["channel"]])
        if p == "stump":
            self.stump_src = c
            self._bundle, self._packs = False, None
            self.toast("The boards get the Stump %s now" % what, 4)
        elif p == "firefly":
            have = self.installed("firefly")
            self.ask("%s FireFly %s?" % ("Update to" if have else "Install", what),
                     ["FireFly's own installer (~/firefly; Ports -> FireFly).",
                      "Its identity, contacts, messages and settings stay (~/.firefly)." if have else
                      "A first install needs internet once (packages, Reticulum); reboot after it.",
                      "Now: %s." % (have or "not installed")],
                     "Install", lambda: self.run_task("Installing FireFly %s" % c["version"], lambda t: self._marked(
                         p, c, installers.firefly_install(c, t.line, self._step(t))), after="product"))
        elif p == "provisioner":
            self.ask("Install the Provisioner %s?" % what,
                     ["Its own install.sh, over this one (v%s, kept to go back to)." % self.version,
                      "Then close it and open it again from Ports."],
                     "Install", lambda: self.run_task("Installing the Provisioner %s" % c["version"],
                                                      lambda t: installers.self_update(c, t.line, self._step(t),
                                                                                       self.app_dir), after="quit"))
        elif p == "handheld":
            try:
                inst = installers.handheld_installer(c)
            except Exception as e:
                self.toast("Couldn't unpack it: %s" % e, 5)
                return
            self.handheld_source({"kind": "clone", "inst": inst})

    def _marked(self, p, c, result):
        ok, msg = result
        if ok:
            installers.mark(p, c)
        return ok, msg

    def handheld_source(self, r, new_answers=False):
        """The handheld's Stump by this installer: Update (keeps settings) when
        there's one, else (or with Y) the form."""
        if r["kind"] == "src":
            c = shelf.best("handheld", r["ch"])
            if not c:
                self.toast("Not on the shelf: X gets it, or + From File", 4)
                return
            try:
                inst = installers.handheld_installer(c)
            except Exception as e:
                self.toast("Couldn't unpack it: %s" % e, 5)
                return
        else:
            inst = r["inst"]
        why = self.system_why("handheld")
        if why:
            self.toast(why, 6)
            return
        if not inst["answers"]:
            self.toast("%s %s can't take answers from here: v2.3.0-r36max or newer can" % (
                inst["repo"], inst["version"]), 6)
            return
        self.hh_inst = inst
        st = self.handheld or {}
        if st.get("installed") and not new_answers:
            self.ask("Update this handheld's Stump?",
                     ["By %s %s: Team Stump's latest SandBox_Stump_On (a newer one needs internet) and its cockpit."
                      % (inst["repo"], inst["version"]),
                      "Its settings, identity on the mesh, files and chain stay. (Y on the row: new answers.)"
                      + (" /admin's password isn't its own: set Its password after." if self.admin_state() != "SET" else ""),
                      ("Checked once, then stopped: it runs while its Port is open. A few minutes."
                       if st.get("port") else "The Stump restarts. A few minutes.")],
                     "Update it", lambda: self.run_handheld("Updating this handheld's Stump",
                                                            handheld.update_answers(st.get("folder"))))
        else:
            self.open_form("handheld", handheld.form_defaults(self.here), back="product")

    def ask_password(self, key):
        """One of the handheld Stump's passwords, typed twice on the keyboard, then set:
        its password (the fserv operator's, which /admin takes too) or a separate /admin one."""
        one = key == "FSERVBOT_OP_PASSWORD"
        name = "its password" if one else "a separate /admin password"
        folder = (self.handheld or {}).get("folder") or os.path.expanduser("~/Stump")

        def second(first):
            def done(again):
                if again != first:
                    self.toast("They differ: nothing changed", 4)
                elif not 4 <= len(first) <= 64:
                    self.toast("4 to 64 characters: nothing changed", 4)
                else:
                    self.ask("Set %s?" % name,
                             [("/admin and the fserv bot take it (unless a separate /admin one is set)." if one else
                               "/admin takes this one instead of its password."),
                              "Written into ~/Stump/config.py by the Stump's own settings (as /admin does); "
                              "config.py.bak kept. " + ("It takes it when its Port opens next."
                                                        if (self.handheld or {}).get("port") else
                                                        "The Stump restarts with it.")],
                             "Set it", lambda: self.run_task("Setting %s" % name, lambda t: self.set_password_fn(
                                 folder, key, first, t.line)))
            self.kb = Keyboard("Again: %s" % name, "", 64, secret=True, hint="The same again")
            self.kb_done = done
        self.kb = Keyboard(name[0].upper() + name[1:], "", 64, secret=True,
                           hint="4 to 64 characters" + (": /admin and the fserv bot" if one else ""))
        self.kb_done = second

    def run_task(self, title, fn, after="product"):
        def work(t):
            ok, msg = fn(t)
            return ok, msg, None
        self.task = Task(title, work)
        self.task.after = after
        self.screen = "run"

    def draw_product(self):
        d, p = self.d, self.prod
        rows = self.product_rows()
        d.fill_rrect(12, TOP + 2, W - 24, 58, 8, PANEL)
        line, tone = self.installed_line(p)
        d.text(F20, 26, TOP + 8, line, tone, W - 52)
        line, tone = self.net_line()
        d.text(F16, 26, TOP + 34, line, tone, W - 52)
        d.text(F16, 16, TOP + 72, "INSTALL FROM" if p != "stump" else "THE BOARDS GET", EMBER)
        rh = 72
        vis = fits(TOP + 96, rh)
        first = window(self.psel, len(rows), vis)
        why = self.system_why(p)
        now = self.installed(p)
        st_folder = (self.handheld or {}).get("folder") or os.path.expanduser("~/Stump")
        for k, r in enumerate(rows[first:first + vis]):
            i, y = first + k, TOP + 96 + k * rh
            sel = i == self.psel
            if sel:
                d.stroke_rrect(12, y, W - 24, rh - 6, 8, EMBER, PANEL)
            tag, tc, ready = "", MUTED, not why
            if r["kind"] == "src":
                c, o = shelf.best(p, r["ch"]), self.newer_online(p, r["ch"])
                name = shelf.CHANNEL_NAMES[r["ch"]]
                title = "%s %s" % (name, c["version"]) if c else "%s: not on the shelf" % name
                repo = shelf.PRODUCTS[p][r["ch"]].split("/")[-1]
                about = "%s · %s" % (repo, ("on the shelf" if c else "nothing here yet"))
                if o:
                    about += " · online: %s (X gets it)" % o["version"]
                elif self.net == "online" and c:
                    about += " · the newest"
                if c and now and c["version"] == now:
                    tag, tc = ("the boards get it" if p == "stump" else "installed"), OK
                ready = ready and bool(c)
            elif r["kind"] == "clone":
                title = "Your clone: %s %s" % (r["inst"]["repo"], r["inst"]["version"])
                about = "~/%s (git): what you put there over SSH" % r["inst"]["repo"]
            elif r["kind"] == "fromfile":
                title = "+ From File"
                about = "A %s from the card or a USB drive, read for what it is first." % " / ".join(
                    shelf.PRODUCTS[p]["file"])
            elif r["kind"] == "hh_check":
                title, about, ready = "Check it", "Asks the Stump on this handheld: release, name, chain.", True
            elif r["kind"] == "hh_pw":
                state = self.password_state_fn(st_folder, r["key"]) if self.password_state_fn else "SET"
                ready = True
                if r["key"] == "FSERVBOT_OP_PASSWORD":
                    title = "Its password"
                    about = {"SET": "Its own: /admin and the fserv bot take it. A changes it.",
                             "EMPTY": "None: /admin can't be opened. A sets one.",
                             "DEFAULT": "Still SandBox_Stump_On's: A sets its own."}.get(state, "")
                    if self.admin_state() != "SET" or state == "DEFAULT":
                        tag, tc = "set one", ERROR
                else:
                    title = "A separate /admin password"
                    about = {"SET": "Its own: /admin takes this one, not the one above. A changes it.",
                             "EMPTY": "None: /admin takes the one above (as Team Stump means it).",
                             "DEFAULT": "SandBox_Stump_On's, left by the wizard: setting Its password clears it."
                             }.get(state, "")
            else:
                title = "Go back to v%s" % installers.version_in(installers.previous_dir(self.app_dir))
                about = "The Provisioner before the last update (kept for this)."
            tw = d.text_width(F16, tag)
            d.text(F24, 26, y + 6, title, (EMBER_BRIGHT if sel else TEXT) if ready else MUTED, W - 80 - tw)
            if tag:
                d.text(F16, W - 28 - tw, y + 12, tag, tc)
            d.text(F16, 26, y + 38, about, MUTED, W - 52)
        cur = rows[min(self.psel, len(rows) - 1)]
        hints = [("A", "use it" if p == "stump" else "install")]
        if cur["kind"] == "src":
            hints.append(("X", "get online"))
        hints.append(("Y", "new answers" if p == "handheld" and cur["kind"] in ("src", "clone") else "look online"))
        self.hints(hints + [("B", "back")])

    # -- this handheld's Stump: the form, the installer, the check --
    def admin_state(self):
        """What /admin takes on the handheld's Stump (handheld.access_state)."""
        st = self.handheld or {}
        return self.access_state_fn(st.get("folder") or os.path.expanduser("~/Stump")) if self.access_state_fn \
            else "SET"

    def handheld_form_rows(self, a):
        st = self.handheld or {}
        keep = st.get("installed") and self.password_state_fn and self.password_state_fn(
            st.get("folder") or os.path.expanduser("~/Stump"), "FSERVBOT_OP_PASSWORD") == "SET"
        rows = [{"key": "name", "label": "Its name", "kind": "text", "max": 20, "blank": "needed"},
                {"key": "pw", "label": "Its password", "kind": "secret", "max": 64,
                 "blank": "keeps the one it has" if keep else "needed: /admin and the fserv bot"},
                {"key": "apw", "label": "Separate /admin password", "kind": "secret", "max": 64,
                 "blank": "none: /admin takes the one above"},
                {"key": "hotspot", "label": "Its Wi-Fi's name", "kind": "text", "max": 32, "blank": "its name"},
                {"key": "storage", "label": "Storage (MB)", "kind": "text", "max": 7, "blank": "2048"},
                {"key": "chain", "label": "Chain", "kind": "choice", "choices": CHAINS}]
        if a.get("chain") == "member":
            rows += [{"key": "parent", "label": "Joins (its address)", "kind": "text", "max": 15,
                      "blank": "needed: e.g. 192.168.1.20"}]
        if a.get("chain") in ("first", "member"):
            rows += [{"key": "secret", "label": "The chain's secret", "kind": "text", "max": 64, "blank": "none (open)"}]
        rows += [{"key": "heltec", "label": "LoRa", "kind": "choice", "choices": HELTECS},
                 {"key": "tavern", "label": "Tavern pack", "kind": "choice", "choices": YESNO},
                 {"key": "rnfs", "label": "rnfs pack", "kind": "choice", "choices": YESNO},
                 {"key": "go", "label": "Install the Stump", "kind": "button"}]
        return rows

    def submit_handheld(self):
        st = self.handheld or {}
        a = self.form["a"]
        folder = st.get("folder") or os.path.expanduser("~/Stump")
        ans = handheld.answers(a, folder, again=bool(st.get("installed")),
                               current=self.current_passwords_fn(folder) if st.get("installed") else None)
        if ans.get("error"):
            self.toast(ans["error"], 4)
            return
        lines = ["%s on this handheld, by %s's installer: Team Stump's own wizard, answered from this form." % (
                 ans["node name"], self.hh_inst["repo"])]
        if st.get("installed"):
            lines.append("Its Stump is there: these answers replace its settings; its identity and files stay.")
        else:
            lines.append("The first install needs internet: packages, SandBox_Stump_On, its Python. 10-20 minutes.")
        if a.get("chain") in ("first", "member") and not a.get("secret"):
            lines.append("No chain secret: anyone on a Stump's Wi-Fi could join the chain.")
        self.ask("Install this handheld's Stump?", lines, "Install", lambda: self.run_handheld(
            "Installing this handheld's Stump", ans))

    def run_handheld(self, title, ans):
        inst = self.hh_inst
        folder = (self.handheld or {}).get("folder") or os.path.expanduser("~/Stump")

        def work(t):
            ok, msg = self.handheld_run(inst, ans, t.line, self._step(t))
            # If SandBox_Stump_On's AUTH_ADMIN_PASSWORD is still there (an installer
            # before v2.4.0-r36max), cleared: /admin takes its one password.
            if ok and self.clear_repo_admin_fn:
                changed, why = self.clear_repo_admin_fn(folder, t.line)
                if changed:
                    msg += " /admin takes its password (the repo's was left: cleared)."
                elif why:
                    ok, msg = False, msg + " /admin's password isn't its own: %s" % why
            return ok, msg, None
        self.form = None
        self.task = Task(title, work)
        self.task.after = "product"
        self.screen = "run"

    def check_handheld(self):
        fn, st = self.here_fn, self.handheld or {}

        def work(t):
            t.step = "Asking the Stump on this handheld (:80, :8080)"
            h = fn() if fn else {"none": True}
            self.here = h
            if h and not h.get("none"):
                return True, "Stump %s · %s%s: it answers." % (h.get("release", "?"), h.get("name", "?"),
                                                              " · " + h["chain"] if h.get("chain") else ""), None
            if st.get("installed") and st.get("port"):
                return True, ("It's installed, and not running: %s So never beside the Provisioner (one Port "
                              "at a time). Its check runs at each Install or Update." % handheld.PORT_NOTE), None
            if st.get("installed"):
                return False, "It's installed but doesn't answer: ~/Stump/stump.log says why (Update starts it again).", None
            return False, "No Stump on this handheld yet: Install a Stump.", None
        self.task = Task("Checking this handheld's Stump", work)
        self.task.after = "product"
        self.screen = "run"

    def draw_here(self, y):
        """This handheld's own Stump, on one line at the top right."""
        h = self.here
        if not h:
            return
        if h.get("none"):
            s, c = "This handheld: no Stump (R36MAX-Stump installs it)", MUTED
        else:
            s, c = "This handheld: Stump %s · %s%s" % (h.get("release", "?"), h.get("name", "?"),
                                                      " · " + h["chain"] if h.get("chain") else ""), OK
        d = self.d
        w = min(d.text_width(F16, s), W - 260)
        d.text(F16, W - 16 - w, y, s, c, W - 260)

    def draw_wifi(self):
        d, w = self.d, self.wifi
        if not w:
            return
        st = w["status"] or {}
        d.fill_rrect(12, TOP + 2, W - 24, 78, 8, PANEL)
        line, tone = self.adapter_line(st)
        if w["joining"] and st.get("state") != "connected":
            line, tone = "Joining %s…" % w["joining"], EMBER_BRIGHT
        d.text(F20, 26, TOP + 10, line, tone, W - 52)
        if st.get("state") == "connected":
            a = w.get("address")
            net = ("This handheld: %s on it" % a) if a else "This handheld: asking that network for an address…"
            inet = {"yes": " · internet OK", "no": " · no internet through it", "checking": ""}
            d.text(F16, 26, TOP + 44, net + inet.get(w["internet"], ""), MUTED if w["internet"] != "no" else ERROR,
                   W - 52)
        else:
            d.text(F16, 26, TOP + 44, "A joins a network; saved ones join by themselves.",
                   MUTED, W - 52)
        d.text(F16, 16, TOP + 92, "NETWORKS", EMBER)
        rows = self.wifi_rows()
        if not rows:
            d.text(F20, 26, TOP + 130, "Looking…" if not w["loaded"] else "None in range (X looks again).", MUTED)
        rh = 62
        vis = fits(TOP + 116, rh)
        w["sel"] = min(w["sel"], max(0, len(rows) - 1))
        first = window(w["sel"], len(rows), vis)
        for k, r in enumerate(rows[first:first + vis]):
            i = first + k
            y = TOP + 116 + k * rh
            sel = i == w["sel"]
            if sel:
                d.stroke_rrect(12, y, W - 24, rh - 6, 8, EMBER, PANEL)
            on = st.get("state") == "connected" and st.get("ssid") == r["ssid"]
            if r["here"]:
                self.draw_bars(26, y + 14, s3wifi.bars(r["rssi"]), OK if on else TEXT)
            tags = []
            if on:
                tags.append(("connected", OK))
            elif w["joining"] == r["ssid"]:
                tags.append(("joining…", EMBER_BRIGHT))
            if r["saved"]:
                tags.append(("saved", MUTED))
            if not r["here"]:
                tags.append(("not in range", MUTED))
            elif r["open"]:
                tags.append(("open", MUTED))
            else:
                tags.append(("password", MUTED))
            tag = "  ·  ".join(t for t, _ in tags)
            tw = d.text_width(F16, tag)
            d.text(F24, 70, y + 14, r["ssid"], (EMBER_BRIGHT if sel else TEXT) if r["here"] else MUTED,
                   W - 110 - tw)
            d.text(F16, W - 28 - tw, y + 20, tag, tags[0][1])
        self.hints([("A", "join"), ("Y", "forget"), ("X", "look again"), ("↑↓", "move"), ("B", "back")])

    def draw_jobs(self):
        d = self.d
        k = self.known[self.cur["port"]]
        b, inf = k["board"], k["info"]
        d.fill_rrect(12, TOP + 2, W - 24, 58, 8, PANEL)
        d.text(F20, 26, TOP + 8, "%s  ·  %s" % (b["name"], inf["chip_text"]), TEXT, W - 52)
        d.text(F16, 26, TOP + 34, "%s · %g MB flash%s · MAC %s" % (self.cur["port"], inf["flash_mb"],
               " · PSRAM %d MB" % inf["psram_mb"] if inf["psram_mb"] else "", inf["mac"]), MUTED, W - 52)
        d.text(F16, 16, TOP + 72, "WHAT IT CAN BE GIVEN", EMBER)
        rows = self.jobs()
        rh = 72
        vis = fits(TOP + 96, rh)
        first = window(self.jsel, len(rows), vis)
        for k, r in enumerate(rows[first:first + vis]):
            i = first + k
            y = TOP + 96 + k * rh
            sel = i == self.jsel
            if sel:
                d.stroke_rrect(12, y, W - 24, rh - 6, 8, EMBER, PANEL)
            b = self.bundle()
            if r["kind"] == "src_stump":
                c = self.stump_copy()
                title = "Stump: %s" % (shelf.describe(c) if c else "none on the shelf")
                about = ("◀ ▶ Official / Sandbox%s · A: + From File, get the newest online" %
                         (" / the file" if self.stump_src and self.stump_src["channel"] == "file" else ""))
                tag, tc, ready = ("◀ ▶" if sel else ""), MUTED, True
            elif r["kind"].startswith("stump_"):
                rel = b.release if b else "?"
                title, about, tag, tc = {
                    "stump_new": ("Make a Stump", "Erases it, writes the Stump %s%s, asks its name, "
                                  "password, Wi-Fi, chain, radio." % (rel, " image" if b and b.images else ""),
                                  "erases", ERROR),
                    "stump_update": ("Update its Stump", "To %s%s; its settings, identity and card stay." % (
                        rel, " (its image in place when it runs one)" if b and b.images else ""), "keeps settings", OK),
                    "stump_settings": ("Its Stump's settings", "Read them, change them, save (as /admin does).", "", MUTED),
                    "stump_check": ("Check it starts", "Restarts it and listens: release, serving, problems.", "", MUTED),
                }[r["kind"]]
                ready = b is not None
            elif r["kind"] == "fw":
                e = r["entry"]
                ready = e["status"] == "ready"
                title, about = e["title"], e.get("about", "")
                tag = ("full install" if e["mode"] == "full" else "app only") if ready else "coming"
                tc = (ERROR if e["mode"] == "full" else OK) if ready else MUTED
            elif r["kind"] == "log":
                title, about, tag, tc, ready = "Serial log", "What the board prints, at 115200.", "", MUTED, True
            elif r["kind"] == "fromfile":
                title, about, tag, tc, ready = ("+ From File", "A .bin from the card or a USB drive (what it is is read "
                                                "from the file), or a pack's .zip for a Stump.", "", MUTED, True)
            elif r["kind"] == "pack":
                pl = r["plan"]
                if pl:
                    title, about = "Add the %s pack %s" % (pl["name"].capitalize(), pl["version"]), pl["description"]
                    tag, tc, ready = "keeps settings", OK, True
                else:
                    title, about, tag, tc, ready = (os.path.basename(r["path"]), r["error"], "won't install",
                                                    ERROR, False)
            else:
                title, about, tag, tc, ready = ("Erase the whole flash", "Everything on the board goes.",
                                                "erases", ERROR, True)
            tw = d.text_width(F16, tag)
            d.text(F24, 26, y + 6, title, (EMBER_BRIGHT if sel else TEXT) if ready else MUTED, W - 80 - tw)
            if tag:
                d.text(F16, W - 28 - tw, y + 12, tag, tc)
            d.text(F16, 26, y + 38, about, MUTED, W - 52)
        self.hints([("A", "choose"), ("B", "boards"), ("Y", "serial log"), ("↑↓", "move")])

    def draw_run(self):
        d, t = self.d, self.task
        if not t:
            return
        d.text(F24, 20, TOP + 20, t.step if not t.done else ("Done" if t.ok else "It didn't work"),
               TEXT if not t.done else (OK if t.ok else ERROR), W - 40)
        bar_y = TOP + 64
        d.fill_rrect(20, bar_y, W - 40, 26, 8, PANEL)
        if t.done and t.ok:
            t.pct = 100
        if t.pct is not None:
            wpx = int((W - 44) * max(0, min(100, t.pct)) / 100)
            if wpx > 8:
                d.fill_rrect(22, bar_y + 2, wpx, 22, 7, OK if (t.done and t.ok) else EMBER)
            pct = "%d %%" % t.pct
            d.text(F16, W // 2 - d.text_width(F16, pct) // 2, bar_y + 4, pct, TEXT)
        elif not t.done:
            x = int((time.time() * 240) % (W - 140))
            d.fill_rrect(22 + x, bar_y + 2, 96, 22, 7, EMBER)
        y = TOP + 104
        if t.done:
            msg = wrap(d, F20, t.msg, W - 80)[:4]
            d.fill_rrect(20, y, W - 40, 20 + 28 * len(msg), 8, PANEL)
            for i, s in enumerate(msg):
                d.text(F20, 36, y + 10 + i * 28, s, OK if t.ok else ERROR, W - 72)
            y += 20 + 28 * len(msg) + 18
            # What it said as it started (its Wi-Fi, the chain, its Heltec): a row each
            rows = t.report[:max(0, (BOT - 6 - y - 60) // 24)]
            lw = max([d.text_width(F16, k) for k, _, _ in rows if k] or [0]) + 14
            for k, v, lvl in rows:
                if k:
                    d.text(F16, 24, y, k, MUTED)
                d.text(F16, 24 + (lw if k else 0), y, v, {"ok": OK, "err": ERROR, "warn": EMBER_BRIGHT}.get(lvl, TEXT),
                       W - 48 - (lw if k else 0))
                y += 24
            if rows:
                y += 10
        else:
            y += 18
        d.text(F16, 20, y, "LOG", EMBER)
        n = max(0, (BOT - 6 - (y + 24)) // 20)
        for i, s in enumerate(t.tail(n)):
            d.text(F16, 20, y + 24 + i * 20, s, MUTED, W - 40)
        self.hints([("A", "continue"), ("B", "back")] if t.done else [("", "working: leave it plugged in")])

    def draw_files(self):
        d, fb = self.d, self.fb
        if not fb:
            return
        where = fb["path"] or "Where to look"
        d.text(F16, 16, TOP + 6, where, EMBER, W - 32)
        es = fb["entries"]
        if not es:
            d.text(F20, 26, TOP + 44, "Nothing here to flash (Y shows every file)." if fb["path"] else
                   "No card or drive found.", MUTED, W - 52)
        rh = 52
        vis = fits(TOP + 34, rh)
        first = window(fb["sel"], len(es), vis)
        for k, e in enumerate(es[first:first + vis]):
            i, y = first + k, TOP + 34 + k * rh
            sel = i == fb["sel"]
            if sel:
                d.stroke_rrect(12, y, W - 24, rh - 6, 8, EMBER, PANEL)
            if e.get("root"):
                name, info = e["name"], e["path"]
            elif e["dir"]:
                name, info = e["name"] + "/", "folder"
            else:
                name, info = e["name"], files.human(e["size"])
            iw = d.text_width(F16, info)
            d.text(F20, 26, y + 12, name, (EMBER_BRIGHT if sel else TEXT) if (e["dir"] or not fb["show_all"]
                   or e["name"].lower().endswith(fb.get("exts", files.USABLE))) else MUTED, W - 70 - iw)
            d.text(F16, W - 28 - iw, y + 15, info, MUTED)
        if len(es) > vis:
            track = vis * rh
            th = max(14, track * vis // len(es))
            d.fill(W - 10, TOP + 34, 4, track, PANEL)
            d.fill(W - 10, TOP + 34 + (track - th) * first // max(1, len(es) - vis), 4, th, MUTED)
        if fb["path"] is None:
            self.hints([("A", "open"), ("↑↓", "move"), ("B", "back")])
        else:
            self.hints([("A", "open / choose"), ("B", "up"), ("Y", "all files" if not fb["show_all"] else ".bin .zip"),
                        ("←→", "page")])

    def draw_log(self):
        d, v, log = self.d, self.logv, self.log
        if not log:
            return
        paused = v["frozen"] is not None
        lines = [t for _, t in v["frozen"]] if paused else log.snapshot()
        n, rh, top = len(lines), self.LOG_ROW, TOP + 34
        if log.error:
            d.text(F20, 20, TOP + 6, log.error, ERROR, W - 40)
        elif not lines:
            d.text(F20, 20, TOP + 6, "Listening… (nothing yet: press the board's RESET to see it boot)", MUTED,
                   W - 40)
        else:
            d.text(F16, 16, TOP + 8, "%d line%s" % (n, "" if n == 1 else "s"), MUTED)
        vis = self.log_rows()
        detail = []
        if paused and n:
            cur = v["cur"] = min(v["cur"], n - 1)
            per = (W - 64) * 64 // d.fonts[F16]["adv64"]
            full = lines[cur]
            if len(full) > (W - 48) * 64 // d.fonts[F16]["adv64"]:      # cut on screen: spell it out below
                detail = [full[k:k + per] for k in range(0, len(full), per)][:6]
                vis -= len(detail) + 1
            first = max(0, min(cur - vis // 2, n - vis))
        else:
            cur, first = -1, max(0, n - vis)
        block = sorted((v["mark"], cur)) if paused and v["mark"] is not None else None
        for k, s in enumerate(lines[first:first + vis]):
            i, y = first + k, top + k * rh
            if i == cur:
                d.fill_rrect(10, y - 1, W - 34, rh, 4, EMBER)
            elif block and block[0] <= i <= block[1]:
                d.fill(10, y - 1, W - 34, rh, BORDER)
            d.text(F16, 16, y, s, BG if i == cur else TEXT, W - 48)
        if n > vis:                                   # where this is in the whole log
            track_h = vis * rh
            d.fill(W - 18, top, 6, track_h, PANEL)
            th = max(14, track_h * vis // n)
            ty = top + (track_h - th) * first // max(1, n - vis)
            d.fill_rrect(W - 19, ty, 8, th, 3, EMBER_BRIGHT if paused else MUTED)
        if detail:
            y = top + vis * rh + 8
            d.fill_rrect(10, y, W - 34, 12 + len(detail) * rh, 6, PANEL)
            for k, s in enumerate(detail):
                d.text(F16, 22, y + 6 + k * rh, s, TEXT)
        tag = ("paused · line %d of %d" % (cur + 1, n)) if paused and n else ("paused" if paused else "live")
        if block:
            tag += " · block %d-%d" % (block[0] + 1, block[1] + 1)
        tw = d.text_width(F16, tag) + 20
        d.fill_rrect(W - 16 - tw, TOP + 4, tw, 26, 6, EMBER if paused else PANEL)
        d.text(F16, W - 6 - tw, TOP + 7, tag, BG if paused else MUTED)
        if paused:
            self.hints([("A", "resume"), ("↑↓", "line"), ("←→", "page"),
                        ("X", "block" if v["mark"] is None else "unblock"),
                        ("Y", "export block" if v["mark"] is not None else "export"), ("B", "back")])
        else:
            self.hints([("A", "pause"), ("Y", "export"), ("X", "clear"), ("B", "back")])

    def draw_confirm(self):
        d, c = self.d, self.confirm
        tone = ERROR if c["danger"] else OK
        # The box fits its text: the body in F20, or F16 when F20 won't fit
        # between the header and the hints.
        area = 8 if H < 560 else TOP + 10       # a short screen: over the header too
        room = BOT - 8 - area - (66 + 20 + 54 + 20)
        for font, lh in ((F20, 26), (F16, 21)):
            body = [wrap(d, font, s, W - 150) for s in c["lines"]]
            h = sum(len(b) * lh + 4 for b in body)
            if h <= room:
                break
        h = min(h, room)
        box_h = 66 + h + 20 + 54 + 20
        top = max(area, (BOT + area - box_h) // 2)
        d.stroke_rrect(50, top, W - 100, box_h, 10, tone, PANEL)
        d.text(F24, 74, top + 20, c["title"], tone, W - 148)
        y, end = top + 66, top + 66 + h
        for b in body:
            for part in b:
                if y + lh > end + 2:
                    break
                d.text(font, 74, y, part, TEXT, W - 148)
                y += lh
            y += 4
        by = top + box_h - 74
        bw = (W - 148 - 20) // 2
        for i in range(2):
            sel = c["choice"] == i
            bx = 74 + i * (bw + 20)
            lbl = "No, cancel" if i == 0 else c["yes"]
            if sel:
                d.fill_rrect(bx, by, bw, 54, 8, EMBER if i == 0 else tone)
            else:
                d.stroke_rrect(bx, by, bw, 54, 8, BORDER, PANEL2)
            lw = min(d.text_width(F24, lbl), bw - 16)
            d.text(F24, bx + (bw - lw) // 2, by + 12, lbl, BG if sel else TEXT, bw - 16)
        self.hints([("←→", "choose"), ("A", "accept"), ("B", "cancel")])
