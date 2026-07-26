"""homemaker-collapse — finish-time global cell→room collapse on a .dom file.

Relabels a layout's room cells to the programme rooms they fit best via one
optimal assignment (hard level constraint, adjacency relaxation, public-access
pinning — see fitness.Fitness.collapse_global), keeping the result only if the
fail count does not increase. Labels only — geometry is never touched, so
shape-intrinsic fails (long-thin cells, crinkliness) are unaffected by design.

Like homemaker-fitness you MUST cd to the directory holding the .dom so that
patterns.config / costs.config resolve.

Usage (module):
  python -m homemaker_layout.collapse_cmd file.dom [file2.dom ...] [-o OUT.dom]

When installed via pip install -e .:
  homemaker-collapse file.dom [...]

Writes the collapsed layout to <stem>.collapsed.dom (or -o OUT for a single
input; - for stdout) and prints "base → collapsed fails" per file to stderr.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import dom as dom_mod
from .fitness import Fitness, load_config


def _parse_args(argv):
    p = argparse.ArgumentParser(prog="homemaker-collapse", description=__doc__)
    p.add_argument("dom", type=Path, nargs="+", help="input .dom file(s)")
    p.add_argument("-o", "--output", type=Path, default=None, metavar="PATH",
                   help="output path (single input only; - for stdout). Default: "
                        "<stem>.collapsed.dom beside each input")
    p.add_argument("--adjacency", action=argparse.BooleanOptionalAction, default=True,
                   help="enforce required room↔room adjacency (default: on)")
    p.add_argument("--public-access", dest="public_access",
                   action=argparse.BooleanOptionalAction, default=True,
                   help="pin the sole street-access provider (default: on)")
    p.add_argument("--objective", choices=("threshold", "quality"),
                   default="threshold",
                   help="threshold = minimise fail count; quality = maximise "
                        "continuous fit (default: threshold)")
    p.add_argument("--keep-better", dest="keep_better",
                   action=argparse.BooleanOptionalAction, default=True,
                   help="revert if the collapse increases the fail count "
                        "(default: on)")
    p.add_argument("--local-search", dest="local_search",
                   action=argparse.BooleanOptionalAction, default=True,
                   help="2-opt polish past the Jacobi adjacency relaxation "
                        "(homemaker-py-9wi, default: on since homemaker-py-cdl)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.output is not None and len(args.dom) != 1:
        print("error: -o/--output requires exactly one input", file=sys.stderr)
        return 2

    conf, cost = load_config(Path.cwd())
    fit = Fitness(conf, cost)
    kw = dict(
        adjacency=args.adjacency,
        objective=args.objective,
        preserve_public_access=args.public_access,
        local_search=args.local_search,
    )

    rc = 0
    for dom_path in args.dom:
        if not dom_path.exists():
            print(f"not found, skipping: {dom_path}", file=sys.stderr)
            rc = 1
            continue
        root = dom_mod.load(str(dom_path))
        if args.keep_better:
            tree, base_f, coll_f, applied = fit.collapse_finish(root, **kw)
        else:
            import copy
            base_f = len(fit.score_with_fails(copy.deepcopy(root))[1])
            fit.collapse_global(root, **kw)
            coll_f = len(fit.score_with_fails(copy.deepcopy(root))[1])
            tree, applied = root, True
        verb = "applied" if applied else "reverted"
        print(f"{dom_path.name}: {base_f} → {coll_f} fails ({verb})", file=sys.stderr)

        if str(args.output) == "-":
            sys.stdout.write(dom_mod.dumps(tree))
        else:
            out = args.output or dom_path.with_suffix(".collapsed.dom")
            dom_mod.dump(tree, str(out))
            print(f"written: {out}", file=sys.stderr)

    return rc


if __name__ == "__main__":
    sys.exit(main())
