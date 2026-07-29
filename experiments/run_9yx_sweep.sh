#!/usr/bin/env bash
# homemaker-py-9yx: non-synthetic third example (health-centre, 19 distinct
# codes / n=20 room instances, not a duplicated-count scale-up) repeats xyu's
# own protocol (DESIGN.md 31) -- ruin_recreate weight=3.0 ON vs OFF, budget
# 3000, 4 workers, finish-time collapse (default), N=15 seeds -- to see
# whether the ambiguous y51/xyu signal (9.3%->6.4% mean fails, p 0.098->0.059
# as N grew) was about room count or about the duplicated-code mechanism
# itself. Mirrors experiments/run_xyu_sweep.sh's run() function exactly,
# retargeted at examples/health-centre.
#
# Usage: experiments/run_9yx_sweep.sh
set -u
cd "$(dirname "$0")/.."

WORKERS=4
BUDGET=3000
SEEDS="1 2 3 4 5 6 7 8 9 10 11 12 13 14 15"
OUT=scratch/9yx_sweep; mkdir -p "$OUT"
TSV=scratch/9yx_sweep_results.tsv
[ -f "$TSV" ] || printf 'seed\truin\tbudget\tfails\tfitness\telapsed_s\n' > "$TSV"

run() {  # seed ruin(0|1)
  local seed="$1" rr="$2"
  local tag="rr${rr}"
  local dom="$OUT/${tag}_s${seed}.dom"
  local log="$OUT/${tag}_s${seed}.log"
  local flag="--no-ruin-recreate"; [ "$rr" = 1 ] && flag="--ruin-recreate"
  echo ">>> seed=$seed ruin_recreate=$rr budget=$BUDGET"
  local t0; t0=$(date +%s)
  homemaker-evolve "examples/health-centre/init.dom" \
    --budget "$BUDGET" --workers "$WORKERS" --seed "$seed" \
    $flag --output "$dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fitness fails
  fitness=$(sed -n 's/^best *: \([0-9.e+-]*\) .*/\1/p' "$log")
  fails=$(sed -n 's/^best *: [0-9.e+-]* (\([0-9]*\) fails).*/\1/p' "$log")
  ( cd "examples/health-centre" && homemaker-fitness "$(realpath "../../$dom")" > /dev/null 2>&1 )
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$seed" "$rr" "$BUDGET" "${fails:-ERR}" "${fitness:-ERR}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, fitness=${fitness:-ERR}, $((t1-t0))s"
}

for seed in $SEEDS; do run "$seed" 0; done
for seed in $SEEDS; do run "$seed" 1; done

echo "=== 9yx health-centre N=15 sweep complete ==="
column -t -s $'\t' "$TSV"
