"""Price the stair-shape ruling (`homemaker-py-5fje.12`, DESIGN.md §39.216).

Scores each design twice in one process: with Urb's ``_stair_fits`` (one
flight shape per door count, two landings across the base whatever the base,
so a base under 2 * stair_width counted negative treads), and with today's
(turn count a maximum; a flight narrows to fit, down to 0.9 m, two of
them across a turned shape's base). ``--fixed-width`` prices the arm the
owner turned down instead: flights always 1.25 m. Reports every design whose score or fail list moved, the fails
added and removed, and, per stair cell, the fit chosen before and after.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje12_stair_shapes.py \\
        [--self-test] DESIGN.dom ...

With no designs it reads §39.211's set: the 98 re-ranked designs and the 114
Phase 1 twins. ``--self-test`` is the negative control: with the old rule on
both sides, nothing may move.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diag_shrunk_rooms import KEYS  # noqa: E402
from successive_halving import REPO, load_config  # noqa: E402

from homemaker_layout import dom, geometry  # noqa: E402
from homemaker_layout.fitness import Fitness, _height  # noqa: E402

NEW = Fitness._stair_fits


def urb_stair_fits(self, leaf, corners):
    """``_stair_fits`` as it was at 2647f03: one shape, chosen by door count."""
    root = dom._level_root(leaf)
    while root.below is not None:
        root = root.below
    max_riser = getattr(root, "stair_riser", None) or 0.21
    width = getattr(root, "stair_width", None) or 1.25
    height = _height(leaf)
    risers = self._risers_number(height, max_riser)
    going = self._ideal_going(height / risers)
    turns = {1: self._three_turn, 2: self._two_turn,
             3: self._one_turn}.get(len(set(corners)), self._zero_turn)
    quad = geometry.quad_corners(leaf)
    sides = [math.dist(quad[i], quad[(i + 1) % 4]) for i in range(4)]
    fits = []
    for edge in range(4):
        base = sides[edge]
        going_a = int((base - 2 * width) / going)
        going_b = turns(risers, going_a)
        for side in (1, 3):
            fits.append(sides[(edge + side) % 4] / (width * 2 + going * going_b))
    return fits


def fixed_width_stair_fits(self, leaf, corners):
    """The arm the owner priced and turned down: turns a maximum, as today,
    but every flight measured at ``stair_width``, so a turned shape needs a
    base of two full widths. It made the owner's 2.29 m programme-house
    U-stair a missing stair (x0.019)."""
    root = dom._level_root(leaf)
    while root.below is not None:
        root = root.below
    max_riser = getattr(root, "stair_riser", None) or 0.21
    width = getattr(root, "stair_width", None) or 1.25
    height = _height(leaf)
    risers = self._risers_number(height, max_riser)
    going = self._ideal_going(height / risers)
    max_turns = {1: 3, 2: 2, 3: 1}.get(len(set(corners)), 0)
    shapes = (self._zero_turn, self._one_turn,
              self._two_turn, self._three_turn)[:max_turns + 1]
    quad = geometry.quad_corners(leaf)
    sides = [math.dist(quad[i], quad[(i + 1) % 4]) for i in range(4)]
    fits = []
    for edge in range(4):
        base = sides[edge]
        going_a = int((base - 2 * width) / going)
        for n_turns, turns in enumerate(shapes):
            if n_turns and base < 2 * width:
                continue
            going_b = turns(risers, going_a)
            for side in (1, 3):
                fits.append(sides[(edge + side) % 4] / (width * 2 + going * going_b))
    return fits


def default_designs() -> list[Path]:
    tsv = REPO / "experiments/results/aggregation/rerank-phi1e-3.tsv"
    paths = [REPO / line.split("\t")[1] for line in tsv.read_text().splitlines()[1:]]
    paths += sorted((REPO / "experiments/results/phase1").glob("*.dom"))
    return paths


def score(fit, path, rule):
    Fitness._stair_fits = rule
    stairs = []
    orig = Fitness._stair_fit

    def spy(self, leaf, corners):
        f = orig(self, leaf, corners)
        q = geometry.quad_corners(leaf)
        short = min(math.dist(q[i], q[(i + 1) % 4]) for i in range(4))
        stairs.append((leaf.id, round(short, 2), round(geometry.area(leaf), 1), f))
        return f

    Fitness._stair_fit = spy
    try:
        root = dom.load(str(path))
        dom.link(root)
        s, fails = fit.score_with_fails(root)
    finally:
        Fitness._stair_fit = orig
        Fitness._stair_fits = NEW
    return s, sorted(fails), stairs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--fixed-width", action="store_true",
                    help="price the arm turned down (1.25 m flights) instead of today's")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    after = urb_stair_fits if a.self_test else fixed_width_stair_fits if a.fixed_width else NEW
    paths = [Path(p) for p in a.designs] or default_designs()
    cache, moved, added, removed = {}, Counter(), Counter(), Counter()
    ratios = {}
    for path in paths:
        prog = next((v for k, v in KEYS.items() if k in str(path)), None)
        if prog is None:
            print(f"# skipped, no programme: {path}", file=sys.stderr)
            continue
        if prog not in cache:
            cache[prog] = Fitness(*load_config(REPO / "examples" / prog))
        s0, f0, st0 = score(cache[prog], path, urb_stair_fits)
        s1, f1, st1 = score(cache[prog], path, after)
        if s0 == s1 and f0 == f1:
            continue
        moved[prog] += 1
        c0 = Counter(re.sub(r"^\d+/[lr]* ", "", x) for x in f0)
        c1 = Counter(re.sub(r"^\d+/[lr]* ", "", x) for x in f1)
        added.update(c1 - c0)
        removed.update(c0 - c1)
        ratios.setdefault(prog, []).append(s1 / s0 if s0 else math.inf)
        fits = "; ".join(f"{i or '-'} {w}m {ar}m2 {b:.2f}->{c:.2f}"
                         for (i, w, ar, b), (_, _, _, c) in zip(st0, st1) if b != c)
        print(f"{prog}\t{path.relative_to(REPO) if path.is_absolute() else path}\t"
              f"x{s1 / s0 if s0 else math.inf:.3g}\tfails {len(f0)}->{len(f1)}\t{fits}")
    total = len(paths)
    print(f"\n{sum(moved.values())} of {total} designs move: {dict(moved)}")
    for prog, r in sorted(ratios.items()):
        r = sorted(r)
        print(f"  {prog}: ratio median {r[len(r) // 2]:.3g}, min {r[0]:.3g}, max {r[-1]:.3g}")
    print(f"fails added:   {dict(added)}")
    print(f"fails removed: {dict(removed)}")
    if a.self_test and moved:
        print("SELF-TEST FAILED: the old rule against itself moved a score")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
