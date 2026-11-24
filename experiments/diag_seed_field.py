"""Is this seed field better than that one, before it is raced?
(`homemaker-py-3xvb`, DESIGN.md §39.264)

A halving race decides between seeds, but it can only choose among the
field it is given: §39.257's maple-court race lost because its best seed was
a deep two-row wing whose back row is buried, and four more stages took off
only four fails. So a new field is worth checking first, for the things that
sank the last one. Per seed, scored as the search scores (its overrides):

  fails      all fail lines
  crink      `crinkliness` lines -- a buried room
  access     ` access` and `not adjacent to c` lines -- a room off the corridor
  unjoined   `level N not connected` lines
  dl_m       metres of double-loaded corridor (`diag_double_loaded.corridors`)

Fields are not paired (different plans), so they are compared by their
distributions: the median, the best quarter (what a race keeps), and a
Mann-Whitney U on fails.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_seed_field.py \\
        --programme maple-court experiments/results/halving-maple-rooms/seed-*.dom -- other/seed-*.dom
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from diag_double_loaded import corridors  # noqa: E402
from homemaker_layout import dom, driver, geometry  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SEARCH = dict(leaf_sharing=True, collapse_insearch=True)


def measure(fit, path) -> dict:
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    dl = sum(c[2] for c in corridors(root))
    geometry.clear_cache()
    _s, fails = fit.score_with_fails(root)
    return dict(
        fails=len(fails),
        crink=sum(f.endswith(" crinkliness") for f in fails),
        access=sum(f.endswith(" access") or "not adjacent to c" in f for f in fails),
        unjoined=sum("not connected" in f and f.startswith("level") for f in fails),
        dl_m=dl)


def summarise(name, rows) -> str:
    f = sorted(r["fails"] for r in rows)
    q = f[: max(1, len(f) // 4)]
    med = lambda k: statistics.median(r[k] for r in rows)  # noqa: E731
    return (f"{name:28} n {len(rows):3d}  fails median {statistics.median(f):6.1f}  best quarter "
            f"{statistics.mean(q):6.1f}  best {f[0]:4d}  | medians: crink {med('crink'):4.1f} "
            f"access {med('access'):4.1f} unjoined {med('unjoined'):3.1f} dl_m {med('dl_m'):5.1f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", required=True)
    ap.add_argument("--names", default=None, help="comma-separated, one per field")
    ap.add_argument("fields", nargs="+", help="seed files, fields separated by --")
    a = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    fields, cur = [], []
    for x in a.fields:
        if x == "--":
            fields.append(cur)
            cur = []
        else:
            cur.append(x)
    fields.append(cur)
    names = a.names.split(",") if a.names else [f"field {i}" for i in range(len(fields))]
    fit = driver._fitness_for(str(REPO / "examples" / a.programme), **SEARCH)
    results = []
    for name, paths in zip(names, fields):
        rows = [measure(fit, p) for p in paths]
        results.append((name, rows))
        print(summarise(name, rows), flush=True)
    if len(results) > 1:
        from scipy.stats import mannwhitneyu
        base = [r["fails"] for r in results[0][1]]
        for name, rows in results[1:]:
            u = mannwhitneyu(base, [r["fails"] for r in rows], alternative="two-sided")
            print(f"  {results[0][0]} vs {name}: Mann-Whitney U on fails p = {u.pvalue:.3g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
