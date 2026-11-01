#!/bin/bash
# homemaker-py-73r9: does a search keep the joined single-loaded plan (§39.194) and
# recover what the repair cost? Four runs from clean-9-bridged.dom against four from
# single-2's double-loaded winner, 128k each, one stage of successive_halving, same
# search and objective. Four rng seeds on one design each: replicates of the search
# on that design, not a sample of plans, so this reads as direction only.
#
# Expectations, written before the run:
#
#   1. no joined run loses a storey: 0 `not connected` on all four (the guard's
#      default applies, every storey being connected at the start);
#   2. joined runs end at a median of 10-12 fails, down from 14: `size` goes,
#      the buried corridor `crinkliness` mostly stays;
#   3. double runs end at a median of 11-13, down from 13, having had far more
#      search since their last change of plan;
#   4. the two medians are within 2 fails of each other;
#   5. at least 3 of 4 joined runs stay single-loaded: no double-loaded corridor
#      over 8 m (the 7.1 m stair is already read as one);
#   6. double runs keep a stair cell over 15 m (single-2's 28.7 m), joined runs do not.
#
#   setsid nohup experiments/run_join_clean9.sh > ~/homemaker-join-clean9.log 2>&1 < /dev/null &
#   RESUME=1 setsid nohup experiments/run_join_clean9.sh >> ~/homemaker-join-clean9.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
SLOTS=${SLOTS:-8}
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset HOMEMAKER_MOVE_LOG HOMEMAKER_SEED_SOLVER HOMEMAKER_CORE_UNDIVIDE_REPAIRED \
      HOMEMAKER_TUNE_HEIGHTS HOMEMAKER_NATIVE HOMEMAKER_LIGHT_WELL HOMEMAKER_LABEL_WRITEBACK \
      HOMEMAKER_AIM_UNDIVIDE HOMEMAKER_RETYPE_KIND HOMEMAKER_PIVOT HOMEMAKER_GUARD_CONNECTION
say() { echo "=== $(date '+%F %T') $*"; }
publish() {   # publish <message> <paths...>
    local msg=$1; shift
    git add -- "$@" && git commit -q -m "$msg

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NE6FXtUoA8scvkzqSFD6M3" && { git pull -q --rebase; git push -q; } \
        || echo "!!! could not publish: $msg"
}

[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
STAMP=$(python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit(), m.search_commit(), m.search_config()[0])")
say "start: objective, search, config = $STAMP; HEAD $(git rev-parse --short HEAD)"
[ "$STAMP" = "c73dfde+orth 1f5cf6a dc80f8a745" ] || { echo "!!! stamp moved since the expectations were written"; exit 1; }

P=maple-court
R=experiments/results/join-clean9
W=$HOME/join-clean9
S=$R/seeds
if [ -z "$RESUME" ]; then
    mkdir -p $S
    for k in 1 2 3 4; do
        cp -f $R/clean-9-bridged.dom $S/joined-$k.dom
        cp -f experiments/results/halving-maple-single/winner.dom $S/double-$k.dom
    done
    : > $R/race.log
fi

say "8 runs at 128k${RESUME:+ (resuming)}"
python -u experiments/successive_halving.py --programme $P --seeds $S/*.dom \
    --start 128000 --final 128000 --slots "$SLOTS" --rank total \
    --work "$W" --output "$R/winner.dom" ${RESUME:+--resume} >> $R/race.log 2>&1
say "runs finished (rc=$?)"

cp -f $W/stages.tsv $R/stages.tsv
python experiments/diag_halving_connect.py $W $S --programme $P > $R/connect.txt 2>&1
python experiments/diag_double_loaded.py --summary $W/s0/*/out.dom > $R/double-loaded.txt 2>&1
python experiments/diag_long_stairs.py --over 8 $W/s0/*/out.dom > $R/long-stairs.txt 2>&1
for f in $W/s0/*/out.dom; do
    n=$(basename "$(dirname "$f")")
    cp -f "$f" "$R/final-$n.dom"
    python experiments/plan_svg.py --programme examples/$P "$R/final-$n.dom" -o "$R/final-$n.plan.svg" >> $R/plans.log 2>&1
done
grep -l Traceback $R/*.txt $R/*.log && echo "!!! a step raised: read it before the results"
publish "join-clean9 continuation on maple-court (homemaker-py-73r9)" $R
say "join-clean9 complete"
