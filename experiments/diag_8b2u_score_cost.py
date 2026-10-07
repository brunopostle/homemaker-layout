"""What one score costs, quad tree and native, and proof that making it cheaper
changed nothing (`homemaker-py-8b2u.9` / `.10` / `.11`).

The native rectangle-frame tree was built for correctness (DESIGN.md §39.103):
it clips every leaf as a general polygon, tests every pair of cells for a
shared wall, and both trees build each storey's graph more than once a score.
Each of those is a change to an OBJECTIVE source that must move no score, so
this tool has two halves:

* ``--snapshot FILE`` writes every orthogonal artefact's score and fail list,
  as the quad tree it is and as the native tree of the same building. Take one
  before a change and one after and ``--diff A B`` them: §39.80's method. The
  score is compared as a float's ``repr``, so "the same" means the same bits
  unless ``--tol`` says otherwise.
* ``--time`` is the cost: CPU milliseconds per score (process time, and the
  fastest of ``--repeat`` -- the box is usually busy, and wall-clock on it
  swung by 2x between identical runs) and how many times the expensive
  primitives are called. The call counts are the part that does not wobble.
* ``--inside`` is `8b2u.9`'s census: how many cells are a whole rectangle, not
  touched by the plot's crop.
* ``--phases`` is `8b2u.13`'s question: how much of a score is leaf-local,
  how much per-storey graph work, how much building-level.

Usage (in a worktree, so that the worktree's ``src`` is the one measured)::

    PYTHONPATH=src python experiments/diag_8b2u_score_cost.py --snapshot before.json
    PYTHONPATH=src python experiments/diag_8b2u_score_cost.py --diff before.json after.json
    PYTHONPATH=src python experiments/diag_8b2u_score_cost.py --time
    PYTHONPATH=src python experiments/diag_8b2u_score_cost.py --self-test
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path

from homemaker_layout import cells, dom, dom_v2, geometry, graph
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parents[1]


def _rt():
    spec = importlib.util.spec_from_file_location(
        "_rt", REPO / "experiments" / "diag_8b2u2_roundtrip.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def both_trees(path: Path):
    """``(quad tree, native tree)`` of one orthogonal artefact. The switch is
    left OFF: set it before touching the quad tree again."""
    geometry.ORTHOGONAL_DIVISION = True
    quad = dom.load(str(path))
    doc = dom_v2.to_document(quad)
    geometry.ORTHOGONAL_DIVISION = False
    return quad, dom_v2.from_document(doc, native=True)


def score(root, fit, orth: bool):
    geometry.ORTHOGONAL_DIVISION = orth
    geometry.clear_cache()
    try:
        return fit.score_with_fails(copy.deepcopy(root))
    finally:
        geometry.ORTHOGONAL_DIVISION = False
        geometry.clear_cache()


def _fitness(prog: Path, _memo={}):
    if prog not in _memo:
        _memo[prog] = Fitness(*load_config(prog))
    return _memo[prog]


# --------------------------------------------------------------------------- #
# snapshot / diff
# --------------------------------------------------------------------------- #
def snapshot(nudge: float = 0.0) -> dict:
    out = {}
    for p, prog in _rt().corpus():
        quad, native = both_trees(p)
        if nudge:
            # the negative control: one cut of each tree moved
            quad.division = [quad.division[0] + nudge] * 2
            native.division = [native.division[0] + nudge] * 2
        fit = _fitness(prog)
        for name, root, orth in (("quad", quad, True), ("native", native, False)):
            s, fails = score(root, fit, orth)
            out[f"{p.relative_to(REPO)}|{name}"] = [repr(s), list(fails)]
    return out


def diff(a: dict, b: dict, tol: float = 0.0) -> int:
    moved = 0
    for key in sorted(set(a) | set(b)):
        x, y = a.get(key), b.get(key)
        if x is None or y is None:
            print(f"only in one snapshot: {key}")
            moved += 1
            continue
        sa, sb = float(x[0]), float(y[0])
        same_score = x[0] == y[0] if tol == 0.0 else abs(sa - sb) <= tol * max(abs(sa), abs(sb))
        if not same_score or x[1] != y[1]:
            moved += 1
            print(f"MOVED {key}: {x[0]} -> {y[0]}, fails {len(x[1])} -> {len(y[1])}")
    print(f"{moved} of {len(set(a) | set(b))} entries moved"
          + (f" (relative tolerance {tol:g})" if tol else " (scores compared bit for bit)"))
    return moved


# --------------------------------------------------------------------------- #
# cost
# --------------------------------------------------------------------------- #
class counting:
    """Count calls to the primitives a score is made of."""

    TARGETS = ((geometry, "leaf_graph"), (cells, "clip"), (cells, "shared_wall"),
               (graph, "has_circulation"))

    def __enter__(self):
        self.n: Counter = Counter()
        self._orig = []
        for mod, name in self.TARGETS:
            fn = getattr(mod, name)
            self._orig.append((mod, name, fn))

            def wrapped(*a, _fn=fn, _name=name, **k):
                self.n[_name] += 1
                return _fn(*a, **k)

            setattr(mod, name, wrapped)
        return self

    def __exit__(self, *exc):
        for mod, name, fn in self._orig:
            setattr(mod, name, fn)


def timings(repeat: int, per_programme: int) -> None:
    rt = _rt()
    by_prog: dict = {}
    for p, prog in rt.corpus():
        if "coldstart-" in p.name:
            by_prog.setdefault(prog.name, []).append((p, prog))
    print(f"{'programme':<16} {'cells':>5} {'storeys':>7} | {'quad ms':>8} {'native ms':>9} "
          f"{'ratio':>5} | calls per score: leaf_graph clip shared_wall (quad / native)")
    for name, items in by_prog.items():
        rows = []
        for p, prog in items[-per_programme:]:
            quad, native = both_trees(p)
            fit = _fitness(prog)
            ms, calls = {}, {}
            for kind, root, orth in (("quad", quad, True), ("native", native, False)):
                best = float("inf")
                for _ in range(repeat):
                    r = copy.deepcopy(root)
                    geometry.ORTHOGONAL_DIVISION = orth
                    geometry.clear_cache()
                    t0 = time.process_time()
                    fit.score_with_fails(r)
                    best = min(best, time.process_time() - t0)
                ms[kind] = best * 1e3
                with counting() as c:
                    score(root, fit, orth)
                calls[kind] = c.n
            geometry.ORTHOGONAL_DIVISION = False
            geometry.clear_cache()
            rows.append((sum(len(l.leaves()) for l in dom.levels(native)),
                         len(dom.levels(native)), ms, calls))
        n = len(rows)
        q = sum(r[2]["quad"] for r in rows) / n
        nv = sum(r[2]["native"] for r in rows) / n
        cq, cn = rows[-1][3]["quad"], rows[-1][3]["native"]
        print(f"{name:<16} {sum(r[0] for r in rows) / n:5.0f} {rows[-1][1]:7d} | "
              f"{q:8.1f} {nv:9.1f} {nv / q:5.2f} | "
              f"{cq['leaf_graph']}/{cn['leaf_graph']}  {cq['clip']}/{cn['clip']}  "
              f"{cq['shared_wall']}/{cn['shared_wall']}")


# --------------------------------------------------------------------------- #
# 8b2u.9: how many cells does the crop not touch?
# --------------------------------------------------------------------------- #
def rect_inside(rect, inner_uv, eps: float = 0.0) -> bool:
    """Is the frame rectangle wholly inside the CONVEX polygon `inner_uv`
    (anticlockwise, in frame coordinates)? Its four corners on the inner side
    of every edge."""
    u0, u1, v0, v1 = rect
    n = len(inner_uv)
    for i in range(n):
        (px, py), (qx, qy) = inner_uv[i], inner_uv[(i + 1) % n]
        ex, ey = qx - px, qy - py
        for cx, cy in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
            if ex * (cy - py) - ey * (cx - px) < -eps:
                return False
    return True


def inside_census() -> None:
    rt = _rt()
    tot: dict = {}
    for p, prog in rt.corpus():
        _, native = both_trees(p)
        u, v, inner, _ = geometry._native_frame(native)
        uv = [(q[0] * u[0] + q[1] * u[1], q[0] * v[0] + q[1] * v[1]) for q in inner]
        c = tot.setdefault(prog.name, Counter())
        for lvl in dom.levels(native):
            for lf in lvl.leaves():
                c["cells"] += 1
                whole = rect_inside(geometry._native_rect(lf), uv)
                c["inside"] += whole
                # the check on the check: a cell called whole must be drawn
                # with four corners and its rectangle's area
                r = geometry._native_rect(lf)
                if whole and (len(geometry.polygon(lf)) != 4 or abs(
                        geometry.area(lf) - (r[1] - r[0]) * (r[3] - r[2])) > 1e-9):
                    c["WRONG"] += 1
        geometry.clear_cache()
    print(f"{'programme':<16} {'cells':>6} {'whole rectangle':>16} {'share':>6}  wrongly called whole")
    for name, c in tot.items():
        print(f"{name:<16} {c['cells']:6d} {c['inside']:16d} "
              f"{100 * c['inside'] / c['cells']:5.1f}%  {c['WRONG']}")
    cells_, inside = (sum(c[k] for c in tot.values()) for k in ("cells", "inside"))
    print(f"{'all':<16} {cells_:6d} {inside:16d} {100 * inside / cells_:5.1f}%")


# --------------------------------------------------------------------------- #
# 8b2u.13: which part of a score could be made incremental?
# --------------------------------------------------------------------------- #
PHASES = (
    ("leaf-local",      ("evaluate_leaf",)),
    ("storey graph",    ("leaf_graph", "has_circulation")),
    ("storey, other",   ("process_storey",)),          # less evaluate_leaf, below
    ("building, checks", ("check_space_counts", "check_adjacency",
                          "check_level_constraints", "check_vertical_connectivity",
                          "evaluate_building", "preprocess_building", "merge_divided",
                          "mark_voids", "plot_cost", "canonicalize_shares")),
)


def phases(per_programme: int, repeat: int) -> None:
    """Share of a score's time by what a moved ratio would force to be redone.

    A ratio at node n moves the cells under n. LEAF-LOCAL work (a cell's
    quality factors) is redone for those cells and their neighbours; a
    STOREY's graph and its circulation filter are redone for the storey, and
    for every storey above that inherits the cut; BUILDING-level work (the
    programme checks, the building factor, the merge) is redone whatever
    moved, and is the floor under any incremental scheme.

    Measured under cProfile, which charges call-heavy code more than it costs
    unprofiled: read the shares, not the milliseconds."""
    import cProfile
    import pstats

    rt = _rt()
    by_prog: dict = {}
    for p, prog in rt.corpus():
        if "coldstart-" in p.name:
            by_prog.setdefault(prog.name, []).append((p, prog))
    names = [n for n, _ in PHASES] + ["everything else"]
    print(f"{'programme':<16} {'tree':<7}" + "".join(f"{n:>18}" for n in names))
    for name, items in by_prog.items():
        for kind in ("quad", "native"):
            pr = cProfile.Profile()
            for p, prog in items[-per_programme:]:
                quad, native = both_trees(p)
                root, orth = (quad, True) if kind == "quad" else (native, False)
                fit = _fitness(prog)
                roots = [copy.deepcopy(root) for _ in range(repeat)]
                geometry.ORTHOGONAL_DIVISION = orth
                for r in roots:
                    geometry.clear_cache()
                    pr.enable()
                    fit.score_with_fails(r)
                    pr.disable()
                geometry.ORTHOGONAL_DIVISION = False
                geometry.clear_cache()
            cum: Counter = Counter()
            for (_file, _line, fn), (_cc, _nc, _tt, ct, _callers) in pstats.Stats(pr).stats.items():
                cum[fn] += ct
            total = cum["score_with_fails"]
            t = {n: sum(cum[f] for f in fns) for n, fns in PHASES}
            t["storey, other"] -= t["leaf-local"]
            t["everything else"] = total - sum(t.values())
            print(f"{name:<16} {kind:<7}" + "".join(f"{100 * t[n] / total:17.0f}%" for n in names))


def self_test() -> int:
    """The diff must FIRE: a snapshot with one cut moved by 1% has to differ
    from the plain one on most entries, or a clean diff says nothing."""
    plain, moved = snapshot(), snapshot(nudge=0.01)
    n = diff(plain, moved)
    again = diff(plain, snapshot())
    ok = n > len(plain) // 2 and again == 0
    print("self-test", "PASSED" if ok else "FAILED",
          f"-- control moved {n} of {len(plain)}, a repeat moved {again}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--snapshot", metavar="FILE")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"))
    ap.add_argument("--tol", type=float, default=0.0,
                    help="relative score tolerance for --diff (default: bit for bit)")
    ap.add_argument("--time", action="store_true")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--per-programme", type=int, default=3,
                    help="artefacts timed per programme (the newest corpus's)")
    ap.add_argument("--inside", action="store_true")
    ap.add_argument("--phases", action="store_true",
                    help="share of a score by what a moved ratio forces to be redone (8b2u.13)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.snapshot:
        Path(a.snapshot).write_text(json.dumps(snapshot(), indent=0, sort_keys=True))
        print(f"wrote {a.snapshot}")
    if a.diff:
        x, y = (json.loads(Path(f).read_text()) for f in a.diff)
        return 1 if diff(x, y, a.tol) else 0
    if a.time:
        timings(a.repeat, a.per_programme)
    if a.inside:
        inside_census()
    if a.phases:
        phases(a.per_programme, a.repeat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
