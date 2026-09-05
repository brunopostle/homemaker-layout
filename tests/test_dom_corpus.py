"""Corpus-backed tests for dom round-trip, free-branch ownership, and fitness parity.

Skipped when the Urb checkout is absent (these need only its .dom files, not
perl).  The parity tests compare native Python fitness against cached oracle
scores and failure sets (generated with URB_NO_OCCLUSION=1).
"""

import math
import re
from pathlib import Path

import pytest

from homemaker_layout import dom, solver

CORPUS = Path(__file__).parent.parent / "examples" / "programme-house"

# The parity fixtures are the Perl corpus, whose files Urb names by MD5. Any
# other .dom in this directory is something a later session generated -- a
# search artefact, a candidate, a seed -- and must NEVER be used as a parity
# fixture: its .score, if one exists, was written by the NATIVE scorer, so
# comparing against it compares the native scorer with itself and passes
# whatever the native scorer says. That is exactly what was happening here
# until 39.20; see `homemaker-py-*` for restoring real oracle fixtures.
_ORACLE_NAME = re.compile(r"^[0-9a-f]{32}\.dom$")
ORACLE_FIXTURES = sorted(p for p in CORPUS.glob("*.dom")
                         if _ORACLE_NAME.match(p.name))

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(), reason="Corpus not available")


def test_roundtrip_idempotent_and_area_preserving(tmp_path):
    # dump() does not reproduce the source bytes (different YAML style); the
    # real invariants are that a dumped file reloads to the same dump (stable
    # fixed point) and that per-leaf geometry survives the trip (§4.1 is the
    # area validation against Urb itself).
    from homemaker_layout import geometry

    for src in sorted(CORPUS.glob("*.dom")):
        root = dom.load(str(src))
        areas = [geometry.area(leaf) for lvl in dom.levels(root) for leaf in lvl.leaves()]
        once = tmp_path / ("once_" + src.name)
        dom.dump(root, str(once))

        root2 = dom.load(str(once))
        areas2 = [geometry.area(leaf) for lvl in dom.levels(root2) for leaf in lvl.leaves()]
        assert areas == pytest.approx(areas2, abs=1e-9), src.name

        twice = tmp_path / ("twice_" + src.name)
        dom.dump(root2, str(twice))
        assert twice.read_bytes() == once.read_bytes(), src.name


def test_free_branches_known_dof():
    # DOF figures from DESIGN.md §4.5
    expected = {
        "2f45907abd9accac2a124d311732f749.dom": 7,
        "candidate-002.dom": 6,
        "c964435454c459f86c3ed9a5a7621132.dom": 6,
    }
    for name, dof in expected.items():
        root = dom.load(str(CORPUS / name))
        assert len(solver.free_branches(root)) == dof, name


def test_free_branches_are_lowest_storey_owners():
    for src in sorted(CORPUS.glob("*.dom")):
        root = dom.load(str(src))
        for b in solver.free_branches(root):
            assert b.divided
            assert b.below is None or not b.below.divided


# ---------------------------------------------------------------------------
# Phase 3 gate: native fitness parity vs oracle (homemaker-py-uxz)
# Oracle scores and failure sets cached as <file>.dom.score / <file>.dom.fails
# generated with URB_NO_OCCLUSION=1 (DESIGN.md §6 descope).
# ---------------------------------------------------------------------------

def _native_evaluate(src: Path):
    """Run native Fitness.evaluate and return (score, frozenset[fail_lines])."""
    from homemaker_layout import fitness as fit_mod, graph as graph_mod, geometry

    root = dom.load(str(src))
    conf, cost = fit_mod.load_config(CORPUS)
    fit = fit_mod.Fitness(conf, cost)

    failures: list[str] = []
    tracking: dict = {
        "has_public_access_outside": False,
        "has_public_access_inside": False,
        "public_length_all": 0.0,
        "public_length_outside": 0.0,
        "private_length_all": 0.0,
        "private_length_outside": 0.0,
        "stair_fit": [],
        "_failures": failures,
    }

    programme = fit._programme or {}
    geometry.clear_cache()

    check_f, missing = graph_mod.check_space_counts(root, programme)
    failures.extend(check_f)
    fit.preprocess_building(root)
    _, gcpre = graph_mod.build_graphs_with_circ(root, fit.conf("door_width") or 1.2, failures.append, fit.usages())
    gbpre = graph_mod.build_graphs(root, fit.conf("door_width") or 1.2)
    failures.extend(graph_mod.check_adjacency(root, programme, gbpre, missing))
    failures.extend(graph_mod.check_level_constraints(root, programme, missing))
    failures.extend(graph_mod.check_vertical_connectivity(root, programme, missing))

    dom.merge_divided(root)
    geometry.clear_cache()
    _, gc = graph_mod.build_graphs_with_circ(root, fit.conf("door_width") or 1.2, failures.append, fit.usages())
    gb = graph_mod.build_graphs(root, fit.conf("door_width") or 1.2)

    cost_v = fit.plot_cost(root)
    value = 0.0
    lvls = dom.levels(root)
    for li, lvl in enumerate(lvls):
        se = fit.process_storey(
            lvl, gb[li], li, failures.append,
            graph_circ=gc, tracking=tracking, lvls=lvls, root=root,
        )
        cost_v += se.cost
        value += se.value

    bf = fit.evaluate_building(root, tracking)
    value *= bf
    value *= 0.5 ** len(failures)
    score = value / cost_v if cost_v else 0.0

    return score, frozenset(failures)


def _oracle_result(src: Path):
    """Read cached oracle score and failure set (URB_NO_OCCLUSION=1)."""
    from homemaker_layout.oracle import Score

    score_file = Path(str(src) + ".score")
    fails_file = Path(str(src) + ".fails")
    if not score_file.exists():
        pytest.skip(
            f"No oracle score committed for {src.name}. `.gitignore` excludes "
            "*.dom.score and *.dom.fails, and none has ever been tracked, so "
            "native-vs-Perl parity is UNVERIFIED in this repository -- these "
            "cases have always skipped on a clean checkout (DESIGN.md §39.20). "
            "Regenerating them with the native scorer would not fix it; the "
            "cache has to come from the Perl oracle.")
    oracle_score = float(score_file.read_text().strip())
    oracle_fails = Score(
        fitness=oracle_score,
        fails=fails_file.read_text() if fails_file.exists() else "",
    ).fail_lines
    return oracle_score, frozenset(oracle_fails)


@pytest.mark.parametrize("src", ORACLE_FIXTURES, ids=lambda p: p.name)
def test_native_fitness_score_parity(src):
    """Native score matches oracle within 1e-4 relative tolerance."""
    native_score, _ = _native_evaluate(src)
    oracle_score, _ = _oracle_result(src)
    assert math.isclose(native_score, oracle_score, rel_tol=1e-4, abs_tol=1e-15), (
        f"{src.name}: native={native_score:.6e} oracle={oracle_score:.6e}"
    )


@pytest.mark.parametrize("src", ORACLE_FIXTURES, ids=lambda p: p.name)
def test_native_fitness_fail_set_parity(src):
    """Native failure set matches oracle failure set exactly."""
    _, native_fails = _native_evaluate(src)
    _, oracle_fails = _oracle_result(src)
    only_native = native_fails - oracle_fails
    only_oracle = oracle_fails - native_fails
    assert not only_native and not only_oracle, (
        f"{src.name}: only_native={sorted(only_native)} only_oracle={sorted(only_oracle)}"
    )


def test_parity_fixtures_are_never_session_artefacts():
    """Guard for the defect §39.20 records.

    The parity tests read a cached `.score` beside each `.dom` and treat it as
    the Perl oracle's answer. Nothing in the file says who wrote it, so a `.dom`
    left behind by a search run -- with a `.score` written by the NATIVE scorer
    -- silently becomes a "parity" case that compares the native scorer with
    itself. Three such cases were live and passing until the §39.19 objective
    change made the native scorer disagree with its own stale output.
    """
    for src in ORACLE_FIXTURES:
        assert _ORACLE_NAME.match(src.name), src.name
    stray = [p.name for p in CORPUS.glob("*.dom")
             if not _ORACLE_NAME.match(p.name)
             and Path(str(p) + ".score").exists()]
    assert not set(stray) & {p.name for p in ORACLE_FIXTURES}, (
        f"session artefacts leaked into the parity fixtures: {stray}")
