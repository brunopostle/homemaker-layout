#!/usr/bin/env bash
# Re-run the 1ph protocol (DESIGN.md §20): programme-house init.dom, budget 3000,
# 4 workers, seeds 1-20, ON vs OFF, BOTH arms finished with --collapse.
set -u
W="$1"; TAG="$2"; OUT="$3"
cd "$W/examples/programme-house"
: > "$OUT"
for seed in $(seq 1 20); do
  for arm in on off; do
    flag=""; [ "$arm" = "off" ] && flag="--no-collapse-insearch"
    t0=$(date +%s)
    PYTHONPATH="$W/src" timeout 600 python -m homemaker_layout.evolve init.dom \
      --budget 3000 --seed "$seed" --workers 4 --collapse $flag \
      --output "$OUT.$arm.dom" > "$OUT.$arm.log" 2>&1
    t1=$(date +%s)
    n=$(PYTHONPATH="$W/src" python - "$OUT.$arm.dom" <<'PY'
import copy, sys
from homemaker_layout import dom, fitness
conf, cost = fitness.load_config(".")
_, f = fitness.Fitness(conf, cost).score_with_fails(copy.deepcopy(dom.load(sys.argv[1])))
print(len(f))
PY
)
    echo -e "$TAG\t$seed\t$arm\t$n\t$((t1-t0))" >> "$OUT"
  done
done
