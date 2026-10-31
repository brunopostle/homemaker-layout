"""How often `mutate_pivot3` can fire, and what it does to a design before any
inner loop (homemaker-py-hjc5), the census §39.162 ran for the pivot.

Every option on the newest `+orth` artefact of each programme: score and fails
of the child against the parent, and, with --solve, the same after a short
Nelder-Mead on a sample. Reads committed artefacts and changes nothing.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_pivot3.py [--solve 12]
"""
import argparse
import copy
import glob
import statistics as st
from pathlib import Path

import numpy as np

from homemaker_layout import dom, fitness, geometry, innerloop, operators
from homemaker_layout.fitness_cmd import load_config

REPO = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--solve", type=int, default=0, help="also re-tune this many children per programme")
    ap.add_argument("--budget", type=int, default=400)
    args = ap.parse_args()
    rng = np.random.default_rng(0)
    for prog in ("programme-house", "harbor-house", "health-centre", "maple-court"):
        found = sorted(glob.glob(str(REPO / "examples" / prog / "coldstart-*+orth-500000-s*.dom")))
        newest = found[-1].split("coldstart-")[1].split("-500000")[0]
        d = REPO / "examples" / prog
        fit = fitness.Fitness(*load_config(d))
        ratios, dfails, tuned = [], [], []
        arts = [f for f in found if newest in f]
        for path in arts:
            root = operators._finalise(dom.load(path))
            ps, pf = fit.score_with_fails(root)
            lvls = dom.levels(root)
            opts = [(li, n.id, o) for li, n in operators._owned_branches(root)
                    for o in operators._pivot3_options(lvls, li, n)]
            kids = []
            for li, nid, (side, span) in opts:
                r = operators._finalise(copy.deepcopy(root))
                ls = dom.levels(r)
                operators._pivot3(ls, li, ls[li].by_id(nid), side, span)
                operators._finalise(r)
                geometry.clear_cache()
                s, f = fit.score_with_fails(r)
                ratios.append(s / ps if ps else 0.0)
                dfails.append(len(f) - len(pf))
                kids.append((r, len(pf), ps))
            for i in rng.permutation(len(kids))[:args.solve // max(1, len(arts))]:
                r, nf, ps_ = kids[i]
                res = innerloop.optimise(r, str(d), budget=args.budget, method="nm")
                geometry.clear_cache()
                tuned.append((len(fit.score_with_fails(r)[1]) - nf, res.fitness / ps_ if ps_ else 0.0))
        q = lambda v: [round(x, 3) for x in st.quantiles(v, n=4)] if len(v) > 1 else v
        print(f"{prog} {newest}: {len(arts)} designs, {len(ratios)} options; child/parent score "
              f"quartiles {q(ratios)}, better {sum(r > 1 for r in ratios)}; "
              f"fails delta quartiles {q(dfails)}, min {min(dfails)}, max {max(dfails)}")
        if tuned:
            print(f"   after {args.budget} NM on {len(tuned)}: fails delta median "
                  f"{st.median(t[0] for t in tuned)}, min {min(t[0] for t in tuned)}, "
                  f"no worse {sum(t[0] <= 0 for t in tuned)}; score ratio median "
                  f"{st.median(t[1] for t in tuned):.3f}")


if __name__ == "__main__":
    main()
