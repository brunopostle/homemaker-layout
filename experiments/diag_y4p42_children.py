"""Does a CHILD gain from tuning storey heights in its 80 evaluations?
(`homemaker-py-y4p4.2`, DESIGN.md §39.128)

`diag_y4p42_heights.py` gives one design thousands of evaluations. A search
gives a child eighty, and every extra variable is one more evaluation Nelder-
Mead spends building its simplex before it moves (§39.109). So, on the
children of §39.109/§39.110 -- the search's own mutation mix on the twelve
`1a24b6a+orth` designs -- the same child tuned twice by `driver._evaluate`:
as today, and with one height per storey added. Paired through `ab_report`.

What it cannot say is whether a search ends better: heights are INHERITED, so
a population can raise a storey a little at a time over generations, which a
single child from a 3.0 m parent does not show. That is the box.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 PYTHONPATH=src \\
        python experiments/diag_y4p42_children.py [--draws 8]
"""

from __future__ import annotations

import argparse
import collections
import copy
import importlib.util
import sys
from pathlib import Path

from homemaker_layout import dom, driver, geometry

REPO = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    loop = _load("diag_8b2u20_local_loop")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="coldstart-1a24b6a+orth-500000-s*.dom")
    ap.add_argument("--programme", action="append", choices=loop.PROGRAMMES)
    ap.add_argument("--draws", type=int, default=8)
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    shaft, ab = _load("diag_8b2u_fixed_shaft"), _load("ab_report")
    weights, search = shaft.search_weights(), shaft.SEARCH

    def tuned(child, prog, x0, kw):
        root = copy.deepcopy(child)
        dom.link(root)
        geometry.clear_cache()
        ind, _ = driver._evaluate(root, str(prog), x0, 80, kw, "y4p42", **search)
        crink = sum("crinkliness" in f for f in ind.fails) if hasattr(ind, "fails") else None
        return ind.n_fails, ind.fitness, [round(l.height, 2) for l in dom.levels(root)], crink

    rows = []
    for name, p, prog, parent, child, op, x0 in loop.children(a, weights):
        row = {"programme": name, "op": op, "cuts": len(x0),
               "today": tuned(child, prog, x0, {}),
               "heights": tuned(child, prog, x0, {"heights": True})}
        rows.append(row)
        print(f"  {name}/{p.name[-8:-4]} {op:<16} cuts {len(x0):2d}  today {row['today'][0]}  "
              f"heights {row['heights'][0]} {row['heights'][2]}", file=sys.stderr, flush=True)

    ops = collections.Counter(r["op"] for r in rows)
    print(f"\n{len(rows)} children ({a.draws} per design, {a.corpus})")
    print("operators drawn: " + ", ".join(f"{k} {v}" for k, v in ops.most_common()))
    moved = sum(any(abs(h - 3.0) > 0.005 for h in r["heights"][2]) for r in rows)
    hs = [h for r in rows for h in r["heights"][2]]
    print(f"children whose loop moved a height: {moved} of {len(rows)}; "
          f"heights it left: {min(hs):.2f} to {max(hs):.2f} m, mean {sum(hs) / len(hs):.2f}")
    for g in ("ALL", *dict.fromkeys(r["programme"] for r in rows)):
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        if len(sel) < 2:
            continue
        better = sum(r["heights"][1] > r["today"][1] for r in sel)
        worse = sum(r["heights"][1] < r["today"][1] for r in sel)
        print(f"\n== {g}: {len(sel)} children; score higher with heights on {better}, "
              f"lower on {worse}\nfails, paired (a W is `heights` LOWER):")
        print(ab.format_report(ab.paired_report(
            [float(r["today"][0]) for r in sel], [float(r["heights"][0]) for r in sel],
            "today", "heights")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
