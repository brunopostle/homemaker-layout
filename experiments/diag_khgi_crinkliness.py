"""`homemaker-py-khgi`: what the crinkliness family looks like once a wall is
counted once.

DESIGN.md §39.95 fixed `Fitness.area_outside`, which had credited a neighbour's
wall twice wherever two cells also met end to end and rounding fell above zero.
Every crinkliness figure in DESIGN.md before that -- §39.12's 35%, §39.13's
"112 of 430 fail, 69% of the residual buried", §39.82's 45.2%, §39.89's 46.2%
-- was measured with the phantom walls in. This re-measures on the committed
artefacts, each corpus under its own convention, with the OLD rule put back
beside the new one, so the two columns differ by that rule and nothing else.

Per corpus: the leaves that carry a minimum-exposure requirement; how many
fail it; how many of those are BURIED (no daylit wall at all, the population
§39.13/§39.68 found no re-weighting can reach); and, for the leaves that only
the correct count fails, how much of the wall they need they actually have.

    python experiments/diag_khgi_crinkliness.py
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, geometry as g  # noqa: E402
from homemaker_layout.fitness import (  # noqa: E402
    FAIL_THRESHOLD, Fitness, _height, _perimeter, load_config)

PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
STAMPS = ("055d710", "99c85ec", "c836457+orth", "1138ff1+orth", "07b2058+orth",
          "1a24b6a+orth")


def urb_area_outside(self, leaf, G, groups):
    """`Urb::Dom::Area_Outside` as ported until §39.95: the neighbour's width
    once per boundary with `Overlap() > 0`."""
    length = 0.0
    for nb in G.neighbors(leaf):
        if not dom.is_outside(nb) or dom.is_covered(nb):
            continue
        for contributors in groups.values():
            if g.boundary_pair_overlap(contributors, leaf, nb) > 0:
                length += G[leaf][nb]["width"]
    perimeter = _perimeter(leaf)
    for e in range(4):
        bid = g.boundary_id(leaf, e)
        if bid in g._EXTERNAL and (perimeter.get(bid) or "").lower() \
                not in ("private", "fortified"):
            length += g.edge_length(leaf, e)
    return length * _height(leaf)


def leaves_of(path: Path, prog: Path, rule) -> dict:
    """{(storey, corners): (type, crinkliness, quality, n_fails)} for every leaf
    with a minimum-exposure requirement, scored under `rule` (None = shipped)."""
    conf, cost = load_config(prog)
    fit = Fitness(conf, cost)
    out: dict = {}
    orig_q, orig_a = Fitness.quality_uncrinkliness, Fitness.area_outside

    def spy(self, leaf, G, groups):
        q = orig_q(self, leaf, G, groups)
        if self.crinkliness_params(leaf) is not None and not (
                dom.is_outside(leaf) and not dom.is_covered(leaf)):
            c = g.centroid(leaf)
            out[(dom.level_of(leaf), round(c[0], 3), round(c[1], 3))] = (
                leaf.type, self.crinkliness(leaf, G, groups),
                self.crinkliness_params(leaf)[0], q)
        return q

    Fitness.quality_uncrinkliness = spy
    if rule is not None:
        Fitness.area_outside = rule
    try:
        _, fails = fit.score_with_fails(dom.load(str(path)))
    finally:
        Fitness.quality_uncrinkliness, Fitness.area_outside = orig_q, orig_a
    g.clear_cache()
    return out, fails


def main() -> int:
    print(f"{'corpus':14} {'leaves':>6}  {'fail old':>8} {'buried':>7}   "
          f"{'fail new':>8} {'buried':>7}   {'all fails old -> new':>20}   crinkliness share")
    newly_all = []
    for stamp in STAMPS:
        g.ORTHOGONAL_DIVISION = "+orth" in stamp
        t = collections.Counter()
        for name in PROGRAMMES:
            prog = REPO / "examples" / name
            for p in sorted(prog.glob(f"coldstart-{stamp}-500000-s*.dom")):
                old, f_old = leaves_of(p, prog, urb_area_outside)
                new, f_new = leaves_of(p, prog, None)
                t["leaves"] += len(new)
                t["fails old"] += len(f_old)
                t["fails new"] += len(f_new)
                t["crink old"] += sum("crinkliness" in f for f in f_old)
                t["crink new"] += sum("crinkliness" in f for f in f_new)
                for key, (ty, crink, target, q) in new.items():
                    failing = q < FAIL_THRESHOLD
                    was = old.get(key, (None, 0, 0, 1.0))[3] < FAIL_THRESHOLD
                    t["fail new"] += failing
                    t["buried new"] += failing and not crink
                    t["fail old"] += was
                    t["buried old"] += was and not old[key][1]
                    if failing and not was:
                        # exposure it has, over the exposure it needs: the
                        # factor's target is 1/crink, so this is target*crink
                        newly_all.append((stamp, name, ty, crink * target,
                                          old[key][1] * target))
        print(f"{stamp:14} {t['leaves']:6d}  {t['fail old']:8d} {t['buried old']:7d}   "
              f"{t['fail new']:8d} {t['buried new']:7d}   "
              f"{t['fails old']:8d} -> {t['fails new']:<8d}   "
              f"{100 * t['crink old'] / t['fails old']:.1f}% -> "
              f"{100 * t['crink new'] / t['fails new']:.1f}%")
    print(f"\n{len(newly_all)} leaves fail only under the correct count. "
          "Share of the exposure they need that they really have:")
    bins = collections.Counter()
    for *_, have, _ in newly_all:
        bins["under 40%" if have < 0.4 else "40-60%" if have < 0.6
             else "60-80%" if have < 0.8 else "80%+"] += 1
    for k in ("under 40%", "40-60%", "60-80%", "80%+"):
        print(f"  {k:10} {bins[k]}")
    by = collections.Counter(n for _, n, *_ in newly_all)
    print("  by programme:", dict(by))
    buried = sum(1 for *_, have, _ in newly_all if have == 0)
    print(f"  buried (no daylit wall at all): {buried}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
