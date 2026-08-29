#!/usr/bin/env bash
# Re-run the 1ph protocol (DESIGN.md §20): programme-house init.dom, budget 3000,
# 4 workers, ON vs OFF, BOTH arms finished with --collapse.
# Usage: rerun_1ph_protocol.sh <worktree> <tag> <out.tsv> [lo] [hi]
#   env: PROG (default programme-house), BUDGET (3000), WORKERS (4), APPEND=1
set -u
W="$1"; TAG="$2"; OUT="$3"; LO="${4:-1}"; HI="${5:-20}"
PROG="${PROG:-programme-house}"; BUDGET="${BUDGET:-3000}"; WORKERS="${WORKERS:-4}"
cd "$W/examples/$PROG"
[ "${APPEND:-0}" = "1" ] || : > "$OUT"
for seed in $(seq "$LO" "$HI"); do
  for arm in on off; do
    flag=""; [ "$arm" = "off" ] && flag="--no-collapse-insearch"
    t0=$(date +%s)
    PYTHONPATH="$W/src" timeout 600 python -m homemaker_layout.evolve init.dom \
      --budget "$BUDGET" --seed "$seed" --workers "$WORKERS" --collapse $flag \
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
