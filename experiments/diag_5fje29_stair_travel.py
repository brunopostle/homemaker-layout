"""Price the owner's stair-placement-by-travel ruling (`homemaker-py-5fje.29`,
DESIGN.md §39.243-§39.245) over committed designs, BEFORE any rule exists:
what the proposed quantities measure on designs the search has already made,
so the owner can choose thresholds against a distribution rather than a guess.

The walk. Each storey's ``graph_circ`` (the scorer's own graph, after
``merge_divided`` and ``has_circulation``'s trimming, so every edge is a door
the scorer allows) becomes a metric graph whose nodes are DOORS -- the
midpoint of each shared wall -- and room centroids. Inside a circulation cell
every pair of its doors is joined by a straight line (the cells are
rectangles cropped to the plot, so convex); a room's centroid is joined to
its doors. Each stair cell has a node at its centroid joined to its doors,
and a shaft's nodes on consecutive storeys are joined at no cost (the climb
is not counted). Distances are metres in plan.

(a) DETOUR. For every pair of rooms on different storeys, the walk between
their centroids against the straight plan distance; ``excess`` = walk - plan,
the "path to reverse". Computed cheaply (owner, 2026-11-17: "calculating all
possible journeys is likely to be expensive, we need to be clever"): every
inter-storey journey goes through a stair, so one Dijkstra per (storey,
stair) gives every room's walk to every stair, and a journey is
``min over stairs s of d(a, s) + d(b, s)`` -- S x storeys searches and R^2 x S
additions, instead of R searches over the whole building. ``--self-test``
checks it against the brute force.

(b) DEAD END (owner, 2026-11-17: 11 m, "distances to a stair core and ground
floor distances to exits"). Escape targets: on a storey above the ground, the
stair cells; on the ground, the exits -- a circulation cell with a street
door (``Fitness._public_access``; the door is taken at the cell's centroid,
which is at most half a cell out) and every door, from circulation or from a
room, to a usable outdoor cell (taken as a place of safety). A point has two directions of escape if it shares a biconnected
block with a super-sink joined to every target, i.e. two node-disjoint routes
reach two different targets (linear time: ``nx.biconnected_components``).
Otherwise its one-direction travel is the walk to the nearest point that has
two, or to a target. Reported as the worst over circulation doors ("corridor
dead end") and over room centroids ("from the room"), per storey kind.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje29_stair_travel.py DESIGN.dom ...
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje29_stair_travel.py --self-test
"""
import argparse
import itertools
import math
import statistics
import sys
import time
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_card as rc  # noqa: E402
from homemaker_layout import dom, geometry, graph  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CORRIDORS = REPO / "experiments/results/halving-health-corridors"
DEAD_END = 11.0          # owner, 2026-11-17


def _door(edge_data, a, b):
    seg = edge_data.get("coordinates")
    if seg:
        (x0, y0), (x1, y1) = seg
        return ((x0 + x1) / 2, (y0 + y1) / 2)
    ca, cb = geometry.centroid(a), geometry.centroid(b)
    return ((ca[0] + cb[0]) / 2, (ca[1] + cb[1]) / 2)


def _key(p):
    return (round(p[0], 4), round(p[1], 4))


class Walk:
    """The metric walk graph of a design, and what was found building it."""

    def __init__(self, fit, root):
        dom.merge_divided(root)
        dom.link(root)
        geometry.clear_cache()
        _, graph_circ, _ = graph.storey_graphs(root, fit.conf("door_width") or 1.2,
                                               fit.usages())
        self.levels = dom.levels(root)
        W = self.W = nx.Graph()
        self.rooms = {}        # node -> level
        self.stairs = {}       # level -> {shaft id: node}
        self.exits = set()     # ground-floor exit nodes
        self.circ = {}         # level -> set(door node of a circulation cell)
        doors_of = {}
        for i, G in enumerate(graph_circ):
            for a, b, d in G.edges(data=True):
                if not (dom.is_usable(a) and dom.is_usable(b)):
                    continue
                oa, ob = dom.is_outside(a), dom.is_outside(b)
                if oa and ob:
                    continue
                xy = _door(d, a, b)
                n = ("door", i, _key(xy))
                W.add_node(n, xy=xy, level=i)
                if oa or ob:
                    inner = b if oa else a
                    doors_of.setdefault(inner, []).append(n)
                    if i == 0:
                        self.exits.add(n)
                    continue
                doors_of.setdefault(a, []).append(n)
                doors_of.setdefault(b, []).append(n)
                if dom.is_circulation(a) or dom.is_circulation(b):
                    self.circ.setdefault(i, set()).add(n)
            for v in G.nodes():
                if (i == 0 and dom.is_circulation(v) and not graph.is_stair_cell(v)
                        and fit._public_access(v, root) is not None):
                    n = ("street", id(v))
                    W.add_node(n, xy=geometry.centroid(v), level=0)
                    doors_of.setdefault(v, []).append(n)
                    self.exits.add(n)
        for leaf, ds in doors_of.items():
            ds = list(dict.fromkeys(ds))
            lv = W.nodes[ds[0]]["level"]
            if dom.is_circulation(leaf):
                for p, q in itertools.combinations(ds, 2):
                    W.add_edge(p, q, weight=math.dist(W.nodes[p]["xy"], W.nodes[q]["xy"]))
                if graph.is_stair_cell(leaf):
                    s =("stair", lv, leaf.id)
                    W.add_node(s, xy=geometry.centroid(leaf), level=lv, leaf=leaf)
                    for p in ds:
                        W.add_edge(s, p, weight=math.dist(W.nodes[s]["xy"], W.nodes[p]["xy"]))
                    self.stairs.setdefault(lv, {})[leaf.id] = s
            else:
                c = ("room", id(leaf))
                W.add_node(c, xy=geometry.centroid(leaf), level=lv)
                for p in ds:
                    W.add_edge(c, p, weight=math.dist(W.nodes[c]["xy"], W.nodes[p]["xy"]))
                self.rooms[c] = lv
        # flights: the same E cell (same path) on consecutive storeys, at no cost
        for lv, ss in self.stairs.items():
            for sid, s in ss.items():
                up = self.stairs.get(lv + 1, {}).get(sid)
                if up is not None and graph.is_stair_cell(dom._above_node(W.nodes[s]["leaf"])):
                    W.add_edge(s, up, weight=0.0, flight=True)

    def storey(self, lv):
        return self.W.subgraph([n for n, d in self.W.nodes(data=True)
                                if d.get("level") == lv])

    # ---------------------------------------------------------------- detour
    def detour_cheap(self):
        """{(a, b): walk} for every pair of rooms on different storeys, via
        one Dijkstra per (storey, stair)."""
        # shafts: chains of stair nodes joined by flights
        flights = nx.Graph([(a, b) for a, b, d in self.W.edges(data=True) if d.get("flight")])
        shafts = [sorted(c, key=lambda n: n[1]) for c in nx.connected_components(flights)]
        to = {}    # (shaft index, room) -> walk from the room to the shaft
        for k, shaft in enumerate(shafts):
            for s in shaft:
                d = nx.single_source_dijkstra_path_length(self.storey(s[1]), s, weight="weight")
                for r, lv in self.rooms.items():
                    if lv == s[1] and r in d:
                        to[k, r] = d[r]
        walks = {}
        rooms = list(self.rooms)
        for a, b in itertools.combinations(rooms, 2):
            if self.rooms[a] == self.rooms[b]:
                continue
            best = min((to[k, a] + to[k, b] for k in range(len(shafts))
                        if (k, a) in to and (k, b) in to), default=None)
            if best is not None:
                walks[frozenset((a, b))] = best
        return walks

    def detour_brute(self):
        walks = {}
        rooms = list(self.rooms)
        for a in rooms:
            d = nx.single_source_dijkstra_path_length(self.W, a, weight="weight")
            for b in rooms:
                if self.rooms[a] != self.rooms[b] and b in d:
                    walks[frozenset((a, b))] = d[b]
        return walks

    def detour(self):
        walks = self.detour_cheap()
        rooms = list(self.rooms)
        total = sum(1 for a, b in itertools.combinations(rooms, 2)
                    if self.rooms[a] != self.rooms[b])
        excess, ratio = [], []
        for pair, w in walks.items():
            a, b = tuple(pair)
            plan = math.dist(self.W.nodes[a]["xy"], self.W.nodes[b]["xy"])
            excess.append(w - plan)
            ratio.append(w / max(plan, 1.0))
        return excess, ratio, total - len(walks)

    # -------------------------------------------------------------- dead end
    def dead_end(self, lv):
        """(worst corridor dead end, worst from a room) on storey ``lv``, or
        (None, None) if it has no escape target."""
        S = nx.Graph(self.storey(lv))
        targets = self.exits if lv == 0 else set(self.stairs.get(lv, {}).values())
        targets = [t for t in targets if t in S]
        if not targets:
            return None, None
        sink = ("sink",)
        S.add_edges_from((sink, t) for t in targets)
        safe = set(targets)
        for block in nx.biconnected_components(S):
            if sink in block and len(block) > 2:
                safe |= block
        safe.discard(sink)
        S.remove_node(sink)
        d = nx.multi_source_dijkstra_path_length(S, safe, weight="weight")
        circ = [p for p in self.circ.get(lv, ()) if p in S]
        rooms = [r for r, l in self.rooms.items() if l == lv and r in S]
        return (max((d.get(p, math.inf) for p in circ), default=0.0),
                max((d.get(r, math.inf) for r in rooms), default=0.0))


def measure(progs, path):
    p = progs(path)
    if p is None:
        return None
    prog, fit, _ = p
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    t0 = time.process_time()
    w = Walk(fit, root)
    n = len(w.levels)
    out = {"prog": prog, "storeys": n, "stairs": len(w.stairs.get(0, {}))}
    if n > 1:
        ex, ra, un = w.detour()
        out.update(pairs=len(ex), unreachable=un,
                   excess_mean=statistics.fmean(ex) if ex else math.nan,
                   excess_max=max(ex, default=math.nan),
                   ratio_mean=statistics.fmean(ra) if ra else math.nan)
    de = {lv: w.dead_end(lv) for lv in range(n)}
    out["ground"] = de[0]
    up = [v for lv, v in de.items() if lv > 0 and v[0] is not None]
    out["upper"] = (max((c for c, _ in up), default=math.nan),
                    max((r for _, r in up), default=math.nan)) if n > 1 else None
    out["ms"] = 1000 * (time.process_time() - t0)
    return out


def self_test(progs) -> bool:
    """The cheap detour equals the brute force on two-storey designs; with
    the flights removed no inter-storey pair is reachable (negative control);
    and with every exit removed the ground floor has no target."""
    ok = True
    for path in (CORRIDORS / "winner.dom",
                 REPO / "experiments/results/halving-health-swap/winner.dom",
                 REPO / "experiments/results/drawings-bestof/maple-court/maple-court.dom"):
        prog, fit, _ = progs(path)
        root = dom.load(str(path))
        dom.link(root)
        geometry.clear_cache()
        w = Walk(fit, root)
        t0 = time.process_time()
        cheap = w.detour_cheap()
        t1 = time.process_time()
        brute = w.detour_brute()
        t2 = time.process_time()
        diff = max((abs(cheap[k] - brute[k]) for k in brute if k in cheap), default=0.0)
        same = cheap.keys() == brute.keys() and diff < 1e-9
        print(f"{path.parent.name}/{path.name}: {len(brute)} pairs, cheap = brute: {same} "
              f"(max diff {diff:.2e}); cheap {1000*(t1-t0):.0f} ms, brute {1000*(t2-t1):.0f} ms")
        ok &= same and len(brute) > 0
    w.W.remove_edges_from([(a, b) for a, b, d in w.W.edges(data=True) if d.get("flight")])
    print("no flights: reachable pairs", len(w.detour_cheap()), len(w.detour_brute()))
    ok &= not w.detour_cheap() and not w.detour_brute()
    w.exits = set()
    print("no exits: ground dead end", w.dead_end(0))
    ok &= w.dead_end(0) == (None, None)
    print("self-test:", "PASS" if ok else "FAIL")
    return ok


def _m(x):
    return "-" if x is None else ("none" if math.isinf(x) else f"{x:.1f}")


def fmt(r):
    g = r["ground"]
    s = (f"{r['prog']}\tstoreys {r['storeys']}\tstairs {r['stairs']}"
         f"\tground dead end {_m(g[0])} / room {_m(g[1])}")
    if r["storeys"] > 1:
        u = r["upper"]
        s += (f"\tupper dead end {_m(u[0])} / room {_m(u[1])}"
              f"\tpairs {r['pairs']} unreach {r['unreachable']}"
              f"\texcess mean {r['excess_mean']:.1f} max {r['excess_max']:.1f}"
              f"\tratio {r['ratio_mean']:.2f}")
    return s + f"\t{r['ms']:.0f} ms"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
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
