#!/usr/bin/env bash
# f1d A/B: does the ruin-and-recreate LNS move (un-divide one wing of a
# storey, rebuild it with the adjacency-aware constructor seeded from the
# surviving circulation bordering the wing) reduce the fail count relative
# to the current baseline (small local mutation operators only)? Same qpk
# protocol as 8sh/qi6: equal-budget ON vs OFF, both arms finished with the
# standard finish-time --collapse (94g) so the comparison is apples-to-apples
# on the final collapsed score.
#
# Authoritative metrics: total fail count read from the .fails file
# homemaker-fitness writes. Each run appends one TSV row so partial results
# survive an interrupt.
#
# Usage: experiments/run_f1d_ab.sh
set -u
cd "$(dirname "$0")/.."

WORKERS=4
OUT=scratch/f1d_ab; mkdir -p "$OUT"
TSV=scratch/f1d_ab_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\truin\tbudget\tfails\tfitness\telapsed_s\n' > "$TSV"

run() {  # programme seed ruin(0|1) budget
  local prog="$1" seed="$2" rr="$3" budget="$4"
  local tag="rr${rr}"
  local dom="$OUT/${prog}_${tag}_s${seed}.dom"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  local flag="--no-ruin-recreate"; [ "$rr" = 1 ] && flag="--ruin-recreate"
  echo ">>> $prog seed=$seed ruin_recreate=$rr budget=$budget"
  local t0; t0=$(date +%s)
  homemaker-evolve "examples/$prog/init.dom" \
    --budget "$budget" --workers "$WORKERS" --seed "$seed" \
    $flag --output "$dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fitness fails
  fitness=$(sed -n 's/^best *: \([0-9.e+-]*\) .*/\1/p' "$log")
  fails=$(sed -n 's/^best *: [0-9.e+-]* (\([0-9]*\) fails).*/\1/p' "$log")
  ( cd "examples/$prog" && homemaker-fitness "$(realpath "../../$dom")" > /dev/null 2>&1 )
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$prog" "$seed" "$rr" "$budget" "${fails:-ERR}" "${fitness:-ERR}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, fitness=${fitness:-ERR}, $((t1-t0))s"
}

# harbor-house: budget 2500, seeds 1-3 (qpk protocol)
for seed in 1 2 3; do run harbor-house "$seed" 0 2500; done
for seed in 1 2 3; do run harbor-house "$seed" 1 2500; done

# programme-house: budget 3000, seeds 1-5 (qpk protocol)
for seed in 1 2 3 4 5; do run programme-house "$seed" 0 3000; done
for seed in 1 2 3 4 5; do run programme-house "$seed" 1 3000; done

echo "=== f1d ruin_recreate A/B complete ==="
column -t -s $'\t' "$TSV"
