# homemaker-layout

Programme-driven building-layout search over slicing trees. A clean-room Python
successor to the Perl [Urb](../urb) project, intended to eventually be 100% Python.

## Why a rewrite

Urb represents a building as a binary slicing tree where room sizes are derived
**top-down** from division ratios. That makes room area an emergent property of
every cut above it, which:

- gives the genome low locality (a cut near the root rescales every descendant),
- makes target room sizes nearly impossible to hit, so the gaussian size penalty
  dominates fitness, and
- defeats crossover (transplanted subtrees lose their proportions).

homemaker inverts this: leaves carry **target dimensions** from the programme and
division ratios are **solved bottom-up** for a fixed topology. The evolutionary
search then only explores topology + types + adjacency.

## Phase plan

1. ~~Solver experiment: port Urb's geometry, re-solve ratios from programme
   targets, score the result against the original via the Perl oracle.~~ ✓
2. ~~Native Python fitness (retire the Perl oracle).~~ ✓
3. ~~Memetic search: canonical slicing genome + high-locality operators +
   Nelder-Mead inner loop.~~ ✓
4. ~~Penalty reshaping: lexicographic `(-n_fails, fitness)` outer-search
   comparison.~~ ✓
5. ~~Representation upgrade: canonical slicing encoding + bottom-up shape
   feasibility, scaled to larger programmes.~~ ✓
6. **Search-quality experiments** (current): a long running series of
   opt-in levers tried against the `harbor-house`, `health-centre`, and
   `programme-house` example corpora — leaf-sharing, finish-time cell→room
   collapse, ruin-and-recreate LNS, 2-opt polish, multi-use/co-located
   leaves, adjacency-graph and bubble-diagram fitness signals, and more.
   Most of these are negative/null results kept as opt-in flags or reference
   code rather than defaults. See `DESIGN.md` §11 onward for the full,
   numbered experiment log with methodology and results for each.

## Layout

- `src/homemaker_layout/dom.py` — read/write Urb `.dom` YAML into a `Node` tree.
- `src/homemaker_layout/geometry.py` — faithful port of Urb's top-down geometry.
- `src/homemaker_layout/programme.py` — parse `patterns.config` space requirements.
- `src/homemaker_layout/solver.py` — bottom-up ratio solve (scipy).
- `src/homemaker_layout/fitness.py` — native Python fitness evaluator.
- `src/homemaker_layout/fitness_cmd.py` — `homemaker-fitness` CLI (drop-in for `urb-fitness.pl`).
- `src/homemaker_layout/collapse_cmd.py` — `homemaker-collapse` CLI: finish-time global cell→room relabel of a `.dom`.
- `src/homemaker_layout/graph.py` — leaf-adjacency graph for programme-driven checks.
- `src/homemaker_layout/genome.py` — topology genome: base-floor tree + per-storey deltas.
- `src/homemaker_layout/operators.py` — high-locality mutation and subtree crossover.
- `src/homemaker_layout/innerloop.py` — ratio optimisation inner loop (Nelder-Mead / CMA-ES).
- `src/homemaker_layout/driver.py` — memetic search outer loop.
- `src/homemaker_layout/evolve.py` — `homemaker-evolve` CLI entry point.
- `src/homemaker_layout/oracle.py` — legacy Perl shim, kept for cross-validation only.
- `src/homemaker_layout/bubble.py` — 3D bubble-diagram adjacency fitness-signal
  prototype (DESIGN.md §27); validated null, not wired into `fitness.py` —
  reference only.
