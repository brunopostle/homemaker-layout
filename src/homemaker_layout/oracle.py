"""Phase-1 fitness oracle: score ``.dom`` files via Urb's ``urb-fitness.pl``.

This is the only throwaway component. It shells out to the Perl evaluator so we
can validate the Python search core against the trusted fitness before porting
fitness to Python (Phase 3). ``urb-fitness.pl`` reads ``patterns.config`` from
its working directory, so the ``.dom`` must live beside the programme config.

``urb-fitness.pl`` accepts many ``.dom`` paths per invocation; ``score_batch``
exploits this so the ~0.65 s Perl startup amortises across a generation
(DESIGN.md §4.6: ~0.99 s/dom batched vs ~1.65 s/dom single). Note the Perl
script computes the occlusion field from the *first* dom in a batch and reuses
it for the rest; ``experiments/bench_batch_oracle.py`` verifies this leaves
corpus scores identical to single-file calls.

Two flavours of Urb-side nondeterminism to know about (both from Perl's
per-process hash-order randomisation, neither a batching artifact): ``.fails``
line *order* varies between runs (use ``Score.fail_lines``), and the score
itself can flip by ~1 ULP. Compare fitness with a relative tolerance
(``math.isclose(..., rel_tol=1e-12)``), never ``==``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

DEFAULT_URB_ROOT = Path("/home/bruno/src/urb")


@dataclass
class Score:
    fitness: float
    fails: str  # raw .fails content (YAML and/or plain lines)

    @property
    def fail_lines(self) -> tuple[str, ...]:
        """Failure messages as a sorted tuple — Perl's per-process hash-order
        randomisation shuffles the raw ``.fails`` line order between runs, so
        comparisons must be order-insensitive."""
        return tuple(
            sorted(line.strip() for line in self.fails.splitlines() if line.strip() and line.strip() != "---")
        )

    @property
    def n_fails(self) -> int:
        return len(self.fail_lines)


def score_batch(
    dom_paths: Sequence[str | Path], urb_root: str | Path = DEFAULT_URB_ROOT
) -> list[Score]:
    """Score many ``.dom`` files in one ``urb-fitness.pl`` invocation.

    All files must live in the same directory (the working directory, where
    ``patterns.config`` is found). Results are returned in input order.
    """
    paths = [Path(p).resolve() for p in dom_paths]
    if not paths:
        return []
    cwd = paths[0].parent
    for p in paths:
        if p.parent != cwd:
            raise ValueError(f"batch spans directories: {p} not in {cwd}")
        Path(f"{p}.score").unlink(missing_ok=True)
        Path(f"{p}.fails").unlink(missing_ok=True)

    urb_root = Path(urb_root).resolve()
    env = {**os.environ, "DEBUG": "1"}
    proc = subprocess.run(
        ["perl", f"-I{urb_root}/lib", str(urb_root / "bin" / "urb-fitness.pl")]
        + [p.name for p in paths],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )

    results = []
    for p in paths:
        score_file = Path(f"{p}.score")
        if not score_file.exists():
            raise RuntimeError(
                f"urb-fitness.pl produced no score for {p}\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        fails_file = Path(f"{p}.fails")
        results.append(
            Score(
                fitness=float(score_file.read_text().strip()),
                fails=fails_file.read_text() if fails_file.exists() else "",
            )
        )
    return results


def score(dom_path: str | Path, urb_root: str | Path = DEFAULT_URB_ROOT) -> Score:
    return score_batch([dom_path], urb_root)[0]
