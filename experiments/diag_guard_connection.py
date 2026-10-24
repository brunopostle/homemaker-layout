"""What would the connection guard turn away? (`homemaker-py-2g7.13.1.10`)

`driver.GUARD_CONNECTION` declines a bred child that fails `level N not
connected` for a storey its parent had connected (`driver.disconnects`).
This draws children from connected-enough parents with the search's own
mutation mix and asks, per operator:

* how many disconnect a storey at the parent's ratios (``raw``, one
  evaluation), and how many still do after the child's inner loop
  (``tuned``, `driver._evaluate` at the search's child budget) -- the guard
  reads the tuned child, so ``raw`` minus ``tuned`` is what the inner loop
  puts back on its own;
* how many of the tuned disconnecting children BEAT their parent (fewer
  fails, or the same and a higher score) -- the ones a search would have
  kept, and so the only ones the guard actually changes anything for;
* the share of all children declined: the budget the guard spends for
  nothing.

Parents are any ``.dom`` given with at least one storey connected; by
default the 4k outputs of §39.167's maple spine race, where `spine-2` sold
its connection. ``--self-test`` is the negative control: every child with a
storey forced apart must count as declined, and the unforced must match.

What it cannot say is whether a search that declines these ends better:
that is the race (population dynamics, the box).

    HOMEMAKER_ORTHOGONAL_DIVISION=1 PYTHONPATH=src \\
        python experiments/diag_guard_connection.py --draws 6 --parents 12
"""

from __future__ import annotations

import argparse
import collections
import copy
import glob
import hashlib
import importlib.util
import os
import sys
import time
from pathlib import Path

import numpy as np

from homemaker_layout import dom, driver, geometry, innerloop, operators, programme

REPO = Path(__file__).resolve().parents[1]
DEFAULT = os.path.expanduser("~/halving-maple-spine/s0/spine-*/out.dom")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _evaluate(root, prog, x0, budget, search):
    r = copy.deepcopy(root)
    dom.link(r)
    geometry.clear_cache()
    ind, _ = driver._evaluate(r, str(prog), x0, budget, {}, "guard", **search)
    return ind


def beats(c, p) -> bool:
    return c.n_fails < p.n_fails or (c.n_fails == p.n_fails and c.fitness > p.fitness)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("doms", nargs="*", help=f"parent designs (default {DEFAULT})")
    ap.add_argument("--programme", default="maple-court")
    ap.add_argument("--parents", type=int, default=12, help="at most this many parents")
    ap.add_argument("--draws", type=int, default=6, help="children per parent")
    ap.add_argument("--child-budget", type=int, default=80)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    shaft = _load("diag_8b2u_fixed_shaft")
    weights, search = shaft.search_weights(), shaft.SEARCH
    if os.environ.get("HOMEMAKER_PIVOT", "") != "1":   # off by default, as in
        weights["pivot"] = 0.0                         # driver.search (mtfo)
    prog = REPO / "examples" / a.programme
    reqs = programme.load_programme_dir(str(prog))
    types = sorted(reqs) + ["C", "O"]
    paths = sorted(a.doms or glob.glob(DEFAULT))
    if not paths:
        sys.exit(f"no parents: {DEFAULT} is empty")

    t0 = time.process_time()
    parents = []
    for p in paths:
        root = dom.load(p)
        dom.link(root)
        geometry.clear_cache()
        ind = _evaluate(root, prog, innerloop.warm_x0(root, innerloop.ratio_map(root)), 1, search)
        n_storeys = len(dom.levels(root))
        if len(driver._unconnected_levels(ind.fails)) < n_storeys:
            parents.append((p, root, ind))
        if len(parents) >= a.parents:
            break
    print(f"{len(parents)} parents with a connected storey, of {len(paths)} read", flush=True)

    if a.self_test:
        a.draws = 2
    rows = []
    for p, parent, pind in parents:
        ratios = innerloop.ratio_map(parent)
        rng = np.random.default_rng(int.from_bytes(
            hashlib.blake2b(p.encode(), digest_size=8).digest(), "little"))
        got = 0
        while got < a.draws:
            child, desc = operators.mutate(parent, rng, types, weights=weights, reqs=reqs,
                                           fails=pind.fails if driver.AIM_UNDIVIDE else None)
            if "noop" in desc:
                continue
            got += 1
            dom.link(child)
            geometry.clear_cache()
            x0 = innerloop.warm_x0(child, {**innerloop.ratio_map(child), **ratios})
            raw = _evaluate(child, prog, x0, 1, search)
            tuned = _evaluate(child, prog, x0, a.child_budget, search)
            row = dict(parent=Path(p).parent.name, op=desc.split()[0],
                       raw=driver.disconnects(raw.fails, pind.fails),
                       tuned=driver.disconnects(tuned.fails, pind.fails),
                       beats=beats(tuned, pind), pf=pind.n_fails, cf=tuned.n_fails)
            if a.self_test:
                forced = tuned.fails + ("level 99 not connected",)
                row["forced"] = driver.disconnects(forced, pind.fails)
            rows.append(row)
            print(f"  {row['parent']:<12} {row['op']:<20} raw {'X' if row['raw'] else '.'} "
                  f"tuned {'X' if row['tuned'] else '.'} {'beats' if row['beats'] else '     '} "
                  f"{row['pf']} -> {row['cf']}", file=sys.stderr, flush=True)

    if a.self_test:
        ok = rows and all(r["forced"] for r in rows) and \
            sum(r["tuned"] for r in rows) < len(rows)
        print("self-test", "PASSED" if ok else "FAILED",
              f"-- forced apart: {sum(r['forced'] for r in rows)} of {len(rows)} declined; "
              f"unforced: {sum(r['tuned'] for r in rows)}")
        return 0 if ok else 1

    n = len(rows)
    by = collections.defaultdict(list)
    for r in rows:
        by[r["op"]].append(r)
    print(f"\n{n} children, {a.draws} per parent, child budget {a.child_budget}; "
          f"{time.process_time() - t0:.0f} s CPU\n")
    print(f"{'operator':<22} {'n':>4} {'raw':>5} {'tuned':>6} {'declined&beats':>15}")
    for op, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"{op:<22} {len(rs):4d} {sum(r['raw'] for r in rs):5d} "
              f"{sum(r['tuned'] for r in rs):6d} "
              f"{sum(r['tuned'] and r['beats'] for r in rs):15d}")
    print(f"{'ALL':<22} {n:4d} {sum(r['raw'] for r in rows):5d} "
          f"{sum(r['tuned'] for r in rows):6d} "
          f"{sum(r['tuned'] and r['beats'] for r in rows):15d}")
    print(f"\nthe guard declines {sum(r['tuned'] for r in rows)} of {n} children "
          f"({100 * sum(r['tuned'] for r in rows) / max(1, n):.0f}% of child budget); "
          f"{sum(r['tuned'] and r['beats'] for r in rows)} of them beat their parent "
          f"and would have been kept; children that beat the parent at all: "
          f"{sum(r['beats'] for r in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
