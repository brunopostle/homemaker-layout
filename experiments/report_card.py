"""A design's report card: plain facts about a plan, read off the geometry and
the brief, none of them a score (`homemaker-py-5fje.1`, DESIGN.md §39.201).

The aggregation review cannot judge a candidate score by its own number or by
today's (§39.200: the fail count is part of A0's aggregation). This is the
yardstick that belongs to no arm. It reads no factor, no fail line, no value
rate. The scorer is run only so that the building is the one it scores: the
same preprocessing and merge, the same adjacency graphs, captured as each
storey goes past.

Per room cell (``--rooms``): built area and target, the usable rectangle's
short side, and its long/short ratio against the brief's proportion,
exposed wall length and the floor depth behind each metre of it, the
adjacencies the brief asks and which are met, and whether a door reaches it.

Per design, one row, a VECTOR, never summed (a sum would be a fifth
aggregation):

  rooms_asked   rooms the brief asks for (sum of counts)
  missing       asked and not built; extra: built beyond the count
  token / over  rooms under 25% / over 150% of their target area
  shortfall_m2  area the built rooms fall short of their targets, plus the
                whole target of every missing room: what the brief asked for
                and did not get
  surplus_m2    area built rooms exceed their targets by. With circ_m2 below,
                the two kinds of area the owner calls waste (§39.204)
  ratio_med, ratio_min, ratio_big5
                median and least built/target; the median over the five
                largest-target rooms (§39.201 Phase 3 names it)
  narrowest     the short side of the narrowest room's usable rectangle, m.
                A fact, not a count against the brief: no programme asks a
                room width (`width_inside` is null, §39.37), and the owner's
                test is usability (a wc stall wants 0.8 m clear, §39.204)
  sliver        rooms whose usable rectangle is under 0.8 m wide, the owner's
                "no use for anything" (§39.204); "sliver rooms" is the
                commonest note on round 0 of judging (§39.207)
  long          rooms whose usable rectangle is longer than the brief's
                proportion (the per-space value, else `proportion_inside`)
  unlit         rooms that need light (any but `crinkliness: none`) with no
                exposed wall at all
  deep          such rooms more than 2.5 m deep per metre of exposed wall: the
                depth Alexander 159 allows a room per window wall (§39.14-§39.16)
  depth_med     median floor depth per metre of exposed wall over lit rooms
  adj_asked / adj_met
                adjacencies the brief asks of built rooms, and how many are met
  adj_share     adj_met / adj_asked. The count alone falls when a room is
                missing, since a missing room asks nothing (§39.207)
  no_door       rooms with no access (no circulation, or what serves their usage)
  storeys / connected
                storeys, and storeys whose circulation is one piece, stairs counted
  stair_storeys storeys a stair rising from the ground floor reaches (0 if none)
  room_m2, circ_m2, circ_share
                programme-room area, indoor circulation (C and E) area, the ratio
  inside_m2     all non-outside area
  wall_per_m2   external wall (m2, inside to outside or to the plot edge) per
                m2 of room
  roof_per_m2   roof (inside area not under inside area on the storey above)
                per m2 of room
  cost          the scorer's construction cost, in its units

Circulation as a network (`homemaker-py-5fje.7`, §39.214), read off the
scorer's access graph (``graph_circ``: each room keeps the door it is served
by), per storey, before a stair joins storeys:

  circ_pieces   pieces of indoor circulation (C and E cells) beyond one per
                storey that has any
  circ_orphan_m2
                area of the pieces that reach no stair and, on the ground
                storey, no outside: scraps that join nothing

A third measure was tried and dropped: circulation on no route joining the
stairs, the way out and every room's door (an approximate Steiner tree, a
cell counting whole). It was zero on 90 of the 98 designs, because nearly
every scrap of corridor is some room's door (§39.214).

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/report_card.py \\
        [--rooms rooms.tsv] [--tsv out.tsv] DESIGN.dom ...
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/report_card.py --self-test

The programme is read from the path, as in diag_aggregation.py.

``--self-test`` is the negative control: the questionnaire's committed edits of
real designs (a room shrunk, a room left out, a storey cut off from the stair)
must each move the column it is about, and the columns it is not about are
listed, so a column that never moves -- or always does -- shows.
"""
import argparse
import statistics
import sys
from collections import Counter
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diag_shrunk_rooms import KEYS  # noqa: E402
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, geometry, programme  # noqa: E402
from homemaker_layout import graph as graph_mod  # noqa: E402
from homemaker_layout import programme as _pr  # noqa: E402
from homemaker_layout.fitness import Fitness, _height  # noqa: E402

DEPTH_PER_WINDOW = 2.5   # m of floor per window wall, Alexander 159 (§39.16)
SLIVER = 0.8             # m: below this a room holds nothing, not even a wc stall (§39.204)
TOKEN, OVER = 0.25, 1.5

DESIGN_COLS = ["rooms_asked", "missing", "extra", "token", "over",
               "shortfall_m2", "surplus_m2",
               "ratio_med", "ratio_min", "ratio_big5", "narrowest", "sliver", "long",
               "unlit", "deep", "depth_med", "adj_asked", "adj_met", "adj_share", "no_door",
               "storeys", "connected", "stair_storeys",
               "room_m2", "circ_m2", "circ_share", "inside_m2",
               "wall_per_m2", "roof_per_m2", "cost",
               "circ_pieces", "circ_orphan_m2"]
ROOM_COLS = ["level", "id", "code", "usage", "area", "target", "ratio",
             "width", "aspect", "aspect_max",
             "exposed_m", "depth", "needs_light",
             "adj_asked", "adj_missed", "door"]


def capture(fit, root):
    """Score ``root`` (mutating it as the scorer does: preprocess, merge) and
    return the merged storeys as [(level_root, G, graph_circ)] and the cost."""
    storeys, cost = [], [0.0]
    ps, pc = fit.process_storey, fit.plot_cost

    def process_storey(level_root, G, level_id, fail, graph_circ=None, **k):
        se = ps(level_root, G, level_id, fail, graph_circ=graph_circ, **k)
        storeys.append((level_root, G, graph_circ))
        cost[0] += se.cost
        return se

    def plot_cost(*a, **k):
        c = pc(*a, **k)
        cost[0] += c
        return c

    fit.process_storey, fit.plot_cost = process_storey, plot_cost
    try:
        fit.score_with_fails(root)
    finally:
        del fit.process_storey, fit.plot_cost
    return storeys, cost[0]


def outline(leaf):
    return Polygon([geometry.coordinate(leaf, i) for i in range(geometry.n_edges(leaf))])


def exposed_length(leaf, G):
    """Wall open to the sky: shared with an uncovered outside cell, or on the
    plot edge where the perimeter is not private. What `Fitness.area_outside`
    measures, as a length rather than an area."""
    from homemaker_layout.fitness import _perimeter
    length = sum(G[leaf][nb]["width"] for nb in G.neighbors(leaf)
                 if dom.is_outside(nb) and not dom.is_covered(nb))
    perimeter = _perimeter(leaf)
    for e in range(geometry.n_edges(leaf)):
        bid = geometry.boundary_id(leaf, e)
        if geometry.is_external(bid) and \
                (perimeter.get(bid) or "").lower() not in ("private", "fortified"):
            length += geometry.edge_length(leaf, e)
    return length


def card(fit, reqs, root):
    """(design row dict, [room row dicts]) for one linked ``root``."""
    storeys, cost = capture(fit, root)
    rooms = {c: r for c, r in reqs.items() if not dom.is_generic(c)}
    usages = {c: r.usage for c, r in reqs.items()}
    room_rows = []
    room_m2 = circ_m2 = inside_m2 = wall_m2 = 0.0
    inside_by_level = []
    for li, (lvl, G, _) in enumerate(storeys):
        h = _height(lvl)
        polys = []
        for leaf in lvl.leaves():
            if dom.is_outside(leaf):
                continue
            a = geometry.area(leaf)
            inside_m2 += a
            polys.append(outline(leaf))
            if dom.is_circulation(leaf):
                circ_m2 += a
            # external wall: to an outside cell, or on the plot edge
            wall = sum(G[leaf][nb]["width"] for nb in G.neighbors(leaf) if dom.is_outside(nb))
            wall += sum(geometry.edge_length(leaf, e) for e in range(geometry.n_edges(leaf))
                        if geometry.is_external(geometry.boundary_id(leaf, e)))
            wall_m2 += wall * h
            r = rooms.get(leaf.type)
            if r is None:
                continue
            room_m2 += a
            exposed = exposed_length(leaf, G)
            req_light = fit.crinkliness_params(leaf) is not None
            missed = []
            for adj in r.adjacency:
                serves = None
                if r.usage in _pr.SERVICE_USAGES and adj.lower() == "c":
                    serves = lambda nb: graph_mod.serves_utility(nb, usages)  # noqa: E731
                if not graph_mod.has_adjacency(leaf, adj, G, serves=serves):
                    missed.append(adj)
            room_rows.append(dict(
                level=li, id=leaf.id, code=leaf.type, usage=r.usage,
                area=a, target=r.size, ratio=a / r.size if r.size else float("nan"),
                width=geometry.usable_width(leaf),
                aspect=geometry.usable_aspect(leaf),
                aspect_max=fit.get_space_params(leaf.type, "proportion")[0],
                exposed_m=exposed, depth=a / exposed if exposed else float("inf"),
                needs_light=int(req_light), adj_asked=len(r.adjacency),
                adj_missed=",".join(missed),
                door=int(bool(fit.access(leaf, G)))))
        inside_by_level.append(unary_union(polys) if polys else Polygon())

    roof = 0.0
    for i, here in enumerate(inside_by_level):
        above = inside_by_level[i + 1] if i + 1 < len(inside_by_level) else Polygon()
        roof += here.difference(above).area

    built = Counter(r["code"] for r in room_rows)
    missing = sum(max(0, r.count - built[c]) for c, r in rooms.items())
    extra = sum(max(0, n - rooms[c].count) for c, n in built.items())
    ratios = [r["ratio"] for r in room_rows if r["target"]]
    # the shortfall of a code counts its best `count` cells: an extra cell
    # is not short of anything
    kept = []
    for c, r in rooms.items():
        cells = sorted((x for x in room_rows if x["code"] == c), key=lambda x: -x["area"])
        kept += [x for x in cells[: r.count] if x["target"]]
    big = sorted((r for r in room_rows if r["target"]), key=lambda r: -r["target"])[:5]
    lit = [r for r in room_rows if r["needs_light"]]

    graph_circ = storeys[0][2] if storeys else []
    n = len(storeys)
    served = set()
    for leaf in (storeys[0][0].leaves() if storeys else []):
        shaft = graph_mod.stair_shaft(leaf)
        if len(shaft) > 1:
            served.update(range(len(shaft)))

    row = dict(
        rooms_asked=sum(r.count for r in rooms.values()),
        missing=missing, extra=extra,
        token=sum(x < TOKEN for x in ratios), over=sum(x > OVER for x in ratios),
        shortfall_m2=sum(max(0.0, r["target"] - r["area"]) for r in kept)
        + sum(max(0, rooms[c].count - built[c]) * rooms[c].size for c in rooms),
        surplus_m2=sum(max(0.0, r["area"] - r["target"]) for r in room_rows if r["target"]),
        ratio_med=statistics.median(ratios) if ratios else float("nan"),
        ratio_min=min(ratios, default=float("nan")),
        ratio_big5=statistics.median(r["ratio"] for r in big) if big else float("nan"),
        narrowest=min((r["width"] for r in room_rows), default=float("nan")),
        sliver=sum(r["width"] < SLIVER for r in room_rows),
        long=sum(r["aspect"] > r["aspect_max"] for r in room_rows),
        unlit=sum(r["exposed_m"] == 0 for r in lit),
        deep=sum(r["depth"] > DEPTH_PER_WINDOW for r in lit),
        depth_med=statistics.median(r["depth"] for r in lit if r["exposed_m"])
        if any(r["exposed_m"] for r in lit) else float("nan"),
        adj_asked=sum(r["adj_asked"] for r in room_rows),
        adj_met=sum(r["adj_asked"] - len([x for x in r["adj_missed"].split(",") if x])
                    for r in room_rows),
        no_door=sum(not r["door"] for r in room_rows),
        storeys=n,
        connected=sum(graph_mod.circulation_joined(graph_circ, i) for i in range(n)),
        stair_storeys=len(served),
        room_m2=room_m2, circ_m2=circ_m2,
        circ_share=circ_m2 / room_m2 if room_m2 else float("nan"),
        inside_m2=inside_m2,
        wall_per_m2=wall_m2 / room_m2 if room_m2 else float("nan"),
        roof_per_m2=roof / room_m2 if room_m2 else float("nan"),
        cost=cost)
    row["adj_share"] = row["adj_met"] / row["adj_asked"] if row["adj_asked"] else float("nan")
    row["circ_pieces"], row["circ_orphan_m2"] = circulation_network(storeys, rooms)
    return row, room_rows


CIRC = set(dom.GENERIC_INDOOR_CIRCULATION)


def circulation_network(storeys, rooms):
    """``(pieces, orphan_m2)`` over the storeys, from each storey's trimmed
    access graph. See the module docstring."""
    import networkx as nx
    pieces = 0
    orphan = 0.0
    graph_circ = storeys[0][2] if storeys else []
    for i, Gc in enumerate(graph_circ):
        circ = [n for n in Gc.nodes() if n.type in CIRC and dom.is_usable(n)]
        if not circ:
            continue
        comps = list(nx.connected_components(Gc.subgraph(circ)))
        pieces += len(comps) - 1
        for comp in comps:
            stair = any(n.type == dom.GENERIC_STAIR for n in comp)
            out = i == 0 and any(nb.type in dom.GENERIC_OUTSIDE
                                 for n in comp for nb in Gc.neighbors(n))
            if not stair and not out:
                orphan += sum(geometry.area(n) for n in comp)
    return pieces, orphan


def fmt(v):
    return f"{v:.4g}" if isinstance(v, float) else str(v)


class Programmes:
    def __init__(self):
        self.cache = {}

    def __call__(self, path, prog=None):
        prog = prog or next((v for k, v in KEYS.items() if k in str(path)), None)
        if prog is None:
            return None
        if prog not in self.cache:
            d = REPO / "examples" / prog
            self.cache[prog] = (prog, Fitness(*load_config(d)),
                                programme.load_programme_dir(str(d)))
        return self.cache[prog]


def card_of(progs, path, prog=None, edit=None):
    """The card of the design at ``path``, after ``edit(root)`` if given."""
    p = progs(path, prog)
    if p is None:
        raise SystemExit(f"no programme in path: {path}")
    prog, fit, reqs = p
    root = dom.load(str(path))
    dom.link(root)
    if edit is not None:
        edit(root)
        dom.link(root)
    geometry.clear_cache()
    return card(fit, reqs, root)


# --------------------------------------------------------------------------- #
# negative control
# --------------------------------------------------------------------------- #

Q = REPO / "experiments" / "results" / "questionnaire"
CLEAN9 = REPO / "experiments/results/halving-maple-clean/final-clean-9.dom"
BEST1 = REPO / "experiments/results/split-stair-race/final-best-1.dom"

# (what the edit is, base, edited, {column: required change}); a number is
# the exact change, "+"/"-" only its sign
CONTROLS = [
    ("lounge shrunk to 2% (O1 a)", CLEAN9, Q / "O1-0-a.dom",
     {"token": 1, "missing": 0, "shortfall_m2": "+", "connected": 0}),
    ("lounge left out (O1 b)", CLEAN9, Q / "O1-0-b.dom",
     {"missing": 1, "token": 0, "shortfall_m2": "+", "connected": 0}),
    ("bathroom shrunk to 38% (O2 a)", CLEAN9, Q / "O2-0-a.dom",
     {"shortfall_m2": "+", "missing": 0, "token": 0, "connected": 0}),
    ("storey 1 cut off (O8 a)", BEST1, Q / "O8-0-a.dom",
     {"connected": -1, "missing": 0, "token": 0, "stair_storeys": 0}),
    ("three bedrooms at 40% (O8 b)", BEST1, Q / "O8-0-b.dom",
     {"shortfall_m2": "+", "missing": 0, "token": 0, "connected": 0}),
    ("stair stopped below the top storey", BEST1, "stair_short",
     {"stair_storeys": -1, "missing": 0, "token": 0, "shortfall_m2": 0,
      "circ_orphan_m2": "+"}),
    ("a corridor cell that joins two parts made outside", CLEAN9, "corridor_cut",
     {"circ_pieces": "+", "missing": 0}),
]


def stair_short(root):
    """Relabel the top-storey cell of every stair shaft as corridor: the
    stair now stops a storey lower, and the cell is still circulation."""
    lvls = dom.levels(root)
    for leaf in lvls[0].leaves():
        shaft = graph_mod.stair_shaft(leaf)
        if len(shaft) == len(lvls):
            shaft[-1].type = "C"


def _circ_cut_vertex(root):
    """The first corridor cell (by storey, then id) whose removal splits its
    storey's circulation, in the plain adjacency graph."""
    import networkx as nx
    for lvl in dom.levels(root):
        G = geometry.leaf_graph(lvl, 0.0)
        H = G.subgraph([n for n in G.nodes() if n.type == "C"])
        for n in sorted(nx.articulation_points(H), key=lambda n: n.id):
            return n
    return None


def corridor_cut(root):
    """Retype a corridor cell that joins two parts of a storey's circulation
    as a store: the circulation is now in two pieces."""
    n = _circ_cut_vertex(root)
    if n is not None:
        n.type = "O"


EDITS = {"stair_short": stair_short, "corridor_cut": corridor_cut}


def self_test(progs):
    ok, ever = True, set()
    for what, base, edited, want in CONTROLS:
        b, _ = card_of(progs, base, "maple-court")
        if edited in EDITS:
            e, _ = card_of(progs, base, "maple-court", EDITS[edited])
            label = f"{base.relative_to(REPO)}, {edited}()"
        else:
            e, _ = card_of(progs, edited, "maple-court")
            label = str(edited.relative_to(REPO))
        moved = {c: (b[c], e[c]) for c in DESIGN_COLS if fmt(b[c]) != fmt(e[c])}
        print(f"\n{what}: {label}")
        ever |= set(moved)
        for c, need in want.items():
            d = e[c] - b[c]
            good = d > 0 if need == "+" else d < 0 if need == "-" else abs(d - need) < 1e-9
            ok &= good
            print(f"  {'ok ' if good else 'BAD'} {c}: {fmt(b[c])} -> {fmt(e[c])}")
        for c, (x, y) in moved.items():
            if c not in want:
                print(f"      also {c}: {fmt(x)} -> {fmt(y)}")
    # a column that no control moves is a column nothing has shown can move
    still = [c for c in DESIGN_COLS if c not in ever]
    print(f"\ncolumns no control moved: {', '.join(still) or 'none'}")
    print("negative control:", "PASS" if ok else "FAIL")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--tsv", help="also write the design rows here")
    ap.add_argument("--rooms", help="write a row per room cell here")
    ap.add_argument("--self-test", action="store_true", help="run the negative control")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    progs = Programmes()
    if a.self_test:
        return 0 if self_test(progs) else 1
    head = "programme\tdesign\t" + "\t".join(DESIGN_COLS)
    rhead = "programme\tdesign\t" + "\t".join(ROOM_COLS)
    lines, rlines = [], []
    print(head)
    for path in a.designs:
        p = progs(path)
        if p is None:
            print(f"# skipped, no programme in path: {path}", file=sys.stderr)
            continue
        row, rooms = card_of(progs, path)
        line = f"{p[0]}\t{path}\t" + "\t".join(fmt(row[c]) for c in DESIGN_COLS)
        print(line, flush=True)
        lines.append(line)
        rlines += [f"{p[0]}\t{path}\t" + "\t".join(fmt(r[c]) for c in ROOM_COLS) for r in rooms]
    if a.tsv:
        Path(a.tsv).write_text(head + "\n" + "\n".join(lines) + "\n")
    if a.rooms:
        Path(a.rooms).write_text(rhead + "\n" + "\n".join(rlines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
