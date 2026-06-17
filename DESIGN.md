# homemaker — Design & Plan

**Status:** validated direction, pre-implementation. Reviewed against the Urb
source 2026-06-12; review findings folded in (see §4.5 evidence note, §4.6
throughput arithmetic, §5 decision 6, §6 port-scope expansion, §7 re-scoped
phases, §8).
**Audience:** a fresh session that will break this into `bd` (beads) tasks
(note: no beads database exists yet — run `bd init` first). Self-contained —
assumes no memory of the originating conversation.

---

## 1. Purpose

`homemaker-layout` is a clean-room Python successor to the Perl **Urb** project
(`/home/bruno/src/urb`). Urb models a building as a binary **slicing tree** and
evolves layouts with mutation + crossover, scored against Christopher
Alexander–style pattern fitness. Two long-standing problems motivate the
rewrite:

1. **It doesn't scale** — beyond a few rooms, evolution never finds layouts an
   architect would consider obvious.
2. **Local minima** — even small programmes converge to poor optima.

The eventual goal is a **100% Python** system. During bring-up, Perl Urb is kept
as a throwaway **fitness oracle** behind the `.dom` file format.

---

## 2. Constraints that fix the representation

These come from the problem domain and are **not negotiable**; importantly, they
*vindicate* the slicing tree rather than argue against it:

- **Multi-storey with stacked walls.** An upper storey retains the storey below,
  except additional divisions/undivisions. Load-bearing walls must stack ⇒ every
  cut is a full edge-to-edge **guillotine** cut. Urb already enforces this via
  `Below`-inheritance (an upper quad reads its geometry from the matching quad
  below).
- **Quadrilateral rooms only** (no L/Z shapes) — recursive bisection produces
  exactly this.
- **No pinwheel / non-slicing layouts** — undesirable for load-bearing
  construction and adaptability (cf. Brand, *How Buildings Learn*). This is the
  one class a slicing tree *can't* express, and we don't want it anyway.
- **Plots are near-rectangular but general convex quadrilaterals** (not
  axis-aligned). Geometry must handle skew; the slicing *combinatorics* are
  unaffected.

**Conclusion:** the slicing tree is the correct phenotype. The rewrite is about
the *genotype*, the *search*, and the *fitness shape* — not about leaving the
slicing class.

---

## 3. What we built this session (all committed)

Package `src/homemaker_layout/`:

- **`dom.py`** — `.dom` YAML ⇄ `Node` tree. Linkage (`parent`/`below`/`position`),
  `wall_outer` inset on load with raw-corner stash for byte-perfect round-trip,
  emit.
- **`geometry.py`** — faithful port of Urb's top-down geometry
  (`Coordinate`/`Coordinate_a`/`_b`/`Area`/`Length`) + `Coordinate_Offset` wall
  inset. **Memoised** (uncached recursion is exponential in depth).
- **`programme.py`** — parse `patterns.config` `spaces:` into per-code
  size/width/proportion/adjacency/level/count requirements.
- **`solver.py`** — bottom-up division-ratio solver (scipy `least_squares`).
  *(Outcome: falsified as a standalone component — see §4.2.)*
- **`oracle.py`** — Phase-1 fitness bridge: write `.dom`, run `urb-fitness.pl`,
  parse `.score` + `.fails`.

Experiments in `experiments/`:
`dump_areas.{py,pl}`, `resolve_ratios.py`, `refine_sweep.py`,
`sweep_failtypes.py`, `optimize_fullfitness.py`.

---

## 4. Empirical findings (the core of this document)

### 4.1 Geometry port — VALIDATED
Per-leaf areas computed in Python are **byte-identical to Urb across all 35
programme-house `.dom` files**, including the wall inset and multi-storey
wall-stacking inheritance. (`experiments/dump_areas.{py,pl}`.) The infrastructure
is trustworthy.

### 4.2 Bottom-up area-proxy sizing solver — FALSIFIED
The original hypothesis: give leaves *target sizes*, solve cut ratios bottom-up,
let the EA search only topology. Tested by re-solving an evolved candidate's
ratios from programme targets and scoring via the oracle.

- `resolve_ratios.py` on candidate-002: areas recovered accurately (errors
  collapsed, e.g. t1/t2/t3 from +1.4/+2.4/+4.8 → ~+0.05), and it *fixed* the
  original's `size` failure — **but total fitness dropped** (0.00737 → 0.00065,
  4 fails) because it introduced shape/relational failures.
- `refine_sweep.py` (warm-start refine of all 34 candidates):
  **0/34 improved.** Total failures 124 → 297 (equal-offset cuts) and 124 → 626
  (independent-offset cuts).
- `sweep_failtypes.py` (failure-type histogram, equal-offset):

  | type | area-dominant Δ | shape-aware Δ |
  |---|---|---|
  | width | +82 | +29 |
  | proportion | +35 | +7 |
  | crinkliness | +18 | +4 |
  | adjacency | +18 | +13 |
  | size | **−15** | **+15** |
  | access | +29 | +39 |
  | **total added** | +173 | +110 |

**Why it fails:** in Urb's fitness, every cut position is simultaneously a *size*
knob **and** an *adjacency/access/shape* knob. A solver that optimises only
size/shape is blind to access/adjacency and trades them away. Refining a
co-evolved local optimum with a *partial* objective is **structurally unable to
win**, and the `0.5^n` failure penalty makes every new failure catastrophic while
fixes are only linear. The proxy solver is strictly worse than optimising real
fitness. **Do not pursue it.**

### 4.3 "Perpendicular" failures were an artifact — RESOLVED
Letting the two ends of a cut float independently produced skewed cuts and many
`perpendicular` failures. Tying the two ends (**equal offset, `a == b`**, one DOF
per cut) produces near-perpendicular walls on these near-rectangular plots and
yields **zero** `perpendicular` failures. **Equal-offset cuts are the only mode
to use.** This also halves the variable count and matches the slicing model.

### 4.4 DOF / over-determination — partially real, not fatal
A topology with *R* rooms has ~*R−1* cut DOF but ~2–3 size/shape constraints per
room, so a *fixed* topology can be over-determined: you cannot always hit
area + width + proportion for every room at once (heavy shape weighting traded
straight into `size`, §4.2 table). This limits any single-objective sizing pass —
but it is **not** fatal, because optimising the *full* objective still found
large gains (§4.5). The earlier "infeasibility" worry was overstated.

### 4.5 Full-fitness frozen-topology optimisation — VALIDATED ✅
Drive the equal-offset ratios with Nelder-Mead against the **real oracle fitness**
(whole objective, no proxy), topology frozen
(`experiments/optimize_fullfitness.py`):

| candidate | DOF | original | optimised | gain | fails |
|---|---|---|---|---|---|
| 2f45907 (best evolved) | 7 | 0.012617 | 0.015684 | ×1.24 | 2→2 |
| candidate-002 (MCP-refined) | 6 | 0.007375 | 0.012319 | ×1.67 | 2→2 |
| c964435 (MCP baseline) | 6 | 0.003667 | 0.005836 | ×1.59 | 3→3 |

**Every design improved 24–67%, none added a failure.** Headroom *widens* on
weaker designs. Because the optimiser sees the whole objective (including the
`0.5^n` penalty), it never trades into a new failure — **the cliff that destroys
the proxy solver protects the full-objective optimiser.**

**Implications:**
- There is large, unclaimed **geometry headroom above every EA design** — even
  the best. Urb's EA under-optimises geometry: source inspection confirms
  `slide()` (Mutate.pm:256-269) *re-randomises* the cut position uniformly
  across the span — Urb has **no fine-tuning geometry operator at all**, which
  fully explains the headroom.
- A **full-objective geometry inner loop is genuinely valuable** (the proxy
  solver is not).
- The EA/search should therefore own **topology**; geometry is delegated to the
  inner loop. This is the memetic architecture (§5).
- Corroboration for §4.3: Urb's own mutations use equal offsets
  (`Divide($division, $division)`) — equal-offset cuts match how every corpus
  design was generated.

### 4.6 Oracle throughput (measured)
`urb-fitness.pl` scores **many `.dom` files per invocation**, so the Perl startup
(~0.65 s) amortises across a batch and cached fields (e.g. occlusion) persist.
Measured on the 35-file corpus: **0.99 s/dom batched** vs **1.65 s/dom** for a
single-file call. The cost is **assessment-dominated** (~1 s/dom of actual work),
so startup amortisation gives ~40% — useful but bounded.

Consequences:
- **Batching only helps when evaluations are submitted together** — favour
  **population/parallel-evaluating optimisers** (CMA-ES, differential evolution,
  island EA, pattern search) over inherently sequential ones (Nelder-Mead), both
  inner loop and outer search, so a whole generation scores in one oracle call.
- **Do the arithmetic before scoping topology search on the oracle.** §4.5 used
  ~200 inner evaluations per topology ⇒ ~3 min/topology at 1 s/dom. A run
  comparable to `urb-evolve` (pop 128 × 768 generations) is *years* of oracle
  time; even 32 topologies × 100 generations with a trimmed 50-eval inner loop
  is ~2 days. Therefore:
  - The oracle supports **Phase 1 fully** and **Phase 2 only as a small-scale
    proof** (tens of topologies, budgets counted in oracle calls).
  - A **native Python fitness is effectively a gate for topology search at any
    real scale** — not merely a later optimisation. (It also brings
    independence, penalty reshaping, and large programmes.)
  - **Warm-starting the inner loop from the parent's optimised ratios**
    (Lamarckian inheritance, §5 decision 6) is the main lever for cutting the
    per-topology cost — with high-locality moves most cuts survive a mutation,
    so an order-of-magnitude reduction is plausible. Measure this in Phase 1.

### 4.7 Occlusion-disabled re-baseline (measured 2026-06-12)

With the §6 descope in place (`URB_NO_OCCLUSION=1` patch in Urb), the corpus
re-baseline (`experiments/rebaseline_no_occlusion.py`): all 35 scores change
(mostly up, ×1.0–×1.24 — daylight terms pin to 1), exactly one failure-set
change (458aa8b8 gains two `crinkliness` fails — expected mechanism: no
shading discount on external wall area), batched oracle ~8% faster
(0.92 s/dom). New inner-loop reference gains (deterministic seed, budget 400,
`accept_innerloop.py` bars): 2f45907 0.01304→0.02128 (×1.63), candidate-002
0.00808→0.01373 (×1.70), c964435 0.00400→0.00674 (×1.68, fails 3→2); ~35
oracle calls per topology. All Phase-2+ work uses the flag; flag-off numbers
above are historical.

### 4.8 The `0.5^n` failure penalty is a first-order pathology
Multiplicative `0.5^n` over failure *count* (a) makes the landscape a cliff (no
gradient across the huge zero-feasibility region), (b) rewards fewer *flags* over
better *geometry* (the original outscored better-sized solved designs purely on
flag count), and (c) is representation-independent. Reshaping it
(additive / soft / multi-objective Pareto) is a high-leverage change that helps
Urb today and homemaker tomorrow.

### 4.9 Penalty reshaping decision: lexicographic outer search (measured 2026-06-14)



`experiments/penalty_reshape.py`, `URB_NO_OCCLUSION=1`, programme-house.

**Inner-loop protection** (nm_search, budget 80, 3 files × 3 seeds = 9 runs):
All runs show `n_fails ≤ x0_n_fails`. **0/9 regressions.** The `0.5^n` cliff
in the native fitness scalar is unchanged and continues to protect the inner
loop.

**Outer-search comparison** (budget 3000, 3 seeds, seed = 2f45907):

| scheme | seed | best | fails | note |
|--------|------|------|-------|------|
| lex    |  0   | 0.01781 | 2 | |
| lex    |  1   | 0.01793 | 2 | |
| lex    |  2   | 0.01785 | 2 | |
| scalar |  0   | 0.01781 | 2 | (same outcome) |
| scalar |  1   | **0.01890** | **3** | trapped by high-score 3-fail design |
| scalar |  2   | 0.02632 | 2 | (different topology path) |

`lex` mean: 0.01786 / 2.00 fails. `scalar` mean: 0.02101 / 2.33 fails.

Key result (seed 1): scalar promoted a 3-fail design whose raw score (×0.125
penalty) beat the pool's 2-fail candidates — exactly the §4.8 pathology.
Lexicographic comparison (`-n_fails` first, then `fitness`) is immune: any
2-fail design beats any 3-fail design regardless of raw score. Within a
homogeneous fail tier both schemes are identical (seeds 0 and 2 agree in
serendipitous runs where scalar also stays in the 2-fail tier).

**Decision: lexicographic. `0.5^n` stays in the fitness scalar (inner loop
unchanged). Outer search uses `(-n_fails, fitness)` as comparison key.**

### 4.10 Deceptive level-fix valley and compound operators (measured 2026-06-14/15)

**Context:** programme-house, Phase 3 native fitness + Phase 4 lex search, seed
`warmstart-2f4.dom` (best Phase-3 result, 2 fails at score 0.032). Goal: reach
≤ 1 fail, beating the Perl optimiser (2–3 fails).

**The deceptive valley.** The 2-fail state has l1 (living room, min 27 m²,
required level 0) on level 1. The obvious repair is `level_fix`: swap l1 with a
leaf on level 0. But every single-step `level_fix` move creates 5+ new fails
because the displaced room (t3, the WC) is dropped into an arbitrary slot that
violates adjacency, size, and access constraints simultaneously. The lex
comparator (`-n_fails, fitness`) correctly rejects these — but the result is that
the 2-fail state appears completely surrounded by ≥ 5-fail states, and the search
stalls. This is a textbook deceptive valley: the fitness gradient points away from
the global optimum.

**Compound operator.** `mutate_level_compound_fix` (added `operators.py`) escapes
the valley by doing two things atomically:

1. Move l1 to level 0 by swapping it with the *largest* leaf there (the
   circulation C node, because C is generic and can absorb the swap without
   producing a new structural failure).
2. Re-insert the displaced t3 by dividing the sibling of that C node (so t3
   lands adjacent to C, satisfying the adjacency requirement).

The new split gets `division=[0.25,0.25]` (giving t3 ≈ 3.4 m², barely in range)
and `rotation=0` (t3 on the left, adjacent to the C sibling).

**The `warm_x0` initialization bug.** The compound operator sets specific ratios
on a newly-created split node. But `driver.py` was initialising the NM inner loop
from `parent.ratios`, which has no entry for the new node (it was a leaf).
`warm_x0` defaulted the new node to 0.5, giving t3 ≈ 6.8 m² — a size fail —
so NM started at 3 fails instead of 1. Lex then always rejected the compound
child; `level_compound_fix` was completely invisible to the outer search for
~12 000 evals (until `warm_x0` was fixed).

The correct fix distinguishes genuinely-new split nodes from stale hidden nodes
that become visible after structural mutations (e.g. `swap` can flip a `b.below`
pointer, revealing pre-writeback division values from a different topology). Only
use the child's explicit ratio for node `(li, path)` if the matching node in the
parent was *not already divided*; everything else falls through to `parent.ratios`
or defaults to 0.5. Fix in `driver.py` lines 259–267.

**Results (50 000 evals each, pop 8, child_budget 80, 4 workers):**

| seed | event | eval | fails | score |
|------|-------|------|-------|-------|
| warmstart-2f4 | seed | 200 | 2 | 0.032 |
| warmstart-2f4 | `level_compound_fix` fires | 12 280 | 1 | 0.000122 |
| warmstart-2f4 | `level_retype 0/ll<->1/l` | 17 880 | 1 | 0.00497 |
| warmstart-2f4 | final | 50 040 | **1** | **0.00518** |
| compound3-raw | seed (1-fail hand-built) | 200 | 1 | 0.000118 |
| compound3-raw | `level_retype 0/ll<->1/l` | 18 360 | 1 | 0.00383 |
| compound3-raw | final | 50 040 | **1** | **0.00523** |

Perl optimiser reference: **2–3 fails**.

**The two-C topology breakthrough.** After `level_compound_fix` fires, the
topology is: level 0 = `ll(l1), lr(t2), rl(C), rrl(t3), rrr(O)` — but now l1
is at level 0 (correct) and t3 is adjacent to rl(C) (staircase). However l1
is occupying ll, and rl(C) is the staircase core — so t3-adj-C is satisfied
via rl, but there is no second C to satisfy staircase independently. Score
≈ 0.000157 (1 fail).

At eval ≈ 18 000, `level_retype 0/ll<->1/l` (swap the type of ll on level 0
with l on level 1) creates a TWO-C configuration at level 0:
`ll(C), lr(t2), rl(C), rrl(t3), rrr(O)`, with l1 moving to level 1. The score
jumps 25× to ≈ 0.005. Why two C nodes work:

- `ll(C)` (bottom-left, 23 m²) satisfies t3-adj-C via geometric contact at the
  l/r zone boundary with `rrl(t3)`.
- `rl(C)` (top-right, 8.5 m²) satisfies staircase adjacency via tree adjacency
  to `rrr(O)` (its right sibling when `r.rotation=3`).

Both constraints are simultaneously met because binary-tree sibling adjacency and
cross-zone geometric adjacency provide *independent* paths.

**Why 0 fails is geometrically impossible on this programme + plot.** l1 needs
min 27 m² at level 0. The only space large enough is `ll` (≈ 23 m², the entire
left half of level 0). Putting l1 at `ll` removes the t3-adj-C provider.
The alternative — dividing `ll` into `lll(l1)+llr(C)` — gives `llr` a proportion
of ≈ 6:1 (width ≈ 0.73 m), failing both the proportion and width constraints.
0 fails is not achievable on this programme+plot with a binary slicing tree
representation; 1 fail is the geometric optimum.

---

## 5. Validated architecture

**Memetic search, full objective throughout:**

```
            ┌─────────────────────── topology search (OUTER) ───────────────────────┐
            │  genome = slicing topology + per-leaf type assignment + per-floor       │
            │           divide/undivide deltas (base floor is master)                 │
            │  operators = high-locality topology moves (see §6)                      │
            │                                                                          │
            │   for each proposed topology:                                            │
            │      ┌──────────── geometry inner loop ────────────┐                     │
            │      │ optimise equal-offset cut ratios (1 DOF/cut) │                     │
            │      │ against the FULL fitness (derivative-free /  │                     │
            │      │ gradient), to convergence                    │                     │
            │      └──────────────────────────────────────────────┘                    │
            │      score = best full-fitness over inner loop                            │
            └──────────────────────────────────────────────────────────────────────────┘
                                   fitness: NATIVE Python (fast), reshaped penalty
```

Key decisions, all evidence-backed:

1. **Geometry = inner optimisation against full fitness** (§4.5), *not* an
   area proxy (§4.2). Equal-offset cuts, one DOF per free branch (§4.3).
2. **Search owns topology only.** The base-floor tree is the primary genome;
   per-floor deltas are a small secondary genome (multi-storey constraint as a
   regulariser, via `Below`-inheritance).
3. **Prefer population/batch-evaluating optimisers** so the batched oracle is
   efficient (§4.6). A **native Python fitness** (faithful to Urb, validated
   against the oracle on the 35-file corpus) **gates topology search at scale**
   (§4.6 arithmetic); the oracle suffices for the inner loop and a small-scale
   topology-search proof only.
4. **Reshape the failure penalty** (§4.8) — additive/soft or multi-objective —
   so the search has a gradient and isn't dominated by flag-count. **Caution:**
   the `0.5^n` cliff is what *protects* the inner loop from trading into new
   failures (§4.5); reshaping must not lose that property. Candidate
   resolutions: keep the cliff inside the inner loop only, lexicographic
   ordering (failure count first, score second), or genuine multi-objective
   Pareto. Decide in Phase 4 with measurements.
5. **Representation upgrade (later):** canonical slicing encoding (normalized
   Polish expression / skewed slicing tree, Wong–Liu) for redundancy-free,
   high-locality topology moves; bottom-up shape feasibility checks. Defer until
   the inner loop + native fitness are in place.
6. **Lamarckian geometry inheritance.** A child topology's inner loop
   warm-starts from the parent's optimised ratios (cuts that survive the
   topology move keep their values; new cuts get heuristic defaults). This is
   the main cost lever for the memetic loop (§4.6) and a standard memetic
   design choice (Lamarckian vs Baldwinian — we write the optimised geometry
   back into the genome). Validate the warm-vs-cold speedup in Phase 1.

What we are **not** doing: the bottom-up area-proxy solver; independent-offset
cuts; non-slicing representations (sequence-pair/B*-tree — excluded by §2).

---

## 6. Component plan

| component | status | notes |
|---|---|---|
| `dom.py` (I/O + linkage) | ✅ done | round-trips byte-perfect; keep |
| `geometry.py` (port + cache) | ✅ done, validated | the trusted geometry kernel |
| `programme.py` | ✅ done | extend as fitness needs grow |
| `oracle.py` (Perl bridge) | ✅ done | throwaway; the validation reference |
| `solver.py` (area proxy) | ⚠️ keep as artifact | falsified; do not build on it |
| **geometry inner loop** | ❌ to build | full-objective ratio optimiser (DOF = free branches); batch/population so the oracle batches; warm-start support (§5.6) |
| **topology genome + operators** | ❌ to build | base tree + per-floor deltas; high-locality moves |
| **search driver** | ❌ to build | memetic EA / SA over topology; small-scale on oracle, full-scale needs native fitness |
| **native fitness** | ❌ to build | **gates topology search at scale** (§4.6); port + validate vs oracle; scope is larger than the term list — see below |
| **penalty reshaping** | ❌ to design | additive/soft or multi-objective; must preserve inner-loop cliff protection (§5.4) |
| canonical encoding (Polish expr.) | ❌ later | representation upgrade once core lands |

Urb fitness terms the native port must reproduce (all couple to geometry):
**size, width, proportion, adjacency, access/inaccessible, crinkliness,
perpendicular, level, staircase volume/count, public access, circulation &
outside ratios, min internal area.** Source of truth:
`/home/bruno/src/urb/lib/Urb/Dom/Fitness/ProgrammeDriven.pm` and the `Storey`/
`Building`/`Leaf`/`Base` submodules.

**Port scope beyond the term list** (found by source review — budget for these):

- **Daylight + occlusion subsystem — DESCOPED (decision 2026-06-12).**
  Occlusion is orthogonal to building a scalable optimiser. Instead of porting
  `Urb::Misc::Sun`/`Urb::Field::Occlusion`/CIESky, disable it in Urb behind an
  env flag (`quality_daylight` → 1 everywhere; `Crinkliness`/`Area_Outside`
  pins the `CIEsky_vertical` illumination factor to 1 — *simple crinkliness* =
  unweighted external wall area / floor area). The boundary-overlap geometry
  (`Dom->Walls`) stays in scope; the sky model does not. The native fitness
  ports simple crinkliness only; a Python occlusion subsystem is rebuilt
  post-Phase-5 once optimisation is fully native. **Flipping the flag changes
  every score** — re-baseline the corpus, the §4.5 table, and gate bars at one
  clean boundary, and run the Phase-2 urb-evolve benchmark under the same flag.
- **The cost denominator.** Fitness is value/**cost**: per-leaf area costs,
  interior/exterior wall edge costs, boundary costs
  (Leaf.pm:194-251, Storey.pm:122-147). Cost couples to geometry too.
- **Structural failures** not in the term list: "edge too long" (>8 m, two
  variants), "unsupported covered outside", "covered outside above ground",
  "level N not connected".
- **Missing-space failure stacking** (ProgrammeDriven.pm:192-212): a missing
  space generates 2 base failures plus one per size/width/proportion/adjacency/
  level requirement — up to ~7 failures. Penalty reshaping (Phase 4) must
  preserve this hierarchy or the search will happily drop rooms.
- **Two-phase graph build**: adjacency/level/vertical checks run on the
  *unmerged* tree; graphs are rebuilt after `Merge_Divided` for storey
  processing (ProgrammeDriven.pm:83-103). Easy to get subtly wrong; the
  35-file validation gate will catch it, but anticipate it.
- **Known stub to decide on** (fidelity-vs-fix, §8.1):
  `has_vertical_connection` (ProgrammeDriven.pm:399-423) matches any leaf of
  the target type anywhere on the level below — no spatial-overlap check. A
  faithful port reproduces the bug; decide explicitly.

---

## 7. Phased roadmap

- **Phase 0 — diagnostics** *(done)*: geometry port validated; proxy solver
  falsified; full-fitness geometry headroom validated; oracle throughput
  measured (~1 s/dom batched).
- **Phase 1 — geometry inner loop (on batched oracle)**: full-objective ratio
  optimiser; use a population/batch optimiser so a generation scores in one
  oracle call. Reproduce/exceed the §4.5 gains. Integrate as
  `optimise(topology, x0=None) -> (geometry, fitness)`. Two cheap experiments
  belong here: (a) **warm-vs-cold start** — quantify the §5.6 speedup;
  (b) **optimiser bake-off** — DOF is only ≈ rooms−1, so batched multi-start
  pattern search may beat CMA-ES on simplicity; measure, don't commit blind.
  *Gate:* match §4.5 gains at materially lower oracle-call budget.
- **Phase 2 — topology search, small-scale proof (on batched oracle)**:
  base-tree + per-floor-delta genome, high-locality operators, memetic driver
  wrapping the Phase-1 inner loop. **Explicitly small** (§4.6 arithmetic):
  tens of topologies, budgets counted in **oracle evaluations**, not
  generations. Compare against `urb-evolve` from the same seeds/programmes *at
  equal oracle-call budget* (urb-evolve has diversity injection/culling baked
  in, so generations are not comparable). *Gate:* memetic loop beats
  equal-budget urb-evolve. Scaling up waits for Phase 3.

  **Gate result (homemaker-py-way, 2026-06-13, `URB_NO_OCCLUSION=1`, budget 2000):**
  `experiments/benchmark_vs_urbevolve.py`; urb-evolve scores unchanged,
  memetic scores corrected (patterns.config missing from re-score cwd in first
  run, fixed in same session).

  | seed | system | best@1000 | final@2000 | fails |
  |------|--------|-----------|------------|-------|
  | init.dom | memetic | 8.84e-10 | 3.37e-09 | 18 |
  | init.dom | urb-evolve p16 | 9.10e-06 | 9.36e-05 | 6 |
  | init.dom | urb-evolve p128 | 4.83e-09 | 3.27e-05 | 6 |
  | c964435 | memetic | 7.65e-03 | **7.65e-03** | 2 |
  | c964435 | urb-evolve p16 | 4.00e-03 | 4.00e-03 | 3 |
  | c964435 | urb-evolve p128 | 4.00e-03 | 4.00e-03 | 3 |
  | 2f45907 | memetic | 2.13e-02 | **2.13e-02** | 2 |
  | 2f45907 | urb-evolve p16 | 1.30e-02 | 1.30e-02 | 2 |
  | 2f45907 | urb-evolve p128 | 1.30e-02 | 1.30e-02 | 2 |

  **Verdict: 2/3 seeds → REVIEW.**
  - *Seeded designs (c964435, 2f45907)*: memetic beats urb-evolve by 1.91× and
    1.63×; topology search adds value over the inner-loop-only reference
    (crossover finds a better topology at eval 372 for c964435).
  - *Blank-slate (init.dom)*: memetic stalls at 18 fails after 2000 evals;
    urb-evolve reaches 6 fails. The `0.5^n` cliff means each fail adds ~2× penalty;
    12-fail gap = ×4096. Root cause: single-seed topology mutation chain builds
    structure one room at a time; urb-evolve's random-population initialisation
    explores broader topology diversity upfront. **Not a regression** — this is
    a scope gap: blank-slate construction is harder than seeded improvement, and
    addressed separately (random multi-start bootstrap, or Phase 4 penalty
    reshaping which flattens the fail cliff).
  - The memetic loop is confirmed correct and competitive on the realistic use
    case (seeded designs). Phase 3 (native fitness) unblocks scaled runs where
    this gap will also narrow.
- **Phase 3 — native Python fitness** (**gates scaled topology search**): first
  disable occlusion/daylight in Urb behind an env flag and re-baseline (§6
  descope note); then port Urb's programme-driven fitness — the §6 "port scope
  beyond the term list" items (simple crinkliness, cost denominator, structural
  failures, failure stacking, two-phase graph build). Validate score + failure
  set against the *flagged* oracle across the 35-file corpus (float tolerance,
  identical failure sets). Swap behind the same interface; retire the oracle.
  Then re-run Phase 2 at scale.

  **Gate result (homemaker-py-ccw, 2026-06-13, `URB_NO_OCCLUSION=1`, budget 20000):**
  `experiments/run_search_scaled.py`; native fitness only, no oracle. pop_size=16,
  child_budget=80, seed_budget=300. 71.8 evals/s, 279.8s elapsed.

  programme-house, seed c964435 vs Phase-2 and urb-evolve references:

  | seed | system | budget | best | fails |
  |------|--------|--------|------|-------|
  | c964435 | memetic Phase-2 (oracle) | 2000 | 7.65e-03 | 2 |
  | c964435 | urb-evolve p16 | — | 4.00e-03 | 3 |
  | c964435 | urb-evolve p128 | — | 4.00e-03 | 3 |
  | c964435 | **memetic Phase-3 (native)** | **20000** | **1.04e-02** | **2** |

  **Verdict: PASS.**
  - Best 1.04e-02 beats Phase-2 oracle run (7.65e-03) by **1.36×** and urb-evolve p128
    (4.00e-03) by **2.60×**; both at 2 fails.
  - Winning topology found at eval 10357 via `rotate 1/ll` — unreachable within the
    Phase-2 budget of 2000.
  - Population diverse: 16 members, all at 2 fails (top 15), range 5.99e-03–1.04e-02.
  - Throughput 71.8 evals/s vs ~0.5 evals/s for the batched oracle (≈140× speedup).
  - harbor-house (16 rooms, oracle-impossible): run attempted, results below.

  harbor-house (16 rooms, budget 10000): seed `2b51b05` (best corpus design, 48 fails raw):

  | system | budget | best | fails | evals/s |
  |--------|--------|------|-------|---------|
  | oracle | — | *impossible* | — | — |
  | memetic Phase-3 (native) | 10000 | 3.73e-18 | 49 | 15.8 |

  Search found 3.73e-18 vs seed inner-loop baseline 8.73e-19 (4.3× lift). 638 topologies
  in 633s. 49-fail landscape: still many fails, but topology search is finding structure
  (best 3 population members all at 49 fails). The 16-room programme is qualitatively
  beyond the oracle's capability — this run is only possible with native fitness.
- **Phase 4 — penalty reshaping** *(done, homemaker-py-yg5, 2026-06-14)*:
  **Decision: lexicographic outer-search comparison** (see §4.9).
  Inner loop unchanged — still uses raw `0.5^n` fitness scalar (cliff protection
  preserved, §5.4). Outer search compares individuals by `(-n_fails, fitness)`:
  fewer fails always beats more fails; within a tier, compare by score.
  Implemented in `driver.search(use_lex=True)`. `_CHILD_INNER_KW` stale
  `sigmas` entry also removed (NM default has no `sigmas` parameter).
- **Phase 5 — representation upgrade**: canonical slicing encoding
  (Polish expression) + bottom-up shape feasibility; scale to larger programmes.

Each phase has a concrete go/no-go gate; do not advance on faith.

---

## 8. Risks & open questions (decisions for the next session)

1. **Native-fitness fidelity vs simplification.** Port Urb's fitness exactly
   (maximise comparability) or take the opportunity to clean up known issues
   (the `0.5^n` cliff, the t3 width-default contradiction below, the
   `has_vertical_connection` no-overlap stub — §6)? Recommend: *port faithfully
   first* (bugs included), validate, then reshape in Phase 4.
2. **Programme contradictions exist.** e.g. t3 (3 m² WC) inherits the 4 m
   `width_inside` default (Fitness/Base.pm:60) — geometrically impossible; the
   original "passes" only by failing `size` instead. *Confirmed in source.*
   Need a sane width default scaled to area, or per-room widths.
3. **Inner-loop optimiser choice — RESOLVED (homemaker-py-d0s, 2026-06-13).**
   Bake-off over 3 files × 4 methods × 3 seeds at budget 200
   (`experiments/bakeoff_innerloop.py`), cold-start, `URB_NO_OCCLUSION=1`:

   | method      | x@40 | x@80 | x@200 | s/eval | oracle calls | fails+ |
   |-------------|------|------|-------|--------|--------------|--------|
   | Nelder-Mead | 1.45 | 1.50 |  1.56 |   2.05 |          200 |      0 |
   | CMA-ES      | 1.09 | 1.32 |  1.41 |   1.69 |           18 |      0 |
   | compass     | 0.71 | 0.92 |  1.48 |   1.69 |           12 |      3 |
   | compass-ms  | 0.71 | 0.92 |  0.92 |   1.44 |           13 |      4 |

   **Decision: keep CMA-ES (already the default) for the Perl oracle era.**
   Nelder-Mead wins quality per eval (+x0.15 at @200) but is inherently
   sequential — 200 Perl invocations vs 18 for CMA (§4.6 batching matters).
   Compass stalls on narrow-valley landscapes (2f45907: x0.62 vs x1.30) and
   introduces fail regressions 3/9 runs. Multi-start compass wastes budget
   on phase splits.

   **Phase 3+ note:** once native fitness replaces the oracle, oracle-call count
   disappears. Revisit Nelder-Mead then — its quality advantage is real.
   Gradient-based (autograd through native fitness) is also an option.
4. **Search algorithm for topology.** Memetic GA (keep crossover — now
   meaningful, since a subtree = a contiguous region) vs simulated annealing
   (the floorplanning workhorse with M1/M2/M3 moves on Polish expressions).
5. **Penalty reshaping vs inner-loop protection — RESOLVED (homemaker-py-yg5,
   2026-06-14).** Lexicographic outer-search comparison (§4.9). Inner loop
   unchanged.
6. **Other continuous DOF are out of scope for Phase 1 — deliberately.**
   Floor-to-floor height is an Urb mutation (Mutate.pm:279-291, bounded
   2.7–3.6 m) and feeds cost and stair fit; stair riser/width similar. Cut
   ratios dominate. Revisit (+1 DOF per storey) if Phase 2 plateaus.
7. **End-state confirmed: 100% Python**; Perl oracle is scaffold only.

---

## 9. How to reproduce (for the next session)

```bash
cd /home/bruno/src/homemaker-layout
# deps: pyyaml numpy scipy (shapely networkx for later phases)

# geometry port vs Urb (must be identical):
for d in /home/bruno/src/urb/examples/programme-house/*.dom; do
  diff <(perl -I/home/bruno/src/urb/lib experiments/dump_areas.pl "$d") \
       <(python3 experiments/dump_areas.py "$d") || echo "MISMATCH $d"
done

python3 experiments/resolve_ratios.py        # proxy solver (falsified)
python3 experiments/sweep_failtypes.py       # failure-type histogram
python3 experiments/optimize_fullfitness.py 200   # full-fitness headroom (validated)
```

Oracle invocation (see `oracle.py`): `cwd` = the `.dom`'s directory (so
`patterns.config` is found), `perl -I<urb>/lib <urb>/bin/urb-fitness.pl <file>`,
env `DEBUG=1` to defeat the skip-if-newer cache; reads `<file>.score` and
`<file>.fails`.

---

## 10. Key gotchas discovered (carry forward)

- **Wall inset:** the `.dom` plot is the *outer* boundary; Urb insets the root by
  `wall_outer` on load (`Urb::Dom::_deserialise`, Dom.pm:458) and offsets back out
  on save. `geometry.offset_quad` mirrors it; `dom.py` stashes raw corners in
  `node_file`. Skipping this makes all areas ~14% too large.
- **Multi-storey `Below`-inheritance:** an upper quad's coordinates come from the
  matching quad below; a cut is "owned" by the *lowest* storey where its path is
  divided (`solver.free_branches` selects these). Walls stack for free.
- **Geometry must be cached** — the pull-based recursion is exponential in depth
  otherwise (`geometry._cache`, cleared on `dom.load` and after each solver
  mutation).
- **Equal-offset cuts** (`a == b`) ⇒ perpendicular walls, 1 DOF/cut. Independent
  offsets are wrong.
- **`0.5^n` cliff** dominates fitness; it punishes new failures catastrophically
  (good for the inner loop, brutal for search gradient).
- **Oracle ≈ 1 s/dom batched** (1.65 s single; assessment-dominated, startup
  ~0.65 s amortises across a batch). Submit many `.dom`s per call and prefer
  population optimisers; native fitness is a later speed/scale win, not a gate.

---

## 11. Phase 6 — topology-search quality for full / multi-storey programmes

**Epic:** `homemaker-py-c4c`. **Status:** scoped 2026-06-17, pre-implementation.
This section is the experiment ledger for the epic; each subsection is stubbed
now and **filled in by the session that runs the experiment** (record the
command, the numbers, and a one-line verdict, in the style of §4).

### 11.0 Diagnosis (why this phase exists)

The delivered speedups landed in the two layers that were **never the
bottleneck**. The native fitness (~140× over the oracle, §7 Phase 3) and the
geometry inner loop (~1.6×, §4.5/§4.7) both operate *within a fixed topology*:
the inner loop polishes geometry **inside a failure tier** and, by design, the
`0.5^n` cliff stops it ever changing the failure count (§4.5: 0-fail-change
across the headroom table). But final design quality is dominated by **failure
count**, which is almost entirely a **topology** property. So faster fitness and
better geometry do not move the number an architect would notice.

Topology search on full programmes is the weakness:

- **blank-slate programme-house** (`init.dom`): memetic stalls at **18 fails**;
  urb-evolve reaches **6** (§7 Phase 2 verdict).
- **harbor-house** (16 rooms): `out1.dom` = **74 fails**, `generated.dom` =
  **130 fails**, both at ~machine-epsilon score; failures dominated by
  **`missing`-room stacking** (each missing room stacks critical + size + width
  + adjacency + level, §6).

**Smoking gun:** `operators.mutate_divide` (operators.py:71) types each new leaf
**at random** from `programme-codes + C + O`. Nothing makes the required
programme spaces a constructive invariant, so on a large programme required
rooms simply go missing → catastrophic `0.5^n` stacking, and the search is a
random walk over type assignments with a flat-and-catastrophic gradient in the
high-fail regime.

**Causal frame for the fixes.** The base-floor tree is the *master* genome;
upper storeys are divide/undivide deltas (`Below`-inheritance); the programme
partitions rooms by required level (harbor: **10 on L0, 4 on L1, 2 free**). So
construction and search should follow the genome's dependency order — credible
base floor first, upper floors as deltas, with each floor's required-room set
known from the programme. **Do not hard-freeze the base** when adding floors:
that recreates the §4.2 partial-objective trap at the topology level (a base
optimised purely as a ground floor can be a bad *substrate* — the vertical core
must stay aligned and load-bearing walls must stack).

### 11.1 Premise experiment: single-storey harbor (`homemaker-py-c4c.1`) — DONE

Built `examples/harbor-house-l0/` from harbor by retaining only the 10 space
codes explicitly marked `level: 0` (cr1, ef1, da1, k1, ws1, m×3, la1, st1, me1,
of×2 → 13 room instances), pruning adjacencies to the retained codes, and
setting single-storey constraints (`storey_minimum: 1`, `storey_limit: 1`). The
straddling anonymous spaces `n`/`t` (no explicit level key) were dropped so the
set is an unambiguous single floor. Seeded from the bare plot (`init.dom`).

- *Expectation / decision rule:* near-zero fails ⇒ bottleneck is multi-storey
  *coupling* (staging is the lever); still stalls (esp. `missing`) ⇒ per-floor
  *construction* itself is the bottleneck (§11.2 required first).
- *Command (reproduce):*
  ```bash
  URB_NO_OCCLUSION=1 python3 experiments/run_search_scaled.py \
    examples/harbor-house-l0 20000 0 \
    examples/harbor-house-l0/init.dom examples/harbor-house-l0/generated.dom
  ```
- *Result:* 20000 native evals across 250 topologies (234 s, 85 evals/s).
  Best **33 fails**, fitness 2.25e-12 — deep in the 0.5ⁿ high-fail penalty
  regime, with the whole 16-member population stuck at 33–35 fails. The smaller
  budget-300 smoke run sat at 40 fails; full budget only crept 40 → 33. **Not
  near zero.** Fail histogram of the best `generated.dom`:

  | count | category |
  |------:|----------|
  | 13 | **missing** (all 3 `m` meeting rooms never constructed: required/critical + per-instance size/width/adjacency sub-checks) |
  | 6 | adjacency (ws1→c, k1→da1, da1→c, da1→k1, me1→c, la1→c) |
  | 4 | access |
  | 4 | size |
  | 2 | edge too long |
  | 2 | crinkliness |
  | 1 | proportion |
  | 1 | too few stairs — single-storey artifact (`staircase_min` floored to 1 by the fitness `or 1` default; constant across runs) |
  | **33** | total |

- *Verdict: per-floor CONSTRUCTION is the bottleneck, not multi-storey coupling.*
  Even on a single floor with only 13 rooms and zero delta/core-alignment
  complexity, the search cannot assemble the required room set: the dominant
  category (13/33 = 39 %) is `missing` — the counted anonymous space `m×3` is
  entirely absent — and the remaining fails are downstream adjacency/access/size
  consequences of a room set the mutation operators never managed to construct.
  This matches the §11.0 prediction's "still stalls (esp. `missing`)" branch:
  **§11.2 programme-aware construction + missing-room repair is the prerequisite,
  and staging alone (§11.3) will not rescue it.** §11.3 stays blocked on §11.2.

### 11.2 Programme-aware construction + missing-room repair (`homemaker-py-c4c.2`) — DONE

Two changes (`operators.py`, wired in `driver.py`):

1. **`constructive_topology`** — bootstrap seeder that makes the required room
   set a *constructive invariant*. It sizes each storey to its required rooms
   (partitioning by `level`; level-free rooms distributed round-robin over a
   shuffled order), plus one circulation `C` and one outside `O` per storey,
   grows the slicing tree to that leaf count, and assigns the types. Stochastic
   (random splits/rotations, shuffled type→leaf assignment) so a bootstrap batch
   is still a diverse population. Replaces the random `random_topology` bootstrap
   whenever the programme has required spaces.
2. **`mutate_place_missing`** — repair operator. Detects a required-but-absent
   space (`graph.check_space_counts`) and inserts one by dividing a host leaf
   into `[room | remainder]`. Lex-safe host ranking (cf. §4.10): generic `O`
   leaves first (unbounded, nothing displaced), then other non-required leaves,
   circulation/stairs only as last resort; a required room is never displaced.
   Forced onto the room's required storey when the programme constrains its
   level. Weight 2.0 in the mutation mix (noops cheaply once complete).

- *Gate:* `missing`-type failures collapse to ~0; net-fail improvement vs the
  blank-slate baseline; no regression on the seeded programme-house 1-fail
  optimum (§4.10).
- *Commands (reproduce):*
  ```bash
  # A/B at identical budget+seed (old = git HEAD before this change):
  URB_NO_OCCLUSION=1 python3 experiments/run_search_scaled.py \
    examples/harbor-house 20000 0 examples/harbor-house/init.dom out.dom
  # §4.10 regression: warmstart-2f4 seed, 50000 evals, pop 8, 4 workers
  ```
- *Result (harbor-house, 20000 native evals, seed 0, identical config):*

  | metric | OLD (random bootstrap) | NEW (constructive) |
  |--------|-----------------------:|-------------------:|
  | seed best fails | 163 | 139 |
  | final total fails | 133 | **105** |
  | `missing` fails | **103** (77 %) | **12** (11 %) |
  | missing-records | 22 | 2 |
  | dominant remaining | `missing` | crinkliness 27, size 23, access 13, edge 12 |

  Constructive seeding alone gives a **24-fail head start at the seed**
  (163 → 139) and the run ends at **105 vs 133 (−21 %)**, with the
  `missing` stack collapsed **103 → 12**. **§4.10 regression: PASS** — the
  warmstart-2f4 seed still reaches a **1-fail** population (whole pop 1f at
  50 040 evals; `place_missing` noops harmlessly when the set is complete).

- *Verdict: construction works and is necessary, but reframes the bottleneck.*
  Making the required set a constructive invariant removes the catastrophic
  `missing`-room stacking that dominated the blank-slate baseline (77 % → 11 %
  of fails). But a *complete* 36-room harbor design then carries a large
  **quality-fail load** — crinkliness/size/access/edge-too-long packing of two
  fully-populated floors — that the current geometry inner loop + topology
  operators reduce only partway in 20k evals. So total fails improve but stay
  high. The dominant categories are now exactly what **§11.4 (graded objective,
  to navigate the dense quality-fail regime)** and **§11.3 (staging — build one
  credible floor at a time instead of cramming both)** target; §11.3 is
  unblocked by this result. A concrete next seeder refinement (filed): the
  type→leaf assignment is currently random, ignoring adjacency — clustering each
  room near its required `c`/neighbour at construction time should cut the
  adjacency (8) and downstream access (13) fails directly.

  *Note on the baseline:* DESIGN cited a "74-fail `out1.dom`", but the on-disk
  `out1.dom` is untracked and was overwritten by a prior experiment (it now
  re-scores to 37 fails; the committed `out1.dom.fails` of 74 lines belongs to
  the superseded `.dom`). The honest, reproducible comparison is therefore the
  identical-config A/B against the pre-change code (133 fails), not the stale
  `out1.dom` number.

### 11.3 Staged per-floor search (`homemaker-py-c4c.3`)

*Stub.* Stage 1: base floor over the level-0 room set (one tree, no deltas) +
reserved core + substrate-readiness term. Stage 2: upper floors as deltas seeded
with their required room sets, base kept mutable at low probability. Gated by
§11.1 premise.

- *Gate:* staged beats single-stage on harbor at equal native-fitness budget;
  reserved-core + readiness shown to prevent the bungalow trap (stage 2 does not
  carve a core from scratch); no programme-house regression.
- *Result:* TODO.

### 11.4 Graded high-fail objective (`homemaker-py-c4c.4`)

*Stub.* Extends Phase 4 (§4.9). Lexicographic-by-total-count gives ~zero signal
when every candidate sits at ~49–74 fails. Add partial credit (proximity per
unsatisfied constraint and/or count of *distinct* unsatisfied requirements) as a
secondary key beneath fail-count, preserving the inner-loop cliff (§5.4) and the
missing-space hierarchy (§6).

- *Gate:* measured escape from a high-fail plateau the current lex comparator
  cannot escape at equal budget; inner-loop 0/9-regression check (§4.9) still
  clean.
- *Result:* TODO.

### 11.5 Topology diversity: structural niching + restarts (`homemaker-py-c4c.5`)

*Stub.* Replace the fitness-scalar dedup (driver.py:174) with a topology
signature so niching is by *structure*, not score; add crowding/restarts/islands
to match urb-evolve's upfront diversity on blank slate.

- *Gate:* blank-slate programme-house reaches ≤ 6 fails at equal budget; distinct
  topology-signature count over time quantified before/after.
- *Result:* TODO. (Capstone `homemaker-py-9gp` canonical Polish encoding is the
  principled long-term signature — `(a|b)|c == a|(b|c)` collapse — and lands
  after §11.2.)
