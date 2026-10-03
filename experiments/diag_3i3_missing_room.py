"""`homemaker-py-3i3`: what does a missing required room actually cost, and where?

The bead asks whether the missing-room cascade's weight "crowds out
geometry-quality signal in the region where the search actually operates", and
says it should want an owner ruling first and a measurement second. This is the
measurement. Two of the bead's own premises do not survive it, so read the header
output before the table.

  * it says "a fixed 5 fails ... a 1/32 penalty". `check_space_counts` emits 2
    base failures plus one placeholder per check a PRESENT room still faces, and
    `room_checks` is derived from `factor_is_asked`. §39.37 retired room width, so
    a room faces size and proportion only: the cascade is 4 fails, 1/16;
  * it says "most corpus layouts carry several missing instances at once, so the
    compounding is steep". No committed corpus artefact carries any.

Converged artefacts are the END of a trajectory, though, and the bead's question is
about where the search OPERATES. So the incidence is measured in three regimes:

  converged   the twelve committed artefacts
  neighbour   one operator applied to each -- the search's local move set
  seed        freshly constructed seeds, the START of a run

and the counterfactual re-scores each with the cascade collapsed to ONE failure per
missing instance, which is what "weight it like any other fail" would mean.

    python experiments/diag_3i3_missing_room.py [--seeds 6] [--draws 4]
"""

from __future__ import annotations

import argparse
import copy
import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from homemaker_layout import (dom, geometry, graph as graph_mod,  # noqa: E402
                              operators, programme)
from homemaker_layout.fitness import Fitness, load_config  # noqa: E402

PROGRAMMES = ("harbor-house", "health-centre", "maple-court", "programme-house")
CORPUS = "coldstart-c836457+orth-*.dom"


def is_cascade(f: str) -> bool:
    return f.startswith("missing required space") or "would need" in f


def split_fails(fails):
    cascade = [f for f in fails if is_cascade(f)]
    geom = [f for f in fails
            if not is_cascade(f)
            and f.split()[-1] in ("size", "width", "proportion", "crinkliness")]
    return cascade, geom, [f for f in fails if f not in cascade and f not in geom]


# --------------------------------------------------------------------------- #
# the counterfactual: ONE failure per missing instance instead of the cascade
# --------------------------------------------------------------------------- #
# Exact arithmetic rather than a monkeypatch. `Fitness` applies failures to the
# score only through `value *= 0.5 ** len(failures)` (fitness.py:2413/2415 --
# connectivity fails carry their own weight `w`, and cascade lines are never
# connectivity), and `_leaf_grade` explicitly scores structural fails 0. So
# dropping k failures multiplies the score by exactly 2**k, with no need to patch
# the THREE producers that each emit part of a cascade -- `check_space_counts`
# (two base lines + one placeholder per room check), `check_adjacency` (one more
# placeholder per declared adjacency), and the level/vertical checks. Patching
# only the first is what made an earlier run of this report say x4 instead of the
# true figure.
def instances(fails) -> int:
    """One per missing instance: the plain base line, not its `(critical)` twin."""
    return sum(1 for f in fails
               if f.startswith("missing required space:")
               and not f.endswith("(critical)"))


def collapsed(score: float, fails) -> float:
    cascade = [f for f in fails if is_cascade(f)]
    return score * (2 ** (len(cascade) - instances(fails)))


def score_both(root, conf, cost):
    """((score, fails) today, (score, fails) with the cascade collapsed to 1)."""
    geometry.clear_cache()
    score, fails = Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
    geometry.clear_cache()
    return (score, fails), (collapsed(score, fails), fails)


def predicted_cascade(req, asked) -> int:
    """2 base + one per room check asked + one per declared adjacency + one for a
    declared level. Derived by decomposing real cascades, and checked against
    every measured case by `--verbosity`."""
    return (2 + len(asked) + len(req.adjacency or [])
            + (1 if req.level is not None else 0))


def report_verbosity(programmes, asked) -> None:
    """Does the cost of omitting a room depend on how chattily its brief is written?

    `homemaker-py-1i8` (§38.12) made `check_space_counts` emit a FIXED count per
    missing instance, "independent of how the programme was spelled".
    `check_adjacency` and `check_level_constraints` each emit a further
    placeholder for the SAME missing room, so the FULL cascade is not fixed.

    THE OWNER HAS RULED THAT CORRECT (2026-09-29, §39.80): a room declaring three
    neighbours and a fixed storey is more entangled with the design, so omitting
    it does more damage. This table prices the brief, it does not indict it.
    """
    print("cost of one missing instance, by what the brief declares about it\n")
    print("%-16s %-6s %4s %6s  %9s  %s" % (
        "programme", "code", "adj", "level", "cascade", "penalty"))
    spread = []
    for prog_name in programmes:
        prog = REPO / "examples" / prog_name
        reqs = programme.load_programme_dir(str(prog))
        for code in sorted(reqs):
            req = reqs[code]
            if dom.is_generic(code):
                continue
            n = predicted_cascade(req, asked)
            spread.append(n)
            print("%-16s %-6s %4d %6s  %9d  1/%d" % (
                prog_name, code, len(req.adjacency or []),
                req.level if req.level is not None else "-", n, 2 ** n))
    if spread:
        lo, hi = min(spread), max(spread)
        print(f"\nrange across the four programmes: {lo} to {hi} lines, "
              f"i.e. 1/{2 ** lo} to 1/{2 ** hi} -- a {2 ** (hi - lo)}x spread in "
              "what it costs to omit a required room.\nThe owner has ruled that "
              "correct (§39.80): a room with more declared neighbours and a fixed "
              "storey\nis load-bearing in more places, so omitting it does more "
              "damage. Do not flatten it.")


def build_seed(prog_dir: Path, seed: int):
    reqs = programme.load_programme_dir(str(prog_dir))
    types = sorted(reqs) + ["C", "O"]
    rng = np.random.default_rng(seed)
    n_st = max(programme.n_storeys_required(reqs),
               programme.storey_minimum(str(prog_dir)))
    buckets = programme.partition_rooms_by_storey(reqs, n_st, rng)
    base = operators.constructive_topology(
        dom.load(str(prog_dir / "init.dom")), reqs, rng, types, min_storeys=n_st)
    root = operators.lift_base_to_storeys(base, buckets[1:], rng, types, reqs=reqs)
    dom.link(root)
    geometry.clear_cache()
    return root


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--draws", type=int, default=4)
    ap.add_argument("--corpus", default=CORPUS,
                    help=f"artefact glob per programme dir (default {CORPUS!r}, "
                         "the corpus §39.80 measured)")
    ap.add_argument("--verbosity-only", action="store_true",
                    help="just the brief-verbosity table (no scoring runs)")
    args = ap.parse_args(argv)
    programmes = args.programme or list(PROGRAMMES)

    conf0, cost0 = load_config(str(REPO / "examples" / "programme-house"))
    fit0 = Fitness(conf0, cost0)
    probe = dom.Node(type="__room_probe__")
    asked = [c for c in ("size", "width", "proportion")
             if fit0.factor_is_asked(c, probe)]
    print(f"a present room faces {asked} (§39.37 retired room width), so "
          f"`check_space_counts` emits 2 base + {len(asked)} placeholders.")
    print("`check_adjacency` adds one more per DECLARED adjacency and "
          "`check_level_constraints` one\nfor a declared level, so the cascade is "
          "NOT a fixed number. That is intended (§39.80).\n")

    report_verbosity(programmes, asked)
    print()
    if args.verbosity_only:
        return 0

    rows = {"converged": [], "neighbour": [], "seed": []}

    for prog_name in programmes:
        prog = REPO / "examples" / prog_name
        conf, cost = load_config(str(prog))
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]

        # --- converged, and its one-move neighbourhood -----------------------
        for path in sorted(prog.glob(args.corpus)):
            geometry.ORTHOGONAL_DIVISION = True
            root = dom.load(str(path))
            geometry.clear_cache()
            rows["converged"].append(score_both(root, conf, cost))

            fit = Fitness(conf, cost)
            for op_name in sorted(operators.MUTATIONS):
                op = operators.MUTATIONS[op_name]
                params = inspect.signature(op).parameters
                kw = {}
                if "reqs" in params:
                    kw["reqs"] = reqs
                if "fit" in params:
                    kw["fit"] = fit
                for s in range(args.draws):
                    geometry.clear_cache()
                    try:
                        child, _d = op(root, np.random.default_rng(s), types, **kw)
                    except Exception:             # noqa: BLE001
                        continue
                    rows["neighbour"].append(score_both(child, conf, cost))

        # --- freshly constructed seeds --------------------------------------
        geometry.ORTHOGONAL_DIVISION = True
        for s in range(args.seeds):
            try:
                root = build_seed(prog, s)
            except Exception as exc:              # noqa: BLE001
                print(f"  seed {prog_name}/{s} failed to build: "
                      f"{type(exc).__name__}: {exc}")
                continue
            rows["seed"].append(score_both(root, conf, cost))

    print("%-11s %6s %8s %6s %7s %9s %8s  %s" % (
        "regime", "n", "with a", "inst", "cascade", "lines per", "geometry",
        "median score"))
    print("%-11s %6s %8s %6s %7s %9s %8s  %s" % (
        "", "", "missing", "", "lines", "instance", "fails", "today -> collapsed"))
    for regime in ("converged", "neighbour", "seed"):
        data = rows[regime]
        if not data:
            continue
        n = len(data)
        with_missing = sum(1 for (r, _a) in data if split_fails(r[1])[0])
        casc = sum(len(split_fails(r[1])[0]) for (r, _a) in data)
        inst = sum(instances(r[1]) for (r, _a) in data)
        geom = sum(len(split_fails(r[1])[1]) for (r, _a) in data)
        med_real = sorted(r[0] for (r, _a) in data)[n // 2]
        med_alt = sorted(a[0] for (_r, a) in data)[n // 2]
        print("%-11s %6d %8d %6d %7d %9s %8d  %.6f -> %.6f" % (
            regime, n, with_missing, inst, casc,
            ("%.2f" % (casc / inst)) if inst else "-", geom, med_real, med_alt))

    # where the collapse changes the score at all
    print()
    for regime in ("converged", "neighbour", "seed"):
        data = rows[regime]
        if not data:
            continue
        moved = [(r[0], a[0]) for (r, a) in data if a[0] != r[0]]
        if not moved:
            print(f"{regime}: collapsing the cascade changes NOTHING "
                  f"({len(data)} cases) -- the weight never fires here")
            continue
        ratio = sorted(a / r for r, a in moved if r > 0)
        med = ratio[len(ratio) // 2] if ratio else float("nan")
        print(f"{regime}: the collapse moves {len(moved)}/{len(data)} scores; "
              f"median gain x{med:.2f} where it moves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
