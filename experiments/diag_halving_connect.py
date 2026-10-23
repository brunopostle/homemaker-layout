"""Does a race keep, make or lose connected storeys? (DESIGN.md §39.159, §39.167)

For every candidate of a successive-halving work directory, counts the
storeys failing `level N not connected` in its seed and after each stage it
ran, and tallies, stage by stage, the candidates that JOINED a storey
(fewer than the stage before) and those that LOST one (more).

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_halving_connect.py \
        ~/halving-maple-spine experiments/results/halving-maple-spine --programme maple-court

The seed directory holds `<candidate>.dom`; a stage's `out.dom` is
`<work>/s<k>/<candidate>/out.dom`.
"""
import argparse, copy, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, geometry  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402


def unconnected(fit, path):
    r = dom.load(str(path)); dom.link(r); geometry.clear_cache()
    _, fails = fit.score_with_fails(copy.deepcopy(r))
    return sum(1 for f in fails if f.endswith(" not connected"))


ap = argparse.ArgumentParser()
ap.add_argument("work")
ap.add_argument("seeds")
ap.add_argument("--programme", default="maple-court")
a = ap.parse_args()
if not geometry.ORTHOGONAL_DIVISION:
    sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
fit = Fitness(*load_config(REPO / "examples" / a.programme))
work, seeds = Path(a.work), Path(a.seeds)
stages = sorted((int(p.name[1:]), p) for p in work.glob("s[0-9]*"))
hist = {}
for f in sorted(seeds.glob("*.dom")):
    if f.stem == "winner":
        continue
    row = [unconnected(fit, f)]
    for k, d in stages:
        o = d / f.stem / "out.dom"
        if not o.exists():
            break
        row.append(unconnected(fit, o))
    hist[f.stem] = row
    print(f"  {f.stem:12s} " + " -> ".join(map(str, row)), flush=True)

arm = lambda n: n.rsplit("-", 1)[0]
print("\nseed: candidates with every storey connected, by arm")
for g, c in sorted(Counter(arm(n) for n, r in hist.items() if r[0] == 0).items()):
    print(f"  {g}: {c} of {sum(1 for n in hist if arm(n) == g)}")
print("\nstage: ran / joined a storey / lost a storey / all connected after")
for i, (k, _) in enumerate(stages, start=1):
    ran = [r for r in hist.values() if len(r) > i]
    j = sum(r[i] < r[i - 1] for r in ran); l = sum(r[i] > r[i - 1] for r in ran)
    print(f"  s{k}: {len(ran)} / {j} / {l} / {sum(r[i] == 0 for r in ran)}")
