#!/usr/bin/env bash
# lj3/qjg larger-N confirmation of 8sh's mixed A/B (DESIGN.md §21), combined
# with lj3's weight change in one sweep (weight and sample-size are separate
# variables tested together, not two separate small sweeps -- per lj3's own
# description). By the time this script runs, driver._MUTATION_WEIGHTS
# already carries "bridge_circulation": 2.0 (matching place_missing), so the
# ON arm here is "enabled + weight 2.0" vs the original 8sh A/B's "enabled +
# uniform weight ~1.0".
#
# Same qpk/1ph protocol as the original run_8sh_ab.sh and the 1ph
# programme-house larger-N confirmation (DESIGN.md §20): equal-budget ON vs
# OFF, both arms finished with the standard finish-time --collapse (94g),
# canonical homemaker-fitness re-score for the .fails breakdown. 1ph used
# 4x the original N (5->20) on programme-house alone; this sweep does the
# same for programme-house (5->20) and a matched 4x for harbor-house (3->12).
#
# Usage: experiments/run_lj3_qjg_ab.sh
set -u
cd "$(dirname "$0")/.."

WORKERS=4
OUT=scratch/lj3_qjg_ab; mkdir -p "$OUT"
TSV=scratch/lj3_qjg_ab_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tbridge\tbudget\tfails\tnot_connected\tfitness\telapsed_s\n' > "$TSV"

run() {  # programme seed bridge(0|1) budget
  local prog="$1" seed="$2" bc="$3" budget="$4"
  local tag="bc${bc}"
  local dom="$OUT/${prog}_${tag}_s${seed}.dom"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  local flag="--no-bridge-circulation"; [ "$bc" = 1 ] && flag="--bridge-circulation"
  echo ">>> $prog seed=$seed bridge=$bc budget=$budget"
  local t0; t0=$(date +%s)
  homemaker-evolve "examples/$prog/init.dom" \
    --budget "$budget" --workers "$WORKERS" --seed "$seed" \
    $flag --output "$dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fitness fails notconn
  fitness=$(sed -n 's/^best *: \([0-9.e+-]*\) .*/\1/p' "$log")
  fails=$(sed -n 's/^best *: [0-9.e+-]* (\([0-9]*\) fails).*/\1/p' "$log")
  ( cd "examples/$prog" && homemaker-fitness "$(realpath "../../$dom")" > /dev/null 2>&1 )
  notconn=0
  if [ -f "${dom}.fails" ]; then
    notconn=$(grep -c 'not connected' "${dom}.fails")
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$prog" "$seed" "$bc" "$budget" "${fails:-ERR}" "$notconn" "${fitness:-ERR}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails (${notconn} not-connected), fitness=${fitness:-ERR}, $((t1-t0))s"
}

# programme-house: budget 3000, seeds 1-20 (1ph protocol, 4x the original 8sh N=5)
for seed in $(seq 1 20); do run programme-house "$seed" 0 3000; done
for seed in $(seq 1 20); do run programme-house "$seed" 1 3000; done

# harbor-house: budget 2500, seeds 1-12 (matched 4x the original 8sh N=3)
for seed in $(seq 1 12); do run harbor-house "$seed" 0 2500; done
for seed in $(seq 1 12); do run harbor-house "$seed" 1 2500; done

echo "=== lj3/qjg bridge_circulation larger-N A/B complete ==="
column -t -s $'\t' "$TSV"
