"""The measurement behind every fail of a hand-drawn design (`homemaker-py-2g7.2`,
DESIGN.md §39.137).

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_2g72_hand_fails.py [hand2a.dom]

For each failing cell: its plot sides and their status, every neighbour with
the width of wall they share (and whether that is a door's width), the wall
that gives it daylight, and the daylight factor against its target. Then the
same design with every storey at 3.0 m, listing each lit room whose daylight
factor is under 0.6 -- which is where a single-aspect room of ordinary depth
shows. Reads the design; writes nothing.
"""

import copy
import sys
from pathlib import Path

from homemaker_layout import dom, geometry, graph
from homemaker_layout import fitness as F
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parents[1]
prog = REPO / "examples" / "harbor-house"
name = sys.argv[1] if len(sys.argv) > 1 else "hand2a.dom"
fit = Fitness(*load_config(prog))


def load(height=None):
    root = dom.load(str(prog / name))
    dom.link(root)
    if height:
        for lvl in dom.levels(root):
            lvl.height = height
    geometry.clear_cache()
    return root


def lit_wall(lf, G, groups):
    return fit.area_outside(lf, G, groups) / F._height(lf)


# ---- every failing cell, as committed
root = load()
score, fails = fit.score_with_fails(copy.deepcopy(root))
print(f"{name}: score {score:.6g}, {len(fails)} fails")
print(f"daylight target {fit.conf('uncrinkliness')}, shape {fit._crinkliness_shape}; "
      f"width: circulation {fit.conf('width_circulation')}, outside {fit.conf('width_outside')}; "
      f"door {graph.DOOR_WIDTH} m; a factor under {F.FAIL_THRESHOLD} fails")
failing: dict = {}
for f in fails:
    head = f.split()[0]
    if "/" in head:
        failing.setdefault(head, []).append(" ".join(f.split()[1:]))
for li, lvl in enumerate(dom.levels(root)):
    G = geometry.leaf_graph(lvl, graph.DOOR_WIDTH)
    G0 = geometry.leaf_graph(lvl, 0.01)        # every contact, however short
    groups = geometry.boundary_groups(lvl)
    for lf in lvl.leaves():
        key = f"{li}/{lf.id}"
        if key not in failing:
            continue
        a, b = geometry.usable_rectangle(lf)
        print(f"\n== {key} {lf.type}: {geometry.area(lf):.1f} m2, {min(a, b):.2f} x {max(a, b):.2f}, "
              f"storey {F._height(lf):.2f} m -- {', '.join(failing[key])}")
        per = F._perimeter(lf)
        sides = [(bid, per.get(bid) or "street / open", round(geometry.edge_length(lf, e), 2))
                 for e in range(geometry.n_edges(lf))
                 for bid in [geometry.boundary_id(lf, e)] if geometry.is_external(bid)]
        print("   plot sides:", sides or "none")
        for nb in sorted(G0.neighbors(lf), key=lambda n: -G0[lf][n]["width"]):
            print(f"   beside {nb.type:<4} {nb.id:<11} {G0[lf][nb]['width']:5.2f} m"
                  + ("" if G.has_edge(lf, nb) else "  (too short for a door)")
                  + ("" if dom.is_usable(nb) else "  (not usable)"))
        c = fit.crinkliness(lf, G, groups)
        print(f"   lit wall {lit_wall(lf, G, groups):.2f} m; floor per metre of it, over the storey "
              f"height: {1 / c if c else float('inf'):.2f}; target {fit.crinkliness_params(lf)}; "
              f"factor {fit.quality_uncrinkliness(lf, G, groups):.3g}")
print("\nnot against a cell:", [f for f in fails if "/" not in f.split()[0]])

# ---- the same design as committed, then with every storey at 3.0 m
for height in (None, 3.0):
    root = load(height)
    score, fails = fit.score_with_fails(copy.deepcopy(root))
    print(f"\nstoreys {[round(lvl.height, 2) for lvl in dom.levels(root)]}: {len(fails)} fails, "
          f"score {score:.3g}; daylight fails: {[f.split()[0] for f in fails if 'crinkliness' in f]}")
    for li, lvl in enumerate(dom.levels(root)):
        G = geometry.leaf_graph(lvl, graph.DOOR_WIDTH)
        groups = geometry.boundary_groups(lvl)
        for lf in lvl.leaves():
            if fit.crinkliness_params(lf) is None or (dom.is_outside(lf) and not dom.is_covered(lf)):
                continue
            c = fit.crinkliness(lf, G, groups)
            q = fit.quality_uncrinkliness(lf, G, groups)
            if c and q < 0.6:
                lit = lit_wall(lf, G, groups)
                print(f"   {li}/{lf.id:<11} {lf.type:<4} {geometry.area(lf):5.1f} m2, lit wall {lit:5.2f} m, "
                      f"{geometry.area(lf) / lit:5.2f} m of floor behind each metre of it "
                      f"(/ height = {1 / c:4.2f}): factor {q:.3f}" + ("  FAIL" if q < F.FAIL_THRESHOLD else ""))
geometry.clear_cache()
