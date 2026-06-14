#!/usr/bin/env python3
"""Genome round-trip fitness parity (homemaker-py-k2g acceptance).

decode(encode(load(f))) canonicalises dead fields (inherited-cut divisions,
below-linked rotations, internal types) that the corpus carries in drifted
form. This scores every original and its round-tripped twin through the
oracle and demands identical fitness (1e-12 rel, Urb's ~1-ULP jitter) and
identical failure sets.

Run under the go-forward fitness:  URB_NO_OCCLUSION=1 python3 experiments/genome_parity.py
"""

from __future__ import annotations

import math
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, genome, oracle  # noqa: E402

URB = Path("/home/bruno/src/urb")
CORPUS = URB / "examples" / "programme-house"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="genome_parity_") as tmp:
        scratch = Path(tmp)
        shutil.copy(CORPUS / "patterns.config", scratch)
        originals, twins = [], []
        for src in sorted(CORPUS.glob("*.dom")):
            o = Path(shutil.copy(src, scratch))
            t = scratch / ("rt_" + src.name)
            dom.dump(genome.decode(genome.encode(dom.load(str(src)))), str(t))
            originals.append(o)
            twins.append(t)

        s_orig = oracle.score_batch(originals, URB)
        s_twin = oracle.score_batch(twins, URB)

        bad = 0
        for o, a, b in zip(originals, s_orig, s_twin):
            if not math.isclose(a.fitness, b.fitness, rel_tol=1e-12) or a.fail_lines != b.fail_lines:
                bad += 1
                print(f"MISMATCH {o.name}: {a.fitness:.17g} ({a.n_fails} fails) vs "
                      f"{b.fitness:.17g} ({b.n_fails} fails)")
        n = len(originals)
        print(f"{'FAIL' if bad else 'OK'}: {n - bad}/{n} files fitness-identical "
              f"after genome round-trip")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
