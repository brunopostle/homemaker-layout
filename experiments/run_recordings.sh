#!/bin/bash
# The move recordings (homemaker-py-urzf), detached from any session:
#   setsid nohup experiments/run_recordings.sh > ~/homemaker-recordings.log 2>&1 &
# Runs already under experiments/results/moves/ are skipped, so it can be
# started again at any time. Run it from the move-book worktree: it records
# with THIS tree's src (the recorder is not on main until the branch merges).
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH="$PWD/src"
python experiments/record_moves.py --programme programme-house --seeds 12 --budget 100000 --jobs 4
python experiments/record_moves.py --programme harbor-house --seeds 4 --budget 60000 --jobs 4
echo "=== $(date '+%F %T') recordings complete: commit experiments/results/moves/ and run experiments/diag_move_book.py"
