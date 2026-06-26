#!/usr/bin/env bash
# leaf_share_factor sweep under the winning bal+share stack (erc.7 second half,
# DESIGN.md §13.5). The §13.5 synergy A/B fixed factor 3 (the §13.3 winner) and
# showed depth-balancing × leaf-sharing survives to convergence (harbor −21 %,
# non-overlapping). This sweep asks whether factor 3 is still the construction
# optimum once depth-balancing is stacked on top: does collapsing FEWER (factor
# 2) or MORE (factor 4) same-code rooms per shared leaf do better?
#
# Both knobs ON in every run (DEPTHBAL=1 LEAFSHARE=1); only LEAFSHAREFAC varies.
# factor 3 bal+share is already known from run_synergy_ab.sh (maple 82.3, harbor
# 40.0), so we only run 2 and 4 here. leaf_share_max (scoring cap, default 4)
# already covers all multiplicities at factor ≤4, so no missing-fail leak — the
# final native re-score (MISMATCH guard) verifies this per run.
set -u
cd "$(dirname "$0")/.."
BUDGET="${1:-20000}"
OUT=scratch/sharefactor_sweep; mkdir -p "$OUT"
TSV=scratch/sharefactor_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tfactor\tfails\ttopologies\telapsed_s\n' > "$TSV"

run() {  # programme seed factor
  local prog="$1" seed="$2" fac="$3"
  local tag="bal_sh1f${fac}"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  echo ">>> $prog seed=$seed bal+share factor=$fac"
  local t0; t0=$(date +%s)
  env URB_NO_OCCLUSION=1 LEAFSHARE=1 LEAFSHAREFAC="$fac" DEPTHBAL=1 \
    python3 experiments/run_staged_search.py "examples/$prog" "$BUDGET" "$seed" \
      "examples/$prog/init.dom" "$OUT/${prog}_${tag}_s${seed}.dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fails topos
  fails=$(grep 're-scored (native)' "$log" | tail -1 | sed -n 's/.*(\([0-9]*\) fails).*/\1/p')
  topos=$(grep -m1 '^evals' "$log" | sed -n 's/.*across \([0-9]*\) topologies.*/\1/p')
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$prog" "$seed" "$fac" "${fails:-ERR}" "${topos:-?}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, ${topos:-?} topologies, $((t1-t0))s"
}

# factor 2 then factor 4, seeds 0/1/2 (factor 3 bal+share is in synergy_results.tsv)
for prog in maple-court harbor-house; do
  for fac in 2 4; do
    for seed in 0 1 2; do run "$prog" "$seed" "$fac"; done
  done
done

echo "=== leaf_share_factor sweep (bal+share) complete ==="
column -t -s $'\t' "$TSV"
