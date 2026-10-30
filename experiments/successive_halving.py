"""`homemaker-py-2g7.13.1`: try every strategy, and let the search drop the dead ends.

The owner (2026-10-16): the search resolves a building's small-scale structure
well; what it lacks is the ability to start from a STRATEGY -- an L, a C, an
8, in every orientation the plot distinguishes -- try them all, and keep the
one that fits. A seed's own fail count is the wrong judge of that (§39.144:
a refilled footprint looks barely better than a cold seed on total fails, yet
keeps the daylight the cold search never recovers). So the search judges it:

    successive halving -- every candidate runs ``--start`` evaluations; the
    better 1/eta survive; each survivor continues from its own best design at
    eta times the budget; until ``--final`` or one candidate is left.

Total cost is about log_eta(n) times one final run, spread over ``--slots``.

**Ranked on what the search does not repair.** A candidate's rank is first its
STRUCTURAL fails -- crinkliness, connectivity, inaccessible space, stairs,
support -- the families §39.142's cold runs end with and the hand-seeded ones
do not; then total fails; then score. Adjacency, size, access and proportion
are what a longer search fixes, so they only break ties. ``--rank total``
ranks on fails alone, as the control. ``--rank weighted`` is ``total`` with
each connectivity fail counted ``connectivity_weight`` times (§39.8), so a
race run under ``--conf connectivity_weight=auto`` ranks as its objective
prices (``total`` would ignore the weight and rank on raw fails first).

**``--conf KEY=VALUE`` changes the objective a race runs under**, for every
candidate's search AND for the ranking: the line is appended to each stage's
copy of ``patterns.config`` (the programme's own file is never touched) and
merged into the ranking scorer's config. The value is parsed as YAML. It is
an objective change for that race, so its rows are not comparable with a
race run without it except as the A/B it is (``homemaker-py-2g7.13.1.10``).

**A stage is a warm restart, not a continuation.** `homemaker-evolve` keeps no
population between runs, so each stage starts from the previous stage's best
design with a fresh population and its own random seed -- the way §39.142's
hand-seeded runs started from the owner's drawing.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/successive_halving.py \\
        --programme harbor-house --seeds examples/harbor-house/wings-*.dom \\
        --start 4000 --final 128000 --eta 2 --slots 8

Every stage's candidates go to ``<work>/stages.tsv`` as they finish; the
winner is copied to ``--output``.

**``--resume`` continues an interrupted race** (a power cut lost one five hours
in). Give it the same arguments. Without it ``<work>`` is deleted at start-up.
Every candidate with a row in the table keeps its result, re-scored from its
``out.dom`` and refused if the row no longer reproduces: that catches a damaged
file and an objective that moved. Everything else reruns from scratch under the
same random seed, because ``homemaker-evolve`` writes nothing until it finishes.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from diag_2g713_seed_storeys import family  # noqa: E402

from homemaker_layout import dom, geometry  # noqa: E402
from homemaker_layout.fitness import Fitness, is_connectivity_fail  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# The families a long search does not repair (§39.142, §39.144). A fail is
# structural if its family starts with one of these.
STRUCTURAL = ("crinkliness", "level", "inaccessible usable space",
              "too few stairs", "too many stairs", "staircase",
              "unsupported", "covered outside above ground", "no outside space")


def structural(fails) -> int:
    return sum(family(f).startswith(STRUCTURAL) for f in fails)


def weighted(fails, w: float) -> float:
    """Fails as the objective prices them: a connectivity fail counts ``w``."""
    n_conn = sum(1 for f in fails if is_connectivity_fail(f))
    return len(fails) - n_conn + w * n_conn


def parse_conf(items, prog: Path) -> dict:
    """``KEY=VALUE`` pairs, each VALUE read as YAML. A key the programme's
    own file already sets is refused: appending it would leave two values
    in one file and which one wins would be the YAML loader's choice."""
    own = yaml.safe_load((prog / "patterns.config").read_text()) or {}
    out = {}
    for item in items:
        key, sep, val = item.partition("=")
        if not sep or not key.strip():
            raise SystemExit(f"--conf wants KEY=VALUE, not {item!r}")
        key = key.strip()
        if key in own:
            raise SystemExit(f"--conf {key}: {prog / 'patterns.config'} already sets it")
        out[key] = yaml.safe_load(val)
    return out


def write_overrides(path: Path, overrides: dict) -> None:
    """Append the overrides to a stage's COPY of patterns.config, as top-level
    keys, and check the file reads back with them."""
    if not overrides:
        return
    with path.open("a") as fh:
        fh.write("\n# successive_halving.py --conf\n")
        fh.write(yaml.safe_dump(overrides, default_flow_style=False))
    back = yaml.safe_load(path.read_text())
    assert all(back.get(k) == v for k, v in overrides.items()), path


def seed_int(*parts) -> int:
    return int.from_bytes(hashlib.sha1("|".join(map(str, parts)).encode()).digest()[:4], "big")


def read_table(path: Path) -> dict:
    """``stages.tsv`` as {(stage, candidate): (budget, structural, fails, score string)}."""
    if not path.exists():
        raise SystemExit(f"--resume: no {path}")
    done = {}
    for line in path.read_text().split("\n")[1:]:
        if not line:
            continue
        row = line.split("\t")
        if len(row) != 8:
            raise SystemExit(f"--resume: damaged row in {path}: {line!r}")
        done[int(row[0]), row[2]] = (int(row[1]), int(row[3]), int(row[4]), row[5])
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default="harbor-house")
    ap.add_argument("--seeds", nargs="+", required=True, help="candidate seed .dom files")
    ap.add_argument("--start", type=int, default=4000, help="first stage's budget")
    ap.add_argument("--final", type=int, default=128000, help="last stage's budget")
    ap.add_argument("--eta", type=int, default=2, help="keep 1/eta, multiply budget by eta")
    ap.add_argument("--slots", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--rank", choices=("structural", "total", "weighted"),
                    default="structural")
    ap.add_argument("--conf", action="append", default=[], metavar="KEY=VALUE",
                    help="override a patterns.config key for the searches and the "
                         "ranking (repeatable; VALUE is YAML)")
    ap.add_argument("--work", default=None, help="working directory (default /tmp/halving_<programme>)")
    ap.add_argument("--output", default=None, help="copy the winner here")
    ap.add_argument("--resume", action="store_true",
                    help="continue the race in --work instead of deleting it; same arguments")
    ap.add_argument("--evolve-args", default="", help="extra homemaker-evolve flags")
    args = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        print("set HOMEMAKER_ORTHOGONAL_DIVISION=1", file=sys.stderr)
        return 2

    prog = REPO / "examples" / args.programme
    overrides = parse_conf(args.conf, prog)
    conf, cost = load_config(prog, overrides)
    fit = Fitness(conf, cost)
    if overrides:
        print(f"objective overrides: {overrides} (connectivity_weight in force: "
              f"{fit._connectivity_weight:g})", flush=True)
    work = Path(args.work or f"/tmp/halving_{args.programme}")
    done = {}
    if args.resume:
        done = read_table(work / "stages.tsv")
        print(f"resuming {work}: {len(done)} finished candidates in the table", flush=True)
        table = (work / "stages.tsv").open("a")
    else:
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        table = (work / "stages.tsv").open("w")
        table.write("stage\tbudget\tcandidate\tstructural\tfails\tscore\telapsed_s\tfamilies\n")

    def rate(d: Path):
        """Score a finished candidate: (result tuple, its fails)."""
        out = d / "out.dom"
        cwd = os.getcwd()
        os.chdir(d)
        try:
            root = dom.load(str(out))
            geometry.clear_cache()
            sc, fails = fit.score_with_fails(root)
        finally:
            os.chdir(cwd)
        fails = list(fails)
        return (structural(fails), len(fails), sc, out,
                weighted(fails, fit._connectivity_weight)), fails

    # candidate name -> its current best design
    alive = {Path(s).stem: Path(s).resolve() for s in args.seeds}
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               MKL_NUM_THREADS="1")
    budget, stage = args.start, 0
    n_stages = 1 + max(0, math.ceil(math.log(max(1, len(alive)), args.eta)))
    print(f"{args.programme}: {len(alive)} candidates, budget {args.start} rising x{args.eta} "
          f"to {args.final}, ranked on {args.rank} fails, {args.slots} slots; "
          f"at most {n_stages} stages", flush=True)

    while True:
        queue, results = [], {}
        for name, src in alive.items():
            row = done.pop((stage, name), None)
            if row is None:
                queue.append((name, src))
                continue
            results[name] = rate(work / f"s{stage}" / name)[0]
            now = (budget, *results[name][:2], f"{results[name][2]:.6g}")
            if now != row:
                raise SystemExit(f"--resume: stage {stage} {name} was {row}, now reproduces as {now}")
        stray = sorted(k for k in done if k[0] <= stage)
        if stray:
            raise SystemExit(f"--resume: table rows for candidates not in this race: {stray}")
        if results:
            print(f"stage {stage}: {len(results)} restored, {len(queue)} to run", flush=True)
        running = {}
        while queue or running:
            while queue and len(running) < args.slots:
                name, src = queue.pop(0)
                d = work / f"s{stage}" / name
                if args.resume:
                    shutil.rmtree(d, ignore_errors=True)  # what the interruption left
                d.mkdir(parents=True)
                shutil.copy(src, d / "seed.dom")
                for f in ("patterns.config", "costs.config"):
                    if (prog / f).exists():
                        shutil.copy(prog / f, d / f)
                write_overrides(d / "patterns.config", overrides)
                cmd = [sys.executable, "-m", "homemaker_layout.evolve", "seed.dom",
                       "--budget", str(budget), "--workers", "1",
                       "--seed", str(seed_int(name, stage)), "--output", "out.dom",
                       *args.evolve_args.split()]
                fh = (d / "log.txt").open("w")
                p = subprocess.Popen(cmd, cwd=d, stdout=subprocess.DEVNULL, stderr=fh, env=env)
                running[p.pid] = (p, name, d, fh, time.monotonic())
            time.sleep(2)
            for pid, (p, name, d, fh, t0) in list(running.items()):
                if p.poll() is None:
                    continue
                fh.close()
                del running[pid]
                el = time.monotonic() - t0
                if not (d / "out.dom").exists():
                    print(f"  !!! {name} wrote no design (rc {p.returncode}); dropped", flush=True)
                    continue
                results[name], fails = rate(d)
                st, sc = results[name][0], results[name][2]
                fam = Counter(family(f) for f in fails)
                table.write(f"{stage}\t{budget}\t{name}\t{st}\t{len(fails)}\t{sc:.6g}\t{el:.0f}\t"
                            + "; ".join(f"{k} {v}" for k, v in fam.most_common(6)) + "\n")
                table.flush()
                print(f"  stage {stage} ({budget}): {name}: {st} structural, "
                      f"{len(fails)} fails, score {sc:.3g}, {el:.0f}s", flush=True)

        if not results:
            print("no candidate survived the stage", flush=True)
            return 1
        if args.rank == "structural":
            key = lambda r: (r[0], r[1], -r[2])  # noqa: E731
        elif args.rank == "weighted":
            key = lambda r: (r[4], -r[2])  # noqa: E731
        else:
            key = lambda r: (r[1], -r[2])  # noqa: E731
        ranked = sorted(results, key=lambda n: key(results[n]))
        if len(ranked) == 1 or budget >= args.final:
            break
        keep = ranked[:max(1, math.ceil(len(ranked) / args.eta))]
        print(f"stage {stage}: keep {', '.join(keep)}; drop "
              f"{', '.join(n for n in ranked if n not in keep) or '-'}", flush=True)
        alive = {n: results[n][3] for n in keep}
        stage += 1
        budget = min(args.final, budget * args.eta)

    win = ranked[0]
    st, nf, sc, out, _ = results[win]
    print(f"\nwinner {win}: {st} structural, {nf} fails, score {sc:.4g} "
          f"(stage {stage}, budget {budget})", flush=True)
    if args.output:
        shutil.copy(out, args.output)
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
