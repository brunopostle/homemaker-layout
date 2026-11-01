"""Do swaps between neighbouring cells survive the scorer's relabelling, and are
they better than swaps between cells chosen at random? (`homemaker-py-8wgz`)

The arms: two neighbours by what they hold (room-room, room-C, room-O, C-O), two
unconnected cells of a storey as the control, and three and four connected cells.
Same reading as `diag_urzf_label_moves.py`, §39.154: `undone` means the scorer
relabelled the child back to the parent's labels. Then, on a sample, the fails
added before and after a short re-tune. Designs held with labels written back,
as a search holds them. Reads committed artefacts and changes nothing.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_swap_cells.py [--stamp S] [--solve 40]
"""
import argparse
import copy
import importlib.util as iu
import statistics as st
from collections import defaultdict
from pathlib import Path

import numpy as np

from homemaker_layout import dom, driver, geometry, innerloop, operators

REPO = Path(__file__).resolve().parent.parent
s = iu.spec_from_file_location("urzf", REPO / "experiments" / "diag_urzf_label_moves.py")
urzf = iu.module_from_spec(s)
s.loader.exec_module(urzf)


def kind(t):
    return t if dom.is_generic(t) else "room"


def draws(lvl, li, rng, n):
    """Yield (arm, cells of this storey) up to about ``n`` per arm."""
    leaves = [lf for lf in lvl.leaves() if lf.type != dom.GENERIC_STAIR]
    if len(leaves) < 2:
        return
    g = geometry.leaf_graph(lvl)
    for _ in range(n):
        a = operators._pick(rng, leaves)
        for k in (2, 3, 4):
            cells = operators._adjacent_cells(lvl, a, k, rng)
            if len(cells) == k and len({c.type for c in cells}) > 1:
                kinds = {kind(c.type) for c in cells}
                arm = (f"adj {'-'.join(sorted(kind(c.type) for c in cells))}" if k == 2
                       else f"adj {k} {'all rooms' if kinds == {'room'} else 'mixed'}")
                yield arm, [c.id for c in cells]
        far = [b for b in leaves if b is not a and not g.has_edge(a, b) and b.type != a.type]
        if far:
            b = operators._pick(rng, far)
            both = "room-room" if {kind(a.type), kind(b.type)} == {"room"} else "mixed"
            yield f"RANDOM far {both}", [a.id, b.id]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stamp", default="4428262+orth")
    ap.add_argument("--n", type=int, default=6, help="start cells per storey per design")
    ap.add_argument("--solve", type=int, default=0, help="re-tune this many draws per arm")
    ap.add_argument("--budget", type=int, default=200)
    ap.add_argument("--doms", nargs="*", help="these maple-court designs instead of the corpus, e.g. mid-race")
    a = ap.parse_args()
    for prog_name in (["maple-court"] if a.doms else urzf.PROGRAMMES):
        prog = REPO / "examples" / prog_name
        fit = driver._fitness_for(str(prog), leaf_sharing=True, collapse_insearch=True)
        stats = defaultdict(lambda: defaultdict(int))
        added = defaultdict(list)
        tuned = defaultdict(list)
        rng = np.random.default_rng(0)
        for path in a.doms or sorted(prog.glob(f"coldstart-{a.stamp}-500000-s*.dom")):
            parent = urzf.held(path, fit)
            pl, pf = urzf.scored(parent, fit)
            for li, lvl in enumerate(dom.levels(parent)):
                geometry.clear_cache()
                for arm, ids in list(draws(lvl, li, rng, a.n)):
                    child = operators._finalise(copy.deepcopy(parent))
                    cs = [dom.levels(child)[li].by_id(i) for i in ids]
                    names = [c.type for c in cs]
                    for c, t in zip(cs, names[-1:] + names[:-1]):
                        c.type = t
                    operators._finalise(child)
                    geometry.clear_cache()
                    k, d = urzf.classify(parent, pl, pf, child, "x", fit)
                    stats[arm][k] += 1
                    if k == "relabel":
                        added[arm].append(d)
                        if len(tuned[arm]) < a.solve:
                            innerloop.optimise(child, str(prog), budget=a.budget, method="nm")
                            geometry.clear_cache()
                            tuned[arm].append(urzf.scored(child, fit)[1] - pf)
        print(prog_name)
        for arm in sorted(stats):
            t = sum(stats[arm].values())
            v, w = added[arm], tuned[arm]
            print(f"  {arm:26} {t:5} draws, undone {stats[arm]['undone'] / t:4.0%}; survivors "
                  f"fails added median {st.median(v) if v else '-'}, better "
                  f"{sum(x < 0 for x in v)}, level {sum(x == 0 for x in v)}, worse "
                  f"{sum(x > 0 for x in v)}"
                  + (f"; retuned {len(w)}: median {st.median(w)}, no worse "
                     f"{sum(x <= 0 for x in w)}" if w else ""), flush=True)


if __name__ == "__main__":
    main()
