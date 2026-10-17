"""Did a successive-halving run move a stair? (homemaker-py-2g7.13.1.2, expectation 4)

No operator relocates a shaft (DESIGN.md §39.146), so a halving survivor's
stairs should stand where its seed put them. Comparing id paths is not enough:
a path can survive while a ratio slides its cell across the plan. So, for every
candidate a halving work dir carried to its last stage, this lists each shaft
in the ORIGINAL seed (stage 0's seed.dom) and in the final out.dom by path and
by ground-cell centroid, and reports how far the nearest final shaft lies from
each seed shaft.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_halving_stairs.py ~/halving-harbor-total
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_halving_stairs.py --self-test

`--self-test` is the negative control: it moves a seed's stair by hand (swaps
the two children of each shaft's parent on every storey) and requires the
report to see it.
"""
import argparse
import copy
import math
import os
import sys
from pathlib import Path

from homemaker_layout import dom, geometry, operators


def shafts(root):
    """{path: (x, y)} -- every shaft's ground-cell centroid."""
    dom.link(root)
    geometry.clear_cache()
    lvls = dom.levels(root)
    out = {}
    for p in operators._shaft_paths(lvls):
        leaf = next(n for n in lvls[0].leaves() if n.id == p)
        c = geometry.centroid(leaf)
        out[p] = (c[0], c[1])
    return out


def compare(seed_root, final_root):
    """[(seed path, final path or None, distance m)] for each seed shaft."""
    a, b = shafts(seed_root), shafts(final_root)
    rows = []
    for p, xy in a.items():
        if not b:
            rows.append((p, None, math.inf))
            continue
        q = min(b, key=lambda k: math.dist(xy, b[k]))
        rows.append((p, q, math.dist(xy, b[q])))
    return rows, len(a), len(b)


def report(work):
    work = Path(work).expanduser()
    stages = sorted((d for d in work.iterdir() if d.is_dir() and d.name[:1] == "s"
                     and d.name[1:].isdigit()), key=lambda d: int(d.name[1:]))
    last = stages[-1]
    print(f"{work}: last stage {last.name}")
    moved = 0
    for cand in sorted(d.name for d in last.iterdir() if (d / "out.dom").exists()):
        seed = stages[0] / cand / "seed.dom"
        rows, na, nb = compare(dom.load(str(seed)), dom.load(str(last / cand / "out.dom")))
        far = [r for r in rows if r[2] > 1.0]
        moved += bool(far) or na != nb
        print(f"  {cand}: {na} shafts in seed, {nb} at the end"
              + ("" if not far and na == nb else "   <-- MOVED"))
        for p, q, d in rows:
            print(f"      {p or '(root)'} -> {q if q is not None else '-'}  {d:.2f} m")
    print(f"{moved} candidate(s) with a stair moved more than 1 m, or a shaft gained or lost")
    return moved


def self_test():
    path = "examples/harbor-house/hand2a.dom"
    root = dom.load(path)
    rows, na, nb = compare(dom.load(path), copy.deepcopy(root))
    assert na and all(d < 1e-9 for _, _, d in rows), rows
    # move every stair: swap the children of each shaft's parent, every storey
    moved = copy.deepcopy(root)
    dom.link(moved)
    lvls = dom.levels(moved)
    paths = operators._shaft_paths(lvls)
    for lvl in lvls:
        for p in paths:
            par = _find(lvl, p[:-1])
            if par is not None and par.left is not None:
                par.left, par.right = par.right, par.left
    rows, _, _ = compare(dom.load(path), moved)
    assert any(d > 1.0 for _, _, d in rows), f"control did not fire: {rows}"
    print("self-test passed: an unmoved copy reads 0 m, a hand-moved stair reads",
          ", ".join(f"{d:.1f} m" for _, _, d in rows))


def _find(node, path):
    if node is None:
        return None
    if node.id == path:
        return node
    return _find(node.left, path) or _find(node.right, path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("work", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if os.environ.get("HOMEMAKER_ORTHOGONAL_DIVISION") != "1":
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1: the halving ran at +orth")
    if a.self_test:
        self_test()
    for w in a.work:
        report(w)
