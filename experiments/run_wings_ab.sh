#!/bin/bash
# homemaker-py-2g7.13.1, DESIGN.md §39.144: harbor-house warm-started from
#   footprint-sK.dom  -- the owner's drawing's O/E cells, wings refilled (§39.144 step 0)
#   wings-(K+1).dom   -- the best three catalogue seeds (seed_from_catalogue.py)
# at 500k, --seed K for K = 0,1,2, exactly as queue 4 ran hand2a.dom
# (run_ab_queue4.sh step 4). The comparison is §39.142's runs at the same
# stamp, budget and seeds: cold coldstart-4428262+orth-500000-sK (28/24/37)
# and handseed-4428262+orth-500000-sK (10/12/5).
#
# EXPECTED, written before the runs: both new arms end with crinkliness at or
# under 4 fails (cold ends at 11-15, hand-seeded at 1-4), and total fails
# between the hand-seeded and the cold runs.
#
# Waits for the labels A/B to stop (~/homemaker-labels-stop.log says "driver
# stopped") and for the seeder to finish; runs the footprint arm alone if the
# seeder wrote no seeds. Start detached:
#   setsid nohup experiments/run_wings_ab.sh > ~/homemaker-wings-ab.log 2>&1 < /dev/null &
cd "$(dirname "$0")/.." || exit 1
REPO=$PWD
say() { echo "$(date '+%F %T') $*"; }
export HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

say "waiting for the labels A/B to stop and the seeder to finish"
until grep -q "driver stopped" "$HOME/homemaker-labels-stop.log" 2>/dev/null; do sleep 120; done
while pgrep -f "seed_from_catalogue.py" >/dev/null; do sleep 120; done
git pull -q --rebase

STAMP=$(python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit())")
say "objective $STAMP"
if [ "$STAMP" != "4428262+orth" ]; then
    echo "!!! the objective moved from 4428262+orth: the cold and hand-seeded runs are no comparison; stopping"
    exit 1
fi

W=/tmp/wings_ab; rm -rf "$W"; mkdir -p "$W"
runs=()
for k in 0 1 2; do
    runs+=("footprint:footprint-s$k.dom:$k")
    [ -s "examples/harbor-house/wings-$((k + 1)).dom" ] && runs+=("wings:wings-$((k + 1)).dom:$k")
done
say "${#runs[@]} runs: ${runs[*]}"
for r in "${runs[@]}"; do
    IFS=: read -r arm seedfile k <<< "$r"
    d=$W/$arm-s$k; mkdir -p "$d"
    cp -f "examples/harbor-house/$seedfile" examples/harbor-house/patterns.config "$d"/
    cp -f examples/harbor-house/costs.config "$d"/ 2>/dev/null
    (cd "$d" && python -m homemaker_layout.evolve "$seedfile" \
        --budget 500000 --seed "$k" --workers 1 --output out.dom > log.txt 2>&1) &
done
wait
say "all runs finished"
for r in "${runs[@]}"; do
    IFS=: read -r arm seedfile k <<< "$r"
    d=$W/$arm-s$k
    name="examples/harbor-house/${arm}seed-$STAMP-500000-s$k"
    if [ -s "$d/out.dom" ]; then
        cp -f "$d/out.dom" "$name.dom"; cp -f "$d/log.txt" "$name.log"
        git add "$name.dom" "$name.log" "examples/harbor-house/$seedfile"
        (cd examples/harbor-house && homemaker-fitness "$(basename "$name.dom")" 2>&1 | tail -1 \
            | sed "s|^|$arm s$k score |"; grep -c . "$(basename "$name.dom").fails" | sed "s|^|$arm s$k fails |")
        rm -f "$name.dom.score" "$name.dom.fails"
    else
        echo "!!! $arm s$k wrote no design (see $d/log.txt)"
    fi
done
git diff --cached --quiet || { git commit -q -m "Wings A/B on harbor-house at $STAMP: footprint- and catalogue-seeded, 500k, seeds 0-2 (homemaker-py-2g7.13.1)" \
    -m "The comparison is the cold and hand-seeded runs at the same stamp, budget and seeds (DESIGN.md §39.142)."; git pull -q --rebase; git push -q; }
say "done"
