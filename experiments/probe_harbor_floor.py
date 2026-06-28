#!/usr/bin/env python3
"""High-budget harbor-house floor probe on the CURRENT full default stack
(homemaker-py-71d.1).

Decides 71d (failure-directed repair operator) go/no-go. 71d's premise: the
harbor 3M-eval plateau (27 fails, 3m.dom) is dominated by LANDLOCKED crinkliness
(leaf area_outside==0 -> crink==0 -> quality_uncrinkliness hits the
`if not crink: return 0.0` branch, fitness.py:355 -> guaranteed fail for ALL
ratios), fixable only by topology (interior O courtyards). That fix
(interior_outside, odiv=3) has since shipped DEFAULT-ON (erc.8, §13.6). So:
re-run harbor at high budget on the full default stack and split the residual
crinkliness fails into LANDLOCKED (area_outside==0, 71d's target) vs
UNDER-EXPOSED (0 < crink < target, reachable by ratios/seeding). If landlocked
still dominates -> 71d worth it; if interior-O dissolved it -> 71d redundant.

Run SERIAL (n_workers=1) — the leaf-share relaxed objective is injected by
monkeypatching fitness.load_config, which does NOT propagate into
ProcessPoolExecutor workers (they re-import fitness fresh, scoring strict ->
fail-count MISMATCH). The whole §13.x ladder was run serial for this reason.
  URB_NO_OCCLUSION=1 python3 experiments/probe_harbor_floor.py [budget] [seed]
Defaults: budget=1_000_000, seed=0.  Serial ~84 ev/s => 1M ~ 3.3 h.
"""
from __future__ import annotations

import copy
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, driver, fitness, geometry  # noqa: E402
from homemaker_layout import graph as graph_mod  # noqa: E402
from homemaker_layout import dom as dom_mod  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
HARBOR = REPO / "examples" / "harbor-house"


def classify_crinkliness(root, conf, cost):
    """For the scored (merged) tree, return per-crinkliness-fail leaf classes.

    Mirrors _evaluate_full Phase-2 graph setup so area_outside matches what the
    evaluator saw. Returns (fails, classes) where classes maps
    'level/leafid' -> ('landlocked'|'under-exposed', crink, area_outside, type).
    """
    fit = fitness.Fitness(conf, cost)
    # score_with_fails merges the tree in place and yields canonical fails
    score, fails = fit.score_with_fails(copy.deepcopy(root))

    # Re-derive the merged tree + base graphs exactly as the evaluator does,
    # so area_outside/crinkliness reproduce the scored values.
    work = copy.deepcopy(root)
    fit2 = fitness.Fitness(conf, cost)
    fit2.preprocess_building(work)
    geometry.clear_cache()
    dom_mod.merge_divided(work)
    geometry.clear_cache()
    door_w = fit2.conf("door_width") or 1.2
    graph_base = graph_mod.build_graphs(work, door_w)
    lvls = dom_mod.levels(work)

    leaf_metric = {}  # 'level/id' -> (crink, area_outside, type)
    for li, lvl in enumerate(lvls):
        G = graph_base[li]
        groups = geometry.boundary_groups(lvl)
        for leaf in lvl.leaves():
            if not dom_mod.is_usable(leaf):
                continue
            if dom_mod.is_outside(leaf) and not dom_mod.is_covered(leaf):
                continue  # the O leaves themselves are exempt (quality 1.0)
            ao = fit2.area_outside(leaf, G, groups)
            crink = fit2.crinkliness(leaf, G, groups)
            leaf_metric[f"{li}/{leaf.id}"] = (crink, ao, leaf.type or "")

    classes = {}
    for f in fails:
        if not f.endswith(" crinkliness"):
            continue
        key = f[: -len(" crinkliness")]
        crink, ao, ltype = leaf_metric.get(key, (None, None, "?"))
        if ao is None:
            cls = "unknown"
        elif ao <= 1e-9:
            cls = "landlocked"
        else:
            cls = "under-exposed"
        classes[key] = (cls, crink, ao, ltype)
    return score, fails, classes


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    out = REPO / "scratch" / "harbor_floor_probe" / f"harbor_fullstack_s{seed}.dom"
    out.parent.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("URB_NO_OCCLUSION", "1")

    # Full default stack, leaf-share config injected into the WHOLE pipeline so
    # the search and the re-score share one relaxed objective (§13.3), matching
    # how every §13.x floor number was produced.
    _orig_load = fitness.load_config

    def _load_with_sharing(directory, overrides=None):
        conf, cost = _orig_load(directory, overrides=overrides)
        conf = dict(conf)
        conf["leaf_sharing"] = True
        conf["max_share"] = 3
        return conf, cost

    fitness.load_config = _load_with_sharing
    conf, cost = fitness.load_config(HARBOR)

    seed_root = dom.load(str(HARBOR / "init.dom"))
    print(f"=== harbor floor probe: budget={budget} seed={seed} serial ===",
          flush=True)
    print("stack: leaf_sharing(3) + depth_balanced + interior_outside(odiv=3) "
          "+ circ_divisor=3 + proportion-aware (current defaults)", flush=True)
    t0 = time.perf_counter()

    r = driver.search_staged(
        seed_root, HARBOR,
        budget=budget, pop_size=16, child_budget=80, seed_budget=300,
        stage1_frac=0.4, base_p=0.15, p_crossover=0.2, seed=seed,
        log=lambda m: print(m, flush=True),
        seed_adjacency_aware=True, seed_proportion_aware=True,
        circ_divisor=3,
        leaf_sharing=True, leaf_share_factor=3,
        depth_balanced=True,
        interior_outside=True, outside_divisor=3,
    )
    elapsed = time.perf_counter() - t0
    print(f"\n--- done in {elapsed:.0f}s ({r.n_evals/elapsed:.1f} ev/s), "
          f"{r.n_evals} evals across {r.n_topologies} topologies ---", flush=True)
    print(f"best: {r.best.fitness:.6g} ({r.best.n_fails} fails) via {r.best.lineage}",
          flush=True)

    dom.dump(r.best.root, str(out))

    score, fails, classes = classify_crinkliness(r.best.root, conf, cost)
    ok = math.isclose(score, r.best.fitness, rel_tol=1e-9)
    print(f"\nre-scored: {score:.6g} ({len(fails)} fails) "
          f"{'OK' if ok else 'MISMATCH'}", flush=True)

    # Fail-type histogram (last token of each fail string).
    types = Counter(f.split()[-1] if " " in f else f for f in fails)
    print("\nfail-type histogram:", flush=True)
    for t, n in types.most_common():
        print(f"  {n:3d}  {t}", flush=True)

    # Crinkliness landlocked split — the 71d decision metric.
    cls_count = Counter(v[0] for v in classes.values())
    n_crink = len(classes)
    print(f"\ncrinkliness fails: {n_crink} total", flush=True)
    for c in ("landlocked", "under-exposed", "unknown"):
        if cls_count.get(c):
            print(f"  {cls_count[c]:3d}  {c}", flush=True)
    print("\nper-crinkliness-leaf detail (key | class | crink | area_outside | type):",
          flush=True)
    for key, (cls, crink, ao, ltype) in sorted(classes.items()):
        cs = f"{crink:.3f}" if crink is not None else "?"
        aos = f"{ao:.2f}" if ao is not None else "?"
        print(f"  {key:18s} {cls:13s} crink={cs:>7s} ao={aos:>7s} type={ltype}",
              flush=True)

    landlocked = cls_count.get("landlocked", 0)
    print(f"\nVERDICT INPUT: {landlocked}/{n_crink} crinkliness fails are "
          f"LANDLOCKED (71d's ratio-invariant target); total fails {len(fails)}.",
          flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
