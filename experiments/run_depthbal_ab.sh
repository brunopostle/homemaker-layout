#!/usr/bin/env bash
# Depth-balanced construction A/B (erc.4, DESIGN.md §13.4): does growing a
# DEPTH-BALANCED slicing tree (always split a shallowest leaf) instead of the
# default random caterpillar lower the end-to-end fail count? Diag B (§13.2)
# localized the size fails to depth-driven maldistribution (same-target rooms at
# 0.05x..14.7x by slicing position); the §13.4 floor probe showed balancing
# collapses the depth spread (7->1) and the giant ratio (maxR 12.7->8.4 harbor,
# 16.7->6.3 maple) and drops the achievable seed floor -12% harbor / -11% maple
# at EQUAL leaf count.
#
# Baseline arm (DEPTHBAL=0) must reproduce the §12.2 figures (maple 136.0,
# harbor 74.0); the balanced arm (DEPTHBAL=1) is the experiment. Leaf-sharing
# stays OFF in both arms here — the share synergy is erc.7.
set -u
cd "$(dirname "$0")/.."
BUDGET="${1:-20000}"
OUT=scratch/depthbal_ab; mkdir -p "$OUT"
TSV=scratch/depthbal_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tdepthbal\tfails\ttopologies\telapsed_s\n' > "$TSV"

run() {  # programme seed depthbal(0|1)
  local prog="$1" seed="$2" bal="$3"
  local tag="db${bal}"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  echo ">>> $prog seed=$seed depthbal=$bal"
  local t0; t0=$(date +%s)
  env URB_NO_OCCLUSION=1 DEPTHBAL="$bal" \
    python3 experiments/run_staged_search.py "examples/$prog" "$BUDGET" "$seed" \
      "examples/$prog/init.dom" "$OUT/${prog}_${tag}_s${seed}.dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fails topos
  fails=$(grep 're-scored (native)' "$log" | tail -1 | sed -n 's/.*(\([0-9]*\) fails).*/\1/p')
  topos=$(grep -m1 '^evals' "$log" | sed -n 's/.*across \([0-9]*\) topologies.*/\1/p')
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$prog" "$seed" "$bal" "${fails:-ERR}" "${topos:-?}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, ${topos:-?} topologies, $((t1-t0))s"
}

# baseline controls (reproduce §12.2) then the depth-balanced arm, seeds 0/1/2
for prog in maple-court harbor-house; do
  for seed in 0 1 2; do run "$prog" "$seed" 0; done
  for seed in 0 1 2; do run "$prog" "$seed" 1; done
done

echo "=== depth-balanced A/B complete ==="
column -t -s $'\t' "$TSV"
