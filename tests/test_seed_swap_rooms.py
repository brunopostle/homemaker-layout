"""The seeder's room-swap pass (DESIGN.md §39.235, `homemaker-py-5fje.22`):
it only keeps swaps the scorer prefers, it moves rooms and never adds or
drops one, and a room the brief binds to a storey stays on it."""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

from homemaker_layout import dom, geometry, operators, programme
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
SEED = REPO / "experiments/results/halving-health/two-18.dom"
PROG = REPO / "examples/health-centre"


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _seeder():
    sys.path.insert(0, str(REPO / "experiments"))
    spec = importlib.util.spec_from_file_location(
        "seed_from_catalogue", REPO / "experiments" / "seed_from_catalogue.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rooms(root, prog):
    return Counter((li, lf.type) for li, lvl in enumerate(dom.levels(root))
                   for lf in lvl.leaves() if lf.type in prog)


def test_swaps_only_improve_and_keep_the_rooms():
    if not SEED.is_file():
        pytest.skip("no seed")
    sc = _seeder()
    conf, cost = load_config(PROG)
    fit = Fitness(conf, cost)
    reqs = programme.load_programme_dir(str(PROG))
    prog = operators._programme_codes(reqs)
    root = dom.load(str(SEED))
    dom.link(root)
    geometry.clear_cache()
    s0, f0 = fit.score_with_fails(root)
    before = _rooms(root, prog)
    kept = sc.swap_rooms(root, reqs, fit, max_passes=1)
    geometry.clear_cache()
    s1, f1 = fit.score_with_fails(root)
    after = _rooms(root, prog)
    assert (len(f1), -s1) <= (len(f0), -s0)
    # control: the pass did something, so the checks below are not vacuous
    assert kept > 0 and (len(f1), -s1) < (len(f0), -s0)
    assert sum(before.values()) == sum(after.values())
    assert Counter(c for _, c in before.elements()) == Counter(c for _, c in after.elements())
    for (li, code), n in before.items():
        if prog[code].level is not None:
            assert after[(li, code)] == n
