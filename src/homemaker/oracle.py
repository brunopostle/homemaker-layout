"""Phase-1 fitness oracle: score a ``.dom`` via Urb's ``urb-fitness.pl``.

This is the only throwaway component. It shells out to the Perl evaluator so we
can validate the Python search core against the trusted fitness before porting
fitness to Python (Phase 2). ``urb-fitness.pl`` reads ``patterns.config`` from
its working directory, so the ``.dom`` must live beside the programme config.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_URB_ROOT = Path("/home/bruno/src/urb")


@dataclass
class Score:
    fitness: float
    fails: str  # raw .fails content (YAML and/or plain lines)

    @property
    def n_fails(self) -> int:
        return sum(1 for line in self.fails.splitlines() if line.strip() and line.strip() != "---")


def score(dom_path: str | Path, urb_root: str | Path = DEFAULT_URB_ROOT) -> Score:
    dom_path = Path(dom_path).resolve()
    urb_root = Path(urb_root).resolve()
    score_file = Path(f"{dom_path}.score")
    fails_file = Path(f"{dom_path}.fails")
    for f in (score_file, fails_file):
        f.unlink(missing_ok=True)

    env = {**os.environ, "DEBUG": "1"}
    proc = subprocess.run(
        ["perl", f"-I{urb_root}/lib", str(urb_root / "bin" / "urb-fitness.pl"), dom_path.name],
        cwd=dom_path.parent,
        env=env,
        capture_output=True,
        text=True,
    )
    if not score_file.exists():
        raise RuntimeError(
            f"urb-fitness.pl produced no score for {dom_path}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    fitness = float(score_file.read_text().strip())
    fails = fails_file.read_text() if fails_file.exists() else ""
    return Score(fitness=fitness, fails=fails)
