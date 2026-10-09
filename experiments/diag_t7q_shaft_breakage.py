"""`homemaker-py-t7q` step 1: which operators throw the staircase away?

The owner's ruling (DESIGN.md §39.72) makes the vertical circulation shaft a hard
structural invariant: a staircase exists only where the cell is IDENTICAL on every
storey, because Alexander's pattern allocates the whole shaft to stairs and no
flight-fitter exists for a part-cell. `graph.stack_corners_in_use` reads it that
way (`dom._above_node`, the EXACT id path), and §39.72 counted the consequence: 21
of 48 committed artefacts have had their shaft merged away by something, and 11
have no intact shaft at all, which costs x0.0225.

"By something" is the gap this closes. Nothing in the operator set knows the shaft
is a structure to protect -- except `mutate_level_add_migrate`
(`operators._stair_path`, §39.71), and only for the storey it adds. So: take every
artefact that still HAS an intact shaft, apply each operator to it, and count how
often the shaft stops being intact.

    python experiments/diag_t7q_shaft_breakage.py [--draws 8] [--programme NAME]

A SHAFT here is a ground-floor leaf typed exactly ``"C"`` whose id path is a leaf
typed exactly ``"C"`` on every storey above -- `operators._stair_path` without its
"largest C leaf" fallback, and the structure `_stack_levels_above` walks. The
scorer asks for two more things before it counts a staircase (the leaf must be
covered, and `corners_in_use` must be non-empty), so this is the shaft as a
STRUCTURE, which is what an operator can preserve or destroy; it is an upper bound
on the stairs at stake, not a fail count.

Columns, per operator, over (artefact x draw) pairs where the parent had a shaft:

  noop       the operator declined to move (it reports so in its description)
  broke      at least one intact shaft stopped being intact
  moved      ... but the child has a NEW intact shaft: the column RELOCATED, which
             is not a loss. `core_divide` does this every time -- it divides the
             core on every storey at once, so the old address stops being a leaf
             and an aligned pair takes its place
  emptied    ... and the child has NO intact shaft left: the severe case, the one
             worth guarding
  gained     the child has an intact shaft the parent did not have (accidental
             repair -- worth knowing before anyone writes a repair operator)

Each artefact is handled under its own objective's orthogonal-division setting
(`+orth` in the name), since operators read geometry. Trees are canonicalised
through `genome.encode`/`decode` first, because that is the form the search
mutates (upper storeys carry drifted dead fields on disk -- `genome.py`).
"""

from __future__ import annotations

import argparse
import inspect
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from homemaker_layout import dom, driver, genome, geometry, operators, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("harbor-house", "health-centre", "maple-court", "programme-house")


def intact_shafts(lvls: "list[dom.Node]") -> "set[str]":
    """The feet of the building's staircases: ground-floor ``E`` leaves whose
    exact id path is an ``E`` leaf on the storey above (DESIGN.md §39.125;
    until then, ``C`` all the way up)."""
    return set(operators._shaft_paths(lvls))


def _gates() -> "dict[str, bool]":
    """Which operators are live under today's `driver.search` defaults."""
    sig = inspect.signature(driver.search)
    return {name[len("enable_"):]: bool(param.default)
            for name, param in sig.parameters.items()
            if name.startswith("enable_")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--draws", type=int, default=8)
    args = ap.parse_args(argv)
    programmes = args.programme or list(PROGRAMMES)

    gates = _gates()
    # shape_rotate/deslim are gated by `shape_repair`, which decides whether the
    # driver builds the Fitness instance they need at all (§driver "fit_ops").
    gates_for = {"shape_rotate": gates.get("shape_repair", False),
                 "deslim": gates.get("shape_repair", False)}

    stats: dict = defaultdict(
        lambda: dict(n=0, noop=0, broke=0, moved=0, emptied=0, gained=0))
    n_with, n_without = 0, 0

    for prog_name in programmes:
        prog = REPO / "examples" / prog_name
        conf, cost = load_config(prog)
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]
        paths = sorted(prog.glob("coldstart-*.dom"))
        parents: list[tuple[Path, dom.Node, set[str]]] = []

        for path in paths:
            geometry.ORTHOGONAL_DIVISION = "+orth" in path.name
            root = genome.decode(genome.encode(dom.load(str(path))))
            geometry.clear_cache()
            shafts = intact_shafts(dom.levels(root))
            if shafts:
                n_with += 1
                parents.append((path, root, shafts))
            else:
                n_without += 1

        for path, root, before in parents:
            geometry.ORTHOGONAL_DIVISION = "+orth" in path.name
            fit = Fitness(conf, cost)
            for name in sorted(operators.MUTATIONS):
                op = operators.MUTATIONS[name]
                params = inspect.signature(op).parameters
                kw = {}
                if "reqs" in params:
                    kw["reqs"] = reqs
                if "fit" in params:
                    kw["fit"] = fit
                for seed in range(args.draws):
                    geometry.clear_cache()
                    child, desc = op(root, np.random.default_rng(seed), types, **kw)
                    geometry.clear_cache()
                    after = intact_shafts(dom.levels(child))
                    row = stats[name]
                    row["n"] += 1
                    if "noop" in desc:
                        row["noop"] += 1
                    if before - after:
                        row["broke"] += 1
                        if not after:
                            row["emptied"] += 1
                        elif after - before:
                            row["moved"] += 1
                    if after - before:
                        row["gained"] += 1

            # crossover: same programme only (a shared plot), paired with the next
            for other_path, other, _s in parents:
                if other_path is path:
                    continue
                for seed in range(args.draws):
                    geometry.clear_cache()
                    ca, cb, _desc = operators.crossover(
                        root, other, np.random.default_rng(seed))
                    for child in (ca, cb):
                        geometry.clear_cache()
                        after = intact_shafts(dom.levels(child))
                        row = stats["crossover"]
                        row["n"] += 1
                        if before - after:
                            row["broke"] += 1
                            if not after:
                                row["emptied"] += 1
                            elif after - before:
                                row["moved"] += 1
                        if after - before:
                            row["gained"] += 1
                break   # one partner is enough to characterise the move

    geometry.ORTHOGONAL_DIVISION = False
    print(f"parents: {n_with} artefacts with an intact shaft, {n_without} without "
          f"(nothing to break); {args.draws} draws per operator\n")
    print(f"{'operator':22s} {'live':5s} {'draws':>6s} {'noop':>6s} "
          f"{'broke':>11s} {'moved':>6s} {'EMPTIED':>12s} {'gained':>7s}")
    order = sorted(stats, key=lambda k: (-stats[k]["emptied"] / max(1, stats[k]["n"]),
                                         -stats[k]["broke"] / max(1, stats[k]["n"]), k))
    for name in order:
        row = stats[name]
        n = row["n"]
        live = "yes" if gates_for.get(name, gates.get(name, True)) else "GATED"
        print(f"{name:22s} {live:5s} {n:6d} {row['noop']:6d} "
              f"{row['broke']:6d} {100.0 * row['broke'] / n:3.0f}% "
              f"{row['moved']:6d} "
              f"{row['emptied']:6d} {100.0 * row['emptied'] / n:4.0f}% "
              f"{row['gained']:7d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
