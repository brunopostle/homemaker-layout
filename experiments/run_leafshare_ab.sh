#!/usr/bin/env bash
# Leaf-sharing A/B (erc.3, DESIGN.md §13.3): does collapsing same-code rooms into
# fewer, larger SHARED leaves lower the end-to-end fail count, given the floor
# probe showed −32…−39 % on the achievable seed floor with zero missing-fail leak
# (explicit, type-guarded per-leaf multiplicity)?
#
# Baseline arm (LEAFSHARE=0) must reproduce the §12.2 figures (maple 136.0,
# harbor 74.0); the share arm (LEAFSHARE=1, factor 3) is the experiment. One
# programme dir per programme — run_staged_search.py injects the leaf_sharing
# objective into the whole pipeline so both arms share patterns.config.
set -u
cd "$(dirname "$0")/.."
BUDGET="${1:-20000}"
FAC="${2:-3}"
OUT=scratch/leafshare_ab; mkdir -p "$OUT"
TSV=scratch/leafshare_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tshare\tfactor\tfails\ttopologies\telapsed_s\n' > "$TSV"

run() {  # programme seed share(0|1)
  local prog="$1" seed="$2" share="$3"
  local tag="ls${share}"; [ "$share" = 1 ] && tag="ls1f${FAC}"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  echo ">>> $prog seed=$seed leafshare=$share factor=$FAC"
  local t0; t0=$(date +%s)
  env URB_NO_OCCLUSION=1 LEAFSHARE="$share" LEAFSHAREFAC="$FAC" \
    python3 experiments/run_staged_search.py "examples/$prog" "$BUDGET" "$seed" \
      "examples/$prog/init.dom" "$OUT/${prog}_${tag}_s${seed}.dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fails topos
  fails=$(grep 're-scored (native)' "$log" | tail -1 | sed -n 's/.*(\([0-9]*\) fails).*/\1/p')
  topos=$(grep -m1 '^evals' "$log" | sed -n 's/.*across \([0-9]*\) topologies.*/\1/p')
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$prog" "$seed" "$share" "$FAC" "${fails:-ERR}" "${topos:-?}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, ${topos:-?} topologies, $((t1-t0))s"
}

# baseline controls (reproduce §12.2) then the leaf-sharing arm, both seeds 0/1/2
for prog in maple-court harbor-house; do
  for seed in 0 1 2; do run "$prog" "$seed" 0; done
  for seed in 0 1 2; do run "$prog" "$seed" 1; done
done

echo "=== leaf-sharing A/B complete ==="
column -t -s $'\t' "$TSV"
