"""homemaker-evolve — memetic layout search starting from a .dom file.

Usage (module):
  python -m homemaker.evolve seed.dom [options]

When installed via pip install -e .:
  homemaker-evolve seed.dom [options]

Positional arguments:
  seed.dom            starting design file

Options:
  --programme-dir DIR  programme directory with patterns.config / costs.config
                       (default: parent directory of seed.dom)
  --budget N           evaluation budget (default: $HOMEMAKER_BUDGET or 20000)
  --pop N              population size   (default: $HOMEMAKER_POP or 16)
  --child-budget N     per-child budget  (default: $HOMEMAKER_CHILD_BUDGET or 80)
  --workers N          parallel workers  (default: $HOMEMAKER_WORKERS or 1)
  --seed N             RNG seed          (default: $HOMEMAKER_SEED or 0)
  --output PATH        output .dom path  (default: <seed_stem>_evolved.dom
                                          next to seed; use - for stdout)

Progress is printed to stderr; the .dom is written on completion or interrupt.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

from . import dom, driver


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v is not None else default


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="homemaker-evolve",
        description="Memetic building-layout search over slicing trees.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("seed_dom", type=Path,
                   help="seed .dom file to start search from")
    p.add_argument("--programme-dir", type=Path, default=None, metavar="DIR",
                   help="programme directory (default: parent of seed.dom)")
    p.add_argument("--budget", type=int,
                   default=_env_int("HOMEMAKER_BUDGET", 20000),
                   metavar="N", help="evaluation budget")
    p.add_argument("--pop", type=int,
                   default=_env_int("HOMEMAKER_POP", 16),
                   metavar="N", help="population size")
    p.add_argument("--child-budget", type=int,
                   default=_env_int("HOMEMAKER_CHILD_BUDGET", 80),
                   metavar="N", help="per-child evaluation budget")
    p.add_argument("--workers", type=int,
                   default=_env_int("HOMEMAKER_WORKERS", 1),
                   metavar="N", help="parallel worker processes")
    p.add_argument("--seed", type=int,
                   default=_env_int("HOMEMAKER_SEED", 0),
                   metavar="N", help="RNG seed")
    p.add_argument("--output", type=Path, default=None, metavar="PATH",
                   help="output .dom path (- for stdout)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    seed_file = args.seed_dom.resolve()
    if not seed_file.exists():
        print(f"ERROR: seed not found: {seed_file}", file=sys.stderr)
        return 1

    programme_dir = (args.programme_dir or seed_file.parent).resolve()
    if not programme_dir.is_dir():
        print(f"ERROR: not a directory: {programme_dir}", file=sys.stderr)
        return 1
    if not (programme_dir / "patterns.config").exists():
        print(f"ERROR: no patterns.config in {programme_dir}", file=sys.stderr)
        return 1

    if args.output is None:
        out: Path | None = seed_file.parent / (seed_file.stem + "_evolved.dom")
    elif str(args.output) == "-":
        out = None
    else:
        out = args.output.resolve()

    print(f"seed         : {seed_file}", file=sys.stderr)
    print(f"programme    : {programme_dir.name}", file=sys.stderr)
    print(f"budget       : {args.budget}", file=sys.stderr)
    print(f"pop          : {args.pop}", file=sys.stderr)
    print(f"child_budget : {args.child_budget}", file=sys.stderr)
    print(f"workers      : {args.workers}", file=sys.stderr)
    print(f"rng seed     : {args.seed}", file=sys.stderr)
    print(f"output       : {out or 'stdout'}", file=sys.stderr, flush=True)

    seed_root = dom.load(str(seed_file))
    t0 = time.perf_counter()

    # SIGTERM → KeyboardInterrupt so the driver's interrupt handler fires.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    r = driver.search(
        seed_root,
        programme_dir,
        budget=args.budget,
        pop_size=args.pop,
        child_budget=args.child_budget,
        p_crossover=0.2,
        seed=args.seed,
        n_workers=args.workers,
        log=lambda m: print(m, file=sys.stderr, flush=True),
    )

    elapsed = time.perf_counter() - t0

    print(file=sys.stderr)
    status = "interrupted" if r.interrupted else "done"
    print(f"--- {status} ---", file=sys.stderr)
    print(f"elapsed      : {elapsed:.1f}s", file=sys.stderr)
    print(f"evals        : {r.n_evals} across {r.n_topologies} topologies",
          file=sys.stderr)

    if r.best is None:
        print("ERROR: no result produced", file=sys.stderr)
        return 1

    print(f"best         : {r.best.fitness:.6g} ({r.best.n_fails} fails) "
          f"via {r.best.lineage}", file=sys.stderr)

    if r.history:
        print("\nimprovement history:", file=sys.stderr)
        for ev, fit_val, lin in r.history:
            print(f"  [{ev:6d}] {fit_val:.6g}  ({lin})", file=sys.stderr)

    if out is None:
        sys.stdout.write(dom.dumps(r.best.root))
    else:
        dom.dump(r.best.root, str(out))
        print(f"written      : {out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
