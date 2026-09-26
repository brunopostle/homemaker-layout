"""What the merge-minted sahn was costing (`homemaker-py-4e7`, §39.66).

`merge_divided` minted an `S` after `preprocess_building` had converted every one
away, and nothing converted it back. Six corpus artefacts carried one;
health-centre s2 carried four.

That is not a label. `dom.is_circulation` is True for `S` and False for `O`, so a
merge-minted sahn joins the circulation graph, counts for the access and
connectivity checks, satisfies a neighbour's `adjacency: [c]`, and takes the
`uncrinkliness_circulation` family -- the whole of what `allow_sahn_circulation
= 0` exists to switch off.

This measures the difference on committed artefacts, per fail family, so the
expected direction of the next sweep is on record BEFORE it runs (§39.12 clause
3, CLAUDE.md's pause discipline). The BEFORE arm is reproduced exactly by forcing
`allow_sahn=True`, which is what the old code did unconditionally.

Usage::

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_4e7_sahn_merge.py
    ... --objective c836457+orth
"""

from __future__ import annotations

import argparse
import collections
import copy
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROGRAMMES = ("programme-house", "harbor-house", "maple-court", "health-centre")


def _family(fail: str) -> str:
    """Collapse a fail line to its family, the way decompose_coldstart does."""
    f = re.sub(r"^\d+/\S+\s*", "", fail.strip())
    f = re.sub(r"^level \d+ ", "level ", f)
    f = re.sub(r"\(.*?\)", "", f)
    f = re.sub(r"\b[a-z]{1,3}\d+\b", "<code>", f)
    return " ".join(f.split())


def score(path: Path, prog_dir: Path, allow_sahn: bool):
    from homemaker_layout import dom, fitness, genome
    real = dom.merge_divided
    if allow_sahn:
        # NOT functools.partial(real, allow_sahn=True): `fitness` passes
        # `allow_sahn=` explicitly, and a call-time keyword overrides a
        # partial's, so the patch silently did nothing and this diagnostic
        # reported "no change" for both arms (§39.66). Swallow the caller's
        # keyword instead.
        dom.merge_divided = lambda r, **_kw: real(r, allow_sahn=True)
    try:
        conf, cost = fitness.load_config(str(prog_dir))
        fit = fitness.Fitness(conf, cost)
        root = genome.decode(genome.encode(dom.load(str(path))))
        val, fails = fit.score_with_fails(copy.deepcopy(root))
    finally:
        dom.merge_divided = real
    return val, [f for f in fails if f.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--objective", default="c836457+orth")
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()

    if os.environ.get("HOMEMAKER_ORTHOGONAL_DIVISION") != "1" and "orth" in args.objective:
        print("NOTE: scoring a +orth artefact with the switch OFF gives a "
              "different layout (CLAUDE.md).\n")

    hdr = f"{'artefact':34s} {'before':>16s}  {'after':>16s}  delta"
    print(hdr); print("-" * len(hdr))
    fam_before, fam_after = collections.Counter(), collections.Counter()
    tot_b = tot_a = 0
    for prog in PROGRAMMES:
        d = REPO / "examples" / prog
        for s in range(args.seeds):
            f = d / f"coldstart-{args.objective}-500000-s{s}.dom"
            if not f.is_file():
                continue
            vb, fb = score(f, d, allow_sahn=True)
            va, fa = score(f, d, allow_sahn=False)
            fam_before.update(_family(x) for x in fb)
            fam_after.update(_family(x) for x in fa)
            tot_b += len(fb); tot_a += len(fa)
            mark = "" if len(fa) == len(fb) else f"  {len(fa) - len(fb):+d}"
            print(f"{prog + ' s' + str(s):34s} {len(fb):3d}f {vb:8.5f}  "
                  f"{len(fa):3d}f {va:8.5f}{mark}")

    print(f"\ntotal: {tot_b} -> {tot_a} fails ({tot_a - tot_b:+d})")
    moved = {k for k in set(fam_before) | set(fam_after)
             if fam_before[k] != fam_after[k]}
    if not moved:
        print("no fail family changed.")
        return 0
    print("\nfamilies that moved:")
    for k in sorted(moved, key=lambda k: -abs(fam_after[k] - fam_before[k])):
        print(f"  {fam_before[k]:4d} -> {fam_after[k]:4d}  ({fam_after[k] - fam_before[k]:+d})  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
