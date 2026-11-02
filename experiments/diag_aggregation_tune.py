"""Re-tune one design's walls under each candidate aggregation and look at the
rooms it builds (`homemaker-py-5fje`, DESIGN.md §39.200).

`diag_aggregation.py` can only rank designs that TODAY's search produced, so
it cannot see what another objective would reward. This holds the topology
fixed and runs the inner loop (`innerloop.optimise`, which compares on score
alone) with `Fitness.score_with_fails` replaced by one arm's score, the real
fail list unchanged. Every arm starts from the design's own ratios with the
same budget, A0 included, so A0 is the control for "more tuning".

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_aggregation_tune.py \\
        --budget 2000 --arms A0,P1,P2 --phi 1e-20 DESIGN.dom ...

A floor PHI makes a factor flat below it, so a room far under its target has
no gradient back; a tiny PHI (1e-20, about 9.6 sigma) keeps one, and then the
log of a gaussian factor is minus half its squared z-score: P1 becomes a
least-squares fit of every room to its brief.
"""
import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diag_aggregation import arms  # noqa: E402
from diag_shrunk_rooms import KEYS  # noqa: E402
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, fitness, geometry, innerloop, programme  # noqa: E402


def rooms_line(root, reqs, codes):
    area = {}
    for lvl in dom.levels(root):
        for leaf in lvl.leaves():
            if leaf.type in codes:
                area.setdefault(leaf.type, []).append(round(geometry.area(leaf)))
    return " ".join(f"{c}={sorted(area.get(c, []))}" for c in codes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("designs", nargs="+")
    ap.add_argument("--arms", default="A0,P1,P2")
    ap.add_argument("--phi", type=float, default=1e-20)
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--method", default="nm")
    ap.add_argument("--out", help="directory to write each tuned design to")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    real = fitness.Fitness.score_with_fails
    for path in a.designs:
        prog = next(v for k, v in KEYS.items() if k in path)
        d = REPO / "examples" / prog
        reqs = programme.load_programme_dir(str(d))
        big = sorted((c for c, r in reqs.items() if not dom.is_generic(c)),
                     key=lambda c: -reqs[c].size)[:5]
        fit = fitness.Fitness(*load_config(d))
        base = dom.load(path)
        dom.link(base)
        r0 = arms(fit, reqs, base, a.phi)
        print(f"\n== {path}\n  as found: fails {r0['fails']} token {r0['token']} "
              f"A0 {r0['A0']:.4g} P1 {r0['P1']:.4g} P2 {r0['P2']:.4g}\n"
              f"    {rooms_line(base, reqs, big)}", flush=True)
        for arm in a.arms.split(","):
            def score_with_fails(self, root, _arm=arm):
                if _arm == "A0":
                    return real(self, root)
                fitness.Fitness.score_with_fails = real
                try:
                    r = arms(self, reqs, root, a.phi)
                finally:
                    fitness.Fitness.score_with_fails = score_with_fails
                return r[_arm], r["fail_lines"]
            root = copy.deepcopy(base)
            dom.link(root)
            fitness.Fitness.score_with_fails = score_with_fails
            try:
                innerloop.optimise(root, d, budget=a.budget, method=a.method)
            finally:
                fitness.Fitness.score_with_fails = real
            r = arms(fit, reqs, root, a.phi)
            print(f"  tuned {arm}: fails {r['fails']} token {r['token']} missing {r['missing']} "
                  f"A0 {r['A0']:.4g} P1 {r['P1']:.4g} P2 {r['P2']:.4g}\n"
                  f"    {rooms_line(root, reqs, big)}", flush=True)
            if a.out:
                Path(a.out).mkdir(parents=True, exist_ok=True)
                out = Path(a.out) / f"{Path(path).stem}-{arm}.dom"
                out.write_text(dom.dumps(root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
