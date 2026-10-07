#!/bin/bash
# What follows the first A/B queue (experiments/run_ab_queue.sh), unattended:
#
#   1. WAIT for that queue to say "queue complete" and for every search to exit.
#   2. MERGE the three branches that were held back because src/ was frozen:
#        move-book      the per-child move recorder        (homemaker-py-urzf)
#        terrace-value  value_supported 100 -> 120         (homemaker-py-ecx, §39.117)
#        seed-solver    --seed-solver, default off         (homemaker-py-8b2u.21, §39.118)
#      terrace-value CHANGES THE OBJECTIVE, on the owner's ruling. It lands here,
#      between queues, so that each queue's experiments share one objective.
#   3. TEST the merged tree, in a scratch checkout. Main is only fast-forwarded
#      to a merge that passed; if anything fails main is untouched and nothing
#      runs: a human should look.
#   4. PUSH, then run the seed-solver A/B (owner, 2026-10-07: "build the
#      share-aware solver pass and queue it"): programme-house, 36 pairs, ~19 h;
#      then harbor-house, 4 pairs, ~16 h -- where the seed gain was largest.
#
#   setsid nohup experiments/run_ab_queue2.sh > ~/homemaker-ab-queue2.log 2>&1 &
#
# DO NOT EDIT src/ ON MAIN from the moment this merges until it says
# "queue 2 complete". Expectations are in flag_ab.py's docstring.
cd "$(dirname "$0")/.." || exit 1
FIRST=${FIRST_LOG:-$HOME/homemaker-ab-queue.log}
BRANCHES="move-book terrace-value seed-solver"
SLOTS=${SLOTS:-8}

echo "=== $(date '+%F %T') waiting for the first queue ($FIRST)"
until grep -q 'queue complete' "$FIRST" 2>/dev/null \
      && ! pgrep -f 'homemaker_layout.evolve|homemaker-evolve|flag_ab.py' >/dev/null; do
    sleep 300
done
echo "=== $(date '+%F %T') first queue complete"

# The merge is made and tested in a SCRATCH checkout, and main is only ever
# fast-forwarded to it. Nothing here resets or overwrites the working tree:
# somebody may be half-way through a drawing in examples/.
[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
if [ -n "$(git status --porcelain -- src)" ]; then
    echo "!!! src/ has uncommitted changes; not merging over them"; exit 1
fi
TRIAL=$(mktemp -d /tmp/ab-queue2-merge.XXXXXX)
git worktree add -q --detach "$TRIAL" main || exit 1
for b in $BRANCHES; do
    ref=$b; git rev-parse -q --verify "$b" >/dev/null || ref=origin/$b
    if ! git -C "$TRIAL" merge -q --no-ff --no-edit "$ref" \
            -m "Merge $b (held until the first A/B queue finished)"; then
        echo "!!! merging $b conflicted; main is untouched (the attempt is in $TRIAL)"; exit 1
    fi
done
echo "=== $(date '+%F %T') merged in $TRIAL: $BRANCHES; testing"
if ! (cd "$TRIAL" && env -u HOMEMAKER_ORTHOGONAL_DIVISION -u HOMEMAKER_MOVE_LOG \
        -u HOMEMAKER_SEED_SOLVER -u HOMEMAKER_CORE_UNDIVIDE_REPAIRED PYTHONPATH="$TRIAL/src" \
        python -m pytest -q -p no:cacheprovider > "$HOME/homemaker-ab-queue2.pytest.log" 2>&1); then
    echo "!!! the merged tree FAILS its tests (see ~/homemaker-ab-queue2.pytest.log);"
    echo "!!! main is untouched and nothing was pushed or run (the merge is in $TRIAL)"
    exit 1
fi
tail -1 "$HOME/homemaker-ab-queue2.pytest.log"
if ! git merge -q --ff-only "$(git -C "$TRIAL" rev-parse HEAD)"; then
    echo "!!! main could not be fast-forwarded (it moved, or a local edit is in the way)"; exit 1
fi
git worktree remove --force "$TRIAL"
git push -q || echo "!!! push failed; the runs will push their own results later"
echo "=== $(date '+%F %T') pushed; objective is now:"
HOMEMAKER_ORTHOGONAL_DIVISION=1 python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print('   ', m.objective_commit(), m.search_commit(), m.search_config()[0])"

for prog_seeds in "programme-house 36" "harbor-house 4"; do
    set -- $prog_seeds
    echo "=== $(date '+%F %T') starting seedsolve on $1 ($2 pairs)"
    python experiments/flag_ab.py seedsolve --programme "$1" --seeds "$2" --slots "$SLOTS" --resume
    echo "=== $(date '+%F %T') finished seedsolve on $1 (rc=$?)"
done
echo "=== $(date '+%F %T') queue 2 complete"
