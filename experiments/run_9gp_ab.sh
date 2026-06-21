#!/usr/bin/env bash
# 9gp A/B sweep (DESIGN.md §12.3): baseline vs reassociate vs shape-feasibility
# vs combined, on the maple-court scaling benchmark + harbor, seeds 0/1/2.
#
# Authoritative metric = the re-scored native fail count (the "re-scored
# (native): <fit> (<n> fails) -> OK" line). Each run appends one TSV row to
# scratch/9gp_ab_results.tsv so partial results survive an interrupt.
#
# Usage: experiments/run_9gp_ab.sh [budget] [seeds...]
set -u
cd "$(dirname "$0")/.."

BUDGET="${1:-20000}"; shift || true
SEEDS=("${@:-0 1 2}")
# shellcheck disable=SC2206
SEEDS=(${SEEDS[*]})

OUT=scratch/9gp_ab
mkdir -p "$OUT"
TSV=scratch/9gp_ab_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tconfig\tfails\tevals\ttopologies\telapsed_s\n' > "$TSV"

# per-programme prune threshold (below the incumbent range; the pred>=best guard
# in driver._evaluate dominates — see DESIGN.md §12.3 calibration).
declare -A MAXSHAPE=( [maple-court]=100 [harbor-house]=55 )

run() {  # programme seed config_name  ENVVARS...
  local prog="$1" seed="$2" cfg="$3"; shift 3
  local dom="examples/$prog/init.dom"
  local out="$OUT/${prog}_${cfg}_s${seed}.dom"
  local log="$OUT/${prog}_${cfg}_s${seed}.log"
  echo ">>> $prog seed=$seed config=$cfg  ($*)"
  local t0; t0=$(date +%s)
  env URB_NO_OCCLUSION=1 "$@" \
    python3 experiments/run_staged_search.py "examples/$prog" "$BUDGET" "$seed" "$dom" "$out" \
    > "$log" 2>&1
  local t1; t1=$(date +%s)
  # authoritative re-scored native fail count
  local line fails evals topos
  line=$(grep 're-scored (native)' "$log" | tail -1)
  fails=$(printf '%s' "$line" | sed -n 's/.*(\([0-9]*\) fails).*/\1/p')
  evals=$(grep -m1 '^evals' "$log" | sed -n 's/.*: \([0-9]*\) across.*/\1/p')
  topos=$(grep -m1 '^evals' "$log" | sed -n 's/.*across \([0-9]*\) topologies.*/\1/p')
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$prog" "$seed" "$cfg" "${fails:-ERR}" "${evals:-?}" "${topos:-?}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, ${topos:-?} topologies, $((t1-t0))s"
}

for prog in maple-court harbor-house; do
  ms="${MAXSHAPE[$prog]}"
  for seed in "${SEEDS[@]}"; do
    run "$prog" "$seed" baseline  REASSOC=0 FEAS=0
    run "$prog" "$seed" reassoc   REASSOC=1 FEAS=0
    run "$prog" "$seed" feas      REASSOC=0 FEAS=1 MAXSHAPE="$ms"
    run "$prog" "$seed" combined  REASSOC=1 FEAS=1 MAXSHAPE="$ms"
  done
done

echo "=== sweep complete ==="
column -t -s $'\t' "$TSV"
