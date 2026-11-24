"""python3 -m provisioner linktest [PORT] [--one-at-a-time]

What a board's serial line loses, shown as it is: for when its answers
"didn't come through whole". The board prints numbered lines, at once and
then in small pieces, and its Stump image's list; every line that didn't
arrive as sent is printed, with what came instead. Nothing on the board is
changed (it is restarted at the end). Paste the output to the team.
"""

import os
import re
import sys

LINES = 100
COUNT = ("import sys\nfor i in range(%d):\n print('%%03d:abcdefghijklmnopqrstuvwxyz0123456789' %% i)\n" % LINES)
IMAGE = ("import json\ntry:\n import stump_image as s\n print('IMG'+json.dumps({'release':s.RELEASE,"
         "'partitions':s.PARTITIONS,'frozen':s.FROZEN}))\nexcept ImportError:\n print('IMGnull')\n")


def counted(out, sealed):
    """(whole, [what came instead]) of the numbered lines in what came."""
    from . import stump
    lines = stump.whole_lines(out) if sealed else out.replace("\r", "").split("\n")
    want = ["%03d:abcdefghijklmnopqrstuvwxyz0123456789" % i for i in range(LINES)]
    got = set(lines)
    bad = [l for l in out.replace("\r", "").split("\n")
           if l and re.sub(r"~~[cf][0-9a-f]{8}~\d+$", "", l) not in want]
    return sum(1 for w in want if w in got), bad


def main(argv, out=print):
    from . import boards, stump
    if "--one-at-a-time" in argv:
        os.environ["PROVISIONER_CH340_ONE_AT_A_TIME"] = "1"
    args = [a for a in argv if not a.startswith("--")]
    ports = [p["port"] for p in boards.list_ports()]
    port = args[0] if args else (ports[0] if ports else None)
    if not port:
        out("No USB serial board found.")
        return 2
    out("port %s (of %s); CH340 read %s" % (port, ", ".join(ports) or "none listed",
                                             "one at a time" if os.environ.get("PROVISIONER_CH340_ONE_AT_A_TIME")
                                             else "without a gap"))
    try:
        repl = stump.ready_repl(lambda: stump.SerialLink(port), lambda s: out("  . %s" % s))
    except stump.StumpError as e:
        out("can't talk to it: %s" % e)
        return 1
    try:
        chip = getattr(getattr(repl.link, "s", None), "chip", None)
        if port.startswith("ch340://"):
            out("its reader: %s" % ("32 transfers waiting" if getattr(chip, "streaming", False) else "one transfer at a time"))
        for name, code, sealed in (("1. 100 lines at once", COUNT, False),
                                   ("2. 100 lines, 64 bytes every 8 ms", stump.paced_print(64, 8) + COUNT, True),
                                   ("3. 100 lines, 16 bytes every 40 ms", stump.paced_print(16, 40) + COUNT, True)):
            try:
                got = repl.run(code, 60)
            except stump.StumpError as e:
                out("%s: stopped: %s" % (name, e))
                continue
            whole, bad = counted(got, sealed)
            out("%s: %d of %d whole, %d bytes came" % (name, whole, LINES, len(got)))
            for l in bad[:12]:
                out("     came instead: %r" % l)
            if len(bad) > 12:
                out("     ... and %d more" % (len(bad) - 12))
        for name, code in (("4. its image's list, 64 bytes every 8 ms", stump.paced_print(64, 8) + IMAGE),
                           ("5. its image's list, 16 bytes every 40 ms", stump.paced_print(16, 40) + IMAGE)):
            try:
                got = repl.run(code, 60)
            except stump.StumpError as e:
                out("%s: stopped: %s" % (name, e))
                continue
            out("%s: %s, %d bytes came:" % (name, "whole" if stump.whole_lines(got) else "NOT whole", len(got)))
            out("     %r" % got)
    finally:
        try:
            stump.restart(repl)
        except Exception:
            pass
        repl.link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
