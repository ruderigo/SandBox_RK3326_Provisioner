"""The handheld's buttons, read from evdev as the Stump cockpit reads them
(the R36MAX's codes, tested on the device), turned into actions:
a b x y l r start select up down left right, and quit on SELECT+START.

Only gamepad codes are read here (BTN_*, the D-pad, the hat); a keyboard's
keys come through SDL, so nothing is seen twice.
"""

import glob
import os
import struct

EV_KEY, EV_ABS = 1, 3
ABS_HAT0X, ABS_HAT0Y = 16, 17
CODES = {305: "a", 304: "b", 307: "x", 308: "y", 310: "l", 311: "r",
         315: "start", 705: "start", 707: "start", 314: "select", 704: "select", 706: "select",
         544: "up", 545: "down", 546: "left", 547: "right"}
EVENT = struct.Struct("llHHi")


class Gamepad:
    def __init__(self, paths=None):
        self.fds = []
        for p in paths if paths is not None else sorted(glob.glob("/dev/input/event*")):
            try:
                self.fds.append(os.open(p, os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                pass
        self.select = self.start = False

    def actions(self):
        out = []
        for fd in self.fds:
            while True:
                try:
                    data = os.read(fd, EVENT.size * 16)
                except (BlockingIOError, OSError):
                    break
                if not data:
                    break
                for k in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    out.extend(self.decode(*EVENT.unpack_from(data, k)[2:]))
        return out

    def decode(self, etype, code, value):
        """Actions from one input event."""
        if etype == EV_KEY and code in CODES:
            act = CODES[code]
            if act == "select":
                self.select = value != 0
            if act == "start":
                self.start = value != 0
            if self.select and self.start:
                return ["quit"]
            if value == 1 or (value == 2 and act in ("up", "down", "left", "right")):
                return [act]
        elif etype == EV_ABS and code in (ABS_HAT0X, ABS_HAT0Y) and value:
            if code == ABS_HAT0X:
                return ["left" if value < 0 else "right"]
            return ["up" if value < 0 else "down"]
        return []

    def close(self):
        for fd in self.fds:
            os.close(fd)
