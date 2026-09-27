"""`homemaker-py-m4d`: how much of the corpus loses its stair to the exact-path rule?

`graph.stack_corners_in_use` counts a staircase only where `_stack_levels_above`
finds a leaf typed exactly `"C"` at the SAME id path on every storey, because it
walks `dom._above_node` (Urb's `Above`). Every other vertical predicate in `dom`
walks `_above_more`/`_below_more` (Urb's `Above_More`), which falls back to the
nearest existing ancestor. So a storey that MERGES the cell over the stair -- one
circulation leaf covering the stair and its neighbour -- breaks the stack, and the
building loses its staircase: `too few stairs`, plus `staircase volume` at its
0.09 floor, which is a x0.045 multiplier between them.

This counts what that costs the committed corpus, which is what the bead asks for
before anybody proposes changing an objective source. Two censuses:

CENSUS 1 -- structural, per ground-floor circulation leaf:

  exact        the stack spans with exact addresses, all "C": the scorer accepts it
  merged       an address is absent above and the covering node is a single "C"
               LEAF -- the m4d case, a landing spanning the stair
  split        the covering node exists but is DIVIDED: the stair's footprint is
               subdivided upstairs, which the permissive walk does not rescue
               either (a different question, left alone here)
  not-c        the covering leaf exists and is not circulation: genuinely no stair

CENSUS 2 -- the counterfactual. Re-score every artefact with `_stack_levels_above`
walking `_above_more` and requiring a LEAF, and diff (score, fails) against the
committed rule. That is the minimal permissive change; nothing else moves.

Each artefact is scored under its OWN objective's orthogonal-division setting
(`+orth` in the filename), because the switch changes every layout (§39.12
clause 3). The comparison here is strict-vs-permissive on one artefact at a time,
so it is valid across stamps in a way a score comparison would not be.

    python experiments/diag_m4d_stair_stack.py [--programme NAME]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homemaker_layout import dom, geometry, graph as graph_mod  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("harbor-house", "health-centre", "maple-court", "programme-house")


# --------------------------------------------------------------------------- #
# the permissive walk: the one line this bead is about
# --------------------------------------------------------------------------- #
def _permissive_stack(leaf: dom.Node) -> list[dom.Node]:
    """`graph._stack_levels_above` with `_above_more` instead of `_above_node`."""
    out: list[dom.Node] = []
    node = leaf
    while True:
        above = dom._above_more(node)
        if above is None or above.divided:
            break
        out.append(above)
        node = above
    return out


def classify(leaf: dom.Node, lvls: list[dom.Node]) -> str:
    """Why (or whether) this ground circulation leaf's stack reaches the top."""
    node = leaf
    for lvl in lvls[1:]:
        exact = lvl.by_id(node.id)
        if exact is not None and not exact.divided:
            if exact.type != "C":
                return "not-c"
            node = exact
            continue
        cover = dom._above_more(node)
        if cover is None:
            return "not-c"
        if cover.divided:
            return "split"
        if cover.type != "C":
            return "not-c"
        return "merged"          # first divergence decides the label
    return "exact"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--programme", action="append", choices=PROGRAMMES,
                    help="restrict to these (default: all four)")
    ap.add_argument("--census-only", action="store_true",
                    help="skip the counterfactual re-scoring (seconds, not minutes)")
    args = ap.parse_args(argv)
    programmes = args.programme or list(PROGRAMMES)

    census = {"exact": 0, "merged": 0, "split": 0, "not-c": 0}
    art_merged = 0       # artefacts carrying at least one merged stack
    art_no_exact = 0     # ... and no exact one either: no stair the scorer takes
    affected: list = []
    n_art = 0
    n_single = 0

    for prog_name in programmes:
        prog = REPO / "examples" / prog_name
        conf, cost = load_config(prog)
        for path in sorted(prog.glob("coldstart-*.dom")):
            n_art += 1
            orth = "+orth" in path.name
            geometry.ORTHOGONAL_DIVISION = orth
            fitness = Fitness(conf, cost)

            root = dom.load(str(path))
            geometry.clear_cache()
            lvls = dom.levels(root)
            if len(lvls) < 2:
                n_single += 1
            else:
                kinds = [classify(lf, lvls) for lf in lvls[0].leaves()
                         if lf.type == "C"]
                for kind in kinds:
                    census[kind] += 1
                if "merged" in kinds:
                    art_merged += 1
                    if "exact" not in kinds:
                        art_no_exact += 1

            if args.census_only:
                continue
            strict_score, strict_fails = fitness.score_with_fails(root)
            saved = graph_mod._stack_levels_above
            graph_mod._stack_levels_above = _permissive_stack
            try:
                root2 = dom.load(str(path))
                geometry.clear_cache()
                loose_score, loose_fails = Fitness(conf, cost).score_with_fails(root2)
            finally:
                graph_mod._stack_levels_above = saved
                geometry.clear_cache()

            if (len(loose_fails), loose_score) != (len(strict_fails), strict_score):
                gone = sorted(set(strict_fails) - set(loose_fails))
                new = sorted(set(loose_fails) - set(strict_fails))
                affected.append((prog_name, path.name, strict_score, loose_score,
                                 len(strict_fails), len(loose_fails), gone, new))

    geometry.ORTHOGONAL_DIVISION = False
    print("### census 1: ground-floor circulation leaves, by why the stack ends")
    total = sum(census.values())
    for key in ("exact", "merged", "split", "not-c"):
        share = 100.0 * census[key] / total if total else 0.0
        print(f"  {key:8s} {census[key]:4d}  ({share:4.1f}%)")
    print(f"  {'total':8s} {total:4d}   over {n_art} artefacts"
          f" ({n_single} single-storey, no stack to walk)")
    print(f"  {art_merged} artefact(s) carry at least one MERGED stack; "
          f"{art_no_exact} of those have no exact one either, so they have no "
          f"staircase at all as scored")
    if args.census_only:
        return 0

    print("\n### census 2: artefacts whose score or fail set moves under the "
          "permissive walk")
    if not affected:
        print("  none")
    for prog_name, name, s_score, l_score, s_n, l_n, gone, new in affected:
        ratio = (l_score / s_score) if s_score else float("inf")
        print(f"  {prog_name:15s} {name.replace('coldstart-', ''):28s} "
              f"{s_score:11.6g} {s_n:2d}f -> {l_score:11.6g} {l_n:2d}f  "
              f"x{ratio:.3g}")
        if gone:
            print(f"  {'':15s} {'':28s} clears: {gone}")
        if new:
            print(f"  {'':15s} {'':28s} ADDS:   {new}")
    print(f"\n  {len(affected)} of {n_art} artefacts affected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
