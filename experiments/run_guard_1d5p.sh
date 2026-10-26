#!/bin/bash
# homemaker-py-1d5p (owner's ruling, DESIGN.md §39.179/§39.180): the connection
# guard restricted to parents with every storey connected -- today's default,
# `--guard-connection=connected` -- replayed over stage 0 of both earlier guard
# races, and paired candidate by candidate against them.
#
#   harbor-house: §39.168's 99 candidates, paired against §39.168 (off) and
#                 §39.178 (any). Expected: cost vs off within MDD of zero
#                 (`any` paid +0.91, MDD 0.68).
#   maple-court:  §39.173's 48 spine seeds, paired against §39.173 (any).
#                 Expected: no run loses a storey its fully connected seed had.
#
# Stage 0 only (--final 4000): it is the stage whose pairs are clean.
#
#   setsid nohup experiments/run_guard_1d5p.sh > ~/homemaker-guard-1d5p.log 2>&1 < /dev/null &
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
until ! pgrep -f 'homemaker_layout.evolve|homemaker-evolve|flag_ab.py|run_coldstart_baseline|successive_halving' >/dev/null; do
    sleep 300
done
[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
git pull -q --rebase || echo "(pull failed; working with what is here)"
STAMP=$(python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit(), m.search_commit(), m.search_config()[0])")
say "start: objective, search, config = $STAMP; HEAD $(git rev-parse --short HEAD)"
R=experiments/results/guard-1d5p
mkdir -p $R/harbor $R/maple

# Preflight: the pairs are clean only if today's code with the OLD guard
# replays a control row exactly. One candidate per programme, `any`, 4k.
replays() {   # replays <programme> <seed.dom> <control stages.tsv>
    local name; name=$(basename "$2" .dom)
    python -u experiments/successive_halving.py --programme "$1" --seeds "$2" \
        --start 4000 --final 4000 --slots 1 --evolve-args=--guard-connection=any \
        --work "$HOME/guard-1d5p-pre-$1" > /dev/null 2>&1
    local got want
    got=$(awk -F'\t' -v c="$name" '$1==0 && $3==c {print $5}' "$HOME/guard-1d5p-pre-$1/stages.tsv")
    want=$(awk -F'\t' -v c="$name" '$1==0 && $3==c {print $5}' "$3")
    say "preflight $1 $name: replayed $got fails, control $want"
    [ -n "$got" ] && [ "$got" = "$want" ]
}
replays harbor-house experiments/results/halving-harbor-split/dealt-17.dom \
    experiments/results/halving-harbor-guard/stages.tsv \
    || { echo "!!! harbor-house does not replay: the pairs would not be clean"; exit 1; }
replays maple-court experiments/results/halving-maple-spine/spine-1.dom \
    experiments/results/halving-maple-connect/guard/stages.tsv \
    || { echo "!!! maple-court does not replay: the pairs would not be clean"; exit 1; }

HS=experiments/results/halving-harbor-split
n=$(ls $HS/dealt-*.dom $HS/cap-*.dom $HS/cold-?.dom | wc -l)
[ "$n" = 99 ] || { echo "!!! expected 99 candidates in $HS, found $n"; exit 1; }
say "harbor-house stage 0: $n candidates"
W=$HOME/guard-1d5p-harbor
python -u experiments/successive_halving.py --programme harbor-house \
    --seeds $HS/dealt-*.dom $HS/cap-*.dom $HS/cold-a.dom $HS/cold-b.dom $HS/cold-c.dom \
    --start 4000 --final 4000 --slots "$SLOTS" --rank total \
    --evolve-args=--guard-connection=connected --work "$W" > $R/harbor/race.log 2>&1
say "harbor-house finished (rc=$?)"
cp -f $W/stages.tsv $R/harbor/stages.tsv
python experiments/diag_halving_connect.py $W $HS --programme harbor-house > $R/harbor/connect.txt 2>&1
{ python experiments/pair_halving_stages.py $HS/stages.tsv $R/harbor/stages.tsv --labels off connected
  echo; python experiments/pair_halving_stages.py experiments/results/halving-harbor-guard/stages.tsv \
      $R/harbor/stages.tsv --labels any connected; } > $R/harbor/pairs.txt 2>&1

MS=experiments/results/halving-maple-spine
say "maple-court stage 0: $(ls $MS/spine-*.dom | wc -l) candidates"
W=$HOME/guard-1d5p-maple
python -u experiments/successive_halving.py --programme maple-court \
    --seeds $MS/spine-*.dom --start 4000 --final 4000 --slots "$SLOTS" --rank weighted \
    --evolve-args=--guard-connection=connected --work "$W" > $R/maple/race.log 2>&1
say "maple-court finished (rc=$?)"
cp -f $W/stages.tsv $R/maple/stages.tsv
python experiments/diag_halving_connect.py $W $MS --programme maple-court > $R/maple/connect.txt 2>&1
python experiments/pair_halving_stages.py experiments/results/halving-maple-connect/guard/stages.tsv \
    $R/maple/stages.tsv --labels any connected > $R/maple/pairs.txt 2>&1

grep -l Traceback $R/*/*.txt $R/*/race.log && echo "!!! a step raised: read it before the results"
publish "guard 1d5p replay: stage 0 of both guard races with the guard restricted to connected parents (homemaker-py-1d5p)" $R
say "guard 1d5p replay complete"
