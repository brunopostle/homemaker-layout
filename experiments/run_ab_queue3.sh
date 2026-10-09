#!/bin/bash
# What follows the A/B queues, unattended -- queue 2 rewritten on the owner's
# word (2026-10-09): "land all six first", and run the seed-solver A/B at the
# objective that results.
#
#   1. WAIT for the queue named by FIRST_LOG to say "queue complete" and for
#      every search to exit (queue 1b, the native re-run, is the last).
#   2. MERGE branch `trial-merge` into a scratch checkout of main. It is main
#      + move-book + terrace-value + seed-solver + hand-curves + escalier +
#      storey-height, with the two additive conflicts already resolved and the
#      full suite already green on it (842 passed, 2026-10-09). Main has only
#      gained results and documents since, so this is expected to be clean.
#      escalier and terrace-value CHANGE THE OBJECTIVE (a stair is a cell
#      labelled E, §39.125; the terrace is worth 120, §39.117).
#   3. RELABEL the staircases of every design written since the first
#      relabelling (the A/B queue's own artefacts): surveyed under the OLD
#      code, verified under the new -- no score may move -- then written.
#   4. TEST the merged tree. Main is only fast-forwarded to a merge that
#      passed; if anything fails main is untouched and nothing runs.
#   5. PUSH, then the seed-solver A/B: programme-house 36 pairs (~19 h), then
#      harbor-house 4 pairs (~16 h).
#
#   FIRST_LOG=~/homemaker-ab-queue1b.log setsid nohup experiments/run_ab_queue3.sh \
#       > ~/homemaker-ab-queue3.log 2>&1 < /dev/null &
#
# DO NOT EDIT src/ ON MAIN from the moment this merges until it says
# "queue 3 complete". If it stops with "!!!", read the line: main is as it was.
cd "$(dirname "$0")/.." || exit 1
REPO=$PWD
FIRST=${FIRST_LOG:-$HOME/homemaker-ab-queue1b.log}
MERGE_REF=${MERGE_REF:-trial-merge}
SLOTS=${SLOTS:-8}
UNSET="-u HOMEMAKER_ORTHOGONAL_DIVISION -u HOMEMAKER_MOVE_LOG -u HOMEMAKER_SEED_SOLVER -u HOMEMAKER_CORE_UNDIVIDE_REPAIRED -u HOMEMAKER_TUNE_HEIGHTS -u HOMEMAKER_NATIVE"

echo "=== $(date '+%F %T') waiting for $FIRST"
until grep -q 'queue complete' "$FIRST" 2>/dev/null \
      && ! pgrep -f 'homemaker_layout.evolve|homemaker-evolve|flag_ab.py' >/dev/null; do
    sleep 300
done
echo "=== $(date '+%F %T') the queues are complete"

[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
if [ -n "$(git status --porcelain -- src)" ]; then
    echo "!!! src/ has uncommitted changes; not merging over them"; exit 1
fi
git pull -q --rebase || echo "(pull failed; merging what is here)"
TRIAL=$(mktemp -d /tmp/ab-queue3-merge.XXXXXX)
git worktree add -q --detach "$TRIAL" main || exit 1
ref=$MERGE_REF; git rev-parse -q --verify "$ref" >/dev/null || ref=origin/$MERGE_REF
if ! git -C "$TRIAL" merge -q --no-ff --no-edit "$ref" \
        -m "Merge the six held branches: E for stairs, storey heights, the terrace at 120, the move recorder, the seed solver, the composer fixes"; then
    echo "!!! merging $ref conflicted; main is untouched (the attempt is in $TRIAL)"; exit 1
fi
echo "=== $(date '+%F %T') merged $ref in $TRIAL; relabelling the designs written since"
SURVEY=$TRIAL/.relabel-survey.json
if ! (cd "$TRIAL" \
        && env $UNSET PYTHONPATH="$REPO/src" python experiments/relabel_stairs.py --survey "$SURVEY" \
        && env $UNSET PYTHONPATH="$TRIAL/src" python experiments/relabel_stairs.py --verify "$SURVEY" \
        && env $UNSET PYTHONPATH="$TRIAL/src" python experiments/relabel_stairs.py --write "$SURVEY"); then
    echo "!!! relabelling did not verify: a score moved, or a cell was not C."
    echo "!!! main is untouched and nothing was pushed or run (the merge is in $TRIAL)"
    exit 1
fi
rm -f "$SURVEY"
git -C "$TRIAL" add -A examples experiments/results
git -C "$TRIAL" diff --cached --quiet || git -C "$TRIAL" commit -q \
    -m "Relabel the staircases of the designs written since the first relabelling, C -> E" \
    -m "experiments/relabel_stairs.py, surveyed under the code before the merge and verified under the code after it: no score moved (run_ab_queue3.sh)."
echo "=== $(date '+%F %T') testing the merged tree"
if ! (cd "$TRIAL" && env $UNSET PYTHONPATH="$TRIAL/src" \
        python -m pytest -q -p no:cacheprovider > "$HOME/homemaker-ab-queue3.pytest.log" 2>&1); then
    echo "!!! the merged tree FAILS its tests (see ~/homemaker-ab-queue3.pytest.log);"
    echo "!!! main is untouched and nothing was pushed or run (the merge is in $TRIAL)"
    exit 1
fi
tail -1 "$HOME/homemaker-ab-queue3.pytest.log"
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
    rc=$?
    echo "=== $(date '+%F %T') finished seedsolve on $1 (rc=$rc)"
    grep -q Traceback "$HOME/homemaker-ab-queue3.log" 2>/dev/null \
        && echo "!!! a Traceback is in this log: read it before trusting the line above"
done
echo "=== $(date '+%F %T') queue 3 complete"
