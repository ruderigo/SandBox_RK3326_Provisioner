"""Boards on the hub: the serial ports, what USB chip they are behind, and
(once esptool has spoken to the chip) which board it is.

A board is told apart by its USB id *and* its chip: a CP2102 sits on a
Heltec V3 (ESP32-S3) and on many classic ESP32 dev boards alike, so the USB
id alone only says "a USB-serial chip"; the chip esptool reports settles it.
"""

import glob
import os
import re

# USB ids of the serial chips ESP32 boards use.
USB_SERIAL = {
    "303a:1001": "ESP32-S3/C3 native USB",
    "303a:0002": "ESP32-S2/S3 native USB",
    "10c4:ea60": "CP210x USB-serial",
    "1a86:55d3": "CH343 USB-serial",
    "1a86:7523": "CH340 USB-serial",
    "1a86:55d4": "CH9102 USB-serial",
    "0403:6001": "FTDI USB-serial",
    "0403:6015": "FTDI USB-serial",
    "067b:2303": "PL2303 USB-serial",
}

# The Linux driver each chip's serial port needs. ROCKNIX's RK3326 kernel
# has none of these but cdc_acm; ArkOS, dArkOS and AmberELEC have all but
# ch341 (the CH340's).
DRIVERS = {"10c4:ea60": "cp210x", "1a86:7523": "ch341", "1a86:5523": "ch341",
           "0403:6001": "ftdi_sio", "0403:6015": "ftdi_sio", "0403:6010": "ftdi_sio", "067b:2303": "pl2303",
           "1a86:55d3": "cdc_acm", "1a86:55d4": "cdc_acm"}
NAMES = {"1a86:5523": "CH341 USB-serial", "0403:6010": "FTDI USB-serial"}

# Boards, by (chip, USB id). The first match wins; None matches any.
BOARDS = [
    {"id": "heltec_v3", "name": "Heltec V3 (LoRa)", "chip": "esp32s3", "usb": ("10c4:ea60",)},
    {"id": "esp32s3", "name": "ESP32-S3 (Freenove CAM or similar)", "chip": "esp32s3", "usb": None},
    {"id": "esp32", "name": "ESP32 (a WROVER is a Stump board)", "chip": "esp32", "usb": None},
]


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def list_ports(sys_tty="/sys/class/tty", dev_dir="/dev", sys_usb="/sys/bus/usb/devices"):
    """[{port, usb, usb_chip, product, serial, native}] of the USB serial
    ports now (ttyUSB*, ttyACM*), and ch340://bus-address for a CH340 no
    driver took (sys_usb None: not looked for). Linux reads sysfs; elsewhere pyserial."""
    if not os.path.isdir(sys_tty):
        return _list_ports_pyserial()
    out = []
    for name in sorted(os.listdir(sys_tty)):
        if not (name.startswith("ttyUSB") or name.startswith("ttyACM")):
            continue
        dev = os.path.realpath(os.path.join(sys_tty, name, "device"))
        usb, product, serial = "", "", ""
        d = dev
        for _ in range(4):                 # the tty's interface, then up to its USB device
            vid, pid = _read(os.path.join(d, "idVendor")), _read(os.path.join(d, "idProduct"))
            if vid and pid:
                usb = "%s:%s" % (vid.lower(), pid.lower())
                product = _read(os.path.join(d, "product"))
                serial = _read(os.path.join(d, "serial"))
                break
            d = os.path.dirname(d)
        out.append(_port(os.path.join(dev_dir, name), usb, product, serial))
    return out + (ch340_ports(sys_usb) if sys_usb else [])


def ch340_ports(sys_usb="/sys/bus/usb/devices"):
    """CH340s no driver took, driven from here through libusb (usbserial)."""
    from . import usbserial
    return [dict(_port(c["port"], c["usb"], "", ""), userspace=True) for c in usbserial.ports(sys_usb)]


def _list_ports_pyserial():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        if p.vid is None:
            continue
        out.append(_port(p.device, "%04x:%04x" % (p.vid, p.pid), p.product or "", p.serial_number or ""))
    return out


def _port(port, usb, product, serial):
    return {"port": port, "usb": usb, "usb_chip": USB_SERIAL.get(usb, product or "USB serial"),
            "product": product, "serial": serial, "native": usb.startswith("303a:")}


def parse_probe(text):
    """What esptool's flash_id said: {chip, chip_text, flash_mb, mac, psram}."""
    t = text or ""
    m = re.search(r"Chip is ([^\n(]+?)\s*(\(|\n|$)", t)
    chip_text = m.group(1).strip() if m else ""
    # The family ("ESP32", "ESP32-S3"), not the part ("ESP32-D0WD-V3" is a classic ESP32).
    m2 = re.search(r"Detecting chip type\.*\s*(ESP32[-\w]*)", t)
    fam = (m2.group(1) if m2 else chip_text).upper()
    chip = ""
    for f in ("ESP32-S3", "ESP32-S2", "ESP32-C3", "ESP32-C6", "ESP32-C2", "ESP32-H2", "ESP32-P4", "ESP32-C5"):
        if fam.startswith(f):
            chip = f.lower().replace("-", "")
            break
    else:
        if fam.startswith("ESP32"):
            chip = "esp32"
    name = chip_text or fam
    m = re.search(r"Detected flash size:\s*(\d+)\s*(KB|MB)", t, re.I)
    flash_mb = (int(m.group(1)) / (1024.0 if m.group(2).upper() == "KB" else 1.0)) if m else 0
    m = re.search(r"^MAC:\s*([0-9a-fA-F:]{17})", t, re.M)
    mac = m.group(1).lower() if m else ""
    m = re.search(r"PSRAM\s*(\d+)\s*MB", t, re.I)
    psram = int(m.group(1)) if m else 0
    return {"chip": chip, "chip_text": chip_text or name, "flash_mb": flash_mb, "mac": mac, "psram_mb": psram}


def identify(chip, usb):
    """The board for a chip behind a USB id, or a generic one."""
    for b in BOARDS:
        if b["chip"] == chip and (b["usb"] is None or usb in b["usb"]):
            return dict(b)
    return {"id": chip or "unknown", "name": (chip.upper() if chip else "Unknown board"), "chip": chip, "usb": None}


def port_users(port, proc="/proc"):
    """[(pid, name)] of the programs that have this serial port open (the
    Stump with its Heltec, a serial monitor): touching the port would reset
    the board under them."""
    real = os.path.realpath(port)
    users = []
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return users
    for pid in pids:
        fd_dir = os.path.join(proc, pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.path.realpath(os.path.join(fd_dir, fd)) == real:
                    cmd = _read(os.path.join(proc, pid, "cmdline")).replace("\0", " ").split()
                    name = next((os.path.basename(c) for c in cmd if c.endswith(".py")),
                                os.path.basename(cmd[0]) if cmd else pid)
                    users.append((int(pid), name))
                    break
            except OSError:
                continue
    return [u for u in users if u[0] != os.getpid()]


def by_id_links(by_id="/dev/serial/by-id"):
    """{real tty: by-id name} (stable names, shown in the log)."""
    out = {}
    for p in glob.glob(os.path.join(by_id, "*")):
        out[os.path.realpath(p)] = os.path.basename(p)
    return out


USERSPACE = ("1a86:7523", "1a86:5523")        # CH340/CH341: libusb drives them when the kernel can't


def _userspace_ok():
    from . import usbserial
    return usbserial.available()


def unbound(sys_usb="/sys/bus/usb/devices"):
    """[{usb, usb_chip, driver}] of USB-serial chips plugged in that no
    driver took (no serial port for them): this system lacks their driver."""
    out = []
    try:
        names = sorted(os.listdir(sys_usb))
    except OSError:
        return out
    for n in names:
        if ":" in n:                    # an interface, not a device
            continue
        d = os.path.join(sys_usb, n)
        usb = "%s:%s" % (_read(os.path.join(d, "idVendor")).lower(), _read(os.path.join(d, "idProduct")).lower())
        if usb not in DRIVERS:
            continue
        ifaces = [os.path.join(d, i) for i in os.listdir(d) if i.startswith(n + ":")] if os.path.isdir(d) else []
        if usb in USERSPACE and _userspace_ok():
            continue                    # driven from here (usbserial): a port, not a missing driver
        if ifaces and not any(os.path.lexists(os.path.join(i, "driver")) for i in ifaces):
            out.append({"usb": usb, "usb_chip": USB_SERIAL.get(usb) or NAMES.get(usb, "USB-serial"),
                        "driver": DRIVERS[usb]})
    return out
