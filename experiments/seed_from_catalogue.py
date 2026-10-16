"""`homemaker-py-2g7.13.1`: seed a project from the wings-of-light catalogue.

The owner (2026-10-15): "find all the likely seed layouts that are generically
possible and feed them into every project (maybe with some filtering)".
`wings_catalogue.py` enumerates the parti once, in storey heights; this takes
a project and

1. reads its plot as a rectangle in storey heights -- the frame's two side
   lengths over the storey height -- with a side giving light unless the
   brief calls it ``private`` or ``fortified`` (what `area_outside` reads);
2. asks the cover its ground floor needs at each storey count the brief
   allows: the programme's room area, plus a circulation share, over storeys
   and plot;
3. sizes every catalogue tree, in every orientation the plot distinguishes,
   to the feasible plan nearest that cover (every built point within 1.62 h of
   a lit wall, the scorer's own number) -- the FILTER -- keeping one tree per
   outline drawn;
4. draws each survivor on the project's real plot as a quad tree (a run of
   parallel strips becomes a chain of cuts), stacks the storeys with the
   courts open to the sky, fills the built cells with the programme's rooms by
   the constructor's own growth, assignment and sizing (as
   `diag_2g7131_footprint.py` refilled hand2a's wings), and tunes it briefly;
5. reports them ranked, and with ``--write`` saves the best as
   ``wings-<rank>.dom`` for `homemaker-evolve` to warm-start from.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/seed_from_catalogue.py \\
        --programme harbor-house --leaves 6 --max-seeds 40 --budget 200 --write 3
"""

from __future__ import annotations

import argparse
import copy
import itertools
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402

import wings_catalogue as wc  # noqa: E402
from diag_2g713_seed_storeys import constructor_kwargs, family, rng_for  # noqa: E402
from diag_2g7131_footprint import grow  # noqa: E402

from homemaker_layout import dom, genome, geometry, graph, innerloop, operators, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DARK = {"private", "fortified"}


def plot_of(init: dom.Node, res_cells: int = 32):
    """The plot as a catalogue `Plot`: corner 0 -> 1 is x (side a, "south"),
    1 -> 2 is y (side b, "east"); opposite sides averaged."""
    c = [np.array(geometry.coordinate(init, i)) for i in range(4)]
    w = (np.linalg.norm(c[1] - c[0]) + np.linalg.norm(c[2] - c[3])) / 2
    d = (np.linalg.norm(c[2] - c[1]) + np.linalg.norm(c[3] - c[0])) / 2
    h = float(init.height or 3.0)
    per = init.perimeter or {}
    lit = tuple((str(per.get(k) or "").lower() not in DARK) for k in "abcd")
    res = max(0.25, max(w, d) / h / res_cells)
    return wc.Plot(round(w / h / res), round(d / h / res), res, lit), (w, d, h)


def frame_axes(init: dom.Node):
    c = [np.array(geometry.coordinate(init, i)) for i in range(4)]
    x = c[1] - c[0]
    x /= np.linalg.norm(x)
    return x, np.array([-x[1], x[0]])


def to_quad(t, sizes, lvl: dom.Node, root: dom.Node, axes) -> None:
    """Draw catalogue tree ``t`` (with strip widths ``sizes``) into the
    undivided storey node ``lvl``. A k-strip node becomes a chain: the first
    strip cut off, the rest cut again on the same axis. Each cut's rotation is
    whichever of the four puts the first strip on the low side of the axis."""
    if isinstance(t, str):
        lvl.type = "O" if t == "O" else "C"
        return
    ax, kids = t
    widths = list(sizes[id(t)])
    axis = axes[0] if ax == "V" else axes[1]
    node = lvl
    for i, kid in enumerate(kids[:-1]):
        f = float(widths[i] / sum(widths[i:]))  # numpy floats do not dump to YAML
        node.type = None
        node.division = [f, f]
        node.left, node.right = dom.Node(type="C"), dom.Node(type="C")
        best = None
        for rot in range(4):
            node.rotation = rot
            dom.link(root)
            geometry.clear_cache()
            gap = (np.dot(geometry.centroid(node.right), axis)
                   - np.dot(geometry.centroid(node.left), axis))
            if best is None or gap > best[0]:
                best = (gap, rot)
        node.rotation = best[1]
        dom.link(root)
        geometry.clear_cache()
        to_quad(kid, sizes, node.left, root, axes)
        node = node.right
    to_quad(kids[-1], sizes, node, root, axes)


def buckets(reqs, n_storeys: int, rng) -> list[list[str]]:
    """The constructor's partition of rooms over storeys (level-bound rooms to
    their storey, the rest round-robin over a shuffled order)."""
    prog = operators._programme_codes(reqs)
    out: list[list[str]] = [[] for _ in range(n_storeys)]
    free = []
    for code, req in prog.items():
        for _ in range(req.count):
            if req.level is not None and req.level < n_storeys:
                out[req.level].append(code)
            else:
                free.append(code)
    free = [free[i] for i in rng.permutation(len(free))]
    for i, code in enumerate(free):
        out[i % n_storeys].append(code)
    return out


def extent(leaf: dom.Node, axis) -> float:
    pts = [np.dot(geometry.coordinate(leaf, i), axis) for i in range(geometry.n_edges(leaf))]
    return max(pts) - min(pts)


def cut_core(leaf: dom.Node, root: dom.Node, rot: int, f: float) -> None:
    """Make ``leaf`` a strip ``f`` deep typed `E` and the rest `C`."""
    leaf.type = None
    leaf.division = [f, f]
    leaf.left, leaf.right = dom.Node(type="E"), dom.Node(type="C")
    leaf.rotation = rot
    dom.link(root)
    geometry.clear_cache()


def core_table(root: dom.Node, axes) -> dict:
    """Every strip a core could be, per built cell of the single (ground)
    storey ``root``: ``{cell id: (f, [(rotation, across, strip centroid)])}``.
    A core is a strip `operators._STAIR_STRIP_M` deep; it is ``across`` when
    it cuts the cell's long axis. Cutting one cell moves no other cell's walls,
    so strips in different cells combine freely."""
    out = {}
    for leaf in [lf for lf in root.leaves() if lf.type != "O"]:
        probe = copy.deepcopy(root)
        dom.link(probe)
        geometry.clear_cache()
        cell = probe.by_id(leaf.id)
        ax = max(axes, key=lambda a: extent(cell, a))
        long_ = extent(cell, ax)
        f = float(min(0.45, operators._STAIR_STRIP_M / long_))
        rows = []
        for rot in range(4):
            cut_core(cell, probe, rot, f)
            rows.append((rot, bool(extent(cell.left, ax) < 0.75 * long_),
                         np.array(geometry.centroid(cell.left))))
        out[leaf.id] = (f, rows)
    geometry.clear_cache()
    return out


def default_placement(root: dom.Node, n: int, table: dict) -> tuple:
    """The seeder's own choice, as ``((cell id, rotation), ...)``: for two
    cores the pair of built cells farthest apart, each strip at the end
    farthest from the other cell, which is what §39.143's half-diagonal
    separation asks; for one, the largest built cell."""
    built = [lf for lf in root.leaves() if lf.type != "O"]
    if n <= 0 or not built:
        return ()
    cen = {lf.id: np.array(geometry.centroid(lf)) for lf in built}
    if n == 1 or len(built) == 1:
        chosen = [max(built, key=geometry.area)]
    else:
        chosen = list(max(((a, b) for i, a in enumerate(built) for b in built[i + 1:]),
                          key=lambda ab: np.linalg.norm(cen[ab[0].id] - cen[ab[1].id])))
    out = []
    for leaf in chosen:
        others = [cen[o.id] for o in chosen if o is not leaf]
        _f, rows = table[leaf.id]
        rot = max(rows, key=lambda r: (r[1], min(np.linalg.norm(r[2] - o) for o in others)
                                       if others else 0.0))[0]
        out.append((leaf.id, rot))
    return tuple(out)


def apply_placement(root: dom.Node, placement: tuple, table: dict) -> list[dom.Node]:
    """Cut the cores of ``placement`` into the single storey ``root`` before
    the storeys are stacked, so each is one column at one path on every
    storey."""
    cores = []
    for cid, rot in placement:
        leaf = root.by_id(cid)
        cut_core(leaf, root, rot, table[cid][0])
        cores.append(leaf.left)
    return cores


def separation(root: dom.Node, centres) -> float:
    """The cores' closest pair over the built footprint's diagonal (the
    stair-separation rule asks >= 0.5); 1.0 for a single core."""
    if len(centres) < 2:
        return 1.0
    pts = [np.array(geometry.coordinate(lf, i)) for lf in root.leaves()
           if lf.type != "O" for i in range(geometry.n_edges(lf))]
    diag = max(np.linalg.norm(a - b) for i, a in enumerate(pts) for b in pts[i + 1:])
    d = min(np.linalg.norm(a - b) for i, a in enumerate(centres) for b in centres[i + 1:])
    return float(d / diag) if diag else 0.0


def core_placements(root: dom.Node, n: int, table: dict, k: int) -> list[tuple]:
    """Up to ``k`` placements: the default first, then the rest separated
    first and farthest apart first, every set of host cells once before any
    is used again with its other ends."""
    first = default_placement(root, n, table)
    if k <= 1 or not first:
        return [first]
    ends = {}
    for cid, (_f, rows) in table.items():
        use = [r for r in rows if r[1]] or rows
        seen, keep = set(), []
        for rot, _a, c in use:
            key = tuple(np.round(c, 2))
            if key not in seen:
                seen.add(key)
                keep.append((rot, c))
        ends[cid] = keep
    n = min(n, len(table))
    cands = []
    for cells in itertools.combinations(sorted(table), n):
        for pick in itertools.product(*(ends[c] for c in cells)):
            pl = tuple((c, rot) for c, (rot, _c) in zip(cells, pick))
            if pl == first:
                continue
            sep = separation(root, [c for _rot, c in pick])
            cands.append((sep >= 0.5, sep, pl))
    cands.sort(key=lambda r: (r[0], r[1]), reverse=True)
    out, used = [first], {frozenset(c for c, _r in first)}
    for _ok, _sep, pl in cands:
        cells = frozenset(c for c, _r in pl)
        if cells not in used and len(out) < k:
            used.add(cells)
            out.append(pl)
    for _ok, _sep, pl in cands:
        if pl not in out and len(out) < k:
            out.append(pl)
    return out


def ground(init, t, sizes) -> dom.Node:
    """Catalogue tree ``t`` drawn on the plot, one storey, no rooms yet."""
    root = copy.deepcopy(init)
    root.above = None
    dom.link(root)
    to_quad(t, sizes, root, root, frame_axes(init))
    dom.link(root)
    return root


# A room no strip can bridge: True makes it circulation, as the constructor's
# repair does; False blocks it and looks for a route around. Retyping cost 69
# missing rooms over 18 seeds and the median seed 4.7 decades of score (§39.147).
RETYPE_FALLBACK = False


def bridge_indoors(lvl: dom.Node, reqs, stairs_join: bool, max_bridges: int = 16,
                   stats: "Counter | None" = None, fit: "Fitness | None" = None) -> int:
    """Join a storey's circulation through the building, never through an
    outdoor cell, and return how many cells were made or cut circulation.

    `operators.repair_circulation_settled` with the courts disguised as rooms
    was the first try, and every bridge it laid on every storey of three
    plans ran through a court -- they cost what a room costs, and a court
    touches more cells -- so restoring the courts deleted the bridges and
    every storey stayed `not connected` (§39.147). Here the outdoor cells are
    simply not in the graph. Its cost model otherwise: circulation free, an
    untyped or generic cell 1, a programme room 5 (crossed last).

    A room on the bridge is not retyped -- that lost a room per bridge and
    made all 18 seeds of §39.147 score worse -- but CUT: a corridor strip
    (`bridge_strip`) off the side that joins the path, the room keeping the
    rest, §39.74's lesson that dividing a cell costs nothing where retyping
    it trades one fail for five. A bridge is laid whole or not at all: where
    a room on it takes no strip that joins anything, every cell of that
    bridge is put back, the room is left whole, and the next route goes
    around it (`RETYPE_FALLBACK`). ``stats`` counts strips cut, rooms
    retyped and rooms routed around.

    ``stairs_join`` (a storey above the ground, built after it): the scorer
    joins pieces that each hold a stair through the floor below
    (`graph.STAIRS_JOIN_STOREYS`), so those count as one piece here and only
    a piece without a stair is bridged. Ties go to tree path, not id(), so
    the same plan builds the same seed (§39.146)."""
    def cost(x: dom.Node) -> int:
        if dom.is_circulation(x):
            return 0
        if x.type and x.type in reqs:
            return 5
        return 1

    made = 0
    blocked: set = set()      # rooms no strip could bridge; still the same nodes
    for _ in range(max_bridges):
        geometry.clear_cache()
        G = geometry.leaf_graph(lvl, graph.DOOR_WIDTH)
        indoor = sorted((x for x in G if not dom.is_outside(x) and x not in blocked),
                        key=lambda x: x.id or "")
        H = nx.Graph()
        H.add_nodes_from(indoor)
        H.add_edges_from(sorted(((a, b) for a, b in G.subgraph(indoor).edges()),
                                key=lambda e: tuple(sorted((e[0].id or "", e[1].id or "")))),
                         )
        for a, b in H.edges():
            H[a][b]["w"] = (cost(a) + cost(b)) / 2.0
        comps = circ_pieces(H, stairs_join)
        if len(comps) <= 1:
            return made
        best = None
        for i, j in itertools.combinations(range(len(comps)), 2):
            T = H.copy()
            T.add_edges_from(("SRC", x, {"w": 0.0}) for x in comps[i])
            T.add_edges_from(("DST", x, {"w": 0.0}) for x in comps[j])
            try:
                _w, path = nx.single_source_dijkstra(T, "SRC", "DST", weight="w")
            except nx.NetworkXNoPath:
                continue
            middle = [x for x in path[1:-1] if not dom.is_circulation(x)]
            w = sum(cost(x) for x in middle)
            if middle and (best is None or w < best[0]):
                best = (w, middle)
        if best is None:
            return made
        rooms = [x for x in best[1] if cost(x) == 5]
        # all or nothing: a bridge that stops part way leaves dead-end
        # corridors, buried and joining nothing (§39.147)
        undo = [(x, x.type) for x in best[1] if x not in rooms]
        for x, _t in undo:
            x.type = "C"
        dom.link(lvl)
        cut, failed = [], None
        for k, x in enumerate(rooms):
            code = x.type
            if bridge_strip(lvl, x, stairs_join, assume=rooms[k + 1:], fit=fit):
                cut.append((x, code))
            elif RETYPE_FALLBACK:
                x.type = "C"
                if stats is not None:
                    stats["retyped"] += 1
            else:
                failed = x
                break
            dom.link(lvl)
        if failed is not None:
            for x, code in cut:
                x.type, x.division, x.left, x.right = code, None, None, None
            for x, t in undo:
                x.type = t
            dom.link(lvl)
            blocked.add(failed)
            if stats is not None:
                stats["left"] += 1
            continue
        made += len(undo) + len(rooms)
        if stats is not None:
            stats["strip"] += len(cut)
    return made


def circ_pieces(H: nx.Graph, stairs_join: bool) -> list[list[dom.Node]]:
    """The circulation pieces of indoor graph ``H``, stair-holding pieces as
    one when ``stairs_join``, in tree-path order."""
    circ = [x for x in H if dom.is_circulation(x)]
    comps = [sorted(c, key=lambda x: x.id or "")
             for c in nx.connected_components(H.subgraph(circ))]
    if stairs_join:
        up = [c for c in comps if any(x.type == dom.GENERIC_STAIR for x in c)]
        if len(up) > 1:
            comps = [c for c in comps if c not in up] + [sum(up, [])]
    return sorted(comps, key=lambda c: min(x.id or "" for x in c))


def n_pieces(lvl: dom.Node, stairs_join: bool) -> int:
    geometry.clear_cache()
    G = geometry.leaf_graph(lvl, graph.DOOR_WIDTH)
    return len(circ_pieces(G.subgraph([x for x in G if not dom.is_outside(x)]), stairs_join))


def bridge_strip(lvl: dom.Node, room: dom.Node, stairs_join: bool,
                 depth_m: float = 1.6, assume=(), fit: "Fitness | None" = None) -> bool:
    """Cut a corridor ``depth_m`` deep (`width_circulation`'s 1.6 m) off
    ``room``, whichever of its eight placements -- four rotations, strip on
    either side -- leaves the storey in fewest circulation pieces, then the
    building's score under ``fit`` -- a corridor cut through the middle of a
    building is buried, and this brief asks circulation for daylight too:
    chosen on the room's area alone, the strips added 60 corridor
    crinkliness fails over 18 seeds, and on the room's own daylight 67
    (§39.147) -- then the most room. Without ``fit``, the room's daylight
    (`area_outside` over area). Keeps it and returns True only if it joined
    something.
    ``assume``: rooms further along the same bridge, counted as circulation
    while this one is judged, since a strip can only join what they will."""
    kept = [(x, x.type) for x in assume]
    for x, _t in kept:
        x.type = "C"
    before = n_pieces(lvl, stairs_join)
    code = room.type
    building = lvl
    while building.below is not None:
        building = building.below
    best = None
    for rot in range(4):
        for side in (0, 1):
            room.type = None
            room.rotation = rot
            room.left, room.right = dom.Node(type="C"), dom.Node(type="C")
            room.division = [0.5, 0.5]
            dom.link(lvl)
            geometry.clear_cache()
            whole = geometry.area(room)
            # the strip's depth is measured across the cut, on the left part
            span = max(1e-6, extent(room, _cut_normal(room)))
            f = float(min(0.45, depth_m / span))  # numpy floats do not dump to YAML
            f = f if side == 0 else 1 - f
            room.division = [f, f]
            strip, rest = (room.left, room.right) if side == 0 else (room.right, room.left)
            strip.type, rest.type = "C", code
            dom.link(lvl)
            got = n_pieces(lvl, stairs_join)
            if fit is not None:
                judge = -fit.score_with_fails(copy.deepcopy(building))[0]
                geometry.clear_cache()
            else:
                judge = -(Fitness.area_outside(None, rest, geometry.leaf_graph(
                    lvl, graph.DOOR_WIDTH), {}) / max(geometry.area(rest), 1e-9))
            cand = (got, judge, -geometry.area(rest) / whole, rot, side)
            if best is None or cand < best[0]:
                best = (cand, rot, side, f)
    (got, *_), rot, side, f = best
    for x, t in kept:
        x.type = t
    if got >= before:
        room.type, room.division, room.left, room.right = code, None, None, None
        dom.link(lvl)
        geometry.clear_cache()
        return False
    room.type = None
    room.rotation, room.division = rot, [f, f]
    room.left, room.right = (dom.Node(type="C"), dom.Node(type=code)) if side == 0 \
        else (dom.Node(type=code), dom.Node(type="C"))
    dom.link(lvl)
    geometry.clear_cache()
    return True


def _cut_normal(node: dom.Node):
    """Unit vector across ``node``'s cut, from its left part's centroid to
    its right's."""
    a = np.array(geometry.centroid(node.left))
    b = np.array(geometry.centroid(node.right))
    v = b - a
    return v / (np.linalg.norm(v) or 1.0)


def build_seed(init, t, sizes, reqs, n_storeys, rng, kw, n_cores: int = 0,
               placement: "tuple | None" = None, stats: "Counter | None" = None,
               fit: "Fitness | None" = None) -> dom.Node:
    """``placement`` names the cores (`core_placements`); by default the
    seeder's own choice. ``stats`` counts how `bridge_indoors` crossed rooms;
    ``fit`` lets it choose each corridor cut on the building's score."""
    root = ground(init, t, sizes)
    if n_storeys > 1 and (n_cores > 0 or placement):
        table = core_table(root, frame_axes(init))
        if placement is None:
            placement = default_placement(root, n_cores, table)
        apply_placement(root, placement, table)
    while len(dom.levels(root)) < n_storeys:
        top = dom.levels(root)[-1]
        dup = genome._copy_storey(top)
        dup.height = top.height
        top.above = dup
    dom.link(root)
    terraces = []
    for li, (lvl, rooms) in enumerate(zip(dom.levels(root), buckets(reqs, n_storeys, rng))):
        wings = [lf for lf in lvl.leaves() if lf.type not in ("O", "E")]
        stairs = [lf for lf in lvl.leaves() if lf.type == "E"]
        n_circ = max(1, -(-len(rooms) // kw["circ_divisor"]))
        # +1: the assignment always places one O in scope, on the most
        # landlocked cell. On the ground it goes back to C (the footprint
        # keeps its own courts); upstairs it stays, a terrace over the
        # building below -- every level needs outdoor space of its own
        # (`force_roof_garden`), and a court below is a hole up here.
        scope = grow(lvl, wings, len(rooms) + n_circ + 1, rng)
        operators._assign_adjacency_aware(
            lvl, rooms, reqs, rng, fixed_circ=stairs or None,
            interior_outside=True, n_outside=1, scope=set(scope))
        for lf in scope:
            if lf.type == "O":
                if li == 0:
                    lf.type = "C"
                else:
                    terraces.append(lf)
        dom.link(root)
        for w in wings:
            if w.divided:
                operators._size_divisions_from_targets(w, reqs)
        dom.link(root)
        # the dominating set is grown on the pre-sizing geometry, and on a
        # footprint split by courts it falls into one piece per wing: every
        # storey of the first build was `not connected` (§39.145, §39.147)
        bridge_indoors(lvl, reqs, stairs_join=li > 0, stats=stats, fit=fit)
        dom.link(root)
    # a terrace with a room built over it is `covered outside above ground`
    geometry.clear_cache()
    for lf in terraces:
        if lf.type == "O" and dom.is_covered(lf):
            lf.type = "C"
    return operators._finalise(root)


def needed_cover(reqs, conf, plot_m2: float, circ_share: float) -> dict:
    prog = operators._programme_codes(reqs)
    area = sum(r.size * r.count for r in prog.values() if r.size) * (1 + circ_share)
    lo = int(conf.get("storey_minimum") or 1)
    hi = int(conf.get("storey_limit") or lo)
    return {n: area / n / plot_m2 for n in range(lo, hi + 1)}


def parse_tree(s: str):
    """The inverse of `wings_catalogue.text`: "H(B V(B O))" -> a tree."""
    pos = 0

    def node():
        nonlocal pos
        c = s[pos]
        pos += 1
        if c in "BO":
            return c
        assert s[pos] == "("
        pos += 1
        kids = []
        while s[pos] != ")":
            if s[pos] == " ":
                pos += 1
                continue
            kids.append(node())
        pos += 1
        return (c, tuple(kids))
    return node()


def plans_catalogue(max_leaves: int) -> list:
    """The catalogue plus the BLOCK, "B": the whole plot built, no court. The
    catalogue starts at two leaves with a court in each, so without it a small
    plot lit all round reads as unlightable at a cover programme-house's
    designs reach (86-96% at two storeys, no crinkliness fail)."""
    return ["B"] + wc.catalogue(max_leaves)


def capacities(cat, gs, plot, args) -> dict:
    """Each oriented tree's CAPACITY on this plot -- the most cover it reaches
    all lit -- keyed by its text, as (cover, sizes, tree), None where no size
    of it is all lit. `sizes` is keyed by id() of that tree's nodes, so the
    tree is kept with it."""
    caps = {}
    for t in cat:
        for g in gs:
            tt = wc.transform(t, *g)
            r = wc.optimise(tt, plot, args.b_min, args.o_min,
                            wc.stable_rng(wc.text(tt), args.programme, "cap"),
                            starts=args.starts)
            caps[wc.text(tt)] = (r[1], r[3], tt) if r and r[2] == 0 else None
    return caps


def passing(cat, gs, plot, args, n: int, cover: float, caps=None):
    """The filter at one storey count: {outline: (leaves, text, cover, tree,
    sizes)}, one tree per outline, and the set of base trees that pass. With
    ``caps`` an oriented tree is tried only if its capacity on this plot comes
    within ``tol`` of the cover. That would be lossless if the capacity were
    exact; it is a hill-climb, and under-finds (DESIGN.md §39.148)."""
    seen, passed, tried = {}, set(), 0
    for t in cat:
        for g in gs:
            tt = wc.transform(t, *g)
            txt = wc.text(tt)
            if caps is not None and (caps[txt] is None or caps[txt][0] < cover - args.tol):
                continue
            tried += 1
            r = wc.optimise(tt, plot, args.b_min, args.o_min,
                            wc.stable_rng(txt, args.programme, n),
                            starts=args.starts, coverage=cover)
            if not r or r[2] > 0 or abs(r[1] - cover) > args.tol:
                continue
            passed.add(wc.text(t))
            outline = "\n".join(wc.ascii_plan(tt, r[3], plot, 16))
            seen.setdefault(outline, (wc.n_leaves(tt), txt, r[1], tt, r[3]))
    return seen, passed, tried


def filter_report(args, plot, covers) -> int:
    """`--filter-only`: each tree's capacity on this plot, and per storey count
    the outlines the filter passes (pruned only with ``--prune``).
    ``--check-prune`` runs each storey count both ways and reports what the
    prune loses."""
    import time
    cat = plans_catalogue(args.leaves)
    gs = wc.orientations(plot)
    print(f"  {len(cat)} trees x {len(gs)} orientation(s)", flush=True)
    t0 = time.process_time()
    caps = capacities(cat, gs, plot, args)
    t_cap = time.process_time() - t0
    best = {}
    for t in cat:
        for g in gs:
            c = caps[wc.text(wc.transform(t, *g))]
            if c and (wc.text(t) not in best or c[0] > best[wc.text(t)][0]):
                best[wc.text(t)] = (c[0], c[2], c[1])
    print(f"  capacity pass: {len(best)} of {len(cat)} trees can be built all lit, best "
          f"{max((v[0] for v in best.values()), default=0):.0%}, {t_cap:.0f} s CPU", flush=True)
    print(f"  the block (all built, cover 100%) is "
          f"{'all lit' if caps['B'] else 'NOT all lit'}", flush=True)
    for cap, tt, sizes in sorted(best.values(), key=lambda v: (-v[0], wc.n_leaves(v[1])))[:3]:
        print(f"    capacity {cap:.0%}: {wc.text(tt)}")
        for line in wc.ascii_plan(tt, sizes, plot, 16):
            print("        " + line)
    for n, cover in covers.items():
        if cover > 0.98:
            print(f"\n  {n} storeys, cover {cover:.0%}: not drawn", flush=True)
            continue
        t0 = time.process_time()
        seen, passed, tried = passing(cat, gs, plot, args, n, cover,
                                      caps if (args.prune or args.check_prune) else None)
        dt = time.process_time() - t0
        print(f"\n  {n} storeys, cover {cover:.0%}: {len(passed)} trees, {len(seen)} outlines "
              f"pass ({tried} of {len(cat) * len(gs)} oriented trees tried, {dt:.0f} s CPU)",
              flush=True)
        for outline, (nl, txt, frac, _tt, _s) in sorted(seen.items(), key=lambda kv: kv[1][:3])[:3]:
            print(f"    {nl} leaves, {txt}, cover {frac:.0%}")
            for line in outline.split("\n"):
                print("        " + line)
        if args.check_prune:
            t0 = time.process_time()
            full, fpassed, ftried = passing(cat, gs, plot, args, n, cover)
            dt = time.process_time() - t0
            lost = [v[1] for k, v in full.items() if k not in seen]
            print(f"    unpruned: {len(fpassed)} trees, {len(full)} outlines ({ftried} tried, "
                  f"{dt:.0f} s CPU); outlines the prune loses: {len(lost)} {lost[:5]}; "
                  f"same plans: {[v[1] for v in full.values()] == [v[1] for v in seen.values()]}",
                  flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default="harbor-house")
    ap.add_argument("--leaves", type=int, default=6)
    ap.add_argument("--storeys", type=int, nargs="*", default=None,
                    help="storey counts to seed (default: all the brief allows)")
    ap.add_argument("--circ-share", type=float, default=0.25,
                    help="circulation added to the room area when asking the cover")
    ap.add_argument("--tol", type=float, default=0.05,
                    help="how far from the needed cover a plan may land")
    ap.add_argument("--b-min", type=float, default=1.0)
    ap.add_argument("--o-min", type=float, default=0.77)
    ap.add_argument("--max-seeds", type=int, default=40,
                    help="filtered plans built and tuned, fewest leaves first")
    ap.add_argument("--budget", type=int, default=200)
    ap.add_argument("--starts", type=int, default=4,
                    help="hill-climb starts per tree and orientation")
    ap.add_argument("--write", type=int, default=0, help="save the best N seeds")
    ap.add_argument("--cores", type=int, default=None,
                    help="stair cores to cut (default: the brief's staircase_min; 0: none)")
    ap.add_argument("--core-variants", type=int, default=1,
                    help="build each plan with up to this many stair-core placements "
                         "(which built cells, which end of each); the first is the "
                         "default, the rest separated first. The search cannot move a "
                         "shaft far (homemaker-py-2g7.13.1.6), so let the halving choose")
    ap.add_argument("--prefix", default="wings", help="written seeds are <prefix>-<rank>.dom")
    ap.add_argument("--out-dir", default=None,
                    help="where --write saves (default: the programme's directory)")
    ap.add_argument("--only", nargs="+", default=None, metavar="N:TREE",
                    help="build just these plans, as printed (e.g. '3:H(B V(B O))'), "
                         "skipping the enumeration; sizing and building are "
                         "deterministic, so this reproduces a ranked run's seeds")
    ap.add_argument("--filter-only", action="store_true",
                    help="report what the filter passes at each storey count, with "
                         "each tree's capacity on this plot, and build nothing")
    ap.add_argument("--check-prune", action="store_true",
                    help="with --filter-only: run the filter with and without the "
                         "capacity prune and report any outline the prune loses")
    ap.add_argument("--prune", action="store_true",
                    help="try an oriented tree at a storey count only if its capacity on "
                         "this plot comes within --tol of the cover. NOT lossless: the "
                         "capacity hill-climb under-finds, and on health-centre the prune "
                         "lost 45 of 199 and 218 of 1172 outlines (DESIGN.md §39.148)")
    args = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        print("set HOMEMAKER_ORTHOGONAL_DIVISION=1", file=sys.stderr)
        return 2

    prog = REPO / "examples" / args.programme
    conf, cost = load_config(prog)
    fit = Fitness(conf, cost)
    reqs = programme.load_programme_dir(str(prog))
    init = dom.load(str(prog / "init.dom"))
    plot, (w, d, h) = plot_of(init)
    covers = needed_cover(reqs, conf, w * d, args.circ_share)
    if args.storeys:
        covers = {n: covers.get(n, list(covers.values())[0] * min(covers) / n)
                  for n in args.storeys}
    kw = constructor_kwargs()
    n_cores = (args.cores if args.cores is not None
               else int(conf.get("staircase_min") or 1))
    print(f"{args.programme}: plot {w:.1f} x {d:.1f} m, storey {h:g} m -> "
          f"{plot.label}; cover needed " +
          ", ".join(f"{n} storeys {c:.0%}" for n, c in covers.items()), flush=True)

    if args.filter_only:
        return filter_report(args, plot, covers)

    plans = []
    if args.only:
        for spec in args.only:
            n_s, txt = spec.split(":", 1)
            n, tt = int(n_s), parse_tree(txt)
            assert wc.text(tt) == txt, (txt, wc.text(tt))
            r = wc.optimise(tt, plot, args.b_min, args.o_min,
                            wc.stable_rng(txt, args.programme, n),
                            starts=args.starts, coverage=covers[n])
            plans.append((n, wc.n_leaves(tt), txt, tt, r[3], r[1],
                          "\n".join(wc.ascii_plan(tt, r[3], plot, 16))))
    cat = [] if args.only else plans_catalogue(args.leaves)
    gs = wc.orientations(plot)
    caps = capacities(cat, gs, plot, args) if (args.prune and not args.only) else None
    for n, cover in ({} if args.only else covers).items():
        if cover > 0.98:
            continue
        seen, _passed, _tried = passing(cat, gs, plot, args, n, cover, caps)
        for outline, (nl, txt, frac, tt, sizes) in seen.items():
            plans.append((n, nl, txt, tt, sizes, frac, outline))
        print(f"  {n} storeys: {len(seen)} outlines pass the filter", flush=True)
    if not args.only:
        plans.sort(key=lambda p: (p[1], p[0], p[2]))
        plans = plans[:args.max_seeds]

    rows = []
    for i, (n, nl, txt, tt, sizes, frac, outline) in enumerate(plans):
        placements = [None]
        if n > 1 and n_cores > 0 and args.core_variants > 1:
            g = ground(init, tt, sizes)
            placements = core_placements(g, n_cores, core_table(g, frame_axes(init)),
                                         args.core_variants)
        for v, pl in enumerate(placements):
            # one room-assignment stream per plan, so variants differ only in the cores
            rng = rng_for(args.programme, txt, n)
            crossed = Counter()
            root = build_seed(init, tt, sizes, reqs, n, rng, kw, n_cores, pl, crossed, fit)
            geometry.clear_cache()
            ground_lvl = dom.levels(root)[0]
            stairs = [lf for lf in ground_lvl.leaves() if lf.type == "E"]
            cores = " ".join(lf.id or "root" for lf in stairs) or "none"
            raw = len(fit.score_with_fails(root)[1])
            res = innerloop.optimise(root, str(prog), budget=args.budget, method="nm")
            geometry.clear_cache()
            _s, fails = fit.score_with_fails(root)
            ground_lvl = dom.levels(root)[0]
            sep = separation(ground_lvl, [np.array(geometry.centroid(lf))
                                          for lf in ground_lvl.leaves() if lf.type == "E"])
            label = (f"cores {cores} (v{v}, sep {sep:.2f}), bridged rooms "
                     f"{crossed['strip']} cut / {crossed['retyped']} retyped / "
                     f"{crossed['left']} routed around")
            rows.append((len(fails), res.fitness, n, txt, outline, root, list(fails), raw,
                         frac, label))
            print(f"  [{i + 1}/{len(plans)}] {n} storeys, {txt}, {label}: cover {frac:.0%}, "
                  f"{raw} fails raw -> {len(fails)} tuned", flush=True)

    rows.sort(key=lambda r: (r[0], -r[1]))
    print(f"\n{len(rows)} seeds, {args.budget} inner-loop evaluations each; "
          f"tuned fails median {statistics.median(r[0] for r in rows) if rows else 0}")
    for k, (nf, sc, n, txt, outline, root, fails, raw, frac, label) in enumerate(rows[:8]):
        fam = Counter(family(f) for f in fails)
        print(f"  #{k + 1}: {nf} fails, score {sc:.3g}, {n} storeys, {txt}, cover {frac:.0%}, "
              f"{label}")
        print("      " + ", ".join(f"{a} {b}" for a, b in fam.most_common(6)))
        for line in outline.split("\n"):
            print("        " + line)
    out_dir = Path(args.out_dir) if args.out_dir else prog
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, r in enumerate(rows[:args.write]):
        out = out_dir / f"{args.prefix}-{k + 1}.dom"
        dom.dump(r[5], str(out))
        print(f"wrote {out}  ({r[3]}, {r[9]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
