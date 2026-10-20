#!/bin/bash
# homemaker-py-iplo: settle `aim` on programme-house. §39.152 left it at the
# edge -- fails 0.92 -> 0.61, a margin equal to the MDD at 36 pairs, p 0.054 --
# and ab_report.py put the pairs needed at ~38. Owner, 2026-10-20: run them.
# Twelve more pairs (seeds 36-47), both arms, so the total is 48.
#
# MUST run at the search commit of the first 36 (1db93d5): the branch
# `height-cap` (label write-back default ON, the height cap) and
# `stair-separation` land only AFTER this. It refuses otherwise.
#
# Waits for the maple-court halving (run_halving_maple.sh) to say "done".
#
#   setsid nohup experiments/run_aim_extend.sh > ~/homemaker-aim-extend.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
FIRST=${FIRST_LOG:-$HOME/homemaker-halving-maple.log}
WANT_SEARCH=1db93d5
WANT_OBJ=4428262+orth
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
unset HOMEMAKER_ORTHOGONAL_DIVISION HOMEMAKER_MOVE_LOG HOMEMAKER_SEED_SOLVER HOMEMAKER_CORE_UNDIVIDE_REPAIRED \
      HOMEMAKER_TUNE_HEIGHTS HOMEMAKER_NATIVE HOMEMAKER_LIGHT_WELL HOMEMAKER_LABEL_WRITEBACK HOMEMAKER_AIM_UNDIVIDE
say() { echo "=== $(date '+%F %T') $*"; }

say "waiting for $FIRST"
until grep -q '=== .* done$' "$FIRST" 2>/dev/null \
      && ! pgrep -f 'homemaker_layout.evolve|homemaker-evolve|flag_ab.py|run_coldstart_baseline|successive_halving' >/dev/null; do
    sleep 300
done
git pull -q --rebase || echo "(pull failed; working with what is here)"
read OBJ SEARCH < <(HOMEMAKER_ORTHOGONAL_DIVISION=1 python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit(), m.search_commit())")
[ "$OBJ" = "$WANT_OBJ" ] && [ "$SEARCH" = "$WANT_SEARCH" ] \
    || { echo "!!! stamps are $OBJ / $SEARCH, not $WANT_OBJ / $WANT_SEARCH: the new pairs would not pair with the first 36"; exit 1; }
say "objective $OBJ, search $SEARCH; aim to 48 pairs"
python experiments/flag_ab.py aim --programme programme-house --seeds 48 --slots 8 --resume
say "finished aim (rc=$?)"
python experiments/flag_ab.py aim --programme programme-house --report-only
grep -q Traceback "$HOME/homemaker-aim-extend.log" 2>/dev/null && echo "!!! a Traceback is in this log: read it"
say "aim extension complete"
