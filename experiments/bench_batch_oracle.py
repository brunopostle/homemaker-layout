#!/usr/bin/env python3
"""Validate and benchmark the batched oracle (homemaker-py-av5).

Copies the 35-file programme-house corpus into a scratch directory, scores
every file via single-file oracle calls and again via one batched invocation,
then checks the per-file fitness and failure sets are identical and reports
measured s/dom for both modes.
"""

from __future__ import annotations

import math
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import oracle  # noqa: E402

URB = Path("/home/bruno/src/urb")
CORPUS = URB / "examples" / "programme-house"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bench_batch_") as tmp:
        scratch = Path(tmp)
        shutil.copy(CORPUS / "patterns.config", scratch)
        doms = sorted(CORPUS.glob("*.dom"))
        paths = [shutil.copy(d, scratch) for d in doms]
        paths = [Path(p) for p in paths]
        print(f"{len(paths)} corpus files -> {scratch}")

        t0 = time.perf_counter()
        singles = [oracle.score(p, URB) for p in paths]
        t_single = time.perf_counter() - t0

        t0 = time.perf_counter()
        batch = oracle.score_batch(paths, URB)
        t_batch = time.perf_counter() - t0

        # Urb's score is nondeterministic at the ~1 ULP level (Perl hash-order
        # summation), so compare fitness with a tight relative tolerance; any
        # real semantic difference (e.g. occlusion handling) would be far larger.
        mismatches = 0
        for p, s, b in zip(paths, singles, batch):
            if not math.isclose(s.fitness, b.fitness, rel_tol=1e-12) or s.fail_lines != b.fail_lines:
                mismatches += 1
                print(f"MISMATCH {p.name}: single {s.fitness:.12g} ({s.n_fails} fails) "
                      f"vs batch {b.fitness:.12g} ({b.n_fails} fails)")
                print(f"  single-only: {sorted(set(s.fail_lines) - set(b.fail_lines))}")
                print(f"  batch-only:  {sorted(set(b.fail_lines) - set(s.fail_lines))}")

        n = len(paths)
        print(f"\nsingle-file: {t_single:.2f} s total, {t_single / n:.3f} s/dom")
        print(f"batched:     {t_batch:.2f} s total, {t_batch / n:.3f} s/dom")
        print(f"speedup:     x{t_single / t_batch:.2f}")
        if mismatches:
            print(f"\nFAIL: {mismatches}/{n} files differ between single and batch")
            return 1
        print(f"\nOK: all {n} files identical (fitness to 1e-12 rel, exact failure set) in both modes")
        return 0


if __name__ == "__main__":
    sys.exit(main())
