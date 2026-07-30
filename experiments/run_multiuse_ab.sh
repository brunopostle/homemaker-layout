#!/usr/bin/env bash
# Multi-use leaves A/B (homemaker-py-1s3, DESIGN.md §26 path b): does fusing
# permanent DIFFERENT-code pairs onto one leaf (co_locate, validated against
# interchangeable()'s S1-S4 bounds) lower the end-to-end fail count the same
# way leaf-sharing's SAME-code multiplicity did (§13.3, -32...-39% on the
# floor)? Baseline arm (MULTIUSE=0) must reproduce the current default stack;
# the experiment arm (MULTIUSE=1) is the lever. Both arms score against
# whichever example programme's patterns.config declares co_locate pairs
# (harbor-house: ef1/m, la1/me1; health-centre: ao1/mo1, ao1/br1, de1/ms1,
# dp1/re1 — see §29/§26-path-b write-up).
set -u
cd "$(dirname "$0")/.."
BUDGET="${1:-20000}"
OUT=scratch/multiuse_ab; mkdir -p "$OUT"
TSV=scratch/multiuse_results.tsv
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

# baseline controls (must reproduce the current default stack) then the
# multi_use arm, both seeds 0/1/2, on both example program with declared
# co_locate pairs.
for prog in harbor-house health-centre; do
  for seed in 0 1 2; do run "$prog" "$seed" 0; done
  for seed in 0 1 2; do run "$prog" "$seed" 1; done
done

echo "=== multi-use A/B complete ==="
column -t -s $'\t' "$TSV"
