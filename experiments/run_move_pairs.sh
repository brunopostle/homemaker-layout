#!/bin/bash
# The pair census (homemaker-py-urzf, DESIGN.md §39.124), detached:
#   setsid nohup experiments/run_move_pairs.sh > ~/homemaker-pairs.log 2>&1 < /dev/null &
# Resumable: rows already under experiments/results/move_pairs/ are skipped.
# Run it from the move-book worktree; nice 10 and four jobs (at nice 19 it got 3% of a core), beside the A/B queue.
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD/src" HOMEMAKER_ORTHOGONAL_DIVISION=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
JOBS=${JOBS:-4}
nice -n 10 python experiments/diag_move_pairs.py --screen --jobs "$JOBS" --pair-draws 6 --single-draws 12 || exit 1
nice -n 10 python experiments/diag_move_pairs.py --confirm --jobs "$JOBS" --confirm-draws 24 || exit 1
python experiments/diag_move_pairs.py --report
echo "=== $(date '+%F %T') pair census complete: commit experiments/results/move_pairs/ and write DESIGN.md §39.124"
