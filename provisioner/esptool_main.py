"""esptool, as the Provisioner runs it (`python -m provisioner.esptool_main`,
vendor/ on the path): pyserial knows ch340:// (a CH340 driven through libusb,
provisioner/usbserial), and such a port is reset into the bootloader by its
DTR/RTS lines one after the other (esptool's ClassicReset): its Unix reset
sets both at once with an ioctl, which only a kernel tty has."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor"))

from provisioner import usbserial  # noqa: E402

usbserial.register()

import esptool  # noqa: E402
from esptool import loader, reset  # noqa: E402

_sequence = loader.ESPLoader._construct_reset_strategy_sequence


def _reset_sequence(self, mode):
    if str(getattr(self._port, "port", "") or "").startswith("ch340://") and mode != "usb_reset":
        d = loader.DEFAULT_RESET_DELAY
        return (reset.ClassicReset(self._port, d), reset.ClassicReset(self._port, d + 0.5))
    return _sequence(self, mode)


loader.ESPLoader._construct_reset_strategy_sequence = _reset_sequence

if __name__ == "__main__":
    esptool._main()
