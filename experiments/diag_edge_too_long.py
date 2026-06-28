#!/usr/bin/env python3
"""Dissect the edge-too-long fails in the harbor probe best (§13.7 follow-up).

Tests three hypotheses for why edge-too-long is now harbor's top fail class:
  (1) COMBINED leaf  — a shared leaf (share>1) holds k rooms, so it is ~k× a
      room's area and its walls run long; would vanish if actually subdivided.
  (2) CORRIDOR       — a circulation leaf, long+thin; long edge inevitable.
  (3) NARROW ROOM    — a non-shared room at/near target AREA but high aspect
      (one wall >8m because the room is too narrow); a real layout problem.
  (4) OVERSIZE ROOM  — a non-shared room well above target area.

For each flagged leaf prints: type, circ?, share k, area vs (k×)target,
narrowest width, the long edge length(s), aspect, and a verdict tag.
"""
from __future__ import annotations
import copy, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, fitness, geometry  # noqa: E402
from homemaker_layout import graph as graph_mod  # noqa: E402
from homemaker_layout import dom as dom_mod  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
HARBOR = REPO / "examples" / "harbor-house"
BEST = REPO / "scratch" / "harbor_floor_probe" / "harbor_fullstack_s0.dom"

# same relaxed-config injection the probe used, so fails match
_orig = fitness.load_config
def _load(d, overrides=None):
    c, k = _orig(d, overrides=overrides); c = dict(c)
    c["leaf_sharing"] = True; c["max_share"] = 3
    return c, k
fitness.load_config = _load
conf, cost = fitness.load_config(HARBOR)
fit = fitness.Fitness(conf, cost)

root = dom.load(str(BEST))
score, fails = fit.score_with_fails(copy.deepcopy(root))
edge_fails = [f for f in fails if "edge too long" in f]
print(f"{BEST.name}: {len(fails)} fails, {len(edge_fails)} edge-too-long\n")
for f in edge_fails:
    print("  ", f)
print()

# rebuild merged tree + base graphs exactly as _evaluate_full does
work = copy.deepcopy(root)
fit2 = fitness.Fitness(conf, cost)
fit2.preprocess_building(work)
geometry.clear_cache(); dom_mod.merge_divided(work); geometry.clear_cache()
door_w = fit2.conf("door_width") or 1.2
graph_base = graph_mod.build_graphs(work, door_w)
lvls = dom_mod.levels(work)
by_id = {}  # 'level/id' -> (leaf, level)
for li, lvl in enumerate(lvls):
    for leaf in lvl.leaves():
        by_id[f"{li}/{leaf.id}"] = (leaf, li)

def edges(leaf):
    return [geometry.edge_length(leaf, e) for e in range(4)]

def t0(leaf):
    return (leaf.type or "?")[0].lower()

def target_area(leaf):
    try:
        p = fit2.get_space_params(leaf.type, "size")
        return p[0]
    except Exception:
        return None

def describe(leaf, li):
    ty = leaf.type or "?"
    circ = dom_mod.is_circulation(leaf)
    out = dom_mod.is_outside(leaf)
    share = graph_mod.leaf_share(leaf, 3)
    area = geometry.area(leaf)
    narrow = geometry.length_narrowest(leaf)
    es = edges(leaf)
    longest = max(es)
    aspect = longest / narrow if narrow else float("inf")
    tgt = target_area(leaf)
    ke = share if share > 1 else 1
    tgt_eff = (tgt * ke) if tgt else None
    # classify
    if share > 1:
        tag = f"COMBINED (share={share})"
    elif circ:
        tag = "CORRIDOR (circulation)"
    elif tgt and area >= 0.85 * tgt and aspect > 1.8:
        tag = "NARROW ROOM (area ok, aspect bad)"
    elif tgt and area > 1.3 * tgt:
        tag = "OVERSIZE ROOM"
    else:
        tag = "other"
    ts = f"{tgt:.0f}" if tgt else "n/a"
    tes = f"{tgt_eff:.0f}" if tgt_eff else "n/a"
    print(f"    {li}/{leaf.id:10s} type={ty:5s} circ={int(circ)} out={int(out)} "
          f"share={share}  area={area:5.1f} (tgt {ts}, k*tgt {tes})")
    print(f"       narrowest={narrow:4.1f}  edges={[round(x,1) for x in es]}  "
          f"longest={longest:4.1f}  aspect={aspect:4.1f}  -> {tag}")
    return tag

tags = []
seen = set()
for f in edge_fails:
    outside = "outside edge too long" in f
    parts = f.split()
    key = parts[0]  # 'level/id'
    if outside:
        ent = by_id.get(key)
        if ent:
            tags.append(describe(*ent))
    else:
        # '{level}/{a.id} {b.id} edge too long' — both leaves border the long wall
        li_a = key
        b_id = parts[1]
        li = li_a.split("/")[0]
        for k in (li_a, f"{li}/{b_id}"):
            if k in by_id and k not in seen:
                seen.add(k)
                tags.append(describe(*by_id[k]))

print("\n=== classification tally ===")
from collections import Counter
for tag, n in Counter(tags).most_common():
    print(f"  {n:2d}  {tag}")
