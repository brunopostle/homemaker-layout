"""`homemaker-py-3tzk`, the search side: which operators move a wall upstairs
by removing the cut beneath it?

An upper-storey node inherits its cut from the storey below and stores a ratio
of its own that is ignored meanwhile (DESIGN.md §39.94). §39.96 stopped
`merge_divided` reviving that ratio when it fuses two outdoor cells. But any
OPERATOR that undivides a lower node does the same thing to a live tree: the
node above, untouched by the operator, stops inheriting and cuts wherever its
stale ratio says.

The census pattern (CLAUDE.md): every operator applied to every `+orth`
coldstart artefact, `--draws` times. An EVENT is a divided upper node, present
in parent and child with its stored ratio unchanged, whose node below was
divided in the parent and is not in the child. It MOVED if its cut end is more
than a millimetre from where it was.

READ THE RESULT WITH TWO CAUTIONS (DESIGN.md §39.98).

* `--raw` matters. `genome.decode` synchronises every inherited node's stored
  ratio with the one it inherits, so a tree that has been through the genome
  has no stale ratios and nothing moves. The live search never does that
  round trip -- `driver` uses only `genome.signature` -- and the artefacts it
  writes carry stale ratios in 180 of 192 files. `--raw` applies the operators
  to trees as loaded, which is the state the search holds them in.
* `reassociate`, `swap` and `ruin_recreate` score high for a different reason:
  they restructure the lower storey, so the same PATH names a different piece
  of floor afterwards. That is the operator doing its job, not a stale ratio.
  The rows that mean what this tool is for are `undivide` and `deslim`.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_3tzk_operator_walls.py --raw
"""

from __future__ import annotations

import argparse
import inspect
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, genome, geometry, operators, programme  # noqa: E402
from homemaker_layout.fitness import Fitness, load_config  # noqa: E402

RAW = False
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")


def upper_cuts(root) -> dict:
    """{(storey, path): (stored ratio, below divided?, cut end)} for every
    divided node above the ground floor."""
    out = {}
    geometry.clear_cache()
    for li, lvl in enumerate(dom.levels(root)):
        if not li:
            continue
        stack = [lvl]
        while stack:
            n = stack.pop()
            if not n.divided:
                continue
            out[(li, n.id)] = (tuple(n.division),
                               n.below is not None and n.below.divided,
                               tuple(geometry.coord_a(n)))
            stack += [n.left, n.right]
    geometry.clear_cache()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--draws", type=int, default=8)
    ap.add_argument("--raw", action="store_true",
                    help="apply operators to the tree as loaded from the file, "
                         "not after a genome round trip")
    ap.add_argument("--only", action="append")
    args = ap.parse_args(argv)
    global RAW
    RAW = args.raw
    geometry.ORTHOGONAL_DIVISION = True
    stats = defaultdict(lambda: {"n": 0, "applied": 0, "events": 0, "moved": 0,
                                 "children": 0, "dist": []})
    for name in PROGRAMMES:
        prog = REPO / "examples" / name
        conf, cost = load_config(prog)
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]
        fit = Fitness(conf, cost)
        for path in sorted(prog.glob("coldstart-*+orth-500000-s*.dom")):
            root = dom.load(str(path))
            if not RAW:
                root = genome.decode(genome.encode(root))
            before = upper_cuts(root)
            for op_name in sorted(args.only or operators.MUTATIONS):
                op = operators.MUTATIONS[op_name]
                params = inspect.signature(op).parameters
                kw = {k: v for k, v in (("reqs", reqs), ("fit", fit)) if k in params}
                for seed in range(args.draws):
                    row = stats[op_name]
                    row["n"] += 1
                    geometry.clear_cache()
                    try:
                        child, desc = op(root, np.random.default_rng(seed), types, **kw)
                    except Exception:                      # noqa: BLE001
                        continue
                    if "noop" in desc:
                        continue
                    row["applied"] += 1
                    after = upper_cuts(child)
                    hit = False
                    for key, (ratio, inherited, end) in before.items():
                        now = after.get(key)
                        if now is None or not inherited or now[1] or now[0] != ratio:
                            continue
                        row["events"] += 1
                        d = math.dist(end, now[2])
                        if d > 1e-3:
                            row["moved"] += 1
                            row["dist"].append(d)
                            hit = True
                    row["children"] += hit
    print(f"{'operator':20} {'applied':>8} {'events':>7} {'moved':>6} "
          f"{'children':>9}  median move")
    tot = {"applied": 0, "children": 0}
    for op_name in sorted(stats):
        r = stats[op_name]
        med = f"{100 * statistics.median(r['dist']):.0f} cm" if r["dist"] else "-"
        print(f"{op_name:20} {r['applied']:8d} {r['events']:7d} {r['moved']:6d} "
              f"{r['children']:9d}  {med}")
        tot["applied"] += r["applied"]
        tot["children"] += r["children"]
    print(f"\n{tot['children']} of {tot['applied']} applied moves "
          f"({100 * tot['children'] / max(1, tot['applied']):.1f}%) shift an "
          "upstairs wall the operator did not touch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
