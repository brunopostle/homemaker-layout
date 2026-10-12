"""Does AIMING `undivide` at a failing cell do, on purpose, what the
recordings saw it do by accident? (`homemaker-py-iplo`, DESIGN.md §39.123)

§39.123 is observational: among undivides a search happened to draw, the ones
that landed beside a failing cell removed a fail 8.5% of the time against
0.9%. This draws them deliberately. Parents: finished designs that still
carry a fail naming a cell. For each, `undivide` unaimed and aimed, the same
number of draws, each child tuned as the search tunes one (`driver._evaluate`,
80 evaluations) and judged against its parent.

    random   mutate_undivide as it is
    aimed    mutate_undivide(fails=the parent's fail lines), AIM_SHARE = 1

Per arm: children with fewer fails than the parent, with more, and that beat
it (fewer, or as many and a higher score). Paired over parents through
`ab_report`, one rate per parent and arm.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 PYTHONPATH=src \\
        python experiments/diag_iplo_aim_undivide.py [--draws 8]
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.util
import sys
from pathlib import Path

import numpy as np

from homemaker_layout import dom, driver, geometry, innerloop, operators

REPO = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parents(table: str, directory: str, programme: str):
    with open(REPO / "experiments" / "results" / f"{table}.tsv") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["programme"] == programme and int(r["fails"]) > 0:
                yield REPO / "experiments" / "results" / directory / r["dom"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default="programme-house")
    ap.add_argument("--table", default="child20_ab")
    ap.add_argument("--dir", default="child20-ab")
    ap.add_argument("--corpus", help="instead: a glob under examples/<programme>/")
    ap.add_argument("--draws", type=int, default=8)
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    shaft, ab = _load("diag_8b2u_fixed_shaft"), _load("ab_report")
    search = shaft.SEARCH
    prog = REPO / "examples" / a.programme
    files = (sorted(prog.glob(a.corpus)) if a.corpus
             else sorted(parents(a.table, a.dir, a.programme)))

    def tuned(tree, x0):
        root = copy.deepcopy(tree)
        dom.link(root)
        geometry.clear_cache()
        ind, _ = driver._evaluate(root, str(prog), x0, 80, {}, "iplo", **search)
        return ind

    rows, used, skipped = [], 0, 0
    for p in files:
        parent = dom.load(str(p))
        dom.link(parent)
        geometry.clear_cache()
        ratios = innerloop.ratio_map(parent)
        base = tuned(parent, innerloop.warm_x0(parent, ratios))    # the parent, re-tuned
        if not operators.failing_cells(base.fails):
            skipped += 1
            continue
        used += 1
        for arm, share in (("random", 0.0), ("aimed", 1.0)):
            operators.AIM_SHARE = share
            rng = np.random.default_rng(int.from_bytes(
                hashlib.blake2b(f"{p.name}/{arm}".encode(), digest_size=8).digest(), "little"))
            for _ in range(a.draws):
                child, desc = operators.mutate_undivide(parent, rng, ["C", "O"],
                                                        fails=base.fails)
                if "noop" in desc:
                    continue
                dom.link(child)
                geometry.clear_cache()
                x0 = innerloop.warm_x0(child, {**innerloop.ratio_map(child), **ratios})
                ind = tuned(child, x0)
                rows.append({"parent": p.name, "arm": arm, "aimed": "aimed" in desc,
                             "fewer": ind.n_fails < base.n_fails,
                             "more": ind.n_fails > base.n_fails,
                             "beat": ind.n_fails < base.n_fails
                             or (ind.n_fails == base.n_fails and ind.fitness > base.fitness)})
        operators.AIM_SHARE = 0.5
        print(f"  {p.name[-28:]}: {base.n_fails} fails; "
              + "  ".join(f"{arm} fewer {sum(r['fewer'] for r in rows if r['parent'] == p.name and r['arm'] == arm)}"
                          for arm in ("random", "aimed")), file=sys.stderr, flush=True)

    print(f"\n{a.programme}: {used} parents with a failing cell ({skipped} without), "
          f"{a.draws} draws an arm")
    print(f"{'arm':<8} {'children':>8} {'actually aimed':>15} {'fewer fails':>12} "
          f"{'more fails':>11} {'beat parent':>12}")
    for arm in ("random", "aimed"):
        rs = [r for r in rows if r["arm"] == arm]
        n = len(rs) or 1
        print(f"{arm:<8} {len(rs):>8} {sum(r['aimed'] for r in rs):>15} "
              f"{100 * sum(r['fewer'] for r in rs) / n:>11.1f}% "
              f"{100 * sum(r['more'] for r in rs) / n:>10.1f}% "
              f"{100 * sum(r['beat'] for r in rs) / n:>11.1f}%")
    for key, lab in (("fewer", "fewer fails"), ("beat", "beat parent")):
        xa, xb = [], []
        for par in dict.fromkeys(r["parent"] for r in rows):
            ra = [r[key] for r in rows if r["parent"] == par and r["arm"] == "random"]
            rb = [r[key] for r in rows if r["parent"] == par and r["arm"] == "aimed"]
            if ra and rb:
                xa.append(100 * sum(ra) / len(ra))
                xb.append(100 * sum(rb) / len(rb))
        if len(xa) >= 2:
            print(f"\n{lab}, percent of a parent's children, paired over parents "
                  "(a W is `aimed` LOWER, so look at the means):")
            print(ab.format_report(ab.paired_report(xa, xb, "random", "aimed")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
