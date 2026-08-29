"""Paired A/B reporting that states what the sample could actually resolve.

Motivation (`homemaker-py-tco`). Two findings in DESIGN.md §38.19 and §38.21 say
this project's A/B protocols are routinely underpowered for the margins they
report:

* programme-house needed N=60 to resolve an effect its own protocol claimed at
  N=20 -- at N=20 the current answer is p ~= 0.069, a null;
* harbor's paired sd is ~6.2 fails, so n=3 resolves nothing finer than ~15
  fails. Every recorded harbor margin is below that, and 25% of 3-seed subsets
  show a clean 3/3 sweep by chance.

Both were only discovered years later. The cheap prevention is to print, beside
every verdict, the smallest difference the sample could have detected -- so an
underpowered result is visible AT THE POINT IT IS MADE.

    minimum detectable difference (MDD) = t_crit(0.975, N-1) * sd / sqrt(N)

A margin below the MDD is not a weak result, it is an ABSENT one: the experiment
could not have distinguished it from zero however it came out. `paired_report`
flags exactly that, and reports the N that would be needed instead.

Usage as a library::

    from ab_report import paired_report, format_report
    print(format_report(paired_report(off_list, on_list, "OFF", "ON")))

Usage as a CLI over a results TSV with `tag  seed  arm  value  [...]` rows::

    python experiments/ab_report.py results/0wr_qpk_harbor_n24.tsv off on
"""

from __future__ import annotations

import csv
import math
import statistics
import sys

try:                                                  # scipy is a hard dep of the
    from scipy import stats as _sps                   # project, but keep the
except ImportError:                                   # report usable without it
    _sps = None


def _t_crit(df: int, alpha: float = 0.05) -> float:
    if _sps is not None:
        return float(_sps.t.ppf(1 - alpha / 2, df))
    return 1.96 if df > 30 else 2.2      # crude, only for a scipy-less fallback


def paired_report(a: list[float], b: list[float],
                  label_a: str = "A", label_b: str = "B",
                  alpha: float = 0.05) -> dict:
    """Paired comparison of two arms measured on the same seeds.

    ``a`` and ``b`` are aligned per seed. Positive ``mean_diff`` means ``b``
    scored LOWER than ``a`` -- for fail counts, that is ``b`` winning.
    """
    if len(a) != len(b):
        raise ValueError(f"unpaired input: {len(a)} vs {len(b)}")
    n = len(a)
    if n < 2:
        raise ValueError("need at least 2 paired observations")
    diffs = [x - y for x, y in zip(a, b)]
    mean = statistics.mean(diffs)
    sd = statistics.stdev(diffs)
    se = sd / math.sqrt(n)
    tc = _t_crit(n - 1, alpha)
    mdd = tc * se                          # smallest |mean| this N could resolve

    # Degenerate case: every seed gave the SAME difference, so sd == 0 and the
    # MDD collapses to 0. Without this, an all-ties comparison (mean 0, sd 0)
    # reports "margin exceeds the MDD" and endorses a zero margin as a verdict,
    # which is worse than saying nothing. t/p are nan here too.
    degenerate = sd == 0.0

    out = {
        "n": n, "label_a": label_a, "label_b": label_b,
        "mean_a": statistics.mean(a), "mean_b": statistics.mean(b),
        "wins_b": sum(1 for d in diffs if d > 0),
        "losses_b": sum(1 for d in diffs if d < 0),
        "ties": sum(1 for d in diffs if d == 0),
        "mean_diff": mean, "sd": sd, "se": se,
        "ci": (mean - tc * se, mean + tc * se),
        "mdd": mdd,
        "degenerate": degenerate,
        "identical": degenerate and mean == 0.0,
        "underpowered": (not degenerate) and abs(mean) < mdd,
        "t": None, "p": None, "wilcoxon_p": None, "n_needed": None,
    }
    if _sps is not None and not degenerate:
        t, p = _sps.ttest_rel(a, b)
        out["t"], out["p"] = float(t), float(p)
        if any(d != 0 for d in diffs):
            try:
                out["wilcoxon_p"] = float(_sps.wilcoxon(a, b).pvalue)
            except ValueError:
                pass
    if mean and not degenerate:            # N that would resolve THIS margin
        k = n
        while k < 100000 and _t_crit(k - 1, alpha) * sd / math.sqrt(k) >= abs(mean):
            k += 1
        out["n_needed"] = k
    return out


def format_report(r: dict, indent: str = "  ") -> str:
    L = []
    A, B = r["label_a"], r["label_b"]
    L.append(f"{indent}N={r['n']}   {A} mean {r['mean_a']:.2f}   {B} mean {r['mean_b']:.2f}   "
             f"{r['wins_b']}W/{r['losses_b']}L/{r['ties']}T (for {B})")
    L.append(f"{indent}mean diff {r['mean_diff']:+.3f}  sd {r['sd']:.3f}  "
             f"95% CI [{r['ci'][0]:+.3f}, {r['ci'][1]:+.3f}]")
    if r["p"] is not None:
        w = "" if r["wilcoxon_p"] is None else f"  wilcoxon p={r['wilcoxon_p']:.4f}"
        L.append(f"{indent}t={r['t']:.3f}  p={r['p']:.4f}{w}")
    if r["identical"]:
        L.append(f"{indent}** NO DIFFERENCE: the two arms scored identically on every seed.")
        L.append(f"{indent}   Nothing to test -- do not report a winner.")
        return "\n".join(L)
    if r["degenerate"]:
        L.append(f"{indent}** Every seed gave the same difference ({r['mean_diff']:+.3f}), "
                 f"so the variance is zero.")
        L.append(f"{indent}   Consistent, but a t-test is undefined here; treat N as the "
                 f"evidence and check the arms are genuinely independent.")
        return "\n".join(L)
    L.append(f"{indent}minimum detectable difference at N={r['n']}: {r['mdd']:.3f}")
    if r["underpowered"]:
        need = r["n_needed"]
        L.append(f"{indent}** UNDERPOWERED: the observed margin ({abs(r['mean_diff']):.3f}) is "
                 f"BELOW what N={r['n']} can resolve.")
        L.append(f"{indent}   This experiment could not distinguish it from zero however it "
                 f"came out. Do not declare a winner.")
        if need:
            L.append(f"{indent}   N ~= {need} would be needed for a margin this size.")
    else:
        L.append(f"{indent}   margin exceeds the MDD -- the sample can support a verdict.")
    return "\n".join(L)


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        print("usage: ab_report.py <results.tsv> <arm_a> <arm_b> [value_col=3]",
              file=sys.stderr)
        return 2
    path, arm_a, arm_b = sys.argv[1], sys.argv[2], sys.argv[3]
    col = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    by: dict = {}
    with open(path) as fh:
        for row in csv.reader(fh, delimiter="\t"):
            if len(row) <= col or not row[1].lstrip("-").isdigit():
                continue                                  # header / short row
            by.setdefault(int(row[1]), {})[row[2]] = float(row[col])
    seeds = sorted(s for s, v in by.items() if arm_a in v and arm_b in v)
    if len(seeds) < 2:
        print(f"only {len(seeds)} paired seed(s) for {arm_a!r}/{arm_b!r}", file=sys.stderr)
        return 1
    a = [by[s][arm_a] for s in seeds]
    b = [by[s][arm_b] for s in seeds]
    print(f"{path}   {arm_a} vs {arm_b}")
    print(format_report(paired_report(a, b, arm_a, arm_b)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
