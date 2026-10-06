"""Flat vs tiered comparator on the support_outside A/B artefacts (DESIGN.md §39.91).

Re-scores the 72 artefacts of each e4r A/B -- `results/e4r/` (flat comparator,
run at 07b2058+orth, §39.81) and `results/e4r-tiers/` (--use-tiers, run at
59d8aa1+orth, §39.91) -- with TODAY's scorer, then prints per-arm fail
families, the same-seed flat-vs-tiers paired report for each arm, and the
seeds where the tiers A/B's two arms disagree about `no outside space`.

Read the paired report with care:

* It is NOT a clean comparator A/B. The two experiments searched against
  different objectives (§39.84 and §39.87 landed between them); re-scoring
  puts the artefacts on one scale but cannot undo what each search climbed.
  `homemaker-py-qkp0` is the run that would make it clean.
* `ab_report` counts a W for the second arm when the difference is positive,
  i.e. LOWER is better. That is right for fails and inverted for score.

Seconds per artefact; runs in a container. No arguments.
"""
import collections
import csv
import importlib.util
import os
import re
import statistics as st
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "experiments" / "results"
EXPERIMENTS = (("flat", "e4r", "e4r_support_outside_ab.tsv"),
               ("tiers", "e4r-tiers", "e4r_support_outside_ab_tiers.tsv"))
ARMS = ("armA", "armB")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_{name}", REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def family(line: str) -> str:
    """A fail line with its level stripped, so levels pool."""
    return re.sub(r"level \d+ ", "", line.split(":")[0]).strip()


def rescore(harness, artefacts: Path, table: Path, env: dict) -> dict:
    rows = list(csv.DictReader(table.open(), delimiter="\t"))

    def one(r):
        val, lines, hard = harness.score(artefacts / r["dom"],
                                         harness.SRC_PROGRAMME, env)
        return (r["arm"], int(r["seed"])), dict(
            score=val, fails=len(lines), hard=hard, soft=len(lines) - hard,
            roof=int(any("no outside space" in l for l in lines)),
            lines=lines, storeys=int(r["storeys"]), row=r)

    with ThreadPoolExecutor(os.cpu_count() or 4) as ex:
        out = dict(ex.map(one, rows))
    moved = sum(1 for v in out.values()
                if abs(v["score"] - float(v["row"]["score"])) > 1e-6
                or v["fails"] != int(v["row"]["fails"]))
    print(f"{table.name}: {len(rows)} rows at "
          f"{sorted({r['objective'] for r in rows})}; "
          f"{moved} do not reproduce under today's scorer")
    return out


def main() -> int:
    harness, ab = _load("e4r_support_outside_ab"), _load("ab_report")
    env = dict(os.environ, HOMEMAKER_ORTHOGONAL_DIVISION="1")
    out = {name: rescore(harness, RESULTS / d, RESULTS / tsv, env)
           for name, d, tsv in EXPERIMENTS}
    print()
    for name in out:
        for arm in ARMS:
            R = [v for k, v in out[name].items() if k[0] == arm]
            print(f"{name:5} {arm} n={len(R)}"
                  f"  fails {st.mean(v['fails'] for v in R):.2f}"
                  f"  hard {st.mean(v['hard'] for v in R):.2f}"
                  f"  soft {st.mean(v['soft'] for v in R):.2f}"
                  f"  roof {sum(v['roof'] for v in R)}"
                  f"  zero-fail {sum(v['fails'] == 0 for v in R)}"
                  f"  zero-hard {sum(v['hard'] == 0 for v in R)}"
                  f"  score mean {st.mean(v['score'] for v in R):.4f}"
                  f" median {st.median(v['score'] for v in R):.4f}"
                  f"  3-storey {sum(v['storeys'] >= 3 for v in R)}")
            census = collections.Counter(
                re.sub(r"^\d+/[lr]+ ", "", family(l))
                for v in R for l in v["lines"])
            print("      ", dict(census.most_common()))
    print()
    seeds = sorted({s for _, s in out["flat"]} & {s for _, s in out["tiers"]})
    for arm in ARMS:
        print(f"== flat vs tiers, same seed, {arm} (today's scorer; a W is "
              f"'tiers LOWER', so inverted for score)")
        for metric in ("fails", "hard", "soft", "score"):
            a = [float(out["flat"][(arm, s)][metric]) for s in seeds]
            b = [float(out["tiers"][(arm, s)][metric]) for s in seeds]
            print(f"{metric}:")
            print(ab.format_report(ab.paired_report(a, b, "flat", "tiers")))
        print()
    print("== tiers A/B: seeds whose arms disagree on `no outside space`")
    for s in seeds:
        a, b = out["tiers"][("armA", s)], out["tiers"][("armB", s)]
        if a["roof"] != b["roof"]:
            print(f"s{s:<3} off {a['score']:.3f} "
                  f"{[family(l) for l in a['lines']]}   "
                  f"on {b['score']:.3f} {[family(l) for l in b['lines']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
