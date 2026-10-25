#!/bin/bash
# homemaker-py-2g7.13.1.10, option 2: does the connection guard keep the
# connection the spine seeds bring? (DESIGN.md §39.170 expectation, §39.172)
#
# ONE successive-halving race over the same 48 committed spine seeds as
# §39.169/§39.172, every candidate's search run with --guard-connection, the
# objective as shipped (connectivity_weight 1), --rank weighted (= total at
# w = 1). Its control is the `w1` arm of results/halving-maple-connect: the
# search is deterministic and the merged guard, off, reproduces a w1 stage
# byte for byte (checked 2026-10-25 on spine-16 at 4k), so that arm need not
# be re-run. 8 slots: the field and the ranking are the w1 arm's, and slot
# count does not change any run.
#
#   setsid nohup experiments/run_guard_race.sh > ~/homemaker-guard-race.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
SLOTS=${SLOTS:-8}
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
mkdir -p $R/guard

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
race guard --evolve-args=--guard-connection

for arm in guard; do
    W=$HOME/halving-connect-$arm
    cp -f $W/stages.tsv $R/$arm/stages.tsv
    python experiments/diag_halving_connect.py $W $SEEDS --programme maple-court > $R/$arm/connect.txt 2>&1
    python experiments/diag_halving_stairs.py $W > $R/$arm/stairs.txt 2>&1
    python experiments/diag_halving_carry.py $R/$arm/winner.dom --programme maple-court \
        --seeds-dir $SEEDS --cold "${STAMP%% *}" > $R/$arm/carry.txt 2>&1
done
grep -l Traceback $R/guard/*.txt $R/guard/race.log && echo "!!! a step raised: read it before the results"
publish "guard race on maple-court: 48 spine seeds with --guard-connection (homemaker-py-2g7.13.1.10)" $R/guard
say "guard race complete"
