"""What a light well does to the design it is cut into (`homemaker-py-evxm`).

`operators.mutate_light_well` slices a strip of outdoor space off a cell that
no daylight reaches, on its storey and every storey above. This applies it to
every corpus design that has such a cell and tunes the child exactly as the
search would (`driver._evaluate`), beside the parent tuned for the same
evaluations and no move (`retune` -- what a declined draw is, §39.120):

    80     one child's budget: what the comparator would be shown
    400    five children's worth: can the cell that paid for the well recover?

Per child: fails, and the daylight (`crinkliness`) and `size` fails among
them. Paired against `retune` through `ab_report`, one pair per draw.

What it cannot say: whether a search keeps such a child and builds on it. A
well is a trade -- light for floor -- and a comparator that counts fails
judges the trade at the moment it is made.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 PYTHONPATH=src \\
        python experiments/diag_evxm_light_well.py [--draws 4] [--budgets 80 400]
"""

from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import importlib.util
import sys
from pathlib import Path

import numpy as np

from homemaker_layout import dom, driver, geometry, innerloop, operators, programme

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="coldstart-1a24b6a+orth-500000-s*.dom")
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--draws", type=int, default=4)
    ap.add_argument("--budgets", type=int, nargs="+", default=[80, 400])
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    shaft, ab = _load("diag_8b2u_fixed_shaft"), _load("ab_report")
    search = shaft.SEARCH

    def tuned(tree, prog, x0, budget):
        root = copy.deepcopy(tree)
        dom.link(root)
        geometry.clear_cache()
        ind, _ = driver._evaluate(root, str(prog), x0, budget, {}, "evxm", **search)
        fams = collections.Counter(f.split()[-1] if "/" in f.split()[0] else f
                                   for f in ind.fails)
        return {"fails": ind.n_fails, "score": ind.fitness,
                "light": fams["crinkliness"], "size": fams["size"],
                "width": fams["width"], "prop": fams["proportion"]}

    rows = []
    for name in a.programme or PROGRAMMES:
        prog = REPO / "examples" / name
        reqs = programme.load_programme_dir(str(prog))
        for p in sorted(prog.glob(a.corpus)):
            parent = dom.load(str(p))
            dom.link(parent)
            geometry.clear_cache()
            ratios = innerloop.ratio_map(parent)
            px = innerloop.warm_x0(parent, ratios)
            retune = {b: tuned(parent, prog, px, b) for b in a.budgets}
            rng = np.random.default_rng(int.from_bytes(
                hashlib.blake2b(f"{name}/{p.name}".encode(), digest_size=8).digest(), "little"))
            got = tries = 0
            while got < a.draws and tries < a.draws * 4:
                tries += 1
                child, desc = operators.mutate_light_well(parent, rng, [], reqs=reqs)
                if "noop" in desc:
                    continue
                got += 1
                dom.link(child)
                geometry.clear_cache()
                x0 = innerloop.warm_x0(child, {**innerloop.ratio_map(child), **ratios})
                row = {"programme": name, "design": p.name[-8:-4], "desc": desc,
                       "retune": retune, "well": {b: tuned(child, prog, x0, b) for b in a.budgets}}
                rows.append(row)
                print(f"  {name}/{row['design']} {desc}: " + "  ".join(
                    f"@{b} fails {retune[b]['fails']}->{row['well'][b]['fails']} "
                    f"light {retune[b]['light']}->{row['well'][b]['light']}"
                    for b in a.budgets), file=sys.stderr, flush=True)
            if not got:
                print(f"  {name}/{p.name[-8:-4]}: no buried cell with a clear column",
                      file=sys.stderr, flush=True)

    if not rows:
        print("the move fired nowhere")
        return 1
    print(f"\n{len(rows)} wells cut ({a.draws} draws per design, {a.corpus})")
    for g in ("ALL", *dict.fromkeys(r["programme"] for r in rows)):
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        print(f"\n== {g}: {len(sel)} wells")
        for b in a.budgets:
            n = len(sel)
            mean = lambda arm, k: sum(r[arm][b][k] for r in sel) / n   # noqa: E731
            print(f"  after {b} evaluations      retune -> with a well")
            for k, lab in (("fails", "fails"), ("light", "daylight"), ("size", "size"),
                           ("width", "width"), ("prop", "proportion")):
                print(f"    {lab:<12} {mean('retune', k):7.2f} -> {mean('well', k):7.2f}")
            beat = sum(r["well"][b]["fails"] < r["retune"][b]["fails"]
                       or (r["well"][b]["fails"] == r["retune"][b]["fails"]
                           and r["well"][b]["score"] > r["retune"][b]["score"]) for r in sel)
            print(f"    the child beats its re-tuned parent: {beat} of {n}")
            if n >= 2:
                for k, lab in (("fails", "fails"), ("light", "daylight fails")):
                    print(f"    {lab}, paired (a W is the well LOWER):")
                    print(ab.format_report(ab.paired_report(
                        [float(r["retune"][b][k]) for r in sel],
                        [float(r["well"][b][k]) for r in sel], "retune", "well"), indent="      "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
