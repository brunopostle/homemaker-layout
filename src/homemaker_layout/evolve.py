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
  --polish-budget N    after a leaf-sharing run, unfold the shared leaves and
                       run N extra no-sharing evals so the written .dom is honest
                       under the canonical scorer (homemaker-py-3l6). -1 = auto
                       (budget//2); 0 = unfold + rescore only. Ignored with
                       --no-leaf-sharing.  (default: $HOMEMAKER_POLISH_BUDGET or -1)
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


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


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
    p.add_argument("--leaf-sharing", action=argparse.BooleanOptionalAction,
                   default=_env_bool("HOMEMAKER_LEAF_SHARING", True),
                   help="collapse same-code rooms into fewer, larger shared "
                        "leaves (erc.3, §13.3); --no-leaf-sharing for the strict "
                        "per-leaf baseline (default: on)")
    p.add_argument("--leaf-share-factor", type=int,
                   default=_env_int("HOMEMAKER_LEAF_SHARE_FACTOR", 3),
                   metavar="N",
                   help="global sharing grain: 0 = per-code opt-in only (share a "
                        "code iff its programme entry sets 'share: N>=2'); N>=2 = "
                        "share every sized code at grain N, with a code's explicit "
                        "'share' overriding (share:1 opts out) (default: 3)")
    p.add_argument("--superpose", action=argparse.BooleanOptionalAction,
                   default=_env_bool("HOMEMAKER_SUPERPOSE", False),
                   help="type superposition (9o5): interchangeable codes (similar "
                        "requirements) form equivalence classes and each candidate "
                        "collapses every superposed leaf to its best in-class usage "
                        "before scoring (default: off)")
    p.add_argument("--polish-budget", type=int,
                   default=_env_int("HOMEMAKER_POLISH_BUDGET", -1),
                   metavar="N",
                   help="homemaker-py-3l6: after a leaf-sharing run, unfold the "
                        "shared leaves and run this many extra evals of "
                        "no-sharing local search to clean up the materialised "
                        "rooms before write, so the output is honest under the "
                        "canonical scorer. -1 = auto (budget//2); 0 = unfold + "
                        "rescore only, no polish. Ignored with --no-leaf-sharing "
                        "(default: -1)")
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
    print(f"leaf sharing : {args.leaf_sharing} (factor={args.leaf_share_factor})",
          file=sys.stderr)
    print(f"superpose    : {args.superpose}", file=sys.stderr)
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
        leaf_sharing=args.leaf_sharing,
        leaf_share_factor=args.leaf_share_factor,
        superpose=args.superpose,
        log=lambda m: print(m, file=sys.stderr, flush=True),
    )

    # homemaker-py-3l6: a leaf-sharing run's internal best is scored against a
    # sharing-credited objective (a shared leaf counts as k programme rooms), so
    # r.best is dishonest under the canonical scorer — it is k-1 rooms short per
    # shared leaf. Unfold those leaves and warm-start a no-sharing polish so the
    # written .dom is honest AND its materialised rooms are cleaned up (yaa: the
    # unfold-then-polish path catches the direct no-sharing route). After this,
    # r.best.fitness is the canonical score (leaf_sharing off ⇒ internal == canon).
    if args.leaf_sharing and r.best is not None:
        polish_budget = args.budget // 2 if args.polish_budget < 0 else args.polish_budget
        # An interrupted sharing run still needs an honest output, but the user
        # asked to stop — unfold and rescore only, skip the long polish phase.
        if r.interrupted:
            polish_budget = 0
        print(file=sys.stderr)
        print(f"--- finishing (homemaker-py-3l6): unfold + polish "
              f"{polish_budget} evals ---", file=sys.stderr, flush=True)
        r = driver.polish_finish(
            r, programme_dir,
            polish_budget=polish_budget,
            pop_size=args.pop,
            child_budget=args.child_budget,
            p_crossover=0.2,
            seed=args.seed,
            n_workers=args.workers,
            superpose=args.superpose,
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
