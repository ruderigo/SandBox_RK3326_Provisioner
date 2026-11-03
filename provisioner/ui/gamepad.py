"""The handheld's buttons, read from evdev and turned into actions:
a b x y l r start select up down left right, and quit on SELECT+START.

Which button is which differs between RK3326 handhelds and their systems
(the same evdev code is Y on one and L1 on another), so for each gamepad:

1. EmulationStation's own mapping (es_input.cfg), when it has the pad: ES's
   "a" is our A, its D-pad our D-pad, and so on. ES stores SDL's joystick
   indices; they're turned back into evdev codes the way SDL numbers them
   (buttons from BTN_JOYSTICK up, then the codes below it; axes in order,
   hats apart).
2. Else a table for the pads known to differ (the RG351's OSH pad, the
   MagicX XU10 / XU Mini M), else the common one (ArkOS, dArkOS, AmberELEC,
   ROCKNIX on the OGA, OGS, R36S/R36MAX and clones).

Anything ES leaves out comes from the table, so SELECT+START always quits.
Only gamepads are read here; a keyboard's keys come through SDL.
"""

import fcntl
import glob
import os
import struct
import xml.etree.ElementTree as ET

EV_KEY, EV_ABS = 1, 3
ABS_HAT0X, ABS_HAT0Y, ABS_HAT3Y = 0x10, 0x11, 0x17
BTN_MISC, BTN_JOYSTICK, BTN_SOUTH, BTN_THUMBR, KEY_MAX, ABS_MAX = 0x100, 0x120, 0x130, 0x13E, 0x2FF, 0x3F
BTN_DPAD_UP = 0x220
EVENT = struct.Struct("llHHi")

COMMON = {305: "a", 304: "b", 307: "x", 308: "y", 310: "l", 311: "r",
          314: "select", 315: "start", 704: "select", 705: "start", 706: "select", 707: "start",
          544: "up", 545: "down", 546: "left", 547: "right"}
# Pads whose codes differ (names as the kernel gives them).
XU = dict(COMMON)
XU.update({304: "a", 305: "b", 308: "x", 307: "y"})             # A/B and X/Y the other way round
TABLES = {
    "OpenSimHardware OSH PB Controller":                    # RG351P/M/V: an internal USB pad, D-pad on a hat
        {305: "a", 304: "b", 307: "x", 306: "y", 308: "l", 309: "r", 311: "select", 310: "start"},
    "XU10 Gamepad": XU,
    "XU Mini M Gamepad": XU,
}
ES_NAMES = {"a": "a", "b": "b", "x": "x", "y": "y", "start": "start", "select": "select",
            "up": "up", "down": "down", "left": "left", "right": "right",
            "leftshoulder": "l", "pageup": "l", "rightshoulder": "r", "pagedown": "r"}
HAT_BITS = {1: "up", 2: "right", 4: "down", 8: "left"}
ES_INPUT = ["~/.emulationstation/es_input.cfg", "/storage/.config/emulationstation/es_input.cfg",
            "/storage/.emulationstation/es_input.cfg", "/etc/emulationstation/es_input.cfg",
            "/home/ark/.emulationstation/es_input.cfg"]


def _ioc_read(nr, size):
    return (2 << 30) | (size << 16) | (ord("E") << 8) | nr


def _bits(fd, ev, nbits):
    buf = bytearray((nbits + 7) // 8)
    try:
        fcntl.ioctl(fd, _ioc_read(0x20 + ev, len(buf)), buf, True)
    except OSError:
        return set()
    return set(i for i in range(nbits) if buf[i // 8] >> (i % 8) & 1)


def _name(fd):
    buf = bytearray(256)
    try:
        fcntl.ioctl(fd, _ioc_read(0x06, len(buf)), buf, True)
    except OSError:
        return ""
    return buf.split(b"\0", 1)[0].decode("utf-8", "replace")


def _absinfo(fd, code):
    """(min, max) of an axis."""
    buf = bytearray(24)
    try:
        fcntl.ioctl(fd, _ioc_read(0x40 + code, 24), buf, True)
    except OSError:
        return -32768, 32767
    return struct.unpack_from("<ii", buf, 4)


def sdl_layout(keys, axes):
    """SDL's numbering: (buttons [code by index], axes [code by index], hats [(x, y) codes by index])."""
    buttons = [c for c in range(BTN_JOYSTICK, KEY_MAX) if c in keys] + [c for c in range(0, BTN_JOYSTICK) if c in keys]
    plain = [c for c in range(0, ABS_MAX) if c in axes and not ABS_HAT0X <= c <= ABS_HAT3Y]
    hats = [(c, c + 1) for c in range(ABS_HAT0X, ABS_HAT3Y, 2) if c in axes or c + 1 in axes]
    return buttons, plain, hats


def es_configs(paths=None):
    """[(path, deviceName, [(name, type, id, value)])] of the joystick configs ES has."""
    out, seen = [], set()
    for p in paths if paths is not None else ES_INPUT:
        p = os.path.expanduser(p)
        try:
            real = os.path.realpath(p)
            if real in seen or not os.path.isfile(p):
                continue
            seen.add(real)
            root = ET.parse(p).getroot()
        except (OSError, ET.ParseError):
            continue
        for ic in root.iter("inputConfig"):
            if ic.get("type") != "joystick":
                continue
            ins = []
            for i in ic.iter("input"):
                try:
                    ins.append((i.get("name", ""), i.get("type", ""), int(i.get("id", "-1")), int(i.get("value", "0"))))
                except ValueError:
                    pass
            out.append((p, ic.get("deviceName", ""), ins))
    return out


def es_mapping(inputs, keys, axes):
    """From ES's inputs to ({code: action}, {abs code: (neg action, pos action)})."""
    buttons, plain, hats = sdl_layout(keys, axes)
    kmap, amap = {}, {}
    for name, typ, idx, value in inputs:
        act = ES_NAMES.get(name)
        if not act:
            continue
        if typ == "button" and 0 <= idx < len(buttons):
            kmap[buttons[idx]] = act
        elif typ == "hat" and 0 <= idx < len(hats) and value in HAT_BITS:
            hx, hy = hats[idx]
            code, neg = (hy, value == 1) if value in (1, 4) else (hx, value == 8)
            cur = list(amap.get(code, (None, None)))
            cur[0 if neg else 1] = act
            amap[code] = tuple(cur)
        elif typ == "axis" and 0 <= idx < len(plain) and value:
            code = plain[idx]
            cur = list(amap.get(code, (None, None)))
            cur[0 if value < 0 else 1] = act
            amap[code] = tuple(cur)
    return kmap, amap


def merge(table, kmap, amap):
    """ES's mapping over the table: an action ES maps drops the table's codes for it."""
    have = set(kmap.values()) | set(a for pair in amap.values() for a in pair if a)
    out = {c: a for c, a in table.items() if a not in have}
    out.update(kmap)
    return out


class Pad:
    """One gamepad: its fd, name and mapping."""

    def __init__(self, fd, name, keys, axes, configs):
        self.fd, self.name = fd, name
        table = TABLES.get(name, COMMON)
        self.source = "the %s table" % ("pad's" if name in TABLES else "common")
        mine = [c for c in configs if c[1] == name]
        if not mine and len(configs) == 1 and not configs[0][1]:
            mine = configs
        kmap, amap = es_mapping(mine[0][2], keys, axes) if mine else ({}, {})
        if kmap or amap:
            self.source = "EmulationStation (%s)" % mine[0][0]
        self.keys = merge(table, kmap, amap)
        hat = {ABS_HAT0X: ("left", "right"), ABS_HAT0Y: ("up", "down")}
        self.axes = dict((c, p) for c, p in hat.items() if c in axes and not any(a in set(kmap.values())
                                                                                for a in p))
        self.axes.update(amap)
        self.range = dict((c, _absinfo(fd, c)) for c in self.axes if not ABS_HAT0X <= c <= ABS_HAT3Y) if fd >= 0 else {}
        self.held = {}                  # axis -> the action it's held at


class Gamepad:
    def __init__(self, paths=None, es_paths=None):
        self.pads = []
        configs = es_configs(es_paths)
        for p in paths if paths is not None else sorted(glob.glob("/dev/input/event*")):
            try:
                fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            keys, axes = _bits(fd, EV_KEY, KEY_MAX + 1), _bits(fd, EV_ABS, ABS_MAX + 1)
            pad_like = (any(BTN_SOUTH <= k <= BTN_THUMBR for k in keys) or any(BTN_DPAD_UP <= k < BTN_DPAD_UP + 4
                        for k in keys) or ABS_HAT0X in axes)
            if paths is None and not pad_like:
                os.close(fd)
                continue
            self.pads.append(Pad(fd, _name(fd), keys, axes, configs))
        self.select = self.start = False

    @property
    def fds(self):
        return [p.fd for p in self.pads]

    def describe(self):
        """One line per pad: its name and where its buttons come from."""
        return ["%s: buttons from %s" % (p.name or "a gamepad", p.source) for p in self.pads] or ["no gamepad found"]

    def actions(self):
        out = []
        for pad in self.pads:
            while True:
                try:
                    data = os.read(pad.fd, EVENT.size * 16)
                except (BlockingIOError, OSError):
                    break
                if not data:
                    break
                for k in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    out.extend(self.decode(*EVENT.unpack_from(data, k)[2:], pad=pad))
        return out

    def decode(self, etype, code, value, pad=None):
        """Actions from one input event."""
        if pad is None:                 # no device: the common table and a hat
            pad = self._plain = getattr(self, "_plain", None) or Pad(-1, "", set(), {ABS_HAT0X, ABS_HAT0Y}, [])
        if etype == EV_KEY and code in pad.keys:
            act = pad.keys[code]
            if act == "select":
                self.select = value != 0
            if act == "start":
                self.start = value != 0
            if self.select and self.start:
                return ["quit"]
            if value == 1 or (value == 2 and act in ("up", "down", "left", "right")):
                return [act]
        elif etype == EV_ABS and code in pad.axes:
            neg, pos = pad.axes[code]
            if code in pad.range:               # a stick: past half way
                lo, hi = pad.range[code]
                mid, half = (lo + hi) / 2.0, max(1, (hi - lo) / 4.0)
                act = neg if value < mid - half else pos if value > mid + half else None
            else:                               # a hat
                act = neg if value < 0 else pos if value > 0 else None
            was = pad.held.get(code)
            pad.held[code] = act
            if act and act != was:
                return [act]
        return []

    def close(self):
        for p in self.pads:
            if p.fd >= 0:
                os.close(p.fd)
