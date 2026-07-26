#!/usr/bin/env bash
# f1d larger-N confirmation: the weight=3.0 follow-up (run_f1d_w3_ab.sh)
# showed a striking, consistent programme-house improvement (4 wins + 1 tie,
# 0 losses, mean fails 8.6 -> 5.75 across seeds 1-5) but a mixed harbor-house
# result (1 win, 1 tie, 1 loss). Extends BOTH arms to seeds 6-15 on
# programme-house and 4-8 on harbor-house so the N=5/N=3 initial reads are
# confirmed or falsified on fresh seeds, mirroring the project's own
# 1ph/qjg larger-N-confirmation pattern. driver._MUTATION_WEIGHTS still
# carries the temporary "ruin_recreate": 3.0 from the w3 follow-up.
#
# Usage: experiments/run_f1d_larger_n.sh
set -u
cd "$(dirname "$0")/.."

WORKERS=4
OUT=scratch/f1d_ln; mkdir -p "$OUT"
TSV=scratch/f1d_ln_results.tsv
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

# programme-house: seeds 6-15, both arms
for seed in $(seq 6 15); do run programme-house "$seed" 0 3000; done
for seed in $(seq 6 15); do run programme-house "$seed" 1 3000; done

# harbor-house: seeds 4-8, both arms
for seed in $(seq 4 8); do run harbor-house "$seed" 0 2500; done
for seed in $(seq 4 8); do run harbor-house "$seed" 1 2500; done

echo "=== f1d larger-N confirmation complete ==="
column -t -s $'\t' "$TSV"
