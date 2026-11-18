#!/bin/bash
# homemaker-py-hlm1 / homemaker-py-5fje.25: stage-0 replicates of the moves
# A/B (§39.252-§39.254). The rooms race's 42 seed files, renamed -r1 and -r2
# so each gets a fresh rng seed (successive_halving seeds by candidate name),
# raced at 4k only, with remove_token + merge_circulation ON and OFF. Pooled
# with the original stage-0 pairs, N = 126. Search-side only.
#
#   setsid nohup experiments/run_halving_health_moves_rep.sh > ~/homemaker-halving-health-moves-rep.log 2>&1 < /dev/null &
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
N=experiments/results/halving-health-nomoves
R=experiments/results/halving-health-moves-rep
mkdir -p $R
for rep in r1 r2; do
    S=$HOME/halving-health-moves-rep/seeds-$rep
    rm -rf "$S"; mkdir -p "$S"
    for f in $C/one-*.dom $C/two-*.dom $C/cold-?.dom; do
        cp -f "$f" "$S/$(basename "$f" .dom)-$rep.dom"
    done
    for arm in on off; do
        v=1; [ $arm = off ] && v=0
        say "$rep $arm: $(ls $S/*.dom | wc -l) candidates at 4k"
        HOMEMAKER_REMOVE_TOKEN=$v HOMEMAKER_MERGE_CIRCULATION=$v \
        python -u experiments/successive_halving.py --programme $P --seeds $S/*.dom \
            --start 4000 --final 4000 --slots "$SLOTS" --rank total \
            --work "$HOME/halving-health-moves-rep/$rep-$arm" \
            --output "$HOME/halving-health-moves-rep/$rep-$arm.winner.dom" > $R/race-$rep-$arm.log 2>&1
        say "$rep $arm finished (rc=$?)"
        cp -f "$HOME/halving-health-moves-rep/$rep-$arm/stages.tsv" $R/stages-$rep-$arm.tsv
    done
    python experiments/pair_halving_stages.py $R/stages-$rep-on.tsv $R/stages-$rep-off.tsv \
        --stage 0 --labels moves nomoves > $R/paired-$rep.txt 2>&1
done
n_on=$(grep -rh "remove_token\|merge_circulation" $HOME/halving-health-moves-rep/r?-off | grep -vc noop)
say "real credits to either move in the OFF arms: $n_on (must be 0)"

# pooled: the original pair plus both replicates, one header each side
{ head -1 $C/stages.tsv; awk 'FNR>1 && $1==0' $C/stages.tsv $R/stages-r1-on.tsv $R/stages-r2-on.tsv; } > $R/pooled-on.tsv
{ head -1 $N/stages.tsv; awk 'FNR>1 && $1==0' $N/stages.tsv $R/stages-r1-off.tsv $R/stages-r2-off.tsv; } > $R/pooled-off.tsv
python experiments/pair_halving_stages.py $R/pooled-on.tsv $R/pooled-off.tsv \
    --stage 0 --labels moves nomoves > $R/paired-pooled.txt 2>&1
grep -l Traceback $R/*.txt $R/*.log 2>/dev/null && echo "!!! a step raised: read it before the results"
publish "health-centre moves A/B: stage-0 replicates and pooled pairing at $STAMP (homemaker-py-hlm1)" $R
say "moves replicates complete"
