#!/bin/bash
# Frozen-context repair vs whole-building search, same start, same budget
# (homemaker-py-2g7.13.1.5, DESIGN.md §39.166). Niced: queue 6 has the box.
cd "$(dirname "$0")" || exit 1
REPO=$(git rev-parse --show-toplevel)
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
B=${B:-30000}; SEED=${SEED:-0}
for st in s0 s1 s2 asbuilt; do
    nice -n 10 python "$REPO/experiments/dnc_frozen.py" search pasted-$st.dom --region l \
        --budget $B --seed $SEED --workers 1 --output frozen-$st-$B-s$SEED.dom \
        > frozen-$st-$B-s$SEED.log 2>&1 &
    nice -n 10 homemaker-evolve pasted-$st.dom --programme-dir "$REPO/examples/harbor-house" \
        --budget $B --seed $SEED --workers 1 --output global-$st-$B-s$SEED.dom \
        > global-$st-$B-s$SEED.log 2>&1 &
done
wait
echo "done $(date '+%F %T')"
