#!/bin/bash
# Queue 6: the box queue left by the 0d79403+orth re-baseline (homemaker-py-vpx5),
# unattended, one step after another, each committing and pushing its results.
#
#   1. kind on maple-court, 4 pairs (homemaker-py-urzf.2; expectation in
#      DESIGN.md §39.158: null). ~15 h at 8 slots.
#   2. the spine race (homemaker-py-2g7.13.1.7, expectation in §39.161):
#      maple-court successive halving, 48 spine seeds beside 48 no-spine
#      seeds, both built now from the same 16 plans x 3 stair placements, and
#      3 cold candidates. ~14 h. halving-maple's own seeds are NOT reused: a
#      rebuild at 5ba9999 by the same command differs in 9 of 48 (the
#      seeder's whole-building link, d211306, moves some 3-placement seeds
#      that §39.161's 1-placement census did not), so they are not the
#      no-spine arm of today's seeder.
#   3. the split race (homemaker-py-2g7.13.1.8, expectation in §39.160):
#      harbor-house successive halving, 48 seeds dealt and 48 capacity, both
#      built now from the same 16 plans, and 3 cold candidates.
#
# Each race uses run_halving_maple.sh's settings: total ranking, 4k x2 ->
# 128k, 8 slots. Seeds are built by the command that made halving-maple's (a rebuild
# reproduces its plans and stair placements).
#
#   setsid nohup experiments/run_ab_queue6.sh > ~/homemaker-ab-queue6.log 2>&1 < /dev/null &
#
# DO NOT EDIT src/ ON MAIN while this runs (code work goes in a worktree).
# Do not trust a "finished" line without grepping the log for Traceback.
cd "$(dirname "$0")/.." || exit 1
SLOTS=${SLOTS:-8}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
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

until ! pgrep -f 'homemaker_layout.evolve|homemaker-evolve|flag_ab.py|run_coldstart_baseline|successive_halving' >/dev/null; do
    sleep 300
done
[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
git pull -q --rebase || echo "(pull failed; working with what is here)"
STAMP=$(HOMEMAKER_ORTHOGONAL_DIVISION=1 python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit(), m.search_commit(), m.search_config()[0])")
say "start: objective, search, config = $STAMP; HEAD $(git rev-parse --short HEAD)"

# 1. kind on maple-court -------------------------------------------------------
say "starting kind on maple-court (4 pairs)"
HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/flag_ab.py kind --programme maple-court \
    --seeds 4 --slots "$SLOTS" --resume
say "finished kind on maple-court (rc=$?)"
publish "kind A/B on maple-court, 4 pairs (homemaker-py-urzf.2, queue 6)" \
    experiments/results/kind_ab.tsv experiments/results/kind-ab

# a race: race <programme> <results dir> <work name> <seed globs...>
race() {
    local prog=$1 R=$2 work=$3; shift 3
    for c in a b c; do cp -f examples/$prog/init.dom $R/cold-$c.dom; done
    say "race $work: $(ls "$@" $R/cold-?.dom | wc -l) candidates"
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python -u experiments/successive_halving.py --programme $prog \
        --seeds "$@" $R/cold-a.dom $R/cold-b.dom $R/cold-c.dom \
        --start 4000 --final 128000 --eta 2 --slots "$SLOTS" --rank total \
        --work "$HOME/$work" --output "$R/winner.dom"
    local rc=$?
    say "race $work finished (rc=$rc)"
    cp -f "$HOME/$work/stages.tsv" $R/stages.tsv
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_halving_stairs.py "$HOME/$work" > $R/stairs.txt 2>&1
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_halving_carry.py $R/winner.dom --programme $prog > $R/carry.txt 2>&1
}
build() {   # build <programme> <dir> <prefix> [seeder flags...]
    local prog=$1 R=$2 prefix=$3; shift 3
    say "building $prefix seeds for $prog $*"
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/seed_from_catalogue.py --programme $prog \
        --max-seeds 16 --core-variants 3 --write 48 --prefix $prefix --out-dir $R "$@" \
        > $R/build-$prefix.log 2>&1
    local rc=$?
    say "built $(ls $R/$prefix-*.dom 2>/dev/null | wc -l) $prefix seeds (rc=$rc)"
}

# 2. the spine race on maple-court --------------------------------------------
R=experiments/results/halving-maple-spine
mkdir -p $R
build maple-court $R nospine --no-spine
build maple-court $R spine --spine
race maple-court $R halving-maple-spine $R/nospine-*.dom $R/spine-*.dom
publish "spine race on maple-court: 48 spine + 48 no-spine + 3 cold (homemaker-py-2g7.13.1.7, queue 6)" $R

# 3. the split race on harbor-house -------------------------------------------
R=experiments/results/halving-harbor-split
mkdir -p $R
build harbor-house $R dealt
build harbor-house $R cap --split capacity
race harbor-house $R halving-harbor-split $R/dealt-*.dom $R/cap-*.dom
publish "split race on harbor-house: 48 dealt + 48 capacity + 3 cold (homemaker-py-2g7.13.1.8, queue 6)" $R

grep -q Traceback "$HOME/homemaker-ab-queue6.log" 2>/dev/null && echo "!!! a Traceback is in this log: read it"
say "queue 6 complete"
