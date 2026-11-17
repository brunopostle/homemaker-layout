"""Owner's ruling of 2026-11-17 (DESIGN.md §39.243): "two stairs next to each
other are superfluous". The corridors race's winner put its two shafts end to
end along the south wing, where the rooms opened off them as off a corridor;
it fails `superfluous stair` once. Controls: with the rule off it does not,
and harbor-house's winner, whose two stairs stand apart, does not either.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
HEALTH = REPO / "experiments/results/halving-health-corridors/winner.dom"
HARBOR = REPO / "experiments/results/halving-harbor-guard/winner.dom"


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _fails(path, programme, **conf):
    if not path.is_file():
        pytest.skip("no design")
    fit = Fitness(*load_config(REPO / "examples" / programme))
    for k, v in conf.items():
        fit._conf[k] = v
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    return [f for f in fit.score_with_fails(root)[1] if "superfluous stair" in f]


def test_two_stairs_end_to_end_fail_once():
    assert _fails(HEALTH, "health-centre") == ["superfluous stair (2 stairs, 1 apart)"]


def test_control_rule_off():
    assert _fails(HEALTH, "health-centre", superfluous_stair=False) == []


def test_control_two_stairs_apart():
    assert _fails(HARBOR, "harbor-house") == []
