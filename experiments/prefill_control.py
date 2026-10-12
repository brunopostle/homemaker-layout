"""Give one `flag_ab.py` experiment the control arm another has already run.

DESIGN.md §39.129: a default search at one objective, one search commit and
one seed is one design, byte for byte, so every A/B on a programme was
re-deriving the same control. `flag_ab.py --resume` skips any (arm, seed)
already in its table; this puts the rows and the designs there.

    python experiments/prefill_control.py labels aim [--programme programme-house]

copies experiment `labels`'s CONTROL arm into `aim`'s table, renamed. It
refuses if the target already has control rows, if the source has none, or if
the stamps the source rows carry are not the live ones. The copied rows keep
the source's `elapsed_s`: the target's elapsed comparison is then NOT paired
and must not be read.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
R = REPO / "experiments" / "results"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source")
    ap.add_argument("target")
    ap.add_argument("--programme", default="programme-house")
    a = ap.parse_args(argv)
    os.environ.setdefault("HOMEMAKER_ORTHOGONAL_DIVISION", "1")
    ab, run = _load("flag_ab"), _load("run_coldstart_baseline")
    src_arm = ab.EXPERIMENTS[a.source]["arms"][0]
    dst_arm = ab.EXPERIMENTS[a.target]["arms"][0]
    src_tsv, dst_tsv = R / f"{a.source}_ab.tsv", R / f"{a.target}_ab.tsv"
    if not src_tsv.exists():
        print(f"no {src_tsv.name}")
        return 1
    rows = [r for r in csv.DictReader(src_tsv.open(), delimiter="\t")
            if r["arm"] == src_arm and r["programme"] == a.programme]
    if not rows:
        print(f"{a.source} has no `{src_arm}` rows for {a.programme}")
        return 1
    live = (run.objective_commit(), run.search_commit())
    stale = {(r["objective"], r["search_commit"]) for r in rows} - {live}
    if stale:
        print(f"{a.source}'s control was run at {sorted(stale)}; the live stamps are {live}")
        return 1
    have = list(csv.DictReader(dst_tsv.open(), delimiter="\t")) if dst_tsv.exists() else []
    if any(r["arm"] == dst_arm and r["programme"] == a.programme for r in have):
        print(f"{a.target} already has `{dst_arm}` rows for {a.programme}; nothing done")
        return 1
    (R / f"{a.target}-ab").mkdir(exist_ok=True)
    out = []
    for r in sorted(rows, key=lambda r: int(r["seed"])):
        row = dict(r)
        row["arm"] = dst_arm
        row["dom"] = f"{a.target}-ab-{a.programme}-{dst_arm}-s{r['seed']}.dom"
        shutil.copyfile(R / f"{a.source}-ab" / r["dom"], R / f"{a.target}-ab" / row["dom"])
        out.append(row)
    with dst_tsv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ab.FIELDS, delimiter="\t")
        w.writeheader()
        w.writerows(have + out)
    print(f"{a.target}: {len(out)} `{dst_arm}` rows supplied from {a.source}'s `{src_arm}` "
          f"({a.programme}, {live[0]}, search {live[1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
