#!/bin/bash
# What follows queue 3, unattended -- the plan the owner approved on 2026-10-10
# (DESIGN.md §39.132; homemaker-py-owo2):
#
#   1. WAIT for queue 3 to say "queue 3 complete" and for every search to exit.
#   2. LAND the brief fixes (branch brief-fixes, homemaker-py-5nw) the way
#      queue 3 lands its merge: in a scratch checkout, tested, and main only
#      fast-forwarded to a tree that passed. They change three programmes, so
#      they land here, immediately before...
#   3. ...the full twelve-run RE-BASELINE at the objective that results
#      (~19 h). Everything since E needs a corpus to be read against.
#   4. THREE HAND-SEEDED harbor-house runs: the owner's drawing as the seed
#      (homemaker-evolve hand2a.dom), same budget and seeds as the
#      re-baseline's three cold harbor-house runs, which are the comparison.
#   5. The programme-house A/Bs, 36 pairs: `labels` in full, then `aim` and
#      `heights` with their control arm supplied from `labels`'s
#      (experiments/prefill_control.py, §39.129) -- so their elapsed_s is not
#      paired.
#   6. harbor-house, 4 pairs each: `well`, then `heights` with `well`'s
#      control. Neither can show anything on programme-house.
#
#   setsid nohup experiments/run_ab_queue4.sh > ~/homemaker-ab-queue4.log 2>&1 < /dev/null &
#
# DO NOT EDIT src/ ON MAIN while this runs. A step that fails says "!!!" and
# the queue goes on to the next where it safely can; read the log, and do not
# trust a "finished" line without grepping for Traceback.
cd "$(dirname "$0")/.." || exit 1
REPO=$PWD
FIRST=${FIRST_LOG:-$HOME/homemaker-ab-queue3.log}
SLOTS=${SLOTS:-8}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
UNSET="-u HOMEMAKER_ORTHOGONAL_DIVISION -u HOMEMAKER_MOVE_LOG -u HOMEMAKER_SEED_SOLVER -u HOMEMAKER_CORE_UNDIVIDE_REPAIRED -u HOMEMAKER_TUNE_HEIGHTS -u HOMEMAKER_NATIVE -u HOMEMAKER_LIGHT_WELL -u HOMEMAKER_LABEL_WRITEBACK -u HOMEMAKER_AIM_UNDIVIDE"
say() { echo "=== $(date '+%F %T') $*"; }

say "waiting for $FIRST"
until grep -q 'queue 3 complete' "$FIRST" 2>/dev/null \
      && ! pgrep -f 'homemaker_layout.evolve|homemaker-evolve|flag_ab.py|run_coldstart_baseline' >/dev/null; do
    sleep 300
done
say "queue 3 is complete"

# --- 2. the brief fixes
[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
[ -z "$(git status --porcelain -- src examples)" ] || { echo "!!! src/ or examples/ has uncommitted changes"; exit 1; }
git pull -q --rebase || echo "(pull failed; working with what is here)"
TRIAL=$(mktemp -d /tmp/ab-queue4-merge.XXXXXX)
git worktree add -q --detach "$TRIAL" main || exit 1
ref=brief-fixes; git rev-parse -q --verify "$ref" >/dev/null || ref=origin/brief-fixes
if ! git -C "$TRIAL" merge -q --no-ff --no-edit "$ref" \
        -m "Merge brief-fixes: no foyer room, maple-court's level-1 bathrooms, the treatment room's WC (homemaker-py-5nw)"; then
    echo "!!! merging $ref conflicted; main is untouched (the attempt is in $TRIAL). The re-baseline would run"
    echo "!!! on the OLD briefs, which is not what was asked for: stopping."
    exit 1
fi
say "merged $ref in $TRIAL; testing"
if ! (cd "$TRIAL" && env $UNSET PYTHONPATH="$TRIAL/src" \
        python -m pytest -q -p no:cacheprovider > "$HOME/homemaker-ab-queue4.pytest.log" 2>&1); then
    echo "!!! the merged tree FAILS its tests (~/homemaker-ab-queue4.pytest.log); main is untouched; stopping."
    exit 1
fi
tail -1 "$HOME/homemaker-ab-queue4.pytest.log"
git merge -q --ff-only "$(git -C "$TRIAL" rev-parse HEAD)" || { echo "!!! main could not be fast-forwarded"; exit 1; }
git worktree remove --force "$TRIAL"
git push -q || echo "!!! push failed; the runs will push their own results later"

# --- 3. the re-baseline
say "the re-baseline: 12 runs, 500k, $SLOTS slots"
HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/run_coldstart_baseline.py \
    --budget 500000 --seeds 3 --slots "$SLOTS"
say "re-baseline finished (rc=$?)"
STAMP=$(HOMEMAKER_ORTHOGONAL_DIVISION=1 python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit())")
say "objective $STAMP"

# --- 4. the owner's drawing as the seed
say "three hand-seeded harbor-house runs"
HS=/tmp/handseed_runs; rm -rf "$HS"; mkdir -p "$HS"
for s in 0 1 2; do
    d=$HS/s$s; mkdir -p "$d"
    cp -f examples/harbor-house/hand2a.dom examples/harbor-house/patterns.config "$d"/
    cp -f examples/harbor-house/costs.config "$d"/ 2>/dev/null
    (cd "$d" && HOMEMAKER_ORTHOGONAL_DIVISION=1 python -m homemaker_layout.evolve hand2a.dom \
        --budget 500000 --seed $s --workers 1 --output out.dom > log.txt 2>&1) &
done
wait
for s in 0 1 2; do
    d=$HS/s$s
    if [ -s "$d/out.dom" ]; then
        cp -f "$d/out.dom" "examples/harbor-house/handseed-$STAMP-500000-s$s.dom"
        cp -f "$d/log.txt" "examples/harbor-house/handseed-$STAMP-500000-s$s.log"
        git add "examples/harbor-house/handseed-$STAMP-500000-s$s.dom" "examples/harbor-house/handseed-$STAMP-500000-s$s.log"
    else
        echo "!!! hand-seeded run s$s wrote no design (see $d/log.txt)"
    fi
done
git diff --cached --quiet || { git commit -q -m "Hand-seeded harbor-house runs at $STAMP: hand2a.dom as the seed, 500k, seeds 0-2 (homemaker-py-2g7.1)" \
    -m "The comparison is the re-baseline's three cold harbor-house runs at the same stamp, budget and seeds."; git pull -q --rebase; git push -q; }
say "hand-seeded runs finished"

# --- 5 and 6. the A/Bs
ab() {   # ab <experiment> <programme> <pairs>
    grep -q "\"$1\": dict" experiments/flag_ab.py || { echo "!!! flag_ab.py has no experiment '$1' (was trial-merge-2 landed?); skipped"; return; }
    say "starting $1 on $2 ($3 pairs)"
    python experiments/flag_ab.py "$1" --programme "$2" --seeds "$3" --slots "$SLOTS" --resume
    say "finished $1 on $2 (rc=$?)"
}
ab labels programme-house 36
for exp in aim heights; do
    python experiments/prefill_control.py labels $exp --programme programme-house \
        && { git add experiments/results/${exp}_ab.tsv experiments/results/${exp}-ab; \
             git commit -q -m "$exp A/B: the control arm supplied from labels' (prefill_control.py, DESIGN.md §39.129)"; \
             git pull -q --rebase; git push -q; }
    ab $exp programme-house 36
done
ab well harbor-house 4
python experiments/prefill_control.py well heights --programme harbor-house \
    && { git add experiments/results/heights_ab.tsv experiments/results/heights-ab; \
         git commit -q -m "heights A/B on harbor-house: the control arm supplied from well's (prefill_control.py)"; \
         git pull -q --rebase; git push -q; }
ab heights harbor-house 4
grep -q Traceback "$HOME/homemaker-ab-queue4.log" 2>/dev/null && echo "!!! a Traceback is in this log: read it"
say "queue 4 complete"
