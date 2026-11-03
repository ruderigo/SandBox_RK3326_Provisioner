#!/usr/bin/env python3
"""CPython standing in for MicroPython's Unix port, for the pretend board
(stump_fixtures/board_sim.py runs `<this> -c RUNNER <file>` with the board's
folder as the working directory).

What the board's code needs that CPython doesn't have, or has differently:
`machine` (a watchdog, a reset), `ujson`, MicroPython's version and .mpy
numbers (FAKE_MPY, default 6.3), and "/" being the board's own folder (the
Stump's radio.py saves to /radio.json). The Stump's modules come from the
board's folder (config.py), then their sources (the bundle has them
compiled, which CPython can't load)."""
import builtins
import json
import os
import sys
import traceback
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.getcwd()
code = open(sys.argv[-1], encoding="utf-8").read()

machine = types.ModuleType("machine")


class WDT:
    def __init__(self, timeout=0, id=0):
        pass

    def feed(self):
        pass


machine.WDT = WDT
machine.reset = lambda: None
sys.modules["machine"] = machine
sys.modules["ujson"] = json
major, minor = (os.environ.get("FAKE_MPY") or "6.3").split(".")
sys.implementation.version = (1, 28, 0)
sys.implementation._mpy = int(major) | (int(minor) << 8)

# "/" is the board's folder.
_open, _stat, _remove, _rename, _mkdir, _listdir = open, os.stat, os.remove, os.rename, os.mkdir, os.listdir


def board(p):
    return os.path.join(ROOT, p.lstrip("/")) if isinstance(p, str) and p.startswith("/") else p


builtins.open = lambda p, *a, **k: _open(board(p), *a, **k)
os.stat = lambda p, *a, **k: _stat(board(p), *a, **k)
os.remove = lambda p: _remove(board(p))
os.rename = lambda a, b: _rename(board(a), board(b))
os.mkdir = lambda p, *a: _mkdir(board(p), *a)
os.listdir = lambda p=".": _listdir(board(p))
sys.path[:0] = [ROOT, os.path.join(HERE, "stump_fixtures")]
try:
    exec(compile(code, "<stdin>", "exec"), {"__name__": "__main__"})
except BaseException:
    traceback.print_exc()
