"""pyserial's ch340://<bus>-<address>: a CH340 driven through libusb (see
__init__.py), for esptool and the Stump's serial link. What arrives is read
in the background into a buffer; DTR and RTS are the chip's modem lines."""

import threading
import time

from serial.serialutil import PortNotOpenError, SerialBase, SerialException, Timeout

from . import CH340, LibusbError, parse


class Serial(SerialBase):
    BAUDRATES = (9600, 19200, 38400, 57600, 74880, 115200, 230400, 460800, 921600, 1500000, 2000000)

    def __init__(self, *args, **kwargs):
        self.chip, self._buf, self._cv, self._stop, self._error = None, bytearray(), threading.Condition(), None, None
        super().__init__(*args, **kwargs)

    def open(self):
        if self.is_open:
            raise SerialException("Port is already open.")
        if self._port is None:
            raise SerialException("Port must be configured before it can be used.")
        try:
            bus, address = parse(self._port)
            self.chip = CH340(bus, address, self._baudrate, dtr=self._dtr_state, rts=self._rts_state)
        except (LibusbError, ValueError) as e:
            raise SerialException("could not open port %s: %s" % (self._port, e))
        self._buf, self._error = bytearray(), None
        self._stop = threading.Event()
        self.is_open = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        stop, chip = self._stop, self.chip
        while not stop.is_set():
            try:
                b = chip.read(256, 50)
            except (LibusbError, AttributeError) as e:
                with self._cv:
                    self._error = e
                    self._cv.notify_all()
                return
            if b:
                with self._cv:
                    self._buf += b
                    self._cv.notify_all()

    def close(self):
        if self.is_open:
            self.is_open = False
            self._stop.set()
            time.sleep(0.07)                     # the reader's transfer ends within its 50 ms
            try:
                self.chip.close()
            finally:
                self.chip = None

    def _reconfigure_port(self):
        if self.chip:
            try:
                self.chip.set_baud(self._baudrate)
            except (LibusbError, ValueError) as e:
                raise SerialException("couldn't set %s baud: %s" % (self._baudrate, e))

    def _update_dtr_state(self):
        if self.chip:
            self._lines(dtr=self._dtr_state)

    def _update_rts_state(self):
        if self.chip:
            self._lines(rts=self._rts_state)

    def _lines(self, **kw):
        try:
            self.chip.set_lines(**kw)
        except LibusbError as e:
            raise SerialException(str(e))

    @property
    def in_waiting(self):
        if not self.is_open:
            raise PortNotOpenError()
        with self._cv:
            return len(self._buf)

    def read(self, size=1):
        if not self.is_open:
            raise PortNotOpenError()
        t = Timeout(self._timeout)
        with self._cv:
            while len(self._buf) < size:
                if self._error is not None:
                    if self._buf:
                        break
                    raise SerialException("the board went away: %s" % self._error)
                if t.expired():
                    break
                left = t.time_left()
                self._cv.wait(0.05 if left is None else max(0.0, min(left, 0.05)))
            out = bytes(self._buf[:size])
            del self._buf[:size]
        return out

    def write(self, data):
        if not self.is_open:
            raise PortNotOpenError()
        data = bytes(data)
        try:
            return self.chip.write(data, int(1000 * (self._write_timeout or 5)))
        except LibusbError as e:
            raise SerialException("writing: %s" % e)

    def reset_input_buffer(self):
        with self._cv:
            self._buf = bytearray()

    def reset_output_buffer(self):
        pass

    def flush(self):
        pass

    @property
    def cts(self):
        return False

    @property
    def dsr(self):
        return False

    @property
    def ri(self):
        return False

    @property
    def cd(self):
        return False
