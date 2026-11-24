"""Routed circulation, evaluated (`homemaker-py-8b2u.17`, DESIGN.md §39.259).

Today circulation is evolved: `C` cells are leaves like any other and the
search must discover a connected spine. The bead's question, asked of
committed designs in a container: erase the circulation the search found,
ROUTE it back -- cells placed, corridors laid afterwards on the graph between
them, as in circuit layout -- and compare. Can a router recover a connected
circulation, with how much floor, and how many connection fails does it
clear?

Erase (stairs `E` are kept: they are the anchors a corridor runs from):

- ``free``: every `C` cell is unlabelled. The router may re-choose any of
  them; the ones it does not use are given to a neighbouring room. This asks
  whether routing picks a corridor as good as the search's from the same
  cells.
- ``merge``: every `C` cell that can be is folded into its sibling room
  (the cut goes, the room takes the whole, the wall above stays,
  `dom.hand_cut_up`); the rest are unlabelled. The router must then mostly
  CUT corridors through rooms. This is the harder and more honest test.

Route, storey by storey from the ground (`route_storey`):

1. no circulation on the storey at all: seed one in the unlabelled cell
   nearest, by graph distance, to every room (a single-storey plan);
2. join the circulation pieces: `seed_from_catalogue.bridge_indoors`
   unchanged (Dijkstra: circulation 0, a plain cell 1, a room 5; a room on
   the path gives up a 1.6 m strip, never its label);
3. reach every room the SCORER calls unserved (`Fitness.access` empty --
   kitchens may open off living space, service rooms off any room but a
   bedroom): the cheapest path from the room to circulation, unlabelled
   cells made corridor, rooms on it cut a strip that leaves the room served.
   All or nothing per room, as `bridge_indoors` lays a bridge.

Then every cell still unlabelled is given to its sibling room, or made `C`
when it has none. The routed design is scored as is (`--inner N` re-tunes
its ratios as a search would tune a child, and the original's too, so a win
is not just the extra tuning).

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u17_route.py
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u17_route.py --mode free PATH.dom
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u17_route.py --self-test

Default designs: the race winners and finals (as `diag_oversized_rooms.py`)
and the newest `+orth` cold corpus.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import networkx as nx  # noqa: E402

import seed_from_catalogue as sfc  # noqa: E402
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, geometry, graph, innerloop, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402

KEYS = {"maple": "maple-court", "harbor": "harbor-house",
        "health": "health-centre", "programme-house": "programme-house",
        "split-stair": "maple-court", "join-clean9": "maple-court"}
FREE = "F"          # an unlabelled cell, while routing only; never scored
CONN = ("not connected", "inaccessible usable space", " access", "not adjacent to c",
        "no outside public access")


def conn_fails(fails) -> int:
    return sum(any(k in f for k in CONN) for f in fails)


def circ_area(root) -> float:
    return sum(geometry.area(lf) for lv in dom.levels(root) for lf in lv.leaves()
               if lf.type == "C")


def _merge_into_sibling(leaf) -> bool:
    """Fold ``leaf`` into its sibling when that is a single programme room
    and the cut is this storey's own."""
    n = leaf.parent
    if n is None or (n.below is not None and n.below.divided):
        return False
    sib = n.right if n.left is leaf else n.left
    if sib.divided or not sib.type or dom.is_generic(sib.type) or sib.type == FREE:
        return False
    n.type = sib.type
    dom.hand_cut_up(n)
    n.division = None
    n.left = n.right = None
    return True


def erase(root, mode: str) -> int:
    """Erase the circulation (`C`, not `E`); return how many cells were."""
    n = 0
    for lv in dom.levels(root):
        for lf in lv.leaves():
            if lf.type == "C":
                lf.type = FREE
                n += 1
    if mode == "merge":
        changed = True
        while changed:
            changed = False
            for lv in dom.levels(root):
                for lf in lv.leaves():
                    if lf.type == FREE and _merge_into_sibling(lf):
                        changed = True
                        break
                if changed:
                    break
            dom.link(root)
            geometry.clear_cache()
    return n


def _indoor_graph(lvl):
    geometry.clear_cache()
    G = geometry.leaf_graph(lvl, graph.DOOR_WIDTH)
    return G, G.subgraph([x for x in G if not dom.is_outside(x)])


def unserved(fit, lvl, reqs) -> list:
    G, _ = _indoor_graph(lvl)
    return sorted((x for x in G if x.type in reqs and not fit.access(x, G)),
                  key=lambda x: x.id or "")


def _cost(x, reqs) -> int:
    if dom.is_circulation(x):
        return 0
    return 5 if x.type in reqs else 1


def seed_circulation(lvl, reqs) -> bool:
    """A storey with no circulation at all: make the unlabelled cell nearest,
    in summed path cost, to every room into a corridor."""
    _, H = _indoor_graph(lvl)
    if any(dom.is_circulation(x) for x in H):
        return True
    free = [x for x in H if x.type == FREE]
    rooms = [x for x in H if x.type in reqs]
    if not free or not rooms:
        return False
    W = nx.Graph()
    W.add_edges_from((a, b, {"w": (_cost(a, reqs) + _cost(b, reqs)) / 2}) for a, b in H.edges())

    def total(x):
        d = nx.single_source_dijkstra_path_length(W, x, weight="w") if x in W else {}
        return sum(d.get(r, 1e6) for r in rooms)
    best = min(sorted(free, key=lambda x: x.id or ""), key=total)
    best.type = "C"
    return True


def strip_serving(lvl, room, target, fit, assume=()) -> bool:
    """Cut a 1.6 m corridor strip off ``room`` so that ``target`` is served
    (rooms in ``assume``, further along the path, counted as corridor): of
    the eight placements that serve it, the one the building scores best.
    The pattern is `seed_from_catalogue.bridge_strip`'s, with "serves the
    target" in place of "joins two pieces"."""
    kept = [(x, x.type) for x in assume]
    for x, _t in kept:
        x.type = "C"
    code = room.type
    building = lvl
    while building.below is not None:
        building = building.below
    best = None
    for rot in range(4):
        for side in (0, 1):
            room.type, room.rotation = None, rot
            room.left, room.right = dom.Node(type="C"), dom.Node(type="C")
            room.division = [0.5, 0.5]
            sfc._relink(lvl)
            geometry.clear_cache()
            span = max(1e-6, sfc.extent(room, sfc._cut_normal(room)))
            f = float(min(0.45, 1.6 / span))
            f = f if side == 0 else 1 - f
            room.division = [f, f]
            strip, rest = (room.left, room.right) if side == 0 else (room.right, room.left)
            strip.type, rest.type = "C", code
            sfc._relink(lvl)
            G, _ = _indoor_graph(lvl)
            if target in G and fit.access(target, G):
                sc = fit.score_with_fails(copy.deepcopy(building))[0]
                if best is None or sc > best[0]:
                    best = (sc, rot, side, f)
            geometry.clear_cache()
    for x, t in kept:
        x.type = t
    if best is None:
        room.type, room.division, room.left, room.right = code, None, None, None
        sfc._relink(lvl)
        geometry.clear_cache()
        return False
    _sc, rot, side, f = best
    room.type, room.rotation, room.division = None, rot, [f, f]
    room.left, room.right = (dom.Node(type="C"), dom.Node(type=code)) if side == 0 \
        else (dom.Node(type=code), dom.Node(type="C"))
    sfc._relink(lvl)
    geometry.clear_cache()
    return True


def reach(lvl, target, reqs, fit) -> bool:
    """Lay the cheapest path from ``target`` to circulation; all or nothing."""
    _, H = _indoor_graph(lvl)
    W = nx.Graph()
    W.add_nodes_from(H)
    W.add_edges_from(sorted(((a, b, {"w": (_cost(a, reqs) + _cost(b, reqs)) / 2})
                             for a, b in H.edges()),
                            key=lambda e: tuple(sorted((e[0].id or "", e[1].id or "")))))
    circ = [x for x in W if dom.is_circulation(x)]
    if not circ:
        return False
    W.add_edges_from(("DST", x, {"w": 0.0}) for x in circ)
    try:
        _w, path = nx.single_source_dijkstra(W, target, "DST", weight="w")
    except nx.NetworkXNoPath:
        return False
    middle = [x for x in path[1:-1] if not dom.is_circulation(x)]
    if not middle:
        return False            # adjacent already, and still unserved: a door the scorer refuses
    rooms = [x for x in middle if x.type in reqs]
    free = [(x, x.type) for x in middle if x not in rooms]
    for x, _t in free:
        x.type = "C"
    sfc._relink(lvl)
    done = []
    for k, x in enumerate(rooms):
        code = x.type
        if strip_serving(lvl, x, target, fit, assume=rooms[k + 1:]):
            done.append((x, code))
        else:
            for y, c in done:
                y.type, y.division, y.left, y.right = c, None, None, None
            for y, t in free:
                y.type = t
            sfc._relink(lvl)
            geometry.clear_cache()
            return False
    return True


def route_storey(lvl, li, reqs, fit) -> dict:
    stats = {"seeded": 0, "bridged": 0, "reached": 0, "unreached": 0}
    if not seed_circulation(lvl, reqs):
        return stats
    stats["seeded"] = 1
    stairs_join = bool(li) and graph.STAIRS_JOIN_STOREYS
    stats["bridged"] = sfc.bridge_indoors(lvl, reqs, stairs_join, fit=fit)
    blocked = set()
    while True:
        todo = [x for x in unserved(fit, lvl, reqs) if x.id not in blocked]
        if not todo:
            break
        x = todo[0]
        if reach(lvl, x, reqs, fit):
            stats["reached"] += 1
        else:
            blocked.add(x.id)
            stats["unreached"] += 1
    return stats


def settle(root, fallback: str = "C") -> int:
    """Every cell still unlabelled goes to its sibling room, or becomes
    ``fallback`` -- `C` after routing (counted: corridor the router did not
    lay), `O` for the erased-but-unrouted control, which must show what NO
    corridor looks like rather than quietly putting the search's back."""
    n = 0
    changed = True
    while changed:
        changed = False
        for lv in dom.levels(root):
            for lf in lv.leaves():
                if lf.type == FREE and _merge_into_sibling(lf):
                    changed = True
                    break
            if changed:
                break
        dom.link(root)
        geometry.clear_cache()
    for lv in dom.levels(root):
        for lf in lv.leaves():
            if lf.type == FREE:
                lf.type = fallback
                n += 1
    return n


def route(root, mode, reqs, fit) -> dict:
    erased = erase(root, mode)
    dom.link(root)
    geometry.clear_cache()
    tot = {"erased": erased}
    for li, lv in enumerate(dom.levels(root)):
        for k, v in route_storey(lv, li, reqs, fit).items():
            tot[k] = tot.get(k, 0) + v
    tot["left_as_C"] = settle(root)
    dom.link(root)
    geometry.clear_cache()
    return tot


def default_paths() -> list[Path]:
    res = REPO / "experiments" / "results"
    found = []
    for pat in ("*/final-*.dom", "*/winner*.dom", "*/drawings/*.dom"):
        found += sorted(res.glob(pat))
    found += sorted((REPO / "examples").glob("*/coldstart-4428262+orth-*.dom"))
    seen, out = set(), []
    for p in found:
        h = hashlib.sha1(p.read_bytes()).hexdigest()
        if h not in seen:
            seen.add(h)
            out.append(p)
    return out


def _tune(root, prog_dir, inner):
    if inner:
        innerloop.optimise(root, prog_dir, x0=innerloop.warm_x0(
            root, innerloop.ratio_map(root)), budget=inner)
        dom.link(root)
        geometry.clear_cache()


def self_test() -> int:
    """Controls. (1) Routing a design that is already connected and served,
    with nothing erased, changes nothing. (2) Erasing must actually break
    something, or the routed result says nothing. (3) No unlabelled cell
    survives a route."""
    d = REPO / "examples" / "health-centre"
    fit, reqs = Fitness(*load_config(d)), programme.load_programme_dir(str(d))
    path = before = root = None
    for p in sorted((REPO / "experiments/results").glob("halving-health*/**/*.dom")):
        r = dom.load(str(p))
        dom.link(r)
        sf = fit.score_with_fails(r)
        if len(dom.levels(r)) > 1 and conn_fails(sf[1]) == 0:
            path, before, root = p, sf, r
            break
    assert path is not None, "no intact multi-storey design to control on"
    print("control design:", path.relative_to(REPO))
    text = dom.dumps(root)
    for li, lv in enumerate(dom.levels(root)):
        st = route_storey(lv, li, reqs, fit)
        assert st["reached"] == 0 and st["bridged"] == 0, f"routed an intact storey {li}: {st}"
    assert dom.dumps(root) == text or fit.score_with_fails(root) == before, \
        "routing an intact design moved it"
    for mode in ("free", "merge"):
        r = dom.load(str(path))
        dom.link(r)
        erase(r, mode)
        settle(r, "O")                  # erased, not routed
        dom.link(r)
        geometry.clear_cache()
        broken = conn_fails(fit.score_with_fails(r)[1])
        assert broken > conn_fails(before[1]), f"{mode}: erasing broke nothing"
        r = dom.load(str(path))
        dom.link(r)
        route(r, mode, reqs, fit)
        assert not any(lf.type == FREE for lv in dom.levels(r) for lf in lv.leaves())
        print(f"self-test {mode}: erased-unrouted {broken} connection fails, "
              f"routed {conn_fails(fit.score_with_fails(r)[1])}, "
              f"original {conn_fails(before[1])}")
    print("self-test passed")
    return 0


def main() -> int:
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--mode", choices=("free", "merge"), default="merge")
    ap.add_argument("--inner", type=int, default=0)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    paths = [Path(p) for p in a.paths] or default_paths()
    cache = {}
    print("programme\tdesign\tmode\torig_fails\torig_conn\torig_circ\terased_fails\t"
          "erased_conn\trouted_fails\trouted_conn\trouted_circ\tscore_x\tstats")
    for path in paths:
        prog = next((v for k, v in KEYS.items() if k in str(path)), None)
        if prog is None:
            continue
        d = REPO / "examples" / prog
        if prog not in cache:
            cache[prog] = (Fitness(*load_config(d)), programme.load_programme_dir(str(d)))
        fit, reqs = cache[prog]
        orig = dom.load(str(path))
        dom.link(orig)
        _tune(orig, str(d), a.inner)
        s0, f0 = fit.score_with_fails(orig)
        er = copy.deepcopy(orig)
        dom.link(er)
        erase(er, a.mode)
        settle(er, "O")
        dom.link(er)
        geometry.clear_cache()
        _se, fe = fit.score_with_fails(er)
        rt = copy.deepcopy(orig)
        dom.link(rt)
        stats = route(rt, a.mode, reqs, fit)
        _tune(rt, str(d), a.inner)
        s1, f1 = fit.score_with_fails(rt)
        rel = str(path.resolve().relative_to(REPO))
        print(f"{prog}\t{rel}\t{a.mode}\t{len(f0)}\t{conn_fails(f0)}\t{circ_area(orig):.0f}\t"
              f"{len(fe)}\t{conn_fails(fe)}\t{len(f1)}\t{conn_fails(f1)}\t{circ_area(rt):.0f}\t"
              f"{s1 / s0:.3g}\t{stats}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
