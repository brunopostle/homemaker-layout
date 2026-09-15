"""Collapse slot order must not depend on how a code is spelled (§39.4, s34).

``collapse_global`` ordered its slots with ``sorted(slot_counts)`` -- by code
NAME -- and ``_best_assignment`` keeps the first permutation reaching the
maximum, so every tie was decided by that order. Renaming a code therefore
changed the collapse of an identical tree.

Width was masking it: with ``quality_width`` live on rooms the ties were rare
enough that ``test_scoring_is_invariant_under_programme_code_spelling`` passed.
The moment homemaker-py-2f1 flattened that factor the invariance broke, which is
how the bug surfaced. So the guard here deliberately runs with a term FLATTENED,
and does not depend on whether 2f1 has landed.
"""

from __future__ import annotations

import copy
import re
import shutil

import numpy as np
import pytest

from homemaker_layout import dom, driver, fitness, operators, programme
from homemaker_layout.fitness import _slot_order_key

from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
RENAME = {"cr1": "fr1", "of": "ao", "st1": "gs1", "st2": "gs2"}
pytestmark = pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                                reason="examples absent")


def _renamed_programme(tmp_path):
    dst = tmp_path / "hh"
    shutil.copytree(EXAMPLES / "harbor-house", dst)
    cfg = dst / "patterns.config"
    text = cfg.read_text()
    for old, new in RENAME.items():
        text = re.sub(rf"^(  ){re.escape(old)}:$", rf"\g<1>{new}:", text, flags=re.M)
    cfg.write_text(text)
    return dst


def test_the_key_ignores_the_name_until_everything_else_is_equal():
    """The name is the last element, so it decides only between codes whose
    specs are identical in every respect -- where the slots are interchangeable
    and the choice cannot change the result."""
    prog = {r.code: r for r in programme.load_programme_dir(
        str(EXAMPLES / "harbor-house")).values()}
    keys = {c: _slot_order_key(c, prog) for c in prog}
    # every key is (0, <structural tuple>, code)
    for c, k in keys.items():
        assert k[0] == 0 and k[2] == c
    structural = [k[1] for k in keys.values()]
    assert len(set(structural)) > 1, "expected the corpus to have distinct specs"


def test_slot_order_survives_renaming(tmp_path):
    src = {r.code: r for r in programme.load_programme_dir(
        str(EXAMPLES / "harbor-house")).values()}
    dst = {r.code: r for r in programme.load_programme_dir(
        str(_renamed_programme(tmp_path))).values()}
    order_a = [RENAME.get(c, c) for c in
               sorted(src, key=lambda c: _slot_order_key(c, src))]
    order_b = sorted(dst, key=lambda c: _slot_order_key(c, dst))
    assert order_a == order_b, (
        "renaming reordered the collapse slots, so ties will break differently")


@pytest.mark.parametrize("flattened", [
    pytest.param({}, id="width-live"),
    pytest.param({"width_inside": None}, id="width-flattened"),
])
def test_scoring_is_spelling_invariant_even_with_a_factor_flattened(
        tmp_path, flattened):
    """The regression guard. `width-flattened` is the case that broke: it must
    hold whether or not homemaker-py-2f1 has landed."""
    renamed = _renamed_programme(tmp_path)
    ov = dict(driver._overrides_for(True, False, None, False, True, False) or {})

    def evaluator(directory):
        conf, cost = fitness.load_config(str(directory),
                                         overrides={**ov, **flattened})
        return fitness.Fitness(conf, cost)

    reqs = programme.load_programme_dir(str(EXAMPLES / "harbor-house"))
    before, after = evaluator(EXAMPLES / "harbor-house"), evaluator(renamed)
    for seed in range(3):
        root = operators.constructive_topology(
            dom.load(str(EXAMPLES / "harbor-house" / "init.dom")), reqs,
            np.random.default_rng(seed), sorted(reqs) + ["C", "O"],
            min_storeys=programme.storey_minimum(str(EXAMPLES / "harbor-house")),
            adjacency_aware=True, proportion_aware=True, circ_divisor=3,
            leaf_sharing=True, leaf_share_factor=3, depth_balanced=True,
            interior_outside=True, outside_divisor=3)
        a, b = copy.deepcopy(root), copy.deepcopy(root)
        for lvl in dom.levels(b):
            for leaf in lvl.leaves():
                leaf.type = RENAME.get(leaf.type, leaf.type)
                leaf.share_type = RENAME.get(leaf.share_type, leaf.share_type)
        score_a, _ = before.score_with_fails(a)
        score_b, _ = after.score_with_fails(b)
        assert f"{score_a:.12g}" == f"{score_b:.12g}", f"seed {seed}: score differs"
