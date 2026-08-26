"""3D bubble-diagram relaxation of programme adjacency (homemaker-py-mi7).

Prototype for a fitness signal that looks past the binary "is X adjacent to
Y" checks in ``graph.py`` toward overall spatial arrangement: build the
programme's required-space adjacency as a graph, relax it in 3D with a
spring/repulsion physics simulation (a "bubble diagram"), then measure how
well an actual Dom layout's real room-to-room distances correlate with a
relaxed target's distances.

Relaxation is non-convex and multi-modal by nature — different random starts
settle into different but equally-valid arrangements (e.g. which side of the
hub a wing ends up on). ``generate_targets`` returns several distinct local
minima; callers should score a candidate layout against each and take the
best match rather than expect one canonical target.

KNOWN SIMPLIFICATIONS (first prototype, see homemaker-py-mi7):
  - Generic circulation/outside/stair codes (c/o/s) collapse to one shared
    hub node per code across the whole graph, not per storey. This matches
    how sparse most patterns.config adjacency is (almost everything just
    says "adjacent to c") but means the target is closer to a hub-and-spoke
    layout than a fully free embedding.
  - Anonymous multi-count codes (``count: N``) are matched to actual leaves
    by a fixed centroid-order rule (see ``matched_leaves``), not by the
    optimal assignment. Good enough to sanity-check correlation; a real
    fitness term would need a proper assignment (Hungarian / brute-force
    for small N, mirroring the ``CLASS_CAP`` pattern in programme.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx
import numpy as np

from . import dom, geometry, graph as graph_mod
from .dom import Node, levels
from .programme import SpaceReq

STOREY_HEIGHT = 3.0  # metres; only used to seed/soften the z axis
DOOR_WIDTH = graph_mod.DOOR_WIDTH


# --------------------------------------------------------------------------- #
# Requirement graph
# --------------------------------------------------------------------------- #

def _radius(area: float) -> float:
    """Bubble radius for a target floor area (equal-area circle)."""
    return math.sqrt(max(area, 1.0) / math.pi)


def requirement_graph(reqs: dict[str, SpaceReq]) -> nx.Graph:
    """Expand programme codes into per-instance nodes plus generic hubs.

    One node per required room instance (``code`` if ``count == 1`` else
    ``code#i``), node attrs ``area``/``level``/``generic``/``code``. Generic
    c/o/s adjacency targets collapse to one shared hub node per code
    (``__c__``, ``__o__``, ``__s__``). Edges to a multi-count non-generic
    code fan out to all its instances at reduced weight, since satisfying
    adjacency only requires ONE matching neighbour, not all of them.
    """
    G = nx.Graph()
    hubs: dict[str, str] = {}

    def hub(low: str) -> str:
        if low not in hubs:
            hub_id = f"__{low}__"
            hubs[low] = hub_id
            G.add_node(hub_id, area=4.0, level=None, generic=True, code=low)
        return hubs[low]

    instances: dict[str, list[str]] = {}
    for code, req in reqs.items():
        if dom.is_generic(code):
            continue
        ids = []
        for i in range(req.count):
            node_id = code if req.count == 1 else f"{code}#{i + 1}"
            G.add_node(node_id, area=req.size, level=req.level, generic=False, code=code)
            ids.append(node_id)
        instances[code] = ids

    for code, req in reqs.items():
        if dom.is_generic(code) or code not in instances:
            continue
        for node_id in instances[code]:
            for adj_code in req.adjacency:
                low = adj_code.lower()
                if low.upper() in dom.GENERIC_TYPES:
                    G.add_edge(node_id, hub(low), weight=1.0)
                elif adj_code in instances:
                    targets = instances[adj_code]
                    w = 1.0 / len(targets)
                    for t in targets:
                        if not G.has_edge(node_id, t):
                            G.add_edge(node_id, t, weight=w)
    return G


# --------------------------------------------------------------------------- #
# Relaxation
# --------------------------------------------------------------------------- #

@dataclass
class BubbleLayout:
    positions: dict[str, np.ndarray]
    radius: dict[str, float]
    level: dict[str, float | None]
    energy: float


def _relax_once(
    G: nx.Graph, rng: np.random.Generator, iterations: int, storey_height: float,
) -> BubbleLayout:
    nodes = list(G.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)
    radius = {v: _radius(d["area"]) for v, d in G.nodes(data=True)}
    level = {v: d.get("level") for v, d in G.nodes(data=True)}

    pos = rng.normal(scale=5.0, size=(n, 3))
    for v, d in G.nodes(data=True):
        if d.get("level") is not None:
            pos[idx[v], 2] = d["level"] * storey_height

    edges = [(idx[u], idx[v], d["weight"]) for u, v, d in G.edges(data=True)]
    leveled = [idx[v] for v, d in G.nodes(data=True) if d.get("level") is not None]
    target_z = np.zeros(n)
    for v, d in G.nodes(data=True):
        if d.get("level") is not None:
            target_z[idx[v]] = d["level"] * storey_height
    r = np.array([radius[v] for v in nodes])

    lr = 0.2
    max_disp = 0.5 * float(np.mean(r))  # clamp step size — repulsion sums grow with n
    for step in range(iterations):
        force = np.zeros_like(pos)

        for ui, vi, w in edges:
            d = pos[vi] - pos[ui]
            dist = np.linalg.norm(d) + 1e-9
            ideal = r[ui] + r[vi]
            f = w * (dist - ideal) * d / dist
            force[ui] += f
            force[vi] -= f

        # overlap-only repulsion, O(n^2) — fine at programme scale
        diff = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(diff, axis=2) + 1e-9
        min_sep = r[:, None] + r[None, :]
        overlap = np.maximum(0.0, min_sep - dist)
        np.fill_diagonal(overlap, 0.0)
        rep = (overlap / dist)[:, :, None] * diff
        force += rep.sum(axis=1)

        if leveled:
            force[leveled, 2] += (target_z[leveled] - pos[leveled, 2]) * 0.5

        disp = lr * force / (1.0 + 0.01 * step)
        disp_norm = np.linalg.norm(disp, axis=1, keepdims=True)
        scale = np.minimum(1.0, max_disp / (disp_norm + 1e-12))
        pos += disp * scale

    total = 0.0
    for ui, vi, w in edges:
        dist = np.linalg.norm(pos[vi] - pos[ui])
        total += w * (dist - (r[ui] + r[vi])) ** 2

    return BubbleLayout(
        positions={v: pos[idx[v]] for v in nodes},
        radius=radius,
        level=level,
        energy=total,
    )


def _layout_signature(layout: BubbleLayout, nodes: list[str]) -> np.ndarray:
    """Flattened, translation-free pairwise-distance vector for dedup."""
    pts = np.array([layout.positions[n] for n in nodes])
    d = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=2)
    iu = np.triu_indices(len(nodes), k=1)
    return d[iu]


def generate_targets(
    reqs: dict[str, SpaceReq],
    n_restarts: int = 8,
    iterations: int = 400,
    storey_height: float = STOREY_HEIGHT,
    seed: int = 0,
    keep: int = 4,
    dedup_corr: float = 0.98,
) -> list[BubbleLayout]:
    """Relax the requirement graph from ``n_restarts`` random starts, return up
    to ``keep`` distinct low-energy layouts (Pearson correlation of pairwise
    distance vectors >= ``dedup_corr`` is treated as a duplicate solution)."""
    G = requirement_graph(reqs)
    nodes = list(G.nodes())
    rng = np.random.default_rng(seed)

    candidates = []
    for _ in range(n_restarts):
        layout = _relax_once(G, rng, iterations, storey_height)
        candidates.append(layout)
    candidates.sort(key=lambda layout: layout.energy)

    kept: list[BubbleLayout] = []
    kept_sigs: list[np.ndarray] = []
    for c in candidates:
        sig = _layout_signature(c, nodes)
        is_dup = any(
            np.corrcoef(sig, ks)[0, 1] >= dedup_corr for ks in kept_sigs if len(ks) > 1
        )
        if not is_dup:
            kept.append(c)
            kept_sigs.append(sig)
        if len(kept) >= keep:
            break
    return kept


# --------------------------------------------------------------------------- #
# Matching an actual Dom layout to requirement-graph node ids
# --------------------------------------------------------------------------- #

def matched_leaves(root: Node, reqs: dict[str, SpaceReq]) -> dict[str, Node]:
    """Map requirement-graph instance ids to actual leaves.

    Anonymous multi-count codes are matched by fixed centroid order (x then
    y) — a known simplification, see module docstring. Codes with fewer
    actual leaves than required are matched as far as they go; excess actual
    leaves of a code are left unmatched.
    """
    by_code: dict[str, list[Node]] = {}
    for lvl in levels(root):
        for leaf in lvl.leaves():
            if not leaf.type or dom.is_generic(leaf.type):
                continue
            by_code.setdefault(leaf.type, []).append(leaf)

    for leaves in by_code.values():
        leaves.sort(key=lambda lf: tuple(geometry.centroid(lf)))

    result: dict[str, Node] = {}
    for code, req in reqs.items():
        if dom.is_generic(code):
            continue
        leaves = by_code.get(code, [])
        for i in range(min(req.count, len(leaves))):
            node_id = code if req.count == 1 else f"{code}#{i + 1}"
            result[node_id] = leaves[i]
    return result


def actual_full_graph(root: Node, door_width: float = DOOR_WIDTH) -> nx.Graph:
    """Union of each storey's leaf-adjacency graph, with synthetic edges
    linking every circulation leaf on adjacent storeys (approximates a
    stair/shared-core connection so cross-floor distances are defined)."""
    lvls = levels(root)
    per_level = [geometry.leaf_graph(lvl, door_width) for lvl in lvls]

    G = nx.Graph()
    for g in per_level:
        G.add_nodes_from(g.nodes())
        G.add_edges_from(g.edges(data=True))

    for i in range(len(per_level) - 1):
        below = [v for v in per_level[i].nodes() if dom.is_circulation(v)]
        above = [v for v in per_level[i + 1].nodes() if dom.is_circulation(v)]
        for a in below:
            for b in above:
                if not G.has_edge(a, b):
                    G.add_edge(a, b, weight=geometry._dist(geometry.centroid(a), geometry.centroid(b)) or 1.0)
    return G


# --------------------------------------------------------------------------- #
# Similarity scoring
# --------------------------------------------------------------------------- #

def similarity(
    root: Node, reqs: dict[str, SpaceReq], target: BubbleLayout,
) -> float | None:
    """Weighted Pearson correlation between actual weighted shortest-path
    distances and the target bubble's Euclidean distances, over pairs of
    matched non-generic room instances. None if fewer than 3 matched pairs.

    Pairs are weighted by ``1 / hop_distance`` in the requirement graph — most
    programmes only declare a handful of direct room-to-room adjacencies
    (e.g. kitchen-dining), with everything else attached only via a shared
    generic circulation hub. Two rooms that both merely want "near
    circulation" carry much weaker positional evidence than a pair with a
    declared adjacency, so unweighted correlation is dominated by noise from
    the many hub-mediated pairs. Raw (not rank) distances are compared since
    hop-weighting requires an ordinary weighted covariance; both distances are
    already in comparable metre-scale units (bubble radius = sqrt(area/pi)).
    """
    matched = matched_leaves(root, reqs)
    ids = [i for i in matched if i in target.positions]
    if len(ids) < 3:
        return None

    G = actual_full_graph(root)
    req_graph = requirement_graph(reqs)
    hop = dict(nx.all_pairs_shortest_path_length(req_graph))
    leaf_of = matched

    actual_d = []
    target_d = []
    weights = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = leaf_of[ids[i]], leaf_of[ids[j]]
            try:
                ad = nx.shortest_path_length(G, a, b, weight="weight")
            except nx.NetworkXNoPath:
                continue
            td = float(np.linalg.norm(target.positions[ids[i]] - target.positions[ids[j]]))
            h = hop.get(ids[i], {}).get(ids[j])
            if h is None or h == 0:
                continue
            actual_d.append(ad)
            target_d.append(td)
            weights.append(1.0 / h)

    if len(actual_d) < 3:
        return None

    return _weighted_corr(np.array(actual_d), np.array(target_d), np.array(weights))


def _weighted_corr(a: np.ndarray, b: np.ndarray, w: np.ndarray) -> float:
    wsum = w.sum()
    mean_a = (w * a).sum() / wsum
    mean_b = (w * b).sum() / wsum
    da, db = a - mean_a, b - mean_b
    cov = (w * da * db).sum() / wsum
    var_a = (w * da * da).sum() / wsum
    var_b = (w * db * db).sum() / wsum
    denom = math.sqrt(var_a * var_b)
    return float(cov / denom) if denom > 0 else 0.0


def best_similarity(
    root: Node, reqs: dict[str, SpaceReq], targets: list[BubbleLayout],
) -> float | None:
    """Best (max) similarity across a set of alternative relaxed targets."""
    scores = [s for t in targets if (s := similarity(root, reqs, t)) is not None]
    return max(scores) if scores else None


# --------------------------------------------------------------------------- #
# Topological (no-embedding) alternative
# --------------------------------------------------------------------------- #

def topological_similarity(
    root: Node, reqs: dict[str, SpaceReq],
) -> float | None:
    """Hop-weighted correlation between requirement-graph hop distance and
    actual-building hop distance — no spatial embedding/relaxation at all.

    Where ``similarity`` relaxes the requirement graph into a 3D bubble
    diagram and compares Euclidean distances, this compares plain graph
    topology on both sides: shortest-path hop count in ``requirement_graph``
    (through the real, possibly-multi-cell circulation network on the actual
    side, not a single collapsed hub) versus shortest-path hop count in
    ``actual_full_graph``. Cheaper (no physics simulation, no multi-restart
    dedup) and avoids the single-point-hub abstraction's mismatch with real
    layouts, which spread circulation across several physical cells.
    """
    matched = matched_leaves(root, reqs)
    req_graph = requirement_graph(reqs)
    ids = [i for i in matched if i in req_graph.nodes]
    if len(ids) < 3:
        return None

    req_hop = dict(nx.all_pairs_shortest_path_length(req_graph))
    actual_graph = actual_full_graph(root)
    actual_hop = dict(nx.all_pairs_shortest_path_length(actual_graph))

    req_d, actual_d, weights = [], [], []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            h = req_hop.get(a, {}).get(b)
            if h is None or h == 0:
                continue
            leaf_a, leaf_b = matched[a], matched[b]
            ah = actual_hop.get(leaf_a, {}).get(leaf_b)
            if ah is None:
                continue
            req_d.append(h)
            actual_d.append(ah)
            weights.append(1.0 / h)

    if len(req_d) < 3:
        return None

    return _weighted_corr(np.array(actual_d), np.array(req_d), np.array(weights))
