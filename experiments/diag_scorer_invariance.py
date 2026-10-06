"""Does the scorer read anything but the building? Four ways to re-describe a
design without changing it, and the score before and after each.

DESIGN.md §39.94 found three defects with ONE such re-description (a v1 -> v2
round trip: renumbered corners, cuts moved by ulps). These are the others that
cost nothing to try:

  translate   the whole plot moved 137.5 m east and 62.25 m north
  rotate      the whole plot turned 33 degrees about the origin
  restart     the plot's corner list started from its next corner (x3)
  mirror      the building reflected, left for right

A building does not know where north is, where the survey's origin was, which
corner the surveyor listed first, or which way round it is -- with one
exception that IS architecture and is why the perimeter is carried along: a
side marked `private` must stay the same side.

Each transformed design is checked BEFORE it is scored: same number of cells,
same types, same areas, storey by storey. A transformation that got the
building wrong would otherwise show up as a "scorer defect". `--self-test`
breaks one on purpose (the mirror without its perimeter) and the report must
show scores moving.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_scorer_invariance.py
"""

from __future__ import annotations

import argparse
import collections
import copy
import importlib.util
import math
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, dom_v2, geometry as g  # noqa: E402

REL_TOL = 1e-6


def _rt():
    spec = importlib.util.spec_from_file_location(
        "_rt", REPO / "experiments" / "diag_8b2u2_roundtrip.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# the re-descriptions
# --------------------------------------------------------------------------- #
def _moved(root, f):
    """A copy of `root` with every stored plot corner passed through `f`."""
    t = copy.deepcopy(root)
    dom.link(t)
    t.node_file = [f(p) for p in t.node_file]
    t.node = g.offset_quad(t.node_file, -(t.wall_outer or 0.25))
    g.clear_cache()
    return t


def translate(root):
    return _moved(root, lambda p: [p[0] + 137.5, p[1] + 62.25])


def rotate(root, degrees: float = 33.0):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return _moved(root, lambda p: [p[0] * c - p[1] * s, p[0] * s + p[1] * c])


def restart(root, k: int = 1):
    """The same plot with its corner list starting `k` corners later. Corner j
    becomes corner j-k, so the root's rotation turns back by k and each
    perimeter side keeps its status under its new letter."""
    t = copy.deepcopy(root)
    dom.link(t)
    t.node_file = t.node_file[k:] + t.node_file[:k]
    t.node = g.offset_quad(t.node_file, -(t.wall_outer or 0.25))
    t.rotation = (t.rotation - k) % 4
    if t.perimeter is not None:
        t.perimeter = {"abcd"[(j - k) % 4]: t.perimeter.get("abcd"[j])
                       for j in range(4)}
    g.clear_cache()
    return t


def mirror(root, keep_perimeter: bool = True):
    """The building reflected in a line parallel to the frame's `u`, by way of
    its v2 document: the plot's points reflected and listed the other way
    round (so they still run anticlockwise), and each side's status carried to
    the side it became.

    The reversed list makes the longest edge run the other way, so the new
    frame is (-u, -v); a reflected point (pu, -pv) reads there as (-pu, pv).
    In the frame, then, the building is flipped along u: a cut that fixes u
    (`cut: v`) moves to 1 - at and swaps its halves, and a `cut: u` stays."""
    doc = yaml.safe_load(dom.dumps(root, version=2))
    u = doc["frame"]["u"]

    def reflect(p):
        along = p[0] * u[0] + p[1] * u[1]
        return [2 * along * u[0] - p[0], 2 * along * u[1] - p[1]]

    n = len(doc["plot"])
    doc["plot"] = [reflect(p) for p in reversed(doc["plot"])]
    if doc.get("perimeter") is not None and keep_perimeter:
        old = doc["perimeter"]
        doc["perimeter"] = [old[(n - 2 - j) % n] for j in range(n)]
    doc["frame"]["u"] = [-u[0], -u[1]]

    # An inherited node writes no `cut`, so each node is first told which axis
    # it cuts on, walking every storey beside the one below it.
    def mark(t, below):
        if "cell" in t:
            return
        t["_axis"] = t.get("cut") or below["_axis"]
        for side in ("low", "high"):
            under = below[side] if below is not None and "cell" not in below else None
            mark(t[side], under)

    def flip(t):
        if "cell" in t:
            return t
        out = {k: v for k, v in t.items() if k not in ("low", "high", "_axis")}
        low, high = flip(t["low"]), flip(t["high"])
        if t["_axis"] == "v":                 # fixes u: the flipped coordinate
            if "at" in out:
                out["at"] = 1.0 - out["at"]
            low, high = high, low
        out["low"], out["high"] = low, high
        return out

    prev = None
    for storey in doc["storeys"]:
        mark(storey["tree"], prev)
        prev = storey["tree"]
    for storey in doc["storeys"]:
        storey["tree"] = flip(storey["tree"])
    return dom_v2.from_document(doc)


class relisted:
    """Context: every storey's cells and walls handed to the scorer in a
    shuffled order. Not a re-description of the building at all -- the same
    tree, the same file -- only of the order things are listed in, which
    follows the tree's left/right naming (`homemaker-py-rwwv`)."""

    def __init__(self, seed: int):
        self.seed = seed

    def __enter__(self):
        import random

        import networkx as nx

        self._orig = orig = g.leaf_graph
        seed = self.seed

        def shuffled(level_root, door_width=1.2):
            G = orig(level_root, door_width)
            rng = random.Random(seed)
            nodes = list(G.nodes())
            rng.shuffle(nodes)
            edges = list(G.edges(data=True))
            rng.shuffle(edges)
            H = nx.Graph()
            H.add_nodes_from(nodes)
            for a, b, d in edges:
                if rng.random() < 0.5:
                    a, b = b, a
                H.add_edge(a, b, **d)
            return H

        g.leaf_graph = shuffled
        return self

    def __exit__(self, *exc):
        g.leaf_graph = self._orig


TRANSFORMS = {
    "translate": [translate],
    "rotate": [rotate],
    "restart": [lambda r, k=k: restart(r, k) for k in (1, 2, 3)],
    "mirror": [mirror],
}


# --------------------------------------------------------------------------- #
def census(root) -> list:
    """(storey, type, area) of every cell: what any honest re-description of
    a building must leave alone."""
    out = sorted((li, lf.type or "", g.area(lf))
                 for li, lvl in enumerate(dom.levels(root)) for lf in lvl.leaves())
    g.clear_cache()
    return out


def same_building(a: list, b: list) -> bool:
    return len(a) == len(b) and all(
        x[:2] == y[:2] and abs(x[2] - y[2]) < 1e-6 for x, y in zip(a, b))


def run(names, paths, rt, broken: bool = False) -> int:
    tot = collections.defaultdict(collections.Counter)
    for p, prog in paths:
        base = dom.load(str(p))
        s0, f0 = rt.score(base, prog)
        c0 = census(base)
        for name in names:
            fns = TRANSFORMS[name]
            if broken and name == "mirror":
                fns = [lambda r: mirror(r, keep_perimeter=False)]
            for fn in fns:
                row = tot[name]
                row["trials"] += 1
                try:
                    t = fn(base)
                except dom_v2.DomFormatError:
                    row["not expressible"] += 1
                    continue
                if not same_building(census(t), c0):
                    row["BUILDING CHANGED"] += 1
                    continue
                s, f = rt.score(t, prog)
                if rt.differs(s, s0, REL_TOL) or len(f) != len(f0):
                    row["score moved"] += 1
                    row["fail count moved"] += len(f) != len(f0)
                    row["_worst"] = max(row["_worst"], int(1000 * max(s / s0, s0 / s)))
                    if row["score moved"] <= 3:
                        print(f"  {name}: {p.relative_to(REPO)}  {s0:.6g} -> {s:.6g}"
                              f"  fails {len(f0)} -> {len(f)}")
    print()
    for name in names:
        row = tot[name]
        worst = f", largest x{row['_worst'] / 1000:.2f}" if row["_worst"] else ""
        extra = "".join(f", {k} {v}" for k, v in row.items()
                        if k in ("BUILDING CHANGED", "not expressible", "fail count moved"))
        print(f"{name:10} {row['trials']:4d} trials, score moved {row['score moved']}"
              f"{worst}{extra}")
    return sum(tot[n]["score moved"] + tot[n]["BUILDING CHANGED"] for n in names)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", choices=sorted(TRANSFORMS), action="append")
    ap.add_argument("--sample", action="store_true",
                    help="one artefact per (programme, corpus) instead of all 192")
    ap.add_argument("--self-test", action="store_true",
                    help="negative control: mirror WITHOUT carrying the perimeter; "
                         "scores must move")
    args = ap.parse_args(argv)
    g.ORTHOGONAL_DIVISION = True
    rt = _rt()
    paths = rt.corpus()
    if args.sample:
        seen, keep = set(), []
        for p, prog in paths:
            if (prog.name, p.parent.name) not in seen:
                seen.add((prog.name, p.parent.name))
                keep.append((p, prog))
        paths = keep
    if args.self_test:
        moved = run(["mirror"], paths, rt, broken=True)
        print("self-test: control " + ("fired" if moved else "DID NOT FIRE"))
        return 0 if moved else 1
    return 1 if run(args.only or list(TRANSFORMS), paths, rt) else 0


if __name__ == "__main__":
    raise SystemExit(main())
