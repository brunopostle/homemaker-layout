"""Programme rooms built far below their target area (DESIGN.md §39.199).

A `size` fail is one line, x0.5, however small the room: an 80 m2 lounge
built at 1.7 m2 costs what a 60 m2 one does. Omitting the room costs 5-8
lines (§39.80). This lists, for each design, every programme room under
half its target area as (area/target, code, whether it carries a size fail).

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_shrunk_rooms.py \\
        $(find experiments/results -name 'final-*.dom') examples/*/coldstart-*+orth-*.dom

The programme is read from the path (maple, harbor, health, programme-house,
and the maple-court race directories split-stair and join-clean9).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, geometry, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402

KEYS = {"maple": "maple-court", "harbor": "harbor-house",
        "health": "health-centre", "programme-house": "programme-house",
        "split-stair": "maple-court", "join-clean9": "maple-court"}


def main() -> int:
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    cache = {}
    print("programme\tdesign\tfails\trooms_under_half")
    for path in sys.argv[1:]:
        prog = next((v for k, v in KEYS.items() if k in path), None)
        if prog is None:
            print(f"# skipped, no programme in path: {path}", file=sys.stderr)
            continue
        if prog not in cache:
            d = REPO / "examples" / prog
            cache[prog] = (Fitness(*load_config(d)), programme.load_programme_dir(str(d)))
        fit, reqs = cache[prog]
        root = dom.load(path)
        dom.link(root)
        _, fails = fit.score_with_fails(root)
        sized = {f.split()[0] for f in fails if f.endswith(" size")}
        rows = []
        for i, lvl in enumerate(dom.levels(root)):
            for leaf in lvl.leaves():
                r = reqs.get(leaf.type)
                if r and r.size and geometry.area(leaf) / r.size < 0.5:
                    rows.append((round(geometry.area(leaf) / r.size, 2), leaf.type,
                                 f"{i}/{leaf.id}" in sized))
        print(f"{prog}\t{'/'.join(Path(path).parts[-2:])}\t{len(fails)}\t{sorted(rows)}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
