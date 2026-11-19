#!/bin/bash
# homemaker-py-hlm1 follow-up: harbor-house then maple-court, raced afresh at the
# objective of §39.246/§39.249 (dead end at 11 m, outdoor space not circulation,
# token rooms scored missing; `narrow room` is health-centre only), which every
# committed design of theirs fails badly (36 and 34 fails at best). Seeder at its
# defaults plus --clean-seeds, 16 plans x 3 stair placements, 48 written, plus 3
# cold; `pivot3` on, as in the health races since the corridors race (§39.242). Expectations in DESIGN.md §39.256.
#
#   setsid nohup experiments/run_halving_housing_rooms.sh > ~/homemaker-halving-housing-rooms.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
SLOTS=${SLOTS:-7}
export HOMEMAKER_PIVOT3=1 HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset HOMEMAKER_MOVE_LOG HOMEMAKER_SEED_SOLVER HOMEMAKER_CORE_UNDIVIDE_REPAIRED \
      HOMEMAKER_TUNE_HEIGHTS HOMEMAKER_NATIVE HOMEMAKER_LIGHT_WELL HOMEMAKER_LABEL_WRITEBACK \
      HOMEMAKER_AIM_UNDIVIDE HOMEMAKER_RETYPE_KIND HOMEMAKER_PIVOT HOMEMAKER_GUARD_CONNECTION \
      HOMEMAKER_SPLIT_STAIR HOMEMAKER_REMOVE_TOKEN HOMEMAKER_MERGE_CIRCULATION
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

race() {   # race <programme> <short>
    local P=$1 R=experiments/results/halving-$2-rooms W=$HOME/halving-$2-rooms
    mkdir -p $R
    say "$P: building seeds"
    python experiments/seed_from_catalogue.py --programme $P --max-seeds 16 --core-variants 3 \
        --write 48 --prefix seed --out-dir $R --clean-seeds > $R/build-seed.log 2>&1
    say "$P: built $(ls $R/seed-*.dom 2>/dev/null | wc -l) seeds (rc=$?)"
    for c in a b c; do cp -f examples/$P/init.dom $R/cold-$c.dom; done
    local n; n=$(ls $R/seed-*.dom $R/cold-?.dom 2>/dev/null | wc -l)
    [ "$n" -ge 20 ] || { echo "!!! $P: only $n candidates"; return 1; }
    publish "$P rooms halving: $n candidates built at $STAMP (homemaker-py-hlm1)" $R
    say "$P: race, $n candidates"
    python -u experiments/successive_halving.py --programme $P \
        --seeds $R/seed-*.dom $R/cold-a.dom $R/cold-b.dom $R/cold-c.dom \
        --start 4000 --final 128000 --eta 2 --slots "$SLOTS" --rank total \
        --work "$W" --output "$R/winner.dom" > $R/race.log 2>&1
    say "$P: race finished (rc=$?)"
    cp -f $W/stages.tsv $R/stages.tsv
    python experiments/diag_halving_connect.py $W $R --programme $P > $R/connect.txt 2>&1
    python experiments/diag_halving_stairs.py $W > $R/stairs.txt 2>&1
    python experiments/diag_halving_carry.py $R/winner.dom --programme $P \
        --seeds-dir $R --cold "${STAMP%% *}" > $R/carry.txt 2>&1
    local last; last=$(ls -d $W/s[0-9]* | sort -V | tail -1)
    for f in $last/*/out.dom; do cp -f "$f" "$R/final-$(basename "$(dirname "$f")").dom"; done
    grep -l Traceback $R/*.txt $R/*.log 2>/dev/null && echo "!!! $P: a step raised: read it before the results"
    publish "$P rooms halving race at $STAMP: results (homemaker-py-hlm1)" $R
}
race harbor-house harbor
race maple-court maple
say "housing races complete"
