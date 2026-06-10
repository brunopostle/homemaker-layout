# homemaker-py

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

1. **Solver experiment** (current): port Urb's geometry, re-solve ratios from
   programme targets, score the result against the original via the Perl oracle.
2. Native Python fitness (retire the Perl oracle).
3. Canonical slicing encoding (normalized Polish expression) + memetic search.

## Layout

- `src/homemaker/dom.py` — read/write Urb `.dom` YAML into a `Node` tree.
- `src/homemaker/geometry.py` — faithful port of Urb's top-down geometry.
- `src/homemaker/programme.py` — parse `patterns.config` space requirements.
- `src/homemaker/solver.py` — bottom-up ratio solve (scipy).
- `src/homemaker/oracle.py` — Phase-1 scaffold: score a `.dom` via Urb's `urb-fitness.pl`.

The Perl oracle is the only throwaway component; everything else is permanent.
