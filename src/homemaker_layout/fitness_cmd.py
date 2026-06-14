"""homemaker-fitness — native Python replacement for urb-fitness.pl.

Scores .dom files using the native fitness engine (fitness.Fitness) and writes
.score / .fails side-car files in the same format as urb-fitness.pl.

Usage (module):
  python -m homemaker_layout.fitness_cmd [dom1.dom dom2.dom ...]

When installed via pip install -e .:
  homemaker-fitness [dom1.dom dom2.dom ...]

If no arguments are given, all *.dom files in the current directory are scored.

Scoring is skipped for a file if its .score and .fails side-cars already exist
and are both newer than the .dom file and the config files — set FORCE_UPDATE=1
to override (matches urb-fitness.pl behaviour).

Score is written to <dom>.score as a 40-decimal-place float; failures are
written one-per-line to <dom>.fails.  Score is also printed to stderr.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

from . import dom as dom_mod
from . import geometry
from .fitness import Fitness, load_config


def _config_mtime(directory: Path) -> float:
    """Latest mtime of any patterns/costs config file visible to this directory."""
    mtime = 0.0
    for name in ("patterns.config", "costs.config"):
        for p in (directory.parent / name, directory / name):
            if p.is_file():
                t = p.stat().st_mtime
                if t > mtime:
                    mtime = t
    return mtime


def _should_score(dom_path: Path, config_mtime: float) -> bool:
    """Return True if the dom needs (re-)scoring."""
    if os.environ.get("FORCE_UPDATE") or os.environ.get("DEBUG"):
        return True
    score_p = Path(f"{dom_path}.score")
    fails_p = Path(f"{dom_path}.fails")
    if not score_p.exists() or not fails_p.exists():
        return True
    dom_mtime = dom_path.stat().st_mtime
    score_mtime = score_p.stat().st_mtime
    if score_mtime < dom_mtime or score_mtime < config_mtime:
        return True
    if fails_p.stat().st_mtime < dom_mtime:
        return True
    return False


def score_file(dom_path: Path, fitness: Fitness) -> float:
    """Score one .dom file, write side-cars, return score."""
    root = dom_mod.load(str(dom_path))
    geometry.clear_cache()
    score, failures = fitness.score_with_fails(root)

    score_str = f"{score:.40f}"
    score_p = Path(f"{dom_path}.score")
    score_p.unlink(missing_ok=True)
    score_p.write_text(score_str + "\n")

    fails_p = Path(f"{dom_path}.fails")
    fails_p.unlink(missing_ok=True)
    fails_p.write_text("\n".join(failures) + ("\n" if failures else ""))

    return score


def main(argv=None) -> int:
    args = (argv or sys.argv)[1:]

    cwd = Path.cwd()
    conf, cost = load_config(cwd)
    fitness = Fitness(conf, cost)
    cfg_mtime = _config_mtime(cwd)

    if args:
        dom_paths = [Path(a) for a in args if a.endswith(".dom")]
    else:
        dom_paths = sorted(cwd.glob("*.dom"))
        print("Calculating fitness for all files in current folder", file=sys.stderr)

    for dom_path in dom_paths:
        dom_path = Path(dom_path)
        if not dom_path.exists():
            print(f"File not found, skipping: {dom_path}", file=sys.stderr)
            continue
        if not _should_score(dom_path, cfg_mtime):
            continue
        try:
            score = score_file(dom_path, fitness)
        except Exception as exc:
            print(f"Error scoring {dom_path}: {exc}", file=sys.stderr)
            continue
        print(f"{score:.40f}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
