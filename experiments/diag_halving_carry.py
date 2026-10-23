"""Did a seeded run keep its seed's plan? (homemaker-py-2g7.13.1.2, DESIGN.md §39.151)

Rasterises each storey into built (room, circulation, stair) and unbuilt
(outside, sahn) on an 80 x 80 grid over the plot, and reports the fraction of
points on which the given design agrees with every halving seed, the
footprint seeds and hand2a where the programme has them, and the cold 4428262+orth runs. The cold runs are the
control: what agreement looks like with no common ancestry.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_halving_carry.py experiments/results/halving-harbor/winner-total.dom
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_halving_carry.py experiments/results/halving-maple/winner.dom --programme maple-court
"""
import glob, sys
import numpy as np
from matplotlib.path import Path as MP
from homemaker_layout import dom, geometry

def raster(path, n=80):
    r = dom.load(path); dom.link(r); geometry.clear_cache()
    L = dom.levels(r)
    pts = None; out = []
    for lvl in L:
        leaves = lvl.leaves()
        polys = [(lf, [tuple(p[:2]) for p in geometry.quad_corners(lf)]) for lf in leaves]
        if pts is None:
            xs = [x for _, P in polys for x, _ in P]; ys = [y for _, P in polys for _, y in P]
            gx, gy = np.meshgrid(np.linspace(min(xs), max(xs), n), np.linspace(min(ys), max(ys), n))
            pts = np.c_[gx.ravel(), gy.ravel()]
        lab = np.zeros(len(pts), int)  # 0 none, 1 outside, 2 indoor circ, 3 room
        for lf, P in polys:
            m = MP(P).contains_points(pts)
            t = lf.type or ""
            lab[m] = 1 if t in ("O", "S") else 2 if t in ("C", "E") else 3
        out.append(lab)
    return out

def agree(a, b):
    k = min(len(a), len(b))
    built = lambda l: l >= 2
    s = [np.mean(built(a[i]) == built(b[i])) for i in range(k)]
    return float(np.mean(s))

import argparse, os
ap = argparse.ArgumentParser()
ap.add_argument("design")
ap.add_argument("--programme", default="harbor-house")
ap.add_argument("--cold", default="4428262+orth", help="stamp of the cold runs used as the control")
ap.add_argument("--seeds-dir", help="the race's own seeds (every *.dom but cold-*/winner); "
                "default the programme's first halving, experiments/results/halving-<short>/halv-*.dom")
a = ap.parse_args()
prog = a.programme
if a.seeds_dir:
    seeds = sorted(f for f in glob.glob(f"{a.seeds_dir}/*.dom")
                   if not os.path.basename(f).startswith(("cold-", "winner")))
else:
    halv = {"harbor-house": "halving-harbor", "maple-court": "halving-maple"}[prog]
    seeds = sorted(glob.glob(f"experiments/results/{halv}/halv-*.dom"))
W = raster(a.design)
rows = []
for p in seeds + \
         sorted(glob.glob(f"examples/{prog}/footprint-s*.dom")) + \
         [f for f in [f"examples/{prog}/hand2a.dom"] if os.path.exists(f)] + \
         sorted(glob.glob(f"examples/{prog}/coldstart-{a.cold}-500000-s*.dom")):
    rows.append((agree(W, raster(p)), p.split("/")[-1]))
rows.sort(reverse=True)
for a, n in rows[:6]: print(f"  {a:.3f} {n}")
print("  ...")
for a, n in rows:
    if "coldstart" in n: print(f"  {a:.3f} {n}  (control: a cold run's final)")
print(f"median over all {len(rows)}: {np.median([a for a,_ in rows]):.3f}")
