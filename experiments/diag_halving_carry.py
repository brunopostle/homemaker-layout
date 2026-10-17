"""Did a seeded run keep its seed's plan? (homemaker-py-2g7.13.1.2, DESIGN.md §39.151)

Rasterises each storey into built (room, circulation, stair) and unbuilt
(outside, sahn) on an 80 x 80 grid over the plot, and reports the fraction of
points on which the given design agrees with every halving seed, the
footprint seeds, hand2a and the cold 4428262+orth runs. The cold runs are the
control: what agreement looks like with no common ancestry.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_halving_carry.py experiments/results/halving-harbor/winner-total.dom
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

W = raster(sys.argv[1])
rows = []
for p in sorted(glob.glob("experiments/results/halving-harbor/halv-*.dom")) + \
         sorted(glob.glob("examples/harbor-house/footprint-s*.dom")) + ["examples/harbor-house/hand2a.dom"] + \
         sorted(glob.glob("examples/harbor-house/coldstart-4428262+orth-500000-s*.dom")):
    rows.append((agree(W, raster(p)), p.split("/")[-1]))
rows.sort(reverse=True)
for a, n in rows[:6]: print(f"  {a:.3f} {n}")
print("  ...")
for a, n in rows:
    if "coldstart" in n: print(f"  {a:.3f} {n}  (control: a cold run's final)")
print(f"median over all {len(rows)}: {np.median([a for a,_ in rows]):.3f}")
