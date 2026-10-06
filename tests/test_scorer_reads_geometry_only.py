"""Two labels the scorer used to read, and must not (DESIGN.md §39.94/§39.95).

A design's score is supposed to depend on its walls. Format v2 was the first
thing to rewrite a design without moving one -- it renumbers every leaf's
corners and shifts every cut by a few ulps -- and half the corpus re-scored.
Two rules were reading what is not geometry:

* `Fitness.area_outside` counted a neighbour's wall once for every boundary on
  which the pair's overlap came out above zero, including the line where two
  cells merely meet end to end and the overlap is rounding noise
  (`homemaker-py-khgi`; 32 of 48 committed coldstart scores rested on it);
* the stair fit measured from the lowest-NUMBERED corner in use, and could not
  see a run of corners that wrapped from 3 to 0 (`homemaker-py-8b2u.6`; owner's
  ruling: "fit stairs to cores whichever way is best, so the flight can start
  at any corner and may run clockwise or counter clockwise").

Each test here has its negative control: the old rule, put back, must fail it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from homemaker_layout import dom, dom as dom_mod, geometry
from homemaker_layout.fitness import Fitness, _height, _perimeter

REPO = Path(__file__).resolve().parent.parent
DIAG = REPO / "experiments" / "diag_8b2u2_roundtrip.py"
PH = REPO / "examples" / "programme-house"
E4R = REPO / "experiments" / "results" / "e4r-tiers"

pytestmark = pytest.mark.skipif(
    not (REPO / "examples" / "maple-court").is_dir() or not E4R.is_dir(),
    reason="corpus absent")


@pytest.fixture(autouse=True)
def orthogonal(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


@pytest.fixture(scope="module")
def rt():
    spec = importlib.util.spec_from_file_location("_rt", DIAG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sample(rt):
    """One artefact per (programme, corpus), plus every e4r-tiers arm B: the
    small sample is where the big programmes are, the e4r set is where a
    single staircase decides the score."""
    seen, out = set(), []
    for p, prog in rt.corpus():
        key = (prog.name, p.parent.name)
        if key not in seen or (p.parent == E4R and "armB" in p.name):
            seen.add(key)
            out.append((p, prog))
    return out


# --------------------------------------------------------------------------- #
# corner numbering
# --------------------------------------------------------------------------- #
def _moved_by_turning(rt) -> int:
    moved = 0
    for p, prog in _sample(rt):
        base = dom.load(str(p))
        s0, f0 = rt.score(base, prog)
        for k in (1, 2, 3):
            s, f = rt.score(rt.turn_leaves(base, "C", k), prog)
            moved += rt.differs(s, s0, 1e-9) or len(f) != len(f0)
    return moved


def test_turning_a_stair_cells_corner_numbering_changes_no_score(rt):
    assert _moved_by_turning(rt) == 0


def test_control_urbs_stair_fit_does_read_the_numbering(rt, monkeypatch):
    """`Urb::Dom::Stair_Fit` as ported: the base is the edge leaving
    `corners[0]`. With it back, the test above must fail."""
    def urb_stair_fit(self, leaf, corners):
        risers = self._risers_number(_height(leaf), 0.21)
        going = self._ideal_going(_height(leaf) / risers)
        base = geometry.edge_length(leaf, corners[0] % 4)
        length = geometry.edge_length(leaf, (corners[0] + 1) % 4)
        going_a = int((base - 2 * 1.25) / going)
        turns = {1: self._three_turn, 2: self._two_turn,
                 3: self._one_turn}.get(len(corners), self._zero_turn)
        return length / (1.25 * 2 + going * turns(risers, going_a))

    monkeypatch.setattr(Fitness, "_stair_fit", urb_stair_fit)
    assert _moved_by_turning(rt) > 0


# --------------------------------------------------------------------------- #
# rounding noise
# --------------------------------------------------------------------------- #
def _moved_by_a_round_trip(rt) -> int:
    """Scores that change when a design goes through format v2 and back, which
    moves no wall by more than nanometres. Stale inherited ratios are
    synchronised first: that is `homemaker-py-3tzk`, a different matter."""
    import copy

    moved = 0
    for p, prog in _sample(rt):
        a = dom.load(str(p))
        b = rt.round_trip(a)
        synced = copy.deepcopy(a)
        dom.link(synced)
        rt.sync_dead_fields(synced)
        sa, fa = rt.score(synced, prog)
        sb, fb = rt.score(b, prog)
        moved += rt.differs(sa, sb) or len(fa) != len(fb)
    return moved


def test_moving_every_cut_by_nanometres_changes_no_score(rt):
    assert _moved_by_a_round_trip(rt) == 0


def test_control_urbs_daylight_rule_does_read_the_noise(rt, monkeypatch):
    """`Urb::Dom::Area_Outside` as ported: the neighbour's width once per
    boundary with `Overlap() > 0`. With it back, the test above must fail."""
    def urb_area_outside(self, leaf, G, groups):
        length = 0.0
        for nb in G.neighbors(leaf):
            if not dom_mod.is_outside(nb) or dom_mod.is_covered(nb):
                continue
            for contributors in groups.values():
                if geometry.boundary_pair_overlap(contributors, leaf, nb) > 0:
                    length += G[leaf][nb]["width"]
        perimeter = _perimeter(leaf)
        for e in range(4):
            bid = geometry.boundary_id(leaf, e)
            if bid in geometry._EXTERNAL and (perimeter.get(bid) or "").lower() \
                    not in ("private", "fortified"):
                length += geometry.edge_length(leaf, e)
        return length * _height(leaf)

    monkeypatch.setattr(Fitness, "area_outside", urb_area_outside)
    assert _moved_by_a_round_trip(rt) > 0

