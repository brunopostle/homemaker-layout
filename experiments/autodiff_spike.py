"""Spike (homemaker-py-2ax): torch-autodiff ratio optimisation vs nm_search.

DESIGN.md 4.5's ``0.5^n`` failure-count cliff and the discrete adjacency/access/
merge machinery around it mean the FULL fitness is not literally differentiable
end-to-end (staircase fit truncates to integers, adjacency existence is a
door_width threshold on wall overlap, access is a categorical neighbour-type
test). So this does not attempt a faithful whole-pipeline port. Instead it
builds a genuinely differentiable LOCAL proxy for a frozen topology:

  * Geometry (``coordinate``/``area``/``edge_length``/``angle``/``aspect``,
    geometry.py) is ordinary arithmetic on the free cut ratios and is ported
    to torch exactly.
  * All *structural* facts that do not vary continuously with the ratios for a
    frozen topology -- which leaves are adjacent (door_width-thresholded wall
    overlap), boundary ids, leaf types/params, which fails are structural
    (missing/adjacency/level/vertical/access/staircase/storey/edge-too-long) --
    are snapshotted ONCE from a real ``fitness.py`` evaluation at the start
    ratios and held frozen.
  * The 5 per-leaf quality factors that vary continuously with geometry
    (perpendicular, proportion, size, width, crinkliness) are recomputed from
    torch geometry every step, and their FAIL_THRESHOLD tests are relaxed to a
    steep sigmoid so the ``0.5^n`` cliff itself is smoothly differentiable --
    this directly probes the risk flagged in the issue.
  * ``building_factor`` (programme area-ratio Gaussians, staircase volume,
    storey/public-access checks) is frozen as a single calibration constant --
    it is a second-order function of the ratios (areas shift slightly) that
    was out of scope to port faithfully for a spike.

The comparison: for each frozen topology, run ``innerloop.nm_search`` (real
fitness, one oracle call per eval) and this torch proxy (Adam over the proxy,
re-evaluated against real fitness periodically, with periodic structural
resnapshots) for a matched evaluation/gradient-step budget, and report the
resulting TRUE fitness and wall-clock time for each.
"""

from __future__ import annotations

import copy
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homemaker_layout import dom as dom_mod  # noqa: E402
from homemaker_layout import fitness as fit_mod  # noqa: E402
from homemaker_layout import geometry  # noqa: E402
from homemaker_layout import graph as graph_mod  # noqa: E402
from homemaker_layout import innerloop as il  # noqa: E402
from homemaker_layout import solver  # noqa: E402

torch.set_default_dtype(torch.float64)

_EPS = il._EPS
FAIL_THRESHOLD = fit_mod.FAIL_THRESHOLD
_E = fit_mod._E
_EXTERNAL = geometry._EXTERNAL
_CONTINUOUS_SUFFIXES = ("perpendicular", "proportion", "size", "width", "crinkliness")
_STEEPNESS = 60.0  # sigmoid steepness for the soft fail-threshold relaxation


# --------------------------------------------------------------------------- #
# torch mirrors of geometry.py -- same recursion, tensors instead of floats.
# --------------------------------------------------------------------------- #

def _interp_t(a, b, t):
    return a * (1 - t) + b * t


def _dist_t(a, b):
    return torch.sqrt(torch.clamp((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2, min=1e-24))


def _triangle_area_t(a, b, c):
    da, db, dc = _dist_t(b, c), _dist_t(a, c), _dist_t(a, b)
    s = (da + db + dc) / 2
    return torch.sqrt(torch.clamp(s * (s - da) * (s - db) * (s - dc), min=0.0))


class TorchGeom:
    """Differentiable ``coordinate``/``coord_a``/``coord_b`` recursion.

    ``xmap`` holds one torch scalar per FREE branch (``innerloop.free_with_keys``
    order); every other divided node's division is never read by the real
    recursion either (it delegates to ``below``), so nothing else is needed.
    """

    def __init__(self, xmap: dict[int, torch.Tensor]):
        self.xmap = xmap
        self._cache: dict = {}

    def coordinate(self, n, idx: int):
        key = (id(n), idx)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        if n.below is not None:
            result = self.coordinate(n.below, idx)
        else:
            rid = (idx + n.rotation) % 4
            if n.parent is None:
                pt = n.node[rid]
                result = torch.tensor([float(pt[0]), float(pt[1])])
            else:
                p = n.parent
                if n.position == "l":
                    result = {0: self.coordinate(p, 0), 1: self.coord_a(p),
                              2: self.coord_b(p), 3: self.coordinate(p, 3)}[rid]
                else:
                    result = {0: self.coord_a(p), 1: self.coordinate(p, 1),
                              2: self.coordinate(p, 2), 3: self.coord_b(p)}[rid]
        self._cache[key] = result
        return result

    def coord_a(self, n):
        key = (id(n), "a")
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        if n.below is not None and n.below.divided:
            result = self.coord_a(n.below)
        else:
            t = self.xmap[id(n)]
            result = _interp_t(self.coordinate(n, 0), self.coordinate(n, 1), t)
        self._cache[key] = result
        return result

    def coord_b(self, n):
        key = (id(n), "b")
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        if n.below is not None and n.below.divided:
            result = self.coord_b(n.below)
        else:
            t = self.xmap[id(n)]
            result = _interp_t(self.coordinate(n, 3), self.coordinate(n, 2), t)
        self._cache[key] = result
        return result

    def area(self, n):
        c = [self.coordinate(n, i) for i in range(4)]
        return _triangle_area_t(c[0], c[1], c[2]) + _triangle_area_t(c[0], c[2], c[3])

    def edge_length(self, n, idx: int):
        return _dist_t(self.coordinate(n, idx), self.coordinate(n, (idx + 1) % 4))

    def angle(self, n, idx: int):
        a = self.edge_length(n, idx)
        b = self.edge_length(n, (idx + 3) % 4)
        c = _dist_t(self.coordinate(n, (idx + 1) % 4), self.coordinate(n, (idx + 3) % 4))
        cos_t = torch.clamp((a * a + b * b - c * c) / (2 * a * b), -1.0 + 1e-9, 1.0 - 1e-9)
        return torch.acos(cos_t)

    def aspect(self, n):
        asp = (self.edge_length(n, 0) + self.edge_length(n, 2)) / (
            self.edge_length(n, 1) + self.edge_length(n, 3))
        return torch.where(asp < 1, 1.0 / asp, asp)

    def length_narrowest(self, n):
        return torch.min(torch.stack([self.edge_length(n, i) for i in range(4)]))


def gaussian_t(x, a, b, c):
    return a * torch.exp(-((x - b) ** 2) / (2 * c * c))


def clipped_gaussian_t(x, target: float, sigma: float, good_side: str):
    gauss = gaussian_t(x, 1.0, target, sigma)
    flat = x > target if good_side == "above" else x < target
    return torch.where(flat, torch.ones_like(gauss), gauss)


def soft_fail(value: torch.Tensor) -> torch.Tensor:
    """Smooth relaxation of ``value < FAIL_THRESHOLD``: ~1 well below the
    threshold, ~0 well above, matching sign/shape but differentiable everywhere
    -- this is the part of the spike that stands in for the real 0.5^n cliff."""
    return torch.sigmoid(_STEEPNESS * (FAIL_THRESHOLD - value))


# --------------------------------------------------------------------------- #
# Frozen-structure snapshot + differentiable proxy objective
# --------------------------------------------------------------------------- #

class TorchTopology:
    def __init__(self, root, programme_dir, conf_overrides: dict | None = None):
        self.programme_dir = programme_dir
        conf, cost = fit_mod.load_config(programme_dir, overrides=conf_overrides)
        self.fit = fit_mod.Fitness(conf, cost)
        self.root = root
        self.free = solver.free_branches(root)
        self._snapshot()

    # -- structural snapshot (all plain python/numpy, no torch) -- #
    def _snapshot(self) -> None:
        geometry.clear_cache()
        root = self.root
        self.fit.preprocess_building(root)
        door_width = self.fit.conf("door_width") or 1.2

        levels = dom_mod.levels(root)
        self.levels = levels
        graph_base = graph_mod.build_graphs(root, door_width)
        self.graph_base = graph_base

        # true full evaluation (fresh deep copy) -- ground truth at this x, and
        # the source of the frozen structural fail count.
        true_score, true_fails = self.fit.score_with_fails(copy.deepcopy(root))
        self.x0_true_score = true_score
        self.x0_true_fails = true_fails
        n_continuous = sum(
            1 for f in true_fails if f.rsplit(" ", 1)[-1] in _CONTINUOUS_SUFFIXES
        )
        self.n_fails_frozen = len(true_fails) - n_continuous

        self.plot_cost_frozen = self.fit.plot_cost(levels[0] if levels[0].below is None else
                                                     _lowest(levels[0]))

        self.leaf_facts: list[dict] = []  # one entry per usable leaf
        self.leaf_cost_facts: list[dict] = []  # one entry per ALL leaves (usable or not)
        self.edge_facts: list[dict] = []  # frozen adjacency edges (all levels)
        self.outside_edge_facts: list[dict] = []  # frozen per-leaf external edges

        for li, lvl in enumerate(levels):
            groups = geometry.boundary_groups(lvl)
            G = graph_base[li]
            leaves = lvl.leaves()

            for leaf in leaves:
                self.leaf_cost_facts.append(self._leaf_cost_fact(leaf))
                if not dom_mod.is_usable(leaf):
                    continue
                self.leaf_facts.append(self._leaf_quality_facts(leaf, li, G, groups))
                self.outside_edge_facts.append(self._outside_edge_fact(leaf))

            for a, b in G.edges():
                edge_a, edge_b = _find_edge_indices(groups, a, b)
                if edge_a is None:
                    continue  # defensive; should not happen for a real G edge
                a_out, b_out = dom_mod.is_outside(a), dom_mod.is_outside(b)
                if a_out and b_out:
                    rate = 0.0
                else:
                    rate = (self.fit.cost("interior_wall") if not a_out and not b_out
                            else self.fit.cost("exterior_wall"))
                self.edge_facts.append(dict(
                    a=a, edge_a=edge_a, b=b, edge_b=edge_b,
                    rate=rate, height=fit_mod._height(a),
                ))

        # building_factor calibration: fold the un-ported (mostly x-insensitive
        # for a frozen topology) building-level factor into one constant so the
        # proxy's absolute scale is comparable to the real score.
        proxy0 = self._raw_value_cost(self.free)
        raw_score0 = (proxy0["value"] / proxy0["cost"]) if proxy0["cost"] else 0.0
        self.calibration = (true_score / raw_score0) if raw_score0 else 1.0

    def _leaf_cost_fact(self, leaf) -> dict:
        if dom_mod.is_outside(leaf):
            covered, supported = dom_mod.is_covered(leaf), dom_mod.is_supported(leaf)
            if covered and supported:
                rate = self.fit.cost("outside_covered_supported")
            elif covered:
                rate = self.fit.cost("outside_covered")
            elif supported:
                rate = self.fit.cost("outside_supported")
            else:
                rate = self.fit.cost("outside")
        else:
            rate = self.fit.cost("inside")
        return dict(leaf=leaf, rate=rate)

    def _outside_edge_fact(self, leaf) -> dict:
        rate = self.fit.cost("boundary") if dom_mod.is_outside(leaf) else self.fit.cost("boundary_wall")
        edges = [e for e in range(4) if geometry.boundary_id(leaf, e) in _EXTERNAL]
        return dict(leaf=leaf, rate=rate, edges=edges)

    def _leaf_quality_facts(self, leaf, level_id: int, G, groups) -> dict:
        t0 = fit_mod._t0(leaf)
        is_out = dom_mod.is_outside(leaf)

        # perpendicular: sigma scalar, target 1.570796, product over 4 corners
        perp_sigma = self.fit.conf("perpendicular_outside" if is_out else "perpendicular_inside")

        # proportion
        if t0 in ("o", "s"):
            prop_params = self.fit.conf("proportion_outside")
        elif t0 == "c":
            prop_params = self.fit.conf("proportion_circulation")
        else:
            prop_params = self.fit.get_space_params(leaf.type, "proportion")

        # size: 'constant_one' for outside/sahn; symmetric gaussian otherwise
        size_const = t0 in ("o", "s")
        if not size_const:
            size_params = (self.fit.conf("size_circulation") if t0 == "c"
                           else self.fit.get_space_params(leaf.type, "size"))
        else:
            size_params = None

        # width: 'constant_one' special case, else clipped-above gaussian
        width_const = (
            t0 in ("o", "s") and not dom_mod.is_covered(leaf)
            and not dom_mod.is_supported(leaf) and dom_mod.level_of(leaf)
        )
        if not width_const:
            if t0 in ("o", "s"):
                width_params = self.fit.conf("width_outside")
            elif t0 == "c":
                width_params = self.fit.conf("width_circulation")
            else:
                width_params = self.fit.get_space_params(leaf.type, "width")
        else:
            width_params = None

        # crinkliness / uncrinkliness
        crink_const = is_out and not dom_mod.is_covered(leaf)
        if not crink_const:
            key = "uncrinkliness_circulation" if dom_mod.is_circulation(leaf) else "uncrinkliness"
            crink_params = self.fit.conf(key)
            # frozen neighbour/edge-index facts for area_outside
            nb_edges = []
            for nb in G.neighbors(leaf):
                if not dom_mod.is_outside(nb) or dom_mod.is_covered(nb):
                    continue
                if geometry.boundary_pair_overlap(groups_contributors(groups), leaf, nb) <= 0:
                    pass
                ea, eb = _find_edge_indices(groups, leaf, nb)
                if ea is not None:
                    nb_edges.append((nb, ea, eb))
            own_edges = []
            perimeter = fit_mod._perimeter(leaf)
            for e in range(4):
                bid = geometry.boundary_id(leaf, e)
                if bid not in _EXTERNAL:
                    continue
                ptype = (perimeter.get(bid) or "").lower()
                if ptype in ("private", "fortified"):
                    continue
                own_edges.append(e)
        else:
            crink_params = None
            nb_edges = []
            own_edges = []

        # access: frozen boolean (adjacency SET + types are both frozen)
        access_ok = len(self.fit.access(leaf, G)) > 0 or (
            not dom_mod.level_of(leaf) and is_out
        )
        access_factor = 1.0 if access_ok else 0.01

        rate = self.fit.value_rate(leaf)
        height = fit_mod._height(leaf)

        return dict(
            leaf=leaf, level=level_id, is_out=is_out,
            perp_sigma=perp_sigma,
            prop_target=prop_params[0], prop_sigma=prop_params[1],
            size_const=size_const, size_target=(size_params[0] if size_params else None),
            size_sigma=(size_params[1] if size_params else None),
            width_const=width_const, width_target=(width_params[0] if width_params else None),
            width_sigma=(width_params[1] if width_params else None),
            crink_const=crink_const,
            crink_target=(crink_params[0] if crink_params else None),
            crink_sigma=(crink_params[1] if crink_params else None),
            nb_edges=nb_edges, own_edges=own_edges, height=height,
            access_factor=access_factor, rate=rate,
        )

    # -- differentiable proxy -- #
    def _raw_value_cost(self, free_nodes, x: torch.Tensor | None = None) -> dict:
        """value/cost BEFORE calibration, at ``x`` (defaults to the frozen
        ratios currently stored on the tree, i.e. x0)."""
        if x is None:
            x = torch.tensor([float(b.division[0]) for b in free_nodes])
        xmap = {id(b): x[j] for j, b in enumerate(free_nodes)}
        geo = TorchGeom(xmap)

        value = torch.zeros(())
        soft_n_fails = torch.zeros(())
        for lf in self.leaf_facts:
            leaf = lf["leaf"]
            area = geo.area(leaf)

            perp = torch.ones(())
            for i in range(4):
                perp = perp * gaussian_t(geo.angle(leaf, i), 1.0, 1.570796, lf["perp_sigma"])
            soft_n_fails = soft_n_fails + soft_fail(perp)

            aspect = geo.aspect(leaf)
            prop = clipped_gaussian_t(aspect, lf["prop_target"], lf["prop_sigma"], "below")
            soft_n_fails = soft_n_fails + soft_fail(prop)

            if lf["size_const"]:
                size = torch.ones(())
            else:
                size = gaussian_t(area, 1.0, lf["size_target"], lf["size_sigma"])
                soft_n_fails = soft_n_fails + soft_fail(size)

            if lf["width_const"]:
                width = torch.ones(())
            else:
                w = geo.length_narrowest(leaf)
                width = clipped_gaussian_t(w, lf["width_target"], lf["width_sigma"], "above")
                soft_n_fails = soft_n_fails + soft_fail(width)

            if lf["crink_const"]:
                crink_q = torch.ones(())
            else:
                outside_len = torch.zeros(())
                for nb, ea, eb in lf["nb_edges"]:
                    outside_len = outside_len + _edge_overlap_t(geo, lf["leaf"], ea, nb, eb)
                for e in lf["own_edges"]:
                    outside_len = outside_len + geo.edge_length(lf["leaf"], e)
                area_outside = outside_len * lf["height"]
                crink = area_outside / torch.clamp(area, min=1e-9)
                inv_crink = torch.where(crink > 1e-9, 1.0 / torch.clamp(crink, min=1e-9),
                                         torch.zeros(()))
                crink_q = torch.where(
                    crink > 1e-9,
                    gaussian_t(inv_crink, 1.0, lf["crink_target"], lf["crink_sigma"]),
                    torch.zeros(()),
                )
                soft_n_fails = soft_n_fails + soft_fail(crink_q)

            quality = perp * prop * size * width * crink_q * lf["access_factor"]
            value = value + quality * lf["rate"] * area

        cost = torch.tensor(float(self.plot_cost_frozen))
        for cf in self.leaf_cost_facts:
            cost = cost + cf["rate"] * geo.area(cf["leaf"])
        for ef in self.edge_facts:
            if ef["rate"] == 0.0:
                continue
            width = _edge_overlap_t(geo, ef["a"], ef["edge_a"], ef["b"], ef["edge_b"])
            cost = cost + ef["rate"] * width * ef["height"]
        for of in self.outside_edge_facts:
            length = torch.zeros(())
            for e in of["edges"]:
                length = length + geo.edge_length(of["leaf"], e)
            cost = cost + of["rate"] * length * fit_mod._height(of["leaf"])

        penalty = torch.exp((self.n_fails_frozen + soft_n_fails) * math.log(0.5))
        return dict(value=value * penalty, cost=cost, soft_n_fails=soft_n_fails)

    def proxy_score(self, x: torch.Tensor) -> torch.Tensor:
        rc = self._raw_value_cost(self.free, x)
        score = rc["value"] / torch.clamp(rc["cost"], min=1e-9)
        return score * self.calibration

    def true_score(self, x: np.ndarray) -> tuple[float, int]:
        for j, b in enumerate(self.free):
            b.division = [float(x[j]), float(x[j])]
        s, fails = self.fit.score_with_fails(copy.deepcopy(self.root))
        return s, len(fails)


def groups_contributors(groups):
    out = []
    for v in groups.values():
        out.extend(v)
    return out


def _find_edge_indices(groups, a, b):
    best = None
    best_w = -1.0
    for contributors in groups.values():
        ea = eb = None
        for leaf, edge in contributors:
            if leaf is a:
                ea = edge
            if leaf is b:
                eb = edge
        if ea is not None and eb is not None:
            w = geometry._edge_overlap(a, ea, b, eb)
            if w > best_w:
                best, best_w = (ea, eb), w
    return best if best is not None else (None, None)


def _edge_overlap_t(geo: TorchGeom, a, edge_a: int, b, edge_b: int):
    p_a0, p_a1 = geo.coordinate(a, edge_a), geo.coordinate(a, (edge_a + 1) % 4)
    p_b0, p_b1 = geo.coordinate(b, edge_b), geo.coordinate(b, (edge_b + 1) % 4)
    len_a, len_b = _dist_t(p_a0, p_a1), _dist_t(p_b0, p_b1)
    dists = torch.stack([_dist_t(p_a0, p_b0), _dist_t(p_a0, p_b1),
                          _dist_t(p_a1, p_b0), _dist_t(p_a1, p_b1)])
    max_dist = torch.max(dists)
    return torch.where(
        max_dist <= len_b, len_a,
        torch.where(max_dist <= len_a, len_b,
                    torch.clamp(len_a + len_b - max_dist, min=0.0)),
    )


def _lowest(n):
    while n.below is not None:
        n = n.below
    return n


# --------------------------------------------------------------------------- #
# Optimiser drivers
# --------------------------------------------------------------------------- #

def run_nm(root, programme_dir, x0: np.ndarray, budget: int) -> dict:
    root_c = copy.deepcopy(root)
    for j, b in enumerate(solver.free_branches(root_c)):
        b.division = [float(x0[j]), float(x0[j])]
    t0 = time.perf_counter()
    result = il.optimise(root_c, programme_dir, x0=x0.copy(), budget=budget, method="nm")
    dt = time.perf_counter() - t0
    return dict(fitness=result.fitness, n_fails=result.n_fails, evals=result.n_evals, seconds=dt)


def run_torch(root, programme_dir, x0: np.ndarray, steps: int, resnapshot_every: int,
              lr: float = 0.05) -> dict:
    root_c = copy.deepcopy(root)
    for j, b in enumerate(solver.free_branches(root_c)):
        b.division = [float(x0[j]), float(x0[j])]

    t0 = time.perf_counter()
    topo = TorchTopology(root_c, programme_dir)
    x_raw = torch.tensor(x0.copy(), requires_grad=True)
    opt = torch.optim.Adam([x_raw], lr=lr, maximize=True)

    best_true, best_fails = topo.x0_true_score, len(topo.x0_true_fails)
    best_x = x0.copy()
    n_evals = 1  # the initial snapshot's true eval

    for step in range(steps):
        opt.zero_grad()
        score = topo.proxy_score(x_raw)
        (-score).backward()
        opt.step()
        with torch.no_grad():
            x_raw.clamp_(_EPS, 1 - _EPS)

        if resnapshot_every and (step + 1) % resnapshot_every == 0:
            x_np = x_raw.detach().numpy()
            true_s, n_fails = topo.true_score(x_np)
            n_evals += 1
            if true_s > best_true:
                best_true, best_fails, best_x = true_s, n_fails, x_np.copy()
            topo = TorchTopology(root_c, programme_dir)  # re-snapshot at current x
            x_raw = torch.tensor(x_np, requires_grad=True)
            opt = torch.optim.Adam([x_raw], lr=lr, maximize=True)

    x_np = x_raw.detach().numpy()
    true_s, n_fails = topo.true_score(x_np)
    n_evals += 1
    if true_s > best_true:
        best_true, best_fails, best_x = true_s, n_fails, x_np.copy()
    dt = time.perf_counter() - t0
    return dict(fitness=best_true, n_fails=best_fails, evals=n_evals, seconds=dt)


def main() -> None:
    cases = [
        ("programme-house/candidate-002.dom", "examples/programme-house", 200),
        ("programme-house/cf0b8a77e8b2325f92a7e7d150184a55.dom", "examples/programme-house", 200),
        ("harbor-house/3m.dom", "examples/harbor-house", 400),
    ]
    repo = Path(__file__).resolve().parents[1]
    for rel, prog_dir, budget in cases:
        path = repo / "examples" / rel
        root = dom_mod.load(str(path))
        free = solver.free_branches(root)
        x0 = np.array([(b.division[0] + b.division[1]) / 2 for b in free], dtype=float)
        print(f"\n=== {rel}  (DOF={len(x0)}, budget={budget}) ===")

        nm = run_nm(root, str(repo / prog_dir), x0, budget)
        print(f"nm_search   fitness={nm['fitness']:.6g} fails={nm['n_fails']} "
              f"evals={nm['evals']} time={nm['seconds']:.2f}s")

        for resnap in (max(budget // 10, 5),):
            td = run_torch(root, str(repo / prog_dir), x0, steps=budget,
                            resnapshot_every=resnap)
            print(f"torch(Adam) fitness={td['fitness']:.6g} fails={td['n_fails']} "
                  f"evals={td['evals']} steps={budget} resnap={resnap} time={td['seconds']:.2f}s")


if __name__ == "__main__":
    main()
