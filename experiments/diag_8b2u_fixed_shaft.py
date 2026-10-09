"""`homemaker-py-8b2u` experiment 4: what would a FIXED stair block cost?

A rectangle frame would let the stair shaft be a pre-placed block -- one
rectangle at the same coordinates on every storey, chosen once, that no move
may disturb (floorplanning's "pre-placed macro"). Today the shaft is a column
that EMERGES (a cell identical on every storey, typed `C` -- the owner's ruling,
§39.72), and ordinary moves break it; `mutate_repair_shaft` cuts a new one back.

Freezing the shaft forbids every move that breaks it. That is free only if
those moves are wasted. So, on every artefact with an intact shaft, draw
children with the SEARCH'S OWN mutation mix and settings (search config
4549a418fc), evaluate each the way the search does (`driver._evaluate`, parent
ratios carried, child_budget 80), and split them:

  kept      the child still has an intact shaft
  emptied   the child has NO intact shaft -- what a fixed block forbids

For each group: how often the child BEATS its (equally evaluated) parent. If
emptying children essentially never win, a fixed block costs nothing and frees
the evaluations they consume. It also reports WHERE each design's shaft sits, as
a fraction of the plot's bounding rectangle, since a fixed block needs its
position chosen once.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u_fixed_shaft.py
"""

from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from homemaker_layout import dom, driver, geometry as g, innerloop, operators, programme  # noqa: E402

PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
CORPUS = "coldstart-07b2058+orth-500000-s*.dom"
SEARCH = dict(leaf_sharing=True, collapse_insearch=True)
CHILD_BUDGET = 80


def search_weights() -> dict:
    """`driver.search`'s mutation weights under search config 4549a418fc."""
    w = dict(driver._MUTATION_WEIGHTS)
    for off in ("reassociate", "bridge_circulation", "ruin_recreate", "reassign",
                "level_add_migrate", "storey_height", "light_well"):
        w[off] = 0.0
    return w


def shafts(root) -> list:
    return operators._shaft_paths(dom.levels(root))


def evaluate(root, prog, parent_ratios):
    root = copy.deepcopy(root)
    ratios = {**innerloop.ratio_map(root), **parent_ratios}
    ind, _ = driver._evaluate(root, str(prog), innerloop.warm_x0(root, ratios),
                              CHILD_BUDGET, {}, "8b2u", **SEARCH)
    return ind.fitness, ind.n_fails


def where(root, path):
    """Shaft cell centroid as (u, v) fractions of the plot's bounding rectangle,
    and its area in m2."""
    lvl = dom.levels(root)[0]
    leaf = lvl if path == "" else lvl.by_id(path)
    u, v = g._reference_axes(lvl)
    plot = [g.coordinate(lvl, i) for i in range(4)]
    pu = [p[0] * u[0] + p[1] * u[1] for p in plot]
    pv = [p[0] * v[0] + p[1] * v[1] for p in plot]
    c = g.centroid(leaf)
    cu, cv = c[0] * u[0] + c[1] * u[1], c[0] * v[0] + c[1] * v[1]
    return ((cu - min(pu)) / (max(pu) - min(pu)),
            (cv - min(pv)) / (max(pv) - min(pv)), g.area(leaf))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--draws", type=int, default=40, help="children per artefact")
    ap.add_argument("--regime", choices=("converged", "seeds"), default="converged",
                    help="parents: the committed corpus (late-run states), or freshly "
                         "constructed seeds (early-run states, where children often win)")
    ap.add_argument("--seeds", type=int, default=6, help="seeds per programme (--regime seeds)")
    args = ap.parse_args(argv)
    g.ORTHOGONAL_DIVISION = True
    weights = search_weights()

    groups = collections.defaultdict(lambda: collections.Counter())
    by_op = collections.defaultdict(collections.Counter)
    print("where each design's shaft sits (u, v as fractions of the plot rectangle):")
    for name in args.programme or PROGRAMMES:
        prog = REPO / "examples" / name
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]
        if args.regime == "seeds":
            sys.path.insert(0, str(REPO / "experiments"))
            from diag_3i3_missing_room import build_seed
            parents = [(f"seed{i}", build_seed(prog, i)) for i in range(args.seeds)]
        else:
            parents = [(q.name, dom.load(str(q))) for q in sorted(prog.glob(args.corpus))]
        for pname, parent in parents:
            p = Path(pname)
            dom.link(parent)
            g.clear_cache()
            paths = shafts(parent)
            if not paths:
                print(f"  {name}/{p.name}: NO intact shaft -- skipped")
                continue
            locs = [where(parent, s) for s in paths]
            print(f"  {name:16} {p.name.split('-s')[-1][:-4]:>3}: " + "; ".join(
                f"u {a:.2f} v {b:.2f} ({ar:.1f} m2)" for a, b, ar in locs))
            ratios = innerloop.ratio_map(parent)
            p_fit, p_fails = evaluate(parent, prog, ratios)
            # A stable hash of programme and file. This was `hash(p.name)`,
            # which Python salts per process: no two runs drew the same
            # children, so §39.88's table cannot be reproduced to the digit
            # (its conclusion does not rest on one).
            rng = np.random.default_rng(int.from_bytes(hashlib.blake2b(
                f"{name}/{p.name}".encode(), digest_size=8).digest(), "little"))
            for _ in range(args.draws):
                child, desc = operators.mutate(parent, rng, types, weights=weights,
                                               reqs=reqs)
                op = desc.split()[0]
                dom.link(child)
                g.clear_cache()
                kind = "kept" if shafts(child) else "emptied"
                c_fit, c_fails = evaluate(child, prog, ratios)
                st = groups[kind]
                st["n"] += 1
                st["beats parent"] += c_fit > p_fit
                st["fewer fails"] += c_fails < p_fails
                st["d fails"] += c_fails - p_fails
                if kind == "emptied":
                    by_op[op]["emptied"] += 1
                    by_op[op]["won"] += c_fit > p_fit
                by_op[op]["n"] += 1

    print(f"\nchildren drawn with the search's mutation mix, {args.draws} per artefact:")
    print(f"{'group':10} {'n':>5} {'share':>6} {'beat parent':>12} {'fewer fails':>12} {'mean d fails':>13}")
    total = sum(st["n"] for st in groups.values())
    for kind in ("kept", "emptied"):
        st = groups[kind]
        n = st["n"] or 1
        print(f"{kind:10} {st['n']:5d} {st['n'] / total:6.1%} {st['beats parent'] / n:12.1%} "
              f"{st['fewer fails'] / n:12.1%} {st['d fails'] / n:+13.2f}")
    print("\nwhich operators empty the shaft (share of that operator's draws):")
    for op, c in sorted(by_op.items(), key=lambda kv: -kv[1]["emptied"]):
        if c["emptied"]:
            print(f"  {op:28} {c['emptied']:3d} of {c['n']:3d}  ({c['emptied'] / c['n']:.0%})"
                  f"  won {c['won']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
