#!/bin/bash
# homemaker-py-7bc2: does the connection guard (default on since §39.174, on
# slim evidence) hold up on a second programme? (DESIGN.md §39.175 expectation)
#
# ONE successive-halving race over EXACTLY §39.168's field -- the 48 dealt, 48
# capacity and 3 cold candidates committed in results/halving-harbor-split,
# under the same names, so each stage's seed hash is the same -- with the
# guard on, ranked --rank total as §39.168 was. Its control is §39.168's race
# itself (guard off): the search is deterministic, and today's code with
# --no-guard-connection replays a §39.168 stage-0 run byte for byte (checked
# 2026-10-26 on dealt-1 at 4k, §39.175), so it need not be re-run. The cold
# candidates are the committed copies, not fresh ones: a recopied init.dom
# would be the same file, but this keeps the field exactly the one raced.
#
#   setsid nohup experiments/run_guard_harbor.sh > ~/homemaker-guard-harbor.log 2>&1 < /dev/null &
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

SEEDS=experiments/results/halving-harbor-split
n=$(ls $SEEDS/dealt-*.dom $SEEDS/cap-*.dom $SEEDS/cold-?.dom | wc -l)
[ "$n" = 99 ] || { echo "!!! expected 99 candidates in $SEEDS, found $n"; exit 1; }
R=experiments/results/halving-harbor-guard
W=$HOME/halving-harbor-guard
mkdir -p $R

say "race guard: $n candidates"
python -u experiments/successive_halving.py --programme harbor-house \
    --seeds $SEEDS/dealt-*.dom $SEEDS/cap-*.dom $SEEDS/cold-a.dom $SEEDS/cold-b.dom $SEEDS/cold-c.dom \
    --start 4000 --final 128000 --eta 2 --slots "$SLOTS" --rank total \
    --evolve-args=--guard-connection \
    --work "$W" --output "$R/winner.dom" > $R/race.log 2>&1
say "race guard finished (rc=$?)"

cp -f $W/stages.tsv $R/stages.tsv
python experiments/diag_halving_connect.py $W $SEEDS --programme harbor-house > $R/connect.txt 2>&1
python experiments/diag_halving_stairs.py $W > $R/stairs.txt 2>&1
python experiments/diag_halving_carry.py $R/winner.dom --programme harbor-house \
    --seeds-dir $SEEDS --cold "${STAMP%% *}" > $R/carry.txt 2>&1
# the control's connection census, from §39.168's own work dir, by the same tool
[ -d "$HOME/halving-harbor-split" ] && python experiments/diag_halving_connect.py \
    "$HOME/halving-harbor-split" $SEEDS --programme harbor-house > $R/connect-control.txt 2>&1
grep -l Traceback $R/*.txt $R/race.log && echo "!!! a step raised: read it before the results"
publish "guard race on harbor-house: §39.168's 99 candidates with the guard on (homemaker-py-7bc2)" $R
say "guard race complete"
