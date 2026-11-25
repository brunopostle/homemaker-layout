"""Is the finish-time collapse optimal? `Fitness.collapse_global` against an
exact CP-SAT solve of the same problem (`homemaker-py-5bv`, DESIGN.md §39.273).

`collapse_global` relabels every room cell of a finished design to the room
it fits best: a quadratic assignment (a satisfied adjacency depends on TWO
cells' labels), approximated by a Jacobi loop of linear assignments and, at
finish time, a 2-opt polish. This builds the SAME problem -- the same supply
cells, slots, pins, level constraint and per-(cell, code) base value
(`Fitness._collapse_value`), the same adjacency reward -- and solves it
exactly with OR-Tools CP-SAT, then asks:

  gap      how far below the exact optimum the shipped collapse lands, in the
           collapse's own objective (one unit = one avoided fail);
  fails    what the scorer says of each labelling, the thing that matters;
  ms       what each costs.

The objective, as `_two_opt_adjacency_polish`'s `reward` sums it: over the
supply cells, the base value of the cell's code plus FAIL_W per adjacency
of that code the cell's neighbours satisfy. The exact model's assignment
rule is the Hungarian one: min(cells, slots) cells take slots, each slot at
most once; the rest keep their label.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5bv_cpsat_collapse.py [PATH.dom ...]
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5bv_cpsat_collapse.py --self-test
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import sys
import time
from collections import Counter
from pathlib import Path

from homemaker_layout import dom, geometry, graph as graph_mod
from homemaker_layout.fitness import Fitness, _slot_order_key, load_config

REPO = Path(__file__).resolve().parents[1]
KEYS = {"maple": "maple-court", "harbor": "harbor-house", "health": "health-centre",
        "programme-house": "programme-house", "split-stair": "maple-court",
        "join-clean9": "maple-court"}
SCALE = 100          # base values are scaled to integers for CP-SAT


def problem(fit, root):
    """`collapse_global`'s own setup: (supply, levels, slots, base, graphs,
    code_adj, prog), or None if there is nothing to collapse."""
    geometry.clear_cache()
    dom.canonicalize_shares(root)
    prog = fit._programme or {}
    room_codes = {c for c in prog if not dom.is_generic(c)}
    if not room_codes:
        return None
    lvls = dom.levels(root)
    graphs = graph_mod.build_graphs(root, fit.conf("door_width") or 1.2)
    pinned = fit._public_access_pins(root, graphs, lvls, room_codes)
    supply = [lf for lv in lvls for lf in lv.leaves()
              if lf.type in room_codes and id(lf) not in pinned]
    slot_counts = Counter({c: max(0, prog[c].count) for c in room_codes})
    for lv in lvls:
        for lf in lv.leaves():
            if id(lf) in pinned and slot_counts.get(lf.type, 0) > 0:
                slot_counts[lf.type] -= 1
    slots = [c for c in sorted(slot_counts, key=lambda c: _slot_order_key(c, prog))
             for _ in range(slot_counts[c])]
    if not supply or not slots:
        return None
    levels_of = [dom.level_of(lf) for lf in supply]
    codes = sorted(set(slots) | {lf.type for lf in supply})
    base = {(i, c): fit._collapse_value(lf, c, levels_of[i], prog, "threshold",
                                        fit._COLLAPSE_FORBID, fit._COLLAPSE_FAIL_W)
            for i, lf in enumerate(supply) for c in codes}
    code_adj = {c: prog[c].adjacency for c in codes}
    return supply, levels_of, slots, base, graphs, code_adj, prog


def objective(fit, prob) -> float:
    """The collapse's objective for the labels the supply cells carry now."""
    supply, levels_of, _slots, base, graphs, code_adj, _prog = prob
    total = 0.0
    for i, lf in enumerate(supply):
        v = base[i, lf.type]
        if v <= fit._COLLAPSE_FORBID:
            return float("-inf")
        G = graphs[levels_of[i]]
        sat = sum(1 for ac in code_adj.get(lf.type, ()) if graph_mod.has_adjacency(lf, ac, G))
        total += v + fit._COLLAPSE_FAIL_W * sat
    return total


def exact(fit, prob, hint=None, time_limit: float = 20.0):
    """CP-SAT on the same objective; writes the optimal labels into the supply
    cells and returns (status, objective bound, ms). ``hint``: labels to
    start from (the shipped collapse's), so the solver never ends below them.

    Linear in the label literals: a cell's literals are mutually exclusive
    (exactly one), so its base value is a sum over them, and an adjacency of
    code c at cell i is a variable no greater than i carrying c and no greater
    than the number of neighbours carrying a matching code. The first version
    reified each label in a helper variable and was still FEASIBLE, not
    OPTIMAL, after 20 s on a 21-cell design, below the shipped collapse."""
    from ortools.sat.python import cp_model
    supply, levels_of, slots, base, graphs, code_adj, prog = prob
    forbid = fit._COLLAPSE_FORBID
    W = int(fit._COLLAPSE_FAIL_W * SCALE)
    m = cp_model.CpModel()
    n = len(supply)
    slot_codes = sorted(set(slots))
    cap = Counter(slots)
    x = {}
    keep = {}
    for i, lf in enumerate(supply):
        for c in slot_codes:
            if base[i, c] > forbid:
                x[i, c] = m.NewBoolVar(f"x{i}_{c}")
        keep[i] = m.NewBoolVar(f"k{i}")
        m.AddExactlyOne([*(x[i, c] for c in slot_codes if (i, c) in x), keep[i]])
    for c in slot_codes:
        m.Add(sum(x[i, c] for i in range(n) if (i, c) in x) <= cap[c])
    # at most as many matched as the Hungarian solve can match; it counts
    # forbidden pairs among its matches (and leaves those cells as they are),
    # so "exactly" made the shipped labelling infeasible as a hint
    m.Add(sum(x.values()) <= min(n, len(slots)))
    # ...and the Hungarian solve FILLS every slot it can: its matching is
    # complete, and the collapse objective has no term for a room left out,
    # so without this the solver leaves slots empty -- the relaxed first run
    # "won" by 4 on the objective and scored 56 fails against the shipped 6
    fill = 1000 * W * max(1, len(slots))
    def lits(i, c):
        out = [x[i, c]] if (i, c) in x else []
        if supply[i].type == c:
            out.append(keep[i])
        return out

    obj = []
    idx = {id(lf): i for i, lf in enumerate(supply)}
    for i, lf in enumerate(supply):
        G = graphs[levels_of[i]]
        node = lf
        while node is not None and not G.has_node(node):
            node = node.parent
        nbs = list(G.neighbors(node)) if node is not None else []
        for c in set(slot_codes) | {lf.type}:
            li = lits(i, c)
            if not li or base[i, c] <= forbid:
                continue
            obj.append(int(round(base[i, c] * SCALE)) * sum(li))
            for ac in code_adj.get(c, ()):
                fixed = any(idx.get(id(nb)) is None and
                            graph_mod.has_adjacency(lf, ac, G.subgraph([node, nb]))
                            for nb in nbs)
                if fixed:
                    obj.append(W * sum(li))
                    continue
                cand = [lit for nb in nbs if (j := idx.get(id(nb))) is not None
                        for d in set(slot_codes) | {supply[j].type}
                        if graph_mod.code_matches_requirement(d, ac)
                        for lit in lits(j, d)]
                if not cand:
                    continue
                y = m.NewBoolVar(f"y{i}_{c}_{ac}")
                m.Add(y <= sum(li))
                m.Add(y <= sum(cand))
                obj.append(W * y)
    m.Maximize(sum(obj) + fill * sum(x.values()))
    if hint is not None:
        # the hint as MATCHES: a cell takes a slot of its hinted label while
        # that code has room (a relabelled cell first, since it must), and
        # keeps its label beyond that -- the Hungarian solve's own complete
        # matching. Hinting every unchanged cell as "keep" filled no slot, and
        # the fill weight pushed the solver off it before it found the optimum.
        left = Counter(cap)
        order = sorted(range(n), key=lambda i: hint[i] == supply[i].type)
        take = {}
        for i in order:
            h = hint[i]
            if (i, h) in x and left[h] > 0:
                take[i] = h
                left[h] -= 1
        for i in range(n):
            m.AddHint(keep[i], int(i not in take))
            for c in slot_codes:
                if (i, c) in x:
                    m.AddHint(x[i, c], int(take.get(i) == c))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_workers = 4
    t0 = time.process_time()
    st = s.Solve(m)
    ms = 1000 * (time.process_time() - t0)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for i, lf in enumerate(supply):
            if s.Value(keep[i]):
                continue
            for c in slot_codes:
                if (i, c) in x and s.Value(x[i, c]):
                    lf.type = c
    return s.StatusName(st), (s.BestObjectiveBound() - fill * s.Value(sum(x.values()))) / SCALE, ms


def compare(fit, path):
    """(gap in avoided fails, shipped fails, exact fails, shipped ms, exact ms, status)."""
    out = {}
    for arm in ("shipped", "exact"):
        root = dom.load(str(path))
        dom.link(root)
        geometry.clear_cache()
        t0 = time.process_time()
        if arm == "shipped":
            fit.collapse_global(root, local_search=True)
            ms, st = 1000 * (time.process_time() - t0), "-"
            prob = problem(fit, root)
            shipped = {(dom.level_of(lf), lf.id): lf.type
                       for lv in dom.levels(root) for lf in lv.leaves()}
        else:
            prob = problem(fit, root)
            if prob is None:
                return None
            # the shipped labels, by cell, as the solver's starting point
            hint = [shipped.get((dom.level_of(lf), lf.id), lf.type) for lf in prob[0]]
            st, _bound, ms = exact(fit, prob, hint)
        if prob is None:
            return None
        o = objective(fit, prob)
        dom.link(root)
        geometry.clear_cache()
        _s, fails = fit.score_with_fails(root)
        out[arm] = (o, len(fails), ms, st)
    gap = (out["exact"][0] - out["shipped"][0]) / fit._COLLAPSE_FAIL_W
    return gap, out["shipped"][1], out["exact"][1], out["shipped"][2], out["exact"][2], out["exact"][3]


def default_paths():
    res = REPO / "experiments" / "results"
    found = []
    for pat in ("*/final-*.dom", "*/winner*.dom", "*/drawings/*.dom"):
        found += sorted(res.glob(pat))
    found += sorted((REPO / "examples").glob("*/coldstart-4428262+orth-*.dom"))
    seen, out = set(), []
    for p in found:
        h = hashlib.sha1(p.read_bytes()).hexdigest()
        if h not in seen:
            seen.add(h)
            out.append(p)
    return out


def self_test() -> int:
    """Controls: (1) the objective of a labelling the exact solver returns is
    at least the shipped collapse's on every design tried (it optimises the
    same function, or the model is wrong); (2) it fills as many slots, so it
    leaves out no room the shipped one keeps (missing lines no more); (3)
    scrambling a design's labels lowers the objective."""
    import random
    path = REPO / "experiments/results/halving-health-swap/winner.dom"
    fit = Fitness(*load_config(REPO / "examples" / "health-centre"))
    r = compare(fit, path)
    assert r is not None and r[0] >= -1e-6, f"exact below shipped: {r}"
    assert r[2] <= r[1] + 3, f"exact labelling scores far worse: {r}"
    root = dom.load(str(path))
    dom.link(root)
    prob = problem(fit, root)
    o0 = objective(fit, prob)
    labels = [lf.type for lf in prob[0]]
    random.Random(0).shuffle(labels)
    for lf, lab in zip(prob[0], labels):
        lf.type = lab
    assert objective(fit, prob) < o0, "scrambling the labels did not lower the objective"
    print(f"self-test passed: gap {r[0]:.2f}, shipped {r[1]} fails, exact {r[2]} fails")
    return 0


def main(argv=None) -> int:
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    fits = {}
    print("programme\tdesign\tgap_fails\tshipped_fails\texact_fails\tshipped_ms\texact_ms\tstatus")
    for p in [Path(x) for x in a.paths] or default_paths():
        prog = next((v for k, v in KEYS.items() if k in str(p)), None)
        if prog is None:
            continue
        if prog not in fits:
            fits[prog] = Fitness(*load_config(REPO / "examples" / prog))
        r = compare(fits[prog], p)
        if r is None:
            continue
        rel = "/".join(p.parts[-2:])
        print(f"{prog}\t{rel}\t{r[0]:.2f}\t{r[1]}\t{r[2]}\t{r[3]:.0f}\t{r[4]:.0f}\t{r[5]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
