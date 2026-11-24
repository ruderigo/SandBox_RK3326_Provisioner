"""A Stump's announce stamps (SandBox_Stump_On 1.0.0-beta.86), worked out
here, as Team Stump's `provisioner.py --stamp-announces` does: Reticulum
1.6.1 puts a proof of work on announces, and a node can be set to ignore
announces without one. A Stump with "Announce stamps" ticked (/admin ->
Stump settings -> Announcing) lists what it announces in
rns/stamps_wanted.json, each with its stamp material; a stamp is 14 bytes
whose SHA-256 after that material starts with 25 zero bits. A board finds
them slowly; every core of this handheld does it in seconds to minutes,
then they go in rns/stamps.json, which the Stump takes within a minute.
"""

import hashlib
import json
import multiprocessing
import os
import time

from . import stump

COST = 25
STAMP_LEN = 14
CHUNK = 100000


def ok(material, stamp, cost=COST):
    full, rest = cost // 8, cost % 8
    d = hashlib.sha256(material + stamp).digest()
    return len(stamp) == STAMP_LEN and not any(d[:full]) and (not rest or d[full] < (1 << (8 - rest)))


def _search(args):
    """One worker's share: up to `tries` random stamps; the first that meets the cost, or None."""
    material, tries, cost = args
    full, rest = cost // 8, cost % 8
    limit = 1 << (8 - rest) if rest else 256
    zero, base, rnd = bytes(full), hashlib.sha256(material), os.urandom
    for _ in range(tries):
        s = rnd(STAMP_LEN)
        h = base.copy()
        h.update(s)
        d = h.digest()
        if d[:full] == zero and d[full] < limit:
            return s
    return None


def find(material, cost=COST, progress=None, workers=None):
    """A stamp for this material, every core on it. progress(tries so far)."""
    n = workers or max(1, multiprocessing.cpu_count())
    done = 0
    # fork: the workers only hash; the app around them (SDL) is never re-run in them
    pool = multiprocessing.get_context("fork").Pool(n)
    try:
        while True:
            for s in pool.imap_unordered(_search, [(material, CHUNK, cost)] * n):
                done += CHUNK
                if s is not None:
                    return s
            if progress:
                progress(done)
    finally:
        pool.terminate()
        pool.join()


def missing(wanted, have, cost=COST):
    """{dest hex: material} of the destinations it announces without a good stamp."""
    todo = {}
    for h, m in (wanted or {}).items():
        try:
            material = bytes.fromhex(m)
            if not ok(material, bytes.fromhex((have or {}).get(h, "") or ""), cost):
                todo[h] = material
        except (ValueError, TypeError, AttributeError):
            continue
    return todo


def work(wanted, have, step, log, cost=COST):
    """The stamps it misses, added to have (a new dict). (stamps, how many found)."""
    todo, out = missing(wanted, have, cost), dict(have or {})
    t0 = time.time()
    for i, (h, material) in enumerate(sorted(todo.items()), 1):
        label = "Its announce stamps: %d of %d" % (i, len(todo))
        step(label)
        s = find(material, cost, progress=lambda n, label=label: step("%s · %d million tries (about %d on average)"
                                                                     % (label, n // 1000000, (1 << cost) // 1000000)))
        out[h] = s.hex()
        log("stamp %d/%d for %s found (%d s so far)" % (i, len(todo), h[:8], int(time.time() - t0)))
    return out, len(todo)


NOT_YET = ("It doesn't list what it announces yet: in its /admin, Stump settings -> Announcing, tick "
           "\"Announce stamps\", let it announce once (a few minutes), then do this again.")


def _read(repl, name):
    d = stump.asked_json(repl, "import json\ntry:\n d=json.loads(open('rns/%s').read())\nexcept (OSError, ValueError):\n"
                               " d={}\nprint('J'+json.dumps(d if isinstance(d, dict) else {}))\n" % name, "J", 20)
    return d if isinstance(d, dict) else {}


def board_job(open_link, step, log, cost=COST):
    """Works out a CAM's missing announce stamps here and copies them over. (ok, message)."""
    step("Connecting")
    repl = stump.ready_repl(open_link, log)
    try:
        if not stump.has_stump(repl):
            return False, "There's no Stump on this board (no config.py): make one first."
        step("Reading what it announces")
        wanted, have = _read(repl, "stamps_wanted.json"), _read(repl, "stamps.json")
        step("Restarting it")
        stump.restart(repl)                       # it runs while this works
    finally:
        repl.link.close()
    if not wanted:
        return False, NOT_YET
    if not missing(wanted, have, cost):
        return True, "Its %d announce stamp(s) are all there." % len(wanted)
    t0 = time.time()
    stamps, n = work(wanted, have, step, log, cost)
    step("Copying them over")
    repl = stump.ready_repl(open_link, log)
    try:
        data = json.dumps(stamps).encode()
        repl.run("import os\ntry:\n os.mkdir('rns')\nexcept OSError:\n pass\n")
        stump.upload(repl, [("rns/stamps.json", data, hashlib.sha256(data).hexdigest())])
        step("Restarting it")
        stump.restart(repl)
    finally:
        repl.link.close()
    return True, ("%d announce stamp(s) worked out here in %d s and copied over: it announces stamped from now on."
                  % (n, int(time.time() - t0)))
