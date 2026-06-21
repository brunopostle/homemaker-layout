#!/usr/bin/env bash
# c3g granularity A/B (DESIGN.md §12.3 follow-up): does a coarser circulation
# spine (fewer, larger leaves -> lower shape floor) pay end-to-end, given that
# §12.3 showed shape fails are the HARD residual and access/adjacency are cheap
# to repair? Trade hard-shape for easy-access at the seed and measure.
#
# Reuses the §12.3 div=3 baseline (maple 126/148/134, harbor 72/81/69); runs
# div=6 and div=8 arms + a div=3 seed-0 control to confirm reproduction.
set -u
cd "$(dirname "$0")/.."
BUDGET="${1:-20000}"
OUT=scratch/c3g_ab; mkdir -p "$OUT"
TSV=scratch/c3g_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tcircdiv\tfails\ttopologies\telapsed_s\n' > "$TSV"

run() {  # programme seed div
  local prog="$1" seed="$2" div="$3"
  local log="$OUT/${prog}_div${div}_s${seed}.log"
  echo ">>> $prog seed=$seed circdiv=$div"
  local t0; t0=$(date +%s)
  env URB_NO_OCCLUSION=1 CIRCDIV="$div" \
    python3 experiments/run_staged_search.py "examples/$prog" "$BUDGET" "$seed" \
      "examples/$prog/init.dom" "$OUT/${prog}_div${div}_s${seed}.dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fails topos
  fails=$(grep 're-scored (native)' "$log" | tail -1 | sed -n 's/.*(\([0-9]*\) fails).*/\1/p')
  topos=$(grep -m1 '^evals' "$log" | sed -n 's/.*across \([0-9]*\) topologies.*/\1/p')
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$prog" "$seed" "$div" "${fails:-ERR}" "${topos:-?}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, ${topos:-?} topologies, $((t1-t0))s"
}

# control (reproduce §12.3 div=3) then the reduced-granularity arms
run maple-court 0 3
for seed in 0 1 2; do run maple-court "$seed" 6; run maple-court "$seed" 8; done
run harbor-house 0 3
for seed in 0 1 2; do run harbor-house "$seed" 6; done

echo "=== c3g sweep complete ==="
column -t -s $'\t' "$TSV"
