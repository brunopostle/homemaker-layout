#!/usr/bin/env bash
# homemaker-py-1s3 larger-N confirmation (DESIGN.md §33 follow-up): the full
# 20k-eval staged A/B (N=3 seeds) found the precision-weighted multi_use
# combination improves both example programmes (harbor-house -1.4%,
# health-centre -13.9%) but wasn't the clean sweep needed for a default
# flip -- harbor-house lost 1/3 seeds. Mirrors xyu/9yx's own larger-N
# confirmation protocol EXACTLY (DESIGN.md §31/§32,
# experiments/run_xyu_sweep.sh / run_9yx_sweep.sh): plain `homemaker-evolve`
# (not staged search), budget=3000, 4 workers, N=15 seeds, finish-time
# --collapse default. Cheaper per-run than the staged A/B so N=15 is
# tractable in a fraction of the time.
#
# Usage: experiments/run_1s3_confirm.sh
set -u
cd "$(dirname "$0")/.."

WORKERS=4
BUDGET=3000
SEEDS="1 2 3 4 5 6 7 8 9 10 11 12 13 14 15"
OUT=scratch/1s3_confirm; mkdir -p "$OUT"
TSV=scratch/1s3_confirm_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tmulti_use\tbudget\tfails\tfitness\telapsed_s\n' > "$TSV"

run() {  # programme seed multi_use(0|1)
  local prog="$1" seed="$2" mu="$3"
  local tag="mu${mu}"
  local dom="$OUT/${prog}_${tag}_s${seed}.dom"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  local flag="--no-multi-use"; [ "$mu" = 1 ] && flag="--multi-use"
  echo ">>> $prog seed=$seed multi_use=$mu budget=$BUDGET"
  local t0; t0=$(date +%s)
  homemaker-evolve "examples/$prog/init.dom" \
    --budget "$BUDGET" --workers "$WORKERS" --seed "$seed" \
    $flag --output "$dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fitness fails
  fitness=$(sed -n 's/^best *: \([0-9.e+-]*\) .*/\1/p' "$log")
  fails=$(sed -n 's/^best *: [0-9.e+-]* (\([0-9]*\) fails).*/\1/p' "$log")
  ( cd "examples/$prog" && homemaker-fitness "$(realpath "../../$dom")" > /dev/null 2>&1 )
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$prog" "$seed" "$mu" "$BUDGET" "${fails:-ERR}" "${fitness:-ERR}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, fitness=${fitness:-ERR}, $((t1-t0))s"
}

for prog in harbor-house health-centre; do
  for seed in $SEEDS; do run "$prog" "$seed" 0; done
  for seed in $SEEDS; do run "$prog" "$seed" 1; done
done

echo "=== 1s3 multi_use N=15 confirmation complete ==="
column -t -s $'\t' "$TSV"
