#!/bin/bash
# Divide and conquer from a catalogue seed (homemaker-py-2g7.13.1.5, §39.166).
# Each seed runs two identical chains of phases: ROUNDS rounds over the seed's
# regions (dnc_frozen.py regions), each phase continuing the last phase's
# output. Arm `dnc` freezes everything outside the phase's region; arm `whole`
# freezes nothing (region ''), so the two differ only by the freeze -- the
# restart from the best at every phase is common to both. Niced: queue 6 has
# the box.
cd "$(dirname "$0")" || exit 1
REPO=$(git rev-parse --show-toplevel)
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
TOTAL=${TOTAL:-60000}; ROUNDS=${ROUNDS:-2}; SEED=${SEED:-0}
SEEDS=${SEEDS:-"halv-1 halv-9 halv-13"}
chain() {   # chain <seed> <arm>
    local s=$1 arm=$2 regs prev phase=0 b
    regs=$(python "$REPO/experiments/dnc_frozen.py" regions "$REPO/experiments/results/halving-harbor/$s.dom")
    set -- $regs; local n=$#
    b=$(( TOTAL / (ROUNDS * n) ))
    prev="$REPO/experiments/results/halving-harbor/$s.dom"
    for r in $(seq 1 "$ROUNDS"); do
        for reg in $regs; do
            phase=$((phase + 1))
            local region=$reg; [ "$arm" = whole ] && region=""
            local out=chain-$s-$arm-p$phase.dom
            echo "$(date '+%T') $s $arm phase $phase region '${region}' budget $b" >> chain-$s-$arm.log
            nice -n 10 python "$REPO/experiments/dnc_frozen.py" search "$prev" --region "$region" \
                --budget "$b" --seed "$SEED" --workers 1 --output "$out" > "${out%.dom}.log" 2>&1 || {
                echo "phase $phase failed" >> chain-$s-$arm.log; return 1; }
            grep '^best' "${out%.dom}.log" >> chain-$s-$arm.log
            prev=$out
        done
    done
    cp -f "$prev" chain-$s-$arm-final.dom
}
for s in $SEEDS; do
    chain "$s" dnc &
    chain "$s" whole &
done
wait
echo "done $(date '+%F %T')"
