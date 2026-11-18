#!/bin/bash
# homemaker-py-hlm1 / homemaker-py-5fje.25: the rooms race of §39.250-§39.251
# again with BOTH repair moves off -- `remove_token` and `merge_circulation` --
# and nothing else changed: the same 42 seed files, copied from that race, the
# same rng seed per candidate. Search-side only; the objective is unchanged.
# A preflight replays one rooms-race stage-0 row with the moves ON, so the
# stage-0 pairing is clean. Expectations in DESIGN.md §39.252.
#
#   setsid nohup experiments/run_halving_health_nomoves.sh > ~/homemaker-halving-health-nomoves.log 2>&1 < /dev/null &
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

P=health-centre
C=experiments/results/halving-health-rooms
R=experiments/results/halving-health-nomoves
W=$HOME/halving-health-nomoves
mkdir -p $R

# Preflight, moves ON: today's code must replay a rooms-race stage-0 row exactly.
PRE=$HOME/halving-health-nomoves-pre
python -u experiments/successive_halving.py --programme $P --seeds $C/one-10.dom \
    --start 4000 --final 4000 --slots 1 --work $PRE > /dev/null 2>&1
got=$(awk -F'\t' '$1==0 && $3=="one-10" {print $5}' $PRE/stages.tsv)
want=$(awk -F'\t' '$1==0 && $3=="one-10" {print $5}' $C/stages.tsv)
say "preflight one-10: replayed $got fails, control $want"
[ -n "$got" ] && [ "$got" = "$want" ] || { echo "!!! does not replay: the pairs would not be clean"; exit 1; }

for f in $C/one-*.dom $C/two-*.dom $C/cold-?.dom; do cp -f "$f" $R/; done
n=$(ls $R/one-*.dom $R/two-*.dom $R/cold-?.dom | wc -l)
publish "health-centre no-moves halving: $n candidates copied from the rooms race at $STAMP (homemaker-py-hlm1)" $R

export HOMEMAKER_REMOVE_TOKEN=0 HOMEMAKER_MERGE_CIRCULATION=0
say "race: $n candidates, remove_token and merge_circulation OFF"
python -u experiments/successive_halving.py --programme $P \
    --seeds $R/one-*.dom $R/two-*.dom $R/cold-a.dom $R/cold-b.dom $R/cold-c.dom \
    --start 4000 --final 128000 --eta 2 --slots "$SLOTS" --rank total \
    --work "$W" --output "$R/winner.dom" > $R/race.log 2>&1
say "race finished (rc=$?)"
n_on=$(grep -rh "remove_token\|merge_circulation" $W | grep -vc noop)
say "real credits to either move with both off: $n_on (must be 0)"

cp -f $W/stages.tsv $R/stages.tsv
python experiments/diag_halving_connect.py $W $R --programme $P > $R/connect.txt 2>&1
python experiments/diag_halving_stairs.py $W > $R/stairs.txt 2>&1
python experiments/diag_halving_carry.py $R/winner.dom --programme $P \
    --seeds-dir $R --cold "${STAMP%% *}" > $R/carry.txt 2>&1
grep -l Traceback $R/*.txt $R/*.log 2>/dev/null && echo "!!! a step raised: read it before the results"
python experiments/pair_halving_stages.py $C/stages.tsv $R/stages.tsv \
    --stage 0 --labels moves nomoves > $R/paired.txt 2>&1
publish "health-centre no-moves race at $STAMP: results and stage-0 pairing (homemaker-py-hlm1)" $R
say "health-centre no-moves race complete"
