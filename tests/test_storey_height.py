"""The inner loop may tune a storey's height (`homemaker-py-y4p4.2`).

Owner's rulings, 2026-10-08/09 (DESIGN.md §39.125, §39.128): "4.86 m depth is
only a limit for low ceilings, the solver should be able to raise the ceiling
height of a storey and allow deeper rooms"; "2.7 can be a minimum height, but
we should leave the maximum open". The scorer has always read the height and
the file has always stored it. What is held here is that the search can move
it, never below the floor, and that a search which is not asked to is the
search it was.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, evolve, geometry, innerloop

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"
DESIGN = PH / "coldstart-1a24b6a+orth-500000-s0.dom"

pytestmark = pytest.mark.skipif(not DESIGN.exists(), reason="examples absent")


@pytest.fixture
def orth():
    was = geometry.ORTHOGONAL_DIVISION
    geometry.ORTHOGONAL_DIVISION = True
    geometry.clear_cache()
    yield
    geometry.ORTHOGONAL_DIVISION = was
    geometry.clear_cache()


def _design():
    root = dom.load(str(DESIGN))
    dom.link(root)
    geometry.clear_cache()
    return root


@pytest.mark.parametrize("h", [2.7, 3.0, 3.3, 4.5, 12.0, 40.0])
def test_a_height_survives_the_round_trip(h):
    u = innerloop.height_to_u(h)
    assert innerloop._EPS <= u <= 1 - innerloop._EPS
    assert innerloop.u_to_height(u) == pytest.approx(h)


def test_no_storey_goes_below_the_floor_and_none_is_capped_low():
    assert innerloop.u_to_height(0.0) == pytest.approx(innerloop.HEIGHT_MIN)
    assert innerloop.u_to_height(innerloop.height_to_u(2.2)) == pytest.approx(2.7)
    # "leave the maximum open": the top of the range is far above any storey
    assert innerloop.u_to_height(1.0) > 40


def test_unasked_the_loop_leaves_every_height_alone(orth):
    root = _design()
    before = [lvl.height for lvl in dom.levels(root)]
    r = innerloop.optimise(root, str(PH), budget=40)
    assert [lvl.height for lvl in dom.levels(root)] == before
    assert len(r.x) == len(innerloop.free_with_keys(root))


def test_asked_it_tunes_one_height_per_storey_and_writes_them_back(orth):
    root = _design()
    n_cuts, storeys = len(innerloop.free_with_keys(root)), dom.levels(root)
    r = innerloop.optimise(root, str(PH), budget=120, heights=True)
    assert len(r.x) == n_cuts + len(storeys)
    got = [lvl.height for lvl in storeys]
    assert got == pytest.approx([innerloop.u_to_height(u) for u in r.x[n_cuts:]])
    assert all(h >= innerloop.HEIGHT_MIN for h in got)
    assert any(abs(h - 3.0) > 1e-6 for h in got), "the loop never moved a height"
    # and it is the same objective: never worse than where it started
    assert r.fitness >= r.x0_fitness


def test_a_vector_of_ratios_alone_is_still_accepted(orth):
    """`x0` is the ratios; a caller that knows nothing of heights (the warm
    start from a parent, the shape-curve DP) passes what it always passed."""
    root = _design()
    ev = innerloop.NativeEvaluator(root, str(PH), heights=True)
    before = [lvl.height for lvl in dom.levels(root)]
    ev.apply(ev.x_current)
    assert [lvl.height for lvl in dom.levels(root)] == before
    ev.apply(np.concatenate([ev.x_current, [innerloop.height_to_u(3.4)] * ev.n_heights]))
    assert [lvl.height for lvl in dom.levels(root)] == pytest.approx([3.4] * ev.n_heights)


def test_a_restart_scatters_the_walls_and_keeps_the_heights(orth, monkeypatch):
    """Nelder-Mead restarts from a random point when it converges early. For a
    cut that is anywhere in the cell; for a height it would be anywhere from
    2.8 m to 11 m, which is not a restart."""
    from scipy import optimize

    starts = []
    real = optimize.minimize

    def spy(f, x0, **kw):
        starts.append(np.array(x0))
        kw["options"] = dict(kw["options"], maxfev=min(kw["options"]["maxfev"], 12))
        return real(f, x0, **kw)

    monkeypatch.setattr(optimize, "minimize", spy)
    root = _design()
    n_h = len(dom.levels(root))
    innerloop.optimise(root, str(PH), budget=80, heights=True)
    assert len(starts) >= 3
    for s in starts[1:]:
        hs = [innerloop.u_to_height(u) for u in s[-n_h:]]
        assert all(2.7 <= h < 4.5 for h in hs), hs


def test_the_probe_crosses_a_valley_the_fine_search_does_not(orth, monkeypatch):
    """Planted: a scorer that pays only for a storey at 3.5 m or more, and
    charges a little for every centimetre below that. Nelder-Mead from 3.0 m
    walks downhill and stays low; the probe finds the far side."""
    root = _design()

    class Planted:
        def score_with_fails(self, r):
            h = dom.levels(r)[0].height
            return (10.0 if h >= 3.5 else 1.0 - 0.1 * (h - 2.7)), ()

    def run(probe: bool) -> float:
        tree = copy.deepcopy(root)
        dom.link(tree)
        ev = innerloop.NativeEvaluator(tree, str(PH), heights=True)
        ev._fit = Planted()
        x0 = np.concatenate([ev.x_current, ev.x_heights])
        if probe:
            x0 = innerloop.probe_heights(ev, x0)
        return innerloop.nm_search(ev, x0, budget=120).fitness

    assert run(probe=True) == 10.0
    assert run(probe=False) < 2.0          # the control: the valley is real


def test_the_height_move_steps_a_storey_and_respects_the_floor():
    from homemaker_layout import operators

    root = _design()
    seen = set()
    for seed in range(40):
        child, desc = operators.mutate_storey_height(root, np.random.default_rng(seed), [])
        hs = [lvl.height for lvl in dom.levels(child)]
        assert all(h >= innerloop.HEIGHT_MIN - 1e-9 for h in hs), (desc, hs)
        assert "noop" in desc or any(abs(h - 3.0) > 1e-9 for h in hs)
        seen.add(desc.split()[1])
    assert {"all", "0", "1"} <= seen
    # the parent is never touched
    assert all(lvl.height == 3.0 for lvl in dom.levels(root))
    # and a storey on the floor is not pushed through it
    for lvl in dom.levels(root):
        lvl.height = innerloop.HEIGHT_MIN
    lows = [operators.mutate_storey_height(root, np.random.default_rng(s), [])
            for s in range(40)]
    assert all(lv.height >= innerloop.HEIGHT_MIN for c, _ in lows for lv in dom.levels(c))
    assert any("noop" in d for _, d in lows)


def test_a_default_search_never_draws_the_height_move(orth):
    from homemaker_layout import driver, operators

    drawn = []
    real = operators.mutate_storey_height
    operators.MUTATIONS["storey_height"] = lambda *a, **k: (drawn.append(1), real(*a, **k))[1]
    try:
        root = dom.load(str(PH / "init.dom"))
        driver.search(root, str(PH), budget=2500, child_budget=20, seed=2)
        assert not drawn
        driver.search(dom.load(str(PH / "init.dom")), str(PH), budget=2500,
                      child_budget=20, seed=2, inner_kw={"heights": True})
        assert drawn, "the flagged search never played the move either: a vacuous test"
    finally:
        operators.MUTATIONS["storey_height"] = real


def _evolve(tmp_path: Path, name: str, monkeypatch, flag: "str | None") -> Path:
    work = tmp_path / name
    work.mkdir()
    for f in ("init.dom", "patterns.config", "costs.config"):
        if (PH / f).exists():
            shutil.copy(PH / f, work / f)
    monkeypatch.setenv("HOMEMAKER_ORTHOGONAL_DIVISION", "1")
    monkeypatch.delenv("HOMEMAKER_TUNE_HEIGHTS", raising=False)
    out = work / "out.dom"
    argv = [str(work / "init.dom"), "--budget", "1200", "--seed", "4",
            "--workers", "1", "--output", str(out)]
    assert evolve.main(argv + ([flag] if flag else [])) == 0
    return out


def test_the_search_takes_the_flag_and_is_unchanged_without_it(tmp_path, monkeypatch, orth):
    plain = _evolve(tmp_path, "plain", monkeypatch, None)
    off = _evolve(tmp_path, "off", monkeypatch, "--no-tune-heights")
    tall = _evolve(tmp_path, "tall", monkeypatch, "--tune-heights")
    assert plain.read_text() == off.read_text()

    def heights(p):
        return [lvl.height for lvl in dom.levels(dom.load(str(p)))]

    assert all(h == 3.0 for h in heights(plain))
    assert all(h >= innerloop.HEIGHT_MIN for h in heights(tall))
    assert any(abs(h - 3.0) > 1e-6 for h in heights(tall)), "the search never moved a height"
