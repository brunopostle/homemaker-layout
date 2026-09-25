"""Decompose a finished cold-start sweep: per-programme deltas, fail families, MDD.

What this is for. A sweep produces twelve numbers; the questions worth asking of
them are "where did the fails go", "did anything actually move", and "could this
sample have resolved it if it had". This answers all three in one pass, at the
moment the sweep lands, so nobody has to reconstruct the protocol from memory a
month later.

Three rules from DESIGN.md are built in rather than left to the reader:

* **§39.31 -- a decomposition is not a result until the sweep is complete.**
  Missing rows are refused, not silently averaged over. ``--partial`` proceeds
  anyway and stamps every section PROVISIONAL.
* **§39.12 clause 3 / §39.31 -- a fail count is only comparable to another
  measured by the same objective.** Comparing two objectives is allowed, but the
  report prints the commits that separate them first, so a confound cannot be
  read as a result. Where the reference arm is at a different objective its
  numbers are RE-SCORED by today's scorer, each layout under the geometry it was
  built with: that holds the scorer fixed and compares the layouts, which is a
  different and weaker claim than a search A/B, and is labelled as such.
* **§38.19/§38.21 (via ab_report) -- print what the sample could have detected.**
  The MDD sits beside every verdict. A margin below it is an absent result, not
  a weak one.

Nothing here re-derives a rule that exists elsewhere: the objective stamp comes
from the runner, the scorer from ``verify_results_table.score_lines``, and the
statistics from ``ab_report``. Three copies of a rule is how §39.42 and §39.43
happened.

Usage::

    python experiments/decompose_coldstart.py                     # current objective
    python experiments/decompose_coldstart.py --against 99c85ec   # plus a comparison
    python experiments/decompose_coldstart.py --partial           # mid-sweep peek
"""

from __future__ import annotations

import argparse
import collections
import csv
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TABLE = REPO / "experiments" / "results" / "coldstart_baseline.tsv"
sys.path.insert(0, str(REPO / "experiments"))

import ab_report  # noqa: E402  (after the path insert)


def _verifier():
    spec = importlib.util.spec_from_file_location(
        "_coldstart_verifier", REPO / "experiments" / "verify_results_table.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A fail line names the leaf it happened to land on; the family is what repeats.
# The shapes, from fitness.py:
#   "<level>/<leaf id> <rest>"                    e.g. "0/rlrlr proportion"
#   "<level>/<leaf id> <other leaf id> <rest>"    e.g. "1/rrll rrlr edge too long"
#   "<level>/<leaf id> (<room code>) <rest>"      e.g. "1/rllr (py) not adjacent to c"
#   "level <n> <rest>"                            e.g. "level 0 not connected"
#   "too few stairs (0, min 1)"                   -- must not split on its numbers
# A leaf id is a string of 'l' and 'r' and nothing else, which no word in a
# failure message is, so dropping a bare [lr]+ token is unambiguous.
_PREFIX = re.compile(r"^\d+/[lr]*\s+")
_PEER = re.compile(r"^[lr]+\s+(?=\S)")
_CODE = re.compile(r"\(\w+\)\s*")
_NUM = re.compile(r"\d+")


def family(line: str) -> str:
    """The kind of failure, with leaf ids, room code and numbers removed.

    Getting this wrong splits one family across several rows and hides exactly
    the concentration the decomposition exists to find -- an earlier version
    left the second leaf id on, so "edge too long" appeared as three families
    of one.
    """
    s = _PREFIX.sub("", line)
    s = _PEER.sub("", s)
    s = _CODE.sub("", s)
    s = _NUM.sub("N", s)
    return " ".join(s.split())


def rows_at(objective: str) -> "dict[tuple[str, str], dict]":
    return {(r["programme"], r["seed"]): r
            for r in csv.DictReader(TABLE.open(), delimiter="\t")
            if r["objective"] == objective}


def separating_commits(a: str, b: str) -> "list[str]":
    """Commits touching the objective's source between two stamps."""
    r = subprocess.run(
        ["git", "log", "--oneline", f"{a}..{b}", "--",
         "src/homemaker_layout/fitness.py", "src/homemaker_layout/geometry.py"],
        cwd=REPO, capture_output=True, text=True)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def default_target(v) -> "tuple[str, dict]":
    """The sweep to decompose, chosen by COMMIT rather than by environment.

    Which rows exist is a fact about the table; which switch the caller happens
    to have exported is not. Deriving the whole stamp from the environment is
    what made `verify_results_table` able to see only half its table (§39.43),
    so this matches on the commit and then looks to see which variants are
    actually present. Ambiguity is reported, never guessed.
    """
    commit = v.source_commit()
    cands = {o: rows_at(o) for o in (commit, commit + v._runner().ORTH_SUFFIX)}
    live = {o: r for o, r in cands.items() if r}
    if len(live) == 1:
        return next(iter(live.items()))
    if len(live) > 1:
        names = ", ".join(sorted(live))
        print(f"both variants of {commit} have rows ({names}).\n"
              f"name one with --objective.")
        return commit, {}
    return commit, {}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--objective", default=None,
                    help="the sweep to decompose (default: the current stamp, "
                         "with the orthogonal switch read from your environment)")
    ap.add_argument("--against", default=None, metavar="OBJECTIVE",
                    help="also compare against this objective's rows")
    ap.add_argument("--partial", action="store_true",
                    help="proceed with an incomplete sweep, marked PROVISIONAL")
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()

    v = _verifier()
    if args.objective:
        target, t_rows = args.objective, rows_at(args.objective)
    else:
        target, t_rows = default_target(v)
    if not t_rows:
        have = sorted({r["objective"] for r in
                       csv.DictReader(TABLE.open(), delimiter="\t")})
        print(f"no rows at objective {target}.\n"
              f"the table holds: {', '.join(have)}\n"
              f"name one with --objective.")
        return 1

    programmes = sorted({p for p, _ in t_rows})
    want = [(p, str(s)) for p in programmes for s in range(args.seeds)]
    missing = [k for k in want if k not in t_rows]

    print(f"objective   : {target}")
    print(f"rows        : {len(t_rows)} of {len(want)}")
    provisional = ""
    if missing:
        names = ", ".join(f"{p} s{s}" for p, s in missing)
        if not args.partial:
            print(f"\nINCOMPLETE -- {len(missing)} run(s) missing: {names}\n\n"
                  f"A decomposition is not a result until the sweep is complete "
                  f"(DESIGN.md §39.31).\nRe-run when it lands, or pass --partial "
                  f"to look anyway.")
            return 2
        provisional = "  [PROVISIONAL]"
        print(f"missing     : {names}")
        print(f"\n*** PROVISIONAL: {len(missing)} run(s) still missing. Nothing below "
              f"is a result. ***")

    # ---------------------------------------------------------------- rows --
    print(f"\n=== rows{provisional} ===")
    print(f"{'programme':<17}" + "".join(f"{'s'+str(s)+': fails(h/s)':>17}"
                                         for s in range(args.seeds)))
    for p in programmes:
        cells = []
        for s in range(args.seeds):
            r = t_rows.get((p, str(s)))
            cells.append(f"{r['fails']:>4} ({r['hard']:>2}/{r['soft']:>2})".rjust(17)
                         if r else "--".rjust(17))
        print(f"{p:<17}" + "".join(cells))

    # ------------------------------------------------------------ families --
    print(f"\n=== fail families{provisional} ===")
    fam: "dict[str, collections.Counter]" = {}
    pooled: collections.Counter = collections.Counter()
    drift: list[tuple] = []
    for (p, s), r in sorted(t_rows.items()):
        _, orth = v.split_objective(r["objective"])
        got = v.score_lines(p, r["dom"], orthogonal=orth)
        if got is None:
            print(f"  MISSING ARTEFACT {p} s{s}: {r['dom']}")
            continue
        for ln in got[0]:
            fam.setdefault(p, collections.Counter())[family(ln)] += 1
            pooled[family(ln)] += 1
        # The census is re-scored with TODAY'S code. The row was recorded by the
        # scorer of its own objective. Those agree only while the objective has
        # not moved since -- so check, rather than claiming it (DESIGN.md
        # §39.61). This block used to print "reproduces the rows exactly"
        # unconditionally, and went on printing it after §39.59 moved the
        # objective, while the two totals differed by seven.
        if len(got[0]) != int(r["fails"]):
            drift.append((p, s, int(r["fails"]), len(got[0])))
    if drift:
        print("*** RE-SCORED UNDER A DIFFERENT OBJECTIVE THAN THE ROWS WERE "
              "RECORDED AT ***")
        print(f"    {len(drift)} of {len(t_rows)} row(s) do not reproduce. The "
              f"families below are\n    what TODAY'S code says about these "
              f"artefacts, NOT the census of {target}:")
        for p, s, was, now in drift:
            print(f"      {p} s{s}: recorded {was}, re-scored {now} ({now-was:+d})")
        print("    Neither number is wrong; they answer different questions "
              "(§39.12 clause 3).\n    For the census AS RECORDED, read the rows "
              "above, or check out the\n    objective's own commit.")
    else:
        print("(re-scored from the committed artefacts; reproduces the rows "
              "exactly)")
    for p in programmes:
        c = fam.get(p)
        if not c:
            continue
        n = sum(1 for k in t_rows if k[0] == p)
        print(f"\n  {p}  ({sum(c.values())} fails over {n} run(s))")
        for k, cnt in c.most_common():
            print(f"    {cnt:>4}  {cnt/n:>5.1f}/run  {k}")
    print(f"\n  ALL PROGRAMMES ({sum(pooled.values())} fails)")
    for k, cnt in pooled.most_common():
        print(f"    {cnt:>4}  {100*cnt/sum(pooled.values()):>5.1f}%  {k}")

    # ----------------------------------------------------------- vs a ref ---
    if args.against:
        ref = args.against
        r_rows = rows_at(ref)
        print(f"\n=== {target} vs {ref}{provisional} ===")
        sep = separating_commits(v.split_objective(ref)[0],
                                 v.split_objective(target)[0])
        if sep:
            print(f"\n  *** {len(sep)} commit(s) change the objective's source "
                  f"between these two:")
            for ln in sep:
                print(f"        {ln}")
            print("  A difference below is NOT attributable to any one of them "
                  "(§39.12 clause 3).")
        paired = [(p, s) for (p, s) in sorted(t_rows) if (p, s) in r_rows]
        if len(paired) < 2:
            print(f"\n  only {len(paired)} matched run(s) -- nothing to pair.")
            return 0
        print(f"\n  {len(paired)} matched (programme, seed) pair(s), as RECORDED "
              f"by each objective's own scorer:")
        for metric in ("fails", "hard", "soft"):
            a = [float(r_rows[k][metric]) for k in paired]
            b = [float(t_rows[k][metric]) for k in paired]
            print(f"\n  -- {metric} --")
            print(ab_report.format_report(
                ab_report.paired_report(a, b, ref, target), indent="     "))
        for p in programmes:
            pk = [k for k in paired if k[0] == p]
            if len(pk) < 2:
                continue
            a = [float(r_rows[k]["fails"]) for k in pk]
            b = [float(t_rows[k]["fails"]) for k in pk]
            print(f"\n  -- {p}, fails --")
            print(ab_report.format_report(
                ab_report.paired_report(a, b, ref, target), indent="     "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
