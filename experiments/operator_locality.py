#!/usr/bin/env python3
"""Operator validity + locality measurement (homemaker-py-nyb acceptance).

For each operator: apply 5 seeded instances per corpus design, score every
child through the oracle (validity = scores without error), and report
locality as (a) mean relative fitness perturbation and (b) mean geometry
perturbation — the fraction of leaf rooms whose (type, footprint) changed.
High-locality operators keep both small, so warm-started inner loops stay
cheap (DESIGN.md §5).

Run under the go-forward fitness:
  URB_NO_OCCLUSION=1 python3 experiments/operator_locality.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker import dom, genome, geometry, operators, oracle, programme  # noqa: E402

URB = Path("/home/bruno/src/urb")
CORPUS = URB / "examples" / "programme-house"
FILES = ["2f45907abd9accac2a124d311732f749.dom", "candidate-002.dom",
         "c964435454c459f86c3ed9a5a7621132.dom"]
SEEDS = range(5)


def leaf_signature(root: dom.Node) -> Counter:
    sig = Counter()
    for li, lvl in enumerate(dom.levels(root)):
        for leaf in lvl.leaves():
            corners = tuple(tuple(round(c, 6) for c in geometry.coordinate(leaf, i))
                            for i in range(4))
            sig[(li, leaf.type, corners)] += 1
    return sig


def geometry_perturbation(parent_sig: Counter, child: dom.Node) -> float:
    child_sig = leaf_signature(child)
    common = sum((parent_sig & child_sig).values())
    return 1.0 - common / max(parent_sig.total(), child_sig.total())


def main() -> int:
    types = sorted(programme.load_programme(str(CORPUS / "patterns.config"))) + ["c", "o"]
    roots = {f: genome.decode(genome.encode(dom.load(str(CORPUS / f)))) for f in FILES}

    with tempfile.TemporaryDirectory(prefix="op_locality_") as tmp:
        scratch = Path(tmp)
        shutil.copy(CORPUS / "patterns.config", scratch)

        parents = {}
        paths = []
        for f, root in roots.items():
            p = scratch / f
            dom.dump(root, str(p))
            paths.append(p)
        for f, s in zip(roots, oracle.score_batch(paths, URB)):
            parents[f] = s

        jobs: list[tuple[str, str, dom.Node]] = []  # (op, desc, child)
        for f, root in roots.items():
            for name, op in operators.MUTATIONS.items():
                for seed in SEEDS:
                    child, desc = op(root, np.random.default_rng(seed), types)
                    jobs.append((name, f, child))
        for seed in SEEDS:
            ca, cb, _ = operators.crossover(roots[FILES[0]], roots[FILES[1]],
                                            np.random.default_rng(seed))
            jobs.append(("crossover", FILES[0], ca))
            jobs.append(("crossover", FILES[1], cb))

        paths = []
        for i, (_, _, child) in enumerate(jobs):
            p = scratch / f"child_{i:03d}.dom"
            dom.dump(child, str(p))
            paths.append(p)
        scores = oracle.score_batch(paths, URB)  # raises if any child is invalid

        sigs = {f: leaf_signature(root) for f, root in roots.items()}
        stats: dict[str, list[tuple[float, float]]] = {}
        for (name, f, child), s in zip(jobs, scores):
            df = abs(s.fitness - parents[f].fitness) / parents[f].fitness
            dg = geometry_perturbation(sigs[f], child)
            stats.setdefault(name, []).append((df, dg))

        print(f"{'operator':14s} {'n':>3s} {'mean |dF|/F':>12s} {'mean geom-pert':>15s}")
        for name in sorted(stats):
            dfs, dgs = zip(*stats[name])
            print(f"{name:14s} {len(dfs):3d} {np.mean(dfs):12.3f} {np.mean(dgs):15.3f}")
        print(f"\nall {len(jobs)} children scored by the oracle without error")
    return 0


if __name__ == "__main__":
    sys.exit(main())
