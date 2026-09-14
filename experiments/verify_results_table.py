"""Check `coldstart_baseline.tsv` against the artefacts it claims to describe.

Every row names a `.dom` that is committed next to it. The scorer is
deterministic, so each row's `fails`, `hard`, `soft` and `score` must be
reproducible by scoring that file -- **with the objective the row was measured
by**, which is what the `objective` column is for.

This exists because the table and the artefacts drifted apart twice in one
week (DESIGN.md 39.27/39.28/39.31):

* `de41ce8` wrote one sweep's outputs over another's under a shared filename,
  so the committed `.dom` files stopped matching the rows beside them and a
  test pinned to the old layouts broke.
* Seven rows went missing from the table entirely while their artefacts stayed
  committed, and five more were appended to twelve rows measured under a
  different objective with nothing to distinguish them.

Neither was detectable by reading the file. Both are detectable by this.

The objective column holds the short commit of the last change to
`fitness.py`. Rows whose objective is not the current one are **skipped, not
failed**: reproducing them needs the scorer as it was at that commit, and
scoring them with today's would report a dozen mismatches that mean nothing
except that the objective changed -- which is the whole point of the column.

There is deliberately no `--objective` flag for that reason. To verify an older
sweep, check out the commit it was measured at and run this there: the objective
it reports will be that one, and those rows become the live set.

Run it after any sweep, and after any change to the objective -- where it should
report every row skipped, which is the correct answer and a reminder that the
corpus now needs re-running before anything is compared to it.

Usage::

    python experiments/verify_results_table.py
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TABLE = REPO / "experiments" / "results" / "coldstart_baseline.tsv"


def current_objective() -> str:
    r = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "src/homemaker_layout/fitness.py"],
        cwd=REPO, capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


def score(programme: str, dom: str) -> "tuple[int, int, int, str] | None":
    """(fails, hard, soft, score), or None if the artefact is missing.

    Scored in a scratch copy: `homemaker-fitness` writes `.score`/`.fails`
    beside its input, and verifying a table must not dirty the tree it is
    verifying.
    """
    from homemaker_layout.fitness import classify_fail_tier

    src = REPO / "examples" / programme / dom
    if not src.exists():
        return None
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for cfg in (REPO / "examples" / programme).glob("*.config"):
            shutil.copy(cfg, work / cfg.name)
        shutil.copy(src, work / dom)
        r = subprocess.run(["homemaker-fitness", dom], cwd=work,
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"scoring {programme}/{dom} failed: {r.stderr.strip()}")
        lines = [ln for ln in (work / f"{dom}.fails").read_text().splitlines()
                 if ln.strip()]
        val = (work / f"{dom}.score").read_text().strip()
    hard = sum(1 for ln in lines if classify_fail_tier(ln) == "hard")
    return len(lines), hard, len(lines) - hard, f"{float(val):.6g}"


def main() -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    want = current_objective()

    rows = list(csv.DictReader(TABLE.open(), delimiter="\t"))
    checked = skipped = bad = missing = 0

    for row in rows:
        if row["objective"] != want:
            skipped += 1
            continue
        got = score(row["programme"], row["dom"])
        label = f"{row['programme']} s{row['seed']}"
        if got is None:
            print(f"  MISSING ARTEFACT  {label}: {row['dom']}")
            missing += 1
            continue
        fails, hard, soft, val = got
        diffs = [f"{k}: table {row[k]} != artefact {v}"
                 for k, v in (("fails", fails), ("hard", hard),
                              ("soft", soft), ("score", val))
                 if row[k] != str(v)]
        if diffs:
            print(f"  MISMATCH  {label}")
            for d in diffs:
                print(f"      {d}")
            bad += 1
        else:
            checked += 1

    print(f"\nobjective {want}: {checked} row(s) verified exactly, "
          f"{bad} mismatched, {missing} artefact(s) missing, "
          f"{skipped} row(s) skipped (other objectives)")
    if not checked and not bad and not missing:
        print(f"no rows were measured by the current objective ({want}).\n"
              f"The corpus needs re-running before anything is compared to it.")
        return 1
    return 1 if (bad or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
