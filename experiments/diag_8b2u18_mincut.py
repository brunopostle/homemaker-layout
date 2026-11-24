"""Min-cut partitioning seeds, evaluated at zero search budget
(`homemaker-py-8b2u.18`, DESIGN.md §39.261).

The classic top-down floorplanner: recursively bisect the set of modules so
that few required connections cross each cut, which yields a slicing tree
whose sibling structure already follows the netlist. The constructor today
grows a RANDOM tree (`operators._grow_leaves`) and then labels it
geometrically (`operators._assign_adjacency_aware`); this arm replaces just
those two steps, per storey, with a tree chosen from the adjacencies, and
leaves everything else -- the storey split, leaf sharing, sizing from targets
(`_size_divisions_from_targets`), the driver's 80 seed evaluations -- as the
default search does it.

The netlist (`netlist`). Items are the storey's rooms (after sharing, as
the constructor lists them) plus its `C` and `O` cells, in the numbers the
constructor would grow. A requirement "a next to t" is any-of: each a needs
SOME t, so each instance of a is joined to each of the n instances of t with
weight 1/n. Every room that asks for `c` is joined that way to the storey's
`C` cells, and for `o` to its `O` cells, so circulation is spread over the
tree in proportion to the rooms that need it rather than placed by hand.

The bisection (`bisect`): area-weighted (a room weighs its target, `C` half
a mean room, `O` a mean room), each side between 30% and 70% of the weight,
an FM-style pass of single moves and swaps from several random starts, the
lowest cut kept, ties to the rng. Each cut's axis is chosen geometrically:
of the two, the one whose two children are squarer (`usable_aspect`), at
the area fraction of its two sides.

Arms, the same constructor rng seed for both, scored by `driver._evaluate`
with the default search's options:

  default+1 / default+80     today's constructed seed, raw and after the
                             80 evaluations a seed gets
  mincut+1  / mincut+80      the min-cut tree on every storey
  mincut0+1 / mincut0+80     the min-cut tree on the ground storey only, the
                             storeys above as today (§39.261: an upper storey's
                             tree is bound by the cuts it inherits)

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u18_mincut.py --seeds 12
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u18_mincut.py --self-test
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import inspect
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from homemaker_layout import dom, driver, geometry, operators, programme
from homemaker_layout.fitness import classify_fail_tier

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
# respect a cut inherited from the storey below (--no-inherit: the first
# version, which did not, and made tokens on every upper storey)
INHERIT = True
CONN = ("not connected", "inaccessible usable space", " access", "not adjacent to c",
        "no outside public access")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def netlist(items: list[str], reqs) -> np.ndarray:
    """Symmetric any-of weights between items (codes, `C`, `O`)."""
    n = len(items)
    W = np.zeros((n, n))
    where = {}
    for i, it in enumerate(items):
        where.setdefault(it.lower() if it in ("C", "O") else it, []).append(i)
    for i, it in enumerate(items):
        r = reqs.get(it)
        if r is None:
            continue
        for t in r.adjacency + r.co_locate:
            js = [j for j in where.get(t, []) if j != i]
            for j in js:
                W[i, j] += 1.0 / len(js)
                W[j, i] += 1.0 / len(js)
    return W


def _cut(W, side) -> float:
    a = side.astype(bool)
    return float(W[a][:, ~a].sum())


def bisect(W, wt, rng, restarts: int = 6, lo: float = 0.3, hi: float = 0.7):
    """Area-balanced min-cut bisection; returns a 0/1 array."""
    n = len(wt)
    tot = wt.sum()
    best = None
    for _ in range(restarts):
        side = np.zeros(n, dtype=int)
        acc = 0.0
        mid = (lo + hi) / 2         # start inside the window, not at a half
        for i in rng.permutation(n):
            if acc + wt[i] <= mid * tot:
                side[i] = 1
                acc += wt[i]
        if side.sum() in (0, n):
            side[int(rng.integers(n))] ^= 1
        improved = True
        while improved:
            improved = False
            cur = _cut(W, side)
            moves = [(i,) for i in range(n)] + [
                (i, j) for i in range(n) for j in range(i + 1, n) if side[i] != side[j]]
            for mv in [moves[k] for k in rng.permutation(len(moves))]:
                s2 = side.copy()
                for i in mv:
                    s2[i] ^= 1
                f = (wt * s2).sum() / tot
                if not lo <= f <= hi or s2.sum() in (0, n):
                    continue
                c = _cut(W, s2)
                if c < cur - 1e-9:
                    side, cur, improved = s2, c, True
        key = (_cut(W, side), float(rng.random()))
        if best is None or key < best[0]:
            best = (key, side)
    return best[1]


def _place(node, root, frac, rng):
    """Cut ``node`` at area fraction ``frac``; of the two axes, the one whose
    children are squarer. Rotation 0/2 and 1/3 are the two ends of one axis
    each; the end is drawn."""
    best = None
    for axis in (0, 1):
        rot = axis + 2 * int(rng.integers(2))
        node.rotation, node.division = rot, [frac, frac]
        dom.link(root)
        geometry.clear_cache()
        try:
            worst = max(geometry.usable_aspect(node.left), geometry.usable_aspect(node.right))
        except Exception:
            worst = float("inf")
        if best is None or worst < best[0]:
            best = (worst, rot)
    node.rotation, node.division = best[1], [frac, frac]
    dom.link(root)
    geometry.clear_cache()


INHERIT_TOL = 0.08


def _inherited_frac(node, root) -> "float | None":
    """A node whose path is divided on the storey below draws THAT cut: its
    own rotation and ratio are dead fields. The area fraction its low child
    gets, or None when the cut is its own."""
    if node.below is None or not node.below.divided:
        return None
    node.type = None
    node.left, node.right = dom.Node(), dom.Node()
    node.division, node.rotation = list(node.below.division), node.below.rotation
    dom.link(root)
    geometry.clear_cache()
    return geometry.area(node.left) / max(geometry.area(node), 1e-9)


def build(node, root, items, wt, W, rng):
    if len(items) == 1:
        node.type = items[0]
        return
    fixed = _inherited_frac(node, root) if INHERIT else None
    if fixed is None:
        side = bisect(W, wt, rng)
    else:
        # the low child (side 0) must get about the inherited fraction
        side = 1 - bisect(W, wt, rng, lo=max(0.0, fixed - INHERIT_TOL),
                          hi=min(1.0, fixed + INHERIT_TOL))
        if side.sum() in (0, len(side)):
            side = bisect(W, wt, rng)
    a = [k for k in range(len(items)) if side[k] == 0]
    b = [k for k in range(len(items)) if side[k] == 1]
    node.type = None
    node.left, node.right = dom.Node(), dom.Node()
    if fixed is None:
        _place(node, root, float(wt[a].sum() / wt.sum()), rng)
    else:
        node.division, node.rotation = list(node.below.division), node.below.rotation
        dom.link(root)
        geometry.clear_cache()
    for child, idx in ((node.left, a), (node.right, b)):
        build(child, root, [items[k] for k in idx], wt[idx], W[np.ix_(idx, idx)], rng)


class MinCut:
    """Stand-ins for `_grow_leaves` and `_assign_adjacency_aware`, installed
    for the duration of one `constructive_topology` call."""

    def __init__(self, reqs, ground_only=False, originals=None):
        self.reqs = reqs
        self.n_leaves = {}
        self.ground_only = ground_only
        self.orig_grow, self.orig_assign = originals or (None, None)

    def grow(self, lvl, n_leaves, rng, balance=False):
        if self.ground_only and lvl.below is not None:
            return self.orig_grow(lvl, n_leaves, rng, balance=balance)
        self.n_leaves[id(lvl)] = n_leaves

    def assign(self, lvl, rooms, reqs, rng, interior_outside=True, n_outside=1, **kw):
        if self.ground_only and lvl.below is not None:
            return self.orig_assign(lvl, rooms, reqs, rng, interior_outside=interior_outside,
                                    n_outside=n_outside, **kw)
        n_c = self.n_leaves[id(lvl)] - len(rooms) - n_outside
        items = list(rooms) + ["C"] * n_c + ["O"] * n_outside
        mean = float(np.mean([reqs[r].size for r in rooms if reqs[r].size])) if rooms else 10.0
        wt = np.array([reqs[it].size if it in reqs and reqs[it].size else
                       (mean / 2 if it == "C" else mean) for it in items], dtype=float)
        root = lvl
        while root.below is not None:
            root = root.below
        build(lvl, root, items, wt, netlist(items, reqs), rng)
        dom.link(root)
        geometry.clear_cache()


def construct(prog, reqs, types, seed, args, defaults, mincut):
    """``mincut``: False (today's seeder), True (every storey), or "ground"
    (the ground storey by min-cut, the storeys above as today)."""
    kw = dict(min_storeys=max(programme.n_storeys_required(reqs),
                              programme.storey_minimum(str(prog))),
              adjacency_aware=defaults["seed_adjacency_aware"],
              proportion_aware=defaults["seed_proportion_aware"],
              circ_divisor=defaults["circ_divisor"],
              leaf_sharing=args.leaf_sharing, leaf_share_factor=args.leaf_share_factor,
              depth_balanced=defaults["depth_balanced"],
              interior_outside=defaults["interior_outside"],
              outside_divisor=defaults["outside_divisor"])
    seed_root = dom.load(str(prog / "init.dom"))
    rng = np.random.default_rng(seed)
    if not mincut:
        return operators.constructive_topology(seed_root, reqs, rng, sorted(reqs) + ["C", "O"], **kw)
    saved = operators._grow_leaves, operators._assign_adjacency_aware
    mc = MinCut(reqs, ground_only=mincut == "ground", originals=saved)
    operators._grow_leaves, operators._assign_adjacency_aware = mc.grow, mc.assign
    try:
        return operators.constructive_topology(seed_root, reqs, rng, sorted(reqs) + ["C", "O"], **kw)
    finally:
        operators._grow_leaves, operators._assign_adjacency_aware = saved


def measure(root, prog, budget, search):
    geometry.clear_cache()
    ind, _ = driver._evaluate(copy.deepcopy(root), str(prog), None, budget, {}, "seed", **search)
    fails = ind.fails or ()
    return {"fails": ind.n_fails, "fit": ind.fitness,
            "hard": sum(classify_fail_tier(f) == "hard" for f in fails),
            "conn": sum(any(k in f for k in CONN) for f in fails),
            "adj": sum("not adjacent to" in f for f in fails),
            "fam": Counter(f.split(" ", 1)[1] if "/" in f.split(" ", 1)[0] else f for f in fails)}


def self_test() -> int:
    """Controls: (1) the netlist is any-of -- a room asking for a code with
    four instances weighs 1/4 to each, and a room asking for nothing weighs
    nothing; (2) the bisection finds the obvious zero cut on two cliques that
    the random start does not; (3) a min-cut seed holds every room the
    default seed holds (the stand-ins dropped nothing)."""
    class R:
        def __init__(self, size, adjacency=(), co_locate=()):
            self.size, self.adjacency, self.co_locate = size, list(adjacency), list(co_locate)
    reqs = {"a": R(10, ["t"]), "t": R(10), "z": R(10)}
    W = netlist(["a", "t", "t", "t", "t", "z"], reqs)
    assert abs(W[0, 1] - 0.25) < 1e-9 and abs(W[0, 1:5].sum() - 1) < 1e-9
    assert W[5].sum() == 0
    k = 8
    W2 = np.zeros((k, k))
    for grp in (range(0, 4), range(4, 8)):
        for i in grp:
            for j in grp:
                if i != j:
                    W2[i, j] = 1
    side = bisect(W2, np.ones(k), np.random.default_rng(0))
    assert _cut(W2, side) == 0, f"min cut missed: {_cut(W2, side)}"
    geometry.ORTHOGONAL_DIVISION = True
    from homemaker_layout import evolve
    args = evolve._parse_args(["init.dom"])
    defaults = {k: v.default for k, v in inspect.signature(driver.search).parameters.items()}
    for name in PROGRAMMES:
        prog = REPO / "examples" / name
        rq = programme.load_programme_dir(str(prog))
        a = construct(prog, rq, sorted(rq), 0, args, defaults, False)
        b = construct(prog, rq, sorted(rq), 0, args, defaults, True)
        dom.link(a)
        dom.link(b)
        ca = Counter(lf.type for lv in dom.levels(a) for lf in lv.leaves())
        cb = Counter(lf.type for lv in dom.levels(b) for lf in lv.leaves())
        assert ca == cb, f"{name}: leaf types differ {ca - cb} / {cb - ca}"
        assert any(lf.type is None for lv in dom.levels(b) for lf in lv.leaves()) is False
        print(f"self-test {name}: {sum(ca.values())} leaves, same multiset both arms")
    print("self-test passed")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--first-seed", type=int, default=0)
    ap.add_argument("--no-inherit", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    global INHERIT
    INHERIT = not a.no_inherit
    if a.self_test:
        return self_test()
    geometry.ORTHOGONAL_DIVISION = True
    from homemaker_layout import evolve
    args = evolve._parse_args(["init.dom"])
    search = dict(leaf_sharing=args.leaf_sharing, collapse_insearch=args.collapse_insearch)
    defaults = {k: v.default for k, v in inspect.signature(driver.search).parameters.items()}
    print("programme\tseed\tarm\tfails\thard\tconn\tadj\tfitness\tfamilies")
    for name in a.programme or PROGRAMMES:
        prog = REPO / "examples" / name
        reqs = programme.load_programme_dir(str(prog))
        for seed in range(a.first_seed, a.first_seed + a.seeds):
            for arm, mc in (("default", False), ("mincut", True), ("mincut0", "ground")):
                topo = construct(prog, reqs, sorted(reqs), seed, args, defaults, mc)
                dom.link(topo)
                for budget in (1, 80):
                    m = measure(topo, prog, budget, search)
                    fam = ";".join(f"{k}={v}" for k, v in m["fam"].most_common())
                    print(f"{name}\t{seed}\t{arm}+{budget}\t{m['fails']}\t{m['hard']}\t"
                          f"{m['conn']}\t{m['adj']}\t{m['fit']:.4g}\t{fam}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
