"""What letting the inner loop tune storey heights does to one design
(`homemaker-py-y4p4.2`, DESIGN.md §39.128).

Two arms from the same starting tree, the same number of evaluations of the
same optimiser: `walls` tunes the cuts as today, `walls+heights` tunes the
cuts and one height per storey, and `probe` does that after a coarse look up
and down each storey first (`innerloop.probe_heights`). The control matters because the starting
design has usually been tuned already, and more tuning alone finds something.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 PYTHONPATH=src \\
        python experiments/diag_y4p42_heights.py examples/harbor-house/hand2a.dom --budget 4000
"""

from __future__ import annotations

import argparse
import collections
import copy
import sys
import time
from pathlib import Path

from homemaker_layout import dom, geometry, innerloop


def family(line: str) -> str:
    return line.split()[-1] if "/" in line.split()[0] else line


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dom", type=Path)
    ap.add_argument("--budget", type=int, default=4000)
    ap.add_argument("--programme", type=Path, help="default: the design's own directory")
    ap.add_argument("--arm", choices=("walls", "walls+heights", "probe"), action="append")
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    prog = a.programme or a.dom.parent
    if not (prog / "patterns.config").exists():
        ap.error(f"no patterns.config in {prog}: pass --programme")
    for arm in a.arm or ("walls", "walls+heights", "probe"):
        root = dom.load(str(a.dom))
        dom.link(root)
        geometry.clear_cache()
        t0 = time.process_time()
        r = innerloop.optimise(root, str(prog), budget=a.budget, method="nm",
                               heights=arm != "walls", height_probe=arm == "probe")
        hs = [round(lvl.height, 2) for lvl in dom.levels(root)]
        fams = collections.Counter(family(f) for f in r.fail_lines)
        print(f"{arm:<14} fails {r.x0_n_fails} -> {r.n_fails}   score {r.x0_fitness:.3g} -> "
              f"{r.fitness:.3g}   storey heights {hs}   {time.process_time() - t0:.0f} CPU-s")
        print("   " + ", ".join(f"{k} x{v}" for k, v in fams.most_common()), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
