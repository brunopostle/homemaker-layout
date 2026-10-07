#!/bin/bash
# The five paired A/Bs owed on 2026-10-07, one after another: they cannot
# share the box. Each is 36 paired seeds on programme-house at 500k, about
# 18-19 h at 8 slots; the queue is about four days. Order (owner, 2026-10-07):
#
#   child20  --child-budget 20          homemaker-py-8b2u.20, DESIGN.md §39.110
#   native   --native                   homemaker-py-8b2u.8,  DESIGN.md §39.104
#   w4e      --core-undivide-repaired   homemaker-py-w4e,     DESIGN.md §39.106
#   t7q      --no-repair-shaft          homemaker-py-t7q,     DESIGN.md §39.75
#   v2k      --level-add-migrate        homemaker-py-v2k,     DESIGN.md §39.71
#
# Every expectation is recorded before its run: the first three in
# flag_ab.py's docstring, the last two on their beads.
#
# DO NOT EDIT src/ WHILE THIS RUNS: every worker reads the editable install,
# and each A/B reads its objective stamp once at start. experiments/ and
# tests/ are safe. A failed A/B does not stop the queue; `--resume` picks up
# what is missing afterwards.
#
#   setsid nohup experiments/run_ab_queue.sh > ~/homemaker-ab-queue.log 2>&1 &
#   python experiments/flag_ab.py <name> --report-only      # any time
cd "$(dirname "$0")/.." || exit 1
SLOTS=${SLOTS:-8}
for name in ${QUEUE:-child20 native w4e t7q v2k}; do
    echo "=== $(date '+%F %T') starting $name"
    python experiments/flag_ab.py "$name" --seeds 36 --slots "$SLOTS" --resume
    echo "=== $(date '+%F %T') finished $name (rc=$?)"
done
echo "=== $(date '+%F %T') queue complete"
