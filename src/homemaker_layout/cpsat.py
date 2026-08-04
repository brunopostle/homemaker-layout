"""Exact room-code-to-leaf labelling via OR-Tools CP-SAT (homemaker-py-2g7.5).

For a FIXED topology (and a fixed circulation/outside placement — that part
stays on ``operators._assign_adjacency_aware``'s existing connected-
dominating-set heuristic, a graph-connectivity problem, not this module's
concern), assigning the remaining room codes to the remaining leaf slots so
that secondary adjacency requirements (``k1<->da1``, ``da1<->o``, ...) are
satisfied is a small discrete optimisation: ~30-70 leaves, ~16-26 codes,
well within CP-SAT's exact-solve range in milliseconds. This replaces the
one-shot greedy/beam heuristic (``operators._assign_adjacency_aware``'s
hardest-constrained-code-first placement, ``_beam_place_rooms``) with an
exact solve of the same decision, usable as (a) a seeder, (b) the periodic
in-search ``mutate_reassign`` repair operator (``operators.py``).

DESIGN.md §25 (line ~3089) rejected adding OR-Tools for a different,
harder QAP-relaxation problem (``Fitness.collapse_global``'s finish-time
relabelling) specifically because the project had no such dependency; that
gap is now closed, but only for this module's simpler fixed-topology
labelling problem — ``collapse_global`` itself is untouched (tracked as a
separate follow-up, DESIGN.md §37.7).

Matches ``graph.check_adjacency``'s real semantics exactly (full-code,
case-insensitive PREFIX match, ``graph._codes_match_prefix``/
``has_adjacency``) rather than the existing greedy heuristic's
first-character-only approximation (``_assign_adjacency_aware``'s local
``_sat``), so the objective this module maximises is a strictly closer proxy
for what ``homemaker-fitness`` actually scores.
"""

from __future__ import annotations

from collections.abc import Hashable
from itertools import pairwise
from typing import Any


def _n_secondary_adjacency(reqs: dict, code: str) -> int:
    r = reqs.get(code)
    return len(r.adjacency) if r else 0


def solve_room_labels(
    slots: list[Hashable],
    codes: list[str],
    reqs: dict,
    neighbors: dict[Hashable, set],
    context_types: dict[Hashable, set[str]],
    time_limit_s: float = 2.0,
) -> dict[Hashable, str] | None:
    """Assign each of ``codes`` to one of ``slots``, maximising satisfied
    secondary adjacency requirements.

    ``slots``: the room slots to label (any hashable key — a ``dom.Node``,
    a plain string in tests, ...). ``codes``: one entry per required room
    instance; if longer than ``slots`` the least-constrained (fewest
    ``reqs[code].adjacency`` entries) codes are dropped first; if shorter,
    the excess slots are simply left unassigned in the returned dict (the
    caller's existing leftover-handling applies, e.g. typing them ``"O"``).
    ``reqs``: ``dict[code, SpaceReq]``. ``neighbors``: adjacency among
    ``slots`` themselves (the room-slot subgraph). ``context_types``: for
    each slot, the set of (lowercase-comparable) type strings of any FIXED
    neighbour outside ``slots`` (e.g. circulation ``"C"``, outside ``"O"``,
    or — for :func:`operators.mutate_reassign`'s scoped re-solve — room
    codes just outside the re-solved wing).

    Returns ``{slot: code}`` (covering ``min(len(slots), len(codes))``
    slots) or ``None`` if OR-Tools is unavailable, the model is infeasible,
    or no solution is found within ``time_limit_s`` — callers must always
    have a defined fallback (the existing greedy/beam path) for ``None``.
    """
    if not slots or not codes:
        return {}
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None

    reqs = reqs or {}
    n = len(slots)
    if len(codes) > n:
        codes = sorted(codes, key=lambda c: -_n_secondary_adjacency(reqs, c))[:n]
    k = len(codes)
    idx = {slot: i for i, slot in enumerate(slots)}

    model = cp_model.CpModel()
    x = {(i, s): model.NewBoolVar(f"x_{i}_{s}") for i in range(k) for s in range(n)}
    for i in range(k):
        model.AddExactlyOne(x[i, s] for s in range(n))
    for s in range(n):
        model.Add(sum(x[i, s] for i in range(k)) <= 1)

    def _matches(code: str, prefix: str) -> bool:
        return code.lower().startswith(prefix.lower())

    # Symmetry breaking (homemaker-py-2g7.5, measured necessary on
    # harbor-house: several unrelated same-requirement codes, e.g. four "t"
    # bedroom instances all needing only "c", turn any permutation among
    # them into an equally-optimal solution — CP-SAT's branch-and-bound can
    # spend seconds proving optimality across that permutation space on an
    # otherwise ~15-variable model). Two code instances are provably
    # interchangeable iff they share the same OWN adjacency requirement set
    # AND neither is ever required as a match target by any code (including
    # each other) — group those and force a canonical slot-index ordering
    # within each group; this never removes an achievable objective value,
    # only the redundant permutations of it.
    referenced = {a.lower() for c in codes for a in (reqs.get(c).adjacency if reqs.get(c) else [])}

    def _is_referenced(code: str) -> bool:
        cl = code.lower()
        return any(cl.startswith(r) for r in referenced)

    groups: dict[tuple, list[int]] = {}
    for i, code in enumerate(codes):
        req = reqs.get(code)
        own = frozenset(a.lower() for a in (req.adjacency if req else []))
        key = ("unique", i) if _is_referenced(code) else ("group", own)
        groups.setdefault(key, []).append(i)

    slot_index: dict[int, Any] = {}
    for key, ids in groups.items():
        if key[0] != "group" or len(ids) < 2:
            continue
        for i in ids:
            if i not in slot_index:
                slot_index[i] = model.NewIntVar(0, n - 1, f"slotidx_{i}")
                model.Add(slot_index[i] == sum(s * x[i, s] for s in range(n)))
        for a, b in pairwise(ids):
            model.Add(slot_index[a] <= slot_index[b])

    neighbor_ok_cache: dict[tuple[int, str], Any] = {}

    def _neighbor_ok(s: int, adj_lower: str):
        key = (s, adj_lower)
        if key in neighbor_ok_cache:
            return neighbor_ok_cache[key]
        slot = slots[s]
        fixed = context_types.get(slot, ())
        if any(_matches(t, adj_lower) for t in fixed):
            neighbor_ok_cache[key] = 1
            return 1
        nbr_idxs = [idx[nb] for nb in neighbors.get(slot, ()) if nb in idx]
        matches = [x[j, ns] for ns in nbr_idxs
                   for j, code in enumerate(codes) if _matches(code, adj_lower)]
        if not matches:
            neighbor_ok_cache[key] = 0
            return 0
        var = model.NewBoolVar(f"nbr_ok_{s}_{adj_lower}")
        model.AddMaxEquality(var, matches)
        neighbor_ok_cache[key] = var
        return var

    sat_vars = []
    for i, code in enumerate(codes):
        req = reqs.get(code)
        if not req or not req.adjacency:
            continue
        seen_adj: set[str] = set()
        for adj_code in req.adjacency:
            adj_lower = adj_code.lower()
            if adj_lower in seen_adj:
                continue
            seen_adj.add(adj_lower)
            for s in range(n):
                ok = _neighbor_ok(s, adj_lower)
                if isinstance(ok, int) and ok == 0:
                    continue  # provably unsatisfiable here — no var needed
                sat = model.NewBoolVar(f"sat_{i}_{s}_{adj_lower}")
                model.Add(sat <= x[i, s])
                model.Add(sat <= ok)
                sat_vars.append(sat)

    if sat_vars:
        model.Maximize(sum(sat_vars))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 1  # determinism (same inputs -> same result)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    result: dict[Hashable, str] = {}
    for i, code in enumerate(codes):
        for s in range(n):
            if solver.Value(x[i, s]) == 1:
                result[slots[s]] = code
                break
    return result
