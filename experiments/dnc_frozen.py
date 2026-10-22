"""Divide and conquer with exact context (`homemaker-py-2g7.13.1.5`, DESIGN.md
§39.165/§39.166): search ONE region of a whole building while everything
outside it stays as it is.

§39.165 cut a wing out and solved it on its own plot. Inside the wing that
did as well as the whole-building search; pasted back, it lost every relation
that crossed the cut -- the next wing's rooms lost their corridor, a moved
stair left the building one short. A stand-alone plot can only approximate
its neighbours with side labels. This keeps the real neighbours instead: the
search runs on the whole building, every child is scored as a whole building,
and only the region may change.

    paste   put a stand-alone wing (dnc_wing_pilot.py's frame) back into a
            building at --wing, and score the result
    search  `homemaker-evolve` on a design with everything outside --region
            frozen; any other arguments go to homemaker-evolve unchanged
    check   say what changed outside --region between two designs
    regions the regions a round of frozen searches visits (`regions()`)

What "frozen" means, and how it is enforced without touching `src/`:

  * topology, cut ratios, rotations and cell types outside the region (on
    every storey, the region's ancestors included) -- a mutation or crossover
    child that changes any of them is drawn again (up to MAX_DRAWS times, then
    the parent is re-evaluated unchanged);
  * the inner loop optimises only the cuts inside the region
    (`solver.free_branches` and `innerloop.free_with_keys` are filtered);
  * the storey count, since a storey added or removed changes the outside.

What is NOT frozen: the in-search room collapse with label write-back (both
defaults) may relabel ROOM cells anywhere, because it relabels the building
as the scorer sees it. `check` counts how many outside cells it relabelled.
Pass `--no-label-writeback` for a strict freeze. Run with `--workers 1` (the
default): the patches live in this process.
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, geometry  # noqa: E402

MAX_DRAWS = 200


# --------------------------------------------------------------------------- #
# The outside of a region
# --------------------------------------------------------------------------- #
def _inside(path: str, region: str) -> bool:
    return path.startswith(region)


def outside(root: dom.Node, region: str, labels: bool = True) -> tuple:
    """Everything that may not change: per storey, every node not in the
    region, with the genes that drive geometry (an inherited cut's ratio and
    rotation are dead fields and left out) and, for a leaf, its type."""
    out = []
    for li, lvl in enumerate(dom.levels(root)):
        stack = [lvl]
        while stack:
            n = stack.pop()
            if _inside(n.id, region):
                continue
            free = n.below is None or not n.below.divided
            rec = (li, n.id, n.divided,
                   n.rotation % 4 if free else None,
                   tuple(round(x, 12) for x in n.division) if (n.divided and free) else None,
                   None if n.divided else (n.type if labels else
                                           (n.type if n.type in dom.GENERIC_TYPES else "room")))
            out.append(rec)
            if n.divided:
                stack += [n.left, n.right]
    return tuple(out)


def diff(a: dom.Node, b: dom.Node, region: str) -> tuple[int, int]:
    """(structural differences, room cells relabelled) outside the region."""
    sa, sb = set(outside(a, region, labels=False)), set(outside(b, region, labels=False))
    struct = len(sa ^ sb)
    la = {r[:2]: r[5] for r in outside(a, region) if r[5] is not None}
    lb = {r[:2]: r[5] for r in outside(b, region) if r[5] is not None}
    relab = sum(1 for k in la if k in lb and la[k] != lb[k])
    return struct, relab


# --------------------------------------------------------------------------- #
# The freeze
# --------------------------------------------------------------------------- #
STATS = {"children": 0, "draws": 0, "gave_up": 0}


def install(region: str) -> None:
    from homemaker_layout import innerloop, operators, solver

    real_mutate, real_cross = operators.mutate, operators.crossover
    real_free, real_fwk = solver.free_branches, innerloop.free_with_keys

    def mutate(root, rng, types, **kw):
        ref = outside(root, region)
        STATS["children"] += 1
        for _ in range(MAX_DRAWS):
            STATS["draws"] += 1
            child, desc = real_mutate(root, rng, types, **kw)
            if outside(child, region) == ref:
                return child, desc
        STATS["gave_up"] += 1
        c = copy.deepcopy(root)
        dom.link(c)
        return c, "frozen noop"

    def crossover(a, b, rng):
        ref = outside(a, region)
        STATS["children"] += 1
        for _ in range(MAX_DRAWS):
            STATS["draws"] += 1
            ca, cb, desc = real_cross(a, b, rng)
            if outside(ca, region) == ref:
                return ca, cb, desc
        STATS["gave_up"] += 1
        c = copy.deepcopy(a)
        dom.link(c)
        return c, copy.deepcopy(b), "frozen noop"

    def free_branches(root):
        return [b for b in real_free(root) if _inside(b.id, region)]

    def free_with_keys(root):
        return [(k, b) for k, b in real_fwk(root) if _inside(b.id, region)]

    operators.mutate, operators.crossover = mutate, crossover
    solver.free_branches, innerloop.free_with_keys = free_branches, free_with_keys
    # driver imported these names as module attributes, so the patches reach it


# --------------------------------------------------------------------------- #
# Paste a stand-alone wing back
# --------------------------------------------------------------------------- #
def paste(design: dom.Node, wing: dom.Node, path: str) -> dom.Node:
    """``design`` with the subtree at ``path`` on every storey replaced by the
    stand-alone ``wing``'s storeys. The wing's root was drawn in the wing's
    own frame (corner i of its root is corner i of the node), so its cuts and
    rotations below the root transfer unchanged; its root's rotation is 0 by
    construction, and the node keeps its own."""
    out = copy.deepcopy(design)
    lvls, wl = dom.levels(out), dom.levels(wing)
    if len(lvls) != len(wl):
        raise SystemExit(f"{len(wl)} wing storeys against {len(lvls)} in the building")
    for lvl, w in zip(lvls, wl):
        n = lvl.by_id(path)
        if n is None:
            raise SystemExit(f"no node at {path!r}")
        if w.rotation % 4:
            raise SystemExit("the wing's root is not in its own frame (rotation != 0)")
        sub = copy.deepcopy(w)
        n.type, n.division, n.left, n.right = sub.type, sub.division, sub.left, sub.right
    dom.link(out)
    geometry.clear_cache()
    return out


def regions(root: dom.Node, max_cells: int) -> list[str]:
    """A partition of the building into regions for a round of frozen
    searches: descend from the root until a subtree holds at most
    ``max_cells`` cells on every storey. A region that is a single outdoor
    leaf on every storey (a court) is left out -- there is nothing in it to
    search. Paths are ground-storey paths; the same path is the region on
    every storey."""
    lvls = dom.levels(root)

    def cells(path):
        ns = [lvl.by_id(path) for lvl in lvls]
        return max(len(n.leaves()) if n is not None else 0 for n in ns)

    out = []

    def walk(n):
        if n.divided and cells(n.id) > max_cells:
            walk(n.left)
            walk(n.right)
            return
        ns = [lvl.by_id(n.id) for lvl in lvls]
        if all(m is not None and not m.divided and m.type in dom.GENERIC_OUTSIDE for m in ns):
            return
        out.append(n.id)

    walk(lvls[0])
    return out


def _score(root, prog):
    from homemaker_layout.fitness import Fitness, load_config

    geometry.clear_cache()
    s, fails = Fitness(*load_config(str(prog))).score_with_fails(copy.deepcopy(root))
    return s, fails


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("paste")
    p.add_argument("design", type=Path)
    p.add_argument("wing", type=Path)
    p.add_argument("--wing-path", default="l")
    p.add_argument("--programme", default="harbor-house")
    p.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("search")
    s.add_argument("design", type=Path)
    s.add_argument("--region", required=True)
    s.add_argument("--programme", default="harbor-house")
    c = sub.add_parser("check")
    c.add_argument("before", type=Path)
    c.add_argument("after", type=Path)
    c.add_argument("--region", required=True)
    g = sub.add_parser("regions")
    g.add_argument("design", type=Path)
    g.add_argument("--max-cells", type=int, default=16)
    args, rest = ap.parse_known_args(argv)
    prog = REPO / "examples" / getattr(args, "programme", "harbor-house")

    if args.cmd == "regions":
        print(" ".join(repr(p)[1:-1] or "''" for p in regions(dom.load(str(args.design)),
                                                             args.max_cells)))
        return 0

    if args.cmd == "paste":
        if rest:
            ap.error(f"unrecognised arguments: {rest}")
        out = paste(dom.load(str(args.design)), dom.load(str(args.wing)), args.wing_path)
        dom.dump(out, str(args.out))
        sc, fails = _score(dom.load(str(args.out)), prog)
        print(f"{args.out.name}: {len(fails)} fails, score {sc:.4g}")
        for f in fails:
            print(f"    {f}")
        return 0

    if args.cmd == "check":
        a, b = dom.load(str(args.before)), dom.load(str(args.after))
        st, rl = diff(a, b, args.region)
        print(f"outside {args.region!r}: {st} structural differences, {rl} room cells relabelled")
        return 0 if st == 0 else 1

    # search
    install(args.region)
    from homemaker_layout import evolve

    seed = dom.load(str(args.design))
    print(f"frozen       : everything outside {args.region!r} "
          f"({len(outside(seed, args.region))} nodes)", file=sys.stderr, flush=True)
    rc = evolve.main([str(args.design), "--programme-dir", str(prog), *rest])
    print(f"frozen draws : {STATS['draws']} for {STATS['children']} children, "
          f"{STATS['gave_up']} gave up", file=sys.stderr)
    out = rest[rest.index("--output") + 1] if "--output" in rest else None
    if out and Path(out).is_file():
        st, rl = diff(seed, dom.load(out), args.region)
        print(f"outside {args.region!r}: {st} structural differences, "
              f"{rl} room cells relabelled", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
