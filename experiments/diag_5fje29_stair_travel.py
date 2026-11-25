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
import copy
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
        self.doors_of = {}     # leaf -> its door nodes (for `fast_stair_moves`)
        for leaf, ds in doors_of.items():
            ds = list(dict.fromkeys(ds))
            self.doors_of[leaf] = ds
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
        """{(a, b): walk} for every pair of rooms on different storeys.

        Every journey between storeys passes through at least one stair node,
        so its shortest walk is the minimum over stair nodes s of d(a, s) +
        d(s, b), with distances over the WHOLE building: one Dijkstra per
        stair node. The first version walked each storey alone and took one
        stair per journey, which misses a journey that changes stairs on a
        third storey -- down one stair, across the ground, up another. On
        `split-stair-race/final-best-3` that was 100 of 968 pairs (found
        2026-11-25, §39.267); the self-test holds it to the brute force."""
        stairs = {n for e in self.W.edges(data=True) if e[2].get("flight") for n in e[:2]}
        to = {}    # stair node -> {room: walk}
        for s in stairs:
            d = nx.single_source_dijkstra_path_length(self.W, s, weight="weight")
            to[s] = {r: d[r] for r in self.rooms if r in d}
        walks = {}
        rooms = list(self.rooms)
        for a, b in itertools.combinations(rooms, 2):
            if self.rooms[a] == self.rooms[b]:
                continue
            best = min((t[a] + t[b] for t in to.values() if a in t and b in t), default=None)
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

    def room_detours(self, walks=None):
        """{room: mean detour (walk - plan, m) over its reachable journeys to
        rooms on other storeys} -- the per-room form of the design's mean
        (§39.267): the design reading is these averaged by journey."""
        walks = self.detour_cheap() if walks is None else walks
        acc = {}
        for pair, w in walks.items():
            a, b = tuple(pair)
            ex = w - math.dist(self.W.nodes[a]["xy"], self.W.nodes[b]["xy"])
            for r in (a, b):
                acc.setdefault(r, []).append(ex)
        return {r: statistics.fmean(v) for r, v in acc.items()}

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
        lvl = dom.levels(root)[0]
        pts = [geometry.coordinate(lvl, i) for i in range(geometry.n_edges(lvl))]
        half = math.dist((min(q[0] for q in pts), min(q[1] for q in pts)),
                         (max(q[0] for q in pts), max(q[1] for q in pts))) / 2
        rd = w.room_detours()
        out.update(half_diag=half, room_detour=sorted(v / half for v in rd.values()))
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


def _mean_detour(w):
    ex, _ra, un = w.detour()
    return (statistics.fmean(ex) if ex else math.nan), len(ex)


CANDIDATES = "circulation"


def stair_moves(fit, root, candidates=None):
    """Per stair (§39.268): how much better would the building's mean detour
    be with THIS stair moved to the best other column it could stand in?

    A shaft is a stair path and the storeys it serves. A candidate is any
    other path that is a circulation cell (`C`, not a stair) on every one of
    those storeys, so the stair could stack there; moving it relabels the
    shaft's `E` cells `C` and the candidate's `C` cells `E`. A candidate
    counts only if every journey the design reaches it still reaches, so a
    move cannot shorten the mean by cutting a storey off. Returns, per
    shaft: (path, storeys, actual mean, best mean, best path, candidates).

    ``candidates="indoor"``: any other path that is indoor and not a stair on
    every storey of the shaft, rooms included; the move SWAPS labels, so a
    displaced room takes the stair's old cell and the room set is kept. That
    asks "is this the best place in the plan for a stair", where the strict
    form asks "is there a corridor column it could move to" -- which is rare
    (§39.268)."""
    candidates = candidates or CANDIDATES
    merged = copy.deepcopy(root)
    w0 = Walk(fit, merged)           # merges `merged` in place
    actual, n0 = _mean_detour(w0)
    lvls = dom.levels(merged)
    shafts = {}
    for lv, ss in w0.stairs.items():
        for sid in ss:
            shafts.setdefault(sid, []).append(lv)
    out = []
    for sid, span in sorted(shafts.items()):
        if len(span) < 2:
            continue
        cands = []
        for leaf in lvls[span[0]].leaves():
            p = leaf.id
            if p == sid:
                continue
            cells = [lvls[lv].by_id(p) for lv in span]
            ok = (lambda c: c.type == "C") if candidates == "circulation" else (
                lambda c: not dom.is_outside(c) and c.type != dom.GENERIC_STAIR)
            if all(c is not None and not c.divided and ok(c) for c in cells):
                cands.append(p)
        best = (actual, sid)
        for p in cands:
            t = copy.deepcopy(merged)
            tl = dom.levels(t)
            for lv in span:
                old, new = tl[lv].by_id(sid), tl[lv].by_id(p)
                old.type, new.type = new.type, dom.GENERIC_STAIR   # a swap
            dom.link(t)
            geometry.clear_cache()
            m, n = _mean_detour(Walk(fit, t))
            if n >= n0 and m < best[0]:
                best = (m, p)
        out.append((sid or "root", span, actual, best[0], best[1], len(cands)))
    geometry.clear_cache()
    return out


def _vector_mean(W, rooms, stair_nodes):
    """Mean detour over every reachable pair of rooms on different storeys:
    one whole-building Dijkstra per stair node, then a vectorised minimum
    over stairs of d(a, s) + d(s, b) (exact, §39.267)."""
    import numpy as np
    R = list(rooms)
    idx = {r: i for i, r in enumerate(R)}
    D = np.full((len(stair_nodes), len(R)), np.inf)
    for k, s in enumerate(stair_nodes):
        for r, d in nx.single_source_dijkstra_path_length(W, s, weight="weight").items():
            if r in idx:
                D[k, idx[r]] = d
    walk = np.min(D[:, :, None] + D[:, None, :], axis=0) if len(stair_nodes) else \
        np.full((len(R), len(R)), np.inf)
    xy = np.array([W.nodes[r]["xy"] for r in R])
    plan = np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=2)
    lv = np.array([rooms[r] for r in R])
    iu = np.triu_indices(len(R), 1)
    mask = (lv[:, None] != lv[None, :])[iu] & np.isfinite(walk[iu])
    ex = (walk - plan)[iu][mask]
    return (float(ex.mean()) if ex.size else math.nan), int(ex.size)


def fast_stair_moves(fit, root):
    """`stair_moves(..., "indoor")` without rebuilding the walk graph per
    candidate (§39.268): the graph is built once, and a swap edits only the
    two columns -- the candidate cell becomes walk-through circulation with
    a stair node, the stair's old cell a room (or stays circulation, if the
    candidate was a corridor). DOORS ARE KEPT as the design has them: the one
    approximation, since the scorer's door rules can depend on the labels;
    `--per-stair --fast --check` holds it to the exact version."""
    merged = copy.deepcopy(root)
    w = Walk(fit, merged)
    W0, rooms0 = w.W, dict(w.rooms)
    stair_nodes0 = [n for n in W0 if n[0] == "stair"]
    actual, n0 = _vector_mean(W0, rooms0, stair_nodes0)
    lvls = dom.levels(merged)
    shafts = {}
    for lv, ss in w.stairs.items():
        for sid in ss:
            shafts.setdefault(sid, []).append(lv)
    out = []
    for sid, span in sorted(shafts.items()):
        if len(span) < 2:
            continue
        cands = []
        for leaf in lvls[span[0]].leaves():
            p = leaf.id
            if p == sid:
                continue
            cells = [lvls[lv].by_id(p) for lv in span]
            if all(c is not None and not c.divided and not dom.is_outside(c)
                   and c.type != dom.GENERIC_STAIR and c in w.doors_of for c in cells):
                cands.append(p)
        best = (actual, sid)
        for p in cands:
            W = W0.copy()
            rooms = dict(rooms0)
            new_stairs = []
            for lv in span:
                old, new = lvls[lv].by_id(sid), lvls[lv].by_id(p)
                s_old = w.stairs[lv][sid]
                # the candidate cell: walk-through, with a stair node
                if not dom.is_circulation(new):
                    rn = ("room", id(new))
                    W.remove_node(rn)
                    rooms.pop(rn, None)
                    ds = w.doors_of[new]
                    for a, b in itertools.combinations(ds, 2):
                        W.add_edge(a, b, weight=math.dist(W.nodes[a]["xy"], W.nodes[b]["xy"]))
                    # the displaced room takes the stair's old cell
                    W.remove_node(s_old)
                    for a, b in itertools.combinations(w.doors_of[old], 2):
                        if W.has_edge(a, b):
                            W.remove_edge(a, b)
                    rc = ("room", "moved", lv)
                    W.add_node(rc, xy=geometry.centroid(old), level=lv)
                    for d in w.doors_of[old]:
                        W.add_edge(rc, d, weight=math.dist(W.nodes[rc]["xy"], W.nodes[d]["xy"]))
                    rooms[rc] = lv
                else:
                    W.remove_node(s_old)            # old cell stays a corridor
                sn = ("stair", lv, "cand")
                W.add_node(sn, xy=geometry.centroid(new), level=lv)
                for d in w.doors_of[new]:
                    W.add_edge(sn, d, weight=math.dist(W.nodes[sn]["xy"], W.nodes[d]["xy"]))
                new_stairs.append(sn)
            for a, b in zip(new_stairs, new_stairs[1:]):
                W.add_edge(a, b, weight=0.0, flight=True)
            stair_nodes = [n for n in W if n[0] == "stair"]
            m, n = _vector_mean(W, rooms, stair_nodes)
            if n >= n0 and m < best[0]:
                best = (m, p)
        out.append((sid or "root", span, actual, best[0], best[1], len(cands)))
    geometry.clear_cache()
    return out


def self_test(progs) -> bool:
    """The cheap detour equals the brute force on two-storey designs; with
    the flights removed no inter-storey pair is reachable (negative control);
    and with every exit removed the ground floor has no target."""
    ok = True
    for path in (CORRIDORS / "winner.dom",
                 REPO / "experiments/results/halving-health-swap/winner.dom",
                 # three storeys; the maple-court drawing first named here was
                 # never committed (found 2026-11-25), so the self-test could not run
                 REPO / "experiments/results/split-stair-race/final-best-3.dom"):
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
        # the per-room reading is the design's, decomposed: each journey
        # counts once for each of its two rooms, so the journey-weighted mean
        # of the room means is the design mean
        rd, n = w.room_detours(cheap), {}
        for pair in cheap:
            for r in pair:
                n[r] = n.get(r, 0) + 1
        ex, _ra, _un = w.detour()
        back = sum(rd[r] * n[r] for r in rd) / (2 * len(cheap))
        print(f"  per-room means give back the design mean: {back:.4f} = {statistics.fmean(ex):.4f}")
        ok &= abs(back - statistics.fmean(ex)) < 1e-9
    w.W.remove_edges_from([(a, b) for a, b, d in w.W.edges(data=True) if d.get("flight")])
    print("no flights: reachable pairs", len(w.detour_cheap()), len(w.detour_brute()))
    ok &= not w.detour_cheap() and not w.detour_brute()
    w.exits = set()
    print("no exits: ground dead end", w.dead_end(0))
    ok &= w.dead_end(0) == (None, None)
    print("self-test:", "PASS" if ok else "FAIL")
    return ok


# the per-room threshold, in plot half-diagonals (owner 2026-11-25: 0.75 to start)
PER_ROOM = 0.75


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
              f"\tratio {r['ratio_mean']:.2f}"
              f"\tscale-free mean {r['excess_mean'] / r['half_diag']:.2f}"
              f"\trooms over {PER_ROOM} {sum(v > PER_ROOM for v in r['room_detour'])}"
              f" of {len(r['room_detour'])}")
    return s + f"\t{r['ms']:.0f} ms"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--per-stair", action="store_true",
                    help="per stair: the mean detour with it moved to its best column (§39.268)")
    ap.add_argument("--fast", action="store_true",
                    help="with --per-stair: the graph-reusing version (indoor candidates)")
    ap.add_argument("--check", action="store_true",
                    help="with --fast: run the exact version beside it and print both")
    ap.add_argument("--candidates", choices=("circulation", "indoor"), default="circulation",
                    help="with --per-stair: columns that are corridor on every storey the "
                         "stair serves, or any indoor column (a swap with the rooms there)")
    ap.add_argument("--per-room", type=float, default=PER_ROOM,
                    help="count rooms whose own mean detour is over this many plot "
                         "half-diagonals (§39.267)")
    a = ap.parse_args()
    globals()["PER_ROOM"] = a.per_room
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    progs = rc.Programmes()
    if a.self_test:
        return 0 if self_test(progs) else 1
    if a.per_stair:
        print("design\tprogramme\tstair\tstoreys\tactual_m\tbest_m\tgain\tbest_at\tcandidates")
        for path in a.designs:
            p = progs(path)
            if p is None:
                continue
            root = dom.load(str(path))
            dom.link(root)
            if len(dom.levels(root)) < 2:
                continue
            if a.fast:
                t0 = time.process_time()
                res = fast_stair_moves(p[1], root)
                ms = 1000 * (time.process_time() - t0)
                if a.check:
                    root = dom.load(str(path))
                    dom.link(root)
                    t0 = time.process_time()
                    exact = stair_moves(p[1], root, "indoor")
                    ems = 1000 * (time.process_time() - t0)
                    for f, e in zip(res, exact):
                        print(f"{path}\t{p[0]}\t{f[0]}\tfast gain {(f[2]-f[3])/f[2] if f[2] else 0:.3f} "
                              f"at {f[4]}\texact gain {(e[2]-e[3])/e[2] if e[2] else 0:.3f} at {e[4]}"
                              f"\tfast {ms:.0f} ms exact {ems:.0f} ms", flush=True)
                    continue
            else:
                res = stair_moves(p[1], root, a.candidates)
            for sid, span, act, best, at, nc in res:
                gain = (act - best) / act if act and not math.isnan(act) else math.nan
                print(f"{path}\t{p[0]}\t{sid}\t{span[0]}-{span[-1]}\t{act:.2f}\t{best:.2f}\t"
                      f"{gain:.3f}\t{at}\t{nc}", flush=True)
        return 0
    for path in a.designs:
        r = measure(progs, path)
        if r is not None:
            print(f"{path}\t{fmt(r)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
