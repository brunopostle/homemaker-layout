#!/usr/bin/env bash
# 6zy joint A/B: topology diversity (structural niching) x selection pressure
# (tournament size k). §11.5 raised diversity to 16/16 but held pressure FIXED at
# k=2; this sweep co-tunes them to test whether sharper selection converts the
# extra structural diversity into lower fails rather than diffusing it.
#
# Grid: NICHE in {0,1} x HOMEMAKER_TOURNAMENT_K in {2,3,4}.
#   (niche=0,k=2) is the legacy baseline; (niche=1,k=2) reproduces §11.5's niche
#   column; the k in {3,4} rows are the new higher-pressure cells.
# Seeds: programme-house 0..4 (>=5, widened from §11.5's thin 3 to clear seed
#   noise); harbor-house staged seed 0.
# Equal native-fitness budget, URB_NO_OCCLUSION=1. Results -> scratch/6zy/summary.tsv
set -u
cd "$(dirname "$0")/.."
OUT=scratch/6zy
mkdir -p "$OUT"
SUMMARY="$OUT/summary.tsv"
# RESUME=1 keeps an existing summary and skips cells already recorded (non-ERR),
# so a killed sweep can finish only its missing cells. Default starts fresh.
if [ "${RESUME:-0}" = 1 ] && [ -s "$SUMMARY" ]; then
  echo "RESUME: keeping $(($(wc -l < "$SUMMARY") - 1)) existing rows"
else
  : > "$SUMMARY"
  printf 'prog\tniche\tk\tseed\tfails\tseen\tpop_distinct\trestarts\ttag\n' >> "$SUMMARY"
fi
BUDGET=${BUDGET:-20000}
PH_SEEDS=${PH_SEEDS:-"0 1 2 3 4"}
HARBOR_SEEDS=${HARBOR_SEEDS:-"0"}
MAXJOBS=${MAXJOBS:-2}
# §11.5 reproduce-commands seed programme-house from init.dom (a bare undivided
# plot) so the run is a true BLANK-SLATE topology search; c964…dom is a finished
# design that would warm-start and floor trivially. Must match §11.5 for the
# direct comparison the acceptance criteria require.
PH_SEED_FILE=examples/programme-house/init.dom

run_one() {
  local prog=$1 harness=$2 niche=$3 k=$4 seed=$5 seedfile=$6
  local tag="${prog}_n${niche}_k${k}_s${seed}"
  local log="$OUT/${tag}.log"
  if [ "${RESUME:-0}" = 1 ] && grep -qP "\t${tag}\$" "$SUMMARY" 2>/dev/null \
      && ! grep -qP "\tERR\t.*\t${tag}\$" "$SUMMARY" 2>/dev/null; then
    echo "SKIP $tag (already recorded)"
    return
  fi
  URB_NO_OCCLUSION=1 NICHE=$niche HOMEMAKER_TOURNAMENT_K=$k \
    python3 "experiments/$harness" \
    "examples/$prog" "$BUDGET" "$seed" "$seedfile" \
    "$OUT/${tag}.dom" > "$log" 2>&1
  local fails seen popd restarts
  fails=$(grep -oE 'best *: [0-9.eE+-]+ \([0-9]+ fails\)' "$log" | grep -oE '[0-9]+ fails' | grep -oE '[0-9]+' | tail -1)
  seen=$(grep -oE 'diversity : [0-9]+ distinct topologies seen' "$log" | grep -oE '[0-9]+' | tail -1)
  popd=$(grep -oE '[0-9]+/[0-9]+ distinct in final population' "$log" | head -1 | grep -oE '^[0-9]+')
  restarts=$(grep -oE '[0-9]+ restarts' "$log" | grep -oE '[0-9]+' | tail -1)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$prog" "$niche" "$k" "$seed" "${fails:-ERR}" "${seen:-?}" "${popd:-?}" "${restarts:-?}" "$tag" >> "$SUMMARY"
  echo "DONE $tag -> ${fails:-ERR} fails (seen=${seen:-?}, popd=${popd:-?})"
}

JOBS=()
for niche in 0 1; do
  for k in 2 3 4; do
    for seed in $PH_SEEDS; do
      JOBS+=("programme-house|run_search_scaled.py|$niche|$k|$seed|$PH_SEED_FILE")
    done
    for seed in $HARBOR_SEEDS; do
      JOBS+=("harbor-house|run_staged_search.py|$niche|$k|$seed|examples/harbor-house/init.dom")
    done
  done
done

echo "queued ${#JOBS[@]} jobs, budget=$BUDGET, maxjobs=$MAXJOBS"
for job in "${JOBS[@]}"; do
  IFS='|' read -r prog harness niche k seed seedfile <<< "$job"
  while [ "$(jobs -rp | wc -l)" -ge "$MAXJOBS" ]; do wait -n; done
  run_one "$prog" "$harness" "$niche" "$k" "$seed" "$seedfile" &
done
wait
echo "ALL DONE"
# keep header first, sort the rest
{ head -1 "$SUMMARY"; tail -n +2 "$SUMMARY" | sort; } > "$SUMMARY.tmp" && mv "$SUMMARY.tmp" "$SUMMARY"
cat "$SUMMARY"
