#!/bin/bash
# homemaker-py-7bc2, spine half: does `--spine` (seed_from_catalogue, default
# on since §39.174 on one maple-court race, §39.167) hold up on a second
# programme? Expectation written first, DESIGN.md §39.182.
#
# The maple-court race's design, on harbor-house: both arms built at today's
# seeder from the same 16 plans x 3 stair placements (dealt split) -- 48
# `nospine-*` (--no-spine), 48 `spine-*` (--spine) -- and 3 copies of
# init.dom as a cold control, in ONE successive-halving race, --rank total,
# 4k doubling to 128k, today's default search (guard `connected`).
#
#   setsid nohup experiments/run_spine_harbor.sh > ~/homemaker-spine-harbor.log 2>&1 < /dev/null &
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
until ! pgrep -f 'homemaker_layout[.]evolve|homemaker-evolve |flag_ab[.]py |run_coldstart_baseline[.]py |successive_halving[.]py ' >/dev/null; do
    sleep 300
done
[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
git pull -q --rebase || echo "(pull failed; working with what is here)"
STAMP=$(python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit(), m.search_commit(), m.search_config()[0])")
say "start: objective, search, config = $STAMP; HEAD $(git rev-parse --short HEAD)"

P=harbor-house
R=experiments/results/halving-harbor-spine
W=$HOME/halving-harbor-spine
mkdir -p $R
build() {   # build <prefix> [seeder flags...]
    local prefix=$1; shift
    say "building $prefix seeds $*"
    python experiments/seed_from_catalogue.py --programme $P \
        --max-seeds 16 --core-variants 3 --write 48 --prefix $prefix --out-dir $R "$@" \
        > $R/build-$prefix.log 2>&1
    say "built $(ls $R/$prefix-*.dom 2>/dev/null | wc -l) $prefix seeds (rc=$?)"
}
build nospine --no-spine
build spine --spine
for c in a b c; do cp -f examples/$P/init.dom $R/cold-$c.dom; done
n=$(ls $R/nospine-*.dom $R/spine-*.dom $R/cold-?.dom | wc -l)
[ "$n" = 99 ] || { echo "!!! expected 99 candidates, found $n"; exit 1; }

say "race: $n candidates"
python -u experiments/successive_halving.py --programme $P \
    --seeds $R/nospine-*.dom $R/spine-*.dom $R/cold-a.dom $R/cold-b.dom $R/cold-c.dom \
    --start 4000 --final 128000 --eta 2 --slots "$SLOTS" --rank total \
    --work "$W" --output "$R/winner.dom" > $R/race.log 2>&1
say "race finished (rc=$?)"

cp -f $W/stages.tsv $R/stages.tsv
python experiments/diag_halving_connect.py $W $R --programme $P > $R/connect.txt 2>&1
python experiments/diag_halving_stairs.py $W > $R/stairs.txt 2>&1
python experiments/diag_halving_carry.py $R/winner.dom --programme $P \
    --seeds-dir $R --cold "${STAMP%% *}" > $R/carry.txt 2>&1
grep -l Traceback $R/*.txt $R/*.log && echo "!!! a step raised: read it before the results"
publish "spine race on harbor-house: 48 spine + 48 no-spine + 3 cold (homemaker-py-7bc2)" $R
say "spine race complete"
