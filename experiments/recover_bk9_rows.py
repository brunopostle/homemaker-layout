"""Regenerate the `bk9` result rows that never reached the results table.

The seven finished `bk9` runs were committed as artefacts (`de41ce8`) but their
rows were lost from `experiments/results/coldstart_baseline.tsv`, which still
holds only the twelve `39.12` rows. The table therefore does not describe the
`.dom` files sitting beside it, and the next run to finish will append a
`bk9` row to twelve rows measured under a different objective, with nothing on
any line to say which is which. That is the mixture `DESIGN.md` 39.12 and 39.20
were both about.

This regenerates the lost rows *from the committed artefacts* rather than from
any remembered number: score, fails, hard and soft all come back exactly,
because `homemaker-fitness` is deterministic and the `.dom` is the run's own
output. Verified against the runner's terminal output when the rows still
existed -- all seven scores match to six significant figures.

`elapsed_s` is NOT recoverable and is deliberately left empty. It lived only in
the runner's on-disk table. That costs nothing: these seven runs were timed with
`time.time()` before the `d04e585` fix and span a three-day machine suspend, so
the numbers were never usable (DESIGN.md 39.27). An empty column is a truer
record than a transcribed one.

Writes `experiments/results/coldstart_bk9_recovered.tsv`, a SEPARATE file. It
does not touch `coldstart_baseline.tsv` on purpose: the runner reads that table
before it takes the git lock, so editing it from another clone while a sweep is
live invites a rebase collision in `record_and_push` and can wedge a job that
has days of compute in it. Merge the two by hand once the sweep is done.

Usage::

    python experiments/recover_bk9_rows.py
    python experiments/recover_bk9_rows.py harbor-house:2 health-centre:2
"""

from __future__ import annotations

import csv
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "experiments" / "results" / "coldstart_bk9_recovered.tsv"
BUDGET = 500000

# The runs finished under the post-39.26 objective as of `de41ce8`, in the
# order the runner completed them.
DEFAULT_RUNS = [
    ("programme-house", 0), ("health-centre", 0), ("harbor-house", 0),
    ("harbor-house", 1), ("maple-court", 0), ("programme-house", 1),
    ("health-centre", 1),
]

FIELDS = ["programme", "seed", "budget", "fails", "hard", "soft", "score",
          "elapsed_s", "dom"]


def score_artefact(programme: str, seed: int) -> "tuple[int, int, int, str]":
    """(fails, hard, soft, score) for one committed artefact.

    Scored in a scratch copy, never in the tree: `homemaker-fitness` writes
    `.score`/`.fails` next to its input, and a sweep may be running in
    `examples/` right now.
    """
    from homemaker_layout.fitness import classify_fail_tier

    name = f"coldstart-{BUDGET}-s{seed}.dom"
    src = REPO / "examples" / programme / name
    if not src.exists():
        raise SystemExit(f"no such artefact: {src}")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for cfg in (REPO / "examples" / programme).glob("*.config"):
            shutil.copy(cfg, work / cfg.name)
        shutil.copy(src, work / name)
        r = subprocess.run(["homemaker-fitness", name], cwd=work,
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"scoring {programme} s{seed} failed: {r.stderr.strip()}")
        lines = [ln for ln in (work / f"{name}.fails").read_text().splitlines()
                 if ln.strip()]
        score = (work / f"{name}.score").read_text().strip()

    hard = sum(1 for ln in lines if classify_fail_tier(ln) == "hard")
    return len(lines), hard, len(lines) - hard, f"{float(score):.6g}"


def main() -> None:
    runs = DEFAULT_RUNS
    if sys.argv[1:]:
        runs = []
        for arg in sys.argv[1:]:
            prog, _, seed = arg.partition(":")
            if not seed.isdigit():
                raise SystemExit(f"expected <programme>:<seed>, got {arg!r}")
            runs.append((prog, int(seed)))

    rows = []
    for programme, seed in runs:
        fails, hard, soft, score = score_artefact(programme, seed)
        rows.append({
            "programme": programme, "seed": seed, "budget": BUDGET,
            "fails": fails, "hard": hard, "soft": soft, "score": score,
            "elapsed_s": "", "dom": f"coldstart-{BUDGET}-s{seed}.dom",
        })
        print(f"{programme:16s} s{seed}  {fails:3d} fails ({hard}h/{soft}s)"
              f"  score {score}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t")
        w.writeheader()
        w.writerows({k: str(r[k]) for k in FIELDS} for r in rows)

    tot = sum(r["fails"] for r in rows)
    th = sum(r["hard"] for r in rows)
    print(f"\n{len(rows)} rows -> {OUT.relative_to(REPO)}"
          f"  (total {tot} fails, {th} hard, {tot - th} soft)")


if __name__ == "__main__":
    main()
