#!/bin/bash
# Give a QUEUED A/B its control arm from one still running, without editing the
# queue script (bash reads a running script as it goes, so editing one is unsafe).
#
#   experiments/prefill_when_ready.sh <source> <target> <programme> <pairs> <queue log>
#
# Waits until <source>'s control arm has all <pairs> seeds in its table, then
# runs prefill_control.py <source> <target> and commits the rows, the way the
# queue scripts do. It gives up, doing nothing, if the queue log already says
# "starting <target> on <programme>": a flag_ab.py that has started has queued
# its control runs, and rows supplied under it would be run twice.
#
# Written for queue 5 (2026-10-18): labels' control spans two search commits
# (0fd7d88 for seeds 0-19, 1db93d5 for 20-35), so prefill_control.py rightly
# refused labels -> aim and will refuse labels -> heights. aim's `random` arm is
# the default search at the live stamps on all 36 seeds, i.e. heights' control.
#
#   setsid nohup experiments/prefill_when_ready.sh aim heights programme-house 36 ~/homemaker-ab-queue5.log \
#       > ~/homemaker-prefill-heights.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
SRC=$1 DST=$2 PROG=$3 N=$4 QLOG=$5
[ -n "$QLOG" ] || { echo "usage: $0 source target programme pairs queue-log"; exit 2; }
ARM=$(python -c "import importlib.util as u; s=u.spec_from_file_location('a','experiments/flag_ab.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.EXPERIMENTS['$SRC']['arms'][0])")
say() { echo "=== $(date '+%F %T') $*"; }
say "waiting for $N '$ARM' seeds of $SRC on $PROG"
while :; do
    if grep -q "starting $DST on $PROG" "$QLOG" 2>/dev/null; then
        say "the queue has already started $DST on $PROG; nothing done"; exit 1
    fi
    have=$(awk -F'\t' -v a="$ARM" -v p="$PROG" '$2==a && $1==p {print $3}' "experiments/results/${SRC}_ab.tsv" 2>/dev/null | sort -u | wc -l)
    [ "$have" -ge "$N" ] && break
    sleep 30
done
say "$SRC has $have '$ARM' seeds; prefilling $DST"
HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/prefill_control.py "$SRC" "$DST" --programme "$PROG" || exit 1
for try in 1 2 3 4 5; do
    git add "experiments/results/${DST}_ab.tsv" "experiments/results/${DST}-ab" \
        && git commit -q -m "$DST A/B on $PROG: the control arm supplied from $SRC's (prefill_control.py, DESIGN.md §39.129)" \
        && { git pull -q --rebase; git push -q; } && break
    sleep 20
done
say "done"
