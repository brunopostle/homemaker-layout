"""Exposure / frontage diagnostic for the crinkliness residual.

Evidence for `homemaker-py-ssz` / `hxi` / `tdp` (DESIGN.md §38). Three reports,
none of which needs a search run:

1. ``exposure``  — decompose crinkliness failures into ZERO-EXPOSURE (the leaf
   has no daylit wall at all, so ``quality_uncrinkliness`` returns a hard 0.0
   and the leaf's whole quality product collapses to zero) vs. wrong-ratio
   (exposed, but off the uncrinkliness target). Run on constructed seeds under
   the driver's real default stack, or on a ``.dom`` from disk.

2. ``value``     — measure what a buried leaf is worth to the objective, by
   deleting one (undividing its parent) and re-scoring. Circulation/outside
   leaves carry no missing-space requirement, so nothing offsets their removal.

3. ``frontage``  — the closed-form feasibility bound. Crinkliness fails when
   ``1/crink > X`` with ``crink = L*h/A``, so every interior leaf needs exposed
   wall ``L >= A/(X*h)``; per storey that is ``A_storey/(X*h)`` metres. Compare
   against the daylit plot perimeter (``area_outside`` skips ``private`` and
   ``fortified`` edges) to get the deficit.

Usage::

    python experiments/diag_exposure_frontage.py frontage
    python experiments/diag_exposure_frontage.py exposure examples/harbor-house
    python experiments/diag_exposure_frontage.py exposure --dom out.dom examples/harbor-house
    python experiments/diag_exposure_frontage.py value examples/harbor-house
"""

from __future__ import annotations

import argparse
import copy
import math
from pathlib import Path

import numpy as np

from homemaker_layout import dom as dom_mod
from homemaker_layout import driver, fitness, geometry
from homemaker_layout import graph as graph_mod
from homemaker_layout import operators, programme

CORPUS = ["examples/harbor-house", "examples/maple-court",
          "examples/health-centre", "examples/programme-house"]


def fail_bounds() -> tuple[float, float]:
    """Solve ``gaussian(x, 1, 5/6, 1.1/3) == FAIL_THRESHOLD`` for x.

    Returns ``(buried_above, exposed_below)``: a leaf fails crinkliness when
    ``1/crink`` exceeds the first (too buried) or falls below the second (too
    exposed). Derived from the real constants, never hard-coded.
    """
    b, c = fitness.CONF_DEFAULTS["uncrinkliness"]
    k = math.sqrt(-2 * c * c * math.log(fitness.FAIL_THRESHOLD) / math.log(fitness._E))
    return b + k, b - k


def _fit(progdir: str) -> fitness.Fitness:
    """Evaluator configured exactly as ``driver.search`` builds it by default."""
    ov = driver._overrides_for(leaf_sharing=True, superpose=False, max_share=None,
                               conn_grade=False, collapse_insearch=True,
                               multi_use=False)
    conf, cost = fitness.load_config(progdir, overrides=ov)
    return fitness.Fitness(conf, cost)


def _seed(progdir: str, seed: int) -> dom_mod.Node:
    """One constructed seed under ``driver.search``'s own default arguments."""
    reqs = programme.load_programme_dir(progdir)
    return operators.constructive_topology(
        dom_mod.load(f"{progdir}/init.dom"), reqs, np.random.default_rng(seed),
        sorted(reqs) + ["C", "O"],
        min_storeys=programme.storey_minimum(progdir),
        adjacency_aware=True, proportion_aware=True, circ_divisor=3,
        leaf_sharing=True, leaf_share_factor=3, depth_balanced=True,
        interior_outside=True, outside_divisor=3)


def _exposure_rows(fit: fitness.Fitness, root: dom_mod.Node) -> list[tuple]:
    """Per interior/covered leaf: (level, id, type, area, exposed_area, quality).

    Reproduces the state ``_evaluate_full`` reaches at storey processing —
    in-search collapse, preprocess, merge — so the numbers match a real eval.
    """
    tree = copy.deepcopy(root)
    geometry.clear_cache()
    dom_mod.canonicalize_shares(tree)
    if fit._collapse_insearch:
        fit.collapse_global(tree, adjacency=True, objective="threshold",
                            preserve_public_access=True, iters=3)
    fit.preprocess_building(tree)
    dom_mod.merge_divided(tree)
    geometry.clear_cache()
    graphs = graph_mod.build_graphs(tree, fit.conf("door_width") or 1.2)

    rows = []
    for li, lvl in enumerate(dom_mod.levels(tree)):
        for leaf in lvl.leaves():
            if dom_mod.is_outside(leaf) and not dom_mod.is_covered(leaf):
                continue  # exempt by quality_uncrinkliness
            rows.append((li, leaf.id, leaf.type, geometry.area(leaf),
                         fit.area_outside(leaf, graphs[li], {}),
                         fit.quality_uncrinkliness(leaf, graphs[li], {})))
    return rows


def report_exposure(progdir: str, seeds: range, dom_path: str | None) -> None:
    fit = _fit(progdir)
    roots = ([dom_mod.load(dom_path)] if dom_path
             else [_seed(progdir, s) for s in seeds])
    ok = zero = ratio = 0
    n_fails = n_crink = 0
    for root in roots:
        _, fails = fit.score_with_fails(copy.deepcopy(root))
        n_fails += len(fails)
        n_crink += sum("crinkliness" in f for f in fails)
        for _, _, _, _, exposed, q in _exposure_rows(fit, root):
            if exposed == 0:
                zero += 1
            elif q < fitness.FAIL_THRESHOLD:
                ratio += 1
            else:
                ok += 1
    total = ok + zero + ratio
    label = dom_path or f"{len(roots)} constructed seeds"
    print(f"=== {progdir}  ({label})")
    print(f"  mean fails/design {n_fails / len(roots):.1f}, of which crinkliness "
          f"{n_crink / len(roots):.1f}")
    print(f"  interior leaves: ok={ok}  ZERO-EXPOSURE={zero}  wrong-ratio={ratio}")
    if total:
        print(f"  -> {100 * zero / total:.0f}% of interior leaves have NO daylit wall: "
              f"hard quality=0, unreachable by any ratio assignment")


def report_value(progdir: str, seed: int, limit: int) -> None:
    """What is a buried leaf worth? Delete one and re-score."""
    fit = _fit(progdir)
    root = _seed(progdir, seed)
    base_score, base_fails = fit.score_with_fails(copy.deepcopy(root))
    print(f"=== {progdir} seed {seed}: baseline score {base_score:.4g}, "
          f"{len(base_fails)} fails")

    buried = [(li, lid, typ) for li, lid, typ, _, exposed, _
              in _exposure_rows(fit, root) if exposed == 0]
    print(f"  {len(buried)} buried leaves; deleting each (undivide its parent):")

    tried = 0
    for li, lid, typ in buried:
        if tried >= limit:
            break
        cand = copy.deepcopy(root)
        lvls = dom_mod.levels(cand)
        if li >= len(lvls):
            continue
        node = lvls[li].by_id(lid)
        if node is None or node.parent is None:
            continue
        parent = node.parent
        if parent.below is not None and parent.below.divided:
            continue  # inherited cut, not owned here
        sibling = parent.right if parent.left is node else parent.left
        if sibling is None or sibling.divided:
            continue
        parent.division = None
        parent.left = parent.right = None
        parent.type = sibling.type
        dom_mod.link(cand)
        geometry.clear_cache()
        score, fails = fit.score_with_fails(copy.deepcopy(cand))
        tried += 1
        verdict = "BETTER" if score > base_score else "worse"
        print(f"    delete {lid:<8s} type={typ:<5s}: score x{score / base_score:>8.2f} "
              f"({verdict}), fails {len(base_fails)} -> {len(fails)}")


def frontage_budget(progdir: str) -> dict:
    """Feasibility of a programme on its plot, before any search runs.

    Two independent checks, in the order they bite:

    1. **Does the programme fit the plot at all?** ``demand / storeys`` against
       the plot area. health-centre asks for 240 m² on a 183 m² plot — 131% —
       and every room comes out at 0.60x its target no matter what the search
       does.
    2. **Is there enough daylit wall for the area it does demand?** Every
       interior leaf needs ``L >= A/(X*h)`` (§38.3), so a storey building
       ``A_built`` needs ``A_built/(X*h)`` metres. The plot's non-``private``
       perimeter supplies some; interior courtyard supplies the rest, at roughly
       ``2 * area / width`` metres per courtyard slot.

    NB this must be computed against the area the programme actually DEMANDS,
    not a fully built plot — see §39.11 for the correction.
    """
    root = dom_mod.load(f"{progdir}/init.dom")
    per = root.perimeter or {}
    height = root.height or 3.0
    # measured exactly as `Fitness.area_outside` does: an external boundary is
    # daylit unless its perimeter type is `private` or `fortified`. Going
    # through `geometry` rather than the raw YAML corners also picks up the
    # `wall_outer` inset and the plot rotation, so these are the metres and the
    # square metres the leaves actually get.
    daylit = sum(geometry.edge_length(root, e) for e in range(4)
                 if (per.get(geometry.boundary_id(root, e)) or "").lower()
                 not in ("private", "fortified"))
    plot = geometry.area(root)
    reqs = programme.load_programme_dir(progdir)
    storeys = max(programme.n_storeys_required(reqs),
                  programme.storey_minimum(progdir))
    demand = sum(r.size * r.count for r in reqs.values())
    built = demand / storeys
    x_buried, _ = fail_bounds()
    needed = built / (x_buried * height)
    gap = needed - daylit
    court = max(0.0, gap) * 3.0 / 2.0          # 3 m courtyard slots
    spare = plot - built
    return dict(plot=plot, daylit=daylit, height=height, storeys=storeys,
                demand=demand, built=built, needed=needed, gap=gap,
                court=court, spare=spare,
                fits_plot=built <= plot,
                frontage_ok=court <= spare)


def report_frontage(progdirs: list[str]) -> None:
    x_buried, x_exposed = fail_bounds()
    print(f"crinkliness fails when 1/crink > {x_buried:.4f} (buried) "
          f"or < {x_exposed:.4f} (over-exposed)")
    print(f"=> every interior leaf needs exposed wall L >= A / ({x_buried:.4f} * h)\n")

    for progdir in progdirs:
        b = frontage_budget(progdir)
        print(f"=== {Path(progdir).name}")
        print(f"  plot {b['plot']:.0f} m2, daylit perimeter {b['daylit']:.0f} m, "
              f"{b['storeys']} storeys, h={b['height']:g}")
        pct = 100 * b["built"] / b["plot"]
        verdict = "OK" if b["fits_plot"] else "DOES NOT FIT THE PLOT"
        print(f"  1. programme demands {b['demand']:.0f} m2 -> {b['built']:.0f} m2 "
              f"per storey = {pct:.0f}% of the plot   [{verdict}]")
        print(f"  2. that needs {b['needed']:.0f} m of daylit wall; perimeter gives "
              f"{b['daylit']:.0f} m -> gap {b['gap']:+.0f} m")
        if b["gap"] > 0:
            print(f"     closing it takes ~{b['court']:.0f} m2 of 3 m courtyard; "
                  f"spare plot {b['spare']:.0f} m2   "
                  f"[{'OK' if b['frontage_ok'] else 'NOT ENOUGH ROOM'}]")
        else:
            print("     perimeter alone is sufficient")
        print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", choices=("exposure", "value", "frontage"))
    ap.add_argument("progdir", nargs="?", default=None)
    ap.add_argument("--dom", default=None, help="score this .dom instead of seeds")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--limit", type=int, default=5, help="deletions to try (value)")
    args = ap.parse_args()

    if args.report == "frontage":
        report_frontage([args.progdir] if args.progdir else CORPUS)
    elif args.report == "exposure":
        for d in ([args.progdir] if args.progdir else CORPUS):
            report_exposure(d, range(args.seeds), args.dom)
    else:
        report_value(args.progdir or CORPUS[0], seed=0, limit=args.limit)


if __name__ == "__main__":
    main()
