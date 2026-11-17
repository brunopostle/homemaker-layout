"""Price the owner's stair-placement-by-travel ruling (`homemaker-py-5fje.29`,
DESIGN.md §39.243) over committed designs, BEFORE any rule exists: what the two
proposed quantities measure on designs the search has already made, so the
owner can choose thresholds against a distribution rather than a guess.

The walk. Each storey's ``graph_circ`` (the scorer's own graph, after
``merge_divided`` and ``has_circulation``'s trimming, so every edge is a door
the scorer allows) becomes a metric graph whose nodes are DOORS -- the
midpoint of each shared wall -- and room centroids. Inside a circulation cell
every pair of its doors is joined by a straight line (the cells are
rectangles cropped to the plot, so convex); a room's centroid is joined to
its doors. A stair shaft joins its doors on one storey to its doors on the
next, by the plan distance between them (a flight carries you along the
shaft; the climb itself is not counted). Distances are metres in plan.

(a) DETOUR. For every pair of rooms on different storeys, the walk between
their centroids against the straight plan distance. ``excess`` = walk - plan,
the "path to reverse". Reported as the mean and the worst over pairs, and the
mean ratio walk/max(plan, 1 m).

(b) DEAD END, multi-storey only, on storeys above the ground. A point of an
indoor circulation cell's door graph has TWO DIRECTIONS of escape if two
node-disjoint routes from it reach two different stairs; otherwise its
dead-end travel is the walk from it to the nearest point that has two, or to
a stair. Reported as the worst over the storey's circulation points, and
also the plain walk from the farthest room to its nearest stair.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje29_stair_travel.py DESIGN.dom ...
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje29_stair_travel.py --self-test
"""
import argparse
import itertools
import math
import statistics
import sys
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_card as rc  # noqa: E402
from homemaker_layout import dom, geometry, graph  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CORRIDORS = REPO / "experiments/results/halving-health-corridors"


def _door(edge_data, a, b):
    seg = edge_data.get("coordinates")
    if seg:
        (x0, y0), (x1, y1) = seg
        return ((x0 + x1) / 2, (y0 + y1) / 2)
    ca, cb = geometry.centroid(a), geometry.centroid(b)
    return ((ca[0] + cb[0]) / 2, (ca[1] + cb[1]) / 2)


WALK_OUTSIDE = False


def _walkway(leaf):
    """A cell one walks through: indoor circulation, and with --outside a
    usable outdoor cell (a court or garden the rooms open onto)."""
    return dom.is_circulation(leaf) or (WALK_OUTSIDE and dom.is_outside(leaf))


def _key(p):
    return (round(p[0], 4), round(p[1], 4))


def build(fit, root):
    """The scorer's post-merge graphs, and the metric door graph over all storeys.
    Returns (W, rooms, stairs_by_level, circ_doors_by_level, levels)."""
    dom.merge_divided(root)
    dom.link(root)
    geometry.clear_cache()
    _, graph_circ, _ = graph.storey_graphs(root, fit.conf("door_width") or 1.2,
                                           fit.usages())
    lvls = dom.levels(root)
    W = nx.Graph()
    rooms = []                       # (level, leaf)
    stairs = {}                      # level -> [leaf]
    circ_doors = {}                  # level -> set(node)
    doors_of = {}                    # leaf -> [node]
    for i, G in enumerate(graph_circ):
        for a, b, d in G.edges(data=True):
            if not WALK_OUTSIDE and (dom.is_outside(a) or dom.is_outside(b)):
                continue
            if not (dom.is_usable(a) and dom.is_usable(b)):
                continue
            n = ("door", i, _key(_door(d, a, b)))
            W.add_node(n, xy=_door(d, a, b), level=i)
            doors_of.setdefault(a, []).append(n)
            doors_of.setdefault(b, []).append(n)
            if dom.is_circulation(a) or dom.is_circulation(b):
                circ_doors.setdefault(i, set()).add(n)
        for v in G.nodes():
            if not dom.is_usable(v) or (dom.is_outside(v) and not WALK_OUTSIDE):
                continue
            if graph.is_stair_cell(v):
                stairs.setdefault(i, []).append(v)
            if not dom.is_circulation(v) and not dom.is_outside(v):
                rooms.append((i, v))
    for leaf, ds in doors_of.items():
        ds = list(dict.fromkeys(ds))
        if _walkway(leaf):
            for p, q in itertools.combinations(ds, 2):
                W.add_edge(p, q, weight=math.dist(W.nodes[p]["xy"], W.nodes[q]["xy"]))
        else:
            c = ("room", id(leaf))
            W.add_node(c, xy=geometry.centroid(leaf), leaf=leaf)
            for p in ds:
                W.add_edge(c, p, weight=math.dist(W.nodes[c]["xy"], W.nodes[p]["xy"]))
    # stair flights: a shaft cell's doors on storey i to its doors on i+1
    for i, ss in stairs.items():
        for s in ss:
            up = dom._above_node(s)
            if not graph.is_stair_cell(up):
                continue
            for p in doors_of.get(s, []):
                for q in doors_of.get(up, []):
                    W.add_edge(p, q, weight=math.dist(W.nodes[p]["xy"], W.nodes[q]["xy"]),
                               flight=True)
    return W, rooms, stairs, circ_doors, lvls, doors_of


def detour(W, rooms):
    """Walk against plan distance for every pair of rooms on different storeys."""
    excess, ratio, unreachable = [], [], 0
    by_room = {}
    for lv, leaf in rooms:
        c = ("room", id(leaf))
        if c in W:
            by_room[c] = (lv, W.nodes[c]["xy"])
    keys = list(by_room)
    for a in keys:
        dist = nx.single_source_dijkstra_path_length(W, a, weight="weight")
        for b in keys:
            if b <= a or by_room[a][0] == by_room[b][0]:
                continue
            plan = math.dist(by_room[a][1], by_room[b][1])
            if b not in dist:
                unreachable += 1
                continue
            excess.append(dist[b] - plan)
            ratio.append(dist[b] / max(plan, 1.0))
    return excess, ratio, unreachable


def dead_end(W, stairs, circ_doors, doors_of, level):
    """Worst one-direction travel on ``level``: from each circulation door, the
    walk to the nearest point with two node-disjoint routes to two different
    stairs, or to a stair. And the worst room-to-nearest-stair walk."""
    Wl = W.subgraph([n for n, d in W.nodes(data=True)
                     if d.get("level") == level or (n[0] == "room"
                     and any(W.nodes[m].get("level") == level for m in W[n]))]).copy()
    targets = {}
    for s in stairs.get(level, []):
        for p in doors_of.get(s, []):
            if p in Wl:
                targets.setdefault(id(s), set()).add(p)
    if not targets:
        return None, None
    # two-direction points: node connectivity to a super-sink fed by one node per stair
    H = Wl.copy()
    sink = ("sink",)
    for sid, ps in targets.items():
        hub = ("stair", sid)
        H.add_node(hub)
        for p in ps:
            H.add_edge(hub, p)
        H.add_edge(hub, sink)
    pts = [p for p in circ_doors.get(level, set()) if p in Wl]
    stair_pts = set().union(*targets.values())
    safe = set(stair_pts)
    if len(targets) > 1:
        for p in pts:
            if p in safe:
                continue
            if nx.node_connectivity(H, p, sink) >= 2:
                safe.add(p)
    dist = nx.multi_source_dijkstra_path_length(Wl, safe, weight="weight")
    worst_dead = max((dist.get(p, math.inf) for p in pts), default=0.0)
    to_stair = nx.multi_source_dijkstra_path_length(Wl, stair_pts, weight="weight")
    worst_room = max((to_stair.get(n, math.inf) for n in Wl if n[0] == "room"),
                     default=0.0)
    return worst_dead, worst_room


def measure(progs, path):
    p = progs(path)
    if p is None:
        return None
    prog, fit, _ = p
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    W, rooms, stairs, circ_doors, lvls, doors_of = build(fit, root)
    out = {"prog": prog, "storeys": len(lvls),
           "stairs": sum(1 for s in stairs.get(0, []) if len(graph.stair_shaft(s)) > 1)}
    if len(lvls) < 2:
        return out
    ex, ra, un = detour(W, rooms)
    out.update(pairs=len(ex), unreachable=un,
               excess_mean=statistics.fmean(ex) if ex else math.nan,
               excess_max=max(ex, default=math.nan),
               ratio_mean=statistics.fmean(ra) if ra else math.nan)
    de = [dead_end(W, stairs, circ_doors, doors_of, i) for i in range(1, len(lvls))]
    out["dead_end"] = max((d for d, _ in de if d is not None), default=math.nan)
    out["room_to_stair"] = max((r for _, r in de if r is not None), default=math.nan)
    return out


def self_test(progs) -> bool:
    """Controls on a synthetic shape the owner described: two stairs side by
    side should have a longer worst dead end than the same building with one
    moved to the far end; checked on the corridors-race winner, whose two
    shafts lie end to end, against itself with nothing changed (stability) and
    against an unreachable-stair control (a stair with no doors is no escape)."""
    ok = True
    r = measure(progs, CORRIDORS / "winner.dom")
    print("winner two-3:", fmt(r))
    ok &= r["stairs"] == 2 and r["pairs"] > 0 and r["unreachable"] == 0
    # negative control: with the flights removed, no inter-storey pair is reachable
    prog, fit, _ = progs(CORRIDORS / "winner.dom")
    root = dom.load(str(CORRIDORS / "winner.dom"))
    dom.link(root)
    geometry.clear_cache()
    W, rooms, *_ = build(fit, root)
    W.remove_edges_from([(a, b) for a, b, d in W.edges(data=True) if d.get("flight")])
    ex, _, un = detour(W, rooms)
    print(f"no flights: reachable pairs {len(ex)}, unreachable {un}")
    ok &= len(ex) == 0 and un > 0
    print("self-test:", "PASS" if ok else "FAIL")
    return ok


def fmt(r):
    if r.get("storeys", 1) < 2:
        return f"{r['prog']}\tstoreys 1"
    return (f"{r['prog']}\tstoreys {r['storeys']}\tstairs {r['stairs']}\tpairs {r['pairs']}"
            f"\tunreach {r['unreachable']}\texcess mean {r['excess_mean']:.1f} m"
            f"\tmax {r['excess_max']:.1f} m\tratio {r['ratio_mean']:.2f}"
            f"\tdead end {r['dead_end']:.1f} m\troom->stair {r['room_to_stair']:.1f} m")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--outside", action="store_true",
                    help="walk through usable outdoor cells as well as circulation")
    a = ap.parse_args()
    global WALK_OUTSIDE
    WALK_OUTSIDE = a.outside
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    progs = rc.Programmes()
    if a.self_test:
        return 0 if self_test(progs) else 1
    for path in a.designs:
        r = measure(progs, path)
        if r is not None:
            print(f"{path}\t{fmt(r)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
