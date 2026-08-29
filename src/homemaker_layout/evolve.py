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
    p.add_argument("--checkpoint-every", type=int, default=0, metavar="N",
                   help="write the best-so-far .dom every N evals (0 = off). "
                        "Crash safety for long runs: without it the only "
                        "output lands at the end, so a reclaimed container or "
                        "an OOM loses the whole search.")
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
    p.add_argument("--multi-use", action=argparse.BooleanOptionalAction,
                   default=_env_bool("HOMEMAKER_MULTI_USE", False),
                   help="homemaker-py-1s3 (§26 path b): multi-use leaves as a "
                        "PERMANENT design goal. Codes declaring a mutual "
                        "'co_locate' (and passing interchangeable()'s S1-S4 "
                        "bounds) may be fused onto one leaf at construction time, "
                        "surviving unchanged into the output (unlike --superpose's "
                        "per-eval collapse to a single usage) (default: off)")
    p.add_argument("--shapecurve-warmstart", dest="shapecurve_warmstart",
                   action=argparse.BooleanOptionalAction,
                   default=_env_bool("HOMEMAKER_SHAPECURVE_WARMSTART", False),
                   help="homemaker-py-6xh (DESIGN.md §37.2/§37.4): warm-start "
                        "each child's inner-loop ratio search from the exact "
                        "Otten/Stockmeyer shape-curve DP solution instead of "
                        "the proportion-aware target-geometry seed, when the "
                        "topology is eligible (single storey, no leaf-sharing/"
                        "superpose/max-share/multi-use — none of which the DP "
                        "models). Falls through to today's start unchanged when "
                        "ineligible or DP-infeasible (default: off)")
    p.add_argument("--shapecurve-prune", dest="shapecurve_prune",
                   action=argparse.BooleanOptionalAction,
                   default=_env_bool("HOMEMAKER_SHAPECURVE_PRUNE", False),
                   help="homemaker-py-wkh (DESIGN.md §37.5): use the shape-curve "
                        "DP's exact feasible/infeasible verdict alongside the "
                        "existing predicted_shape_fails pre-filter (a no-op "
                        "unless the driver.search()-level feasibility_filter is "
                        "also on -- not yet exposed as its own CLI flag). A "
                        "DP-feasible verdict vetoes a heuristic-triggered prune "
                        "outright (a real shape-feasible point exists, so the "
                        "heuristic's high count was a false signal); a "
                        "DP-infeasible verdict prunes immediately only when the "
                        "incumbent already has zero total fails (exact: "
                        "DP-infeasible proves the shape-fail floor is >=1); "
                        "otherwise falls through to today's heuristic-count "
                        "decision unchanged (default: off)")
    p.add_argument("--conn-grade", dest="conn_grade",
                   action=argparse.BooleanOptionalAction,
                   default=_env_bool("HOMEMAKER_CONN_GRADE", False),
                   help="homemaker-py-qi6 (§18): graded circulation-connectivity "
                        "signal. Adds a secondary comparator key (beneath fail "
                        "count, above fitness) = per-level largest-circ-component "
                        "fraction, giving the search a gradient toward connected "
                        "circulation that the binary 'not connected' fail lacks. "
                        "Does not change the scalar fitness or fail count "
                        "(default: off)")
    p.add_argument("--use-tiers", dest="use_tiers",
                   action=argparse.BooleanOptionalAction,
                   default=_env_bool("HOMEMAKER_USE_TIERS", False),
                   help="homemaker-py-2g7.3 (DESIGN.md §37): hard/soft fail "
                        "tiering. Outer comparator becomes (-n_hard, -n_soft, "
                        "fitness) instead of (-n_fails, fitness), so budget "
                        "stops being spent polishing SOFT shape fails "
                        "(crinkliness/proportion/size/width/edge-too-long/"
                        "staircase-volume) while HARD structural fails (missing "
                        "space, wrong/required level, level/circulation/vertical "
                        "connectivity, adjacency, stairs, covered-outside, "
                        "storey limits, public access) remain unfixed. Does not "
                        "change the scalar fitness or total fail count "
                        "(default: off)")
    p.add_argument("--bridge-circulation", dest="bridge_circulation",
                   action=argparse.BooleanOptionalAction,
                   default=_env_bool("HOMEMAKER_BRIDGE_CIRCULATION", False),
                   help="homemaker-py-8sh (qi6 mechanism (a) follow-on): "
                        "explicit repair mutation that retypes the cheapest "
                        "path between two disconnected circulation components "
                        "to circulation, directly clearing a 'level N not "
                        "connected' fail instead of relying on the qi6 graded "
                        "comparator key (measured negative, §18) (default: off)")
    p.add_argument("--ruin-recreate", dest="ruin_recreate",
                   action=argparse.BooleanOptionalAction,
                   default=_env_bool("HOMEMAKER_RUIN_RECREATE", False),
                   help="homemaker-py-f1d: large-neighbourhood-search repair "
                        "mutation that un-divides one wing of a storey and "
                        "rebuilds it with the adjacency-aware constructor "
                        "(seeded from the surviving circulation bordering the "
                        "wing), applying the one construction technique with a "
                        "track record repeatedly during search instead of only "
                        "at seeding (default: off)")
    p.add_argument("--collapse-insearch", dest="collapse_insearch",
                   action=argparse.BooleanOptionalAction,
                   default=_env_bool("HOMEMAKER_COLLAPSE_INSEARCH", True),
                   help="homemaker-py-qpk (§17 follow-on): run the 94g global "
                        "cell→room collapse inside every fitness eval instead of "
                        "once at finish time, so search optimises the collapsed "
                        "objective directly. A/B-validated positive on both "
                        "harbor-house (3/3, mean fails 80.3→72.0) and, after the "
                        "homemaker-py-1ph larger-N sweep, programme-house (11/17 "
                        "non-tied wins, mean fails 7.95→7.10) (default: on)")
    p.add_argument("--anneal-grain", type=str,
                   default=os.environ.get("HOMEMAKER_ANNEAL_GRAIN"),
                   metavar="LADDER",
                   help="homemaker-py-kpu (Schedule B): in-run leaf-share grain "
                        "annealing. A descending comma-separated grain ladder (e.g. "
                        "'4,3,2') ramped down across phases within one run, "
                        "unfolding leaves that exceed each new cap and carrying the "
                        "population across steps, then a de-share polish. Implies "
                        "leaf-sharing; --budget is split across the sharing phases "
                        "and --polish-budget funds the final de-share phase. Unset "
                        "(default) = the single-transition §15 finish.")
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
    p.add_argument("--collapse", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="homemaker-py-94g: finish-time global cell→room collapse — "
                        "relabel the best layout's room cells to the programme "
                        "rooms they fit best (level + adjacency + public-access "
                        "constrained), kept only if it does not increase the fail "
                        "count. Labels only, never geometry (default: on)")
    p.add_argument("--collapse-local-search", dest="collapse_local_search",
                   action=argparse.BooleanOptionalAction, default=True,
                   help="homemaker-py-9wi/cdl: run the 2-opt adjacency polish "
                        "past collapse_global's Jacobi fixpoint as part of "
                        "--collapse. A 46-file A/B sweep (harbor-house + "
                        "programme-house) found 0 regressions, 2 improvements "
                        "(default: on). Ignored if --no-collapse")
    p.add_argument("--output", type=Path, default=None, metavar="PATH",
                   help="output .dom path (- for stdout)")
    return p.parse_args(argv)


def _preflight(programme_dir) -> None:
    """Warn before the run if the programme cannot fit its plot (homemaker-py-tdp).

    Two checks, cheap and closed-form (DESIGN.md §38.3/§39.11). Neither can be
    fixed by searching harder, so it is worth saying so up front rather than
    letting a multi-hour run bottom out against it:

    1. does the demanded floor area fit the plot at all;
    2. is there enough daylit wall for that area, given every interior leaf
       needs ``L >= A/(1.6202*h)`` before it fails crinkliness.

    "Daylit" is measured exactly as ``Fitness.area_outside`` does: an external
    boundary counts unless its perimeter type is ``private`` or ``fortified``.

    Advisory only — it never blocks a run, since an author may deliberately be
    exploring an over-tight brief.
    """
    from . import geometry
    from . import programme as _prog

    try:
        root = dom.load(f"{programme_dir}/init.dom")
        per = root.perimeter or {}
        daylit = sum(geometry.edge_length(root, e) for e in range(4)
                     if (per.get(geometry.boundary_id(root, e)) or "").lower()
                     not in ("private", "fortified"))
        plot = geometry.area(root)
        height = root.height or 3.0
        reqs = _prog.load_programme_dir(str(programme_dir))
        storeys = max(_prog.n_storeys_required(reqs),
                      _prog.storey_minimum(str(programme_dir)))
        built = sum(r.size * r.count for r in reqs.values()) / max(storeys, 1)
    except Exception:
        return                              # advisory only; never block a run

    if not plot or not daylit:
        return

    if built > plot:
        print(f"WARNING: programme demands {built:.0f} m2 per storey on a "
              f"{plot:.0f} m2 plot ({100 * built / plot:.0f}%). Every room will "
              f"be squeezed below its target however long the search runs. "
              f"(DESIGN.md §39.11)", file=sys.stderr)
    needed = built / (1.6202 * height)
    if needed > daylit:
        court = (needed - daylit) * 1.5
        note = (f", but only {plot - built:.0f} m2 of plot is spare"
                if court > plot - built else "")
        print(f"WARNING: {built:.0f} m2 per storey needs ~{needed:.0f} m of daylit "
              f"wall; the plot's non-private perimeter gives {daylit:.0f} m. "
              f"Roughly {court:.0f} m2 of courtyard closes the gap{note}. "
              f"(DESIGN.md §38.3)", file=sys.stderr)


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

    _preflight(programme_dir)

    def _make_checkpoint(path):
        """Write best-so-far to `<out>.checkpoint` ATOMICALLY.

        A checkpoint is worthless if a crash can catch it half-written, so it
        goes to a temp file in the same directory and is renamed over the
        target (rename is atomic within a filesystem). It is deliberately NOT
        the final output path -- a checkpoint is a leaf-sharing run's internal
        best, which is dishonest under the canonical scorer until the finish
        stage unfolds it (homemaker-py-3l6), so it must not be mistaken for
        the finished article.
        """
        import os
        import tempfile

        def _write(best, n_evals):
            if best is None:
                return
            d = os.path.dirname(path) or "."
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".ckpt")
            try:
                with os.fdopen(fd, "w") as fh:
                    fh.write(dom.dumps(best.root))
                os.replace(tmp, path)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
            print(f"[{n_evals:6d} evals] checkpoint -> {os.path.basename(path)} "
                  f"({best.n_fails} fails)", file=sys.stderr, flush=True)

        return _write

    _ckpt = (_make_checkpoint(str(out) + ".checkpoint")
             if args.checkpoint_every > 0 and args.output != Path("-") else None)

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
    print(f"multi_use    : {args.multi_use}", file=sys.stderr)
    print(f"conn grade   : {args.conn_grade}", file=sys.stderr)
    print(f"use tiers    : {args.use_tiers}", file=sys.stderr)
    print(f"bridge circulation : {args.bridge_circulation}", file=sys.stderr)
    print(f"ruin recreate      : {args.ruin_recreate}", file=sys.stderr)
    print(f"collapse in-search : {args.collapse_insearch}", file=sys.stderr)
    print(f"shapecurve warmstart : {args.shapecurve_warmstart}", file=sys.stderr)
    print(f"shapecurve prune     : {args.shapecurve_prune}", file=sys.stderr)
    print(f"output       : {out or 'stdout'}", file=sys.stderr, flush=True)

    anneal_ladder = None
    if args.anneal_grain:
        anneal_ladder = tuple(int(g) for g in args.anneal_grain.split(",")
                              if g.strip())

    seed_root = dom.load(str(seed_file))
    t0 = time.perf_counter()

    # SIGTERM → KeyboardInterrupt so the driver's interrupt handler fires.
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    if anneal_ladder:
        # homemaker-py-kpu (Schedule B): in-run grain annealing already ends with a
        # de-share polish, so it is self-finishing — the §15 unfold+polish is not
        # applied on top.
        polish_budget = args.budget // 2 if args.polish_budget < 0 else args.polish_budget
        print(f"anneal grain : {anneal_ladder} → off (polish {polish_budget})",
              file=sys.stderr, flush=True)
        r = driver.search_annealed(
            seed_root,
            programme_dir,
            budget=args.budget,
            polish_budget=polish_budget,
            grain_ladder=anneal_ladder,
            pop_size=args.pop,
            child_budget=args.child_budget,
            p_crossover=0.2,
            seed=args.seed,
            n_workers=args.workers,
            superpose=args.superpose,
            multi_use=args.multi_use,
            checkpoint=_ckpt,
            checkpoint_every=args.checkpoint_every,
            log=lambda m: print(m, file=sys.stderr, flush=True),
        )
        _finish_sharing = False
    else:
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
            multi_use=args.multi_use,
            conn_grade=args.conn_grade,
            use_tiers=args.use_tiers,
            enable_bridge_circulation=args.bridge_circulation,
            enable_ruin_recreate=args.ruin_recreate,
            collapse_insearch=args.collapse_insearch,
            shapecurve_warmstart=args.shapecurve_warmstart,
            shapecurve_prune=args.shapecurve_prune,
            checkpoint=_ckpt,
            checkpoint_every=args.checkpoint_every,
            log=lambda m: print(m, file=sys.stderr, flush=True),
        )
        _finish_sharing = args.leaf_sharing

    # homemaker-py-3l6: a leaf-sharing run's internal best is scored against a
    # sharing-credited objective (a shared leaf counts as k programme rooms), so
    # r.best is dishonest under the canonical scorer — it is k-1 rooms short per
    # shared leaf. Unfold those leaves and warm-start a no-sharing polish so the
    # written .dom is honest AND its materialised rooms are cleaned up (yaa: the
    # unfold-then-polish path catches the direct no-sharing route). After this,
    # r.best.fitness is the canonical score (leaf_sharing off ⇒ internal == canon).
    if _finish_sharing and r.best is not None:
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
            multi_use=args.multi_use,
            collapse_insearch=args.collapse_insearch,
            log=lambda m: print(m, file=sys.stderr, flush=True),
        )

    # homemaker-py-94g: finish-time global cell→room collapse. Relabels the best
    # layout's room cells to the programme rooms they fit best (label search only,
    # no geometry change), kept only if it does not increase the fail count. Runs
    # after the sharing polish so it acts on the canonical (materialised) best.
    if args.collapse and r.best is not None:
        print(file=sys.stderr)
        print("--- collapse (homemaker-py-94g): finish-time cell→room relabel ---",
              file=sys.stderr, flush=True)
        r = driver.collapse_best(
            r, programme_dir,
            superpose=args.superpose,
            multi_use=args.multi_use,
            conn_grade=args.conn_grade,
            local_search=args.collapse_local_search,
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
