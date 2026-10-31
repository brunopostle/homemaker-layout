"""`homemaker-py-srl0`: what penalty stops the search making double-loaded corridors?

One storey, rectangular plots, equal rooms that all want the corridor. A ladder
of depths, 30 m long, party walls on the short ends and lit on both long sides,
with rooms in proportion to the plot; and a 30 m square lit all round, where a
court allows single-loaded ranges. At 7 m single-loading is natural, at 11-13 m
double-loading is the obvious fit. Every arm runs the same seeds:

    off   today's objective, the control
    k1 k2 k3 k5 k12   `double_loaded_fails: k`, k fails per corridor
    m5 m2 `double_loaded_metres: L`, one fail per L m of corridor
    guard `--guard-double-loaded`: the objective unchanged, a child with more
          metres than its parent is declined

    HOMEMAKER_ORTHOGONAL_DIVISION=1 PYTHONPATH=src python experiments/srl0_penalty_sweep.py \\
        --work ~/srl0 --table experiments/results/srl0-penalty/sweep.tsv --seeds 8 --budget 16000
    ... --report experiments/results/srl0-penalty/sweep.tsv

`--start double` begins every run from a seed that already HAS the corridor:
one plot-long strip with a row of rooms on each side. The cold pilot
(`--start cold`, the default) made one in 3 runs of 20, too few to prevent, so
the seeded grid asks what makes the search GET RID of one. `--start single` is
the same rooms in one row along a corridor on one long wall: its off arm is the
price of single-loading on that plot, and whether the search keeps it clean.
`--check-seeds` builds each model's seeds, requires the detector to fire on the
double one and not on the single one, and runs nothing.

A finished row is not run again, so an interrupted sweep continues from the
table. ``base_fails`` leaves out the penalty's own fails, so arms compare on
what the runs paid for avoiding the corridor.
"""

from __future__ import annotations

import argparse
import copy
import os
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ab_report import format_report, paired_report  # noqa: E402
from diag_2g713_seed_storeys import family  # noqa: E402

from homemaker_layout import dom, geometry, graph  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

# model -> (plot x, plot y, rooms, perimeter of a b c d)
MODELS = {
    "deep7": (7.0, 30.0, 12, ("private", None, "private", None)),
    "deep9": (9.0, 30.0, 16, ("private", None, "private", None)),
    "deep11": (11.0, 30.0, 20, ("private", None, "private", None)),
    "deep13": (13.0, 30.0, 24, ("private", None, "private", None)),
    "court": (30.0, 30.0, 30, (None, None, None, None)),
}
ARMS = {
    "off": ({}, []),
    "k1": ({"double_loaded_fails": 1}, []),
    "k2": ({"double_loaded_fails": 2}, []),
    "k3": ({"double_loaded_fails": 3}, []),
    "k5": ({"double_loaded_fails": 5}, []),
    "k12": ({"double_loaded_fails": 12}, []),
    "m5": ({"double_loaded_metres": 5.0}, []),
    "m2": ({"double_loaded_metres": 2.0}, []),
    "guard": ({}, ["--guard-double-loaded"]),
}
CORRIDOR = 1.2
# which way a node's cut runs on these plots; --check-seeds holds them to it
DEPTH_ROTATION = 0
ROW_ROTATION = 1
COLUMNS = ("model", "arm", "seed", "fails", "base_fails", "score", "corridors",
           "metres", "elapsed_s", "families")


def patterns(rooms: int, arm: dict) -> dict:
    spaces = {f"r{i + 1}": {"usage": "bedroom", "name": f"Room {i + 1}",
                            "size": [12.0, 3.0], "width": [3.0, 0.8],
                            "proportion": [1.5, 0.5], "adjacency": ["c"]}
              for i in range(rooms)}
    return {"spaces": spaces, "storey_minimum": 1, "storey_limit": 1,
            "staircase_min": 0, "staircase_max": 0, "force_roof_garden": 0,
            "value_inside": 300.0, "value_circulation": 50.0,
            "value_outside": 100.0, "value_supported": 120.0, **arm}


def write_model(d: Path, model: str, arm: dict, start: str = "cold") -> None:
    x, y, rooms, per = MODELS[model]
    d.mkdir(parents=True, exist_ok=True)
    (d / "patterns.config").write_text(yaml.safe_dump(patterns(rooms, arm), sort_keys=False))
    plan = {"cold": lambda: {"type": "O", "rotation": 0},
            "double": lambda: double_loaded_seed(rooms, x),
            "single": lambda: single_loaded_seed(rooms, x)}[start]()
    (d / "seed.dom").write_text(yaml.safe_dump(
        {"node": [[0.0, 0.0], [x, 0.0], [x, y], [0.0, y]],
         "perimeter": dict(zip("abcd", per)), **plan,
         "height": 3, "elevation": 0.0, "wall_inner": 0.08, "wall_outer": 0.25},
        sort_keys=False))


def _row(codes: list[str], rotation: int = ROW_ROTATION) -> dict:
    """Rooms in equal cells along the plot's length, as a slicing subtree."""
    if len(codes) == 1:
        return {"type": codes[0], "rotation": 0}
    k = len(codes) // 2
    a = k / len(codes)
    # rotation accumulates down the tree: quarter-turn once, then keep cutting
    # the same way
    return {"rotation": rotation, "division": [a, a],
            "l": _row(codes[:k], 0), "r": _row(codes[k:], 0)}


def double_loaded_seed(rooms: int, depth: float) -> dict:
    """Rooms, a CORRIDOR m strip, rooms: the plan the penalty is meant to stop."""
    codes = [f"r{i + 1}" for i in range(rooms)]
    row = (depth - CORRIDOR) / 2
    a, b = row / depth, CORRIDOR / (depth - row)
    return {"rotation": DEPTH_ROTATION, "division": [a, a],
            "l": _row(codes[:rooms // 2]),
            "r": {"rotation": DEPTH_ROTATION, "division": [b, b],
                      "l": {"type": "C", "rotation": 0},
                      "r": _row(codes[rooms // 2:])}}


def single_loaded_seed(rooms: int, depth: float) -> dict:
    """A CORRIDOR m strip along one long wall, every room in one row on the other:
    the same plot and brief, the plan a penalty is meant to send the search to."""
    a = CORRIDOR / depth
    return {"rotation": DEPTH_ROTATION, "division": [a, a],
            "l": {"type": "C", "rotation": 0},
            "r": _row([f"r{i + 1}" for i in range(rooms)])}


def rate(d: Path) -> tuple:
    """(score, fails, base_fails, corridors, metres, families) of ``d/out.dom``."""
    cwd = os.getcwd()
    os.chdir(d)
    try:
        conf, cost = load_config(d, {})
        root = dom.load("out.dom")
        geometry.clear_cache()
        score, fails = Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
        dom.merge_divided(root)
        dom.link(root)
        geometry.clear_cache()
        found = graph.double_loaded_corridors(root)
    finally:
        os.chdir(cwd)
    base = [f for f in fails if "double-loaded" not in f]
    fam = Counter(family(f).split(" not adjacent")[0] for f in base)
    return (score, len(fails), len(base), len(found), sum(c[1] for c in found),
            "; ".join(f"{k} {v}" for k, v in fam.most_common(6)))


def sweep(args) -> int:
    table = Path(args.table)
    table.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if table.exists():
        done = {tuple(r.split("\t")[:3]) for r in table.read_text().split("\n")[1:] if r}
    else:
        table.write_text("\t".join(COLUMNS) + "\n")
    queue = [(m, a, s) for s in range(args.seeds) for m in args.models for a in args.arms
             if (m, a, str(s)) not in done]
    print(f"{len(done)} rows in the table, {len(queue)} to run, {args.slots} slots", flush=True)
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    running = {}
    while queue or running:
        while queue and len(running) < args.slots:
            m, a, s = queue.pop(0)
            d = Path(args.work) / m / a / f"s{s}"
            shutil.rmtree(d, ignore_errors=True)
            write_model(d, m, ARMS[a][0], args.start)
            cmd = [sys.executable, "-m", "homemaker_layout.evolve", "seed.dom",
                   "--budget", str(args.budget), "--workers", "1", "--seed", str(s),
                   "--output", "out.dom", *ARMS[a][1]]
            fh = (d / "log.txt").open("w")
            p = subprocess.Popen(cmd, cwd=d, stdout=subprocess.DEVNULL, stderr=fh, env=env)
            running[p.pid] = (p, m, a, s, d, fh, time.monotonic())
        time.sleep(2)
        for pid, (p, m, a, s, d, fh, t0) in list(running.items()):
            if p.poll() is None:
                continue
            fh.close()
            del running[pid]
            if not (d / "out.dom").exists():
                print(f"!!! {m} {a} s{s} wrote no design (rc {p.returncode}), see {d}/log.txt", flush=True)
                continue
            score, nf, base, n, metres, fam = rate(d)
            with table.open("a") as out:
                out.write(f"{m}\t{a}\t{s}\t{nf}\t{base}\t{score:.6g}\t{n}\t{metres:.1f}\t"
                          f"{time.monotonic() - t0:.0f}\t{fam}\n")
            print(f"  {m} {a} s{s}: {base} base fails, {n} double-loaded, {metres:.1f} m", flush=True)
    return 0


def report(path: str) -> int:
    rows = [dict(zip(COLUMNS, r.split("\t"))) for r in Path(path).read_text().split("\n")[1:] if r]
    models = [m for m in MODELS if any(r["model"] == m for r in rows)]
    for m in models:
        print(f"\n{m}")
        print(f"  {'arm':6} {'runs':>4} {'with one':>8} {'median m':>8} {'median base fails':>18}")
        control = {r["seed"]: r for r in rows if r["model"] == m and r["arm"] == "off"}
        for a in ARMS:
            got = [r for r in rows if r["model"] == m and r["arm"] == a]
            if not got:
                continue
            print(f"  {a:6} {len(got):4d} {sum(int(r['corridors']) > 0 for r in got):8d} "
                  f"{statistics.median(float(r['metres']) for r in got):8.1f} "
                  f"{statistics.median(int(r['base_fails']) for r in got):18.1f}")
        for a in ARMS:
            if a == "off":
                continue
            pair = [(control[r["seed"]], r) for r in rows
                    if r["model"] == m and r["arm"] == a and r["seed"] in control]
            if len(pair) < 2:
                continue
            print(f"  base fails, {a} against off:")
            print(format_report(paired_report([int(x["base_fails"]) for x, _ in pair],
                                              [int(y["base_fails"]) for _, y in pair]), indent="    "))
    return 0


def check_seeds(work: str) -> int:
    """Every seed must be what it says: the detector fires once, about 30 m."""
    bad = 0
    for m in MODELS:
        if m == "court":
            continue
        for start, want in (("double", 1), ("single", 0)):
            d = Path(work) / "check" / m / start
            shutil.rmtree(d, ignore_errors=True)
            write_model(d, m, {}, start)
            shutil.copy(d / "seed.dom", d / "out.dom")
            _, nf, base, n, metres, fam = rate(d)
            print(f"{m} {start}: {n} double-loaded, {metres:.1f} m; {base} fails: {fam}")
            bad += not (n == want and (want == 0 or metres > 25))
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--work", default=None)
    ap.add_argument("--table", default=None)
    ap.add_argument("--models", nargs="+", default=list(MODELS), choices=list(MODELS))
    ap.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--budget", type=int, default=16000)
    ap.add_argument("--slots", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--report", default=None, metavar="TABLE")
    ap.add_argument("--start", default="cold", choices=["cold", "double", "single"],
                    help="start from an empty plot, a seed that has the corridor, "
                         "or the same rooms single-loaded")
    ap.add_argument("--check-seeds", default=None, metavar="WORK")
    args = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        print("set HOMEMAKER_ORTHOGONAL_DIVISION=1", file=sys.stderr)
        return 2
    if args.check_seeds:
        return check_seeds(args.check_seeds)
    if args.report:
        return report(args.report)
    if not args.work or not args.table:
        ap.error("--work and --table, or --report")
    return sweep(args)


if __name__ == "__main__":
    sys.exit(main())
