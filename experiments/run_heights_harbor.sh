#!/bin/bash
# homemaker-py-y4p4.2: does `--tune-heights`, now capped at the brief's 3.9 m
# in 75 mm courses (§39.153), help on harbor-house? Expectation written first,
# DESIGN.md §39.184.
#
# A CONTINUATION A/B, not a race. The height move is one of 26 equally
# weighted moves, so a 4k stage-0 run draws it about twice and stage 0 cannot
# see it (two 4k smoke runs moved no storey). Instead: the 13 candidates that
# reached stage 3 (32k) of the §39.182 spine race, each continued for another
# 32k three times (names <cand>-a/-b/-c, so three rng seeds), once with
# today's default search (`fixed`) and once with --tune-heights (`heights`).
# Same file and same rng seed in both arms, so 39 clean pairs. Both arms run
# at once, half the slots each, so they share the box's load.
#
#   setsid nohup experiments/run_heights_harbor.sh > ~/homemaker-heights-harbor.log 2>&1 < /dev/null &
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
S3=$HOME/halving-harbor-spine/s3                  # the spine race's stage-3 outputs
R=experiments/results/halving-harbor-heights
WF=$HOME/halving-harbor-heights-fixed
WH=$HOME/halving-harbor-heights-tuned
mkdir -p $R/field
n=0
for d in $S3/*/; do
    c=$(basename "$d")
    for k in a b c; do cp -f "$d/out.dom" "$R/field/$c-$k.dom"; n=$((n + 1)); done
done
[ "$n" = 39 ] || { echo "!!! expected 39 field files from 13 stage-3 candidates, found $n"; exit 1; }

# Preflight: a field file must score as the spine race's stage 3 recorded it.
python - "$R/field" experiments/results/halving-harbor-spine/stages.tsv <<'PY' || exit 1
import copy, csv, sys
from pathlib import Path
sys.path.insert(0, "experiments")
from successive_halving import REPO, load_config
from homemaker_layout import dom, geometry
from homemaker_layout.fitness import Fitness
fit = Fitness(*load_config(REPO / "examples" / "harbor-house"))
want = {r["candidate"]: int(r["fails"]) for r in csv.DictReader(open(sys.argv[2]), delimiter="\t")
        if r["stage"] == "3"}
for f in sorted(Path(sys.argv[1]).glob("*-a.dom")):
    r = dom.load(str(f)); dom.link(r); geometry.clear_cache()
    got = len(fit.score_with_fails(copy.deepcopy(r))[1])
    if got != want[f.stem[:-2]]:
        sys.exit(f"!!! {f.name} scores {got} fails, stage 3 recorded {want[f.stem[:-2]]}")
print(f"=== field reproduces stage 3 on all {len(want)} candidates")
PY

HALF=$((SLOTS / 2))
say "continuation: 39 candidates x 2 arms, 32k each, $HALF slots per arm"
run() {   # run <work> <log> [evolve args]
    python -u experiments/successive_halving.py --programme $P --seeds $R/field/*.dom \
        --start 32000 --final 32000 --slots "$HALF" --rank total \
        ${3:+--evolve-args=$3} --work "$1" > "$2" 2>&1
}
run $WF $R/fixed.log &
run $WH $R/heights.log --tune-heights &
wait
say "both arms finished"

cp -f $WF/stages.tsv $R/fixed.tsv
cp -f $WH/stages.tsv $R/heights.tsv
python experiments/pair_halving_stages.py $R/fixed.tsv $R/heights.tsv --labels fixed heights \
    --programme $P --works $WF $WH \
    --family crinkliness --family level --family "too few stairs" --family size \
    > $R/pairs.txt 2>&1
python experiments/diag_halving_heights.py $WH $R/field --programme $P > $R/heights.txt 2>&1
python experiments/diag_halving_heights.py $WF $R/field --programme $P --expect-fixed > $R/heights-fixed.txt 2>&1 \
    || echo "!!! the fixed arm moved a storey: the control is broken"
grep -l Traceback $R/*.txt $R/*.log && echo "!!! a step raised: read it before the results"
publish "heights continuation A/B on harbor-house: 39 pairs at 32k (homemaker-py-y4p4.2)" $R
say "heights A/B complete"
