"""homemaker-compose -- SVG trace + boundary .dom -> full slicing-tree .dom
(homemaker-py-2g7.1). See DESIGN.md sec 37.x for the trace format.

Usage:
  homemaker-compose plan.svg boundary.dom -o out.dom [--tol 0.15] [--refine]
"""

from __future__ import annotations

import argparse
import os
import sys

from . import dom as dom_mod
from .compose import LabelError, NonSlicible, compose, parse_svg, refine


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="homemaker-compose")
    ap.add_argument("svg")
    ap.add_argument("boundary_dom")
    ap.add_argument("-o", "--output")
    ap.add_argument("--tol", type=float, default=0.15, help="cut/edge snapping tolerance")
    ap.add_argument("--scale", type=float, default=1.0, help="SVG user-unit -> plan-unit scale")
    ap.add_argument(
        "--refine",
        action="store_true",
        help="solve division ratios against patterns.config next to the boundary dom",
    )
    args = ap.parse_args(argv)

    boundary = dom_mod.load(args.boundary_dom)
    storeys = parse_svg(args.svg, scale=args.scale)
    try:
        root = compose(boundary, storeys, tol=args.tol)
    except (NonSlicible, LabelError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.refine:
        refine(root, os.path.dirname(os.path.abspath(args.boundary_dom)))

    out_path = args.output or (args.svg.rsplit(".", 1)[0] + ".dom")
    dom_mod.dump(root, out_path)
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
