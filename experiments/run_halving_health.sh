#!/bin/bash
# homemaker-py-5fje.19: health-centre through the wings-of-light catalogue, the
# first run at the roof/slab/corner objective (DESIGN.md §39.231, §39.232).
# Every earlier health-centre run was cold, and the owner reads its plans as
# "everything just mashed together higgledy-piggledy" (§39.229).
#
# The catalogue filter offers health-centre a 76%-cover plan at one storey and
# a 38%-cover plan at two (`seed_from_catalogue.py --filter-only`), so the field
# is both, built at today's seeder, plus a cold control, in ONE successive-
# halving race (--rank total, 4k doubling to 128k, today's default search):
#   24 `one-*`  --storeys 1, the 24 best plans, one build each (no stair)
#   24 `two-*`  --storeys 2, the 8 best plans x 3 stair placements
#    3 `cold-*` init.dom under three names
# Whether a two-storey seed survives is the question the cost change asks.
#
#   setsid nohup experiments/run_halving_health.sh > ~/homemaker-halving-health.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
SLOTS=${SLOTS:-7}
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset HOMEMAKER_MOVE_LOG HOMEMAKER_SEED_SOLVER HOMEMAKER_CORE_UNDIVIDE_REPAIRED \
      HOMEMAKER_TUNE_HEIGHTS HOMEMAKER_NATIVE HOMEMAKER_LIGHT_WELL HOMEMAKER_LABEL_WRITEBACK \
      HOMEMAKER_AIM_UNDIVIDE HOMEMAKER_RETYPE_KIND HOMEMAKER_PIVOT HOMEMAKER_GUARD_CONNECTION \
      HOMEMAKER_SPLIT_STAIR
say() { echo "=== $(date '+%F %T') $*"; }
publish() {   # publish <message> <paths...>
    local msg=$1; shift
    git add -- "$@" && git commit -q -m "$msg

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && { git pull -q --rebase; git push -q; } \
        || echo "!!! could not publish: $msg"
}

until ! pgrep -f 'homemaker_layout[.]evolve|homemaker-evolve |flag_ab[.]py |run_coldstart_baseline[.]py |successive_halving[.]py ' >/dev/null; do
    say "waiting for the box"; sleep 300
done
[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
git pull -q --rebase || echo "(pull failed; working with what is here)"
STAMP=$(python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit(), m.search_commit(), m.search_config()[0])")
say "start: objective, search, config = $STAMP; HEAD $(git rev-parse --short HEAD)"

P=health-centre
R=experiments/results/halving-health
W=$HOME/halving-health
mkdir -p $R
build() {   # build <prefix> [seeder flags...]
    local prefix=$1; shift
    say "building $prefix seeds $*"
    python experiments/seed_from_catalogue.py --programme $P \
        --prefix $prefix --out-dir $R "$@" > $R/build-$prefix.log 2>&1
    say "built $(ls $R/$prefix-*.dom 2>/dev/null | wc -l) $prefix seeds (rc=$?)"
}
build one --storeys 1 --max-seeds 24 --core-variants 1 --write 24
build two --storeys 2 --max-seeds 8 --core-variants 3 --write 24
for c in a b c; do cp -f examples/$P/init.dom $R/cold-$c.dom; done
n=$(ls $R/one-*.dom $R/two-*.dom $R/cold-?.dom 2>/dev/null | wc -l)
[ "$n" -ge 30 ] || { echo "!!! only $n candidates"; exit 1; }
publish "health-centre halving: $n candidates built at $STAMP (homemaker-py-5fje.19)" $R

say "race: $n candidates"
python -u experiments/successive_halving.py --programme $P \
    --seeds $R/one-*.dom $R/two-*.dom $R/cold-a.dom $R/cold-b.dom $R/cold-c.dom \
    --start 4000 --final 128000 --eta 2 --slots "$SLOTS" --rank total \
    --work "$W" --output "$R/winner.dom" > $R/race.log 2>&1
say "race finished (rc=$?)"

cp -f $W/stages.tsv $R/stages.tsv
python experiments/diag_halving_connect.py $W $R --programme $P > $R/connect.txt 2>&1
python experiments/diag_halving_stairs.py $W > $R/stairs.txt 2>&1
python experiments/diag_halving_carry.py $R/winner.dom --programme $P \
    --seeds-dir $R --cold "${STAMP%% *}" > $R/carry.txt 2>&1
grep -l Traceback $R/*.txt $R/*.log 2>/dev/null && echo "!!! a step raised: read it before the results"
publish "health-centre halving race at $STAMP: results (homemaker-py-5fje.19)" $R
say "health-centre race complete"
