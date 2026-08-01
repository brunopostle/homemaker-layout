#!/usr/bin/env bash
# homemaker-py-1s3 larger-N confirmation, SAME conditions (DESIGN.md §33):
# the N=15/budget=3000/plain-search confirmation (run_1s3_confirm.sh) came
# back negative on both programmes, but that protocol differs from the one
# the original positive result was measured under (staged search, budget
# 20000 -- run_multiuse_ab.sh, N=3) in both budget AND, for the multi-storey
# harbor-house, search algorithm (search_staged falls back to plain search
# only on single-storey programmes). This script is the true same-conditions
# confirmation: identical to run_multiuse_ab.sh (staged, 20000, 4 workers)
# but N=15 seeds instead of 3, so it can actually confirm or refute the
# original finding rather than answering a different question. Expensive
# (~10h sequential at this budget/seed count) -- run in background.
#
# Usage: experiments/run_1s3_confirm_staged.sh
set -u
cd "$(dirname "$0")/.."
BUDGET="${1:-20000}"
SEEDS="${SEEDS:-0 1 2 3 4 5 6 7 8 9 10 11 12 13 14}"
OUT=scratch/1s3_confirm_staged; mkdir -p "$OUT"
TSV=scratch/1s3_confirm_staged_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tmulti_use\tfails\ttopologies\telapsed_s\n' > "$TSV"

run() {  # programme seed multi_use(0|1)
  local prog="$1" seed="$2" mu="$3"
  local tag="mu${mu}"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  echo ">>> $prog seed=$seed multi_use=$mu"
  local t0; t0=$(date +%s)
  env URB_NO_OCCLUSION=1 MULTIUSE="$mu" WORKERS="${WORKERS:-4}" \
    python3 experiments/run_staged_search.py "examples/$prog" "$BUDGET" "$seed" \
      "examples/$prog/init.dom" "$OUT/${prog}_${tag}_s${seed}.dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fails topos
  fails=$(grep 're-scored (native)' "$log" | tail -1 | sed -n 's/.*(\([0-9]*\) fails).*/\1/p')
  topos=$(grep -m1 '^evals' "$log" | sed -n 's/.*across \([0-9]*\) topologies.*/\1/p')
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$prog" "$seed" "$mu" "${fails:-ERR}" "${topos:-?}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, ${topos:-?} topologies, $((t1-t0))s"
}

for prog in harbor-house health-centre; do
  for seed in $SEEDS; do run "$prog" "$seed" 0; done
  for seed in $SEEDS; do run "$prog" "$seed" 1; done
done

echo "=== 1s3 staged-conditions N=15 confirmation complete ==="
column -t -s $'\t' "$TSV"
