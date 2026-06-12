#!/usr/bin/env python3
"""Warm vs cold inner-loop starts under topology mutation (homemaker-py-8cs).

Lamarckian inheritance (DESIGN.md §5 decision 6): a child topology's inner
loop warm-starts from the parent's optimised ratios — cuts that survive the
mutation keep their values, new cuts get 0.5. This experiment measures the
speedup against a cold start (all cuts 0.5) at equal budget:

  for each corpus design: optimise geometry (parent optimum), then apply
  single top-storey topology mutations (divide a leaf / undivide a leaf-pair
  branch); re-optimise each child warm and cold; compare oracle evaluations
  needed to reach 95% of the better final fitness, and the finals themselves.

Run under the go-forward fitness:
  URB_NO_OCCLUSION=1 python3 experiments/warm_vs_cold.py [parent_budget child_budget]
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker import dom, innerloop, solver  # noqa: E402

URB = Path("/home/bruno/src/urb")
EX = URB / "examples" / "programme-house"

DESIGNS = [
    "2f45907abd9accac2a124d311732f749.dom",
    "candidate-002.dom",
    "c964435454c459f86c3ed9a5a7621132.dom",
]
N_DIVIDE = 2  # mutations of each kind per design
N_UNDIVIDE = 2
TARGET_FRACTION = 0.95


def free_with_keys(root: dom.Node) -> list[tuple[tuple[int, str], dom.Node]]:
    """solver.free_branches order, with (level_index, id-path) keys that
    survive deepcopy and structural mutation."""
    out = []
    for li, lvl in enumerate(dom.levels(root)):
        for b in solver._branches(lvl):
            if b.below is None or not b.below.divided:
                out.append(((li, b.id), b))
    return out


def divide_leaf(leaf: dom.Node) -> None:
    leaf.division = [0.5, 0.5]
    leaf.left = dom.Node(type=leaf.type)
    leaf.right = dom.Node(type="c")  # circulation absorbs the residual
    leaf.type = None


def undivide_branch(branch: dom.Node) -> None:
    # keep the more programme-specific child type (generic = circulation/outside)
    types = [branch.left.type, branch.right.type]
    specific = [t for t in types if t and not t.startswith(("c", "o", "s"))]
    branch.type = specific[0] if specific else types[0]
    branch.division = None
    branch.left = branch.right = None


def mutations(root: dom.Node) -> list[tuple[str, dom.Node]]:
    """Mutated deep copies of ``root`` (top storey only, so Below-inheritance
    from lower storeys is never invalidated)."""
    out = []
    top_idx = len(dom.levels(root)) - 1
    top = dom.levels(root)[top_idx]
    leaf_ids = [leaf.id for leaf in top.leaves()][:N_DIVIDE]
    branch_ids = [b.id for b in solver._branches(top)
                  if not b.left.divided and not b.right.divided][:N_UNDIVIDE]
    for lid in leaf_ids:
        child = copy.deepcopy(root)
        divide_leaf(dom.levels(child)[top_idx].by_id(lid))
        dom._link(child)
        out.append((f"divide {top_idx}/{lid or 'root'}", child))
    for bid in branch_ids:
        child = copy.deepcopy(root)
        undivide_branch(dom.levels(child)[top_idx].by_id(bid))
        dom._link(child)
        out.append((f"undivide {top_idx}/{bid or 'root'}", child))
    return out


def optimise_traced(root: dom.Node, x0: np.ndarray, budget: int) -> tuple[innerloop.Result, list[float]]:
    """cma_search with a per-evaluation best-so-far trace."""
    history: list[float] = []
    with innerloop.OracleEvaluator(root, EX, URB) as ev:
        inner_evaluate = ev.evaluate

        def traced(xs):
            scores = inner_evaluate(xs)
            history.extend(s.fitness for s in scores)
            return scores

        ev.evaluate = traced
        r = innerloop.cma_search(ev, x0, budget=budget)
        ev.apply(r.x)
    return r, history


def evals_to(history: list[float], target: float) -> int | None:
    best = -np.inf
    for i, f in enumerate(history):
        best = max(best, f)
        if best >= target:
            return i + 1
    return None


def main() -> int:
    parent_budget = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    child_budget = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    speedups = []
    for name in DESIGNS:
        root = dom.load(str(EX / name))
        with innerloop.OracleEvaluator(root, EX, URB) as ev:
            x0 = ev.x_current
        parent, _ = optimise_traced(root, x0, parent_budget)
        parent_map = {k: b.division[0] for k, b in free_with_keys(root)}
        print(f"\n{name}: parent optimum {parent.fitness:.6g} "
              f"(fails {parent.n_fails}, dof {len(parent.x)})", flush=True)

        for label, child in mutations(root):
            keys = free_with_keys(child)
            x_warm = np.array([parent_map.get(k, 0.5) for k, _ in keys])
            x_cold = np.full(len(keys), 0.5)
            surviving = sum(k in parent_map for k, _ in keys)

            r_warm, h_warm = optimise_traced(copy.deepcopy(child), x_warm, child_budget)
            r_cold, h_cold = optimise_traced(copy.deepcopy(child), x_cold, child_budget)

            target = TARGET_FRACTION * max(r_warm.fitness, r_cold.fitness)
            e_warm, e_cold = evals_to(h_warm, target), evals_to(h_cold, target)
            if e_warm is not None and e_cold is not None:
                speedups.append(e_cold / e_warm)
            ratio = f"x{e_cold / e_warm:.1f}" if e_warm and e_cold else "n/a"
            print(f"  {label:22s} dof {len(keys):2d} ({surviving} inherited)  "
                  f"warm: {r_warm.fitness:.6g} in {e_warm} evals  "
                  f"cold: {r_cold.fitness:.6g} in {e_cold} evals  "
                  f"speedup {ratio}", flush=True)

    if speedups:
        print(f"\nspeedup (evals to {TARGET_FRACTION:.0%} of best final): "
              f"median x{np.median(speedups):.1f}, "
              f"range x{min(speedups):.1f}-x{max(speedups):.1f}, "
              f"n={len(speedups)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
