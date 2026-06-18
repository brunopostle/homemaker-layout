"""Topology genome: base-floor tree + per-storey deltas + type assignment.

The search genome (DESIGN.md §5.2) is the base-floor slicing tree plus, per
additional storey, the *delta* against the storey below: extra divisions,
undivisions, and leaf-type overrides. Below-inheritance does the rest — a cut
is owned by the lowest storey where its path is divided, so walls stack for
free and the multi-storey constraint acts as a regulariser.

Corpus reality check (measured): upper-storey nodes carry heavily drifted
*dead* fields — 97 inherited-cut divisions and 187 rotations differ from the
owning node below across the 35-file corpus. They are dead because
``geometry.coordinate`` delegates to ``below`` before ever reading them (and
Urb's ``Coordinate`` does the same). ``decode`` therefore canonicalises every
below-linked node's rotation/division/type from the storey below;
``experiments/genome_parity.py`` verifies this is fitness-neutral through the
oracle. Upper level roots carry only ``height`` as metadata.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from . import dom

_BASE_META = ("node", "node_file", "perimeter", "height", "elevation",
              "wall_inner", "wall_outer")


@dataclass
class GNode:
    """Genome tree node; a leaf iff ``division is None``."""
    type: str | None = None
    rotation: int = 0
    division: tuple[float, float] | None = None
    left: "GNode | None" = None
    right: "GNode | None" = None

    @property
    def divided(self) -> bool:
        return self.division is not None


@dataclass
class StoreyDelta:
    """One storey's difference from the storey below it."""
    height: float | None = None
    undivides: list[str] = field(default_factory=list)  # divided below, leaf here
    divides: dict[str, GNode] = field(default_factory=dict)  # leaf below, subtree here
    retypes: dict[str, str | None] = field(default_factory=dict)  # leaf type overrides


@dataclass
class Genome:
    base: GNode
    base_meta: dict
    deltas: list[StoreyDelta] = field(default_factory=list)

    @property
    def n_storeys(self) -> int:
        return 1 + len(self.deltas)


# --------------------------------------------------------------------------- #
# encode: Node tree -> Genome
# --------------------------------------------------------------------------- #
def _gnode_from(n: dom.Node) -> GNode:
    g = GNode(type=n.type, rotation=n.rotation)
    if n.divided:
        g.division = (n.division[0], n.division[1])
        g.left = _gnode_from(n.left)
        g.right = _gnode_from(n.right)
    return g


def _delta_walk(n: dom.Node, below: dom.Node, path: str, delta: StoreyDelta) -> None:
    if below.divided and n.divided:
        _delta_walk(n.left, below.left, path + "l", delta)
        _delta_walk(n.right, below.right, path + "r", delta)
    elif below.divided:  # merged here
        delta.undivides.append(path)
        delta.retypes[path] = n.type
    elif n.divided:  # extra division here; the subtree's cuts are owned here
        sub = _gnode_from(n)
        # the subtree root still sits on an inherited quad: its rotation is
        # dead (geometry delegates to below, and decode keeps the inherited
        # value) — store 0 so genomes from drifted sources compare equal
        sub.rotation = 0
        delta.divides[path] = sub
    elif n.type != below.type:
        delta.retypes[path] = n.type


def encode(root: dom.Node) -> Genome:
    lvls = dom.levels(root)
    base_meta = {k: copy.deepcopy(getattr(lvls[0], k)) for k in _BASE_META}
    g = Genome(base=_gnode_from(lvls[0]), base_meta=base_meta)
    for below, lvl in zip(lvls, lvls[1:]):
        delta = StoreyDelta(height=lvl.height)
        _delta_walk(lvl, below, "", delta)
        g.deltas.append(delta)
    return g


# --------------------------------------------------------------------------- #
# signature: Genome -> structural topology hash (homemaker-py-c4c.5, §11.5)
# --------------------------------------------------------------------------- #
# A cheap structural signature so the search can niche by *topology* rather than
# by the fitness scalar. It captures tree shape, cut orientation (rotation) and
# leaf-type assignment per storey, but deliberately ignores division *ratios*
# (geometry): two designs with the same topology and different geometry collapse
# to one signature, which is exactly the "same topology, different geometry"
# equivalence the niching wants. Routing through ``encode`` first canonicalises
# the dead inherited fields (rotation/division on below-linked nodes, see module
# docstring), so genome-equal trees always share a signature. This is the cheap
# stand-in for the canonical Polish encoding (homemaker-py-9gp), which would
# additionally collapse associativity ``(a|b)|c == a|(b|c)``.
def _gnode_sig(g: GNode) -> str:
    if g.divided:
        return f"({g.rotation}{_gnode_sig(g.left)}{_gnode_sig(g.right)})"
    return g.type or "."


def _delta_sig(d: StoreyDelta) -> str:
    parts: list[str] = []
    for path in sorted(d.undivides):
        parts.append(f"u{path}={d.retypes.get(path) or '.'}")
    for path in sorted(d.divides):
        parts.append(f"d{path}={_gnode_sig(d.divides[path])}")
    for path in sorted(p for p in d.retypes if p not in d.undivides):
        parts.append(f"t{path}={d.retypes[path] or '.'}")
    return ";".join(parts)


def signature(root: dom.Node) -> str:
    """Structural topology signature of a (possibly multi-storey) Node tree.

    Equal iff two trees have the same per-storey tree shape, cut orientations and
    leaf types — independent of division ratios, heights and other geometry. Used
    as the niching key in :func:`homemaker_layout.driver.search`.
    """
    g = encode(root)
    return _gnode_sig(g.base) + "||" + "||".join(_delta_sig(d) for d in g.deltas)


# --------------------------------------------------------------------------- #
# decode: Genome -> Node tree
# --------------------------------------------------------------------------- #
def _node_from(g: GNode) -> dom.Node:
    n = dom.Node(type=g.type, rotation=g.rotation)
    if g.divided:
        n.division = [g.division[0], g.division[1]]
        n.left = _node_from(g.left)
        n.right = _node_from(g.right)
    return n


def _copy_storey(below: dom.Node) -> dom.Node:
    """Structural copy of the storey below — the canonical inherited state.

    Dead fields (rotation, inherited-cut division, internal type) are synced
    from the owning node below rather than preserved, see module docstring.
    """
    n = dom.Node(type=below.type, rotation=below.rotation)
    if below.divided:
        n.division = list(below.division)
        n.left = _copy_storey(below.left)
        n.right = _copy_storey(below.right)
    return n


def decode(genome: Genome) -> dom.Node:
    from . import geometry  # local import mirrors dom.load (avoids cycle)

    base = _node_from(genome.base)
    for k, v in genome.base_meta.items():
        setattr(base, k, copy.deepcopy(v))
    prev = base
    for delta in genome.deltas:
        lvl = _copy_storey(prev)
        for path in delta.undivides:
            n = lvl.by_id(path)
            n.division = None
            n.left = n.right = None
            n.type = None  # retypes always carries the merged leaf's type
        for path, sub in delta.divides.items():
            n = lvl.by_id(path)
            grafted = _node_from(sub)
            n.division, n.left, n.right = grafted.division, grafted.left, grafted.right
            n.type = grafted.type
        for path, t in delta.retypes.items():
            lvl.by_id(path).type = t
        lvl.height = delta.height
        prev.above = lvl
        prev = lvl
    dom._link(base)
    geometry.clear_cache()
    return base
