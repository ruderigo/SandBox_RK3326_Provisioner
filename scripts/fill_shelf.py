#!/usr/bin/env python3
"""Fills the shelf the Provisioner carries (firmware/shelf/): the newest
Official and Sandbox release of each product, checked as on the handheld
(provisioner/shelf.py: GitHub's SHA-256 of every file, SHA256SUMS, then
the files read for what they are). The Provisioner itself isn't put on its
own shelf (it is that copy).

    python3 scripts/fill_shelf.py                  every product, both channels
    python3 scripts/fill_shelf.py stump sandbox    one product, one channel
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["PROVISIONER_SHELF"] = os.path.join(ROOT, "firmware", "shelf")
from provisioner import shelf  # noqa: E402


def main(argv):
    products = [argv[0]] if argv else [p for p in shelf.ORDER if p != "provisioner"]
    channels = [argv[1]] if len(argv) > 1 else list(shelf.CHANNELS)
    for p in products:
        for ch in channels:
            rel = shelf.online(p, ch)
            d = os.path.join(os.environ["PROVISIONER_SHELF"], p, ch)
            if not rel:
                print("%s %s: no release" % (p, ch))
                shutil.rmtree(d, ignore_errors=True)
                continue
            have = shelf.local(p, ch)
            if have and have[0]["tag"] == rel["tag"]:
                print("%s %s: %s (already)" % (p, ch, rel["tag"]))
                continue
            c = shelf.fetch(p, ch, rel, log=lambda s: print("   " + s))
            print("%s %s: %s, %d file(s)" % (p, ch, c["tag"], len(c["files"])))


if __name__ == "__main__":
    main(sys.argv[1:])
