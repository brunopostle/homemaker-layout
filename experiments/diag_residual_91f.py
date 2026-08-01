#!/usr/bin/env python3
"""Diagnostic (homemaker-py-91f): per-leaf fail-category breakdown of the
CURRENT full default construction stack's residual, on harbor-house and
maple-court.

The last such per-leaf diagnostic (diag_leaf_shapefail.py / erc.1-erc.2)
predates the depth-balanced+leaf-sharing synergy default flip (erc.7) and the
share-aware edge cap default flip (homemaker-py-rq2/x3b) -- the current §13.9
floor (harbor 31.0, maple 74.0) has never been decomposed by fail category.

Reads the ``*.fails.json`` sidecars written by ``run_and_capture_91f.py``
(a REAL staged search, budget 20000, seeds 0/1/2, full default stack:
leaf_sharing/leaf_share_factor=3/depth_balanced/interior_outside/
outside_divisor=3/share_edge_cap) -- the actual reported floor, not a proxy.

IMPORTANT: this does NOT rescore the .dom files from disk. homemaker-py-iio
found that reloading a dumped .dom under leaf_sharing+collapse_insearch and
rescoring it does not reliably reproduce the search's own in-process
n_fails (collapse_global's cell-relabelling converges differently after a
dump/reload round trip, for reasons not yet root-caused). The .fails.json
sidecar captures the TRUE fails list straight off the in-process
``driver.search_staged`` result, which IS verified to reproduce the
search's own reported n_fails exactly (see run_and_capture_91f.py's
rescore_match field, true on all runs). Read-only: does not change
behaviour or run any search itself.

Usage:
  python3 experiments/diag_residual_91f.py <dir-with-{prog}_s{seed}.fails.json files>
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAMMES = ["harbor-house", "maple-court"]
SEEDS = (0, 1, 2)

SHAPE_SUFFIXES = ("perpendicular", "proportion", "size", "width", "crinkliness",
                  "access")


def categorize(f: str) -> str:
    if "too many spaces" in f:
        return "too many spaces (over-provided)"
    if "too few stairs" in f:
        return "too few stairs"
    if "too many stairs" in f:
        return "too many stairs"
    if "missing required space" in f:
        return "missing required space"
    if re.match(r"^missing \S+: would need", f):
        return "missing (cascade: adjacency/level/vertical/quality)"
    if " not adjacent to " in f:
        return "adjacency (not adjacent)"
    if "on wrong level" in f:
        return "wrong level"
    if "not connected to" in f and "below" in f:
        return "vertical connectivity"
    if "outside edge too long" in f:
        return "edge too long (outside)"
    if "edge too long" in f:
        return "edge too long (wall)"
    if "unsupported covered outside" in f:
        return "covered outside (unsupported)"
    if "covered outside above ground" in f:
        return "covered outside (above ground)"
    if "not connected" in f:
        return "circulation not connected"
    if "no outside space" in f:
        return "level: no outside space"
    if "no outside public access" in f:
        return "no outside public access"
    if "staircase volume" in f:
        return "staircase volume"
    if "storey limit" in f:
        return "storey limit"
    if "storey minimum" in f:
        return "storey minimum"
    for suf in SHAPE_SUFFIXES:
        if f.endswith(" " + suf):
            return suf
    return f"other: {f[:40]}"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: diag_residual_91f.py "
              "<dir-with-{prog}_s{seed}.fails.json files>", file=sys.stderr)
        return 1
    indir = Path(sys.argv[1])

    grand = Counter()
    for name in PROGRAMMES:
        tally = Counter()
        n_fails_total = 0
        n_seeds = 0
        for s in SEEDS:
            jsonfile = indir / f"{name}_s{s}.fails.json"
            if not jsonfile.exists():
                print(f"  (skip {jsonfile.name}: not found yet)", file=sys.stderr)
                continue
            data = json.loads(jsonfile.read_text())
            if not data.get("rescore_match", False):
                print(f"  WARNING: {jsonfile.name} rescore_match=False -- "
                      f"in-process rescore did not match search's own "
                      f"n_fails, investigate before trusting this seed",
                      file=sys.stderr)
            fails = data["fails"]
            n_seeds += 1
            n_fails_total += len(fails)
            for f in fails:
                tally[categorize(f)] += 1

        if n_seeds == 0:
            continue
        print(f"=== {name}  ({n_seeds} seed(s), {n_fails_total/n_seeds:.1f} "
              f"fails/seed avg) ===")
        total = sum(tally.values())
        for cat, n in tally.most_common():
            pct = 100.0 * n / total if total else 0.0
            print(f"  {n:4d}  ({pct:4.1f}%)  {cat}")
        print()
        grand.update(tally)

    if grand:
        print("=== COMBINED (both programmes, all seeds) ===")
        total = sum(grand.values())
        for cat, n in grand.most_common():
            pct = 100.0 * n / total if total else 0.0
            print(f"  {n:4d}  ({pct:4.1f}%)  {cat}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
