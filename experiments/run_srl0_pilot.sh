#!/bin/bash
# homemaker-py-srl0: does the search make a double-loaded corridor at all on the
# synthetic models? A penalty cannot be measured where the control has none to
# prevent: a 3k smoke run made none on deep7 or deep11 in any arm. So the off arm
# alone, 4 seeds at 16k, before the grid. Rows land in the sweep's table, so the
# grid continues from them.
#
# Expected, written before it runs: none on deep7, where a corridor with rooms
# both sides does not fit; on deep11 and deep13 fewer than half of the runs have
# one, since a cold search on a long plot spends 16k on connecting the storey;
# court few. If no model reaches 2 of 4, the grid must start from a seed that
# has a double-loaded corridor, and then it asks what KEEPS one, not what stops
# the search making one.
#
#   setsid nohup experiments/run_srl0_pilot.sh > ~/homemaker-srl0-pilot.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH=$PWD/src
say() { echo "=== $(date '+%F %T') $*"; }
say "waiting for the box"
until ! pgrep -f 'homemaker_layout[.]evolve|homemaker-evolve |flag_ab[.]py |run_coldstart_baseline[.]py |successive_halving[.]py |run_single_loaded_maple' >/dev/null; do
    sleep 300
done
[ "$(git branch --show-current)" = srl0 ] || { echo "!!! not on srl0"; exit 1; }
R=experiments/results/srl0-penalty
say "start: HEAD $(git rev-parse --short HEAD)"
python -u experiments/srl0_penalty_sweep.py --work "$HOME/srl0-sweep" --table $R/sweep.tsv \
    --arms off --seeds 4 --budget 16000 --slots "${SLOTS:-8}"
say "pilot finished (rc=$?)"
python experiments/srl0_penalty_sweep.py --report $R/sweep.tsv > $R/pilot.txt 2>&1
cat $R/pilot.txt
git add -- $R && git commit -q -m "srl0 pilot: the control arm on the synthetic models (homemaker-py-srl0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NE6FXvn91JjbzZYtRwJNAt" && git push -q || echo "!!! could not publish"
say "pilot complete"
