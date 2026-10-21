#!/bin/bash
# Three cold stand-alone searches on the cut wing (homemaker-py-2g7.13.1.5).
cd "$(dirname "$0")" || exit 1
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
for s in 0 1 2; do
    homemaker-evolve init.dom --budget 50000 --seed $s --workers 1 \
        --output cold-50000-s$s.dom > cold-50000-s$s.log 2>&1 &
done
wait
echo "done $(date '+%F %T')"
