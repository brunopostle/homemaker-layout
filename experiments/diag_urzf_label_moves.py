"""Do label moves survive the scorer's own relabelling? (`homemaker-py-urzf`, DESIGN.md §39.154)

With label write-back the default (§39.153), a parent's labels ARE the scored
labels. The scorer still relabels a copy before it counts (`collapse_insearch`,
§39.130: a third of cells), so a move that only edits labels -- `retype`,
`swap`, `level_retype`, ... -- may be undone before it is ever scored. Such a
draw is not lost (the search re-tunes the child, so it acts as a re-tune), but
it is not the move it was drawn as.

For every committed design at the given stamp, with its labels written back as
a search would hold it, this applies each operator `--draws` times and sorts the
children:

* `noop`      -- the operator declined;
* `undone`    -- same cells, and after the scorer's relabelling the same labels
                 as the parent: the move vanished before scoring;
* `relabel`   -- same cells, different scored labels;
* `topology`  -- the cells themselves changed (a divide, an undivide, ...).

and reports the share of each, with the scored-fail delta for the last two. No
inner loop is run: a label move leaves every cut where it was, so what the
scorer sees is what the child would start its re-tune from.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_urzf_label_moves.py --draws 20
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_urzf_label_moves.py --self-test

`--self-test` is the negative control: an untouched copy must read `undone`,
and a child with a cell divided must read `topology`.
"""
from __future__ import annotations

import argparse
import copy
import inspect
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, driver, geometry, operators, programme  # noqa: E402

PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
LABEL_OPS = ("retype", "swap", "level_retype", "level_fix", "level_compound_fix",
             "place_missing", "reassign")
CONTROL_OPS = ("divide", "undivide")      # topology moves, for comparison


def cells(root):
    return [(li, lf.id) for li, lvl in enumerate(dom.levels(root)) for lf in lvl.leaves()]


def labels(root):
    return [lf.type for lvl in dom.levels(root) for lf in lvl.leaves()]


def scored(root, fit):
    """(labels after the scorer's relabelling, number of fails)."""
    t = copy.deepcopy(root)
    dom.link(t)
    driver.write_labels_back(t, fit)
    geometry.clear_cache()
    _, fails = fit.score_with_fails(copy.deepcopy(t))
    return labels(t), len(fails)


def classify(parent, p_labels, p_fails, child, desc, fit):
    if "noop" in desc:
        return "noop", 0
    if cells(child) != cells(parent):
        return "topology", scored(child, fit)[1] - p_fails
    c_labels, c_fails = scored(child, fit)
    if c_labels == p_labels:
        return "undone", c_fails - p_fails
    return "relabel", c_fails - p_fails


def held(path, fit):
    """The design as a search holds it: labels written back."""
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    driver.write_labels_back(root, fit)
    geometry.clear_cache()
    return root


def self_test(prog):
    fit = driver._fitness_for(str(prog), leaf_sharing=True, collapse_insearch=True)
    path = sorted(prog.glob("coldstart-4428262+orth-500000-s*.dom"))[0]
    parent = held(path, fit)
    pl, pf = scored(parent, fit)
    assert pl == labels(parent), "write-back is not a fixed point: the census premise fails"
    k, _ = classify(parent, pl, pf, copy.deepcopy(parent), "identity", fit)
    assert k == "undone", k
    child, desc = operators.mutate_divide(parent, np.random.default_rng(0), sorted(set(labels(parent))))
    k, _ = classify(parent, pl, pf, child, desc, fit)
    assert k in ("topology", "noop"), k
    print(f"self-test passed on {path.name}: write-back is a fixed point, "
          f"an untouched copy reads 'undone', a divide reads '{k}'")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", nargs="*", default=list(PROGRAMMES))
    ap.add_argument("--stamp", default="4428262+orth")
    ap.add_argument("--draws", type=int, default=20)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if os.environ.get("HOMEMAKER_ORTHOGONAL_DIVISION") != "1":
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    if a.self_test:
        self_test(REPO / "examples" / a.programme[0])
        return 0

    t0 = time.process_time()
    for prog_name in a.programme:
        prog = REPO / "examples" / prog_name
        fit = driver._fitness_for(str(prog), leaf_sharing=True, collapse_insearch=True)
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]
        stats = defaultdict(lambda: defaultdict(int))
        deltas = defaultdict(list)
        for path in sorted(prog.glob(f"coldstart-{a.stamp}-500000-s*.dom")):
            parent = held(path, fit)
            pl, pf = scored(parent, fit)
            for op_name in LABEL_OPS + CONTROL_OPS:
                op = operators.MUTATIONS[op_name]
                params = inspect.signature(op).parameters
                kw = {k: v for k, v in (("reqs", reqs), ("fit", fit)) if k in params}
                for seed in range(a.draws):
                    geometry.clear_cache()
                    try:
                        child, desc = op(parent, np.random.default_rng(seed), types, **kw)
                    except Exception:             # noqa: BLE001
                        stats[op_name]["raised"] += 1
                        continue
                    geometry.clear_cache()
                    k, d = classify(parent, pl, pf, child, desc, fit)
                    stats[op_name][k] += 1
                    if k in ("relabel", "topology"):
                        deltas[(op_name, k)].append(d)
        print(f"\n=== {prog_name}: {a.draws} draws x each design at {a.stamp}")
        print(f"  {'operator':20s} {'n':>4s} {'noop':>6s} {'undone':>7s} {'relabel':>8s} "
              f"{'topology':>9s}   fails, relabel / topology (mean; better / worse)")
        for op_name in LABEL_OPS + CONTROL_OPS:
            s = stats[op_name]
            n = sum(s.values())
            if not n:
                continue
            pct = lambda k: f"{100 * s[k] / n:5.0f}%"   # noqa: E731

            def dd(k):
                v = deltas[(op_name, k)]
                if not v:
                    return "-"
                return (f"{np.mean(v):+.2f}; {sum(x < 0 for x in v)}/{sum(x > 0 for x in v)}")
            print(f"  {op_name:20s} {n:4d} {pct('noop'):>6s} {pct('undone'):>7s} "
                  f"{pct('relabel'):>8s} {pct('topology'):>9s}   {dd('relabel')} / {dd('topology')}"
                  + (f"   raised {s['raised']}" if s["raised"] else ""))
    print(f"\nCPU {time.process_time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
