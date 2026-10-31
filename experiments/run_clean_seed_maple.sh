#!/bin/bash
# homemaker-py-4872: what does a single-loaded plan cost on maple-court? §39.187's
# race did not say: its winner inherited a double-loaded corridor from its seed.
# Here no seed has one, and the field holds no other kind, so clean seeds are not
# knocked out early by a plan they are trying to price. Expectations, DESIGN.md §39.189:
#
#   1. at least 40 seeds survive --clean-seeds, each reading 0 double-loaded;
#   2. stage 0 median above sp11's single arm (79.5), because `outer` starts
#      133 of 144 storeys unconnected against 62;
#   3. the winner is worse than 13 fails, at 15-25;
#   4. at least half the finalists grow a double-loaded corridor over 8 m, since
#      nothing keeps them off one (spine-3 did), despite §39.188's synthetic plots;
#   5. the winner still has a storey not connected;
#   6. at least one finalist has a stair cell over 15 m (homemaker-py-yd6t).
#
# Control: sp11's race, same objective, search commit and config, compared
# stage by stage, unpaired. The script refuses a different stamp, because the
# comparison would then mean nothing.
#
#   setsid nohup experiments/run_clean_seed_maple.sh > ~/homemaker-clean-seed-maple.log 2>&1 < /dev/null &
#   RESUME=1 setsid nohup experiments/run_clean_seed_maple.sh >> ~/homemaker-clean-seed-maple.log 2>&1 < /dev/null &
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

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NE6FXtUoA8scvkzqSFD6M3" && { git pull -q --rebase; git push -q; } \
        || echo "!!! could not publish: $msg"
}

[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
STAMP=$(python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit(), m.search_commit(), m.search_config()[0])")
say "start: objective, search, config = $STAMP; HEAD $(git rev-parse --short HEAD)"
[ "$STAMP" = "c73dfde+orth fefeb72 517acdbf88" ] || { echo "!!! not sp11's stamp: the control does not apply"; exit 1; }

P=maple-court
R=experiments/results/halving-maple-clean
W=$HOME/halving-maple-clean
mkdir -p $R
if [ -z "$RESUME" ]; then
    : > $R/race.log
    say "building clean seeds"
    # 22 plans x 3: outer drops about a quarter (11 of 48 in seeding-outer)
    python experiments/seed_from_catalogue.py --programme $P \
        --max-seeds 22 --core-variants 3 --write 48 --prefix clean \
        --out-dir $R --reach 1.25 --spine-at outer --clean-seeds --storeys 3 > $R/build-clean.log 2>&1
    say "built $(ls $R/clean-*.dom 2>/dev/null | wc -l) clean seeds (rc=$?)"
    for c in a b c; do cp -f examples/$P/init.dom $R/cold-$c.dom; done
    python experiments/diag_double_loaded.py --summary $R/clean-*.dom > $R/double-loaded-seeds.txt 2>&1
fi
n=$(ls $R/clean-*.dom 2>/dev/null | wc -l)
[ "$n" -ge 40 ] || { echo "!!! expected at least 40 clean seeds, found $n"; exit 1; }

say "race: $n clean + 3 cold${RESUME:+ (resuming)}"
python -u experiments/successive_halving.py --programme $P \
    --seeds $R/clean-*.dom $R/cold-a.dom $R/cold-b.dom $R/cold-c.dom \
    --start 4000 --final 128000 --eta 2 --slots "$SLOTS" --rank total \
    --work "$W" --output "$R/winner.dom" ${RESUME:+--resume} >> $R/race.log 2>&1
say "race finished (rc=$?)"

cp -f $W/stages.tsv $R/stages.tsv
python experiments/diag_halving_connect.py $W $R --programme $P > $R/connect.txt 2>&1
python experiments/diag_halving_stairs.py $W > $R/stairs.txt 2>&1
python experiments/diag_halving_carry.py $R/winner.dom --programme $P \
    --seeds-dir $R --cold "${STAMP%% *}" > $R/carry.txt 2>&1
python experiments/diag_double_loaded.py $R/winner.dom > $R/double-loaded-winner.txt 2>&1
python experiments/diag_double_loaded.py --summary $W/s*/*/out.dom > $R/double-loaded-stages.txt 2>&1
last=$(ls -d $W/s* | sort -V | tail -1)
python experiments/diag_long_stairs.py --over 8 $last/*/out.dom > $R/long-stairs-finalists.txt 2>&1
for f in $last/*/out.dom; do cp -f "$f" "$R/final-$(basename "$(dirname "$f")").dom"; done
grep -l Traceback $R/*.txt $R/*.log && echo "!!! a step raised: read it before the results"
publish "clean-seed race on maple-court (homemaker-py-4872)" $R
say "clean-seed race complete"
