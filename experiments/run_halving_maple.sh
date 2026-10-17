#!/bin/bash
# homemaker-py-2g7.13.1.9: does the catalogue pipeline generalise? Successive
# halving on MAPLE-COURT, the programme it was not developed against
# (DESIGN.md §39.148: 34-42 of its 60-67 cold fails are crinkliness, and the
# filter finds lit outlines at three storeys).
#
# Candidates: 48 catalogue seeds (experiments/results/halving-maple, the 16
# smallest filtered plans x 3 stair placements, built by
# seed_from_catalogue.py exactly as harbor-house's were) and THREE COLD
# candidates, the bare plot (init.dom) under three names -- so the halving
# itself carries a cold control, each with its own seed stream. Maple-court
# has no hand drawing and no footprint.
#
# One ranking, on TOTAL fails, 8 slots: on harbor-house the structural and
# total rankings converged on the same final two and the same winner
# (§39.151), and they share runs where they agree. 4k rising x2 to 128k,
# each stage continuing the previous one's design (252k for a finalist).
#
# It WAITS for queue 5 (run_ab_queue5.sh) to say "queue 5 complete" and for
# every search to exit. Do not edit src/ on main while either runs.
#
#   setsid nohup experiments/run_halving_maple.sh > ~/homemaker-halving-maple.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
FIRST=${FIRST_LOG:-$HOME/homemaker-ab-queue5.log}
P=examples/maple-court
R=experiments/results/halving-maple
say() { echo "=== $(date '+%F %T') $*"; }

say "waiting for $FIRST"
until grep -q 'queue 5 complete' "$FIRST" 2>/dev/null \
      && ! pgrep -f 'homemaker_layout.evolve|homemaker-evolve|flag_ab.py|run_coldstart_baseline|successive_halving' >/dev/null; do
    sleep 300
done
git pull -q --rebase || echo "(pull failed; working with what is here)"
ls $R/halv-*.dom >/dev/null 2>&1 || { echo "!!! no seeds in $R"; exit 1; }
for c in a b c; do cp -f $P/init.dom $R/cold-$c.dom; done
say "start, objective $(git log -1 --format=%h -- src/homemaker_layout/{cells,dom,dom_v2,fitness,geometry,graph,programme}.py)+orth, HEAD $(git rev-parse --short HEAD)"
python -u experiments/successive_halving.py --programme maple-court \
    --seeds $R/halv-*.dom $R/cold-a.dom $R/cold-b.dom $R/cold-c.dom \
    --start 4000 --final 128000 --eta 2 --slots 8 --rank total \
    --work "$HOME/halving-maple" --output "$R/winner.dom"
say "halving finished (rc=$?)"
cp -f "$HOME/halving-maple/stages.tsv" $R/stages.tsv
HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_halving_stairs.py "$HOME/halving-maple"
HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_halving_carry.py $R/winner.dom --programme maple-court
say "done"
