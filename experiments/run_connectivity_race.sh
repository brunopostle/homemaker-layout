#!/bin/bash
# homemaker-py-2g7.13.1.10, option 1: does connectivity_weight=auto keep the
# connection the spine seeds bring? (DESIGN.md §39.167, expectation in §39.169)
#
# Two successive-halving races over the SAME 48 committed spine seeds of
# §39.167's race (experiments/results/halving-maple-spine/spine-*.dom), run
# side by side at 4 slots each so both see the same box and the same search:
#
#   w1   -- the objective as shipped (connectivity_weight 1), the control;
#   auto -- --conf connectivity_weight=auto (3 at maple-court's value rates),
#           for every candidate's search and for the ranking.
#
# Both rank --rank weighted (connectivity fails counted w times, then score),
# which at w=1 is exactly --rank total, §39.167's ranking. No cold candidates:
# all three went at 4k in §39.167. 4k doubling to 128k, as before.
#
# It WAITS for the pivot A/B (flag_ab.py pivot, homemaker-py-mtfo) and every
# other search to exit. Do not edit src/ on main while it runs.
#
#   setsid nohup experiments/run_connectivity_race.sh > ~/homemaker-connectivity-race.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
SLOTS=${SLOTS:-4}
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset HOMEMAKER_MOVE_LOG HOMEMAKER_SEED_SOLVER HOMEMAKER_CORE_UNDIVIDE_REPAIRED \
      HOMEMAKER_TUNE_HEIGHTS HOMEMAKER_NATIVE HOMEMAKER_LIGHT_WELL HOMEMAKER_LABEL_WRITEBACK \
      HOMEMAKER_AIM_UNDIVIDE HOMEMAKER_RETYPE_KIND HOMEMAKER_PIVOT
say() { echo "=== $(date '+%F %T') $*"; }
publish() {   # publish <message> <paths...>
    local msg=$1; shift
    git add -- "$@" && git commit -q -m "$msg

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && { git pull -q --rebase; git push -q; } \
        || echo "!!! could not publish: $msg"
}

say "waiting for the box"
until ! pgrep -f 'homemaker_layout.evolve|homemaker-evolve|flag_ab.py|run_coldstart_baseline|successive_halving' >/dev/null; do
    sleep 300
done
[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
git pull -q --rebase || echo "(pull failed; working with what is here)"
STAMP=$(python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit(), m.search_commit(), m.search_config()[0])")
say "start: objective, search, config = $STAMP; HEAD $(git rev-parse --short HEAD)"

SEEDS=experiments/results/halving-maple-spine
ls $SEEDS/spine-*.dom >/dev/null 2>&1 || { echo "!!! no spine seeds in $SEEDS"; exit 1; }
R=experiments/results/halving-maple-connect
mkdir -p $R/w1 $R/auto

race() {   # race <arm> [--conf ...]
    local arm=$1; shift
    say "race $arm: $(ls $SEEDS/spine-*.dom | wc -l) candidates $*"
    python -u experiments/successive_halving.py --programme maple-court \
        --seeds $SEEDS/spine-*.dom --start 4000 --final 128000 --eta 2 \
        --slots "$SLOTS" --rank weighted "$@" \
        --work "$HOME/halving-connect-$arm" --output "$R/$arm/winner.dom" \
        > $R/$arm/race.log 2>&1
    say "race $arm finished (rc=$?)"
}
race w1 &
race auto --conf connectivity_weight=auto &
wait

for arm in w1 auto; do
    W=$HOME/halving-connect-$arm
    cp -f $W/stages.tsv $R/$arm/stages.tsv
    python experiments/diag_halving_connect.py $W $SEEDS --programme maple-court > $R/$arm/connect.txt 2>&1
    python experiments/diag_halving_stairs.py $W > $R/$arm/stairs.txt 2>&1
    python experiments/diag_halving_carry.py $R/$arm/winner.dom --programme maple-court \
        --seeds-dir $SEEDS --cold "${STAMP%% *}" > $R/$arm/carry.txt 2>&1
done
grep -l Traceback $R/*/*.txt $R/*/race.log && echo "!!! a step raised: read it before the results"
publish "connectivity race on maple-court: 48 spine seeds at w=1 and w=auto (homemaker-py-2g7.13.1.10)" $R
say "connectivity race complete"
