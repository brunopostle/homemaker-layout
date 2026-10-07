"""`homemaker-dom-upgrade`: convert a `.dom` between format v1 and v2, VERIFIED.

    homemaker-dom-upgrade coldstart-1a24b6a+orth-500000-s0.dom   # -> ....v2.dom
    homemaker-dom-upgrade --orthogonal working.dom
    homemaker-dom-upgrade --to-v1 design.v2.dom                 # -> ....v1.dom

v1 -> v2 (`docs/dom-format-v2.md`, Migration). A v1 file does not say whether
it was made with orthogonal division, and it is a different building either
way, so the convention comes from `--orthogonal` or from a `+orth` objective
stamp in the file's name; with neither the file is refused. Only orthogonal
designs have a v2 form at all.

v2 -> v1 (`--to-v1`) exists so Urb's Perl tools keep working on a converted
design. It can only express what the v1 tree holds -- which, while the reader
is stage 1a, is everything the reader accepts.

Either way the converted text is read back and every cell compared with the
original's before anything is written, and the input is never overwritten:
committed artefacts are records (decision 4), and a results table names the
file that was scored.
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from . import dom, dom_v2, geometry

CELL_TOL = 1e-6      # metres, corner to corner


class ConvertError(ValueError):
    """Nothing was written, and this says why."""


def _cells(root: dom.Node) -> list:
    """(storey, type, live share, corners) for every leaf."""
    out = []
    for li, lvl in enumerate(dom.levels(root)):
        for leaf in lvl.leaves():
            share = leaf.share if leaf.share_type == leaf.type else 1
            out.append((li, leaf.type, share, leaf.co_type,
                        [geometry.coordinate(leaf, i) for i in range(4)]))
    return out


def _same_corners(a: list, b: list) -> bool:
    """The same set of corner points, whichever is called corner 0."""
    return (all(min(math.dist(p, q) for q in b) <= CELL_TOL for p in a)
            and all(min(math.dist(p, q) for q in a) <= CELL_TOL for p in b))


def unmatched_cells(a: dom.Node, b: dom.Node) -> int:
    """How many cells of `a` and `b` have no partner in the other: same storey,
    type, share and corners. Leaf NAMES are not compared -- a v2 round trip may
    swap which child is called `l`."""
    rest, missing = _cells(b), 0
    for li, ty, share, co, corners in _cells(a):
        hit = next((x for x in rest if x[:4] == (li, ty, share, co)
                    and _same_corners(x[4], corners)), None)
        if hit is None:
            missing += 1
        else:
            rest.remove(hit)
    return missing + len(rest)


def _plain(root: dom.Node) -> dict:
    """The fields a conversion must also carry that are not cells."""
    return {"perimeter": root.perimeter, "plot": root.node_file,
            "walls": (root.wall_inner, root.wall_outer),
            "storeys": [(lvl.elevation, lvl.height) for lvl in dom.levels(root)]}


def convert(path: Path, to_v1: bool = False, orthogonal: bool = False) -> str:
    """The converted text for `path`, verified. Raises :class:`ConvertError`."""
    with open(path) as fh:
        head = yaml.safe_load(fh)
    is_v2 = isinstance(head, dict) and "format" in head
    if to_v1 and not is_v2:
        raise ConvertError("already format v1")
    if not to_v1:
        if is_v2:
            raise ConvertError("already format v2")
        if not (orthogonal or "+orth" in path.name):
            raise ConvertError(
                "a v1 file does not record whether it was made with orthogonal "
                "division, and its name carries no +orth stamp. Pass "
                "--orthogonal if it was; a non-orthogonal design has no v2 form")
    # v2 IS the orthogonal convention, and so is the v1 file being upgraded.
    was, geometry.ORTHOGONAL_DIVISION = geometry.ORTHOGONAL_DIVISION, True
    try:
        try:
            source = dom.load(str(path))
            if to_v1:
                text = dom.dumps(source, version=1)
                back = dom._parse(yaml.safe_load(text))
                dom.link(back)
                back.node_file = [list(p) for p in back.node]
                back.node = geometry.offset_quad(back.node, -(back.wall_outer or 0.25))
                geometry.clear_cache()
            else:
                source.meta = {**(source.meta or {}), "converted_from": path.name}
                text = dom.dumps(source, version=2)
                back = dom_v2.from_document(yaml.safe_load(text))
        except dom_v2.DomFormatError as e:
            raise ConvertError(str(e)) from e
        bad = unmatched_cells(source, back)
        if bad:
            raise ConvertError(
                f"verification failed: {bad} cell(s) of the converted file do "
                "not match the original's")
        if _plain(source) != _plain(back):
            raise ConvertError("verification failed: plot, perimeter, walls or "
                               "storey heights changed in conversion")
        return text
    finally:
        geometry.ORTHOGONAL_DIVISION = was
        geometry.clear_cache()


def output_path(path: Path, to_v1: bool) -> Path:
    tag = "v1" if to_v1 else "v2"
    stem = path.name[:-len(".dom")] if path.name.endswith(".dom") else path.name
    for other in (".v1", ".v2"):
        if stem.endswith(other):
            stem = stem[:-len(other)]
    return path.with_name(f"{stem}.{tag}.dom")


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="homemaker-dom-upgrade",
        description="Convert .dom files from format v1 to v2 (or back with "
                    "--to-v1), verifying every cell. Writes <name>.v2.dom beside "
                    "each input and never overwrites the input.")
    ap.add_argument("dom", nargs="+")
    ap.add_argument("--orthogonal", action="store_true",
                    help="the v1 input was made with orthogonal division (a v1 "
                         "file does not say; a +orth stamp in its name is taken "
                         "as saying so)")
    ap.add_argument("--to-v1", action="store_true",
                    help="convert v2 to v1 instead, for Urb's tools")
    ap.add_argument("-o", "--output",
                    help="write here instead (one input only)")
    ap.add_argument("--force", action="store_true",
                    help="replace an existing OUTPUT file")
    args = ap.parse_args(argv)
    if args.output and len(args.dom) != 1:
        ap.error("--output takes exactly one input")
    rc = 0
    for name in args.dom:
        path = Path(name)
        out = Path(args.output) if args.output else output_path(path, args.to_v1)
        try:
            if out.resolve() == path.resolve():
                raise ConvertError("the output would overwrite the input")
            if out.exists() and not args.force:
                raise ConvertError(f"{out.name} exists (use --force)")
            text = convert(path, args.to_v1, args.orthogonal)
        except (ConvertError, OSError) as e:
            print(f"{name}: NOT WRITTEN: {e}")
            rc = 1
            continue
        out.write_text(text)
        print(f"{name}: verified -> {out}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
