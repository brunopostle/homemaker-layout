#!/bin/bash
# homemaker-py-3xvb: maple-court raced from a field of single-row wings. §39.257's
# race lost on its FIELD: its best seed was a two-row north wing whose back row is
# buried (15 crinkliness, 5 access), and stages 3-5 took off only 4 fails. This field
# lays every spine along an edge no other wing shares (--spine-at outer) and caps a
# wing near 7.5 m (--reach 1.25), from twice the draw (32 plans x 3 stair placements).
# Expectations in DESIGN.md §39.264, written before it runs. Control: §39.257's race,
# halving-maple-rooms, same objective stamp (6191a33+orth); the search stamp has moved
# only by trim_oversized, which is off.
#
# The field alone took ~1.6 h a plan in a container (one process), so this is the
# box's job: about 13 h of building on one core, then the race.
#
#   setsid nohup experiments/run_halving_maple_outer.sh > ~/homemaker-halving-maple-outer.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
SLOTS=${SLOTS:-7}
export HOMEMAKER_PIVOT3=1 HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset HOMEMAKER_MOVE_LOG HOMEMAKER_SEED_SOLVER HOMEMAKER_CORE_UNDIVIDE_REPAIRED \
      HOMEMAKER_TUNE_HEIGHTS HOMEMAKER_NATIVE HOMEMAKER_LIGHT_WELL HOMEMAKER_LABEL_WRITEBACK \
      HOMEMAKER_AIM_UNDIVIDE HOMEMAKER_RETYPE_KIND HOMEMAKER_PIVOT HOMEMAKER_GUARD_CONNECTION \
      HOMEMAKER_SPLIT_STAIR HOMEMAKER_REMOVE_TOKEN HOMEMAKER_MERGE_CIRCULATION HOMEMAKER_TRIM_OVERSIZED
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
[ "${STAMP%% *}" = "6191a33+orth" ] || { echo "!!! objective moved from §39.257's; the control means nothing"; exit 1; }

P=maple-court R=experiments/results/halving-maple-outer W=$HOME/halving-maple-outer
mkdir -p $R
if [ -z "$RESUME" ]; then
    say "$P: building seeds"
    python experiments/seed_from_catalogue.py --programme $P --max-seeds 32 --core-variants 3 \
        --write 96 --prefix outer --out-dir $R --clean-seeds --spine-at outer --reach 1.25 \
        > $R/build-seed.log 2>&1
    say "$P: built $(ls $R/outer-*.dom 2>/dev/null | wc -l) seeds"
    for c in a b c; do cp -f examples/$P/init.dom $R/cold-$c.dom; done
    # the field against §39.257's, before a single race evaluation (expectation 1)
    python experiments/diag_seed_field.py --programme $P --names "rooms (§39.257),outer" \
        experiments/results/halving-maple-rooms/seed-*.dom -- $R/outer-*.dom > $R/field.txt 2>&1
    publish "$P outer-spine field: $(ls $R/outer-*.dom | wc -l) seeds at $STAMP (homemaker-py-3xvb)" $R
fi
n=$(ls $R/outer-*.dom $R/cold-?.dom 2>/dev/null | wc -l)
[ "$n" -ge 20 ] || { echo "!!! only $n candidates"; exit 1; }
say "$P: race, $n candidates"
python -u experiments/successive_halving.py --programme $P \
    --seeds $R/outer-*.dom $R/cold-a.dom $R/cold-b.dom $R/cold-c.dom \
    --start 4000 --final 128000 --eta 2 --slots "$SLOTS" --rank total \
    --work "$W" --output "$R/winner.dom" > $R/race.log 2>&1
say "$P: race finished (rc=$?)"
cp -f $W/stages.tsv $R/stages.tsv
python experiments/diag_halving_connect.py $W $R --programme $P > $R/connect.txt 2>&1
python experiments/diag_halving_stairs.py $W > $R/stairs.txt 2>&1
python experiments/diag_halving_carry.py $R/winner.dom --programme $P \
    --seeds-dir $R --cold "${STAMP%% *}" > $R/carry.txt 2>&1
python experiments/diag_double_loaded.py $R/winner.dom > $R/double-loaded.txt 2>&1
last=$(ls -d $W/s[0-9]* | sort -V | tail -1)
for f in $last/*/out.dom; do cp -f "$f" "$R/final-$(basename "$(dirname "$f")").dom"; done
grep -l Traceback $R/*.txt $R/*.log 2>/dev/null && echo "!!! a step raised: read it before the results"
publish "$P outer-spine halving race at $STAMP: results (homemaker-py-3xvb)" $R
say "done"
