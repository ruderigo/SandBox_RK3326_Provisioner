"""The serial log: what a board prints, read at 115200 in the background,
each line with the time it arrived. It keeps reading while the screen is
paused (the screen holds a copy), and exports to a text file."""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor"))


def export_dir():
    """Where exported logs go: a folder on the card's games partition when
    there is one (reachable from a computer by card reader, and over SSH),
    else the home folder."""
    for roms in ("/roms", "/storage/roms", "/roms2"):
        if os.path.isdir(roms) and os.access(roms, os.W_OK):
            return os.path.join(roms, "provisioner-logs")
    return os.path.join(os.path.expanduser("~"), "provisioner-logs")


class SerialLog:
    def __init__(self, port, baud=115200, keep=5000, open_serial=None):
        self.port, self.baud, self.keep = port, baud, keep
        self.lines, self.error, self.paused = [], "", False     # lines: [(time, text)]
        self.started = time.time()
        self._open = open_serial
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _add(self, line):
        with self._lock:
            self.lines.append((time.time(), line))
            del self.lines[:-self.keep]

    def _run(self):
        try:
            if self._open:
                s = self._open()
            else:
                import serial
                from . import usbserial
                usbserial.register()             # ch340://: a CH340 with no kernel driver
                s = serial.serial_for_url(self.port, self.baud, timeout=0.2)
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
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._add(line.decode("utf-8", "replace").rstrip("\r"))
        finally:
            s.close()

    def snapshot(self):
        """The lines' text."""
        with self._lock:
            return [t for _, t in self.lines]

    def timed(self):
        """[(time, text)]."""
        with self._lock:
            return list(self.lines)

    def clear(self):
        with self._lock:
            self.lines = []

    def export(self, lines=None, folder=None, now=None):
        """Writes lines ([(time, text)], default: all of them) to a new text
        file, each with its time. Returns the file's path."""
        lines = self.timed() if lines is None else lines
        folder = folder or export_dir()
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now or time.time()))
        name = "serial-%s-%s.txt" % (os.path.basename(self.port) or "port", stamp)
        path = os.path.join(folder, name)
        k = 2
        while os.path.exists(path):
            path = os.path.join(folder, name[:-4] + "-%d.txt" % k)
            k += 1
        with open(path, "w", encoding="utf-8") as f:
            f.write("# %s at %d baud, from %s; %d line(s)\n" % (
                self.port, self.baud, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started)), len(lines)))
            for t, text in lines:
                f.write("%s.%03d  %s\n" % (time.strftime("%H:%M:%S", time.localtime(t)), int(t * 1000) % 1000, text))
        return path

    def stop(self):
        self._stop.set()
        self._t.join(timeout=1)
