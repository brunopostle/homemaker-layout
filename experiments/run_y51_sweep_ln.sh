#!/usr/bin/env bash
# homemaker-py-y51 larger-N confirmation: the initial 5-seed sweep
# (run_y51_sweep.sh) came back noisy and non-monotonic across synthetic sizes
# 10/14/18/22 (n=10: 3W/1L/1T; n=14: 0W/4L/1T; n=18: 4W/0L/1T; n=22: 2W/3L),
# none significant. Extends the two sizes that showed the strongest (opposite-
# direction) initial signal -- n=14 (loss-leaning) and n=18 (win-leaning) --
# with 5 more seeds each (6-10) to check whether either holds up or is N=5
# noise, mirroring this project's own larger-N-confirmation pattern (f1d, 1ph).
#
# Usage: experiments/run_y51_sweep_ln.sh
set -u
cd "$(dirname "$0")/.."

WORKERS=4
BUDGET=3000
SIZES="14 18"
SEEDS="6 7 8 9 10"
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

for n in $SIZES; do
  for seed in $SEEDS; do run "$n" "$seed" 0; done
  for seed in $SEEDS; do run "$n" "$seed" 1; done
done

echo "=== y51 larger-N confirmation complete ==="
column -t -s $'\t' "$TSV"
