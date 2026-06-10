"""Go/no-go experiment for bottom-up sizing.

Take a real evolved .dom, throw away its division ratios, and re-solve them from
the programme's target sizes alone. Score three versions through the Perl oracle:

  original  -- the evolved .dom as-is (baseline)
  roundtrip -- loaded and re-emitted unmodified (checks dump fidelity)
  solved    -- ratios stripped to 0.5 then solved from programme targets

If `solved` scores >= `original`, sizing can be recovered from the programme
without the evolved geometry, and the EA only needs to search topology.

Usage:
  python experiments/resolve_ratios.py [source.dom] [--urb /path/to/urb]
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homemaker import dom, oracle, programme, solver  # noqa: E402

DEFAULT_URB = Path("/home/bruno/src/urb")
DEFAULT_SRC = DEFAULT_URB / "examples/programme-house/candidate-002.dom"


def _score_in(scratch: Path, name: str, root: dom.Node, urb: Path) -> oracle.Score:
    path = scratch / name
    dom.dump(root, str(path))
    return oracle.score(path, urb)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?", default=str(DEFAULT_SRC))
    ap.add_argument("--urb", default=str(DEFAULT_URB))
    args = ap.parse_args()

    src = Path(args.source).resolve()
    urb = Path(args.urb).resolve()
    config = src.parent / "patterns.config"

    scratch = Path(__file__).resolve().parents[1] / "scratch"
    scratch.mkdir(exist_ok=True)
    shutil.copy(config, scratch / "patterns.config")

    targets = programme.load_programme(str(config))

    # baseline: score the original file as-is
    orig_copy = scratch / "original.dom"
    shutil.copy(src, orig_copy)
    s_orig = oracle.score(orig_copy, urb)

    # roundtrip: load + re-emit unmodified
    s_round = _score_in(scratch, "roundtrip.dom", dom.load(str(src)), urb)

    # solved: strip ratios and re-solve from programme targets
    root = dom.load(str(src))
    print("--- programme leaves BEFORE solve (ratios intact) ---")
    print(solver.area_report(root, targets))
    res = solver.solve_ratios(root, targets, strip=True)
    print("\n--- programme leaves AFTER solve (from targets, ratios stripped) ---")
    print(solver.area_report(root, targets))
    print(f"\nsolver: cost={res.cost:.4f} nfev={res.nfev} success={res.success}")
    s_solved = _score_in(scratch, "solved.dom", root, urb)

    # refined: warm-start from the evolved ratios (solver as geometry optimiser)
    root2 = dom.load(str(src))
    solver.solve_ratios(root2, targets, strip=False)
    s_refined = _score_in(scratch, "refined.dom", root2, urb)

    print("\n=== FITNESS (via urb-fitness.pl oracle) ===")
    for label, s in (
        ("original", s_orig),
        ("roundtrip", s_round),
        ("solved", s_solved),
        ("refined", s_refined),
    ):
        print(f"  {label:9s} fitness={s.fitness:.10g}  fails={s.n_fails}")

    print("\nVERDICT:")
    print(f"  solved  (strip, frozen topology): {'>=' if s_solved.fitness >= s_orig.fitness else '<'} original")
    print(f"  refined (warm-start optimiser):   {'>=' if s_refined.fitness >= s_orig.fitness else '<'} original")


if __name__ == "__main__":
    main()
