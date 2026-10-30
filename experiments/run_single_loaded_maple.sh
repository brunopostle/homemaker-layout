#!/bin/bash
# homemaker-py-sp11: do single-loaded wings round a court beat the default
# seeder's double-loaded ones on maple-court? Expectation written first,
# DESIGN.md §39.186.
#
# Both arms built by today's seeder from the catalogue, 16 plans x 3 stair
# placements each, in ONE successive-halving race with 3 copies of init.dom as
# a cold control, --rank total, 4k doubling to 128k, today's default search
# (guard `connected`, spine on):
#   double-*  the default seeder: the filter passes wings up to 1.62 h from a
#             lit wall (~9.7 m deep lit both sides), and a spine may run
#             through a wing's middle -- a double-loaded corridor;
#   single-*  --reach 1.25 (wings ~7.5 m deep at most) and --spine-at edge
#             (every corridor along a wing's edge, rooms on the far side).
# Both arms at THREE storeys (--storeys 3). The brief allows four, but every
# maple-court room is pinned to level 0, 1 or 2, so a fourth storey holds
# nothing and a four-storey plan squeezes three storeys of rooms onto a
# footprint sized for four. At reach 1.25 the fewest-leaves plans pass only
# at four storeys (79 outlines pass at three, 463 at four), so the seeder's
# own ordering would have built exactly those.
# Two changes in one arm, deliberately: together they ARE the single-loaded
# plan; which of the two carries any difference is a later question.
#
#   setsid nohup experiments/run_single_loaded_maple.sh > ~/homemaker-single-loaded-maple.log 2>&1 < /dev/null &
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

P=maple-court
R=experiments/results/halving-maple-single
W=$HOME/halving-maple-single
mkdir -p $R
build() {   # build <prefix> <plans> [seeder flags...]
    local prefix=$1 plans=$2; shift 2
    say "building $prefix seeds $*"
    python experiments/seed_from_catalogue.py --programme $P \
        --max-seeds $plans --core-variants 3 --write $((plans * 3)) --prefix $prefix \
        --out-dir $R "$@" > $R/build-$prefix.log 2>&1
    local rc=$?
    say "built $(ls $R/$prefix-*.dom 2>/dev/null | wc -l) $prefix seeds (rc=$rc)"
}
build double 16 --storeys 3
build single 16 --reach 1.25 --spine-at edge --storeys 3
for c in a b c; do cp -f examples/$P/init.dom $R/cold-$c.dom; done
python experiments/diag_double_loaded.py --summary $R/double-*.dom $R/single-*.dom > $R/double-loaded-seeds.txt 2>&1
n=$(ls $R/double-*.dom $R/single-*.dom $R/cold-?.dom | wc -l)
[ "$n" = 99 ] || { echo "!!! expected 99 candidates, found $n"; exit 1; }

say "race: $n candidates"
python -u experiments/successive_halving.py --programme $P \
    --seeds $R/double-*.dom $R/single-*.dom $R/cold-a.dom $R/cold-b.dom $R/cold-c.dom \
    --start 4000 --final 128000 --eta 2 --slots "$SLOTS" --rank total \
    --work "$W" --output "$R/winner.dom" > $R/race.log 2>&1
say "race finished (rc=$?)"

cp -f $W/stages.tsv $R/stages.tsv
python experiments/diag_halving_connect.py $W $R --programme $P > $R/connect.txt 2>&1
python experiments/diag_halving_stairs.py $W > $R/stairs.txt 2>&1
python experiments/diag_halving_carry.py $R/winner.dom --programme $P \
    --seeds-dir $R --cold "${STAMP%% *}" > $R/carry.txt 2>&1
python experiments/diag_double_loaded.py $R/winner.dom > $R/double-loaded-winner.txt 2>&1
python experiments/diag_double_loaded.py --summary $W/s*/*/out.dom > $R/double-loaded-stages.txt 2>&1
grep -l Traceback $R/*.txt $R/*.log && echo "!!! a step raised: read it before the results"
publish "single-loaded race on maple-court: 48 single + 48 double + 3 cold (homemaker-py-sp11)" $R
say "single-loaded race complete"
