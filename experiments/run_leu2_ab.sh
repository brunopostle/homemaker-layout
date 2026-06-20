#!/usr/bin/env bash
# leu.2 end-to-end A/B: proportion-aware split sizing (PROP=0 vs PROP=1).
# programme-house is single-stage (1 storey); harbor & maple-court are staged.
# Concurrency capped at 2 (machine has ~2 GB free). Results -> scratch/leu2/summary.tsv
set -u
cd "$(dirname "$0")/.."
OUT=scratch/leu2
mkdir -p "$OUT"
SUMMARY="$OUT/summary.tsv"
: > "$SUMMARY"
BUDGET=${BUDGET:-20000}
SEEDS=${SEEDS:-"0 1 2"}
MAXJOBS=${MAXJOBS:-2}

run_one() {
  local prog=$1 harness=$2 prop=$3 seed=$4
  local tag="${prog}_p${prop}_s${seed}"
  local log="$OUT/${tag}.log"
  URB_NO_OCCLUSION=1 PROP=$prop python3 "experiments/$harness" \
    "examples/$prog" "$BUDGET" "$seed" "examples/$prog/init.dom" \
    "$OUT/${tag}.dom" > "$log" 2>&1
  local best
  best=$(grep -oE 'best *: [0-9.eE+-]+ \([0-9]+ fails\)' "$log" | grep -oE '\([0-9]+ fails\)' | grep -oE '[0-9]+' | tail -1)
  printf '%s\t%s\t%s\t%s\t%s\n' "$prog" "$prop" "$seed" "${best:-ERR}" "$tag" >> "$SUMMARY"
  echo "DONE $tag -> ${best:-ERR} fails"
}

JOBS=()
for prog_h in "programme-house:run_search_scaled.py" \
              "harbor-house:run_staged_search.py" \
              "maple-court:run_staged_search.py"; do
  prog=${prog_h%%:*}; harness=${prog_h##*:}
  for prop in 0 1; do
    for seed in $SEEDS; do
      JOBS+=("$prog|$harness|$prop|$seed")
    done
  done
done

echo "queued ${#JOBS[@]} jobs, budget=$BUDGET, maxjobs=$MAXJOBS"
for job in "${JOBS[@]}"; do
  IFS='|' read -r prog harness prop seed <<< "$job"
  while [ "$(jobs -rp | wc -l)" -ge "$MAXJOBS" ]; do wait -n; done
  run_one "$prog" "$harness" "$prop" "$seed" &
done
wait
echo "ALL DONE"
sort "$SUMMARY" -o "$SUMMARY"
cat "$SUMMARY"
