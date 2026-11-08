"""The ``aggregation`` config key (`homemaker-py-5fje.5`, DESIGN.md §39.217).

"A0", the default, is today's score, and the switch must not move it by a bit:
`experiments/diag_8b2u_score_cost.py --snapshot/--diff` proved that over every
committed orthogonal artefact when it landed, and the first test here pins
it on a sample. "P1" and "P2" are `experiments/diag_aggregation.py`'s arms,
moved into the scorer so a search can run under them. They must equal what
that tool computes, which is how Phase 1 measured them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
DESIGNS = [
    ("programme-house", "examples/programme-house/hand-3storey.dom"),
    ("maple-court", "experiments/results/split-stair-race/final-best-3.dom"),
    ("maple-court", "experiments/results/join-clean9/final-joined-1.dom"),
    ("harbor-house", "experiments/results/halving-harbor/winner-total.dom"),
    ("health-centre", "examples/health-centre/coldstart-c836457+orth-500000-s1.dom"),
]


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


@pytest.fixture(scope="module")
def diag():
    sys.path.insert(0, str(REPO / "experiments"))
    import diag_aggregation as d
    from homemaker_layout import programme
    return d, programme


def _root(path):
    root = dom.load(str(REPO / path))
    dom.link(root)
    return root


def _fit(prog, **ov):
    return Fitness(*load_config(REPO / "examples" / prog, overrides=ov or None))


@pytest.mark.parametrize("prog,path", DESIGNS)
def test_default_is_today(prog, path):
    explicit = _fit(prog, aggregation="A0").score_with_fails(_root(path))
    assert _fit(prog).score_with_fails(_root(path)) == explicit


@pytest.mark.parametrize("prog,path", DESIGNS)
@pytest.mark.parametrize("arm,phi", [("P1", 1e-3), ("P2", 1e-3), ("P1", 1e-20)])
def test_p_arms_equal_the_diagnostic(diag, prog, path, arm, phi):
    d, programme = diag
    reqs = programme.load_programme_dir(str(REPO / "examples" / prog))
    want = d.arms(_fit(prog), reqs, _root(path), phi)
    score, fails = _fit(prog, aggregation=arm, aggregation_phi=phi).score_with_fails(_root(path))
    assert score == pytest.approx(want[arm], rel=1e-12)
    assert len(fails) == want["fails"]          # the fail list is not the arm's
    # control: the arm is not A0 under another name
    assert score != pytest.approx(want["A0"], rel=1e-6)


def test_unknown_aggregation_is_refused():
    with pytest.raises(ValueError, match="unknown aggregation"):
        _fit("programme-house", aggregation="P3")


# --- the run-time switch (homemaker-py-5fje.14, DESIGN.md §39.218) ---------

def test_environment_sets_the_aggregation(monkeypatch):
    from homemaker_layout import fitness
    monkeypatch.setenv(fitness.AGGREGATION_ENV, "P2")
    monkeypatch.setenv(fitness.AGGREGATION_PHI_ENV, "1e-20")
    conf, _ = load_config(REPO / "examples" / "programme-house")
    assert (conf["aggregation"], conf["aggregation_phi"]) == ("P2", 1e-20)
    # an explicit override still wins over the environment
    conf, _ = load_config(REPO / "examples" / "programme-house",
                          overrides={"aggregation": "A0"})
    assert conf["aggregation"] == "A0"
    # control: without the environment the key is the config's, absent
    monkeypatch.delenv(fitness.AGGREGATION_ENV)
    monkeypatch.delenv(fitness.AGGREGATION_PHI_ENV)
    conf, _ = load_config(REPO / "examples" / "programme-house")
    assert "aggregation" not in conf


@pytest.mark.parametrize("arm,phi,suffix", [
    (None, None, ""), ("A0", None, ""), ("P1", None, "+P1"),
    ("P2", "1e-3", "+P2"), ("P1", "1e-20", "+P1phi1e-20")])
def test_the_stamp_names_the_aggregation(monkeypatch, arm, phi, suffix):
    from homemaker_layout import fitness
    for env, v in ((fitness.AGGREGATION_ENV, arm), (fitness.AGGREGATION_PHI_ENV, phi)):
        if v is None:
            monkeypatch.delenv(env, raising=False)
        else:
            monkeypatch.setenv(env, v)
    assert fitness.aggregation_suffix() == suffix


def test_a_bad_environment_is_refused(monkeypatch):
    from homemaker_layout import fitness
    monkeypatch.setenv(fitness.AGGREGATION_ENV, "p1")
    with pytest.raises(ValueError, match="HOMEMAKER_AGGREGATION"):
        load_config(REPO / "examples" / "programme-house")


def test_evolve_refuses_tiers_with_score_ranking(tmp_path, capsys):
    from homemaker_layout import evolve
    rc = evolve.main([str(REPO / "examples/programme-house/init.dom"),
                      "--use-tiers", "--rank", "score", "--budget", "1"])
    assert rc == 2 and "--use-tiers with --rank score" in capsys.readouterr().err
