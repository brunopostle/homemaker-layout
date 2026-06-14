"""Unit tests for geometry.py with known analytic values (oracle-free)."""

import math

import pytest

from homemaker_layout import geometry
from homemaker_layout.dom import Node


def _square(size: float = 10.0) -> Node:
    geometry.clear_cache()
    return Node(node=[[0.0, 0.0], [size, 0.0], [size, size], [0.0, size]])


def _rect(w: float, h: float) -> Node:
    geometry.clear_cache()
    return Node(node=[[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]])


def _divided(size: float = 10.0, split: float = 0.5):
    """Return (root, left, right) for a square split at `split`."""
    geometry.clear_cache()
    root = Node(
        node=[[0.0, 0.0], [size, 0.0], [size, size], [0.0, size]],
        division=[split, split],
    )
    left = Node(position="l")
    right = Node(position="r")
    root.left, root.right = left, right
    left.parent = right.parent = root
    return root, left, right


# --------------------------------------------------------------------------- #


def test_area_square():
    assert geometry.area(_square(10.0)) == pytest.approx(100.0)


def test_area_rectangle():
    assert geometry.area(_rect(6.0, 4.0)) == pytest.approx(24.0)


def test_area_divided_halves():
    _, left, right = _divided(10.0, 0.5)
    assert geometry.area(left) == pytest.approx(50.0)
    assert geometry.area(right) == pytest.approx(50.0)


def test_area_divided_unequal():
    _, left, right = _divided(10.0, 0.3)
    assert geometry.area(left) == pytest.approx(30.0, rel=1e-9)
    assert geometry.area(right) == pytest.approx(70.0, rel=1e-9)


def test_edge_length_square_all_equal():
    r = _square(8.0)
    for i in range(4):
        assert geometry.edge_length(r, i) == pytest.approx(8.0)


def test_edge_length_rectangle():
    r = _rect(6.0, 4.0)
    assert geometry.edge_length(r, 0) == pytest.approx(6.0)
    assert geometry.edge_length(r, 1) == pytest.approx(4.0)
    assert geometry.edge_length(r, 2) == pytest.approx(6.0)
    assert geometry.edge_length(r, 3) == pytest.approx(4.0)


def test_angle_square_corners_are_right_angles():
    r = _square(10.0)
    for i in range(4):
        assert geometry.angle(r, i) == pytest.approx(math.pi / 2, abs=1e-9)


def test_angle_rectangle_corners_are_right_angles():
    r = _rect(6.0, 4.0)
    for i in range(4):
        assert geometry.angle(r, i) == pytest.approx(math.pi / 2, abs=1e-9)


def test_aspect_square_is_one():
    assert geometry.aspect(_square(10.0)) == pytest.approx(1.0)


def test_aspect_wide_rectangle():
    assert geometry.aspect(_rect(2.0, 1.0)) == pytest.approx(2.0)


def test_aspect_tall_rectangle_is_same_as_wide():
    assert geometry.aspect(_rect(1.0, 2.0)) == pytest.approx(2.0)


def test_length_narrowest_square():
    assert geometry.length_narrowest(_square(5.0)) == pytest.approx(5.0)


def test_length_narrowest_rectangle():
    assert geometry.length_narrowest(_rect(6.0, 3.0)) == pytest.approx(3.0)


def test_centroid_square():
    cx, cy = geometry.centroid(_square(10.0))
    assert cx == pytest.approx(5.0)
    assert cy == pytest.approx(5.0)


def test_centroid_rectangle():
    cx, cy = geometry.centroid(_rect(6.0, 4.0))
    assert cx == pytest.approx(3.0)
    assert cy == pytest.approx(2.0)


def test_boundary_id_root_returns_external_letters():
    r = _square()
    assert geometry.boundary_id(r, 0) == "a"
    assert geometry.boundary_id(r, 1) == "b"
    assert geometry.boundary_id(r, 2) == "c"
    assert geometry.boundary_id(r, 3) == "d"


def test_boundary_id_left_child_internal_edge():
    root, left, right = _divided()
    # left child edge 1 (rid=1, position='l') → the division line → parent.id
    assert geometry.boundary_id(left, 1) == root.id
    assert geometry.boundary_id(left, 1) == ""  # root id is '' (empty path)


def test_boundary_id_right_child_internal_edge():
    root, left, right = _divided()
    # right child edge 3 → division line → parent.id
    assert geometry.boundary_id(right, 3) == root.id


def test_boundary_id_children_inherit_external_edges():
    _, left, right = _divided()
    assert geometry.boundary_id(left, 0) == "a"
    assert geometry.boundary_id(left, 3) == "d"
    assert geometry.boundary_id(right, 0) == "a"
    assert geometry.boundary_id(right, 1) == "b"


def test_is_between_2d_midpoint():
    assert geometry.is_between_2d([5.0, 0.0], [0.0, 0.0], [10.0, 0.0])


def test_is_between_2d_endpoint():
    assert geometry.is_between_2d([0.0, 0.0], [0.0, 0.0], [10.0, 0.0])


def test_is_between_2d_outside():
    assert not geometry.is_between_2d([11.0, 0.0], [0.0, 0.0], [10.0, 0.0])


def test_is_between_2d_none():
    assert not geometry.is_between_2d(None, [0.0, 0.0], [10.0, 0.0])


def test_offset_quad_inward_shrinks_area():
    corners = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    inset = geometry.offset_quad(corners, -1.0)
    # inward offset of a square → smaller square
    assert inset[0][0] > corners[0][0]  # x moves right
    assert inset[0][1] > corners[0][1]  # y moves up
    assert inset[2][0] < corners[2][0]  # top-right x moves left
    assert inset[2][1] < corners[2][1]  # top-right y moves down


def test_boundary_groups_single_leaf():
    r = _square()
    groups = geometry.boundary_groups(r)
    # undivided root has no internal boundaries
    assert len(groups) == 0


def test_boundary_groups_divided_root():
    root, left, right = _divided()
    groups = geometry.boundary_groups(root)
    # one internal boundary between left and right
    assert len(groups) == 1
    contributors = list(groups.values())[0]
    nodes = {leaf for leaf, _ in contributors}
    assert left in nodes
    assert right in nodes
