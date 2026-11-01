#!/bin/bash
# homemaker-py-yd6t, the owner's "switch it on for the next race" (section 39.197).
# Every run has --split-stair. maple-court, 128k, one stage, 8 runs in two fields:
#
#   double-1..4  from single-2, the only finalists with a shaft the move can see
#                (28.7 m). Same names, seed and rng as section 39.195's double arm,
#                so these pair against it at stage 0.
#   best-1..4    from joined-1, the best design found (11 fails, connected). It has
#                no stair over 6.8 m, so here the move has nothing to do unless the
#                search grows one: this arm shows what the idle move costs.
#
# Four replicates a design: direction only. Each field keeps its own move log.
#
# Expectations, written before the run:
#
#   1. in at least 3 of 4 double runs a child with a real split is kept;
#   2. at least 2 of 4 double runs end with no shaft of stair over 12 m (0 of 4 did
#      without the move: expectation 6 of section 39.195);
#   3. double runs end at a median of 12-13 fails, against 13 without the move: the
#      split frees no room by itself, it only makes the cell's length readable;
#   4. best runs end at a median of 10-11, none above 11, all connected;
#   5. best runs make no real split at all, and `split_stair noop` is 4-8% of their
#      children, each spending an inner loop on a duplicate (8 of 146 at 4k, both fields);
#   6. single-storey stairs stay in the designs that have them (the owner's ruling,
#      section 39.197, leaves them alone): double-4's ground-floor kind is not removed
#      by this move.
#
#   setsid nohup experiments/run_split_stair_race.sh > ~/homemaker-split-race.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset HOMEMAKER_MOVE_LOG HOMEMAKER_SEED_SOLVER HOMEMAKER_CORE_UNDIVIDE_REPAIRED \
      HOMEMAKER_TUNE_HEIGHTS HOMEMAKER_NATIVE HOMEMAKER_LIGHT_WELL HOMEMAKER_LABEL_WRITEBACK \
      HOMEMAKER_AIM_UNDIVIDE HOMEMAKER_RETYPE_KIND HOMEMAKER_PIVOT HOMEMAKER_GUARD_CONNECTION \
      HOMEMAKER_SPLIT_STAIR
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
[ "$STAMP" = "c73dfde+orth 5dd9012 1a0632d662" ] || { echo "!!! stamp moved since the expectations were written"; exit 1; }

P=maple-court
R=experiments/results/split-stair-race
W=$HOME/split-stair-race
mkdir -p $R/seeds-double $R/seeds-best $W
for k in 1 2 3 4; do
    cp -f experiments/results/halving-maple-single/winner.dom $R/seeds-double/double-$k.dom
    cp -f experiments/results/join-clean9/final-joined-1.dom $R/seeds-best/best-$k.dom
done

for arm in double best; do
    rm -f "$W/moves-$arm.jsonl"
    HOMEMAKER_MOVE_LOG="$W/moves-$arm.jsonl" python -u experiments/successive_halving.py \
        --programme $P --seeds $R/seeds-$arm/*.dom --start 128000 --final 128000 --slots 4 \
        --rank total --work "$W/$arm" --output "$R/winner-$arm.dom" \
        --evolve-args=--split-stair > $R/race-$arm.log 2>&1 &
done
say "8 runs at 128k"
wait
say "runs finished"

for arm in double best; do
    cp -f $W/$arm/stages.tsv $R/stages-$arm.tsv
    python experiments/diag_double_loaded.py --summary $W/$arm/s0/*/out.dom > $R/double-loaded-$arm.txt 2>&1
    python experiments/diag_long_stairs.py --over 8 $W/$arm/s0/*/out.dom > $R/long-stairs-$arm.txt 2>&1
    python experiments/diag_halving_connect.py $W/$arm $R/seeds-$arm --programme $P > $R/connect-$arm.txt 2>&1
    python - "$W/moves-$arm.jsonl" > $R/split-moves-$arm.txt 2>&1 <<'PY'
import json, sys
from collections import Counter
tot, real, noop = 0, Counter(), Counter()
for line in open(sys.argv[1]):
    r = json.loads(line)
    tot += 1
    if r["move"].startswith("split_stair"):
        (noop if "noop" in r["move"] else real)[r["status"]] += 1
print(f"children {tot}\nreal split, by what admit did: {dict(real)}\nnoop: {dict(noop)}")
PY
    for f in $W/$arm/s0/*/out.dom; do
        n=$(basename "$(dirname "$f")")
        cp -f "$f" "$R/final-$n.dom"
        python experiments/plan_svg.py --programme examples/$P "$R/final-$n.dom" -o "$R/final-$n.plan.svg" >> $R/plans.log 2>&1
    done
done
{ head -1 experiments/results/join-clean9/stages.tsv; grep -P '\tdouble-' experiments/results/join-clean9/stages.tsv; } > $R/control-double.tsv
python experiments/pair_halving_stages.py $R/control-double.tsv $R/stages-double.tsv --stage 0 \
    --labels off split > $R/pair-double.txt 2>&1
grep -l Traceback $R/*.txt $R/*.log && echo "!!! a step raised: read it before the results"
publish "split-stair race on maple-court (homemaker-py-yd6t)" $R
say "split-stair race complete"
