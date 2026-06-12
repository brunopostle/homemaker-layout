#!/usr/bin/env python3
"""Re-baseline the corpus under URB_NO_OCCLUSION=1 (homemaker-py-gp2).

Occlusion/daylight is disabled in Urb behind the URB_NO_OCCLUSION env flag
(daylight -> 1 everywhere, CIEsky illumination factor pinned to 1, i.e.
simple crinkliness). Flipping the flag changes every score, so this script
records the new baseline in one pass:

  - per-file flag-on vs flag-off score and failure-set deltas (35 corpus files)
  - batched oracle throughput under the flag

Run the inner-loop reference gains separately:
  URB_NO_OCCLUSION=1 python3 experiments/accept_innerloop.py 400 cma
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker import oracle  # noqa: E402

URB = Path("/home/bruno/src/urb")
CORPUS = URB / "examples" / "programme-house"


def score_corpus(paths: list[Path], flag: bool) -> tuple[list[oracle.Score], float]:
    os.environ.pop("URB_NO_OCCLUSION", None)
    if flag:
        os.environ["URB_NO_OCCLUSION"] = "1"
    t0 = time.perf_counter()
    scores = oracle.score_batch(paths, URB)
    return scores, time.perf_counter() - t0


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rebaseline_") as tmp:
        scratch = Path(tmp)
        shutil.copy(CORPUS / "patterns.config", scratch)
        paths = [Path(shutil.copy(d, scratch)) for d in sorted(CORPUS.glob("*.dom"))]

        off, t_off = score_corpus(paths, flag=False)
        on, t_on = score_corpus(paths, flag=True)

        n_changed_score = n_changed_fails = 0
        print(f"{'file':42s} {'flag-off':>12s} {'flag-on':>12s} {'ratio':>7s}  fails off->on")
        for p, a, b in zip(paths, off, on):
            score_changed = not math.isclose(a.fitness, b.fitness, rel_tol=1e-9)
            fails_changed = a.fail_lines != b.fail_lines
            n_changed_score += score_changed
            n_changed_fails += fails_changed
            ratio = b.fitness / a.fitness if a.fitness else float("inf")
            mark = "*" if fails_changed else " "
            print(f"{p.name:42s} {a.fitness:12.6g} {b.fitness:12.6g} {ratio:7.3f}  "
                  f"{a.n_fails}->{b.n_fails}{mark}")

        n = len(paths)
        print(f"\nscore changed: {n_changed_score}/{n}   failure set changed: {n_changed_fails}/{n}")
        print(f"batched s/dom: flag-off {t_off / n:.3f}, flag-on {t_on / n:.3f} "
              f"(x{t_off / t_on:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
