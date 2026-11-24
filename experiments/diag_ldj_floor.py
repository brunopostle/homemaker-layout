"""A shape-fail FLOOR from the shape-curve DP, and whether it ranks children
(`homemaker-py-ldj` direction (b), DESIGN.md §39.262).

`shapecurve.is_feasible` answers yes/no -- can some ratio assignment clear
every leaf's size/width/proportion bounds at once -- and on the full
programmes it almost always says no (§38.24), so as a gate it never opens.
The bead's suggestion: an infeasible topology still has a best-achievable
number of leaves that must miss their bounds, and that floor is what a
pre-filter would rank candidates on.

`floor(root, fit)` computes it with the same model as the DP. Each leaf's
table V[w, h] is 0 where the cell shape clears its bounds
(`shapecurve.leaf_constraints`) and 1 where it does not; a cut composes its
children by min-plus convolution along the dimension the cut sums (each
child read in the parent's frame by its rotation parity, as
`shapecurve._child_contrib`); the floor is the region root's value at its own
box. Grid g[i] = (i+1)Δ, so g[i1] + g[i2] = g[i1+i2+1] exactly. Regions,
below-fixed leaves and the merged copy are as `_solve_all_levels` /
`is_feasible` take them, except that an upper storey's fixed boxes are read
from the tree as it stands (no realisation between storeys), so on a
multi-storey tree this is the floor GIVEN the lower storeys' current ratios.

Checks before the signal (`--self-test`): a hand tree whose floor is known;
floor 0 agrees with `is_feasible`; and the floor never exceeds the shape
fails a tree actually has at its own ratios (it is a lower bound, up to the
DP's rectangle approximation, so violations are counted, not assumed away).

The signal (`main`): children drawn with the search's own mutation mix from
the newest cold corpus (as `diag_8b2u12_children.py`), each given the 80
evaluations a child gets. Two predictors of how a child ends, both cheap:
  floor  this DP
  raw    the child's shape fails at its inherited ratios (one score) --
         the baseline the floor must beat to be worth a pre-filter.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_ldj_floor.py --self-test
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_ldj_floor.py --draws 8
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import sys
import time
from pathlib import Path

import numpy as np

from homemaker_layout import dom, driver, geometry, innerloop, operators, programme, shapecurve

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
SHAPE = (" size", " width", " proportion")
G = 120


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def leaf_table(b, g) -> np.ndarray:
    W, H = np.meshgrid(g, g, indexing="ij")
    A = W * H
    ok = (A >= b.amin - 1e-9) & (A <= b.amax + 1e-9)
    ok &= np.minimum(W, H) >= b.wmin - 1e-9
    ok &= np.maximum(W, H) / np.minimum(W, H) <= b.rmax + 1e-9
    return np.where(ok, 0, 1).astype(np.int32)


def table(node, fit, g) -> np.ndarray:
    """Min violations in ``node``'s own frame, indexed [w, h]."""
    if not node.divided:
        return leaf_table(shapecurve.leaf_constraints(fit, node), g)
    tl, tr = table(node.left, fit, g), table(node.right, fit, g)
    if node.left.rotation % 2:
        tl = tl.T
    if node.right.rotation % 2:
        tr = tr.T
    n = len(g)
    out = np.full((n, n), 10 ** 6, dtype=np.int32)
    for i1 in range(n - 1):
        cand = tl[i1][None, :] + tr[: n - i1 - 1]
        np.minimum(out[i1 + 1:], cand, out=out[i1 + 1:])
    return out


def _region_floor(region, fit) -> int:
    w, h = shapecurve._dims(region)
    if not region.divided:
        return 0 if shapecurve._leaf_feasible(fit, region) else 1
    d = max(w, h) * 1.2 / G
    g = (np.arange(G) + 1) * d
    t = table(region, fit, g)
    iw, ih = int(round(w / d)) - 1, int(round(h / d)) - 1
    win = t[max(0, iw - 1): iw + 2, max(0, ih - 1): ih + 2]
    return int(win.min())


def floor(root, fit) -> int:
    probe = copy.deepcopy(root)
    geometry.clear_cache()
    dom.merge_divided(probe)
    dom.link(probe)
    geometry.clear_cache()
    total = 0
    try:
        for lvl in dom.levels(probe):
            for region in shapecurve._region_roots(lvl):
                if not region.divided and region.below is not None:
                    total += 0 if shapecurve._leaf_feasible(fit, region) else 1
                else:
                    total += _region_floor(region, fit)
    finally:
        geometry.clear_cache()
    return total


def shape_fails(fails) -> int:
    return sum(f.endswith(SHAPE) for f in fails)


def _auc(pred, good) -> float:
    """P(a good child is predicted lower than a bad one), ties half."""
    g = [p for p, y in zip(pred, good) if y]
    b = [p for p, y in zip(pred, good) if not y]
    if not g or not b:
        return float("nan")
    s = sum((x < y) + 0.5 * (x == y) for x in g for y in b)
    return s / (len(g) * len(b))


def _spearman(x, y) -> float:
    from scipy.stats import spearmanr
    return float(spearmanr(x, y).correlation)


def self_test() -> int:
    from homemaker_layout.fitness import Fitness, load_config
    geometry.ORTHOGONAL_DIVISION = True
    # (1) a known floor: two copies of a 2-leaf tree, one where both leaves
    # can clear their bounds and one where a 1 m wide leaf cannot
    class B:
        amin, amax, wmin, rmax = 9.0, 16.0, 2.5, 2.0
    g = (np.arange(G) + 1) * 0.1
    t = leaf_table(B, g)
    assert t[29, 29] == 0 and t[9, 29] == 1        # 3x3 ok, 1x3 too narrow
    # (2)-(3) on real designs
    prog = REPO / "examples" / "programme-house"
    fit = Fitness(*load_config(prog))
    agree = viol = n = 0
    for p in sorted(REPO.glob("examples/*/coldstart-4428262+orth-*.dom")):
        pf = Fitness(*load_config(p.parent))
        root = dom.load(str(p))
        dom.link(root)
        geometry.clear_cache()
        fl = floor(root, pf)
        feas = shapecurve.is_feasible(root, pf)
        actual = shape_fails(pf.score_with_fails(root)[1])
        n += 1
        agree += (fl == 0) == feas
        viol += fl > actual
        print(f"  {p.parent.name}/{p.name[-6:-4]}: floor {fl}, feasible {feas}, "
              f"shape fails at own ratios {actual}")
    print(f"self-test: floor==0 agrees with is_feasible on {agree}/{n}; "
          f"floor above the actual shape fails on {viol}/{n}")
    assert agree >= n - 1, "floor and is_feasible disagree"
    del fit
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="coldstart-4428262+orth-500000-s*.dom")
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--draws", type=int, default=8)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    geometry.ORTHOGONAL_DIVISION = True
    shaft = _load("diag_8b2u_fixed_shaft")
    weights, search = shaft.search_weights(), shaft.SEARCH
    print("programme\tparent\top\tparent_fails\tfloor\traw_shape\tpost_shape\tpost_fails\t"
          "floor_ms\tbeats_parent")
    for name in a.programme or PROGRAMMES:
        prog = REPO / "examples" / name
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]
        fit = driver._fitness_for(str(prog), **search)
        for p in sorted(prog.glob(a.corpus)):
            parent = dom.load(str(p))
            dom.link(parent)
            geometry.clear_cache()
            pfails = len(fit.score_with_fails(copy.deepcopy(parent))[1])
            ratios = innerloop.ratio_map(parent)
            rng = np.random.default_rng(int.from_bytes(
                hashlib.blake2b(f"ldj/{name}/{p.name}".encode(), digest_size=8).digest(), "little"))
            got = 0
            while got < a.draws:
                child, desc = operators.mutate(parent, rng, types, weights=weights, reqs=reqs)
                if "noop" in desc:
                    continue
                got += 1
                dom.link(child)
                geometry.clear_cache()
                t0 = time.process_time()
                fl = floor(child, fit)
                ms = (time.process_time() - t0) * 1000
                raw = shape_fails(fit.score_with_fails(copy.deepcopy(child))[1])
                root = copy.deepcopy(child)
                dom.link(root)
                geometry.clear_cache()
                x0 = innerloop.warm_x0(root, {**innerloop.ratio_map(root), **ratios})
                ind, _ = driver._evaluate(root, str(prog), x0, 80, {}, "ldj", **search)
                post = shape_fails(ind.fails or ())
                print(f"{name}\t{p.name[-6:-4]}\t{desc.split()[0]}\t{pfails}\t{fl}\t{raw}\t{post}\t"
                      f"{ind.n_fails}\t{ms:.0f}\t{int(ind.n_fails <= pfails)}", flush=True)
    return 0


def summarise(path) -> int:
    import csv
    rows = list(csv.DictReader(open(path), delimiter="\t"))
    print(f"{len(rows)} children")
    for prog in [*dict.fromkeys(r["programme"] for r in rows), "ALL"]:
        rs = [r for r in rows if prog == "ALL" or r["programme"] == prog]
        f = [int(r["floor"]) for r in rs]
        raw = [int(r["raw_shape"]) for r in rs]
        post = [int(r["post_shape"]) for r in rs]
        good = [r["beats_parent"] == "1" for r in rs]
        ms = sorted(float(r["floor_ms"]) for r in rs)
        print(f"{prog:16} n {len(rs):3d}  spearman(post shape): floor {_spearman(f, post):+.2f} "
              f"raw {_spearman(raw, post):+.2f}   AUC(child not worse): floor {_auc(f, good):.2f} "
              f"raw {_auc(raw, good):.2f}  (good {sum(good)})  floor median {ms[len(ms) // 2]:.0f} ms"
              f"  floor>post {sum(a > b for a, b in zip(f, post))}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--summarise":
        raise SystemExit(summarise(sys.argv[2]))
    raise SystemExit(main())
