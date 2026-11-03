"""Build and pre-test the ordering questionnaire (`homemaker-py-5fje.2`,
DESIGN.md §39.201-§39.203).

Each item is one or more pairs of edits, A and B, to a real design. For every
pair this makes both variants, says what each edit moved (cells and fails),
asks every candidate score which variant is worse, and draws both BLIND
(no score, no fails, the edited cells outlined, each room's target beside its
area). An item goes to the owner only if the candidates disagree on it: an
item they all agree on cannot drop any of them. A1 (value - cost) is
printed but not counted, since at today's rates it is all cost.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/questionnaire.py \\
        --outdir experiments/results/questionnaire

writes `<outdir>/items.json`, which `ask_questionnaire.py` reads, the drawings
and `.dom`s beside it, and a pre-test report on stdout.

Edits move ONE cut or relabel ONE cell. Where several cells of a code could
take an edit, the one changing fewest fails ELSEWHERE is used, then fewest of
its own beyond the one asked about, so an item asks one question. What
remains is printed: the owner judges a plan, side effects and all.

A "ladder" item is a sequence of pairs of rising severity on one side; the
owner's answers find the rung where the preference switches, and that rung
is the number the item measures (a trade-off, not an ordering).
"""
import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diag_aggregation import arms  # noqa: E402
from successive_halving import REPO, load_config  # noqa: E402
import plan_svg  # noqa: E402
from homemaker_layout import dom, geometry, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402

CLEAN9 = "experiments/results/halving-maple-clean/final-clean-9.dom"
BEST1 = "experiments/results/split-stair-race/final-best-1.dom"
PROG = "maple-court"
O5_DESIGN = BEST1
O7_DESIGN = BEST1

# (label, arm, phi): the candidates every item is pre-tested against
CANDIDATES = [("A0 today", "A0", 1e-3),
              ("A1 value-cost", "A1", 1e-3),
              ("P1 equal votes", "P1", 1e-3),
              ("P2 target-weighted", "P2", 1e-3),
              ("P1 unfloored", "P1", 1e-20),
              ("P2 unfloored", "P2", 1e-20),
              ("P1 / cost", "P1c", 1e-3),
              ("P2 / cost", "P2c", 1e-3)]


# --------------------------------------------------------------------------- #
# edits
# --------------------------------------------------------------------------- #

class Ctx:
    def __init__(self):
        d = REPO / "examples" / PROG
        self.prog = d
        self.fit = Fitness(*load_config(d))
        self.reqs = programme.load_programme_dir(str(d))
        self._base = {}

    def base(self, path):
        if path not in self._base:
            root = dom.load(str(REPO / path))
            dom.link(root)
            self._base[path] = (root, self.fails(root))
        return self._base[path]

    def fails(self, root):
        geometry.clear_cache()
        return set(self.fit.score_with_fails(root)[1])


def leaves(root):
    for i, lvl in enumerate(dom.levels(root)):
        for leaf in lvl.leaves():
            yield i, leaf


def find(root, key):
    for i, leaf in leaves(root):
        if (i, leaf.id) == key:
            return leaf
    raise KeyError(key)


def sibling(leaf):
    p = leaf.parent
    return p.right if p.left is leaf else p.left


def set_area(root, key, goal):
    """Move the cut between ``key`` and its sibling until ``key`` has ``goal`` m2.
    Returns the area reached."""
    leaf = find(root, key)
    parent = leaf.parent

    def area_at(x):
        parent.division = [x, x]
        geometry.clear_cache()       # areas are memoised per tree
        return geometry.area(leaf)
    lo, hi = 0.001, 0.999
    rising = area_at(hi) > area_at(lo)
    for _ in range(60):
        mid = (lo + hi) / 2
        if (area_at(mid) < goal) == rising:
            lo = mid
        else:
            hi = mid
    return area_at((lo + hi) / 2)


def own(key, f):
    """Is fail line ``f`` about cell ``key`` or a cell cut out of it?"""
    head = f.split(" ", 1)[0]
    return head.startswith(f"{key[0]}/{key[1]}") and set(head[len(f"{key[0]}/{key[1]}"):]) <= set("lr")


def collateral(ctx, base_fails, root, keys):
    """(fails changed on cells other than ``keys``, fails changed on ``keys``)."""
    diff = ctx.fails(root) ^ base_fails
    other = [f for f in diff if not any(own(k, f) for k in keys)]
    return other, [f for f in diff if f not in other]


def best_edit(ctx, path, trials):
    """``trials`` yields (description, keys, make) with ``make(root)`` editing a
    copy in place and returning False if it cannot; keep the cleanest."""
    base, base_fails = ctx.base(path)
    best = None
    for desc, keys, make in trials:
        root = copy.deepcopy(base)
        dom.link(root)
        geometry.clear_cache()
        if make(root) is False:
            continue
        other, mine = collateral(ctx, base_fails, root, keys)
        rank = (len(other), len(mine))
        if best is None or rank < best[0]:
            best = (rank, desc, keys, root)
    if best is None:
        raise RuntimeError("no cell could take the edit")
    return best[1], best[2], best[3]


def area_trials(ctx, root, code, goal, fixed=None, any_sibling=False):
    """Every cell of ``code`` (or just ``fixed``) set to ``goal`` m2 against its
    sibling, where the sibling is a single corridor or outside cell, so no
    other room changes size."""
    for i, leaf in leaves(root):
        if leaf.type != code or (fixed and (i, leaf.id) != fixed):
            continue
        sib = sibling(leaf)
        if sib.divided or (sib.type not in ("C", "O") and not (fixed or any_sibling)):
            continue
        key = (i, leaf.id)

        def make(r, key=key):
            return abs(set_area(r, key, goal) - goal) < 0.25
        size = ctx.reqs[code].size
        yield f"{code} at {goal:.1f} m2 ({goal / size:.0%} of {size:g})", [key], make


def room_at(ctx, path, code, fraction=None, z=None, fixed=None):
    size, sigma = ctx.reqs[code].size, ctx.reqs[code].size_sigma
    goal = size * fraction if fraction is not None else size - z * sigma

    def build():
        base, _ = ctx.base(path)
        return best_edit(ctx, path, area_trials(ctx, base, code, goal, fixed))
    return build


def rooms_at(ctx, path, code, fraction, n):
    """``n`` cells of ``code`` each at ``fraction`` of target, the cleanest ones."""
    def build():
        base, base_fails = ctx.base(path)
        size = ctx.reqs[code].size
        scored = []
        trials = list(area_trials(ctx, base, code, size * fraction))
        if len(trials) < n:       # no corridor or yard beside enough of them
            trials = list(area_trials(ctx, base, code, size * fraction, any_sibling=True))
        for _, keys, make in trials:
            r = copy.deepcopy(base)
            dom.link(r)
            if make(r) is False:
                continue
            other, mine = collateral(ctx, base_fails, r, keys)
            scored.append(((len(other), len(mine)), keys[0]))
        scored.sort()
        keys = [k for _, k in scored[:n]]
        if len(keys) < n:
            raise RuntimeError(f"only {len(keys)} cells of {code} can take it")
        root = copy.deepcopy(base)
        dom.link(root)
        for k in keys:
            set_area(root, k, size * fraction)
        geometry.clear_cache()
        return f"{n} x {code} at {fraction:.0%} of {size:g} m2", keys, root
    return build


def omit(ctx, path, key):
    def build():
        base, _ = ctx.base(path)
        root = copy.deepcopy(base)
        dom.link(root)
        leaf = find(root, key)
        leaf.type = sibling(leaf).type
        return (f"{find(base, key).type} left out (its cell given to the neighbouring "
                f"{leaf.type})"), [key], root
    return build


def unchanged(ctx, path):
    def build():
        base, _ = ctx.base(path)
        root = copy.deepcopy(base)
        dom.link(root)
        return "as designed", [], root
    return build


def strip(ctx, path, typ, extra, what):
    """``extra`` m2 of ``typ`` cut off a ground-floor yard as a strip touching a
    corridor, rooms untouched. Every yard, rotation and side is tried; the
    cleanest is kept."""
    from homemaker_layout import operators

    def build():
        base, _ = ctx.base(path)

        def trials():
            for i, leaf in leaves(base):
                if i or leaf.type != "O" or geometry.area(leaf) < 2 * extra:
                    continue
                for rot in range(4):
                    for side in ("left", "right"):
                        key = (i, leaf.id)

                        def make(r, key=key, rot=rot, side=side):
                            n = find(r, key)
                            n.division = [0.5, 0.5]
                            n.rotation = rot
                            n.left = dom.Node(type="O")
                            n.right = dom.Node(type="O")
                            n.type = None
                            getattr(n, side).type = typ
                            operators._finalise(r)
                            cut = getattr(n, side)
                            if abs(set_area(r, (0, cut.id), extra) - extra) > 0.25:
                                return False
                            G = geometry.leaf_graph(dom.levels(r)[0])
                            return cut in G and any(
                                m.type == "C" and m is not cut for m in G.neighbors(cut))
                        yield what, [key], make
        desc, keys, root = best_edit(ctx, path, trials())
        k = keys[0]
        cut = [(i, lf.id) for i, lf in leaves(root)
               if i == k[0] and lf.id.startswith(k[1]) and lf.type == typ]
        return desc, cut, root
    return build


def corridor_grown(ctx, path, extra):
    return strip(ctx, path, "C", extra, f"{extra:g} m2 more corridor, a strip cut off the yard")


def extra_room(ctx, path, code, extra):
    return strip(ctx, path, code, extra,
                 f"an extra {ctx.reqs[code].name.lower()} ({code}, {extra:g} m2) nobody asked "
                 "for, cut off the yard")


def disconnect(ctx, path):
    """One circulation cell above the ground relabelled as its neighbour, chosen
    so that a storey loses its connection and as little else changes."""
    def build():
        base, base_fails = ctx.base(path)

        def trials():
            for i, leaf in leaves(base):
                sib = sibling(leaf)
                if not i or leaf.type != "C" or sib.divided or sib.type in ("C", "E"):
                    continue
                key = (i, leaf.id)

                def make(r, key=key, t=sib.type):
                    find(r, key).type = t
                    return any("not connected" in f for f in ctx.fails(r) - base_fails)
                yield f"storey {i} cut off: a corridor cell built over as {sib.type}", [key], make
        return best_edit(ctx, path, trials())
    return build


# --------------------------------------------------------------------------- #
# the items
# --------------------------------------------------------------------------- #

def items(ctx):
    lounge = (0, "ll")       # clean-9's lr1, 69 m2 of 80, beside a 149 m2 yard
    same = {"cost_a": 1.0, "cost_b": 1.0}
    yield dict(id="O1", design=CLEAN9, kind="pair",
               question="Which is worse: the common living room shrunk to a sliver (2% of its "
                        "80 m2), or left out altogether?",
               rungs=[dict(a=room_at(ctx, CLEAN9, "lr1", 0.02, fixed=lounge),
                           b=omit(ctx, CLEAN9, lounge), **same)])
    yield dict(id="O2", design=CLEAN9, kind="pair",
               question="Which is worse: a bathroom at 2.3 m2 (asked 6 +- 1.5), or the common "
                        "living room at 55 m2 (asked 80 +- 10)? The brief calls these equally far "
                        "off: each is 2.5 of its own tolerances short.",
               rungs=[dict(a=room_at(ctx, CLEAN9, "t", z=2.5),
                           b=room_at(ctx, CLEAN9, "lr1", z=2.5, fixed=lounge), **same)])
    yield dict(id="O3", design=CLEAN9, kind="pair",
               question="Which is worse: a bathroom at 60% of its size (3.6 of 6 m2), or the "
                        "common living room at 60% (48 of 80 m2)?",
               rungs=[dict(a=room_at(ctx, CLEAN9, "t", 0.6),
                           b=room_at(ctx, CLEAN9, "lr1", 0.6, fixed=lounge), **same)])
    yield dict(id="O5", design=O5_DESIGN, kind="ladder",
               question="Every room unchanged; B has more corridor, taken out of the yard. Is B "
                        "worse, or no different?",
               measure="the smallest added corridor that makes a plan worse",
               rungs=[dict(a=unchanged(ctx, O5_DESIGN), b=corridor_grown(ctx, O5_DESIGN, m), value=m,
                           **same) for m in (5, 10, 20, 40)])
    yield dict(id="O6", design=CLEAN9, kind="ladder",
               question="A is as designed. B has the common living room at 80% of its size "
                        "(64 of 80 m2) and costs the stated amount less to build. Which is worse?",
               measure="the saving at which a 20%-short living room becomes acceptable",
               rungs=[dict(a=unchanged(ctx, CLEAN9),
                           b=room_at(ctx, CLEAN9, "lr1", 0.8, fixed=lounge),
                           cost_a=1.0, cost_b=1 - y, value=y)
                      for y in (0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4)])
    yield dict(id="O7", design=O7_DESIGN, kind="pair",
               question="Which is worse: as designed, or with an extra room nobody asked for "
                        "built on part of the yard?",
               rungs=[dict(a=unchanged(ctx, O7_DESIGN), b=extra_room(ctx, O7_DESIGN, "m", 10),
                           **same)])
    yield dict(id="O8", design=BEST1, kind="pair",
               question="Which is worse: one storey cut off from the others' circulation, or three "
                        "individual rooms each at 40% of their size (4 of 10 m2)?",
               rungs=[dict(a=disconnect(ctx, BEST1), b=rooms_at(ctx, BEST1, "r", 0.4, 3), **same)])


# --------------------------------------------------------------------------- #

def verdict(sa, sb):
    if abs(sa - sb) <= 0.001 * max(abs(sa), abs(sb)):
        return "="
    return "A" if sa < sb else "B"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--outdir", default="experiments/results/questionnaire")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    ctx = Ctx()
    out = REPO / a.outdir
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for item in items(ctx):
        print(f"\n== {item['id']} ({item['kind']}): {item['question']}", flush=True)
        _, base_fails = ctx.base(item["design"])
        rungs = []
        table = {lab: [] for lab, _, _ in CANDIDATES}
        for n, rung in enumerate(item["rungs"]):
            sides = {}
            for side in ("a", "b"):
                desc, keys, root = rung[side]()
                f = ctx.fails(root)
                stem = f"{item['id']}-{n}-{side}"
                (out / f"{stem}.dom").write_text(dom.dumps(root))
                svg = plan_svg.render(out / f"{stem}.dom", ctx.prog, "", blind=True,
                                      highlight={f"{k[0]}/{k[1]}" for k in keys})
                (out / f"{stem}.svg").write_text(svg)
                cost = rung[f"cost_{side}"]
                if cost != 1.0:
                    desc += f"; costs {1 - cost:.0%} less to build"
                sides[side] = dict(desc=desc, svg=f"{stem}.svg", root=root, cost=cost,
                                   plus=sorted(f - base_fails), minus=sorted(base_fails - f))
                print(f"  rung {n} {side.upper()}: {desc}")
                for x in sides[side]["plus"]:
                    print(f"       + {x}")
                for x in sides[side]["minus"]:
                    print(f"       - {x}")
            for lab, arm, phi in CANDIDATES:
                sa = arms(ctx.fit, ctx.reqs, sides["a"]["root"], phi, sides["a"]["cost"])[arm]
                sb = arms(ctx.fit, ctx.reqs, sides["b"]["root"], phi, sides["b"]["cost"])[arm]
                table[lab].append(verdict(sa, sb))
            rungs.append(dict(value=rung.get("value"),
                              a={k: v for k, v in sides["a"].items() if k != "root"},
                              b={k: v for k, v in sides["b"].items() if k != "root"},
                              worse={lab: table[lab][-1] for lab in table}))
        print("  worse, per rung:      " + " ".join(
            f"{r['value'] if r['value'] is not None else '':>5}" for r in rungs))
        for lab in table:
            print(f"    {lab:20s} " + " ".join(f"{v:>5}" for v in table[lab]))
        # A1 is left out of the test: at today's rates value - cost is all
        # cost (§39.200), so its "=" says nothing about rooms
        useful = len({tuple(v) for k, v in table.items() if not k.startswith("A1")}) > 1
        print(f"  -> {'ASK: the candidates disagree' if useful else 'DROP: every candidate agrees'}",
              flush=True)
        manifest.append(dict(id=item["id"], kind=item["kind"], question=item["question"],
                             measure=item.get("measure"), useful=useful, rungs=rungs))
    (out / "items.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"\nwrote {out / 'items.json'}: "
          f"{sum(m['useful'] for m in manifest)} of {len(manifest)} items to ask")
    return 0


if __name__ == "__main__":
    sys.exit(main())
