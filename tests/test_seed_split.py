"""The seeder's storey split (experiments/seed_from_catalogue.buckets, DESIGN.md §39.161)."""
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments"))

import seed_from_catalogue as sfc  # noqa: E402
from homemaker_layout import operators, programme  # noqa: E402


def _reqs():
    return programme.load_programme_dir(str(REPO / "examples" / "harbor-house"))


def _fullest(split, size, caps):
    return max(sum(size[c] for c in rooms) / cap for rooms, cap in zip(split, caps))


def test_capacity_split_places_every_room_once_and_keeps_levels():
    reqs = _reqs()
    prog = operators._programme_codes(reqs)
    want = Counter({c: r.count for c, r in prog.items()})
    caps = [300.0, 200.0, 100.0]
    split = sfc.buckets(reqs, 3, np.random.default_rng(0), caps)
    assert Counter(c for rooms in split for c in rooms) == want
    for li, rooms in enumerate(split):
        for c in rooms:
            assert prog[c].level in (None, li) or prog[c].level >= 3


def test_capacity_split_is_fuller_nowhere_than_the_round_robin():
    """Negative control: the round-robin, which ignores capacity, overflows."""
    reqs = _reqs()
    prog = operators._programme_codes(reqs)
    size = {c: float(r.size or 0) for c, r in prog.items()}
    caps = [320.0] * 3
    worst = {m: max(_fullest(sfc.buckets(reqs, 3, rng, caps if m else None), size, caps)
                    for rng in [np.random.default_rng(s) for s in range(50)])
             for m in (False, True)}
    assert worst[True] < worst[False]
    total = sum(size[c] * prog[c].count for c in prog)
    assert worst[True] <= total / sum(caps) + max(size.values()) / caps[0]
