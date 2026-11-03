"""The serial log: what a board prints, read at 115200 in the background."""

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor"))


class SerialLog:
    def __init__(self, port, baud=115200, keep=400):
        self.port, self.baud, self.keep = port, baud, keep
        self.lines, self.error, self.paused = [], "", False
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _add(self, line):
        with self._lock:
            self.lines.append(line)
            del self.lines[:-self.keep]

    def _run(self):
        try:
            import serial
            s = serial.Serial(self.port, self.baud, timeout=0.2)
        except Exception as e:
            self.error = "Can't open %s: %s" % (self.port, e)
            return
        buf = b""
        try:
            while not self._stop.is_set():
                try:
                    chunk = s.read(256)
                except Exception as e:
                    self.error = "The board went away: %s" % e
                    return
                if not chunk or self.paused:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._add(line.decode("utf-8", "replace").rstrip("\r"))
        finally:
            s.close()

    def snapshot(self):
        with self._lock:
            return list(self.lines)

    def clear(self):
        with self._lock:
            self.lines = []

    def stop(self):
        self._stop.set()
        self._t.join(timeout=1)
