#!/bin/bash
# The unfinished half of queue 4, unattended. Queue 4 (run_ab_queue4.sh) ran its
# re-baseline and hand-seeded runs, then stopped on 2026-10-15 inside `labels`
# on programme-house at 20 of 36 pairs, when the box went to the wings A/B
# (§39.150). `aim`, `heights` and `well` never started, and four beads wait on
# them (urzf.1, iplo, y4p4.2, evxm). This is its steps 5 and 6, unchanged:
#
#   1. WAIT for the harbor-house halving (run_halving.sh) to say "done" and for
#      every search to exit.
#   2. REFUSE unless the objective is still 4428262+orth: labels' 20 pairs are
#      at that stamp, so the stair-separation ruling (homemaker-py-2g7.12,
#      which moves it) lands only AFTER this queue.
#   3. labels (resume, 16 pairs), aim and heights on programme-house with their
#      control arm supplied from labels' (prefill_control.py, §39.129); well on
#      harbor-house, then heights there with well's control.
#
# Estimate, from queue 4's own run times (programme-house ~2.5 h, harbor-house
# ~15 h, 8 slots): labels ~5 h, aim ~11 h, heights ~11 h, well ~15 h,
# heights on harbor-house ~15 h -- about 2.5 days.
#
#   setsid nohup experiments/run_ab_queue5.sh > ~/homemaker-ab-queue5.log 2>&1 < /dev/null &
#
# DO NOT EDIT src/ ON MAIN while this runs. Do not trust a "finished" line
# without grepping the log for Traceback.
cd "$(dirname "$0")/.." || exit 1
FIRST=${FIRST_LOG:-$HOME/homemaker-halving.log}
SLOTS=${SLOTS:-8}
WANT=4428262+orth
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset HOMEMAKER_ORTHOGONAL_DIVISION HOMEMAKER_MOVE_LOG HOMEMAKER_SEED_SOLVER HOMEMAKER_CORE_UNDIVIDE_REPAIRED \
      HOMEMAKER_TUNE_HEIGHTS HOMEMAKER_NATIVE HOMEMAKER_LIGHT_WELL HOMEMAKER_LABEL_WRITEBACK HOMEMAKER_AIM_UNDIVIDE
say() { echo "=== $(date '+%F %T') $*"; }

say "waiting for $FIRST"
until grep -q ' done$' "$FIRST" 2>/dev/null \
      && ! pgrep -f 'homemaker_layout.evolve|homemaker-evolve|flag_ab.py|run_coldstart_baseline|successive_halving' >/dev/null; do
    sleep 300
done
say "the halving is complete"

[ "$(git branch --show-current)" = main ] || { echo "!!! not on main"; exit 1; }
git pull -q --rebase || echo "(pull failed; working with what is here)"
STAMP=$(HOMEMAKER_ORTHOGONAL_DIVISION=1 python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit())")
[ "$STAMP" = "$WANT" ] || { echo "!!! objective is $STAMP, not $WANT: labels' 20 pairs would not pair with the rest"; exit 1; }
say "objective $STAMP"

ab() {   # ab <experiment> <programme> <pairs>
    grep -q "\"$1\": dict" experiments/flag_ab.py || { echo "!!! flag_ab.py has no experiment '$1'; skipped"; return; }
    say "starting $1 on $2 ($3 pairs)"
    python experiments/flag_ab.py "$1" --programme "$2" --seeds "$3" --slots "$SLOTS" --resume
    say "finished $1 on $2 (rc=$?)"
}
ab labels programme-house 36
for exp in aim heights; do
    python experiments/prefill_control.py labels $exp --programme programme-house \
        && { git add experiments/results/${exp}_ab.tsv experiments/results/${exp}-ab; \
             git commit -q -m "$exp A/B: the control arm supplied from labels' (prefill_control.py, DESIGN.md §39.129)"; \
             git pull -q --rebase; git push -q; }
    ab $exp programme-house 36
done
ab well harbor-house 4
python experiments/prefill_control.py well heights --programme harbor-house \
    && { git add experiments/results/heights_ab.tsv experiments/results/heights-ab; \
         git commit -q -m "heights A/B on harbor-house: the control arm supplied from well's (prefill_control.py)"; \
         git pull -q --rebase; git push -q; }
ab heights harbor-house 4
grep -q Traceback "$HOME/homemaker-ab-queue5.log" 2>/dev/null && echo "!!! a Traceback is in this log: read it"
say "queue 5 complete"
