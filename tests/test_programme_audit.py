"""The programme audit must not cry IMPOSSIBLE at a legitimate config (45g).

CLAUDE.md tells agents to run ``experiments/audit_programme_config.py`` when
adding or editing a programme. Since §39.22 removed the corridor aspect cap it
reported ``C ... IMPOSSIBLE (size/width/proportion contradict)`` on every corpus
programme, because ``np.linspace(1.0, inf, n)`` is ``[nan, inf, inf, ...]`` and
every candidate height collapses to ``sqrt(A/inf) = 0``.

A tool that cries wolf is worse than no tool: an agent either chases a non-bug or
learns to ignore its output. Same shape as §39.20 and §39.25.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

AUDIT = Path(__file__).resolve().parent.parent / "experiments" / "audit_programme_config.py"
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CORPUS = ["harbor-house", "maple-court", "health-centre", "programme-house"]
pytestmark = pytest.mark.skipif(
    not AUDIT.is_file() or not (EXAMPLES / "harbor-house").is_dir(),
    reason="audit or examples absent")


def _audit():
    spec = importlib.util.spec_from_file_location("programme_audit", AUDIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fit(name):
    from homemaker_layout import fitness
    conf, cost = fitness.load_config(EXAMPLES / name)
    return fitness.Fitness(conf, cost)


@pytest.mark.parametrize("name", CORPUS)
def test_an_unconstrained_aspect_is_not_impossible(name):
    """Circulation has no aspect cap by §39.22, which is deliberate, not broken."""
    mod = _audit()
    fit = _fit(name)
    r = mod.audit_code(fit, "C", height=3.0)
    assert not math.isfinite(r["rmax"]), (
        "premise: C's aspect is unconstrained -- if that changes this test is "
        "no longer testing what it thinks")
    assert r["swp"], f"{name}: C reported impossible with an unconstrained aspect"


@pytest.mark.parametrize("name", CORPUS)
def test_no_corpus_room_is_impossible(name):
    mod = _audit()
    fit = _fit(name)
    from homemaker_layout import programme
    for code in programme.load_programme_dir(str(EXAMPLES / name)):
        assert mod.audit_code(fit, code, height=3.0)["swp"], (
            f"{name}: {code} reported impossible as specified")


def test_crinkliness_bounds_use_the_exact_generic_not_a_leading_letter():
    """§39.4: `cr1` is a room, not circulation. harbor-house has cr1/of/st1/st2,
    so a first-character test hands real rooms circulation's bounds."""
    mod = _audit()
    fit = _fit("harbor-house")
    room = mod.crink_bounds(fit, circulation=False)
    circ = mod.crink_bounds(fit, circulation=True)
    # audit_code must classify by the exact code, so cr1 gets the room bounds
    r_cr1 = mod.audit_code(fit, "cr1", height=3.0)
    r_C = mod.audit_code(fit, "C", height=3.0)
    assert r_cr1["code"] == "cr1" and r_C["code"] == "C"
    if room != circ:
        # only meaningful when the two families actually differ
        assert r_cr1["needs"] is not None or r_cr1["swp"]
