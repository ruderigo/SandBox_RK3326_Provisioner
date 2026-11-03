"""FireFly's on-screen keyboard (as in the Stump cockpit), for the
Provisioner's forms: real upper and lower case, symbols, accents.

    D-pad move · A type the key · B delete · X space · Y shift (one letter)
    L/R page (abc, symbols, accents) · START OK · SELECT cancel

A USB keyboard types straight into it (Enter OK, Esc cancel, Backspace)."""

from .sdl import F16, F20, F24, F30B, W

PAGES = [
    ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.?"],
    ["!@#$%&*()-", "_=+/\\:;\"<>", "[]{}~`|^€£", "°±×÷…«»¿¡·"],
    ["àâäçéèêëîï", "ôöùûüÿœæñß", "ÀÂÇÉÈÊÎÔÙÛ", "✓✗→←↑↓♥☺★—"],
]
PAGE_NAMES = ["abc", "sym", "àé"]
SPECIALS = ["⇧", "PAGE", "SPACE", "⌫", "OK"]


def upper(c):
    if "a" <= c <= "z":
        return c.upper()
    o = ord(c)
    if 0xE0 <= o <= 0xFE and o != 0xF7:
        return chr(o - 32)
    return {"œ": "Œ", "ÿ": "Ÿ"}.get(c, c)


class Keyboard:
    def __init__(self, title, text="", max_bytes=64, secret=False, hint=""):
        self.title, self.text, self.max_bytes, self.secret, self.hint = title, text, max_bytes, secret, hint
        self.page = self.row = self.col = 0
        self.row = 1
        self.shift = False

    def _type(self, s):
        for ch in s:
            if len((self.text + ch).encode()) > self.max_bytes:
                return
            self.text += ch

    def handle(self, act):
        """'ok', 'cancel' or None (still typing)."""
        if isinstance(act, tuple) and act[0] == "text":
            self._type(act[1])
            return None
        if act in ("up", "down"):
            self.row = (self.row + (1 if act == "down" else -1)) % 5
            self.col %= self._len(self.row)
        elif act in ("left", "right"):
            n = self._len(self.row)
            self.col = (self.col + (1 if act == "right" else -1)) % n
        elif act in ("b", "backspace"):
            self.text = self.text[:-1]
        elif act == "x":
            self._type(" ")
        elif act == "y":
            self.shift = not self.shift
        elif act in ("l", "r"):
            self.page = (self.page + (1 if act == "r" else -1)) % len(PAGES)
            self.col %= self._len(self.row)
        elif act in ("start", "enter"):
            return "ok"
        elif act in ("select", "escape"):
            return "cancel"
        elif act == "a":
            return self.press()
        return None

    def _len(self, r):
        return len(PAGES[self.page][r]) if r < 4 else len(SPECIALS)

    def press(self):
        if self.row < 4:
            c = PAGES[self.page][self.row][self.col]
            self._type(upper(c) if self.shift else c)
            self.shift = False
        elif self.col == 0:
            self.shift = not self.shift
        elif self.col == 1:
            self.page = (self.page + 1) % len(PAGES)
        elif self.col == 2:
            self._type(" ")
        elif self.col == 3:
            self.text = self.text[:-1]
        else:
            return "ok"
        return None

    def draw(self, d, th):
        d.clear(th["BG"])
        d.text(F30B, 14, 8, self.title, th["EMBER"], W - 28)
        ax, ay, aw, ah = 10, 52, W - 20, 150
        d.stroke_rrect(ax, ay, aw, ah, 8, th["BORDER"], th["PANEL"])
        per = (aw - 20) // d.text_width(F24, "m")
        shown = self.text + "▏"
        lines = [shown[i:i + per] for i in range(0, len(shown), per)] or [""]
        for i, s in enumerate(lines[-5:]):
            d.text(F24, ax + 10, ay + 8 + i * 28, s, th["TEXT"], aw - 20)
        d.text(F16, 14, ay + ah + 6, "%s%s" % (PAGE_NAMES[self.page], "  ⇧" if self.shift else ""), th["MUTED"])
        meter = "%d/%d bytes%s" % (len(self.text.encode()), self.max_bytes, " · shown as you type" if self.secret else "")
        d.text(F16, ax + aw - 8 - d.text_width(F16, meter), ay + ah + 6, meter, th["MUTED"])
        if self.hint:
            d.text(F16, 14, ay + ah + 28, self.hint, th["MUTED"], W - 28)
        top, kh = 262, 78
        for r in range(5):
            keys = list(PAGES[self.page][r]) if r < 4 else SPECIALS
            n = len(keys)
            kw = (W - 20 - (n - 1) * 6) // n
            for c, k in enumerate(keys):
                x, y = 10 + c * (kw + 6), top + r * (kh + 6)
                sel = (r == self.row and c == self.col)
                label = upper(k) if (r < 4 and self.shift) else k
                if sel:
                    d.fill_rrect(x, y, kw, kh, 8, th["EMBER"])
                else:
                    d.stroke_rrect(x, y, kw, kh, 8, th["BORDER"], th["PANEL2"])
                f = F24 if r < 4 else F20
                lw = d.text_width(f, label)
                d.text(f, x + (kw - lw) // 2, y + (kh - d.line(f)) // 2, label, th["BG"] if sel else th["TEXT"])
        hints = [("A", "type"), ("B", "delete"), ("X", "space"), ("Y", "shift"), ("L/R", "page"), ("START", "OK"),
                 ("SELECT", "cancel")]
        x = 10
        d.fill(0, 682, W, 38, th["PANEL2"])
        for k, lbl in hints:
            kw = d.text_width(F16, k) + 12
            d.fill_rrect(x, 690, kw, 24, 5, th["BORDER"])
            d.text(F16, x + 6, 693, k, th["TEXT"])
            x += kw + 4
            x += d.text(F16, x, 693, lbl, th["MUTED"]) + 10
