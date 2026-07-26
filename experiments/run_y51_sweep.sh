#!/usr/bin/env bash
# homemaker-py-y51: locate the room-count threshold where ruin_recreate
# (weight=3.0, homemaker-py-f1d) stops helping. f1d found a clear win on
# programme-house (6 rooms, 8W/1L/6T over 15 seeds) but no consistent effect
# on harbor-house (37 room instances, 3W/2L/3T, slight negative lean) -- only
# two data points, so the size threshold was inferred rather than measured.
#
# No natural third example programme sits between the two (programme-house2
# is the same 6-room size; maple-court is even bigger than harbor-house), so
# this sweeps four SYNTHETIC sizes generated from programme-house's own
# patterns.config by scaling its b1/t1/b2/t2 bedroom+ensuite module count
# (examples/y51-sweep-{10,14,18,22}, see scratchpad gen_sweep.py), holding
# room-type mix, storey limits, ratios and adjacency constant -- isolating
# room count as the one variable that changes, unlike comparing against
# harbor-house's very different programme.
#
# Same qpk/f1d protocol: paired seeds, --ruin-recreate (weight=3.0, driver.py
# _MUTATION_WEIGHTS) ON vs OFF, both arms finish with the default --collapse
# (94g), 4 workers. budget=3000 calibrated (see timing probe) to leave
# nontrivial residual fails at every size (14/29/27/43 fails at seed 1,
# scaling roughly with room count) rather than saturating to ~0.
#
# Usage: experiments/run_y51_sweep.sh
set -u
cd "$(dirname "$0")/.."

WORKERS=4
BUDGET=3000
SIZES="10 14 18 22"
SEEDS="1 2 3 4 5"
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

echo "=== y51 room-count sweep complete ==="
column -t -s $'\t' "$TSV"
