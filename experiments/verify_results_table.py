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

The objective column holds the short commit of the last change to `fitness.py`
or `geometry.py`, plus `+orth` if the run-time orthogonal-division switch was
on. Rows whose commit is not the current one are **skipped, not failed**:
reproducing them needs the scorer as it was at that commit, and scoring them
with today's would report a dozen mismatches that mean nothing except that the
objective changed -- which is the whole point of the column.

The `+orth` half is not part of that test. Both halves of a commit's rows are
live at once, and each row is re-scored with the switch set to what the row
says -- not to what the environment of whoever runs this happens to say. That
matters: the switch changes the geometry, so a `+orth` row only reproduces with
it on, and an unsuffixed row only with it off. Deriving it from the environment
meant a single invocation could check only the half of the table that matched
it, and forgetting the variable skipped every orthogonal row while printing
"0 mismatched" -- which reads like success.

There is deliberately no `--objective` flag. To verify an older sweep, check out
the commit it was measured at and run this there: the commit it reports will be
that one, and those rows become the live set.

Run it after any sweep, and after any change to the objective -- where it should
report every row skipped, which is the correct answer and a reminder that the
corpus now needs re-running before anything is compared to it.

Usage::

    python experiments/verify_results_table.py
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TABLE = REPO / "experiments" / "results" / "coldstart_baseline.tsv"


def _runner():
    """The runner module, so its rules are borrowed rather than re-derived.

    Two copies of the stamping rule drifted apart once already: the runner
    stamped only `fitness.py` while `geometry.py` could change every leaf's
    area and aspect, and the ORTHOGONAL_DIVISION switch left no commit at all.
    A verifier that computes the stamp its own way cannot notice that -- it
    would simply agree with itself. So it asks the runner.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_coldstart_runner", REPO / "experiments" / "run_coldstart_baseline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def source_commit() -> str:
    """The commit half of the stamp: what the objective's *source* is at.

    Deliberately NOT the full stamp. The other half -- the orthogonal-division
    switch -- is a property of each ROW, not of whoever is running this.
    """
    mod = _runner()
    env = dict(os.environ)
    env.pop(mod.ORTH_ENV, None)
    saved, os.environ = os.environ, env
    try:
        return mod.objective_commit()
    finally:
        os.environ = saved


def split_objective(stamp: str) -> "tuple[str, bool]":
    """`"47c604f+orth"` -> `("47c604f", True)`; `"47c604f"` -> `("47c604f", False)`."""
    suffix = _runner().ORTH_SUFFIX
    if stamp.endswith(suffix):
        return stamp[:-len(suffix)], True
    return stamp, False


def score(programme: str, dom: str,
          orthogonal: bool = False) -> "tuple[int, int, int, str] | None":
    """(fails, hard, soft, score), or None if the artefact is missing.

    Scored in a scratch copy: `homemaker-fitness` writes `.score`/`.fails`
    beside its input, and verifying a table must not dirty the tree it is
    verifying.

    ``orthogonal`` comes from the ROW's objective, and is passed to the scorer
    through the environment rather than inherited from it. A row measured with
    orthogonal division on describes a geometry that only reproduces with the
    switch on; scoring it with the switch off yields a different layout and a
    mismatch that says nothing about the table. The inverse is just as wrong.
    Before this, the switch reached the scorer by inheritance, so the verifier
    could only ever check the half of the table that matched its own
    invocation -- and forgetting the variable skipped every orthogonal row
    while reporting "0 mismatched", which reads like success.
    """
    got = score_lines(programme, dom, orthogonal)
    if got is None:
        return None
    lines, val = got
    from homemaker_layout.fitness import classify_fail_tier
    hard = sum(1 for ln in lines if classify_fail_tier(ln) == "hard")
    return len(lines), hard, len(lines) - hard, f"{float(val):.6g}"


def score_lines(programme: str, dom: str,
                orthogonal: bool = False) -> "tuple[list[str], str] | None":
    """The scorer's raw output for one artefact: (fail lines, score), or None.

    The single place that runs `homemaker-fitness` over a corpus artefact, so
    the scratch-copy discipline and the per-row switch have one implementation
    rather than one per consumer. `decompose_coldstart.py` needs the lines
    themselves, which the counts above throw away.
    """
    src = REPO / "examples" / programme / dom
    if not src.exists():
        return None
    mod = _runner()
    env = dict(os.environ)
    env[mod.ORTH_ENV] = "1" if orthogonal else "0"
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for cfg in (REPO / "examples" / programme).glob("*.config"):
            shutil.copy(cfg, work / cfg.name)
        shutil.copy(src, work / dom)
        r = subprocess.run(["homemaker-fitness", dom], cwd=work,
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            raise SystemExit(f"scoring {programme}/{dom} failed: {r.stderr.strip()}")
        lines = [ln for ln in (work / f"{dom}.fails").read_text().splitlines()
                 if ln.strip()]
        val = (work / f"{dom}.score").read_text().strip()
    return lines, val


def main() -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    want = source_commit()

    rows = list(csv.DictReader(TABLE.open(), delimiter="\t"))
    checked = skipped = bad = missing = 0
    live = set()

    # Every row, at EVERY objective, must name an artefact that is still there.
    # The re-scoring below can only speak for rows at the current commit, so a
    # row whose .dom was deleted or overwritten under an older objective sat
    # unchallenged -- which is how two rows describing a crashed sweep outlived
    # the files they described (DESIGN.md §39.44). A row with no artefact is
    # not skippable: nothing can ever reproduce it again.
    orphans = [r for r in rows
               if not (REPO / "examples" / r["programme"] / r["dom"]).is_file()]
    for r in orphans:
        print(f"  ORPHAN ROW  {r['objective']} {r['programme']} s{r['seed']}: "
              f"{r['dom']} is not in the tree")

    for row in rows:
        commit, orthogonal = split_objective(row["objective"])
        # Match on the COMMIT only. Both orthogonal and non-orthogonal rows at
        # the current commit are live, and each is re-scored under its own
        # switch -- so one invocation verifies the whole table rather than
        # whichever half the environment happened to select.
        if commit != want:
            skipped += 1
            continue
        live.add(row["objective"])
        got = score(row["programme"], row["dom"], orthogonal=orthogonal)
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

    print(f"\nobjective {' + '.join(sorted(live)) or want}: "
          f"{checked} row(s) verified exactly, "
          f"{bad} mismatched, {missing} artefact(s) missing, "
          f"{skipped} row(s) skipped (other objectives)")
    # A dirty objective source is the likeliest cause of a wall of mismatches,
    # and the least obvious: the rows were measured by a commit, and they are
    # being re-scored by a working tree that is not that commit. Saying so is
    # the difference between "the table drifted" and "you have edits" (§39.51).
    dirty = _runner().uncommitted_objective_sources()
    if dirty and (bad or missing):
        print("\n  NOTE: the objective's own source is not committed --"
              + "".join(f"\n        {d}" for d in dirty)
              + "\n        so these rows are being re-scored by code that is "
                "not the commit\n        they name. Expect mismatches until "
                "you commit or revert.")

    if orphans:
        print(f"{len(orphans)} row(s) name an artefact that no longer exists. "
              f"A row that cannot be\nreproduced is not a result -- drop it, or "
              f"restore the file it names.")
        return 1
    if not checked and not bad and not missing:
        print(f"no rows were measured at the current objective commit ({want}),"
              f"\nwith or without the orthogonal-division switch.\n"
              f"The corpus needs re-running before anything is compared to it.")
        return 1
    return 1 if (bad or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
