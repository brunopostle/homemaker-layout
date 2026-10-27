"""What storey heights did a race's search choose? (`homemaker-py-y4p4.2`)

For every candidate of a successive-halving work directory, prints the
storey heights its seed started with and the ones its `out.dom` ended each
stage with, then, stage by stage, how many storeys sit at the brief's floor,
at its cap, and between. A race run without `--tune-heights` must print every
storey at the seed's height: that is the negative control, and
`--expect-fixed` turns it into an exit status.

    python experiments/diag_halving_heights.py ~/halving-harbor-heights \\
        experiments/results/halving-harbor-spine --programme harbor-house

The seed directory holds `<candidate>.dom`; a stage's `out.dom` is
`<work>/s<k>/<candidate>/out.dom`.
"""
import argparse, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, innerloop  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402


def heights(path) -> list[float]:
    return [round(lvl.height, 3) for lvl in dom.levels(dom.load(str(path)))]


ap = argparse.ArgumentParser()
ap.add_argument("work")
ap.add_argument("seeds")
ap.add_argument("--programme", default="harbor-house")
ap.add_argument("--expect-fixed", action="store_true",
                help="exit 1 if any storey moved from its seed's height")
a = ap.parse_args()
fit = Fitness(*load_config(REPO / "examples" / a.programme))
rule = innerloop.height_rule(fit.conf)
lo, hi = rule.snap(rule.lo), rule.snap(rule.hi)
work, seeds = Path(a.work), Path(a.seeds)
stages = sorted((int(p.name[1:]), p) for p in work.glob("s[0-9]*"))
moved = 0
tally = {k: Counter() for k, _ in stages}
names = sorted({d.name for _, s in stages for d in s.iterdir() if (d / "out.dom").exists()})
for name in names:
    seed = heights(seeds / f"{name}.dom")
    row = [seed]
    for k, s in stages:
        out = s / name / "out.dom"
        if not out.exists():
            break
        h = heights(out)
        row.append(h)
        # a storey the search adds copies a height, so 'moved' is a height
        # the seed does not have, whatever the storey count did
        moved += sum(1 for x in h if all(abs(x - y) > 1e-6 for y in seed))
        for x in h:
            tally[k]["floor" if x <= lo + 1e-6 else "cap" if x >= hi - 1e-6 else "between"] += 1
    print(f"  {name:12s} " + " -> ".join("/".join(f"{x:.3f}" for x in h) for h in row))

print(f"\nbrief: storeys {lo:g}-{hi:g} m")
print("stage: candidates / storeys at the floor / between / at the cap / mean height")
for k, s in stages:
    hs = [x for d in s.iterdir() if (d / "out.dom").exists() for x in heights(d / "out.dom")]
    t = tally[k]
    if hs:
        print(f"  s{k}: {sum(1 for d in s.iterdir() if (d / 'out.dom').exists())} / "
              f"{t['floor']} / {t['between']} / {t['cap']} / {sum(hs) / len(hs):.3f} m")
print(f"storeys that moved from their seed's height: {moved}")
if a.expect_fixed and moved:
    sys.exit(1)
