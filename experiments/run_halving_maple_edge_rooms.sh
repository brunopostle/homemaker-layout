#!/bin/bash
# homemaker-py-3xvb: maple-court's single-row race (§39.259) won at 26 fails with every
# storey unjoined, and bridge_indoors joins none of its finalists. Its seeds ran each
# wing's spine along an edge no other wing shares (--spine-at outer), so the wings start
# apart. This race is the same field with --spine-at edge: a spine may run along an edge
# two wings share, which joins them (sp11's single arm, §39.187), and --clean-seeds drops
# any seed where that makes a double-loaded corridor. 36 plans x 3 stair placements, up
# to 64 written, plus 3 cold; everything else as run_halving_maple_single_rooms.sh.
# Controls, same stamp, unpaired: §39.257 (seeder defaults) and §39.259 (outer).
# Expectations in DESIGN.md §39.260.
#
#   setsid nohup experiments/run_halving_maple_edge_rooms.sh > ~/homemaker-halving-maple-edge-rooms.log 2>&1 < /dev/null &
#   RESUME=1 setsid nohup experiments/run_halving_maple_edge_rooms.sh >> ~/homemaker-halving-maple-edge-rooms.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
SLOTS=${SLOTS:-8}
CONTROL_STAMP="6191a338+orth 6191a338 82241975c2"
export HOMEMAKER_PIVOT3=1 HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset HOMEMAKER_MOVE_LOG HOMEMAKER_SEED_SOLVER HOMEMAKER_CORE_UNDIVIDE_REPAIRED \
      HOMEMAKER_TUNE_HEIGHTS HOMEMAKER_NATIVE HOMEMAKER_LIGHT_WELL HOMEMAKER_LABEL_WRITEBACK \
      HOMEMAKER_AIM_UNDIVIDE HOMEMAKER_RETYPE_KIND HOMEMAKER_PIVOT HOMEMAKER_GUARD_CONNECTION \
      HOMEMAKER_SPLIT_STAIR HOMEMAKER_REMOVE_TOKEN HOMEMAKER_MERGE_CIRCULATION
say() { echo "=== $(date '+%F %T') $*"; }
publish() {   # publish <message> <paths...>
    local msg=$1; shift
    git add -- "$@" && git commit -q -m "$msg

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NE6FXs7ZwmmJsgwHuK1NiB" && { git pull -q --rebase; git push -q; } \
        || echo "!!! could not publish: $msg"
}

until ! pgrep -f 'homemaker_layout[.]evolve|homemaker-evolve |flag_ab[.]py |run_coldstart_baseline[.]py |successive_halving[.]py ' >/dev/null; do
    say "waiting for the box"; sleep 300
done
[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
git pull -q --rebase || echo "(pull failed; working with what is here)"
STAMP=$(python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit(), m.search_commit(), m.search_config()[0])")
say "start: objective, search, config = $STAMP; HEAD $(git rev-parse --short HEAD)"
short() { sed 's/\([0-9a-f]\{7\}\)[0-9a-f]*/\1/g' <<<"$1"; }   # git's abbreviation length varies
[ "$(short "$STAMP")" = "$(short "$CONTROL_STAMP")" ] || { echo "!!! stamp $STAMP is not the control's ($CONTROL_STAMP)"; exit 1; }

P=maple-court
R=experiments/results/halving-maple-edge-rooms
W=$HOME/halving-maple-edge-rooms
mkdir -p $R
if [ -z "$RESUME" ]; then
    : > $R/race.log
    say "building seeds"
    python experiments/seed_from_catalogue.py --programme $P --max-seeds 36 --core-variants 3 \
        --write 64 --prefix edge --out-dir $R \
        --reach 1.25 --spine-at edge --clean-seeds --storeys 3 > $R/build-seed.log 2>&1
    say "built $(ls $R/edge-*.dom 2>/dev/null | wc -l) seeds (rc=$?)"
    for c in a b c; do cp -f examples/$P/init.dom $R/cold-$c.dom; done
    python experiments/diag_double_loaded.py --summary $R/edge-*.dom > $R/double-loaded-seeds.txt 2>&1
fi
n=$(ls $R/edge-*.dom $R/cold-?.dom 2>/dev/null | wc -l)
[ "$n" -ge 40 ] || { echo "!!! only $n candidates"; exit 1; }
[ -n "$RESUME" ] || publish "maple-court edge-spine rooms halving: $n candidates built at $STAMP (homemaker-py-3xvb)" $R

say "race, $n candidates${RESUME:+ (resuming)}"
python -u experiments/successive_halving.py --programme $P \
    --seeds $R/edge-*.dom $R/cold-a.dom $R/cold-b.dom $R/cold-c.dom \
    --start 4000 --final 128000 --eta 2 --slots "$SLOTS" --rank total \
    --work "$W" --output "$R/winner.dom" ${RESUME:+--resume} >> $R/race.log 2>&1
say "race finished (rc=$?)"
cp -f $W/stages.tsv $R/stages.tsv
python experiments/diag_halving_connect.py $W $R --programme $P > $R/connect.txt 2>&1
python experiments/diag_halving_stairs.py $W > $R/stairs.txt 2>&1
python experiments/diag_halving_carry.py $R/winner.dom --programme $P \
    --seeds-dir $R --cold "${STAMP%% *}" > $R/carry.txt 2>&1
python experiments/diag_double_loaded.py $R/winner.dom > $R/double-loaded-winner.txt 2>&1
last=$(ls -d $W/s[0-9]* | sort -V | tail -1)
for f in $last/*/out.dom; do cp -f "$f" "$R/final-$(basename "$(dirname "$f")").dom"; done
grep -l Traceback $R/*.txt $R/*.log 2>/dev/null && echo "!!! a step raised: read it before the results"
publish "maple-court edge-spine rooms halving race at $STAMP: results (homemaker-py-3xvb)" $R
say "maple edge-spine race complete"
