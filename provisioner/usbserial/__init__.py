"""CH340 boards with no kernel driver: the chip driven from here, through
libusb (libusb-1.0, there on ArkOS and dArkOS), as Linux's ch341.c drives it.

None of the RK3326 systems has ch341, the CH340's driver (a Freenove
ESP32-WROVER carries one), and a kernel module only loads into the kernel
it was built for. The CH340 needs little: a few vendor requests set its
speed and its DTR/RTS lines (an ESP32's EN and IO0), and data goes through
two bulk endpoints. So a CH340 that no driver took is offered as the port
ch340://<bus>-<address>, which pyserial opens with protocol_ch340.Serial
(this package is registered as one of its URL handlers): esptool and the
Stump's serial link use it like any port.

    register()          pyserial knows ch340://
    ports()             [{port, usb, bus, address}] of CH340s no driver took
    Libusb()            the library (ctypes), or LibusbError
    divisor(baud)       the CH340's prescaler/divisor register value
"""

import ctypes
import ctypes.util
import os

VID_PIDS = ("1a86:7523", "1a86:5523")            # CH340, CH341 (serial mode)
EP_OUT, EP_IN = 0x02, 0x82
REQ_READ_VERSION, REQ_WRITE_REG, REQ_SERIAL_INIT, REQ_MODEM_CTRL = 0x5F, 0x9A, 0xA1, 0xA4
REG_PRESCALER, REG_DIVISOR, REG_LCR, REG_LCR2 = 0x12, 0x13, 0x18, 0x25
LCR_8N1 = 0x80 | 0x40 | 0x03                     # RX on, TX on, 8 bits, no parity, 1 stop
MODEM_DTR, MODEM_RTS = 0x20, 0x40
CLKRATE = 48000000
OUT, IN = 0x40, 0xC0                             # vendor request, to the device / from it

ERRORS = {-1: "input/output error", -3: "no permission (install.sh adds the rule; plug it in again)",
          -4: "the board went away", -5: "not found", -6: "busy (another program has it)", -7: "timed out",
          -9: "pipe error", -12: "not supported"}


class LibusbError(OSError):
    def __init__(self, code, what=""):
        self.code = code
        super().__init__("%s%s" % (what + ": " if what else "", ERRORS.get(code, "libusb error %d" % code)))


def _clk_div(ps, fact):
    return 1 << (12 - 3 * ps - fact)


def divisor(baud):
    """The value for the prescaler/divisor registers (ch341.c's
    ch341_get_divisor), bit 7 set (no waiting for a full packet)."""
    min_bps = -(-CLKRATE // (_clk_div(0, 0) * 256))
    max_bps = CLKRATE // (_clk_div(3, 0) * 2)
    speed = max(min_bps, min(max_bps, int(baud)))
    fact = 1
    for ps in (3, 2, 1, 0):
        if speed > CLKRATE // (_clk_div(ps, 1) * 512):
            break
    else:
        raise ValueError("unsupported speed %s" % baud)
    clk = _clk_div(ps, fact)
    div = CLKRATE // (clk * speed)
    if div < 9 or div > 255:
        div //= 2
        clk *= 2
        fact = 0
    if div < 2:
        raise ValueError("unsupported speed %s" % baud)
    if 16 * CLKRATE // (clk * div) - 16 * speed >= 16 * speed - 16 * CLKRATE // (clk * (div + 1)):
        div += 1
    if fact == 1 and div % 2 == 0:
        div //= 2
        fact = 0
    return ((0x100 - div) << 8 | fact << 2 | ps) | 0x80


# -- libusb through ctypes -----------------------------------------------------------
class _Descriptor(ctypes.Structure):
    _fields_ = [("bLength", ctypes.c_uint8), ("bDescriptorType", ctypes.c_uint8), ("bcdUSB", ctypes.c_uint16),
                ("bDeviceClass", ctypes.c_uint8), ("bDeviceSubClass", ctypes.c_uint8),
                ("bDeviceProtocol", ctypes.c_uint8), ("bMaxPacketSize0", ctypes.c_uint8),
                ("idVendor", ctypes.c_uint16), ("idProduct", ctypes.c_uint16), ("bcdDevice", ctypes.c_uint16),
                ("iManufacturer", ctypes.c_uint8), ("iProduct", ctypes.c_uint8), ("iSerialNumber", ctypes.c_uint8),
                ("bNumConfigurations", ctypes.c_uint8)]


class Libusb:
    """The few libusb-1.0 calls a CH340 needs."""

    def __init__(self, path=None):
        path = path or os.environ.get("PROVISIONER_LIBUSB") or ctypes.util.find_library("usb-1.0") or "libusb-1.0.so.0"
        try:
            self.lib = lib = ctypes.CDLL(path)
        except OSError as e:
            raise LibusbError(-12, "libusb-1.0 isn't on this system (%s)" % e)
        P, I, U8, U16, U32 = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint
        sig = {"libusb_init": (I, [ctypes.POINTER(P)]),
               "libusb_get_device_list": (ctypes.c_ssize_t, [P, ctypes.POINTER(ctypes.POINTER(P))]),
               "libusb_free_device_list": (None, [ctypes.POINTER(P), I]),
               "libusb_get_device_descriptor": (I, [P, ctypes.POINTER(_Descriptor)]),
               "libusb_get_bus_number": (U8, [P]), "libusb_get_device_address": (U8, [P]),
               "libusb_open": (I, [P, ctypes.POINTER(P)]), "libusb_close": (None, [P]),
               "libusb_kernel_driver_active": (I, [P, I]), "libusb_detach_kernel_driver": (I, [P, I]),
               "libusb_claim_interface": (I, [P, I]), "libusb_release_interface": (I, [P, I]),
               "libusb_control_transfer": (I, [P, U8, U8, U16, U16, ctypes.c_char_p, U16, U32]),
               "libusb_bulk_transfer": (I, [P, ctypes.c_ubyte, ctypes.c_char_p, I, ctypes.POINTER(I), U32])}
        for name, (res, args) in sig.items():
            f = getattr(lib, name)
            f.restype, f.argtypes = res, args
        self.ctx = P()
        r = lib.libusb_init(ctypes.byref(self.ctx))
        if r < 0:
            raise LibusbError(r, "libusb_init")

    def find(self, bus, address):
        """The device at bus/address, opened: a handle, or LibusbError."""
        lst = ctypes.POINTER(ctypes.c_void_p)()
        n = self.lib.libusb_get_device_list(self.ctx, ctypes.byref(lst))
        if n < 0:
            raise LibusbError(n, "listing USB devices")
        try:
            for i in range(n):
                dev = lst[i]
                if self.lib.libusb_get_bus_number(dev) == bus and self.lib.libusb_get_device_address(dev) == address:
                    d = _Descriptor()
                    self.lib.libusb_get_device_descriptor(dev, ctypes.byref(d))
                    if "%04x:%04x" % (d.idVendor, d.idProduct) not in VID_PIDS:
                        raise LibusbError(-5, "USB %d-%d isn't a CH340" % (bus, address))
                    h = ctypes.c_void_p()
                    r = self.lib.libusb_open(dev, ctypes.byref(h))
                    if r < 0:
                        raise LibusbError(r, "opening USB %d-%d" % (bus, address))
                    return h
        finally:
            self.lib.libusb_free_device_list(lst, 1)
        raise LibusbError(-4, "no USB device %d-%d (unplugged?)" % (bus, address))

    def claim(self, h):
        if self.lib.libusb_kernel_driver_active(h, 0) == 1:
            self.lib.libusb_detach_kernel_driver(h, 0)
        r = self.lib.libusb_claim_interface(h, 0)
        if r < 0:
            raise LibusbError(r, "claiming the CH340")

    def release(self, h):
        self.lib.libusb_release_interface(h, 0)
        self.lib.libusb_close(h)

    def control(self, h, rtype, req, value, index, length=0, timeout=1000):
        buf = ctypes.create_string_buffer(max(length, 1))
        r = self.lib.libusb_control_transfer(h, rtype, req, value & 0xFFFF, index & 0xFFFF, buf, length, timeout)
        if r < 0:
            raise LibusbError(r, "CH340 request 0x%02x" % req)
        return buf.raw[:r]

    def bulk(self, h, ep, data=None, size=0, timeout=100):
        """Out: bytes written. In: bytes read (b"" on a time-out)."""
        n = ctypes.c_int(0)
        if data is not None:
            buf = ctypes.create_string_buffer(bytes(data), len(data))
            r = self.lib.libusb_bulk_transfer(h, ep, buf, len(data), ctypes.byref(n), timeout)
        else:
            buf = ctypes.create_string_buffer(size)
            r = self.lib.libusb_bulk_transfer(h, ep, buf, size, ctypes.byref(n), timeout)
        if r < 0 and r != -7:
            raise LibusbError(r)
        return n.value if data is not None else buf.raw[:n.value]


_LIB = []


def libusb():
    """The one Libusb of this program (LibusbError if there's none)."""
    if not _LIB:
        _LIB.append(Libusb())
    return _LIB[0]


def available():
    try:
        libusb()
        return True
    except (LibusbError, AttributeError):
        return False


class CH340:
    """One CH340, opened: its line set to 8N1 at baud, DTR and RTS as given."""

    def __init__(self, bus, address, baud=115200, dtr=False, rts=False, lib=None):
        self.lib = lib or libusb()
        self.h = self.lib.find(bus, address)
        try:
            self.lib.claim(self.h)
            v = self.lib.control(self.h, IN, REQ_READ_VERSION, 0, 0, 2)
            self.version = v[0] if v else 0
            self.lib.control(self.h, OUT, REQ_SERIAL_INIT, 0, 0)
            self.dtr, self.rts = dtr, rts
            self.set_baud(baud)
            self.set_lines(dtr, rts)
        except Exception:
            self.lib.release(self.h)
            raise

    def set_baud(self, baud):
        self.lib.control(self.h, OUT, REQ_WRITE_REG, REG_DIVISOR << 8 | REG_PRESCALER, divisor(baud))
        if self.version >= 0x30:          # older chips keep the line settings elsewhere (8N1 by default)
            self.lib.control(self.h, OUT, REQ_WRITE_REG, REG_LCR2 << 8 | REG_LCR, LCR_8N1)

    def set_lines(self, dtr=None, rts=None):
        """The modem lines (active low on the wire: the chip takes them inverted)."""
        self.dtr = self.dtr if dtr is None else bool(dtr)
        self.rts = self.rts if rts is None else bool(rts)
        bits = (MODEM_DTR if self.dtr else 0) | (MODEM_RTS if self.rts else 0)
        self.lib.control(self.h, OUT, REQ_MODEM_CTRL, ~bits & 0xFFFF, 0)

    def write(self, data, timeout=2000):
        done = 0
        while done < len(data):
            n = self.lib.bulk(self.h, EP_OUT, data[done:], timeout=timeout)
            if n <= 0:
                raise LibusbError(-7, "writing to the CH340")
            done += n
        return done

    def read(self, size=256, timeout=50):
        return self.lib.bulk(self.h, EP_IN, size=size, timeout=timeout)

    def close(self):
        if self.h:
            try:
                self.lib.release(self.h)
            finally:
                self.h = None


def parse(url):
    """ch340://3-5 -> (3, 5)."""
    rest = url.split("://", 1)[-1].strip("/")
    try:
        bus, address = rest.split("-", 1)
        return int(bus), int(address)
    except ValueError:
        raise ValueError("not a ch340://<bus>-<address> port: %s" % url)


def ports(sys_usb="/sys/bus/usb/devices", check=available):
    """[{port, usb, bus, address}] of the CH340s plugged in that no driver
    took (on a system with ch341 they're /dev/ttyUSB* instead), when libusb
    is there to drive them."""
    out = []
    try:
        names = sorted(os.listdir(sys_usb))
    except OSError:
        return out
    for n in names:
        if ":" in n:
            continue
        d = os.path.join(sys_usb, n)

        def rd(f):
            try:
                with open(os.path.join(d, f)) as fh:
                    return fh.read().strip()
            except OSError:
                return ""
        usb = "%s:%s" % (rd("idVendor").lower(), rd("idProduct").lower())
        if usb not in VID_PIDS:
            continue
        ifaces = [os.path.join(d, i) for i in os.listdir(d) if i.startswith(n + ":")] if os.path.isdir(d) else []
        if any(os.path.lexists(os.path.join(i, "driver")) for i in ifaces):
            continue
        try:
            bus, address = int(rd("busnum")), int(rd("devnum"))
        except ValueError:
            continue
        out.append({"port": "ch340://%d-%d" % (bus, address), "usb": usb, "bus": bus, "address": address})
    return out if out and check() else []


def register():
    """pyserial opens ch340:// with this package's protocol_ch340."""
    import serial
    if __name__ not in serial.protocol_handler_packages:
        serial.protocol_handler_packages.append(__name__)
