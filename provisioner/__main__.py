"""RK3326 Provisioner.

    python3 -m provisioner                    the app (the handheld's screen, or a window)
    python3 -m provisioner list               the boards on USB, identified
    python3 -m provisioner flash PORT ID      flash a catalogue image (ID from `catalog`)
    python3 -m provisioner catalog            what it can flash
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def version():
    try:
        with open(os.path.join(HERE, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return "dev"


def cmd_list():
    from . import boards, flasher
    ports = boards.list_ports()
    if not ports:
        print("No USB serial board found.")
    for p in ports:
        users = boards.port_users(p["port"])
        if users:
            print("%s  %s  in use by %s: not touched" % (p["port"], p["usb_chip"], ", ".join(u[1] for u in users)))
            continue
        ok, out = flasher.probe(p["port"])
        if not ok:
            print("%s  %s  %s" % (p["port"], p["usb_chip"], flasher.explain(out)))
            continue
        info = boards.parse_probe(out)
        b = boards.identify(info["chip"], p["usb"])
        print("%s  %s  %s, %g MB flash, MAC %s" % (p["port"], b["name"], info["chip_text"], info["flash_mb"], info["mac"]))
    return 0


def cmd_catalog():
    from . import catalog
    for e in catalog.load():
        print("%-28s %-8s %-8s %s" % (e["id"], e["status"], e.get("mode", ""), e["title"]))
    return 0


def cmd_flash(port, fid):
    from . import boards, catalog, flasher
    e = next((x for x in catalog.load() if x["id"] == fid), None)
    if not e or e["status"] != "ready":
        print("No ready image %r (see: python3 -m provisioner catalog)" % fid)
        return 2
    why = catalog.check(e)
    if why:
        print(why)
        return 2
    ok, out = flasher.probe(port)
    if not ok:
        print(flasher.explain(out))
        return 1
    info = boards.parse_probe(out)
    usb = next((p["usb"] for p in boards.list_ports() if p["port"] == port), "")
    board = dict(boards.identify(info["chip"], usb), flash_mb=info["flash_mb"])
    if board["id"] not in e["boards"]:
        print("%s is for %s; this is a %s" % (e["title"], ", ".join(e["boards"]), board["name"]))
        return 2
    if e["mode"] == "full" and input("%s erases the whole flash. Type yes: " % e["title"]).strip() != "yes":
        return 1
    ok, msg = flasher.flash(port, e, board, on_step=lambda s: print("==", s),
                            on_progress=lambda p: print("\r%3d %%" % p, end="", flush=True))
    print("\n" + msg)
    return 0 if ok else 1


def cmd_ui(headless=False, frames=0, script=None, shots=None):
    from .ui.app import App
    from .ui.gamepad import Gamepad
    from .ui.sdl import Display, write_png
    d = Display(os.path.join(HERE, "assets", "cockpit_font.bin"), headless=headless)
    app = App(d, version=version())
    pad = Gamepad([]) if headless else Gamepad()
    n = 0
    try:
        while app.running:
            app.scan()
            for act in pad.actions() + d.events():
                app.handle(act)
            if script and n < len(script):
                for act in script[n]:
                    app.handle(act)
            app.draw()
            if shots:
                w, h, px = d.snapshot()
                write_png(shots % n, w, h, px)
            n += 1
            if frames and n >= frames:
                break
            time.sleep(1 / 30.0)
    finally:
        app.stop_log()
        pad.close()
        d.close()
    return 0


def main(argv):
    if argv[:1] == ["--version"]:
        print(version())
        return 0
    if argv[:1] == ["list"]:
        return cmd_list()
    if argv[:1] == ["catalog"]:
        return cmd_catalog()
    if argv[:1] == ["flash"] and len(argv) == 3:
        return cmd_flash(argv[1], argv[2])
    if argv[:1] == ["--smoke"]:                     # draws a few frames with no screen (install check, CI)
        return cmd_ui(headless=True, frames=5)
    if not argv:
        return cmd_ui()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
