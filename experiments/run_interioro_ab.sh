#!/usr/bin/env bash
# Interior-O courtyard / light-well seeding A/B (ld2, DESIGN.md §13.6). The erc
# crinkliness residual is dominated by LANDLOCKED rooms (seed probe: every
# crinkliness fail is under-exposed crink<0.62, none over-exposed) — rooms with
# no plot facade and no uncovered-O neighbour, so area_outside ~ 0. The current
# adjacency-aware seeder places ONE O on the most PERIPHERAL leaf, where adjacent
# rooms already have facade, wasting it. This arm instead seeds O as INTERIOR
# light wells (most-landlocked leaves first) and scales their count with the room
# count (outside_divisor=3). Seed probe (bal+share stack): harbor 147->129,
# maple 219->206 total fails at odiv=3 — but the lever ADDS leaves (harbor +4,
# maple +8), so the §13.4 risk is the seed advantage washing out under search.
# This A/B answers whether it survives to convergence.
#
# Both arms hold the current default stack LEAFSHARE=1 (factor 3) + DEPTHBAL=1
# (the §13.5 winner). The control arm is interior-OFF (peripheral O) — must
# reproduce §13.5 bal+share (maple 82.3, harbor 40.0); the experiment arm adds
# INTERIORO=1 (odiv=3). Seeds 0/1/2, two programmes, 20000 native evals, staged.
set -u
cd "$(dirname "$0")/.."
BUDGET="${1:-20000}"
ODIV="${2:-3}"
OUT=scratch/interioro_ab; mkdir -p "$OUT"
TSV=scratch/interioro_results.tsv
[ -f "$TSV" ] || printf 'programme\tseed\tinterior\todiv\tfails\ttopologies\telapsed_s\n' > "$TSV"

run() {  # programme seed interior(0|1)
  local prog="$1" seed="$2" interior="$3"
  local tag="io${interior}_od${ODIV}"
  local log="$OUT/${prog}_${tag}_s${seed}.log"
  echo ">>> $prog seed=$seed interior=$interior odiv=$ODIV"
  local t0; t0=$(date +%s)
  env URB_NO_OCCLUSION=1 LEAFSHARE=1 LEAFSHAREFAC=3 DEPTHBAL=1 \
    INTERIORO="$interior" ODIV="$ODIV" \
    python3 experiments/run_staged_search.py "examples/$prog" "$BUDGET" "$seed" \
      "examples/$prog/init.dom" "$OUT/${prog}_${tag}_s${seed}.dom" > "$log" 2>&1
  local t1; t1=$(date +%s)
  local fails topos
  fails=$(grep 're-scored (native)' "$log" | tail -1 | sed -n 's/.*(\([0-9]*\) fails).*/\1/p')
  topos=$(grep -m1 '^evals' "$log" | sed -n 's/.*across \([0-9]*\) topologies.*/\1/p')
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$prog" "$seed" "$interior" "$ODIV" "${fails:-ERR}" "${topos:-?}" "$((t1-t0))" >> "$TSV"
  echo "    -> ${fails:-ERR} fails, ${topos:-?} topologies, $((t1-t0))s"
}

# peripheral-O control (reproduce §13.5) then the interior-O arm, seeds 0/1/2
for prog in maple-court harbor-house; do
  for seed in 0 1 2; do run "$prog" "$seed" 0; done
  for seed in 0 1 2; do run "$prog" "$seed" 1; done
done

echo "=== interior-O seeding A/B complete ==="
column -t -s $'\t' "$TSV"
