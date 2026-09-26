"""homemaker-py-2g7.1: plan->dom composer tests.

Synthetic fixtures only -- no real human trace exists yet (see DESIGN.md sec
37.x). These exercise the two acceptance-criteria halves: a slicible
partition round-trips to a scoring .dom, and a non-slicible one is reported
with the offending region rather than mis-parsed.
"""

from __future__ import annotations

import textwrap

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.compose import (InheritedCut, LabelError, NonSlicible, StoreyTrace,
                                      compose, parse_svg)

BOUNDARY_YAML = textwrap.dedent(
    """\
    node: [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]]
    perimeter: {a: null, b: null, c: null, d: null}
    height: 3.0
    elevation: 0.0
    wall_inner: 0.08
    wall_outer: 0.25
    rotation: 0
    """
)

# Plot is 10x8. Cut 1 (axis 0, vertical) at x=4 splits into a left column
# (x:0-4, full height) and a right column (x:4-10). Cut 2 (axis 1,
# horizontal) at y=5 splits the right column into a bottom room (y:0-5) and
# a top room (y:5-8) -- exercises both axes and depth-2 recursion.
GOOD_SVG = textwrap.dedent(
    """\
    <svg xmlns="http://www.w3.org/2000/svg"
         xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
      <g inkscape:groupmode="layer" inkscape:label="storey-0">
        <path d="M 4,0 L 4,8"/>
        <path d="M 4,5 L 10,5"/>
        <text x="2" y="4">cr1</text>
        <text x="7" y="2.5">k1</text>
        <text x="7" y="6.5">b1</text>
      </g>
    </svg>
    """
)

# Same partition, endpoints perturbed by < 0.15 (default tol) to exercise
# snapping: a hand-drawn line that overlaps/undershoots slightly.
SLOPPY_SVG = textwrap.dedent(
    """\
    <svg xmlns="http://www.w3.org/2000/svg"
         xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
      <g inkscape:groupmode="layer" inkscape:label="storey-0">
        <path d="M 4.06,-0.05 L 3.95,8.07"/>
        <path d="M 3.96,5.04 L 10.06,4.93"/>
        <text x="2" y="4">cr1</text>
        <text x="7" y="2.5">k1</text>
        <text x="7" y="6.5">b1</text>
      </g>
    </svg>
    """
)

# One dangling interior line that touches neither pair of opposite edges --
# not a guillotine cut of the plot, and there is no other line to try.
NON_SLICIBLE_SVG = textwrap.dedent(
    """\
    <svg xmlns="http://www.w3.org/2000/svg"
         xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
      <g inkscape:groupmode="layer" inkscape:label="storey-0">
        <path d="M 3,3 L 7,3"/>
      </g>
    </svg>
    """
)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return p


def test_composes_synthetic_partition_and_scores(tmp_path):
    boundary_path = _write(tmp_path, "boundary.dom", BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", GOOD_SVG)

    boundary = dom.load(str(boundary_path))
    storeys = parse_svg(str(svg_path))
    root = compose(boundary, storeys)

    leaves = root.leaves()
    assert sorted(leaf.type for leaf in leaves) == ["b1", "cr1", "k1"]

    # round-trips through the .dom text format
    out_path = tmp_path / "plan.dom"
    dom.dump(root, str(out_path))
    reloaded = dom.load(str(out_path))
    reloaded_types = sorted(leaf.type for leaf in reloaded.leaves())
    assert reloaded_types == ["b1", "cr1", "k1"]

    # geometry is sane: leaf areas sum to the (wall-inset) plot area
    total = sum(geometry.area(leaf) for leaf in reloaded.leaves())
    assert total == pytest.approx(geometry.area(reloaded), rel=1e-9)

    # scores cleanly through the native fitness engine (no config on disk:
    # unconstrained score, just confirms it runs end-to-end without raising)
    from homemaker_layout.fitness import Fitness

    fitness = Fitness({}, {})
    score, failures = fitness.score_with_fails(reloaded)
    assert isinstance(score, float)
    assert len(failures) > 0  # unconstrained rooms + no programme: expected fails


def test_snaps_sloppy_hand_traced_lines(tmp_path):
    boundary_path = _write(tmp_path, "boundary.dom", BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", SLOPPY_SVG)

    boundary = dom.load(str(boundary_path))
    storeys = parse_svg(str(svg_path))
    root = compose(boundary, storeys, tol=0.15)

    assert sorted(leaf.type for leaf in root.leaves()) == ["b1", "cr1", "k1"]

    # a tighter tolerance than the sketch's slop should fail to find the cuts
    boundary2 = dom.load(str(boundary_path))
    with pytest.raises((NonSlicible, LabelError)):
        compose(boundary2, storeys, tol=0.01)


def test_non_slicible_region_is_reported(tmp_path):
    boundary_path = _write(tmp_path, "boundary.dom", BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", NON_SLICIBLE_SVG)

    boundary = dom.load(str(boundary_path))
    storeys = parse_svg(str(svg_path))

    with pytest.raises(NonSlicible) as excinfo:
        compose(boundary, storeys)

    exc = excinfo.value
    assert exc.storey == 0
    # names the offending region: should be the whole plot (wall-inset
    # corners), since the dangling line doesn't localise to a sub-quad
    assert len(exc.corners) == 4
    assert "region around" in str(exc)


def test_label_count_mismatch_is_reported(tmp_path):
    svg = textwrap.dedent(
        """\
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
          <g inkscape:groupmode="layer" inkscape:label="storey-0">
          </g>
        </svg>
        """
    )
    boundary_path = _write(tmp_path, "boundary.dom", BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", svg)

    boundary = dom.load(str(boundary_path))
    storeys = parse_svg(str(svg_path))

    with pytest.raises(LabelError) as excinfo:
        compose(boundary, storeys)
    assert excinfo.value.storey == 0
    assert excinfo.value.labels == []


def test_parse_svg_rejects_missing_storey_layers(tmp_path):
    svg = textwrap.dedent(
        """\
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
          <g inkscape:groupmode="layer" inkscape:label="not-a-storey"/>
        </svg>
        """
    )
    svg_path = _write(tmp_path, "plan.svg", svg)
    with pytest.raises(ValueError):
        parse_svg(str(svg_path))


def test_compose_rejects_storey_count_mismatch(tmp_path):
    boundary_path = _write(tmp_path, "boundary.dom", BOUNDARY_YAML)
    boundary = dom.load(str(boundary_path))
    with pytest.raises(ValueError):
        compose(boundary, [StoreyTrace(), StoreyTrace()])


# --------------------------------------------------------------------------- #
# Multi-storey traces (DESIGN.md §39.70). Everything above is single-storey,
# which is why the below-inheritance defect these cover went unnoticed: an
# upper storey's `rotation` and its inherited division ratios are DEAD fields
# (`geometry.coordinate`/`coord_a` follow `below` first), so a traced upper
# storey composed as-if-independent describes a different building.
# --------------------------------------------------------------------------- #

TWO_LEVEL_BOUNDARY_YAML = textwrap.dedent(
    """\
    node: [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]]
    perimeter: {a: null, b: null, c: null, d: null}
    height: 3.0
    elevation: 0.0
    wall_inner: 0.08
    wall_outer: 0.25
    rotation: 0
    above:
      rotation: 0
      height: 3.0
    """
)


def _quad(leaf):
    return [tuple(geometry.coordinate(leaf, i)) for i in range(4)]


def _contains(leaf, point) -> bool:
    """Point inside a leaf's (convex) quad — all cross products one sign."""
    corners = _quad(leaf)
    signs = []
    for i in range(4):
        (ax, ay), (bx, by) = corners[i], corners[(i + 1) % 4]
        signs.append((bx - ax) * (point[1] - ay) - (by - ay) * (point[0] - ax))
    return all(s >= 0 for s in signs) or all(s <= 0 for s in signs)


def _leaf_at(level_root, point):
    for leaf in level_root.leaves():
        if _contains(leaf, point):
            return leaf
    return None


def test_upper_storey_cut_keeps_its_traced_axis(tmp_path):
    """An upper-storey cut across the other axis than the frame below.

    Storey 0 cuts the plot at x=4; storey 1 keeps that wall and cuts its left
    column at y=5 — the other axis. The engine reads the cut through the
    rotation of the node BELOW (`geometry.boundary_id`: "Rotation is delegated
    to the lowest below-link"), so composing the storeys independently turns
    that horizontal cut into a vertical one at the same ratio — same two areas,
    different building, silently.
    """
    svg = textwrap.dedent(
        """\
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
          <g inkscape:groupmode="layer" inkscape:label="storey-0">
            <path d="M 4,0 L 4,8"/>
            <text x="2" y="4">cr1</text>
            <text x="7" y="4">k1</text>
          </g>
          <g inkscape:groupmode="layer" inkscape:label="storey-1">
            <path d="M 4,0 L 4,8"/>
            <path d="M 0,5 L 4,5"/>
            <text x="2" y="2.5">b1</text>
            <text x="2" y="6.5">t1</text>
            <text x="7" y="4">of</text>
          </g>
        </svg>
        """
    )
    boundary_path = _write(tmp_path, "boundary.dom", TWO_LEVEL_BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", svg)
    root = compose(dom.load(str(boundary_path)), parse_svg(str(svg_path)))

    upper = dom.levels(root)[1]
    assert sorted(leaf.type for leaf in upper.leaves()) == ["b1", "of", "t1"]

    # every label sits in the room it labels -- the plan as drawn
    for point, code in ((2, 2.5), "b1"), (((2, 6.5)), "t1"), (((7, 4)), "of"):
        leaf = _leaf_at(upper, point if isinstance(point, tuple) else (2, 2.5))
        assert leaf is not None and leaf.type == code

    # and the mechanism: the axis is recorded where the engine reads it
    assert dom.levels(root)[0].by_id("l").rotation == upper.by_id("l").rotation


def test_traced_upper_cut_that_contradicts_the_wall_below_is_reported(tmp_path):
    """Storey 1 puts the shared wall somewhere else: not representable."""
    svg = textwrap.dedent(
        """\
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
          <g inkscape:groupmode="layer" inkscape:label="storey-0">
            <path d="M 4,0 L 4,8"/>
            <text x="2" y="4">cr1</text>
            <text x="7" y="4">k1</text>
          </g>
          <g inkscape:groupmode="layer" inkscape:label="storey-1">
            <path d="M 7,0 L 7,8"/>
            <text x="3" y="4">b1</text>
            <text x="8.5" y="4">t1</text>
          </g>
        </svg>
        """
    )
    boundary_path = _write(tmp_path, "boundary.dom", TWO_LEVEL_BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", svg)

    with pytest.raises(InheritedCut) as excinfo:
        compose(dom.load(str(boundary_path)), parse_svg(str(svg_path)))
    exc = excinfo.value
    assert exc.storey == 1
    assert exc.path == ""
    assert "inherited" in str(exc)


THREE_LEVEL_BOUNDARY_YAML = textwrap.dedent(
    """\
    node: [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]]
    perimeter: {a: null, b: null, c: null, d: null}
    height: 3.0
    elevation: 0.0
    wall_inner: 0.08
    wall_outer: 0.25
    rotation: 0
    above:
      rotation: 0
      height: 3.0
      above:
        rotation: 0
        height: 3.0
    """
)


def test_ambiguous_upper_span_resolves_onto_the_inherited_wall(tmp_path):
    """Two parallel lines span the same region: take the one owned below.

    Storey 2's left column carries both the y=3 wall it inherits from storey 1
    and a new y=6 wall of its own, and either could be the first guillotine cut
    -- but only cutting at y=3 first can be represented, since storey 1 owns
    that wall and an upper storey's division ratios there are dead. The y=3 arm
    is traced sloppily so that ranking by snapping error alone takes y=6 first,
    which is what a real hand trace did.
    """
    svg = textwrap.dedent(
        """\
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
          <g inkscape:groupmode="layer" inkscape:label="storey-0">
            <path d="M 4,0 L 4,8"/>
            <text x="2" y="4">cr1</text>
            <text x="7" y="4">k1</text>
          </g>
          <g inkscape:groupmode="layer" inkscape:label="storey-1">
            <path d="M 4,0 L 4,8"/>
            <path d="M 0,3 L 4,3"/>
            <text x="2" y="1.5">b1</text>
            <text x="2" y="5.5">t1</text>
            <text x="7" y="4">of</text>
          </g>
          <g inkscape:groupmode="layer" inkscape:label="storey-2">
            <path d="M 4,0 L 4,8"/>
            <path d="M 0.05,3.04 L 3.95,2.96"/>
            <path d="M 0,6 L 4,6"/>
            <text x="2" y="1.5">st1</text>
            <text x="2" y="4.5">st2</text>
            <text x="2" y="7">m</text>
            <text x="7" y="4">r</text>
          </g>
        </svg>
        """
    )
    boundary_path = _write(tmp_path, "boundary.dom", THREE_LEVEL_BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", svg)
    root = compose(dom.load(str(boundary_path)), parse_svg(str(svg_path)))

    mid, top = dom.levels(root)[1], dom.levels(root)[2]
    # the wall storey 2 shares with storey 1 is the inherited one, not y=6
    assert top.by_id("l").division == pytest.approx(mid.by_id("l").division,
                                                    abs=0.02)
    for point, code in (((2, 1.5), "st1"), ((2, 4.5), "st2"),
                        ((2, 7), "m"), ((7, 4), "r")):
        leaf = _leaf_at(top, point)
        assert leaf is not None and leaf.type == code
