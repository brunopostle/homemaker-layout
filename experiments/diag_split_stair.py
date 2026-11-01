"""What does the owner's split of a long stair cost? (`homemaker-py-yd6t`, §39.193)

Takes each finished design with a shaft over `operators.LONG_STAIR_M`, applies
`mutate_split_stair` for each end and each long shaft, and scores it raw and after
the inner loop at the same topology. No search. A price for the move alone.

Expectations, written before the first run, on `single-2` and its continuations:

  1. the stair keeps its label at one path on every storey, at about 7 m, and every
     split leaves the rest `C`;
  2. no split costs a storey's connection: the two cells together are the old one;
  3. the fail count moves by -1 to +3, median 13 to 15: `rrrl`'s three `crinkliness`
     stay on the corridor, and the stair part may add its own;
  4. the score moves by no more than a factor of 2 either way, the other stair
     already holding the best-stair factor;
  5. the long double-loaded corridor stays, spelt `C`: the ruling relabels a use, it
     does not re-plan the range, so `diag_double_loaded.py` reads about the same.

`--keep` scans what the stair is left, as a check on `SPLIT_STAIR_KEEP_M`.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_split_stair.py \\
        experiments/results/halving-maple-single/winner.dom
"""
import argparse, copy, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diag_join_clean9 import family  # noqa: E402
from successive_halving import REPO, load_config  # noqa: E402
from collections import Counter  # noqa: E402
from homemaker_layout import dom, geometry, innerloop, operators  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402


KEEP = operators.SPLIT_STAIR_KEEP_M


def score(fit, root):
    dom.link(root); geometry.clear_cache()
    s, f = fit.score_with_fails(copy.deepcopy(root))
    geometry.clear_cache()
    return s, f


def fam(fails):
    return "; ".join(f"{k} {v}" for k, v in Counter(map(family, fails)).most_common())


def splits(root):
    """Every distinct child of the move, by its description."""
    seen = {}
    for seed in range(40):
        child, desc = operators.mutate_split_stair(root, np.random.default_rng(seed), [])
        if "noop" in desc:
            return {}
        seen.setdefault(desc, child)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("designs", nargs="+")
    ap.add_argument("--programme", default="maple-court")
    ap.add_argument("--budget", type=int, default=1000)
    ap.add_argument("--keep", type=float, nargs="*", help="scan these stair lengths, m, raw only")
    ap.add_argument("--out-dir", help="write the best tuned split of each design here")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    prog = REPO / "examples" / a.programme
    fit = Fitness(*load_config(prog))
    for path in a.designs:
        root = operators._finalise(dom.load(path))
        s0, f0 = score(fit, root)
        print(f"{path}: {len(f0)} fails, score {s0:.3g}\n    {fam(f0)}", flush=True)
        kids = splits(root)
        if not kids:
            print("    no long shaft the move will split")
            continue
        best = None
        for desc, child in sorted(kids.items()):
            s, f = score(fit, child)
            nc = sum(x.endswith(" not connected") for x in f)
            print(f"  {desc}: raw {len(f)} fails, {s:.3g}, not connected {nc}\n      {fam(f)}", flush=True)
            for keep in a.keep or ():
                operators.SPLIT_STAIR_KEEP_M = keep
                for seed in range(40):
                    k, d = operators.mutate_split_stair(root, np.random.default_rng(seed), [])
                    if d == desc:
                        sk, fk = score(fit, k)
                        print(f"      keep {keep:4.1f} m: {len(fk)} fails, {sk:.3g}")
                        break
                operators.SPLIT_STAIR_KEEP_M = KEEP
            res = innerloop.optimise(child, str(prog), budget=a.budget, method="nm")
            dom.link(child)
            s, f = score(fit, child)
            print(f"      tuned {a.budget}: {len(f)} fails, {s:.3g}\n      {fam(f)}", flush=True)
            if best is None or (len(f), -s) < best[:2]:
                best = (len(f), -s, child)
        if a.out_dir and best:
            out = Path(a.out_dir) / (Path(path).parent.name + "-" + Path(path).stem + "-split.dom")
            out.parent.mkdir(parents=True, exist_ok=True)
            dom.dump(best[2], str(out))
            print("    wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
