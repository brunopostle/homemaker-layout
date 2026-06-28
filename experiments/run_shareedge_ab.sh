#!/usr/bin/env bash
# Share-aware edge-too-long cap A/B (hph, DESIGN.md §13.7 follow-up). §13.7 named
# edge-too-long harbor's top fail class; diag_edge_too_long.py showed the bulk are
# a leaf-sharing REPRESENTATION ARTIFACT — a share=k leaf aggregates k same-code
# rooms, so its walls run ~k× the flat 8 m cap purely for being big. That is the
# same leak §13.3 closed for quality_size (k×target centring) on a different
# measure: edge_cost / outside_edge_cost still used a flat 8 m regardless of
# leaf.share. The fix scales the cap by the (type-guarded) share of the adjoining
# leaf/leaves, mirroring k×target; non-shared leaves keep the flat cap so genuine
# narrow/oversize pathologies stay flagged.
#
# Both arms hold the full Phase-8 default stack (leaf-share factor 3, depth-bal,
# interior-O odiv=3, circ_divisor 3, proportion-aware). Control is SHAREEDGE=0
# (flat cap) — must reproduce §13.6/§13.7 (maple 80.3, harbor 34.0); experiment
# adds SHAREEDGE=1 (share-aware cap). Seeds 0/1/2, two programmes, 20000 native
# evals, staged, final native re-score.
set -u
cd "$(dirname "$0")/.."
BUDGET="${1:-20000}"
OUT=scratch/shareedge_ab; mkdir -p "$OUT"
TSV=scratch/shareedge_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tshareedge\tfails\ttopologies\telapsed_s\n' > "$TSV"

run() {  # programme seed shareedge(0|1)
  local prog="$1" seed="$2" se="$3"
  local tag="se${se}"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  echo ">>> $prog seed=$seed shareedge=$se"
  local t0; t0=$(date +%s)
  env URB_NO_OCCLUSION=1 LEAFSHARE=1 LEAFSHAREFAC=3 DEPTHBAL=1 \
    INTERIORO=1 ODIV=3 SHAREEDGE="$se" \
    python3 experiments/run_staged_search.py "examples/$prog" "$BUDGET" "$seed" \
      "examples/$prog/init.dom" "$OUT/${prog}_${tag}_s${seed}.dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fails topos
  fails=$(grep 're-scored (native)' "$log" | tail -1 | sed -n 's/.*(\([0-9]*\) fails).*/\1/p')
  topos=$(grep -m1 '^evals' "$log" | sed -n 's/.*across \([0-9]*\) topologies.*/\1/p')
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$prog" "$seed" "$se" "${fails:-ERR}" "${topos:-?}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, ${topos:-?} topologies, $((t1-t0))s"
}

# flat-cap control (reproduce §13.6/§13.7) then the share-aware arm, seeds 0/1/2
for prog in maple-court harbor-house; do
  for seed in 0 1 2; do run "$prog" "$seed" 0; done
  for seed in 0 1 2; do run "$prog" "$seed" 1; done
done

echo "=== share-aware edge cap A/B complete ==="
column -t -s $'\t' "$TSV"
