#!/bin/bash
# homemaker-py-2g7.13.1.2: successive halving over harbor-house's strategy
# portfolio -- 48 catalogue seeds (experiments/results/halving-harbor, 16 plans
# x 3 stair placements, today's seeder) plus the three footprint seeds and the
# owner's drawing as references. Two runs side by side, 4 slots each: ranked
# on STRUCTURAL fails (the question) and on TOTAL fails (the control).
# 4k evaluations rising x2 to 128k.
#
#   setsid nohup experiments/run_halving.sh > ~/homemaker-halving.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
H=examples/harbor-house
R=experiments/results/halving-harbor
SEEDS="$R/halv-*.dom $H/footprint-s0.dom $H/footprint-s1.dom $H/footprint-s2.dom $H/hand2a.dom"
echo "$(date '+%F %T') start, objective $(git log -1 --format=%h -- src/homemaker_layout/{cells,dom,dom_v2,fitness,geometry,graph,programme}.py)+orth, HEAD $(git rev-parse --short HEAD)"
for rank in structural total; do
    python -u experiments/successive_halving.py --programme harbor-house --seeds $SEEDS \
        --start 4000 --final 128000 --eta 2 --slots 4 --rank $rank \
        --work "$HOME/halving-harbor-$rank" --output "$R/winner-$rank.dom" \
        > "$HOME/homemaker-halving-$rank.log" 2>&1 &
    echo "$(date '+%F %T') $rank: pid $!"
done
wait
echo "$(date '+%F %T') done"
