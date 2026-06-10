"""Read/write Urb ``.dom`` YAML into a ``Node`` tree.

A ``.dom`` file is a YAML serialisation of a binary slicing tree (see
``Urb::Quad::Serialise``). The top-level mapping is the *lowest* level's root
quad; each level's root carries an ``above`` mapping pointing at the next storey
up. Only the lowest root carries plot geometry (``node``); all other coordinates
are derived top-down (see :mod:`homemaker.geometry`).

This module owns *structure and I/O only* — no geometry. Linkage fields
(``parent``, ``below``, ``position``) are populated after parsing so the geometry
port can mirror ``Urb::Quad`` exactly, including multi-storey wall-stacking where
an upper quad inherits its coordinates from the matching quad below.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

# Root-level attributes that live only on a level's root quad.
_ROOT_FLOATS = ("height", "elevation", "wall_inner", "wall_outer")


@dataclass
class Node:
    rotation: int = 0
    division: list[float] | None = None
    type: str | None = None
    left: "Node | None" = None
    right: "Node | None" = None
    above: "Node | None" = None

    # level-root only
    node: list[list[float]] | None = None  # working corners (wall-inset)
    node_file: list[list[float]] | None = None  # raw outer corners as read from disk
    perimeter: dict | None = None
    height: float | None = None
    elevation: float | None = None
    wall_inner: float | None = None
    wall_outer: float | None = None

    # runtime linkage (never serialised)
    parent: "Node | None" = field(default=None, repr=False, compare=False)
    below: "Node | None" = field(default=None, repr=False, compare=False)
    position: str = ""  # 'l', 'r', or '' for a level root

    @property
    def divided(self) -> bool:
        return self.division is not None and self.left is not None and self.right is not None

    @property
    def id(self) -> str:
        """Absolute id path within this level, e.g. '' (root), 'l', 'rlr'."""
        parts: list[str] = []
        n: Node | None = self
        while n is not None and n.parent is not None:
            parts.append(n.position)
            n = n.parent
        return "".join(reversed(parts))

    def leaves(self) -> list["Node"]:
        if not self.divided:
            return [self]
        return self.left.leaves() + self.right.leaves()

    def by_id(self, path: str) -> "Node | None":
        """Walk an id path from this node; None if the path runs off a leaf."""
        n: Node | None = self
        for ch in path:
            if n is None or not n.divided:
                return None
            n = n.left if ch == "l" else n.right
        return n


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _parse(d: dict) -> Node:
    n = Node()
    n.rotation = int(d.get("rotation") or 0)
    if d.get("type") is not None:
        n.type = str(d["type"])
    if d.get("node") is not None:
        n.node = [[float(p[0]), float(p[1])] for p in d["node"]]
    if d.get("perimeter") is not None:
        n.perimeter = dict(d["perimeter"])
    for k in _ROOT_FLOATS:
        if d.get(k) is not None:
            setattr(n, k, float(d[k]))
    if d.get("division") is not None:
        n.division = [float(x) for x in d["division"]]
        n.left = _parse(d["l"])
        n.right = _parse(d["r"])
    if d.get("above") is not None:
        n.above = _parse(d["above"])
    return n


def _link_subtree(n: Node, parent: Node | None, position: str) -> None:
    n.parent = parent
    n.position = position
    if n.divided:
        _link_subtree(n.left, n, "l")
        _link_subtree(n.right, n, "r")


def levels(root: Node) -> list[Node]:
    """Level roots, lowest first."""
    out: list[Node] = []
    lvl: Node | None = root
    while lvl is not None:
        out.append(lvl)
        lvl = lvl.above
    return out


def _link(root: Node) -> None:
    lvls = levels(root)
    for lvl in lvls:
        _link_subtree(lvl, None, "")  # each level root is parent-less
    # Below-inheritance: a node links to the same-id node one level down,
    # if that path exists there (mirrors Urb::Quad::Below via By_Id).
    for i in range(1, len(lvls)):
        below_root = lvls[i - 1]

        def _set(n: Node, below_root: Node = below_root) -> None:
            b = below_root.by_id(n.id)
            if b is not None:
                n.below = b
            if n.divided:
                _set(n.left)
                _set(n.right)

        _set(lvls[i])


def load(path: str) -> Node:
    """Load a ``.dom`` file and return the fully-linked lowest level root.

    The plot stored on disk is the *outer* boundary; Urb::Dom insets it by
    ``wall_outer`` on load (and offsets back out on save). We mirror that so
    leaf areas match ``urb-fitness.pl``, stashing the raw corners in
    ``node_file`` for byte-perfect plot round-tripping.
    """
    from . import geometry  # local import avoids a module-load cycle

    with open(path) as fh:
        root = _parse(yaml.safe_load(fh))
    _link(root)
    if root.wall_outer is None:
        root.wall_outer = 0.25  # Urb::Dom::Wall_Outer default
    if root.wall_inner is None:
        root.wall_inner = 0.08  # Urb::Dom::Wall_Inner default
    if root.node is not None:
        root.node_file = [list(p) for p in root.node]
        root.node = geometry.offset_quad(root.node, -root.wall_outer)
    return root


# --------------------------------------------------------------------------- #
# Emit (mirrors Urb::Quad::Serialise; field order kept close for readability)
# --------------------------------------------------------------------------- #
def _emit(n: Node, is_level_root: bool) -> dict:
    d: dict = {}
    if is_level_root and (n.node_file is not None or n.node is not None):
        # write the outer plot boundary Urb expects on disk
        if n.node_file is not None:
            d["node"] = [list(p) for p in n.node_file]
        else:
            from . import geometry

            d["node"] = [list(p) for p in geometry.offset_quad(n.node, n.wall_outer or 0.25)]
    if is_level_root and n.perimeter is not None:
        d["perimeter"] = dict(n.perimeter)
    if n.type and not n.divided:
        d["type"] = n.type
    d["rotation"] = n.rotation
    if n.divided:
        d["division"] = list(n.division)
    if is_level_root and n.height is not None:
        d["height"] = n.height
    if is_level_root and n.elevation is not None:
        d["elevation"] = n.elevation
    for k in ("wall_inner", "wall_outer"):
        if is_level_root and getattr(n, k) is not None:
            d[k] = getattr(n, k)
    if n.divided:
        d["l"] = _emit(n.left, False)
        d["r"] = _emit(n.right, False)
    if n.above is not None:
        d["above"] = _emit(n.above, True)
    return d


def dump(root: Node, path: str) -> None:
    with open(path, "w") as fh:
        yaml.safe_dump(
            _emit(root, True), fh, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
