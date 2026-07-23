#!/usr/bin/env bash
# qi6 A/B (DESIGN.md §18): does the graded circulation-connectivity signal
# actually pull full-budget evolve runs toward connected circulation and clear
# 'level N not connected' fails, or is the secondary-comparator gradient too
# weak to matter (mirrors the qpk §20 protocol: equal-budget ON vs OFF, both
# arms finished with the standard finish-time --collapse (94g) so the
# comparison is apples-to-apples on the final collapsed score)?
#
# Authoritative metrics: total fail count and 'not connected' fail count, read
# from the .fails file homemaker-fitness writes (evolve.py itself only prints
# n_fails, not the fail list). Each run appends one TSV row so partial results
# survive an interrupt.
#
# Usage: experiments/run_qi6_ab.sh
set -u
cd "$(dirname "$0")/.."

WORKERS=4
OUT=scratch/qi6_ab; mkdir -p "$OUT"
TSV=scratch/qi6_ab_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tconn_grade\tbudget\tfails\tnot_connected\tfitness\telapsed_s\n' > "$TSV"

run() {  # programme seed conn_grade(0|1) budget
  local prog="$1" seed="$2" cg="$3" budget="$4"
  local tag="cg${cg}"
  local dom="$OUT/${prog}_${tag}_s${seed}.dom"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  local flag="--no-conn-grade"; [ "$cg" = 1 ] && flag="--conn-grade"
  echo ">>> $prog seed=$seed conn_grade=$cg budget=$budget"
  local t0; t0=$(date +%s)
  homemaker-evolve "examples/$prog/init.dom" \
    --budget "$budget" --workers "$WORKERS" --seed "$seed" \
    $flag --output "$dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fitness fails notconn
  fitness=$(sed -n 's/^best *: \([0-9.e+-]*\) .*/\1/p' "$log")
  fails=$(sed -n 's/^best *: [0-9.e+-]* (\([0-9]*\) fails).*/\1/p' "$log")
  # re-score with the canonical scorer to get the .fails breakdown (evolve.py
  # only prints the count, not the list); dom lives outside examples/$prog so
  # pass an absolute path while cd'd there for patterns.config resolution
  ( cd "examples/$prog" && homemaker-fitness "$(realpath "../../$dom")" > /dev/null 2>&1 )
  notconn=0
  if [ -f "${dom}.fails" ]; then
    notconn=$(grep -c 'not connected' "${dom}.fails")
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$prog" "$seed" "$cg" "$budget" "${fails:-ERR}" "$notconn" "${fitness:-ERR}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails (${notconn} not-connected), fitness=${fitness:-ERR}, $((t1-t0))s"
}

# harbor-house: budget 2500, seeds 1-3 (qpk protocol)
for seed in 1 2 3; do run harbor-house "$seed" 0 2500; done
for seed in 1 2 3; do run harbor-house "$seed" 1 2500; done

# programme-house: budget 3000, seeds 1-5 (qpk protocol)
for seed in 1 2 3 4 5; do run programme-house "$seed" 0 3000; done
for seed in 1 2 3 4 5; do run programme-house "$seed" 1 3000; done

echo "=== qi6 conn_grade A/B complete ==="
column -t -s $'\t' "$TSV"
