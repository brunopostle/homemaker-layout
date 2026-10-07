"""Run searches with the move recorder on, and keep the logs
(`homemaker-py-urzf`, DESIGN.md §39.115).

Each run is `homemaker-evolve` as shipped, single worker, orthogonal division
on, with `HOMEMAKER_MOVE_LOG` naming a file: one JSON line per child (the
move, the parent's fail lines, the child's, what `admit` did with it). The
recorder changes nothing about the search (`tests/test_move_log.py`).

Logs land in `experiments/results/moves/<programme>-b<budget>-s<seed>.jsonl.gz`
with the stamp they were searched at in `MANIFEST.tsv`. Runs already there
are skipped. They are run at low priority (`nice 19`): this is container work
and is usually sharing the box with a sweep, whose budget is counted in
evaluations and so loses time, not results.

    PYTHONPATH=src python experiments/record_moves.py --programme programme-house \\
        --seeds 12 --budget 100000 --jobs 4
    python experiments/diag_move_book.py            # read them
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "experiments" / "results" / "moves"
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")


def _runner():
    spec = importlib.util.spec_from_file_location(
        "_coldstart_runner", REPO / "experiments" / "run_coldstart_baseline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", choices=PROGRAMMES, default="programme-house")
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--first-seed", type=int, default=100,
                    help="seeds start here, clear of the 0-35 the A/Bs use")
    ap.add_argument("--budget", type=int, default=100000)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)

    env = dict(os.environ, HOMEMAKER_ORTHOGONAL_DIVISION="1", OMP_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               PYTHONPATH=str(REPO / "src"))
    os.environ["HOMEMAKER_ORTHOGONAL_DIVISION"] = "1"
    mod = _runner()
    stamp, search, config = mod.objective_commit(), mod.search_commit(), mod.search_config()[0]
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = OUT / "MANIFEST.tsv"
    if not manifest.exists():
        manifest.write_text("file\tprogramme\tseed\tbudget\tobjective\tsearch_commit\t"
                            "search_config\trecords\telapsed_s\n")

    queue = []
    for seed in range(a.first_seed, a.first_seed + a.seeds):
        name = f"{a.programme}-b{a.budget}-s{seed}.jsonl.gz"
        if not (OUT / name).exists():
            queue.append((seed, name))
    print(f"{len(queue)} runs to record on {a.programme}, objective {stamp}, "
          f"search {search} / {config}, budget {a.budget}", flush=True)

    work = Path(tempfile.mkdtemp(prefix="record_moves_"))
    running: dict = {}
    while queue or running:
        while queue and len(running) < a.jobs:
            seed, name = queue.pop(0)
            d = work / f"s{seed}"
            shutil.copytree(REPO / "examples" / a.programme, d)
            for junk in {*d.glob("coldstart-*"), *d.glob("*.score"), *d.glob("*.fails")}:
                junk.unlink()
            log = d / "moves.jsonl"
            p = subprocess.Popen(
                ["nice", "-n", "19", sys.executable, "-m", "homemaker_layout.evolve",
                 "init.dom", "--budget", str(a.budget), "--seed", str(seed),
                 "--workers", "1", "--output", str(d / "out.dom")],
                cwd=d, stdout=subprocess.DEVNULL, stderr=(d / "run.log").open("w"),
                env=dict(env, HOMEMAKER_MOVE_LOG=str(log)))
            running[p.pid] = (p, seed, name, log, time.monotonic())
        time.sleep(5)
        for pid, (p, seed, name, log, t0) in list(running.items()):
            if p.poll() is None:
                continue
            del running[pid]
            if p.returncode != 0 or not log.exists():
                print(f"  FAILED s{seed} rc={p.returncode}: see {log.parent / 'run.log'}", flush=True)
                continue
            data = log.read_bytes()
            with gzip.open(OUT / name, "wb") as fh:
                fh.write(data)
            n = data.count(b"\n")
            with manifest.open("a") as fh:
                fh.write(f"{name}\t{a.programme}\t{seed}\t{a.budget}\t{stamp}\t{search}\t"
                         f"{config}\t{n}\t{time.monotonic() - t0:.0f}\n")
            print(f"  recorded s{seed}: {n} children, {time.monotonic() - t0:.0f}s", flush=True)
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
