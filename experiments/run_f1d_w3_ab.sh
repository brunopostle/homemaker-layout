#!/usr/bin/env bash
# f1d weight follow-up: the initial run_f1d_ab.sh A/B (uniform uneabled weight,
# ~7.5% activation among active ops) came back essentially null (1 win, 1
# loss, 6 ties out of 8 paired seeds) with a directly-instrumented run showing
# ruin_recreate fired only ~1/32 children -- likely underpowered rather than
# a clean negative. driver._MUTATION_WEIGHTS now carries a temporary
# "ruin_recreate": 3.0 (matching place_missing's weight, mirroring the lj3
# weight-bump precedent) to raise the activation rate; this reruns the ON arm
# only at the SAME seeds/budgets as run_f1d_ab.sh so it is directly
# comparable against the existing rr=0 baseline rows in
# scratch/f1d_ab_results.tsv.
#
# Usage: experiments/run_f1d_w3_ab.sh
set -u
cd "$(dirname "$0")/.."

WORKERS=4
OUT=scratch/f1d_w3_ab; mkdir -p "$OUT"
TSV=scratch/f1d_w3_ab_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\truin\tweight\tbudget\tfails\tfitness\telapsed_s\n' > "$TSV"

run() {  # programme seed budget
  local prog="$1" seed="$2" budget="$3"
  local dom="$OUT/${prog}_rr1w3_s${seed}.dom"
  local log="$OUT/${prog}_rr1w3_s${seed}.log"
  echo ">>> $prog seed=$seed ruin_recreate=1 weight=3.0 budget=$budget"
  local t0; t0=$(date +%s)
  homemaker-evolve "examples/$prog/init.dom" \
    --budget "$budget" --workers "$WORKERS" --seed "$seed" \
    --ruin-recreate --output "$dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fitness fails
  fitness=$(sed -n 's/^best *: \([0-9.e+-]*\) .*/\1/p' "$log")
  fails=$(sed -n 's/^best *: [0-9.e+-]* (\([0-9]*\) fails).*/\1/p' "$log")
  ( cd "examples/$prog" && homemaker-fitness "$(realpath "../../$dom")" > /dev/null 2>&1 )
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$prog" "$seed" "1" "3.0" "$budget" "${fails:-ERR}" "${fitness:-ERR}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, fitness=${fitness:-ERR}, $((t1-t0))s"
}

for seed in 1 2 3; do run harbor-house "$seed" 2500; done
for seed in 1 2 3 4 5; do run programme-house "$seed" 3000; done

echo "=== f1d weight=3.0 follow-up complete ==="
column -t -s $'\t' "$TSV"
