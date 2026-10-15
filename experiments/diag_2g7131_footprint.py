"""`homemaker-py-2g7.13.1` step 0: is it the drawing's FOOTPRINT that wins?

DESIGN.md §39.142: seeded from the owner's drawing, harbor-house ends at 9.7
fails against 29.7 cold. The owner's reading (2026-10-15) is that the drawing
wins because its plan is "wings of light" -- hand2a's ground floor is an E, a
spine on the street with three wings and two courts -- and proposes a catalogue
of such parti as seeds. That is only the right lever if the footprint carries
the gap, rather than the rooms the owner placed inside it. This separates them
without a search, in the manner of `diag_2g713_seed_storeys.py`: build seeds,
give each the same inner-loop tune, compare fails.

Arms, each built from hand2a by the constructor's own pieces:

  hand       hand2a as drawn.
  relabel    hand2a's every wall kept; the room labels stripped (all but O and
             E) and re-placed by the constructor's assignment, the stairs as
             its fixed core. What the owner's PLACEMENT of rooms is worth.
  footprint  hand2a's O and E cells kept; every maximal subtree holding
             neither -- a wing, or a block of wings -- collapsed to one cell
             and refilled by the constructor: grown to the storey's room count
             plus circulation, rooms placed round a spine grown from the
             stairs, cuts sized from targets. The drawing's footprint and
             cores, nothing else of it.
  nocore     as footprint, but the E cells are refilled too: footprint only,
             no stairs (the cold constructor builds none, §39.143).
  cold2/3    the cold constructor at 2 and 3 storeys (§39.143's arms).

Every arm but the cold ones takes each storey's room multiset from hand2a, so
the rooms-per-storey split is held equal across them; the cold arms make their
own, as a cold run does.

On a storey above the ground, a refilled subtree inherits the cuts of the one
below it wherever the paths coincide (Urb's rule), so an upper storey's wings
follow the ground's new walls, as `lift_base_to_storeys`' do.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_2g7131_footprint.py
    ... --seeds 6 --budget 600 --arms hand relabel footprint nocore cold2

`--write DIR` saves each built seed, untuned, as `<arm>-s<N>.dom` -- what a
box A/B warm-starts `homemaker-evolve` from, as §39.142 did from `hand2a`.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diag_2g713_seed_storeys import constructor_kwargs, family, rng_for  # noqa: E402

from homemaker_layout import dom, geometry, innerloop, operators, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GENERIC = {"C", "O", "E"}


def walk(n: dom.Node):
    yield n
    if n.divided:
        yield from walk(n.left)
        yield from walk(n.right)


def wing_roots(lvl: dom.Node, keep: set[str]) -> list[dom.Node]:
    """Maximal subtrees of ``lvl`` none of whose leaves is typed in ``keep``.
    A quad tree (what `dom.load` gives a v1 file) has no void leaves."""
    out = []

    def rec(n):
        if all(lf.type not in keep for lf in walk(n) if not lf.divided):
            out.append(n)
        elif n.divided:
            rec(n.left)
            rec(n.right)
    rec(lvl)
    return out


def collapse(n: dom.Node) -> None:
    n.left = n.right = None
    n.division = None
    n.type = "C"


def rooms_of(lvl: dom.Node) -> list[str]:
    return [lf.type for lf in lvl.leaves() if lf.type not in GENERIC]


def grow(lvl: dom.Node, scope: list[dom.Node], n_target: int, rng) -> list[dom.Node]:
    """Split the largest cell in ``scope`` until it holds ``n_target`` cells;
    random cut direction, as the constructor's `_grow_leaves`. Returns the
    scope's leaves."""
    scope = list(scope)
    while len(scope) < n_target:
        geometry.clear_cache()
        leaf = max(scope, key=lambda lf: (geometry.area(lf), -scope.index(lf)))
        leaf.division = [0.5, 0.5]
        leaf.rotation = int(rng.integers(4))
        leaf.left = dom.Node(type="C")
        leaf.right = dom.Node(type="C")
        leaf.type = None
        scope.remove(leaf)
        scope += [leaf.left, leaf.right]
        dom.link(lvl)
    return scope


def refill(root: dom.Node, reqs, rng, keep: set[str], kw: dict) -> dom.Node:
    """Collapse every storey's wings (subtrees with no ``keep`` cell) and refill
    them with that storey's rooms, bottom storey first."""
    import copy
    root = copy.deepcopy(root)
    dom.link(root)
    for lvl in dom.levels(root):
        rooms = rooms_of(lvl)
        wings = wing_roots(lvl, keep)
        for w in wings:
            collapse(w)
        dom.link(root)
        n_circ = max(1, -(-len(rooms) // kw["circ_divisor"]))
        # +1: `_assign_adjacency_aware` always places at least one O in scope;
        # it is turned back into circulation below, so the footprint is kept.
        scope = grow(lvl, wings, len(rooms) + n_circ + 1, rng) if wings else []
        if not scope:
            continue
        fixed = [lf for lf in lvl.leaves() if lf.type == "E"]
        operators._assign_adjacency_aware(
            lvl, rooms, reqs, rng, fixed_circ=fixed or None,
            interior_outside=True, n_outside=1, scope=set(scope))
        for lf in scope:
            if lf.type == "O":
                lf.type = "C"
        dom.link(root)
        for w in wings:
            if w.divided:
                operators._size_divisions_from_targets(w, reqs)
        dom.link(root)
    return operators._finalise(root)


def relabel(root: dom.Node, reqs, rng) -> dom.Node:
    import copy
    root = copy.deepcopy(root)
    dom.link(root)
    for lvl in dom.levels(root):
        rooms = rooms_of(lvl)
        scope = {lf for lf in lvl.leaves() if lf.type not in {"O", "E"}}
        fixed = [lf for lf in lvl.leaves() if lf.type == "E"]
        # the drawing's O cells stay; one more O is forced into scope -- give
        # it back to circulation as above
        operators._assign_adjacency_aware(
            lvl, rooms, reqs, rng, fixed_circ=fixed or None,
            interior_outside=True, n_outside=1, scope=scope)
        for lf in scope:
            if lf.type == "O":
                lf.type = "C"
    return operators._finalise(root)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default="harbor-house")
    ap.add_argument("--hand", default="hand2a.dom")
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--budget", type=int, default=600)
    ap.add_argument("--write", default=None,
                    help="directory to save each untuned seed in")
    ap.add_argument("--arms", nargs="+",
                    default=["hand", "relabel", "footprint", "nocore", "cold2", "cold3"])
    args = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        print("set HOMEMAKER_ORTHOGONAL_DIVISION=1", file=sys.stderr)
        return 2

    prog = REPO / "examples" / args.programme
    conf, cost = load_config(prog)
    fit = Fitness(conf, cost)
    reqs = programme.load_programme_dir(str(prog))
    types = sorted(reqs) + ["C", "O"]
    init = dom.load(str(prog / "init.dom"))
    hand = dom.load(str(prog / args.hand))
    kw = constructor_kwargs()

    def build(arm, s):
        rng = rng_for(args.programme, arm, s)
        if arm == "hand":
            import copy
            return copy.deepcopy(hand)
        if arm == "relabel":
            return relabel(hand, reqs, rng)
        if arm == "footprint":
            return refill(hand, reqs, rng, {"O", "E"}, kw)
        if arm == "nocore":
            return refill(hand, reqs, rng, {"O"}, kw)
        if arm.startswith("cold"):
            return operators.constructive_topology(
                init, reqs, rng_for(args.programme, s), types,
                min_storeys=int(arm[4:]), **kw)
        raise SystemExit(f"unknown arm {arm}")

    def tuned(root):
        geometry.clear_cache()
        raw = len(fit.score_with_fails(root)[1])
        res = innerloop.optimise(root, str(prog), budget=args.budget, method="nm")
        geometry.clear_cache()
        _s, fails = fit.score_with_fails(root)
        return raw, res.fitness, list(fails)

    rows: dict[str, list] = {}
    for arm in args.arms:
        rows[arm] = []
        for s in range(1 if arm == "hand" else args.seeds):
            root = build(arm, s)
            if args.write and arm != "hand":
                Path(args.write).mkdir(parents=True, exist_ok=True)
                dom.dump(root, str(Path(args.write) / f"{arm}-s{s}.dom"))
            lv = dom.levels(root)
            stairs = len(operators._shaft_feet(lv))
            o_cells = sum(lf.type == "O" for lf in lv[0].leaves())
            raw, score, fails = tuned(root)
            rows[arm].append((raw, len(fails), score, stairs, fails))
            print(f"  {arm} s{s}: {len(lv)} storeys, {sum(len(l.leaves()) for l in lv)} "
                  f"cells, {o_cells} O on the ground, {stairs} shaft(s); "
                  f"{raw} fails raw -> {len(fails)} tuned, score {score:.3g}", flush=True)

    print(f"\n{args.programme}: {args.seeds} seeds per arm, "
          f"{args.budget} inner-loop evaluations each")
    for arm, rs in rows.items():
        t = [r[1] for r in rs]
        fam = Counter(family(f) for r in rs for f in r[4])
        print(f"  {arm:9s} raw {statistics.mean(r[0] for r in rs):5.1f}  "
              f"tuned {statistics.mean(t):5.1f} ({min(t)}-{max(t)})  "
              f"shafts {dict(Counter(r[3] for r in rs))}")
        print("            " + ", ".join(f"{k} {v / len(rs):.1f}"
                                         for k, v in fam.most_common(7)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
