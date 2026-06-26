#!/usr/bin/env bash
# Leaf-sharing × depth-balancing synergy A/B (erc.7, DESIGN.md §13.5). The
# decisive test the §13.4 floor probe set up: depth-balanced construction was
# only MODEST standalone end-to-end (the 20k search erodes the seed advantage
# via divide/undivide), but the floor probe showed bal+sh3 beats share3-alone
# at EQUAL leaf count (harbor 65.3 vs 73.3, maple 113.7 vs 133.0) — additive on
# the leaf-COUNT cut the search cannot erode. Does that additive seed floor
# survive to convergence once stacked on leaf-sharing?
#
# Both arms keep LEAFSHARE=1 (factor 3, the §13.3 winner). The control arm is
# share-alone (DEPTHBAL=0) — must reproduce §13.3 (maple 86.3, harbor 50.3);
# the experiment arm adds DEPTHBAL=1 (depth-balanced grow). Seeds 0/1/2, two
# programmes. Factor/max_share sweep is the second half of erc.7, run separately.
set -u
cd "$(dirname "$0")/.."
BUDGET="${1:-20000}"
FAC="${2:-3}"
OUT=scratch/synergy_ab; mkdir -p "$OUT"
TSV=scratch/synergy_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tdepthbal\tshare\tfactor\tfails\ttopologies\telapsed_s\n' > "$TSV"

run() {  # programme seed depthbal(0|1)
  local prog="$1" seed="$2" bal="$3"
  local tag="sh1f${FAC}_db${bal}"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  echo ">>> $prog seed=$seed share=1 factor=$FAC depthbal=$bal"
  local t0; t0=$(date +%s)
  env URB_NO_OCCLUSION=1 LEAFSHARE=1 LEAFSHAREFAC="$FAC" DEPTHBAL="$bal" \
    python3 experiments/run_staged_search.py "examples/$prog" "$BUDGET" "$seed" \
      "examples/$prog/init.dom" "$OUT/${prog}_${tag}_s${seed}.dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fails topos
  fails=$(grep 're-scored (native)' "$log" | tail -1 | sed -n 's/.*(\([0-9]*\) fails).*/\1/p')
  topos=$(grep -m1 '^evals' "$log" | sed -n 's/.*across \([0-9]*\) topologies.*/\1/p')
  printf '%s\t%s\t%s\t1\t%s\t%s\t%s\t%s\n' "$prog" "$seed" "$bal" "$FAC" "${fails:-ERR}" "${topos:-?}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, ${topos:-?} topologies, $((t1-t0))s"
}

# share-alone control (reproduce §13.3) then the bal+share synergy arm, seeds 0/1/2
for prog in maple-court harbor-house; do
  for seed in 0 1 2; do run "$prog" "$seed" 0; done
  for seed in 0 1 2; do run "$prog" "$seed" 1; done
done

echo "=== leaf-sharing × depth-balancing synergy A/B complete ==="
column -t -s $'\t' "$TSV"
