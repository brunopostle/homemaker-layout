"""Which finished race finalists can `bridge_indoors` join? (`homemaker-py-05k3`)

The raw repair only, no inner loop: seconds a design. A design already in one
piece is listed and left alone. Prints one row a design.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_join_scan.py \\
        harbor-house:~/halving-harbor-guard/s5/*/out.dom ...
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diag_join_clean9 import join, score, storeys  # noqa: E402
from seed_from_catalogue import n_pieces  # noqa: E402
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, geometry, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402


def main() -> int:
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    print("programme\tdesign\tfails\tnot_connected\tjoined_fails\tjoined_not_connected\tstrips_plus_abandoned")
    for arg in sys.argv[1:]:
        name, path = arg.split(":", 1)
        prog = REPO / "examples" / name
        fit = Fitness(*load_config(prog))
        reqs = programme.load_programme_dir(str(prog))
        root = dom.load(path); dom.link(root)
        _, f0 = score(fit, root)
        before = sum("not connected" in x for x in f0)
        stats = {}
        if before:
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                stats = join(root, reqs, fit)
            _, f1 = score(fit, root)
        else:
            f1 = f0
        print(f"{name}\t{'/'.join(Path(path).parts[-4:-1])}\t{len(f0)}\t{before}\t{len(f1)}\t"
              f"{sum('not connected' in x for x in f1)}\t{sum(stats.values()) if stats else 0}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
