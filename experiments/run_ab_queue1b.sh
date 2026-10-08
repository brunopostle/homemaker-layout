#!/bin/bash
# The `native` A/B again, between the two queues.
#
# In experiments/run_ab_queue.sh it died after 6 of 36 pairs (2026-10-08 13:05):
# flag_ab.py loaded a native design into the quad tree to count its storeys,
# and the design did not fit one. The queue logged "finished native (rc=0)"
# under the traceback and went on to w4e -- do not trust that rc line; grep the
# log for Traceback. flag_ab.py is fixed; this runs what is
# missing, AFTER the first queue (so no more than eight searches share the
# box) and BEFORE the second (which merges src/ and moves the objective).
#
#   setsid nohup experiments/run_ab_queue1b.sh > ~/homemaker-ab-queue1b.log 2>&1 < /dev/null &
#   FIRST_LOG=~/homemaker-ab-queue1b.log setsid nohup experiments/run_ab_queue2.sh >> ~/homemaker-ab-queue2.log 2>&1 < /dev/null &
#
# The second line is how queue 2 is made to wait for this one: it looks for
# "queue complete" in FIRST_LOG.
cd "$(dirname "$0")/.." || exit 1
FIRST=${FIRST_LOG:-$HOME/homemaker-ab-queue.log}
SLOTS=${SLOTS:-8}
echo "=== $(date '+%F %T') waiting for the first queue ($FIRST)"
until grep -q 'queue complete' "$FIRST" 2>/dev/null \
      && ! pgrep -f 'homemaker_layout.evolve .*--budget 500000|flag_ab.py' >/dev/null; do
    sleep 60
done
echo "=== $(date '+%F %T') starting native (--resume)"
python experiments/flag_ab.py native --seeds 36 --slots "$SLOTS" --resume
rc=$?
echo "=== $(date '+%F %T') finished native (rc=$rc)"
if [ "$rc" -ne 0 ]; then
    echo "!!! native did not finish; queue 2 is NOT released. Fix it, then run this again."
    exit 1
fi
echo "=== $(date '+%F %T') queue complete"
