"""Export a layout as a homemaker-addon *rooms document* (`docs/rooms-format.md`).

The rooms document is homemaker-addon's web-editor format: one convex plan
polygon per room with an elevation, a height, a style per face and a usage.
The web editor loads it, and `geometry_adapter.rooms_to_faces_and_widgets()`
turns it into the faces and widgets `Molior.from_faces_and_widgets()` builds
an IFC building from. This replaces Urb's `urb-dom2molior.pl` (owner,
2026-10-05: target homemaker-addon directly, through a debuggable file).

Each room also carries `dom_id` (storey / id path) and `code` (the programme
room code) so a face in the IFC traces back to the cell that made it. Both
consumers ignore keys they do not declare.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from . import dom, geometry, operators
from .fitness import load_config
from .programme import load_programme_dir

FORMAT = "homemaker-rooms"
VERSION = 1

# This repo's `usage:` classes -> homemaker-addon room types (docs/rooms-format.md).
# `none` -> `void` and the new `utility` usage are the owner's rulings, 2026-10-05.
USAGE_MAP = {
    "bedroom": "bedroom",
    "kitchen": "kitchen",
    "living": "living",
    "toilet": "toilet",
    "none": "void",
    "utility": "utility",
}


class ExportError(ValueError):
    """The layout cannot be written as a rooms document without losing something."""


def _ccw(poly: list) -> list:
    """The polygon and its edge order, counter-clockwise. Returns (poly, flipped)."""
    s = sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
            - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))
    return (poly, False) if s > 0 else (list(reversed(poly)), True)


def _convex(poly: list) -> bool:
    sign = 0
    n = len(poly)
    for i in range(n):
        a, b, c = poly[i], poly[(i + 1) % n], poly[(i + 2) % n]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) < 1e-10:
            continue
        s = 1 if cross > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def _storey_heights(root) -> list:
    """(elevation, height) per storey, lowest first. A storey that does not
    state its elevation sits on top of the one below."""
    out, z = [], None
    for lvl in dom.levels(root):
        h = lvl.height if lvl.height is not None else 3.0
        e = lvl.elevation if lvl.elevation is not None else (z if z is not None else 0.0)
        out.append((e, h))
        z = e + h
    return out


def _usage(leaf, reqs: dict, stair_ids: set) -> "str | None":
    """The homemaker-addon usage for a leaf, or None for a cell that is not a room."""
    t = leaf.type
    if t == "C":
        # `stair`, not `circulation_stair`: every stair behaviour in
        # homemaker-addon (molior/floor.py, shell.py, topologist/graph.py) tests
        # usage == "stair"; `circulation_stair` only appears in its widget-name
        # list. Exported as `circulation_stair`, a shaft built no staircase.
        return "stair" if leaf.id in stair_ids else "circulation"
    if t in ("O", "S"):
        if not dom.is_covered(leaf):
            return None          # a terrace or yard: the roof of what is below, not a room
        return "outside" if t == "O" else "sahn"
    req = reqs.get(t)
    if req is None:
        raise ExportError(f"cell {leaf.id or 'root'} has type {t!r}, which the "
                          "programme does not declare")
    usage = USAGE_MAP.get(req.usage)
    if usage is None:
        raise ExportError(f"room code {t!r} has usage {req.usage!r}, which has no "
                          "homemaker-addon counterpart (docs/rooms-format.md)")
    return usage


def rooms(root, programme_dir) -> list:
    """The rooms of `root`, a loaded and linked `.dom`, as plain dicts."""
    conf, _ = load_config(str(programme_dir))
    reqs = load_programme_dir(str(programme_dir))
    root = copy.deepcopy(root)
    dom.link(root)
    # Exactly the merge the scorer applies before it reads anything: adjacent
    # OUTDOOR siblings (O/S) fuse into one leaf. Room leaves are never merged --
    # the scorer counts room instances per leaf, so two adjacent same-code
    # leaves are two rooms to it, and are two rooms here.
    dom.merge_divided(root, allow_sahn=bool(conf.get("allow_sahn_circulation")))
    dom.link(root)
    geometry.clear_cache()
    lvls = dom.levels(root)
    stair_ids = set(operators._shaft_paths(lvls))
    perimeter = root.perimeter or {}
    # Write in the FRAME's coordinates (u along x, v along y), not the world's.
    # homemaker-addon snaps every vertex to 1 mm; on a plot whose axes are skew
    # to the world, that knocks a T-junction's corner a hair off the wall it
    # sits on, Topologic makes a sliver cell of the gap, and ApplyDictionary
    # stalls on it -- programme-house s0, 75 deg skew: 12 cells from 11 rooms and
    # a build that never finished, against 11 cells and 7 s in the frame. In the
    # frame every interior wall is axial, so snapping cannot move a point off one.
    u, v = geometry._reference_axes(lvls[0])
    out = []
    for li, (lvl, (elev, height)) in enumerate(zip(lvls, _storey_heights(root))):
        for leaf in lvl.leaves():
            if not leaf.type:
                continue
            usage = _usage(leaf, reqs, stair_ids)
            if usage is None:
                continue
            corners = [[x * u[0] + y * u[1], x * v[0] + y * v[1]]
                       for x, y in (geometry.coordinate(leaf, i) for i in range(4))]
            walls = ["blank" if perimeter.get(geometry.boundary_id(leaf, i)) == "private"
                     else "default" for i in range(4)]
            poly, flipped = _ccw(corners)
            if flipped:
                # reversing the vertices reverses the edges: edge i of the reversed
                # polygon is edge (2 - i) mod 4 of the original
                walls = [walls[(2 - i) % 4] for i in range(4)]
            if not _convex(poly):
                raise ExportError(f"cell {li}/{leaf.id} is not convex")
            out.append({
                # To a tenth of a micron, not a tenth of a millimetre: three
                # rooms' corners along one skew plot side are collinear, and
                # rounded to 1e-4 they are not. A roof face over that side has
                # all of them on its eave, and homemaker-addon refuses a face
                # whose corners are more than a micron off one plane; the
                # alternative, a roof plane per kink, makes features smaller
                # than the 0.1 mm the addon merges at, and its cell complex
                # then fails to build (harbor-house did).
                "vertices": [[round(x, 7), round(y, 7)] for x, y in poly],
                "elevation": round(elev, 4),
                "height": round(height, 4),
                "stylename": "default",
                "face_styles": ["default", "default"] + walls,
                "usage": usage,
                "dom_id": f"{li}/{leaf.id}",
                "code": leaf.type,
                # nothing is built over the top storey: these are the rooms a
                # pitched roof goes on (`roofs.for_rooms`). A room lower down
                # with open air over it carries a terrace, which is flat.
                "roofed": li == len(lvls) - 1,
            })
    return out


def document(dom_path, programme_dir=None, roof_pitch: "float | None" = 35.0,
             gables: bool = True) -> dict:
    """The rooms document for the `.dom` at `dom_path`.

    With a ``roof_pitch`` (degrees) the top storey gets pitched roofs: sloping
    ``faces`` over each group of rooms, gabled where the group ends on a party
    wall if ``gables``, and a ``void`` widget inside each so the roof space is
    not taken for a room. ``roof_pitch=None`` leaves the roofs flat."""
    dom_path = Path(dom_path)
    programme_dir = Path(programme_dir) if programme_dir else dom_path.parent
    root = dom.load(str(dom_path))
    u, _ = geometry._reference_axes(root)
    made = rooms(root, programme_dir)
    extra: dict = {}
    if roof_pitch is not None:
        from . import roofs

        faces, widgets, notes = roofs.for_rooms(made, roof_pitch, gables)
        if faces:
            extra = {"faces": faces, "widgets": widgets}
        extra["roof"] = {"pitch_degrees": roof_pitch, "gables": gables, "notes": notes}
    doc = {
        "format": FORMAT,
        "version": VERSION,
        "name": f"{programme_dir.name} {dom_path.stem}",
        "meta": {"source": str(dom_path), "programme": programme_dir.name,
                 "orthogonal_division": geometry.ORTHOGONAL_DIVISION,
                 # rooms are in the frame: world = rotate(frame, angle) about the origin
                 "frame": {"u": [round(u[0], 9), round(u[1], 9)],
                           "angle_degrees": round(math.degrees(math.atan2(u[1], u[0])), 6)}},
        "rooms": made,
    }
    if "roof" in extra:
        doc["meta"]["roof"] = extra.pop("roof")
    doc.update(extra)
    return doc


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="homemaker-rooms",
        description="Write a .dom as a homemaker-addon rooms document "
                    "(docs/rooms-format.md), next to it as <file>.rooms.json.")
    ap.add_argument("dom", nargs="+")
    ap.add_argument("--programme", help="programme directory (default: the .dom's own)")
    ap.add_argument("--orthogonal", action="store_true",
                    help="read the .dom with orthogonal division; a v1 file does not "
                         "record it, so +orth artefacts need this (or "
                         "HOMEMAKER_ORTHOGONAL_DIVISION=1)")
    ap.add_argument("--roof-pitch", type=float, default=35.0, metavar="DEGREES",
                    help="pitch of the roofs over the top storey (default 35)")
    ap.add_argument("--flat-roofs", action="store_true",
                    help="write no roof geometry: homemaker-addon then roofs every "
                         "top cell flat")
    ap.add_argument("--no-gables", action="store_true",
                    help="hip every roof all round; by default a roof ends in a "
                         "gable where it meets a party wall, as Urb's did")
    args = ap.parse_args(argv)
    if args.orthogonal:
        geometry.ORTHOGONAL_DIVISION = True
    rc = 0
    for p in args.dom:
        try:
            doc = document(p, args.programme,
                           None if args.flat_roofs else args.roof_pitch,
                           not args.no_gables)
        except ExportError as e:
            print(f"{p}: NOT WRITTEN: {e}")
            rc = 1
            continue
        out = Path(p).with_suffix(Path(p).suffix + ".rooms.json")
        out.write_text(json.dumps(doc, indent=1) + "\n")
        roof = doc["meta"].get("roof") or {}
        print(f"{p}: {len(doc['rooms'])} rooms, {len(doc.get('faces', []))} roof faces "
              f"-> {out}")
        for note in roof.get("notes", []):
            print(f"   roof: {note}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
