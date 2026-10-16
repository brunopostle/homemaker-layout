"""`homemaker-py-2g7.13.1.4`: room-to-wing allocation pilot.

The seeder (`seed_from_catalogue.py`) never decides which rooms go in which
wing: it deals rooms to storeys round-robin, splits the largest cells of all
wings until there are enough, and lets the adjacency-aware assignment place
rooms over every wing at once. This asks what an EXPLICIT allocation would
offer, from generic structure only (owner, 2026-10-16: the briefs are test
projects; nothing may come from what a room means):

1. a strategy plan (catalogue tree + storey count), sized on the real plot as
   the seeder sizes it; each built cell on each storey is a BIN with its own
   rectangle;
2. allocations of the programme's rooms to bins by CP-SAT: every room in one
   bin, a `level:` room on its storey, each bin's room area within
   ``--slack`` of its share of the bin (the rest is circulation), and as
   many room-room adjacency requirements as possible met inside one bin --
   diverse allocations by random objective noise;
3. each bin tested for SHAPE feasibility: is there any slicing of its
   rectangle into its rooms plus one circulation cell with every room's
   size, width and proportion clear of the fail line? Shape curves
   (`shapecurve.leaf_constraints`, the scorer's own bounds) composed over
   EVERY split of the bin's room set, both ways. A union of two feasible
   ranges is stored as its hull, which over-states feasibility, so a bin this
   calls infeasible is infeasible (up to the grid), and one it passes may not
   be;
4. the same test on allocations made the seeder's way (round-robin storeys,
   rooms dealt to a storey's wings in proportion to area), as the control.

The question on the bead: does exact feasibility prune anything, and how many
allocations survive?

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_2g71314_allocation.py \\
        --programme harbor-house --plan '3:H(B V(B H(O B) O))' --n 40
"""

from __future__ import annotations

import argparse
import itertools
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
from ortools.sat.python import cp_model  # noqa: E402

import seed_from_catalogue as sfc  # noqa: E402
import wings_catalogue as wc  # noqa: E402

from homemaker_layout import dom, geometry, graph, operators, programme, shapecurve  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GRID_N = 120


# --------------------------------------------------------------------------- #
# bins
# --------------------------------------------------------------------------- #

def bins_of(prog_dir: Path, plan: str, args):
    """[(storey, wing index, w, h)] for the plan sized on the plot; w, h in m."""
    init = dom.load(str(prog_dir / "init.dom"))
    conf, _cost = load_config(prog_dir)
    reqs = programme.load_programme_dir(str(prog_dir))
    plot, (w, d, _h) = sfc.plot_of(init)
    n_s, txt = plan.split(":", 1)
    n = int(n_s)
    tt = sfc.parse_tree(txt)
    covers = sfc.needed_cover(reqs, conf, w * d, args.circ_share)
    r = wc.optimise(tt, plot, 1.0, 0.77, wc.stable_rng(txt, args.programme, n),
                    starts=4, coverage=covers[n])
    g = sfc.ground(init, tt, r[3])
    geometry.clear_cache()
    wings = [lf for lf in g.leaves() if lf.type != "O"]
    dims = [shapecurve._dims(lf) for lf in wings]
    return [(s, i, dw, dh) for s in range(n) for i, (dw, dh) in enumerate(dims)], r[1]


# --------------------------------------------------------------------------- #
# shape feasibility of one bin: shape curves over every split of its rooms
# --------------------------------------------------------------------------- #

class Shapes:
    """Vectorised curves: (lo, hi) arrays over a geometric grid, NaN where
    nothing is feasible. ``wh`` is the w-range at each h, ``hw`` the h-range
    at each w."""

    def __init__(self, grid):
        self.grid = grid

    def leaf(self, b: shapecurve.LeafBounds):
        rg = b.range_grid(self.grid)
        lo = np.array([r[0] if r else np.nan for r in rg])
        hi = np.array([r[1] if r else np.nan for r in rg])
        return (lo, hi), (lo.copy(), hi.copy())

    def invert(self, lo, hi):
        g = self.grid
        mask = (lo[:, None] - 1e-9 <= g[None, :]) & (hi[:, None] + 1e-9 >= g[None, :])
        mask &= ~np.isnan(lo)[:, None]
        anyf = mask.any(axis=0)
        gm = np.where(mask, g[:, None], np.nan)
        with np.errstate(invalid="ignore"), np.testing.suppress_warnings() as sup:
            sup.filter(RuntimeWarning)
            ilo = np.where(anyf, np.nanmin(gm, axis=0), np.nan)
            ihi = np.where(anyf, np.nanmax(gm, axis=0), np.nan)
        # the true range ends somewhere between grid points: round OUTWARD a
        # step, so the curve over-states and an infeasible verdict stays sound
        step = g[1] / g[0]
        return ilo / step, ihi * step

    def side_by_side(self, a, b):
        """Widths add at a shared height."""
        lo, hi = a[0][0] + b[0][0], a[0][1] + b[0][1]
        return (lo, hi), self.invert(lo, hi)

    def stacked(self, a, b):
        lo, hi = a[1][0] + b[1][0], a[1][1] + b[1][1]
        return self.invert(lo, hi), (lo, hi)

    @staticmethod
    def hull(a, b):
        if a is None:
            return b
        out = []
        for x, y in zip(a, b):
            out.append((np.fmin(x[0], y[0]), np.fmax(x[1], y[1])))
        return tuple(out)

    def fits(self, c, w, h) -> bool:
        """Is (w, h) inside the curve? Read at both grid points bracketing
        the coordinate, either one enough (over-states, as above)."""
        g = self.grid
        for (lo, hi), x, y in ((c[1], w, h), (c[0], h, w)):
            j = int(np.searchsorted(g, x))
            for k in (j - 1, j):
                if 0 <= k < len(g) and not np.isnan(lo[k]) and lo[k] <= y <= hi[k]:
                    return True
        return False


def bin_feasible(bounds: list, w: float, h: float) -> bool:
    """Any slicing of a w x h rectangle into these leaves, every one inside its
    bounds? DP over sub-MULTISETS (equal bounds are interchangeable leaves):
    curve(M) = hull over splits M = A + B of A beside B and A above B. Hull
    over-states, so False is exact up to the grid."""
    if not bounds:
        return True
    kinds = sorted({(b.amin, b.amax, b.wmin, b.rmax) for b in bounds})
    kb = [shapecurve.LeafBounds(*k) for k in kinds]
    full = tuple(sum(1 for b in bounds if (b.amin, b.amax, b.wmin, b.rmax) == k) for k in kinds)
    sh = Shapes(shapecurve.make_grid(max(w, h) * 1.3, n=GRID_N))
    memo = {}

    def curve(m):
        if m in memo:
            return memo[m]
        if sum(m) == 1:
            memo[m] = sh.leaf(kb[m.index(1)])
            return memo[m]
        best = None
        for a in itertools.product(*(range(k + 1) for k in m)):
            if not any(a) or a == m:
                continue
            bb = tuple(x - y for x, y in zip(m, a))
            if a > bb:              # each unordered split once
                continue
            ca, cb = curve(a), curve(bb)
            best = sh.hull(best, sh.side_by_side(ca, cb))
            best = sh.hull(best, sh.stacked(ca, cb))
        memo[m] = best
        return best
    return sh.fits(curve(full), w, h)


# --------------------------------------------------------------------------- #
# allocations
# --------------------------------------------------------------------------- #

def room_list(reqs):
    prog = operators._programme_codes(reqs)
    return prog, [(c, r) for c, r in prog.items()]


def adjacency_pairs(prog) -> list[tuple[str, str]]:
    """Room-room adjacency requirements (generic c/o/s entries are not rooms)."""
    out = set()
    for c, r in prog.items():
        for tgt in r.adjacency:
            if tgt.lower() in ("c", "o", "s"):
                continue
            for c2 in prog:
                if c2 != c and graph.code_matches_requirement(c2, tgt):
                    out.add(tuple(sorted((c, c2))))
    return sorted(out)


def cpsat_allocations(prog, bins, args, rng):
    """Up to ``args.n`` distinct allocations, {(code, bin): count}."""
    codes = list(prog)
    pairs = adjacency_pairs(prog)
    share = 1 / (1 + args.circ_share)
    seen, out = set(), []
    for trial in range(args.n * 3):
        m = cp_model.CpModel()
        y = {(c, b): m.NewIntVar(0, prog[c].count, f"y_{c}_{b}")
             for c in codes for b in range(len(bins))}
        for c in codes:
            m.Add(sum(y[c, b] for b in range(len(bins))) == prog[c].count)
            lv = prog[c].level
            if lv is not None:
                for b, (s, _i, _w, _h) in enumerate(bins):
                    if s != lv:
                        m.Add(y[c, b] == 0)
        for b, (_s, _i, w, h) in enumerate(bins):
            cap = w * h * share
            area = sum(y[c, b] * int(round(prog[c].size or 0)) for c in codes)
            m.Add(area <= int(cap * (1 + args.slack)))
            m.Add(area >= int(cap * (1 - args.slack)))
        z = []
        for (a, c) in pairs:
            for b in range(len(bins)):
                v = m.NewBoolVar("")
                m.Add(y[a, b] >= 1).OnlyEnforceIf(v)
                m.Add(y[c, b] >= 1).OnlyEnforceIf(v)
                z.append(v)
        noise = [] if trial == 0 else [
            int(rng.integers(0, args.noise)) * y[c, b] for c in codes for b in range(len(bins))]
        m.Maximize(100 * sum(z) + sum(noise))
        sol = cp_model.CpSolver()
        sol.parameters.max_time_in_seconds = args.time
        sol.parameters.num_workers = 1
        sol.parameters.random_seed = trial
        st = sol.Solve(m)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if trial == 0:
                print("  CP-SAT: no allocation meets the bin capacities", flush=True)
                return out, pairs
            continue
        alloc = {k: sol.Value(v) for k, v in y.items() if sol.Value(v)}
        key = tuple(sorted(alloc.items()))
        met = sum(sol.Value(v) for v in z)
        if key not in seen:
            seen.add(key)
            out.append((alloc, met))
        if len(out) >= args.n:
            break
    return out, pairs


def seeder_allocation(prog, bins, n_storeys, rng):
    """The seeder's way: storeys round-robin (`buckets`), then each storey's
    rooms dealt to its wings in proportion to wing area."""
    reqs_like = {c: r for c, r in prog.items()}
    storeys = sfc.buckets(reqs_like, n_storeys, rng)
    alloc = Counter()
    for s, rooms in enumerate(storeys):
        bs = [b for b, (bs_, _i, _w, _h) in enumerate(bins) if bs_ == s]
        p = np.array([bins[b][2] * bins[b][3] for b in bs])
        for c in rooms:
            alloc[c, bs[int(rng.choice(len(bs), p=p / p.sum()))]] += 1
    return dict(alloc)


def met_rooms(alloc, pairs) -> tuple[int, int]:
    """(rooms with a room-room adjacency requirement that share a bin with a
    room meeting it, rooms with such a requirement)."""
    held = {}
    for (c, b), k in alloc.items():
        held.setdefault(b, Counter())[c] += k
    partners = {}
    for a, c in pairs:
        partners.setdefault(a, set()).add(c)
        partners.setdefault(c, set()).add(a)
    met = total = 0
    for cnt in held.values():
        for code, k in cnt.items():
            if code in partners:
                total += k
                if any(cnt.get(p) for p in partners[code]):
                    met += k
    return met, total


def evaluate(alloc, prog, bins, fit, circ_bounds, cache, circ_divisor):
    """(shape-feasible bins, area-feasible bins, total bins, shape failures).
    Each bin gets the seeder's circulation cells, one per ``circ_divisor``
    rooms (at least one). AREA-feasible: the rooms' minimum areas fit in the
    bin (circulation has no size bound, so there is no maximum)."""
    by_bin = {b: [] for b in range(len(bins))}
    for (c, b), k in alloc.items():
        by_bin[b] += [c] * k
    ok, area_ok, bad = 0, 0, []
    for b, codes in by_bin.items():
        _s, _i, w, h = bins[b]
        bounds = [shapecurve.leaf_constraints(fit, dom.Node(type=c)) for c in codes]
        if sum(x.amin for x in bounds) > w * h:
            continue                         # area-infeasible: not a shape question
        area_ok += 1
        key = (round(w, 2), round(h, 2), tuple(sorted(codes)))
        if key not in cache:
            n_circ = max(1, -(-len(codes) // circ_divisor))
            if len(set(codes)) > 10:
                cache[key] = None            # too many kinds to enumerate: not judged
            else:
                cache[key] = bin_feasible(bounds + [circ_bounds] * n_circ, w, h)
        v = cache[key]
        if v is None or v:
            ok += 1
        if v is False:
            bad.append((b, f"{w:.1f}x{h:.1f}", tuple(sorted(Counter(codes).items()))))
    return ok, area_ok, len(by_bin), bad


def self_test() -> int:
    """The check must say yes and no where the answer is known."""
    LB = shapecurve.LeafBounds
    room = LB(amin=20, amax=30, wmin=3, rmax=2)       # a 20-30 m2 room, 3 m wide, <= 2:1
    free = LB(amin=0, amax=math.inf, wmin=1.2, rmax=math.inf)   # a corridor
    cases = [
        ("one room in a 5 x 5 rectangle", [room], 5, 5, True),
        ("one room in a 10 x 10 rectangle (too big for it)", [room], 10, 10, False),
        ("room + corridor in 10 x 5 (room 5x5, corridor 5x5)", [room, free], 10, 5, True),
        ("room + corridor in 2.5 x 30 (too narrow for the room)", [room, free], 2.5, 30, False),
        ("four rooms + corridor in 10 x 11.2", [room] * 4 + [free], 10, 11.2, True),
        ("four rooms in 5 x 5 (area 80+ in 25)", [room] * 4 + [free], 5, 5, False),
        ("two rooms only in 13 x 5 (each at most 30 m2)", [room, room], 13, 5, False),
        # harbor-house's cr1 and la1 in a 4.5 m wing: cr1 is near its proportion
        # limit there, and a 5% grid rounded inward called this infeasible
        ("cr1 + la1 + corridor in 4.5 x 22.7 (marginal)",
         [LB(58.54, 101.46, 0.0, 3.073), LB(11.42, 28.58, 0.0, 2.573), free], 4.5, 22.7, True),
        ("cr1 in 4.5 x 22.7 with no corridor (22.7:4.5 exceeds 3.07)",
         [LB(58.54, 101.46, 0.0, 3.073)], 4.5, 22.7, False),
    ]
    bad = 0
    for name, bounds, w, h, want in cases:
        got = bin_feasible(bounds, w, h)
        bad += got != want
        print(f"  {'ok ' if got == want else 'BAD'} {name}: {got}")
    print("self-test", "PASSED" if not bad else f"FAILED ({bad})")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default="harbor-house")
    ap.add_argument("--plan", nargs="+", default=["3:H(B V(B H(O B) O))", "3:H(B V(B H(O B)) O)",
                                                  "3:H(V(B H(O V(O B))) B)"])
    ap.add_argument("--n", type=int, default=40, help="CP-SAT allocations per plan")
    ap.add_argument("--control", type=int, default=200, help="seeder-style allocations")
    ap.add_argument("--slack", type=float, default=0.3,
                    help="bin room area within this fraction of its share")
    ap.add_argument("--circ-share", type=float, default=0.25)
    ap.add_argument("--noise", type=int, default=60)
    ap.add_argument("--time", type=float, default=5.0)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not geometry.ORTHOGONAL_DIVISION:
        print("set HOMEMAKER_ORTHOGONAL_DIVISION=1", file=sys.stderr)
        return 2

    prog_dir = REPO / "examples" / args.programme
    conf, cost = load_config(prog_dir)
    fit = Fitness(conf, cost)
    reqs = programme.load_programme_dir(str(prog_dir))
    prog, _ = room_list(reqs)
    circ_bounds = shapecurve.leaf_constraints(fit, dom.Node(type="C"))
    circ_div = int(sfc.constructor_kwargs()["circ_divisor"])
    print(f"{args.programme}: {sum(r.count for r in prog.values())} rooms; circulation cell "
          f"wmin {circ_bounds.wmin:.2f} m", flush=True)
    for plan in args.plan:
        bins, frac = bins_of(prog_dir, plan, args)
        n_s = int(plan.split(":")[0])
        rng = wc.stable_rng(args.programme, plan, "alloc")
        print(f"\nplan {plan}, cover {frac:.0%}: {len(bins)} bins "
              + ", ".join(f"{w:.1f}x{h:.1f}" for s, i, w, h in bins if s == 0), flush=True)
        cache = {}
        allocs, pairs = cpsat_allocations(prog, bins, args, rng)
        print(f"  room-room adjacency requirements: {pairs}")
        arms = [("CP-SAT", [a for a, _m in allocs])]
        arms.append(("seeder-style", [seeder_allocation(prog, bins, n_s, rng)
                                       for _ in range(args.control)]))
        for name, al in arms:
            if not al:
                continue
            res = [evaluate(a, prog, bins, fit, circ_bounds, cache, circ_div) for a in al]
            mets = [met_rooms(a, pairs) for a in al]
            area_all = sum(1 for _ok, ar, nb, _b in res if ar == nb)
            shape_all = sum(1 for ok, ar, nb, _b in res if ok == nb)
            print(f"  {name}: {len(al)} allocations; rooms with a room-room need met in-bin "
                  f"median {int(np.median([m for m, _t in mets]))} of {mets[0][1]}; "
                  f"every bin area-feasible {area_all}, every bin also shape-feasible "
                  f"{shape_all}; bins: {sum(nb for *_x, nb, _b in res)} total, "
                  f"{sum(nb - ar for _ok, ar, nb, _b in res)} area-infeasible, "
                  f"{sum(ar - ok for ok, ar, _nb, _b in res)} area-feasible but shape-infeasible",
                  flush=True)
            why = Counter((sz, b) for *_x, bad in res for _bb, sz, b in bad)
            for (sz, k), v in why.most_common(4):
                print(f"    shape-infeasible x{v}: {sz} holding {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
