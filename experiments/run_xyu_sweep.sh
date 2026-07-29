#!/usr/bin/env bash
# homemaker-py-xyu: y51 follow-up (a) -- extend the n=18 synthetic sweep size
# (the strongest, non-monotonic trend of y51's four sizes: 7W/2L/1T at N=10,
# +9.3% mean fails, Wilcoxon p=0.098) to N=15 seeds, matching the N needed for
# f1d's own programme-house confirmation (p=0.041 at N=15 for a similar-
# magnitude ~15% effect). Appends 5 fresh seeds (11-15) to the existing
# scratch/y51_sweep_results.tsv rows for n=18 seeds 1-10.
#
# Usage: experiments/run_xyu_sweep.sh
set -u
cd "$(dirname "$0")/.."

WORKERS=4
BUDGET=3000
N=18
SEEDS="11 12 13 14 15"
OUT=scratch/y51_sweep; mkdir -p "$OUT"
TSV=scratch/y51_sweep_results.tsv
[ -f "$TSV" ] || printf 'n_rooms\tseed\truin\tbudget\tfails\tfitness\telapsed_s\n' > "$TSV"

run() {  # n_rooms seed ruin(0|1)
  local n="$1" seed="$2" rr="$3"
  local tag="rr${rr}"
  local dom="$OUT/n${n}_${tag}_s${seed}.dom"
  local log="$OUT/n${n}_${tag}_s${seed}.log"
  local flag="--no-ruin-recreate"; [ "$rr" = 1 ] && flag="--ruin-recreate"
  echo ">>> n_rooms=$n seed=$seed ruin_recreate=$rr budget=$BUDGET"
  local t0; t0=$(date +%s)
  homemaker-evolve "examples/y51-sweep-$n/init.dom" \
    --budget "$BUDGET" --workers "$WORKERS" --seed "$seed" \
    $flag --output "$dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fitness fails
  fitness=$(sed -n 's/^best *: \([0-9.e+-]*\) .*/\1/p' "$log")
  fails=$(sed -n 's/^best *: [0-9.e+-]* (\([0-9]*\) fails).*/\1/p' "$log")
  ( cd "examples/y51-sweep-$n" && homemaker-fitness "$(realpath "../../$dom")" > /dev/null 2>&1 )
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$n" "$seed" "$rr" "$BUDGET" "${fails:-ERR}" "${fitness:-ERR}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, fitness=${fitness:-ERR}, $((t1-t0))s"
}

for seed in $SEEDS; do run "$N" "$seed" 0; done
for seed in $SEEDS; do run "$N" "$seed" 1; done

echo "=== xyu n=18 N=15 confirmation complete ==="
column -t -s $'\t' "$TSV"
