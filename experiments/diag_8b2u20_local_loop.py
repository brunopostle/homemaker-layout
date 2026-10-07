"""A child changed one thing. Should its inner loop tune everything?
(`homemaker-py-8b2u.20`)

§39.109: Nelder-Mead's first n evaluations build its simplex one ratio at a
time, so on a programme with 35-41 cuts half of a child's 80 evaluations are
spent before the method moves. A child inherits its parent's tuned ratios and
differs from it in one place. So: tune only the cuts NEAR what the move
changed, and leave the rest where the parent had them.

"Near" is structural and cheap: a node CHANGED if its path exists in only one
of parent and child, or its type, its rotation or whether it is divided
differ. The local cuts are the child's free cuts on a changed path, above one
or below one -- on any storey, since storeys share paths. If a move changed
nothing this can see, every cut is local.

Arms, on children drawn with the search's own mutation mix, each scored with
the search's overrides:

  today     every cut, 80 evaluations            (`driver._evaluate`)
  all-40    every cut, 40
  all-20    every cut, 20
  local-80  the local cuts only, 80
  local-40  the local cuts only, 40
  local-20  the local cuts only, 20

The check on the harness itself: `local` with every cut and 80 evaluations IS
today's loop, and must give today's fails on every child (`--self-test`).

Fails per child, each arm paired against `today`; and, since a search keeps a
child only if it beats its parent, how many children do -- fewer fails, or
the same fails and a higher score -- and how the score compares with today's
on the same child. What it cannot say is whether a search with a cheaper
child ENDS better: more children per budget is population dynamics, and that
is the box.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 PYTHONPATH=src \\
        python experiments/diag_8b2u20_local_loop.py [--draws 8]
"""

from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import importlib.util
import sys
from pathlib import Path

import numpy as np

from homemaker_layout import dom, driver, geometry, innerloop, operators, programme, solver

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
ARMS = ("today", "all-40", "all-20", "local-80", "local-40", "local-20")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _nodes(root) -> dict:
    """``{(storey, path): (divided, type, rotation)}`` for every node."""
    out = {}
    for li, lvl in enumerate(dom.levels(root)):
        for n in operators._level_nodes(lvl):
            out[li, n.id or ""] = (n.divided, n.type, n.rotation)
    return out


def local_cuts(parent, child) -> "list[int]":
    """Indices into ``solver.free_branches(child)`` of the cuts near what the
    move changed; all of them if nothing it changed can be seen."""
    a, b = _nodes(parent), _nodes(child)
    changed = {path for (li, path) in set(a) | set(b) if a.get((li, path)) != b.get((li, path))}
    keyed = innerloop.free_with_keys(child)
    near = [i for i, ((_li, path), _b) in enumerate(keyed)
            if any(path.startswith(c) or c.startswith(path) for c in changed)]
    return near or list(range(len(keyed)))


def tune(child, prog, x0, budget, subset, overrides):
    """Nelder-Mead over the cuts in `subset`, the rest held at `x0`."""
    root = copy.deepcopy(child)
    dom.link(root)
    geometry.clear_cache()
    ev = innerloop.NativeEvaluator(root, prog, overrides)
    full = np.clip(np.asarray(x0, dtype=float), solver._EPS, 1 - solver._EPS)
    ev.apply(full)
    ev.free = [ev.free[i] for i in subset]
    r = innerloop.nm_search(ev, full[subset], budget=budget)
    return r.n_fails, r.fitness


def children(a, weights):
    for name in a.programme or PROGRAMMES:
        prog = REPO / "examples" / name
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]
        for p in sorted(prog.glob(a.corpus)):
            parent = dom.load(str(p))
            dom.link(parent)
            geometry.clear_cache()
            ratios = innerloop.ratio_map(parent)
            rng = np.random.default_rng(int.from_bytes(
                hashlib.blake2b(f"{name}/{p.name}".encode(), digest_size=8).digest(), "little"))
            got = 0
            while got < a.draws:
                child, desc = operators.mutate(parent, rng, types, weights=weights, reqs=reqs)
                if "noop" in desc:
                    continue
                got += 1
                dom.link(child)
                geometry.clear_cache()
                x0 = innerloop.warm_x0(child, {**innerloop.ratio_map(child), **ratios})
                yield name, p, prog, parent, child, desc.split()[0], x0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="coldstart-1a24b6a+orth-500000-s*.dom")
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--draws", type=int, default=8, help="children per artefact")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--save", metavar="FILE", help="write every row as JSON")
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    shaft, ab = _load("diag_8b2u_fixed_shaft"), _load("ab_report")
    weights, search = shaft.search_weights(), shaft.SEARCH
    overrides = driver._overrides_for(search.get("leaf_sharing", False), False, None, False,
                                      search.get("collapse_insearch", True), False)

    def today(child, prog, x0):
        root = copy.deepcopy(child)
        dom.link(root)
        geometry.clear_cache()
        ind, _ = driver._evaluate(root, str(prog), x0, 80, {}, "8b2u20", **search)
        return ind.n_fails, ind.fitness

    if a.self_test:
        a.draws, a.programme = 2, ["programme-house", "harbor-house"]
        n = bad = 0
        for name, p, prog, parent, child, op, x0 in children(a, weights):
            want = today(child, prog, x0)
            got = tune(child, str(prog), x0, 80, list(range(len(x0))), overrides)
            n += 1
            bad += want != got
        # ...and the comparison must be able to fail: a loop given 5
        # evaluations is not today's loop
        differs = sum(today(c, pr, x0) != tune(c, str(pr), x0, 5, list(range(len(x0))), overrides)
                      for _n, _p, pr, _par, c, _op, x0 in children(a, weights))
        ok = n >= 8 and bad == 0 and differs > 0
        print("self-test", "PASSED" if ok else "FAILED",
              f"-- every cut at 80 evaluations is today's loop on {n - bad} of {n} children; "
              f"at 5 evaluations it differs on {differs}")
        return 0 if ok else 1

    rows = []
    for name, p, prog, parent, child, op, x0 in children(a, weights):
        every = list(range(len(x0)))
        near = local_cuts(parent, child)
        px = innerloop.warm_x0(parent, innerloop.ratio_map(parent))
        row = {"programme": name, "op": op, "cuts": len(every), "local": len(near),
               "parent": tune(parent, str(prog), px, 1, list(range(len(px))), overrides),
               "today": today(child, prog, x0)}
        for arm in ARMS[1:]:
            kind, budget = arm.split("-")
            row[arm] = tune(child, str(prog), x0, int(budget),
                            every if kind == "all" else near, overrides)
        rows.append(row)
        print(f"  {name}/{p.name[-8:-4]} {op:<16} cuts {len(every):2d} local {len(near):2d}  "
              + "  ".join(f"{arm} {row[arm][0]}" for arm in ARMS), file=sys.stderr, flush=True)

    if a.save:
        import json
        Path(a.save).write_text(json.dumps(rows, indent=0))
    ops = collections.Counter(r["op"] for r in rows)
    print(f"\n{len(rows)} children ({a.draws} per artefact, {a.corpus})")
    print("operators drawn: " + ", ".join(f"{k} {v}" for k, v in ops.most_common()) + "\n")
    print(f"{'programme':<16} {'n':>3} {'cuts':>5} {'local':>6} " + "".join(f"{arm:>10}" for arm in ARMS))
    groups = [*dict.fromkeys(r["programme"] for r in rows), "ALL"]
    for g in groups:
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        n = len(sel)
        print(f"{g:<16} {n:3d} {sum(r['cuts'] for r in sel) / n:5.1f} "
              f"{sum(r['local'] for r in sel) / n:6.1f} "
              + "".join(f"{sum(r[arm][0] for r in sel) / n:10.2f}" for arm in ARMS))
    def beats(c, par) -> bool:
        return c[0] < par[0] or (c[0] == par[0] and c[1] > par[1])

    import math
    print(f"\n{'beat the parent':<16} {'n':>3} " + "".join(f"{arm:>10}" for arm in ARMS)
          + "     (a search keeps only these)")
    for g in groups:
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        print(f"{g:<16} {len(sel):3d} " + "".join(
            f"{sum(beats(r[arm], r['parent']) for r in sel):10d}" for arm in ARMS))
    print(f"\n{'score vs today':<16} {'n':>3} " + "".join(f"{arm:>10}" for arm in ARMS)
          + "     (mean log2 of the arm's score over today's, same child)")
    for g in groups:
        sel = [r for r in rows if (g == "ALL" or r["programme"] == g) and r["today"][1] > 0
               and all(r[arm][1] > 0 for arm in ARMS)]
        print(f"{g:<16} {len(sel):3d} " + "".join(
            f"{sum(math.log2(r[arm][1] / r['today'][1]) for r in sel) / max(1, len(sel)):+10.2f}"
            for arm in ARMS))
    for g in ("ALL", *groups[:-1]):
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        if len(sel) < 2:
            continue
        print(f"\n== {g}: fails, each arm paired against `today` on the same child "
              f"(a W is the arm LOWER)")
        for arm in ARMS[1:]:
            print(f"{arm}:")
            print(ab.format_report(ab.paired_report(
                [float(r["today"][0]) for r in sel], [float(r[arm][0]) for r in sel],
                "today", arm)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
