"""`homemaker-py-8b2u.2`: does a design survive v1 -> v2 -> memory, and if its
SCORE does not, what is the scorer reading that the cells do not contain?

DESIGN.md §39.94. Format v2 keeps a design's cuts as lines in the frame, and
drops v1's `rotation` and its upper-storey copies of inherited ratios as
carrying no information. The cells agree. The scores at first did not, on half
the corpus, and each mode below isolates one reason -- none of them a property
of v2, all of them things the objective reads that are not geometry:

  --cells        every artefact through `dom.dumps(version=2)` and back: same
                 cells, and a second dump byte-identical (the format's own test)
  --scores       the same round trip, scored before and after, strict and then
                 with the two scorer behaviours below neutralised
  --rotation     turn the corner labelling of leaves, which moves no wall:
                 `C` leaves against every other leaf
  --noise        the committed artefacts scored with `boundary_pair_overlap`
                 as it is (`> 0`) and with a 1 nm floor: how many scores rest on
                 two walls that merely touch end to end
  --dead-fields  upper-storey nodes whose cut is inherited still store a ratio
                 of their own; `merge_divided` can undivide the node below and
                 bring that stale ratio back to life

`--self-test` is the negative control for --cells: one `at` moved by 1e-4 must
be reported as a different cell.

SINCE §39.95 the first two are fixed, so `--rotation` and `--noise` are
regression checks that should report nothing moved, and `--scores` moves only
on the three files `--dead-fields` names. The numbers in §39.94 are what these
modes printed BEFORE; `tests/test_scorer_reads_geometry_only.py` carries the old
rules as negative controls, which is how to see them fire again.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u2_roundtrip.py --scores
"""

from __future__ import annotations

import argparse
import collections
import copy
import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, dom_v2, geometry as g  # noqa: E402
from homemaker_layout.fitness import Fitness, load_config  # noqa: E402

PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
NOISE_FLOOR = 1e-9        # metres: an overlap below this is two walls touching


def _frame_diag():
    spec = importlib.util.spec_from_file_location(
        "_rect_frame", REPO / "experiments" / "diag_8b2u_rect_frame.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def corpus() -> "list[tuple[Path, Path]]":
    """(artefact, programme directory) for every tracked orthogonal design."""
    out = [(p, REPO / "examples" / name) for name in PROGRAMMES
           for p in sorted((REPO / "examples" / name).glob(
               "coldstart-*+orth-500000-s*.dom"))]
    ph = REPO / "examples" / "programme-house"
    for d in ("e4r", "e4r-tiers"):
        out += [(p, ph) for p in sorted(
            (REPO / "experiments" / "results" / d).glob("e4r-arm*.dom"))]
    return out


def round_trip(root, mutate=None):
    """`root` through a v2 document and back; `mutate(doc)` may edit it."""
    doc = yaml.safe_load(dom.dumps(root, version=2))
    if mutate:
        mutate(doc)
    return dom_v2.from_document(doc)


def cells(root, rf):
    return [(li, lf.type, rf.dedupe([g.coordinate(lf, i) for i in range(4)]))
            for li, lvl in enumerate(dom.levels(root)) for lf in lvl.leaves()]


def same_cells(a, b, rf) -> "tuple[int, int]":
    """(matched, unmatched) cells of `a` in `b`, ignoring how leaves are named."""
    rest, ok, bad = list(b), 0, 0
    for li, ty, poly in a:
        hit = next((x for x in rest if x[0] == li and x[1] == ty
                    and rf.same_polygon(x[2], poly)), None)
        if hit is None:
            bad += 1
        else:
            rest.remove(hit)
            ok += 1
    return ok, bad + len(rest)


def score(root, prog) -> "tuple[float, tuple]":
    conf, cost = load_config(prog)
    s, fails = Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
    g.clear_cache()
    return s, fails


class floor_overlap:
    """Context: `boundary_pair_overlap` returns 0 below `NOISE_FLOOR`."""

    def __init__(self):
        self.tiny = 0

    def __enter__(self):
        self._orig = g.boundary_pair_overlap

        def patched(contributors, a, b):
            w = self._orig(contributors, a, b)
            if 0 < w <= NOISE_FLOOR:
                self.tiny += 1
                return 0.0
            return w

        g.boundary_pair_overlap = patched
        return self

    def __exit__(self, *exc):
        g.boundary_pair_overlap = self._orig


def sync_dead_fields(root) -> int:
    """Overwrite every inherited upper node's own ratio and rotation with the
    ones it inherits; returns how many were stale."""
    stale = 0
    for lvl in dom.levels(root)[1:]:
        stack = [lvl]
        while stack:
            n = stack.pop()
            if not n.divided:
                continue
            if n.below is not None and n.below.divided:
                if abs(n.division[0] - n.below.division[0]) > 1e-9 \
                        or n.rotation != n.below.rotation:
                    stale += 1
                n.division, n.rotation = list(n.below.division), n.below.rotation
            stack += [n.left, n.right]
    g.clear_cache()
    return stale


def differs(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) > tol * max(abs(a), 1e-300)


# --------------------------------------------------------------------------- #
def mode_cells(self_test: bool) -> int:
    rf, tot = _frame_diag(), collections.Counter()

    def nudge(doc):
        def first_cut(t):
            if "at" in t:
                t["at"] += 1e-4
                return True
            return any(first_cut(t[k]) for k in ("low", "high") if k in t and "cell" not in t[k])
        first_cut(doc["storeys"][0]["tree"])

    for p, _ in corpus():
        a = dom.load(str(p))
        b = round_trip(a, nudge if self_test else None)
        ok, bad = same_cells(cells(a, rf), cells(b, rf), rf)
        tot["files"] += 1
        tot["cells identical"] += ok
        tot["cells DIFFERENT"] += bad
        tot["second dump identical"] += dom.dumps(b, version=2) == dom.dumps(a, version=2)
    print(dict(tot))
    if self_test:
        fired = tot["cells DIFFERENT"] > 0
        print("self-test: control " + ("fired" if fired else "DID NOT FIRE"))
        return 0 if fired else 1
    return 0 if not tot["cells DIFFERENT"] and tot["second dump identical"] == tot["files"] else 1


def mode_scores() -> int:
    tot = collections.Counter()
    for p, prog in corpus():
        a = dom.load(str(p))
        b = round_trip(a)
        tot["files"] += 1
        tot["strict: score moved"] += differs(score(a, prog)[0], score(b, prog)[0])
        with floor_overlap():
            sa, fa = score(a, prog)
            sb, fb = score(b, prog)
            tot["noise floored: score moved"] += differs(sa, sb)
            synced = copy.deepcopy(a)
            dom.link(synced)
            sync_dead_fields(synced)
            sc, fc = score(synced, prog)
            moved = differs(sc, sb)
            tot["noise floored + dead fields synced: score moved"] += moved
            tot["... and fail count moved"] += len(fc) != len(fb)
            if moved:
                print(f"  {p.relative_to(REPO)}: {sc:.6g} -> {sb:.6g}")
    for k, v in tot.items():
        print(f"{k:52} {v}")
    return 0 if not tot["noise floored + dead fields synced: score moved"] else 1


def turn_leaves(base, group: str, k: int):
    """A copy of `base` with the corner numbering of its `C` leaves (group
    "C") or of every other leaf ("other") turned `k` places. Only leaves whose
    rotation no geometry reads are turned -- nothing below them, and no storey
    above cutting across them -- so not one wall moves."""
    lvls = dom.levels(base)

    def free(leaf, li):
        if leaf.below is not None:
            return False
        for up in lvls[li + 1:]:
            n = up.by_id(leaf.id)
            if n is None:
                break
            if n.divided:
                return False
        return True

    pick = [[free(lf, li) for lf in lvl.leaves()] for li, lvl in enumerate(lvls)]
    t = copy.deepcopy(base)
    dom.link(t)
    for li, lvl in enumerate(dom.levels(t)):
        for lf, ok in zip(lvl.leaves(), pick[li]):
            if ok and ((lf.type == "C") == (group == "C")):
                lf.rotation = (lf.rotation + k) % 4
    g.clear_cache()
    return t


def mode_rotation() -> int:
    tot = collections.Counter()
    worst = 1.0
    for p, prog in corpus():
        base = dom.load(str(p))
        s0, _ = score(base, prog)
        for group in ("C", "other"):
            for k in (1, 2, 3):
                s, _ = score(turn_leaves(base, group, k), prog)
                tot[f"{group}: trials"] += 1
                tot[f"{group}: score moved"] += 0
                if differs(s, s0, 1e-9):
                    tot[f"{group}: score moved"] += 1
                    worst = max(worst, s0 / s, s / s0)
    for k, v in tot.items():
        print(f"{k:24} {v}")
    print(f"largest factor              {worst:.1f}x")
    return 0


def mode_noise() -> int:
    tot = collections.Counter()
    worst = (1.0, "")
    for p, prog in corpus():
        a = dom.load(str(p))
        s1, f1 = score(a, prog)
        with floor_overlap() as fl:
            s2, f2 = score(a, prog)
        grp = "coldstart" if p.name.startswith("coldstart") else "e4r"
        tot[f"{grp}: files"] += 1
        tot[f"{grp}: touching pairs credited"] += fl.tiny
        if differs(s1, s2, 1e-9):
            tot[f"{grp}: score rests on them"] += 1
            tot[f"{grp}: fail count too"] += len(f1) != len(f2)
            if s1 / s2 > worst[0]:
                worst = (s1 / s2, f"{p.relative_to(REPO)}: {len(f1)} fails as "
                                  f"scored, {len(f2)} without the phantom walls")
    for k, v in tot.items():
        print(f"{k:36} {v}")
    print(f"largest inflation: {worst[0]:.0f}x  {worst[1]}")
    return 0


def mode_dead_fields() -> int:
    tot = collections.Counter()
    for p, prog in corpus():
        a = dom.load(str(p))
        t = copy.deepcopy(a)
        dom.link(t)
        stale = sync_dead_fields(t)
        tot["files"] += 1
        tot["files with a stale inherited ratio"] += stale > 0
        tot["stale nodes"] += stale
        s1, s2 = score(a, prog)[0], score(t, prog)[0]
        if differs(s1, s2):
            tot["files whose SCORE reads one"] += 1
            print(f"  {p.relative_to(REPO)}: {s1:.6g} -> {s2:.6g}")
    for k, v in tot.items():
        print(f"{k:36} {v}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for flag in ("cells", "scores", "rotation", "noise", "dead-fields", "self-test"):
        ap.add_argument(f"--{flag}", action="store_true")
    args = ap.parse_args(argv)
    g.ORTHOGONAL_DIVISION = True
    if args.self_test:
        return mode_cells(True)
    for name, fn in (("cells", lambda: mode_cells(False)), ("scores", mode_scores),
                     ("rotation", mode_rotation), ("noise", mode_noise),
                     ("dead_fields", mode_dead_fields)):
        if getattr(args, name):
            return fn()
    ap.error("choose a mode")


if __name__ == "__main__":
    raise SystemExit(main())
