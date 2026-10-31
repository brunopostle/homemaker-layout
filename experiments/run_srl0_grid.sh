#!/bin/bash
# homemaker-py-srl0: the penalty grid, from seeds, because the cold pilot made a
# double-loaded corridor in only 3 runs of 20 (results/srl0-penalty/pilot.txt).
# So every arm starts from a plot-long corridor with rooms both sides, and the
# grid asks what makes the search get rid of one, NOT what stops it making one.
# A control beside it: the same rooms single-loaded, off arm only, which prices
# single-loading on that plot and shows whether the search keeps it clean.
#
# Unsearched seed fails, double against single (--check-seeds): deep7 3 / 13,
# deep9 3 / 33, deep11 3 / 41, deep13 27 / 49. Rooms in one row on a 30 m plot are
# narrow and deep, so they lose daylight and proportion. So a penalty has this much
# to overcome before search, and the corridor is 29.5 m, which m5 prices at 5 fails
# and m2 at 14.
#
# Expected, written before it runs:
# 1. off: all runs keep a corridor over 25 m on deep7, deep9, deep11. Nothing
#    rewards leaving a 3-fail plan.
# 2. k2, k5, m5 are too small against that price: at most 1 run of 6 per model
#    loses its corridor, unless the search finds a dodge (a jog, a corridor pushed
#    to one wall) that costs less than a single-loaded plan. If runs do lose it,
#    read HOW before calling it a working penalty.
# 3. k12, m2: enough to pay for it on deep7 only. Under half of deep7 runs lose it,
#    because no one operator gets from this plan to a single-loaded one.
# 4. guard: declines added metres and does not remove any, so like off.
# 5. single, off arm: base fails stay at least 5 above double's off arm on every
#    model, after search. So the price is real, not an artefact of an unsearched
#    seed. At most 2 of 6 make a double-loaded corridor on deep7; more on deep11.
#
#   setsid nohup experiments/run_srl0_grid.sh > ~/homemaker-srl0-grid.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH=$PWD/src
say() { echo "=== $(date '+%F %T') $*"; }
[ "$(git branch --show-current)" = srl0 ] || { echo "!!! not on srl0"; exit 1; }
R=experiments/results/srl0-penalty
M="deep7 deep9 deep11 deep13"
say "start: HEAD $(git rev-parse --short HEAD)"
python experiments/srl0_penalty_sweep.py --check-seeds "$HOME/srl0-grid" | tee $R/seeds.txt || { echo "!!! a seed is wrong"; exit 1; }
python -u experiments/srl0_penalty_sweep.py --work "$HOME/srl0-grid/single" --table $R/grid-single.tsv \
    --start single --models $M --arms off --seeds 6 --budget 16000 --slots "${SLOTS:-8}"
say "single control finished (rc=$?)"
python -u experiments/srl0_penalty_sweep.py --work "$HOME/srl0-grid/double" --table $R/grid-double.tsv \
    --start double --models $M --arms off k2 k5 k12 m5 m2 guard --seeds 6 --budget 16000 --slots "${SLOTS:-8}"
say "grid finished (rc=$?)"
{ echo "== started double-loaded"; python experiments/srl0_penalty_sweep.py --report $R/grid-double.tsv
  echo; echo "== started single-loaded"; python experiments/srl0_penalty_sweep.py --report $R/grid-single.tsv; } > $R/grid.txt 2>&1
cat $R/grid.txt
git add -- $R && git commit -q -m "srl0 grid: penalties from a seed that has the corridor (homemaker-py-srl0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NE6FXtUoA8scvkzqSFD6M3" && git push -q || echo "!!! could not commit or push"
say "grid complete"
