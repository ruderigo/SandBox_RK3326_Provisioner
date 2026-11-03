"""The Provisioner's screens: the boards on the hub, what each can be given,
asking first, flashing with progress, a board's serial log, and making a
Stump (a form, FireFly's keyboard).

    BOARDS  --A-->  (identify)  -->  JOBS  --A-->  ask  -->  RUN  --B-->  JOBS
       \\--Y--> LOG                       |\\--> LOG
                                         \\--> FORM (a Stump's answers) --> ask --> RUN

Nothing touches a board until you choose it: identifying a board resets it,
so a port another program has open (the Stump and its Heltec) asks first.
"""

import threading
import time

from .. import boards, catalog, flasher, stump
from ..seriallog import SerialLog
from .keyboard import Keyboard
from .sdl import F16, F20, F24, F30B, W, rgb

BG, PANEL, PANEL2, BORDER = rgb("1b1512"), rgb("2a2119"), rgb("221b15"), rgb("493c2e")
EMBER, EMBER_BRIGHT, TEXT, MUTED = rgb("d97a3a"), rgb("f0a050"), rgb("ecdfc8"), rgb("9c8d76")
ERROR, OK = rgb("e07a5a"), rgb("9cb876")
TOP = 96                                   # under the header
THEME = {"BG": BG, "PANEL": PANEL, "PANEL2": PANEL2, "BORDER": BORDER, "EMBER": EMBER, "TEXT": TEXT, "MUTED": MUTED}
CHAINS = [("none", "No chain"), ("first", "First Stump of a chain"), ("member", "Joins another Stump")]
RADIOS = [("ap", "Heltec on its own Wi-Fi"), ("lan", "Heltec on the home Wi-Fi"), ("none", "No LoRa radio")]


class Task:
    """Something slow (esptool) in the background; the screen shows its state."""

    def __init__(self, title, fn):
        self.title, self.step, self.pct = title, "Starting", None
        self.lines, self.done, self.ok, self.msg, self.result = [], False, False, "", None
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
        self.version = version
        self.entries = catalog.load(firmware_dir)
        self.ports_fn = ports_fn or boards.list_ports
        self.users_fn = users_fn or boards.port_users
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
        self.here = None                # this handheld's own Stump: {release, name, chain} or {"none": True}
        self.here_fn = here_status
        self.next_here = 0.0

    def bundle(self):
        if self._bundle is False:
            try:
                self._bundle = stump.find_bundle(self.bundle_dir)
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
        if time.time() < self.next_scan:
            return
        self.next_scan = time.time() + 1.0
        ports = self.ports_fn()
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
        self.sel = min(self.sel, max(0, len(ports) - 1))

    def jobs(self):
        """The rows of the JOBS screen for the current board."""
        b = self.known.get(self.cur["port"], {}).get("board", {})
        rows = []
        if b.get("id") == "esp32s3":           # the Freenove CAM: a Stump
            rows += [{"kind": k} for k in ("stump_new", "stump_update", "stump_settings", "stump_check")]
        rows += [{"kind": "fw", "entry": e} for e in catalog.for_board(self.entries, b)]
        rows.append({"kind": "log"})
        rows.append({"kind": "erase"})
        return rows

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
                self.form["a"][self.kb_key] = self.kb.text
                self.kb = None
            elif r == "cancel":
                self.kb = None
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
        n = len(self.ports)
        if act in ("up", "down") and n:
            self.sel = (self.sel + (1 if act == "down" else -1)) % n
        elif act in ("a", "x", "y") and n:
            p = self.ports[self.sel]
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
        self.jsel = 0
        self.screen = "jobs"

    def on_jobs(self, act):
        rows = self.jobs()
        if act in ("up", "down"):
            self.jsel = (self.jsel + (1 if act == "down" else -1)) % len(rows)
        elif act == "b":
            self.screen = "boards"
        elif act == "y":
            self.open_log()
        elif act == "a":
            r = rows[self.jsel]
            if r["kind"].startswith("stump_"):
                self.stump_job(r["kind"])
            elif r["kind"] == "log":
                self.open_log()
            elif r["kind"] == "erase":
                self.ask_erase()
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
            else:
                self.screen = "jobs" if self.cur and self.cur["port"] in self.known else "boards"

    # -- a Stump --
    def link_for(self, port):
        return lambda: self.open_link(port)

    def stump_job(self, kind):
        b = self.bundle()
        if not b:
            self.toast("No Stump bundle here (firmware/stump/): reinstall the Provisioner", 4)
            return
        port = self.cur["port"]
        if kind == "stump_new":
            self.open_form("new", {"name": "", "pw": "", "ssid": "", "wpass": "", "hotspot": "", "chain": "none",
                                   "radio": "ap", "secret": "", "upSsid": b.default_ssid, "subnet": "5", "hhost": "",
                                   "features": list(stump.FEATURES[:3])})
        elif kind == "stump_update":
            self.ask("Update its Stump to %s?" % b.release,
                     ["Copies the new release onto the Stump on this board.",
                      "Its settings, its identity on the mesh and its card stay.", "About 4 minutes."],
                     "Update it", lambda: self.run_stump("Updating the Stump", lambda t: stump.make(
                         b, {}, self.link_for(port), None, self._step(t), self._pct(t), t.line, update=True)))
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
            self.run_stump("Checking it starts", lambda t: stump.check_job(self.link_for(port), self._step(t), t.line))

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

    def open_form(self, mode, a):
        self.form = {"mode": mode, "a": a, "sel": 0}
        self.screen = "form"

    def form_rows(self):
        f, a = self.form, self.form["a"]
        keep = f["mode"] == "settings"
        b = self.bundle()
        rows = [{"key": "name", "label": "Its name", "kind": "text", "max": 20, "blank": "needed"},
                {"key": "pw", "label": "Admin password", "kind": "secret", "max": 64,
                 "blank": "keeps the one it has" if keep else "needed (4+ characters)"},
                {"key": "ssid", "label": "Home Wi-Fi (optional)", "kind": "text", "max": 32, "blank": "none"},
                {"key": "wpass", "label": "Home Wi-Fi password", "kind": "secret", "max": 63,
                 "blank": "keeps the one it has" if keep else "none"},
                {"key": "hotspot", "label": "Its own Wi-Fi's name", "kind": "text", "max": 32,
                 "blank": b.default_ssid if b else "the default"},
                {"key": "chain", "label": "Chain", "kind": "choice", "choices": CHAINS}]
        if a.get("chain") == "member":
            rows += [{"key": "upSsid", "label": "Joins (its Wi-Fi)", "kind": "text", "max": 32},
                     {"key": "subnet", "label": "Its number (5-254)", "kind": "text", "max": 3}]
        if a.get("chain") in ("first", "member"):
            rows += [{"key": "secret", "label": "The chain's secret", "kind": "text", "max": 64, "blank": "none (open)"}]
        rows += [{"key": "radio", "label": "LoRa", "kind": "choice", "choices": RADIOS}]
        if a.get("radio") == "lan":
            rows += [{"key": "hhost", "label": "The Heltec's address", "kind": "text", "max": 15}]
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
            self.form, self.screen = None, "jobs"
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
        f, b, port = self.form, self.bundle(), self.cur["port"]
        a = dict(f["a"], pw2=f["a"].get("pw", ""))
        if f["mode"] == "settings":
            a["keepWifiPass"] = True
        s = stump.settings_from(dict(a, requireAdmin=f["mode"] == "new"))
        if s.get("error"):
            self.toast(s["error"], 4)
            return
        if f["mode"] == "new":
            info = self.known[port]["info"]
            lines = ["Erases everything on the board: a Stump on it now loses its identity.",
                     "Stump %s, MicroPython %s. About 5 minutes." % (b.release, b.micropython)]
            if not info.get("psram_mb"):
                lines.append("esptool didn't report PSRAM: the Stump needs the octal-PSRAM board (Freenove N16R8).")
            self.ask("Make a Stump on this board?", lines + s["warn"], "Make it", lambda: self.run_stump(
                "Making the Stump", lambda t: stump.make(
                    b, a, self.link_for(port),
                    lambda img: flasher.write_image(port, "esp32s3", img, "0x0", t.line, self._pct(t)),
                    self._step(t), self._pct(t), t.line)), danger=True)
        else:
            self.ask("Save its settings?", ["Written by the Stump's own settings.py, as /admin does.",
                                            "Its config.py is kept as config.py.bak. It restarts."] + s["warn"],
                     "Save", lambda: self.run_stump("Saving its settings", lambda t: stump.save_job(
                         a, self.link_for(port), self._step(t), t.line)))

    def draw_form(self):
        d, f = self.d, self.form
        if self.kb:
            return
        a, rows = f["a"], self.form_rows()
        d.text(F16, 16, TOP + 4, "A NEW STUMP" if f["mode"] == "new" else "ITS SETTINGS", EMBER)
        rh, vis = 56, 9
        first = max(0, min(f["sel"] - (vis - 2), len(rows) - vis))
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
            d.text(F20, 26, y + 13, r["label"], EMBER_BRIGHT if sel else TEXT, 300)
            vw = min(d.text_width(F20, val), W - 360)
            d.text(F20, W - 28 - vw, y + 13, val, vc, W - 360)
        if a.get("radio") != "none":
            d.text(F16, 16, 656, "LoRa: 868.8 MHz · 125 kHz · SF8 · CR 4/5 · 22 dBm (the mesh's)",
                   MUTED, W - 32)
        self.hints([("A", "type / choose"), ("←→", "choice"), ("↑↓", "move"), ("B", "back")])

    def open_log(self):
        self.stop_log()
        self.log = SerialLog(self.cur["port"])
        self.log_from = self.screen if self.screen in ("boards", "jobs") else "boards"
        self.screen = "log"

    def stop_log(self):
        if self.log:
            self.log.stop()
            self.log = None

    def on_log(self, act):
        if act == "b":
            self.stop_log()
            self.screen = getattr(self, "log_from", "boards")
        elif act == "a" and self.log:
            self.log.paused = not self.log.paused
        elif act == "x" and self.log:
            self.log.clear()

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
                  "form": "%s  ›  %s" % (self.board_name(), "A new Stump" if self.form and self.form["mode"] == "new"
                                         else "Its settings"), "log": "Serial log  ·  %s  ·  115200"
                  % (self.cur["port"] if self.cur else "")}[self.screen]
        d.text(F20, 16, 52, crumbs, TEXT, W - 32)
        d.fill(0, 86, W, 1, BORDER)

    def board_name(self):
        k = self.known.get(self.cur["port"]) if self.cur else None
        return k["board"]["name"] if k else (self.cur["usb_chip"] if self.cur else "")

    def hints(self, pairs):
        d, x = self.d, 12
        d.fill(0, 682, W, 38, PANEL2)
        for key, label in pairs:
            if key:
                kw = d.text_width(F16, key) + 14
                d.fill_rrect(x, 690, kw, 24, 5, BORDER)
                d.text(F16, x + 7, 693, key, TEXT)
                x += kw + 6
            x += d.text(F16, x, 693, label, MUTED) + 16

    def draw_boards(self):
        d = self.d
        if not self.ports:
            d.text(F24, 24, TOP + 120, "Plug a board into the hub", TEXT)
            for i, s in enumerate(("With a data cable: a Heltec V3, an ESP32-S3 (Freenove CAM)",
                                   "or a classic ESP32. It shows up here by itself.",
                                   "A board with two USB-C ports: either one flashes it; once",
                                   "it's a USB Wi-Fi adapter, use the serial chip's port.")):
                d.text(F16, 24, TOP + 160 + i * 24, s, MUTED, W - 48)
            self.hints([("SELECT+START", "quit")])
            return
        self.draw_here(TOP + 4)
        d.text(F16, 16, TOP + 4, "BOARDS ON THE HUB", EMBER)
        rh = 84
        first = max(0, min(self.sel - 5, len(self.ports) - 6))
        for k, p in enumerate(self.ports[first:first + 6]):
            i = first + k
            y = TOP + 28 + k * rh
            sel = i == self.sel
            if sel:
                d.stroke_rrect(12, y, W - 24, rh - 6, 8, EMBER, PANEL)
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
        self.hints([("A", "choose"), ("X", "identify again"), ("Y", "serial log"), ("↑↓", "move"),
                    ("SELECT+START", "quit")])

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
        first = max(0, min(self.jsel - 6, len(rows) - 7))
        for k, r in enumerate(rows[first:first + 7]):
            i = first + k
            y = TOP + 96 + k * rh
            sel = i == self.jsel
            if sel:
                d.stroke_rrect(12, y, W - 24, rh - 6, 8, EMBER, PANEL)
            b = self.bundle()
            if r["kind"].startswith("stump_"):
                rel = b.release if b else "?"
                title, about, tag, tc = {
                    "stump_new": ("Make a Stump", "Erases it, writes MicroPython and the Stump %s, asks its name, "
                                  "password, Wi-Fi, chain, radio." % rel, "erases", ERROR),
                    "stump_update": ("Update its Stump", "To %s; its settings, identity and card stay." % rel,
                                     "keeps settings", OK),
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
        else:
            y += 18
        d.text(F16, 20, y, "LOG", EMBER)
        n = (676 - (y + 24)) // 20
        for i, s in enumerate(t.tail(n)):
            d.text(F16, 20, y + 24 + i * 20, s, MUTED, W - 40)
        self.hints([("A", "continue"), ("B", "back")] if t.done else [("", "working: leave it plugged in")])

    def draw_log(self):
        d = self.d
        if not self.log:
            return
        lines = self.log.snapshot()
        if self.log.error:
            d.text(F20, 20, TOP + 10, self.log.error, ERROR, W - 40)
        elif not lines:
            d.text(F20, 20, TOP + 10, "Listening… (nothing yet: press the board's RESET to see it boot)", MUTED,
                   W - 40)
        for i, s in enumerate(lines[-27:]):
            d.text(F16, 16, TOP + 10 + i * 21, s, TEXT, W - 32)
        if self.log.paused:
            d.fill_rrect(W - 120, TOP + 6, 104, 26, 6, EMBER)
            d.text(F16, W - 108, TOP + 9, "paused", BG)
        self.hints([("A", "pause" if not self.log.paused else "resume"), ("X", "clear"), ("B", "back")])

    def draw_confirm(self):
        d, c = self.d, self.confirm
        tone = ERROR if c["danger"] else OK
        d.stroke_rrect(50, 170, W - 100, 330, 10, tone, PANEL)
        d.text(F24, 74, 190, c["title"], tone, W - 148)
        y = 236
        for s in c["lines"]:
            for part in wrap(d, F20, s, W - 150):
                d.text(F20, 74, y, part, TEXT, W - 148)
                y += 26
            y += 4
        for i in range(2):
            sel = c["choice"] == i
            bx = 74 + i * 290
            lbl = "No, cancel" if i == 0 else c["yes"]
            if sel:
                d.fill_rrect(bx, 420, 270, 54, 8, EMBER if i == 0 else tone)
            else:
                d.stroke_rrect(bx, 420, 270, 54, 8, BORDER, PANEL2)
            d.text(F24, bx + (270 - d.text_width(F24, lbl)) // 2, 432, lbl, BG if sel else TEXT)
        self.hints([("←→", "choose"), ("A", "accept"), ("B", "cancel")])
