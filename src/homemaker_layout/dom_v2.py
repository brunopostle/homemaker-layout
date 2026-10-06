"""`.dom` format version 2 -- the rectangle frame (docs/dom-format-v2.md).

Stage 1a of the rectangle-frame pivot (`homemaker-py-8b2u.2`): the FILE changes,
the in-memory model does not. A v2 document is read into the same ``Node`` tree
a v1 file produces, with the ``rotation`` and ``division`` that make
``geometry`` draw the cuts the file describes, so the scorer and the search are
untouched and every layout keeps its cells.

The two directions:

* :func:`to_document` -- the forward map of ``experiments/diag_8b2u_rect_frame.py``
  (DESIGN.md §39.88, 2,577 of 2,577 cells): each cut, as ``geometry`` computes
  it, becomes an axis and a position in its parent RECTANGLE.
  A LEAF's ``rotation`` is not written: it only says which corner is called 0,
  and since §39.95 nothing scored reads that.
* :func:`from_document` -- the reverse. A v1 node does not store a line; it
  stores which pair of its quad's edges a cut joins (``rotation``) and how far
  along the first (``division[0]``). So each cut is fitted: the rotation whose
  edges the line crosses, and the ratio that puts end 'a' on it.

Three things v2 can say that the v1 tree cannot hold, each REFUSED here rather
than approximated -- they wait for native rectangle geometry (`8b2u.4`):

* a plot that is not a quad, or a ``frame.u`` other than the one ``geometry``
  derives from the plot's longest edge;
* a cut that misses its cropped cell (the cell would crop to nothing);
* an upper-storey cut across a path whose orientation a storey below has
  already fixed the other way. ``geometry`` reads a node's rotation from the
  bottom of its ``below`` chain, so that field is not the upper storey's to set
  (CLAUDE.md, "a multi-storey trace is not a stack of independent storeys").

v2 is the ORTHOGONAL convention written down, so both directions need
``geometry.ORTHOGONAL_DIVISION`` on and say so when it is off. Turning it on
from here would silently change what every v1 file loaded afterwards means.
"""

from __future__ import annotations

from .dom import Node, levels

FORMAT = "homemaker-dom"
VERSION = 2

AXIAL_TOL = 1e-7     # |sin| of a cut's angle to its axis (as §39.88's experiment 1)
FRAME_TOL = 1e-6     # a stored frame.u against the derived one
EDGE_EPS = 1e-12     # a cut must cross the INTERIOR of the edges it joins
AT_DIGITS = 10       # decimal places of `at` on write
CHECK_TOL = 1e-9     # reader self-check: a rebuilt cut against the file's `at`


class DomFormatError(ValueError):
    """The file is not a `.dom` this reader understands, or it is a v2 document
    the v1 in-memory tree cannot hold. Never a guess at what it meant."""


# --------------------------------------------------------------------------- #
# shared geometry helpers
# --------------------------------------------------------------------------- #
def _geometry():
    from . import geometry  # dom <- geometry <- dom_v2: import late, as dom.load does

    return geometry


def _need_orthogonal(what: str) -> None:
    if not _geometry().ORTHOGONAL_DIVISION:
        raise DomFormatError(
            f"{what}: format v2 describes orthogonal division, and "
            "geometry.ORTHOGONAL_DIVISION is off. Set "
            "HOMEMAKER_ORTHOGONAL_DIVISION=1 (it is not switched on for you: "
            "that would change what every v1 file loaded afterwards means).")


def _dot(p, ax) -> float:
    return p[0] * ax[0] + p[1] * ax[1]


def _frame(root: Node):
    """``(u, v, [u0, u1, v0, v1])``: the plot's axes and its bounding rectangle
    in them, after the wall inset. Derived, never stored (the spec's reason: it
    must always enclose the plot exactly)."""
    g = _geometry()
    u, v = g._reference_axes(root)
    pu = [_dot(p, u) for p in root.node]
    pv = [_dot(p, v) for p in root.node]
    return u, v, [min(pu), max(pu), min(pv), max(pv)]


def _split(rect, k: int, s: float):
    """The low and high halves of ``rect`` cut at ``s`` on coordinate ``k``
    (0 = u, 1 = v)."""
    low, high = list(rect), list(rect)
    if k:
        low[3] = high[2] = s
    else:
        low[1] = high[0] = s
    return low, high


def _cut_of(n: Node, u, v):
    """``(k, s, left_is_low)`` of the cut ``geometry`` draws across ``n``, or
    None where that cut is not axial."""
    g = _geometry()
    a, b = g.coord_a(n), g.coord_b(n)
    d = (b[0] - a[0], b[1] - a[1])
    length = (d[0] * d[0] + d[1] * d[1]) ** 0.5 or 1.0
    along_u = abs(_dot(d, v)) / length <= AXIAL_TOL
    along_v = abs(_dot(d, u)) / length <= AXIAL_TOL
    if not (along_u or along_v):
        return None
    k = 1 if along_u else 0              # a cut ALONG u fixes v
    ax = v if k else u
    s = _dot(a, ax)
    return k, s, _dot(g.coordinate(n, 0), ax) < s


# --------------------------------------------------------------------------- #
# Node tree -> v2 document
# --------------------------------------------------------------------------- #
def to_document(root: Node) -> dict:
    """The v2 document for a linked ``Node`` tree. Raises :class:`DomFormatError`
    for a tree v2 cannot express (a skew cut)."""
    if root.plot is not None:
        return _native_to_document(root)
    _need_orthogonal("writing v2")
    g = _geometry()
    g.clear_cache()
    u, v, box = _frame(root)

    def emit(n: Node, rect, where: str) -> dict:
        if not n.divided:
            d: dict = {"cell": n.type}
            if n.share > 1 and n.share_type == n.type:
                d["share"] = n.share
            if n.co_type:
                d["co_type"] = n.co_type
            return d
        cut = _cut_of(n, u, v)
        if cut is None:
            raise DomFormatError(
                f"{where or 'root'}: this cut is not parallel to a plot axis, "
                "so a rectangle frame cannot express it (format v2 holds "
                "orthogonal designs only)")
        k, s, left_low = cut
        lo, hi = (rect[2], rect[3]) if k else (rect[0], rect[1])
        low, high = _split(rect, k, s)
        d = {}
        if not (n.below is not None and n.below.divided):
            # an inherited cut is the storey below's to state, not this one's
            d["cut"] = "u" if k else "v"
            # Rounded so that load -> dump reproduces the file: the position is
            # recomputed from geometry on every write and comes back a few ulps
            # away. 1e-10 of a plot is nanometres.
            d["at"] = round((s - lo) / (hi - lo), AT_DIGITS)
        lchild = emit(n.left, low if left_low else high, where + "l")
        rchild = emit(n.right, high if left_low else low, where + "r")
        d["low"], d["high"] = (lchild, rchild) if left_low else (rchild, lchild)
        return d

    lvls = levels(root)
    per = root.perimeter
    doc: dict = {"format": FORMAT, "version": VERSION,
                 "frame": {"u": [u[0], u[1]]},
                 "plot": [list(p) for p in (root.node_file or g.offset_quad(
                     root.node, root.wall_outer or 0.25))]}
    if per is not None:
        doc["perimeter"] = [per.get(e) for e in "abcd"]
    for key in ("wall_inner", "wall_outer"):
        if getattr(root, key) is not None:
            doc[key] = getattr(root, key)
    doc["storeys"] = []
    for i, lvl in enumerate(lvls):
        storey: dict = {}
        for key in ("elevation", "height"):
            if getattr(lvl, key) is not None:
                storey[key] = getattr(lvl, key)
        storey["tree"] = emit(lvl, box, f"storey {i} ")
        doc["storeys"].append(storey)
    if root.meta:
        doc["meta"] = dict(root.meta)
    return doc


# --------------------------------------------------------------------------- #
# v2 document -> Node tree
# --------------------------------------------------------------------------- #
def _check_header(doc: dict) -> None:
    if doc.get("format") != FORMAT:
        raise DomFormatError(f"not a {FORMAT} file: format is {doc.get('format')!r}")
    version = doc.get("version")
    if version != VERSION or isinstance(version, bool):
        raise DomFormatError(
            f"{FORMAT} version {version!r} is not one this reader knows "
            f"(it reads version {VERSION}, and v1 files, which have no "
            "`format` key)")
    if "blocks" in doc:
        raise DomFormatError(
            "`blocks` (pre-placed rectangles) is reserved for a later stage "
            "and this reader does not implement it")
    for key in ("frame", "plot", "storeys"):
        if key not in doc:
            raise DomFormatError(f"v2 file has no `{key}`")
    if not doc["storeys"]:
        raise DomFormatError("v2 file has no storeys")


def _fit(corners, k: int, s: float, u, v):
    """The rotations under which a v1 node with these UNROTATED corners draws
    the line ``coordinate k == s``: ``[(rotation, ratio, left_is_low), ...]``.

    A v1 cut runs from edge(0,1) to edge(3,2) of the rotated quad, and
    ``geometry._orthogonal_b`` picks its axis from the mean direction of the
    other two edges -- so a rotation fits only if the line crosses the interior
    of both edges AND that rule would pick this line's axis."""
    ax, along = (v, u) if k else (u, v)
    out = []
    for r in range(4):
        c = [corners[(i + r) % 4] for i in range(4)]
        w = [_dot(p, ax) for p in c]
        if abs(w[1] - w[0]) < EDGE_EPS or abs(w[2] - w[3]) < EDGE_EPS:
            continue
        t0 = (s - w[0]) / (w[1] - w[0])
        t1 = (s - w[3]) / (w[2] - w[3])
        if not (EDGE_EPS < t0 < 1 - EDGE_EPS and EDGE_EPS < t1 < 1 - EDGE_EPS):
            continue
        g = _geometry()
        e1 = g._unit(c[2][0] - c[1][0], c[2][1] - c[1][1])
        e2 = g._unit(c[3][0] - c[0][0], c[3][1] - c[0][1])
        mean = g._unit((e1[0] + e2[0]) / 2.0, (e1[1] + e2[1]) / 2.0)
        picks_u = abs(_dot(mean, u)) >= abs(_dot(mean, v))
        if picks_u != (along is u):
            continue
        out.append((r, t0, w[0] < s))
    return out


def _unrotated(base: Node):
    """Corners of ``base`` as they would be with ``rotation == 0``."""
    g = _geometry()
    p = base.parent
    if p is None:
        return [list(q) for q in base.node]
    if base.position == "l":
        return [g.coordinate(p, 0), g.coord_a(p), g.coord_b(p), g.coordinate(p, 3)]
    return [g.coord_a(p), g.coordinate(p, 1), g.coordinate(p, 2), g.coord_b(p)]


def _leaf_spec(n: Node) -> dict:
    d: dict = {"cell": n.type}
    if n.share > 1 and n.share_type == n.type:
        d["share"] = n.share
    if n.co_type:
        d["co_type"] = n.co_type
    return d


def _native_to_document(root: Node) -> dict:
    """A native tree written back: it already holds what the file says."""
    def emit(n: Node) -> dict:
        if not n.divided:
            return _leaf_spec(n)
        d: dict = {}
        if not (n.below is not None and n.below.divided):
            d["cut"], d["at"] = n.cut, n.at
        d["low"], d["high"] = emit(n.left), emit(n.right)
        return d

    doc: dict = {"format": FORMAT, "version": VERSION,
                 "frame": {"u": list(root.frame_u)},
                 "plot": [list(p) for p in root.plot]}
    if root.perimeter is not None:
        doc["perimeter"] = [root.perimeter.get(f"#{k}") for k in range(len(root.plot))]
    for key in ("wall_inner", "wall_outer"):
        if getattr(root, key) is not None:
            doc[key] = getattr(root, key)
    doc["storeys"] = []
    for lvl in levels(root):
        storey: dict = {}
        for key in ("elevation", "height"):
            if getattr(lvl, key) is not None:
                storey[key] = getattr(lvl, key)
        storey["tree"] = emit(lvl)
        doc["storeys"].append(storey)
    if root.meta:
        doc["meta"] = dict(root.meta)
    return doc


def _native_from_document(doc: dict) -> Node:
    """A NATIVE tree for a parsed v2 document: the cuts as the file states
    them, drawn by ``geometry`` as rectangles cropped to the plot. Nothing is
    fitted and nothing v2 can say is refused -- a plot of any shape, a frame of
    the file's own, cells that crop to wedges or to nothing. The orthogonal-
    division switch is not consulted: a native tree has no other geometry.
    """
    from . import cells, dom
    g = _geometry()

    plot = [[float(p[0]), float(p[1])] for p in doc["plot"]]
    if len(plot) < 3:
        raise DomFormatError("a plot needs at least three vertices")
    if cells._signed_area(plot) <= 0:
        raise DomFormatError("the plot must be listed anticlockwise")
    fu = doc["frame"].get("u")
    if fu is None or (float(fu[0]) == 0.0 and float(fu[1]) == 0.0):
        raise DomFormatError("v2 file has no usable frame.u")
    wall_outer = float(doc["wall_outer"]) if doc.get("wall_outer") is not None else 0.25
    wall_inner = float(doc["wall_inner"]) if doc.get("wall_inner") is not None else 0.08
    perimeter = None
    if doc.get("perimeter") is not None:
        if len(doc["perimeter"]) != len(plot):
            raise DomFormatError("`perimeter` must have one entry per plot edge")
        perimeter = {f"#{k}": status for k, status in enumerate(doc["perimeter"])}

    roots: list[Node] = []
    for i, storey in enumerate(doc["storeys"]):
        if "tree" not in storey:
            raise DomFormatError(f"storey {i} has no `tree`")
        below_root = roots[-1] if roots else None

        def build(spec, path: str, i=i, below_root=below_root) -> Node:
            where = f"storey {i} {path or 'root'}"
            if not isinstance(spec, dict):
                raise DomFormatError(f"{where}: a node must be a mapping")
            n = Node()
            if "cell" in spec:
                n.type = None if spec["cell"] is None else str(spec["cell"])
                if spec.get("share") is not None:
                    n.share, n.share_type = int(spec["share"]), n.type
                if spec.get("co_type") is not None:
                    n.co_type = str(spec["co_type"])
                return n
            if "low" not in spec or "high" not in spec:
                raise DomFormatError(f"{where}: a node is a `cell` or has `low` and `high`")
            under = below_root.by_id(path) if below_root is not None else None
            if under is not None and under.divided:
                if "cut" in spec or "at" in spec:
                    raise DomFormatError(
                        f"{where}: the storey below is cut here, so this storey "
                        "inherits that cut and must not write `cut`/`at` of its own")
                n.cut, n.at = under.cut, under.at
            else:
                if spec.get("cut") not in ("u", "v") or "at" not in spec:
                    raise DomFormatError(f"{where}: a cut needs `cut: u|v` and `at`")
                n.cut, n.at = spec["cut"], float(spec["at"])
                if not 0.0 < n.at < 1.0:
                    raise DomFormatError(f"{where}: `at` is {n.at}, outside (0, 1)")
            n.division = [n.at, n.at]
            n.left, n.right = build(spec["low"], path + "l"), build(spec["high"], path + "r")
            return n

        lvl = build(storey["tree"], "")
        lvl.wall_inner, lvl.wall_outer = wall_inner, wall_outer
        for key in ("elevation", "height"):
            if storey.get(key) is not None:
                setattr(lvl, key, float(storey[key]))
        if roots:
            roots[-1].above = lvl
        roots.append(lvl)
    root = roots[0]
    root.plot, root.frame_u = plot, [float(fu[0]), float(fu[1])]
    root.perimeter = perimeter
    if doc.get("meta") is not None:
        root.meta = dict(doc["meta"])
    dom.link(root)
    g.clear_cache()
    g.mark_voids(root)
    return root


def to_native(root: Node) -> Node:
    """A quad tree (orthogonal) re-made as a native one: the same building."""
    return _native_from_document(to_document(root))


def from_document(doc: dict, native: bool = False) -> Node:
    """The linked ``Node`` tree for a parsed v2 document (wall inset applied, as
    :func:`dom.load` does for v1). ``native=True`` builds a native tree
    (:func:`_native_from_document`); the default fits the quad tree every older
    tool works on, and refuses what that tree cannot hold."""
    _check_header(doc)
    if native:
        return _native_from_document(doc)
    _need_orthogonal("reading v2")
    g = _geometry()

    plot = [[float(p[0]), float(p[1])] for p in doc["plot"]]
    if len(plot) != 4:
        raise DomFormatError(
            f"the plot has {len(plot)} vertices; until native rectangle "
            "geometry (homemaker-py-8b2u.4) only a four-cornered plot can be "
            "read")
    wall_outer = float(doc["wall_outer"]) if doc.get("wall_outer") is not None else 0.25
    wall_inner = float(doc["wall_inner"]) if doc.get("wall_inner") is not None else 0.08
    perimeter = None
    if doc.get("perimeter") is not None:
        if len(doc["perimeter"]) != len(plot):
            raise DomFormatError("`perimeter` must have one entry per plot edge")
        perimeter = dict(zip("abcd", doc["perimeter"]))

    roots: list[Node] = []
    for i, storey in enumerate(doc["storeys"]):
        lvl = Node(wall_inner=wall_inner, wall_outer=wall_outer)
        for key in ("elevation", "height"):
            if storey.get(key) is not None:
                setattr(lvl, key, float(storey[key]))
        if roots:
            roots[-1].above = lvl
            lvl.below = roots[-1]
        roots.append(lvl)
    root = roots[0]
    root.node_file = [list(p) for p in plot]
    root.node = g.offset_quad(plot, -wall_outer)
    root.perimeter = perimeter
    if doc.get("meta") is not None:
        root.meta = dict(doc["meta"])

    g.clear_cache()
    u, v, box = _frame(root)
    want = doc["frame"].get("u")
    if want is None or abs(float(want[0]) - u[0]) > FRAME_TOL \
            or abs(float(want[1]) - u[1]) > FRAME_TOL:
        raise DomFormatError(
            f"frame.u is {want}, but the plot's longest edge gives "
            f"[{u[0]:.9g}, {u[1]:.9g}]; a frame that differs from the derived "
            "one needs native rectangle geometry (homemaker-py-8b2u.4)")

    # what each divided node was built from, for the storeys above it:
    # id(node) -> (k, s, left_is_low)
    cuts: dict[int, tuple] = {}
    pinned: set[int] = set()        # nodes whose rotation a cut already relies on

    def build(spec, n: Node, rect, below_root, where: str) -> None:
        if not isinstance(spec, dict):
            raise DomFormatError(f"{where}: a node must be a mapping")
        if "cell" in spec:
            n.type = None if spec["cell"] is None else str(spec["cell"])
            if spec.get("share") is not None:
                n.share, n.share_type = int(spec["share"]), n.type
            if spec.get("co_type") is not None:
                n.co_type = str(spec["co_type"])
            return
        if "low" not in spec or "high" not in spec:
            raise DomFormatError(f"{where}: a node is a `cell` or has `low` and `high`")
        base = n
        while base.below is not None:
            base = base.below
        if n.below is not None and n.below.divided:
            if "cut" in spec or "at" in spec:
                raise DomFormatError(
                    f"{where}: the storey below is cut here, so this storey "
                    "inherits that cut and must not write `cut`/`at` of its own")
            k, s, left_low = cuts[id(n.below)]
            n.division = list(n.below.division)
        else:
            if spec.get("cut") not in ("u", "v") or "at" not in spec:
                raise DomFormatError(f"{where}: a cut needs `cut: u|v` and `at`")
            at = float(spec["at"])
            if not 0.0 < at < 1.0:
                raise DomFormatError(f"{where}: `at` is {at}, outside (0, 1)")
            k = 1 if spec["cut"] == "u" else 0
            lo, hi = (rect[2], rect[3]) if k else (rect[0], rect[1])
            s = lo + at * (hi - lo)
            fits = _fit(_unrotated(base), k, s, u, v)
            if id(base) in pinned or base.divided:
                # the orientation here is already spoken for, by a storey below
                fits = [f for f in fits if f[0] == base.rotation]
                why = ("a storey below has fixed this cell's orientation the "
                       "other way, and the v1 tree reads it from there")
            else:
                why = ("the line misses this cell once it is cropped to the "
                       "plot, which needs native rectangle geometry "
                       "(homemaker-py-8b2u.4)")
            if not fits:
                raise DomFormatError(f"{where}: cut {spec['cut']} at {at} cannot "
                                     f"be held in the v1 tree: {why}")
            # left = low where there is a choice, so ids read the same way round
            r, t0, left_low = sorted(fits, key=lambda f: (not f[2], f[0]))[0]
            base.rotation = r
            pinned.add(id(base))
            n.division = [t0, t0]
        n.rotation = base.rotation
        cuts[id(n)] = (k, s, left_low)
        n.left, n.right = Node(), Node()
        for child, pos in ((n.left, "l"), (n.right, "r")):
            child.parent, child.position = n, pos
            child.below = below_root.by_id(child.id) if below_root is not None else None
        g.clear_cache()             # a rotation may have moved under cached corners
        low, high = _split(rect, k, s)
        build(spec["low"], n.left if left_low else n.right, low, below_root,
              where + ("l" if left_low else "r"))
        build(spec["high"], n.right if left_low else n.left, high, below_root,
              where + ("r" if left_low else "l"))

    for i, storey in enumerate(doc["storeys"]):
        if "tree" not in storey:
            raise DomFormatError(f"storey {i} has no `tree`")
        build(storey["tree"], roots[i], box, roots[i - 1] if i else None,
              f"storey {i} ")

    from .dom import link

    link(root)
    g.clear_cache()
    _self_check(root, cuts, u, v)
    g.clear_cache()
    return root


def _self_check(root: Node, cuts: dict, u, v) -> None:
    """Every cut ``geometry`` now draws must be the line the file asked for.
    The fit above reasons about one node at a time; this asks the engine."""
    for i, lvl in enumerate(levels(root)):
        stack = [lvl]
        while stack:
            n = stack.pop()
            if not n.divided:
                continue
            got = _cut_of(n, u, v)
            k, s, left_low = cuts[id(n)]
            if got is None or got[0] != k or abs(got[1] - s) > CHECK_TOL \
                    or got[2] != left_low:
                raise DomFormatError(
                    f"storey {i} {n.id or 'root'}: the tree built from this "
                    f"file does not draw the cut it describes (wanted "
                    f"{'uv'[1 - k]} at {s:.9g}, geometry gives {got})")
            stack += [n.left, n.right]
