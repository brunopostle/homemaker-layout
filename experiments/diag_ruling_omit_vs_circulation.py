"""Does the objective rank "a room omitted" above "no circulation", everywhere?

The owner's ruling (2026-10-03, DESIGN.md §39.84):

    An omitted room should be closer to a working building than a building
    with no circulation.

and, on how to check it: a generic tool that works with all programmes and
sizes -- not a probe built for one artefact. This is that tool. For every
artefact it builds the two buildings the ruling compares, the same way, and
scores both:

  omit      one room instance removed: the connected cells of one code on one
            storey are absorbed by their neighbouring room. Tried for EVERY
            instance of every room code, and the CHEAPEST omission is the one
            that counts -- the ruling has to hold for the room the objective
            minds least.
  no-circ   every circulation cell (`C`) absorbed by its neighbouring room,
            repeated until none is left (a corridor between two corridor cells
            is absorbed once its neighbours are), stair shaft included.

"Absorbed by its neighbouring room" means retyped to the most common
programme-room type among its graph neighbours, so both buildings keep their
area and their outline and differ only in what the ruling is about.

The margin is reported in FAIL-LINES, log2(omit score / no-circ score): the
ruling holds where it is positive. Where a score is zero (§39.72's x0 floors),
fail counts decide instead and the margin is printed as `n/a`.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_ruling_omit_vs_circulation.py
    ... --corpus 'coldstart-07b2058+orth-*.dom' --programme maple-court
"""

from __future__ import annotations

import argparse
import collections
import copy
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, geometry, programme  # noqa: E402
from homemaker_layout.fitness import Fitness, load_config  # noqa: E402

PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
CORPUS = "coldstart-*+orth-500000-s*.dom"


def _graphs(root, door_width):
    geometry.clear_cache()
    return [geometry.leaf_graph(lvl, door_width) for lvl in dom.levels(root)]


def _absorber(leaf, G, rooms) -> "str | None":
    """The programme-room type most common among `leaf`'s neighbours."""
    if leaf not in G:
        return None
    seen = collections.Counter(n.type for n in G.neighbors(leaf)
                               if n.type in rooms and n.type != leaf.type)
    return seen.most_common(1)[0][0] if seen else None


def instances(root, door_width, rooms):
    """Every room instance as (level index, code, [leaf ids]): the connected
    components of same-code cells on one storey."""
    out = []
    for li, G in enumerate(_graphs(root, door_width)):
        lvl = dom.levels(root)[li]
        cells = [l for l in lvl.leaves() if l.type in rooms]
        done = set()
        for leaf in cells:
            if leaf.id in done:
                continue
            comp, todo = [], [leaf]
            while todo:
                n = todo.pop()
                if n.id in done:
                    continue
                done.add(n.id)
                comp.append(n.id)
                if n in G:
                    todo += [m for m in G.neighbors(n) if m.type == leaf.type]
            out.append((li, leaf.type, comp))
    return out


def _by_id(root, li, ids):
    lvl = dom.levels(root)[li]
    want = set(ids)
    return [l for l in lvl.leaves() if l.id in want]


def omit(root, li, ids, door_width, rooms):
    child = copy.deepcopy(root)
    dom.link(child)
    G = _graphs(child, door_width)[li]
    cells = _by_id(child, li, ids)
    code = cells[0].type
    # absorbed by a neighbour of the instance that is not the same code
    seen = collections.Counter()
    for c in cells:
        if c in G:
            seen.update(n.type for n in G.neighbors(c)
                        if n.type in rooms and n.type != code)
    if not seen:
        return None
    to = seen.most_common(1)[0][0]
    for c in cells:
        c.type = to
    dom.link(child)
    return child


def no_circulation(root, door_width, rooms):
    child = copy.deepcopy(root)
    dom.link(child)
    while True:
        changed = False
        for li, G in enumerate(_graphs(child, door_width)):
            for leaf in dom.levels(child)[li].leaves():
                if leaf.type == "C":
                    to = _absorber(leaf, G, rooms)
                    if to:
                        leaf.type, changed = to, True
        if not changed:
            break
    dom.link(child)
    left = sum(1 for lv in dom.levels(child) for l in lv.leaves() if l.type == "C")
    return child, left


def margin(a, b) -> str:
    (sa, fa), (sb, fb) = a, b
    if sa > 0 and sb > 0:
        return f"{math.log2(sa / sb):+7.1f}"
    return "    n/a"


def holds(a, b) -> bool:
    (sa, fa), (sb, fb) = a, b
    if sa > 0 or sb > 0:
        return sa > sb
    return len(fa) < len(fb)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--corpus", default=CORPUS,
                    help=f"artefact glob per programme directory (default {CORPUS!r})")
    ap.add_argument("--self-test", action="store_true",
                    help="negative control: inflate a missing room's cascade by 80 "
                         "lines, which MUST make the tool report VIOLATED")
    args = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    if args.self_test:
        from homemaker_layout import graph as graph_mod
        real = graph_mod.check_space_counts

        def inflated(*a, **k):
            out = real(*a, **k)
            fails = out[0] if isinstance(out, tuple) else out
            extra = [f"self-test {i} for {f}" for f in fails
                     if f.startswith("missing required space")
                     and not f.endswith("(critical)") for i in range(80)]
            if isinstance(out, tuple):
                return (list(out[0]) + extra, *out[1:])
            return list(out) + extra
        graph_mod.check_space_counts = inflated

    verdict = []
    for name in args.programme or PROGRAMMES:
        prog = REPO / "examples" / name
        conf, cost = load_config(str(prog))
        fit = Fitness(conf, cost)
        dw = fit.conf("door_width") or 1.2
        reqs = programme.load_programme_dir(str(prog))
        rooms = {c for c in reqs if not dom.is_generic(c)}
        size = sum((r.count or 1) for c, r in reqs.items() if c in rooms)
        paths = sorted(prog.glob(args.corpus))
        print(f"\n=== {name}: {len(rooms)} room codes, {size} room instances "
              f"required, {len(paths)} artefact(s)")
        print(f"{'artefact':44} {'base':>9} {'no-circ':>9} {'C left':>6} "
              f"{'cheapest omit':>22} {'margin':>7}  ruling")

        def score(r):
            geometry.clear_cache()
            s, f = Fitness(conf, cost).score_with_fails(copy.deepcopy(r))
            geometry.clear_cache()
            return s, f

        for p in paths:
            root = dom.load(str(p))
            dom.link(root)
            base = score(root)
            nc_root, left = no_circulation(root, dw, rooms)
            nc = score(nc_root)
            best = None
            for li, code, ids in instances(root, dw, rooms):
                child = omit(root, li, ids, dw, rooms)
                if child is None:
                    continue
                s = score(child)
                if not any(f.startswith("missing required space") for f in s[1]):
                    continue   # absorbing it left the count met: not an omission
                if best is None or holds(s, best[0]) is False:
                    best = (s, f"{li}/{code}")
            if best is None:
                print(f"{p.name:44} {base[0]:9.3g} {nc[0]:9.3g} {left:6d} "
                      f"{'(no omittable room)':>22}")
                continue
            ok = holds(best[0], nc)
            verdict.append((name, p.name, ok))
            print(f"{p.name:44} {base[0]:9.3g} {nc[0]:9.3g} {left:6d} "
                  f"{best[1]:>12} {best[0][0]:9.3g} {margin(best[0], nc)}  "
                  f"{'holds' if ok else 'VIOLATED'}")

    bad = [v for v in verdict if not v[2]]
    print(f"\nruling holds on {len(verdict) - len(bad)} of {len(verdict)} artefacts"
          + (": VIOLATED on " + ", ".join(f"{a}/{b}" for a, b, _ in bad) if bad else ""))
    if args.self_test:   # the control must FIRE: a clean report here is the failure
        print("self-test: control " + ("fired" if bad else "DID NOT FIRE -- the tool cannot see a violation"))
        return 0 if bad else 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
