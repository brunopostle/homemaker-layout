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


@dataclass(eq=False)
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
            # always assign: re-linking a structurally mutated tree must CLEAR
            # below-links whose path no longer exists on the storey below
            n.below = below_root.by_id(n.id)
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
    geometry.clear_cache()  # fresh tree: drop any stale coordinates
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


# --------------------------------------------------------------------------- #
# Structural predicates (mirrors Urb::Dom::Is_Outside etc.)
# --------------------------------------------------------------------------- #

def is_outside(n: Node) -> bool:
    """True if n's type starts with 'o' or 's' (case-insensitive)."""
    return n.type is not None and n.type[0].lower() in ("o", "s")


def _level_root(n: Node) -> Node:
    while n.parent is not None:
        n = n.parent
    return n


def _below_more(n: Node) -> "Node | None":
    """Matching node on level below, walking up to parent if path absent;
    mirrors ``Urb::Quad::Below_More``."""
    lr = _level_root(n)
    if lr.below is None:
        return None
    if n.below is not None:
        return n.below
    if n.parent is None:
        return None
    return _below_more(n.parent)


def _below_leaves(n: Node) -> "list[Node]":
    bm = _below_more(n)
    return bm.leaves() if bm is not None else []


def _above_node(n: Node) -> "Node | None":
    """Matching node on the level above; mirrors ``Urb::Quad::Above``."""
    lr = _level_root(n)
    if lr.above is None:
        return None
    return lr.above.by_id(n.id)


def _above_more(n: Node) -> "Node | None":
    """Matching node on level above, walking up to parent if path absent;
    mirrors ``Urb::Quad::Above_More``."""
    if _level_root(n).above is None:
        return None
    a = _above_node(n)
    if a is not None:
        return a
    if n.parent is None:
        return None
    return _above_more(n.parent)


def _above_leaves(n: Node) -> "list[Node]":
    am = _above_more(n)
    return am.leaves() if am is not None else []


def level_of(n: Node) -> int:
    """Storey index of n (0 = ground); mirrors ``Urb::Quad::Level``
    (= number of levels below n's level root)."""
    lr = _level_root(n)
    i = 0
    while lr.below is not None:
        lr = lr.below
        i += 1
    return i


def is_covered(n: Node) -> bool:
    """Any leaf above n is indoor; mirrors ``Urb::Dom::Is_Covered``."""
    return any(not is_outside(lf) for lf in _above_leaves(n))


def is_supported(n: Node) -> bool:
    """All leaves below n are indoor; mirrors ``Urb::Dom::Is_Supported``."""
    bl = _below_leaves(n)
    return bool(bl) and all(not is_outside(lf) for lf in bl)


def is_unsupported(n: Node) -> bool:
    """All leaves below n are outdoor; mirrors ``Urb::Dom::Is_Unsupported``."""
    bl = _below_leaves(n)
    return bool(bl) and all(is_outside(lf) for lf in bl)


def is_usable(n: Node) -> bool:
    """Indoors, or on the ground floor, or supported by building below;
    mirrors ``Urb::Dom::Is_Usable``."""
    if not is_outside(n):
        return True
    if level_of(n) == 0:
        return True
    return is_supported(n)


def is_circulation(n: Node) -> bool:
    """Usable and type 'c'/'s'; mirrors ``Urb::Dom::Is_Circulation``."""
    if not is_usable(n):
        return False
    return n.type is not None and n.type[0].lower() in ("c", "s")


# --------------------------------------------------------------------------- #
# Merge_Divided (Urb::Dom::Merge_Divided)
# --------------------------------------------------------------------------- #

def _undivide(n: Node, new_type: str) -> None:
    n.division = None
    n.left = None
    n.right = None
    n.type = new_type


def _merge_node(n: Node) -> None:
    """Post-order recursive merge; mirrors ``Urb::Dom::Merge_Divided``."""
    if n.divided:
        _merge_node(n.left)
        _merge_node(n.right)
    if n.above is not None and n.parent is None:
        _merge_node(n.above)
    if not n.divided:
        return
    lt = n.left.type or ""
    rt = n.right.type or ""
    l_os = bool(lt) and lt[0].lower() in ("o", "s")
    r_os = bool(rt) and rt[0].lower() in ("o", "s")
    if not (l_os and r_os):
        return
    l_o = bool(lt) and lt[0].lower() == "o"
    r_o = bool(rt) and rt[0].lower() == "o"
    if is_supported(n) and l_o and r_o:
        _undivide(n, "O")
    elif is_supported(n):
        _undivide(n, "S")
    elif is_unsupported(n):
        _undivide(n, "O")
    elif _level_root(n).below is None:   # ground floor: !$self->Level in Perl
        _undivide(n, "S")


def merge_divided(root: Node) -> None:
    """Merge adjacent outdoor siblings into a single node in-place;
    mirrors ``Urb::Dom::Merge_Divided``.  Re-links the tree afterward so
    ``below`` / ``parent`` / ``position`` fields stay consistent.
    """
    _merge_node(root)
    _link(root)
