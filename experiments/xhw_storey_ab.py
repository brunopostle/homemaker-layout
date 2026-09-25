"""Does the 3-storey answer score better? (`homemaker-py-xhw`, DESIGN.md §39.52)

The owner, reading the programme-house plan: the guest bathroom and second
bedroom could both go on a second floor, and then every level gets outdoor
space. The objective disagrees only because level 1's terrace sits over the
ground-floor courtyard, so it is unsupported, unusable, and does not satisfy
`force_roof_garden`. Whether the 3-storey arrangement actually SCORES better is
the open question, and guessing at it is what §39.52 refuses to do.

Matched A/B, one variable:

* **arm A** — programme-house as shipped (`storey_minimum: 2`); the search may
  pick 2 or 3.
* **arm B** — identical but `storey_minimum: 3`, forcing the owner's shape.

Same objective, same budget, same seeds, cold from `init.dom` in both --
warm-starting arm B from the 2-storey best would bias it toward that topology.
`storey_minimum` only adds a fail when violated, so a 3-storey layout scores
identically under either config; every output is therefore scored under ARM A's
config and arm B is never credited or penalised for its own gate.

**Results are committed and pushed as each run lands**, because this is an
ephemeral container and the experiment has already been lost twice -- once to a
reaped process group, once to a container restart (§39.33's lesson, which the
cold-start runner learned the expensive way). `--resume` skips pairs already in
the table, so a restart costs only the runs that were in flight.

Usage::

    python experiments/xhw_storey_ab.py --budget 500000 --seeds 6 --slots 4
    python experiments/xhw_storey_ab.py --resume
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "experiments" / "results" / "xhw_storey_ab.tsv"
ARTEFACTS = REPO / "experiments" / "results" / "xhw"
SRC_PROGRAMME = REPO / "examples" / "programme-house"
FIELDS = ["arm", "seed", "objective", "budget", "storeys", "fails", "hard",
          "soft", "roof_fail", "score", "elapsed_s", "dom", "fail_list"]


def _runner():
    """Borrow the cold-start runner's stamp and its commit/push discipline
    rather than writing a second copy of either (§39.42, §39.43)."""
    spec = importlib.util.spec_from_file_location(
        "_coldstart_runner", REPO / "experiments" / "run_coldstart_baseline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_arms(work: Path) -> "dict[str, Path]":
    """Two programme directories differing in exactly one config line."""
    arms = {}
    for arm, minimum in (("armA", None), ("armB", 3)):
        d = work / arm
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(SRC_PROGRAMME, d)
        for junk in list(d.glob("coldstart-*")) + list(d.glob("*.score")) \
                + list(d.glob("*.fails")) + list(d.glob("*.checkpoint")):
            junk.unlink()
        if minimum is not None:
            cfg = d / "patterns.config"
            text = cfg.read_text()
            assert "\nstorey_minimum: 2\n" in text, "config shape changed"
            cfg.write_text(text.replace("\nstorey_minimum: 2\n",
                                        f"\nstorey_minimum: {minimum}\n"))
        arms[arm] = d
    return arms


def score_under_arm_a(dom: Path, arm_a: Path, env: dict):
    from homemaker_layout.fitness import classify_fail_tier
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        for cfg in arm_a.glob("*.config"):
            shutil.copy(cfg, w / cfg.name)
        shutil.copy(dom, w / dom.name)
        subprocess.run(["homemaker-fitness", dom.name], cwd=w,
                       capture_output=True, env=env)
        lines = [l for l in (w / f"{dom.name}.fails").read_text().splitlines()
                 if l.strip()]
        val = float((w / f"{dom.name}.score").read_text().strip())
    hard = sum(1 for l in lines if classify_fail_tier(l) == "hard")
    return val, lines, hard


def storeys(dom: Path) -> int:
    from homemaker_layout import dom as dm, geometry as g
    g.ORTHOGONAL_DIVISION = True
    r = dm.load(str(dom))
    g.clear_cache()
    n, k = r, 0
    while n is not None:
        n, k = n.above, k + 1
    return k


def existing() -> "set[tuple[str, str]]":
    if not RESULTS.exists():
        return set()
    return {(r["arm"], r["seed"])
            for r in csv.DictReader(RESULTS.open(), delimiter="\t")}


def record(row: dict, dom: Path, mod) -> None:
    rows = list(csv.DictReader(RESULTS.open(), delimiter="\t")) \
        if RESULTS.exists() else []
    rows.append({k: str(row[k]) for k in FIELDS})
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    ARTEFACTS.mkdir(parents=True, exist_ok=True)
    kept = ARTEFACTS / dom.name
    shutil.copy(dom, kept)
    mod.commit_and_push(
        [str(RESULTS.relative_to(REPO)), str(kept.relative_to(REPO))],
        f"xhw {row['arm']} seed {row['seed']}: {row['storeys']} storeys, "
        f"{row['fails']} fails, score {row['score']}",
        "Storey-count A/B (homemaker-py-xhw, DESIGN.md §39.52). Pushed per run\n"
        "because the container is ephemeral and this experiment has been lost\n"
        "twice already.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=500000)
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--slots", type=int, default=4)
    ap.add_argument("--resume", action="store_true",
                    help="skip (arm, seed) pairs already recorded")
    args = ap.parse_args()

    mod = _runner()
    dirty = mod.uncommitted_objective_sources()
    if dirty:
        print("the objective's own source is not committed: "
              + ", ".join(dirty) + "\nCommit first (§39.51).")
        return 2
    env = dict(os.environ, HOMEMAKER_ORTHOGONAL_DIVISION="1",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               MKL_NUM_THREADS="1")
    os.environ.update(env)
    objective = mod.objective_commit()

    work = Path(tempfile.gettempdir()) / "xhw_arms"
    work.mkdir(parents=True, exist_ok=True)
    arms = build_arms(work)

    queue = [(arm, s) for s in range(args.seeds) for arm in ("armA", "armB")]
    if args.resume:
        have = existing()
        skipped = [q for q in queue if (q[0], str(q[1])) in have]
        queue = [q for q in queue if (q[0], str(q[1])) not in have]
        print(f"resuming: {len(skipped)} already recorded, {len(queue)} to run")
    if not queue:
        print("nothing to do")
        return 0

    print(f"{len(queue)} runs, objective {objective}, budget {args.budget}, "
          f"{args.slots} slots", flush=True)
    running: dict = {}
    while queue or running:
        while queue and len(running) < args.slots:
            arm, seed = queue.pop(0)
            d = arms[arm]
            out = d / f"xhw-{arm}-s{seed}.dom"
            fh = (d / f"xhw-{arm}-s{seed}.log").open("w")
            p = subprocess.Popen(
                ["homemaker-evolve", "init.dom", "--budget", str(args.budget),
                 "--seed", str(seed), "--workers", "1", "--output", str(out)],
                cwd=d, stdout=subprocess.DEVNULL, stderr=fh, env=env)
            running[p.pid] = (p, arm, seed, out, fh, time.monotonic())
            print(f"  start {arm} s{seed}", flush=True)
        time.sleep(10)
        for pid, (p, arm, seed, out, fh, st) in list(running.items()):
            if p.poll() is None:
                continue
            fh.close()
            del running[pid]
            el = round(time.monotonic() - st, 1)
            if not out.exists():
                print(f"    FAILED {arm} s{seed} rc={p.returncode} ({el}s)",
                      flush=True)
                continue
            sc, fails, hard = score_under_arm_a(out, arms["armA"], env)
            k = storeys(out)
            roof = any("no outside space" in f for f in fails)
            print(f"    done {arm} s{seed}: {k} storeys, {len(fails)} fails "
                  f"(roof_fail={int(roof)}), score {sc:.4g}, {el}s", flush=True)
            record(dict(arm=arm, seed=seed, objective=objective,
                        budget=args.budget, storeys=k, fails=len(fails),
                        hard=hard, soft=len(fails) - hard, roof_fail=int(roof),
                        score=f"{sc:.6g}", elapsed_s=el, dom=out.name,
                        fail_list=" | ".join(sorted(fails))), out, mod)
    print("\n=== all runs complete ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
