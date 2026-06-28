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

### 11.3 Staged per-floor search (`homemaker-py-c4c.3`) — DONE

Searches the genome in causal dependency order (`driver.search_staged`), two
stages composed from the existing `driver.search`:

1. **Stage 1 — base floor** (40 % of budget). A single-storey programme is
   auto-derived to a tempdir (`programme.write_stage1_programme`): the full
   `patterns.config` filtered to the storey-0 room set
   (`programme.partition_rooms_by_storey`), `level:` keys dropped, adjacencies
   pruned to surviving refs, `storey_limit/staircase` forced to 1. The base is
   searched on that reduced programme but **ranked** with a substrate-readiness
   bonus — key `(-n_fails, fitness·(1 + W·readiness))`, `W=1` — so it is selected
   as a good *substrate*, not merely a good ground floor (anti-§4.2).
   `graph.substrate_readiness` = `core_factor · capacity`: full credit for a
   reserved `C` leaf ≥ `STAIR_MIN_AREA` (vertically-alignable core), times
   `min(1, usable_base_area / required_upper_area)` (enough divisible footprint
   for the upper set).
2. **Stage 2 — upper floors as deltas** (remaining budget). The best base is
   lifted (`operators.lift_base_to_storeys`) into a full multi-storey design that
   **preserves the base storey and its inherited core** and instantiates each
   upper storey's required room set by construction (the Stage-2 analog of §11.2
   seeding). Deltas are searched with the base kept **mutable at low probability**
   (`base_p=0.15`, threaded through the exploratory ops; `place_missing`/`core_*`
   stay unbiased — repair and core-maintenance must reach the base).

- *Gate:* staged beats single-stage on harbor at equal budget; reserved-core +
  readiness prevent the bungalow trap (stage 2 does not carve a core from
  scratch); no programme-house regression.
- *Commands (reproduce, `URB_NO_OCCLUSION=1`, 20000 evals, seed 0):*
  ```bash
  python3 experiments/run_search_scaled.py examples/harbor-house 20000 0 \
    examples/harbor-house/init.dom scratch/ab_single.dom        # single-stage
  python3 experiments/run_staged_search.py examples/harbor-house 20000 0 \
    examples/harbor-house/init.dom scratch/ab_staged.dom         # staged
  ```
- *Result (harbor-house, 20000 native evals, seed 0, identical config):*

  | metric | single-stage | **staged** |
  |--------|-------------:|-----------:|
  | total fails | 105 | **95** |
  | crinkliness | 27 | 18 |
  | edge too long | 12 | 8 |
  | proportion | 6 | 4 |
  | width | 4 | 2 |
  | size | 25 | 26 |
  | access | 13 | 18 |
  | missing | 8 | 8 |
  | adjacency | 2 | 2 |

  Single-stage reproduces the §11.2 baseline **exactly (105 fails)**; staged ends
  at **95 (−10, −9.5 %)**. The gain is concentrated in the packing fails staging
  targets — crinkliness 27→18 and edge-too-long 12→8 — at a small cost in access
  (+5). **Anti-bungalow: confirmed.** Every `core_divide`/`core_undivide` in the
  Stage-2 winning lineage is a *noop* — the core is inherited from Stage 1 and is
  never carved from scratch. **Programme-house regression: PASS** — single-storey
  programmes fall through to plain `search`; the warmstart-2f4 seed (50000 evals,
  pop 8, 4 workers) still reaches a whole-population **1-fail** optimum (§4.10).

- *Verdict: staging helps, modestly, and is the right structural frame.* Building
  one credible, substrate-ready floor first — then upper floors as constructed
  deltas with an inherited core — beats cramming both floors simultaneously
  (95 vs 105) without touching the inner loop. The remaining load is the dense
  quality-fail regime (size/access/crinkliness on two fully-populated floors) that
  **§11.4 (graded objective)** targets: with `missing` already collapsed (§11.2)
  and the floors now assembled in dependency order, the lever left is navigation
  *within* the high-fail plateau, where lex-by-count gives near-zero gradient.

### 11.4 Graded high-fail objective (`homemaker-py-c4c.4`) — DONE (negative)

Premise (from Phase 4, §4.9): lexicographic-by-total-count `(-n_fails, fitness)`
gives ~zero selection signal in the high-fail regime because the `0.5^n` cliff
flattens fitness to ~machine-epsilon, so neighbours at ~49–105 fails look
indistinguishable. Proposed fix: a continuous proximity key *beneath* fail-count
and *above* fitness — `(-n_fails, grade, fitness)`.

**Implementation (kept, default-off).** `fitness._leaf_grade` reads each *failing*
per-leaf quality factor (perpendicular/proportion/size/width/crinkliness/access)
as proximity-to-satisfaction `f / FAIL_THRESHOLD ∈ [0,1)` and sums it;
`Fitness.score_with_grade` returns it alongside score/fails. The scalar fitness
and the fail count are **untouched**, so the inner-loop `0.5^n` cliff (§5.4) is
unaffected — **inner-loop 0/9-regression check: PASS** (re-ran §4.9 part 1,
`run_inner_loop_protection`, 0/9 regressions). The grade is read once per child
off the already-optimised tree in `driver._evaluate` (one extra native eval,
~1/child_budget) and used **only** in the outer comparator key, behind
`search(..., use_grade=True)` / `search_staged(..., use_grade=True)` (default
`False`; threaded to Stage 2 only — Stage 1 keeps its readiness key, §11.3).
Structural fails (missing/adjacency/edge-too-long/level/…) score 0 grade, so the
missing-space hierarchy (§6) is preserved: grade can never reward dropping a room.

- *Commands (reproduce, `URB_NO_OCCLUSION=1`, 20000 evals):*
  ```bash
  USE_GRADE=0 python3 experiments/run_staged_search.py examples/harbor-house 20000 <seed> \
    examples/harbor-house/init.dom scratch/st_lex.dom        # lex baseline
  USE_GRADE=1 python3 experiments/run_staged_search.py examples/harbor-house 20000 <seed> \
    examples/harbor-house/init.dom scratch/st_grade.dom      # lex + grade
  ```
- *Result (harbor-house, staged, 20000 native evals, total fails at budget):*

  | seed | staged `lex` | staged `lex+grade` |
  |-----:|-------------:|-------------------:|
  | 0    | **95**       | 99                 |
  | 1    | **96**       | 98                 |
  | 2    | 106          | **102**            |
  | mean | **99.0**     | 99.7               |

  Grade wins 1/3 seeds, loses 2/3, and is **slightly worse on the mean** —
  within seed-noise, **no escape** from the plateau. Single-stage seed 0 is a
  dead heat (105 = 105). Stage-1 is identical by construction (grade off there);
  the divergence is entirely in Stage 2, where the grade run **stalls early**
  (seed 0: last improvement at 13600/20000 evals, stuck at 99) while lex keeps
  reducing the count (99→95).

- *Why it fails — the premise is falsified by measurement.* The cliff is constant
  *within* a fail-tier (`0.5^n`, `n` fixed), so within a tier reported fitness is
  `value/cost × const` and still spans **~6 orders of magnitude** (seed-0 Stage-2
  history: 1.2e-37 → 4.6e-31 *all inside the same descending fail count*). The
  outer comparator only ever compares within a tier (−`n_fails` dominates across
  tiers), so lex's secondary `fitness` key already carries a strong, well-graded
  signal — exactly the gradient §11.4 assumed was missing. Inserting `grade`
  *above* `fitness` **displaces** that working signal: the population fills with
  high-grade (shallow-fail) incumbents and the fail-reducing restructurings — which
  transiently deepen other fails and so look worse on grade — are no longer
  selected. Placing `grade` *below* `fitness` instead would be near-inert (fitness
  ties are measure-zero in a continuous objective). Either way there is no lever:
  the high-fail plateau is a *topology* basin, not a comparator-resolution problem.

- *Verdict: reject the graded objective; lexicographic `(-n_fails, fitness)`
  stands.* The §11.3 staged **95-fail** result remains the harbor best. The
  remaining load is genuinely structural (escaping topology basins), which is what
  **§11.5 (structural niching + restarts)** and the `9gp` canonical-encoding
  capstone target — not outer-comparator reshaping. The `use_grade` flag and
  `score_with_grade` are kept default-off for reproducibility and possible reuse
  (e.g. as a *diversity* signal under §11.5 rather than a selection key).

### 11.5 Topology diversity: structural niching + restarts (`homemaker-py-c4c.5`) — DONE (negative)

Premise (epic diagnosis): the population dedups on the **fitness scalar**
(`driver.admit`, `abs(fitness)` within `1e-9`) and so has no structural diversity
preservation — proposed as the root cause of the blank-slate gap (§7 Phase 2:
memetic 18 fails vs urb-evolve 6), a single mutation chain losing to urb-evolve's
upfront random-population diversity.

**Implementation (kept, default-off).** A cheap structural topology signature
(`genome.signature`) string-encodes each storey's tree shape + cut orientations
+ leaf types, routed through `encode` so dead inherited fields canonicalise; it
is **ratio-invariant** (same topology, different geometry → same signature). Two
diversity mechanisms, both behind flags on `search`/`search_staged`:
`niche_by_signature` holds at most one individual per signature in the population
(structural niching, keeping the better of a collision) in place of the
fitness-scalar guard; `restart_patience=<evals>` does a soft restart on
stagnation (keep `restart_elite` incumbents, refill with fresh
constructive/random seeds — urb-evolve's upfront diversity as a soft restart).
`SearchResult` gained `n_distinct_signatures` / `diversity_history` /
`n_restarts` to quantify diversity over time.

- *Commands (reproduce, `URB_NO_OCCLUSION=1`, 20000 evals):*
  ```bash
  NICHE=0 python3 experiments/run_search_scaled.py examples/programme-house 20000 <seed> \
    examples/programme-house/init.dom scratch/ph_before.dom   # legacy dedup (before)
  NICHE=1 python3 experiments/run_search_scaled.py examples/programme-house 20000 <seed> \
    examples/programme-house/init.dom scratch/ph_niche.dom    # structural niching
  NICHE=1 RESTART_PATIENCE=2000 python3 experiments/run_search_scaled.py \
    examples/programme-house 20000 <seed> examples/programme-house/init.dom scratch/ph_restart.dom
  # harbor (staged): swap run_staged_search.py, seed examples/harbor-house/init.dom
  ```

- *Diversity (the secondary criterion) — MET.* Niching takes the final
  population from ~**4–6 / 16** distinct topologies (legacy dedup) to **16 / 16**;
  restarts raise distinct topologies *seen* by ~30 % (≈105–138 → ≈164–186 on
  programme-house). The signature machinery works exactly as designed.

- *Fail count (the gate) — NOT MET.* Blank-slate programme-house, total fails at
  budget (lower is better):

  | seed | before (legacy) | niche | niche + restart |
  |-----:|----------------:|------:|----------------:|
  | 0    | **11**          | 14    | 12              |
  | 1    | **11**          | 11    | 14              |
  | 2    | 15              | **13**| 13              |
  | mean | **12.3**        | 12.7  | 13.0            |

  Harbor-house (staged, seed 0): legacy **95** (reproduces §11.3 exactly), niche
  **94**, niche+restart **108**. Across both programmes niching is a **tie within
  seed noise** and restarts are **strictly worse**; nothing approaches the ≤ 6
  gate.

- *Why it fails — the premise is falsified by measurement.* More *structural*
  population diversity does not buy lower fails: the legacy dedup already holds
  14/16 distinct topologies on harbor (Stage-2 starts from lifted bootstraps), so
  it was never the diversity bottleneck the epic assumed. Maximal diversity
  (16/16) with the fixed tournament pressure just **diffuses** effort — the
  fitness-scalar dedup's smaller effective population exploits a basin slightly
  harder. Restarts throw away converging Stage-2 work and regress hardest. The
  high-fail plateau is a **reachability** problem (operators + encoding cannot
  reach the low-fail basins), not a population-management one — the same
  conclusion §11.4 reached from the comparator side.

- *Verdict: reject niching/restarts as defaults; the legacy fitness-scalar dedup
  stands.* `niche_by_signature` / `restart_patience` are kept default-off for
  reproducibility and reuse, and `genome.signature` is the cheap stand-in that the
  canonical Polish encoding (**`homemaker-py-9gp`**) supersedes. With §11.3–§11.5
  all landed, the residual load is genuinely structural: the principled lever is
  the canonical encoding (associativity collapse `(a|b)|c == a|(b|c)`) plus richer
  topology operators, not outer-loop selection/population reshaping.

### 11.6 Adjacency-aware constructive seeding (`homemaker-py-s44`) — DONE (positive)

Premise (follow-up to §11.2): `constructive_topology` instantiated every required
room but **typed the leaves at random**, so rooms landed stranded from
circulation. On harbor the seed carried ~29 adjacency-to-`c` + ~27 per-leaf
`access` + level-`inaccessible` fails (≈ 56 of the seeder-controllable load; the
remaining size/width/proportion/crinkliness fails are geometry, the inner loop's
job). The programme confirms the shape: of 16 harbor spaces all 16 require
adjacency to `c`, so the dominant lever is *connect every room to circulation*.

**Implementation (`operators._assign_adjacency_aware`, default-on).** A single
circulation leaf cannot border a dozen rooms, and a slicing tree guarantees
adjacency only between *siblings* — so adjacency must be read from the geometric
leaf graph, not the tree. The seeder now spends ~one extra leaf per three rooms
on circulation, builds the type-independent `geometry.leaf_graph`, and picks a
**greedy connected dominating set** of circulation leaves (start at the
highest-degree leaf, extend along the frontier by most-newly-dominated): every
room leaf ends up bordering a *connected* circulation spine, so adjacency-to-`c`
and access are satisfied by construction at the seed geometry. Rooms are placed on
dominated leaves (constraint-hardest first), outside `O` on the most peripheral
leaf; room order and tie-breaks stay stochastic so a bootstrap batch is diverse.
Threaded through `driver.search(seed_adjacency_aware=True)`; `adjacency_aware`
flag on `constructive_topology` (env `ADJ` in `run_search_scaled.py`) for the A/B.

- *Commands (reproduce, `URB_NO_OCCLUSION=1`, 20000 evals, single-stage):*
  ```bash
  ADJ=0 python3 experiments/run_search_scaled.py examples/harbor-house 20000 <seed> \
    examples/harbor-house/init.dom scratch/hh_adj0.dom        # random assignment (before)
  ADJ=1 python3 experiments/run_search_scaled.py examples/harbor-house 20000 <seed> \
    examples/harbor-house/init.dom scratch/hh_adj1.dom        # adjacency-aware (after)
  ```

- *Seed quality (harbor, 10 seeds, raw seed before optimisation):* adjacency-to-`c`
  **29.2 → 12.2**, per-leaf access **26.6 → 8.3**, level-inaccessible 0.4 → 0.2
  (≈ 56 → 21 seeder-controllable fails). Geometry fails rise at the raw 0.5-split
  seed (more, smaller leaves) but are recovered by the inner loop.

- *End-to-end (total fails at budget, single-stage, lower is better):*

  | seed | harbor before | harbor after | prog-house before | prog-house after |
  |-----:|--------------:|-------------:|------------------:|-----------------:|
  | 0    | 105           | 100          | 11                | 10               |
  | 1    | 115           | **85**       | 11                | **8**            |
  | 2    | 110           | 87           | 15                | 10               |
  | mean | **110.0**     | **90.7**     | **12.3**          | **9.3**          |

  Harbor **−19.3 fails (−17.5 %)**, programme-house **−3.0 (−24 %)**. `ADJ=0`
  seed 0 reproduces the §11.2 single-stage **105** baseline exactly (clean
  control). Notably the adjacency-aware **single-stage** harbor (mean 90.7, best
  85) now **beats the §11.3 staged best of 95** — the first Phase-6 fail-count
  reduction from *seeding* rather than search machinery.

- *Verdict: keep adjacency-aware seeding as the default.* It is the first lever in
  Phase 6 to move the fail count on both programmes. The win is the dominant
  adjacency-to-`c` / access load; secondary adjacencies and the staged
  `lift_base_to_storeys` upper floors are picked up in §11.7 (`homemaker-py-ld5`).

### 11.7 Adjacency-aware lift + secondary adjacencies (`homemaker-py-ld5`) — DONE (positive)

Two gaps left by §11.6: (a) `lift_base_to_storeys` — the staged Stage-2 seeder —
still typed upper-floor leaves at random, so staged search did not get the
adjacency win; (b) secondary adjacencies (`k1↔da1`, `da1↔o`, ~4 harbor rooms)
were ignored.

**Implementation.** `_assign_adjacency_aware` gained a `fixed_circ` parameter: the
dominating-set search is *seeded from* given circulation leaves, so on an upper
floor the spine grows off the **inherited vertical core** rather than from
scratch (preserving the §11.3 anti-bungalow core-alignment invariant). Room
placement is now constraint-ordered: codes with the most non-`c` adjacency
requirements are placed first, each onto the open slot that satisfies the most of
its requirements against already-typed neighbours (circulation + rooms placed so
far), clustering `k1↔da1`, `da1↔o`, etc. `lift_base_to_storeys(reqs=…,
adjacency_aware=True)` grows a per-floor circulation budget and calls it with the
core as `fixed_circ`; threaded through `search_staged(seed_adjacency_aware=True)`
(`ADJ` env in `run_staged_search.py`).

- *Seed quality (harbor lift, 8 seeds, raw seed):* adjacency-to-`c` **16.1 → 7.6**,
  access **16.2 → 7.2** on the lifted upper floor.

- *End-to-end (harbor, staged, 20000 evals, total fails at budget):*

  | seed | staged before (`ADJ=0`) | staged after (`ADJ=1`) |
  |-----:|------------------------:|-----------------------:|
  | 0    | 95                      | 97                     |
  | 1    | 96                      | **78**                 |
  | 2    | 106                     | 81                     |
  | mean | **99.0**                | **85.3**               |

  `ADJ=0` reproduces the §11.4 staged lex baseline **exactly** (95/96/106, mean
  99.0 — clean control). Staged adjacency-aware is **−13.7 fails (−14 %)** and is
  now the **best harbor configuration overall**: staged baseline 99.0 → single-
  stage adjacency-aware (§11.6) 90.7 → **staged + adjacency-aware lift 85.3**
  (best **78**, seed 1). Staging and adjacency-aware seeding compose: the
  credible Stage-1 base and the core-seeded upper spine each contribute.

- *Verdict: keep adjacency-aware lift + secondary clustering as defaults.* Harbor
  is now ~85 fails, down from the 95/105 plateaus that opened Phase 6. The
  residual is geometry- and shape-bound (size/proportion/crinkliness on the
  denser, more-circulation layouts), which is the canonical-encoding /
  shape-feasibility territory of `homemaker-py-9gp`.

## 12. Phase 7 — scaling validation & residual reduction (post-c4c)

**Epic:** `homemaker-py-leu`. **Status:** opened 2026-06-19. Continuation of the
closed Phase 6 (§11). Phase 6 evidence located the leverage in *construction /
seed quality* (§11.6/§11.7 wins) rather than search machinery (§11.4/§11.5 both
regressed); the harbor residual is now geometry/shape-bound at ~85 fails. This
section is the experiment ledger for Phase 7, same discipline as §11: each
subsection records the command, the numbers, and a one-line verdict.

### 12.1 Larger-than-house benchmark: `maple-court` (`homemaker-py-leu.1`) — DONE

**Why.** Harbor (16 programme entries, 2 storeys) was the biggest real programme
in `examples/`. `homemaker-py-9gp`'s headline claim is scaling **>16 rooms** and
its acceptance criterion demands "a larger-than-house programme" to measure on —
so a bigger benchmark is a prerequisite, not optional. Proportion-aware seeding
(`leu.2`) and re-scoped 9gp are both measured against this baseline.

**The benchmark.** `examples/maple-court/` — a three-storey assisted-living /
co-housing facility: **26 distinct programme entries / 52 room instances** across
**3 required storeys** (`storey_minimum: 3`), ~1015 m² target internal area on a
~790 m²/floor plot. It mirrors harbor's structure deliberately — a dominant
adjacency-to-`c` load on nearly every room plus a handful of secondary
adjacencies (`da1↔k1`, `da1↔o`, `lr1/ws1/lo1/gh1/gy1 ↔ o`), anonymous
interchangeable room families (`m`×3, `t`×6, `n`×4, `r`×12, `em`×2, `py`×2,
`tt`×4), and `staircase_min/max: 2`. Code letters avoid the generic `c`/`o`/`s`
leading-letter trap (those are reserved in `fitness.py`/`graph.py` for
circulation/outside/sahn): no *room* code starts with c/o/s, so harbor's quirk of
typing Common Room / Storage / Office as quasi-generic (`cr1`/`st1`/`of`) is not
reproduced. `init.dom` is a single `O` footprint; storeys are built by the search
from `storey_minimum`, exactly as harbor.

**Baseline (current default search: adjacency-aware seeding + staged, §11.7).**
Reproduce (`URB_NO_OCCLUSION=1`, 20000 evals, staged, `ADJ=1` default):

```bash
URB_NO_OCCLUSION=1 python3 experiments/run_staged_search.py \
  examples/maple-court 20000 <seed> examples/maple-court/init.dom scratch/mc_s<seed>.dom
```

| seed | total fails | best lineage        |
|-----:|------------:|---------------------|
| 0    | **145**     | rotate 0/rrlr       |
| 1    | 158         | core_undivide noop  |
| 2    | 152         | swap 0/rrlllr       |
| mean | **151.7**   |                     |

Each run executed exactly 20000 native evals across 250 topologies (~36 min,
~9.1 evals/s) and re-scored native-consistent (`→ OK`). The best layout (seed 0,
145 fails) was saved as `examples/maple-court/generated.dom` with its `.fails`
(superseded in §12.2 by the proportion-aware 126-fail layout).
The single-stage harness (`run_search_scaled.py`) also accepts the programme
unchanged. The score prints near-zero (`0.5^145` fail cliff) — the **fail count**
is the yardstick.

- *Verdict: benchmark established at mean 151.7 fails (best 145).* As expected for
  a programme ~3× harbor's room count, the absolute fail floor is well above
  harbor's ~85; this is the scaling yardstick `leu.2` (proportion-aware seeding)
  and the re-scoped `9gp` are measured against. The residual character is the same
  geometry/shape family flagged at the close of §11.7.

### 12.2 Proportion-aware constructive seeding (`homemaker-py-leu.2`) — DONE (positive)

Premise (follow-up to §11.6/§11.7). The constructive seeders grow geometry with
uniform `[0.5, 0.5]` cuts *before* types are assigned, so the raw seed is "more,
smaller leaves" of equal area: a room with a large programme target comes out too
small, a small room too big, and the inner loop must recover all of
size/width/proportion from scratch. With the adjacency load now cut by seeding
(§11.6/§11.7), this geometry residual is the dominant remaining term. Attacking it
at the seed — in the proven *construction* direction — is far cheaper than the
`9gp` encoding rewrite.

**Implementation (`operators._size_divisions_from_targets`, flag
`seed_proportion_aware`, env `PROP`, default-on per the A/B below).** After the
adjacency-aware type assignment (§11.6/§11.7, left exactly as is), each leaf
carries a target area — a sized room's programme `size`; circulation/outside
absorb the plot slack (floored at `0.4 ×` mean room area so a circulation leaf
never shrinks below door-width and undoes the §11.6 adjacency win). Because
`division=[f, f]` cuts off left area-fraction `f` (rotation-independent —
verified), bottom-up subtree-target sums compose multiplicatively to give every
leaf area ∝ its target. **Area alone regressed the raw seed**, though: choosing
only the cut *fraction* to hit a target *area* slices thin slivers with terrible
aspect (proportion/width/edge-too-long fails swamp the size gain — measured
below). So each cut also picks the **rotation** (the two distinct cut directions)
that makes its two children squarest; rotation depends on realised parent
geometry, so the pass runs top-down. Both ratio and rotation derive from the
target dims; neither touches topology or type assignment. Threaded through
`driver.search`/`search_staged(seed_proportion_aware=…)`.

- *Raw-seed fails (10 seeds, single-stage constructive, before optimisation),
  area-only vs area+rotation:*

  | family      | harbor before | area-only | area+rot |
  |-------------|--------------:|----------:|---------:|
  | geometry    | 123.0         | 135.9     | **99.9** |
  | access/adj  | 19.1          | 23.8      | 20.4     |
  | total       | 144.1         | 162.1     | **123.7** |

  Area-only makes geometry *worse* (slivers); area+rotation drops the geometry
  family on every programme — harbor **123.0 → 99.9 (−19 %)**, programme-house
  **13.1 → 8.7 (−34 %)**, maple-court **200.5 → 164.1 (−18 %)**. Access/adjacency
  regresses slightly (rotation shifts the leaf graph the adjacency assignment was
  computed against): harbor +1.3, prog-house +2.4, maple +3.4 — far smaller than
  the geometry gain. The size family in particular falls as intended
  (harbor size 31.4 → 22.0), and proportion flips from a regression to a win
  (21.3 → 12.8) once rotation is co-chosen.

- *End-to-end (total fails at budget, 20000 evals, 3 seeds, PROP=0 vs PROP=1;
  harbor & maple-court staged):*

  | seed | harbor PROP=0 | harbor PROP=1 | maple PROP=0 | maple PROP=1 |
  |-----:|--------------:|--------------:|-------------:|-------------:|
  | 0    | 97            | 72            | 145          | 126          |
  | 1    | 78            | 81            | 158          | 148          |
  | 2    | 81            | 69            | 152          | 134          |
  | mean | **85.3**      | **74.0**      | **151.7**    | **136.0**    |

  Harbor **−13 % (best 69, was 78)**, maple-court **−10 % (best 126, was 145)**.
  PROP=0 reproduces the §11.7 staged harbor (85.3) and §12.1 maple baseline
  (151.7) *exactly* — clean controls. Proportion-aware seeding is the first
  Phase-7 lever to move the fail count on the larger-than-house benchmark.

- *A storey-count bug surfaced (`homemaker-py-cq1`).* programme-house has
  `storey_minimum: 2` but all rooms `level: 0`, and `n_storeys_required` only read
  `level:` keys — so the constructive seeder built a **1-storey** seed for a
  2-storey programme and `search_staged` fell through to plain search. Fixed
  (`programme.storey_minimum`/`n_storeys_for`; `driver.search` passes `min_storeys`
  to the seeder; `search_staged` routes on `max(level-derived, storey_minimum)`).
  No-op for harbor/maple (level-derived already ≥ storey_minimum); independent win
  on programme-house (single-stage baseline **8.0 → 5.0** with a correct 2-storey
  seed).

- *programme-house regresses, but it is a convergence-speed artifact, not a worse
  optimum.* On the 6-room programme proportion-aware seeding loses at 20000 evals
  on every path tested (single-stage 1-storey 8.0→11.7, single-stage 2-storey
  5.0→8.3, staged 2-storey 4.3→6.0). The mechanism is a *deeper local optimum*:
  the equal-area PROP=0 seed has badly-proportioned leaves, so `undivide` moves —
  the route to programme-house's simpler optimum — are accepted as improvements;
  the well-fitted PROP=1 seed makes `undivide` an immediate fitness drop (merging
  two good leaves yields one bad one), walling off the restructuring path. A
  budget sweep (staged, storey-fixed) shows this is *reachability speed*, not an
  asymptotic trap:

  | budget | PROP=0 (s0/s1) | PROP=1 (s0/s1) |
  |-------:|---------------:|---------------:|
  | 20000  | 4 / 5          | 8 / 6          |
  | 60000  | 2 / 2          | 4 / 3          |
  | 150000 | 2 / 0          | **1** / 10     |

  PROP=1 reaches **1 fail** (seed 0, 150k — beating PROP=0's 2; best-known is 2),
  so it is not trapped; the gap narrows with budget and crosses over. (Staged
  splits budget by *fraction*, so runs at different budgets evolve different
  Stage-1 bases and are not nested — hence the high variance, e.g. PROP=1 seed 1
  swinging 3→10.) The same "deeper basin" that *helps* where the constructed
  topology is roughly right (large programmes, scarce budget) *delays* convergence
  where the seed must be restructured (small programmes).

- *Verdict: keep proportion-aware split sizing, default-on (`seed_proportion_aware`
  default `True`, env `PROP=1`).* It is a measured win on both larger programmes —
  harbor −13 %, the maple-court scaling benchmark −10 % — exactly the regime
  Phase 7 targets and the basis the re-scoped `9gp` is measured on. The only
  regression is a small-programme convergence-speed effect that washes out with
  budget (PROP=1 reaches the known floor), with no evidence of an asymptotic
  penalty, so default-on is not paid for by a worse optimum anywhere. The win is
  rotation-and-ratio sizing from target dims; the bare ratio is not enough
  (area-only regressed). Area sizing assumes total target ≈ plot area; choosing
  the cut *direction* for aspect is what makes it pay.

### 12.3 Re-scoped 9gp: shape feasibility + reachability moves (`homemaker-py-9gp`)

Re-scoped capstone of the epic (2026-06-19): the original canonical-Polish-
expression rewrite was justified partly by a niching *signature*, but §11.5
falsified niching and `genome.signature` already supplies the cheap stand-in. The
two surviving, evidence-supported parts are landed here as operators on the
existing decoded `Node` tree — **no** Polish-expression rewrite — each measured
independently against the §12.2 leu.2 baseline (maple-court staged 136.0, harbor
74.0). A true canonical encoding is revisited only if the M3 measurement proves
associativity valuable at scale.

**9gp.1 — shape-feasibility pre-filter (scaling lever).** `operators.
predicted_shape_fails(root, reqs, fit)` lays a topology out at its proportion-
aware target geometry (reusing `_size_divisions_from_targets`, §12.2 — the
squarest layout the inner loop warm-starts from) and counts the
size/width/proportion/crinkliness fails the native fitness reports: a cheap
lower-bound proxy for the best shape the topology can reach. `driver._evaluate`
calls it *before* the inner loop and **prunes** (1 feasibility eval instead of
~80 inner-loop evals) when the predicted shape fails both exceed a tunable
threshold *and* are ≥ the incumbent's total fails — the second guard makes the
proxy safe (a topology whose shape floor is still below the incumbent is never
discarded). Pruned individuals are tagged `pruned/…`, counted as explored
topologies but never bred from or ranked, so budget flows to feasible topologies.
Seed/bootstrap/restart batches are never filtered (construction invariants must
survive). Threaded as `search(…, feasibility_filter, feasibility_max_shape_fails)`
through `search_staged`; **default OFF** so the §12.2 controls reproduce exactly
(`test_feasibility_filter_off_matches_baseline`). Env: `FEAS=1 MAXSHAPE=<n>`.

**9gp.2 — M3 Wong-Liu re-association move (reachability lever).** `operators.
mutate_reassociate` adds the associativity move `(a|b)|c ↔ a|(b|c)` on two
**same-orientation** live cuts (both directions, for reversibility): a pure-
topology move that preserves the leaf set and types but reaches tree shapes the
existing set cannot. M1 (operand swap) is `mutate_swap` and M2 (single-cut
orientation complement) is `mutate_rotate`; associativity was the missing
canonical-slicing move attacking the reachability bottleneck §11.4/§11.5 both
fingered. Only live cuts (`below is None`, as `mutate_rotate`) are restructured,
so dead inherited fields are untouched and `encode` re-anchors deltas; the two
restructured cuts default to `0.5` and the inner loop recovers their ratios.
Registered in `MUTATIONS`; **default OFF** via `enable_reassociate` (forces its
mutation weight to 0 so the baseline is byte-identical). Env: `REASSOC=1`.

- *Implementation status (this session):* both land with unit tests
  (`tests/test_operators.py`: reassociate preserves the leaf multiset, changes
  the signature, noops on perpendicular cuts, stays canonical on the harbor
  corpus; `predicted_shape_fails` is non-negative, pure, deterministic.
  `tests/test_driver.py`: filter-off reproduces the baseline trajectory;
  filter-on prunes at 1 eval/topology and never admits a pruned individual).
  Full suite green (211 passed). A short smoke run on maple-court confirms both
  paths execute under the real native fitness.

- *Calibration (predicted shape-fail floor of the constructive seeds).* Over 8
  proportion-aware constructive seeds, `predicted_shape_fails` is maple **121–163
  (mean 135.6)** and harbor **72–90 (mean 84.6)** — essentially equal to the final
  *achieved* total fail counts (maple 126–148, harbor 69–81). So the shape floor at
  the best achievable geometry already accounts for almost the whole residual:
  independent confirmation of §11.7 that the Phase-7 residual is geometry/shape-
  bound. `MAXSHAPE` was set below the incumbent range (maple 100, harbor 55) so the
  `pred ≥ incumbent` safety guard is the dominant prune gate (`experiments/
  run_9gp_ab.sh`).

- *A/B sweep (DONE — negative). maple-court + harbor, seeds 0/1/2, 20000 evals,
  staged, total fails at budget:*

  | programme   | seed | baseline | reassoc | feas | combined |
  |-------------|-----:|---------:|--------:|-----:|---------:|
  | maple-court | 0    | **126**  | 131     | 129  | 131      |
  | maple-court | 1    | **148**  | 141     | 151  | 142      |
  | maple-court | 2    | **134**  | 146     | 140  | 144      |
  | maple-court | mean | **136.0**| 139.3   | 140.0| 139.0    |
  | harbor      | 0    | **72**   | 83      | 82   | 81       |
  | harbor      | 1    | **81**   | 81      | 80   | 81       |
  | harbor      | 2    | **69**   | 70      | 69   | 70       |
  | harbor      | mean | **74.0** | 78.0    | 77.0 | 77.3     |

  The baseline controls reproduce the §12.2 leu.2 means **exactly** (maple 136.0,
  harbor 74.0) — a clean control, so the negative is real. Every variant is
  neutral-to-slightly-worse on every programme: reassoc +3.3/+4.0, feas +4.0/+3.0,
  combined +3.0/+3.3 (maple/harbor). The feasibility filter *did* prune and explore
  more topologies in several runs (maple s1/s2 combined 342/319, s2 feas 317 vs the
  baseline 250) — but the extra topologies did not lower the fail count, and M3
  reassociate never produced a win despite reaching new tree shapes.

- *Verdict: keep both default-OFF; the Phase-7 residual is NOT reachability- or
  feasibility-bound.* This is the third independent negative on **search machinery**
  (§11.4 graded objective, §11.5 niching+restarts, now §12.3 M3 moves + shape
  pruning), against four positives all from **construction/seed quality** (§11.2,
  §11.6, §11.7, §12.2). The associativity move reaches new topologies but they are
  not better; the shape filter saves budget on topologies whose shape floor already
  matches the incumbent, but — precisely because the floor ≈ the achieved total
  (calibration above) — there is no lower-fail basin for that saved budget to find.
  The geometry/shape residual is intrinsic to the *constructed* layouts, not a
  search-reachability deficit. A full canonical Polish-expression rewrite is **not**
  justified: its one measurable promise here (associativity reachability) was tested
  directly and did not pay.

- *Residual diagnostic (where the shape fails actually live, maple-court, 6
  constructive seeds).* A per-leaf breakdown — to test, not assume, what the next
  lever would be — overturns the obvious "shape-aware placement" guess:

  | signal | measured | reading |
  |---|---|---|
  | plot utilisation (target/plot area) | **0.44** (0.28–0.54) | NOT density/area-bound — ample slack |
  | failing leaves / total | **~68 / 73** | shape fails are *uniform*, not concentrated |
  | dominant factors | **crinkliness 346, size 242**, proportion 121, width 102 | perimeter/area + undersize, both granularity effects |

  Because nearly *every* leaf fails (not a few mismatched ones), the residual is
  **not** a room→leaf placement mismatch — there are no well-shaped leaves to place
  demanding rooms into. The mechanism is **over-granular construction**: 73 small
  leaves for 52 rooms at 44 % utilisation gives every leaf a high perimeter/area
  ratio (crinkliness) and rooms below their target area (size). So the measured
  candidate lever is construction **granularity / leaf shape** (fewer, larger
  leaves; merge or share leaves across same-class rooms; a coarser spine), NOT
  shape-aware placement and NOT more search machinery. This is a *hypothesis with a
  measured motivation*, filed as **`homemaker-py-c3g`** — it is unproven and must be
  A/B'd against the §12.2 baseline before adoption, same discipline as every lever
  above. It may also be that 52 distinct rooms simply cannot be well-shaped as 52
  leaves at this density, i.e. the residual is the geometry floor of the slicing
  representation; the experiment is what decides.

### 12.4 Construction granularity A/B (`homemaker-py-c3g`) — DONE (null) + a noise finding

The c3g hypothesis tested directly. The cheap **raw-seed probe** (circ-per-room
divisor `circ_divisor`, env `CIRCDIV`, default 3) confirmed the mechanism but also
its catch: a coarser spine lowers the **shape** floor (maple 135→110, harbor 83→66
as `div` 3→∞) yet raises **access/adjacency** by as much, leaving the raw **total**
floor flat-to-worse (maple 198→210, harbor 121→134). `div=3` already sits near the
total-floor minimum. Because §12.3 showed shape is the *hard* residual and
access/adjacency are *cheap* to repair, the open question was whether that trade
pays **end-to-end**.

- *End-to-end A/B (20000 evals, staged, total fails at budget; div=3 reuses §12.3):*

  | programme   | div=3 (baseline) | div=6        | div=8     |
  |-------------|-----------------:|-------------:|----------:|
  | maple-court | **136.0**        | 137.0        | 134.3     |
  | harbor      | **74.0**         | 75.3         | —         |

  Per-seed: maple div6 143/122/146, div8 132/138/133; harbor div6 65/76/85. **Every
  arm is within ±1.7 of baseline** — inside the noise floor (below) — with a huge
  per-seed spread (maple div6 122–146). *Null result:* coarsening the spine does not
  pay end-to-end. The raw-probe prediction held — the shape-floor gain is cancelled
  by access/adjacency damage that is *not* free to repair after all.

- *A reproducibility finding surfaced en route (`homemaker-py-xcy`, P2 bug) —
  later RE-DIAGNOSED and FIXED (2026-06-22).* The `div=3` control gave **129** vs
  §12.3's **126** for the same maple seed 0. The first diagnosis blamed
  `operators._assign_adjacency_aware` iterating `id()`-ordered Python sets of
  `Node`s — **this was wrong.** That function already ends every `max`/`min` with a
  unique leaf-`idx` tiebreak, and its set unions are used only for membership, so
  order never leaks: `constructive_topology(seed=0)` is **byte-identical across
  processes** for every example programme (stable sha1, e.g. maple `e688f744326b`).
  The "sig hashes 4480 vs 16064" was a **measurement artifact** — Python's builtin
  `hash()` of a *string* is salted per process (`PYTHONHASHSEED`), so an *identical*
  signature hashes to different ints run-to-run (reproduced 51920/5342/59970 for one
  identical string). Use `genome.signature` equality or a stable hash, never builtin
  `hash()`, to compare topologies.
  The **real** cause was parallel-only: `driver._run_batch` admitted futures via
  `concurrent.futures.as_completed`, i.e. in **completion order**, and `admit()` is
  order-sensitive (accrues `n_evals` per result; keeps the *first* individual of an
  equal-key tie as `best`). A long parallel run diverged **167 vs 161 fails** (maple
  seed 0) — the true source of the ±3..6 "noise". **Fix:** iterate the futures in
  *submission* order (`for f in futs: f.result()`; all still run concurrently),
  reproducing the serial admission sequence. After the fix two `workers=4` runs are
  byte-identical (162 fails). Serial (`workers=1`) was already byte-for-byte
  reproducible.
  Implication for the §11/§12 ledger: per-seed numbers are reproducible **only at a
  fixed worker count**. Serial≠parallel is *expected* (children/iteration = 1 vs
  `n_workers` changes batch granularity, hence the search), not nondeterminism. Any
  A/B that compared runs at *different* worker counts — or any pre-fix parallel run —
  conflated this with a real effect; sub-±3 effects (the §12.3 +3-4 negatives, the
  §12.4 ±1.7) should be re-run at a single fixed worker count before being trusted as
  magnitudes.

- *Verdict: keep `circ_divisor=3` default; the granularity lever is null.* Together
  with §12.3 this closes the residual-reduction question for now from both sides:
  neither search machinery (§12.3) nor construction granularity (§12.4) moves the
  maple/harbor geometry residual beyond noise. The weight of evidence is that the
  residual is the **geometry floor of the slicing representation** at this room
  density — 52 distinct rooms as 52 adjacency-connected leaves inherently incur
  ~135 shape+access fails. Further progress, if wanted, needs either the
  determinism fix (to even see sub-±3 effects) or a representational change beyond
  the slicing tree — not another seed/search tweak at this scale.

## 13. Phase 8 — lowering the geometry/shape floor (`homemaker-py-erc`)

Phase 8 runs DIAGNOSTICS FIRST to decide *which* floor-lowering lever to invest
in, then the construction/inner-loop experiments in dependency order. §12.3/§12.4
established the floor is real (search machinery and circulation-granularity both
null); the open question is *what about the floor* — per-leaf slicing tax, or
fixable cuts — and *where the slack hides* (util 0.44 yet rooms undersize).

### 13.1 Diagnostic A: per-leaf shape-fail vs density/granularity (`homemaker-py-erc.1`) — DONE

GATES leaf-sharing (`erc.3`) vs compactness-cuts (`erc.5`). Reads only; no A/B, no
baseline reproduction. Builds the §12.2 constructive seed (adjacency- and
proportion-aware), lays it out at the proportion-aware TARGET geometry — the
squarest geometry the inner loop warm-starts from, exactly as
`operators.predicted_shape_fails` — then counts size/width/proportion/crinkliness
fails per leaf. Script: `experiments/diag_leaf_shapefail.py` (seeds 0/1/2).

*View 1 — cross-programme density sweep* (per-leaf rate = shape-fails ÷ leaves):

| programme        | rooms | leaves | l/room | util | shape | /leaf | siz/lf | wid/lf | prp/lf | crk/lf |
|------------------|------:|-------:|-------:|-----:|------:|------:|-------:|-------:|-------:|-------:|
| programme-house  |   6   |   9.0  | 1.50   | 0.83 |   8.0 | 0.889 | 0.000  | 0.519  | 0.222  | 0.148  |
| harbor-house-l0  |  13   |  13.0  | 1.00   | 0.31 |  19.0 | 1.462 | 0.231  | 0.154  | 0.487  | 0.590  |
| harbor-house     |  37   |  45.0  | 1.22   | 0.50 |  87.3 | 1.941 | 0.519  | 0.378  | 0.296  | 0.748  |
| maple-court      |  52   |  73.0  | 1.40   | 0.54 | 134.3 | 1.840 | 0.562  | 0.224  | 0.251  | 0.804  |

Per-leaf shape-fail SATURATES at ~1.8–1.9 once the programme is non-trivial: the
tiny 6-room case is the only outlier (0.89, no size fails, high util 0.83), and
the three larger programmes cluster at 1.46→1.94 with no dependence on
leaves-per-room (which barely moves, 1.0–1.5). Cross-programme "density" here is
confounded by plot/room-mix/util (util swings 0.31→0.83), so this view alone
cannot separate "intrinsic per-leaf tax" from "more leaves, worse cuts".

*View 2 — synthetic granularity sweep, maple-court, room set FIXED, leaf count
varied via the c3g `circ_divisor` knob* (the controlled test):

| circ_div | leaves | l/room | util | shape | /leaf | siz/lf | wid/lf | prp/lf | crk/lf |
|---------:|-------:|-------:|-----:|------:|------:|-------:|-------:|-------:|-------:|
|     2    |  81.0  | 1.56   | 0.46 | 139.0 | 1.716 | 0.477  | 0.169  | 0.226  | 0.844  |
|     3    |  73.0  | 1.40   | 0.54 | 134.3 | 1.840 | 0.562  | 0.224  | 0.251  | 0.804  |
|     4    |  68.0  | 1.31   | 0.44 | 126.7 | 1.863 | 0.495  | 0.294  | 0.289  | 0.784  |
|     6    |  65.0  | 1.25   | 0.47 | 126.0 | 1.938 | 0.554  | 0.303  | 0.262  | 0.821  |
|     9    |  63.0  | 1.21   | 0.50 | 116.3 | 1.847 | 0.481  | 0.280  | 0.339  | 0.746  |

With the programme held fixed, the per-leaf shape-fail rate is **FLAT** as leaf
count varies (1.72–1.94, no monotone trend; if anything a slight *rise* as you
coarsen, since the survivors are bigger but still fail). Crucially **TOTAL shape
fails track leaf count almost linearly** (139 → 116 as leaves 81 → 63), and
crinkliness — the dominant factor (crk/lf ≈ 0.75–0.84) — is itself flat per leaf.
Each leaf carries a roughly fixed ~1.8 shape-fail tax regardless of how finely the
*same plot* is sliced. The target layout already picks the squarest-aspect cut
direction (`_size_divisions_from_targets` chooses rotation for squarest children),
so leaves are already near-optimally shaped and STILL fail at ~1.8/leaf — there is
little compactness headroom left to recover at fixed leaf count.

**VERDICT — per-leaf shape-fail is FLAT vs slicing density (controlled view 2) →
the floor is INTRINSIC to per-leaf slicing, not to cut quality.** By the
diagnostic's decision rule this *prioritises leaf-sharing* (`erc.3` — fewer leaves
for the same rooms is the only lever that moves the floor) and *deprioritises
compactness-aware cuts* (`erc.5` — cuts are already squarest and still pay the
tax; little headroom at fixed count). Note this is *not* the §12.4 `circ_divisor`
null: that lever removed CIRCULATION leaves and the shape gain was cancelled by
access/adjacency damage; leaf-sharing removes ROOM-leaf count (multi-room leaves)
without disturbing the circulation spine, so the access penalty that killed c3g
need not apply. Recommendation: close/deprioritise `erc.5`, advance `erc.3`.

### 13.2 Diagnostic B: undersize-despite-slack localization (`homemaker-py-erc.2`) — DONE

GATES plot-fill construction (`erc.4`) vs the inner-loop slack-expansion term
(`erc.6`). The §12.3 paradox: plot utilisation ≈ 0.44 (over half the plot
"empty") yet rooms are UNDERSIZE. Where is the slack stranded, and at which stage
should it be spent? Reads only. Builds the §12.2 constructive seed (whose
geometry already sits at the proportion-aware TARGET ratios — the inner-loop warm
start, so it *is* the "before" state), measures per sized-room leaf achieved-vs-
target area and a plot accounting, then runs `innerloop.optimise` (nm, budget 80
= the bootstrap child budget) and re-measures. Script:
`experiments/diag_slack_localization.py` (harbor-house + maple-court, seeds 0/1/2).

| programme    | state            | sizeF | util | tgtFill | ā/t | %und | %ovr | sized% | circ% | out% |
|--------------|------------------|------:|-----:|--------:|----:|-----:|-----:|-------:|------:|-----:|
| harbor-house | BEFORE (target)  | 23.3 | 0.50 | 0.50    |1.43 |  43  |  12  |   50   |  46   |  4   |
| harbor-house | AFTER (innerloop)| 21.7 | 0.49 | 0.50    |1.40 |  54  |  16  |   49   |  46   |  4   |
| maple-court  | BEFORE (target)  | 41.0 | 0.54 | 0.44    |1.46 |  42  |  15  |   54   |  43   |  3   |
| maple-court  | AFTER (innerloop)| 37.3 | 0.53 | 0.44    |1.46 |  42  |  19  |   53   |  44   |  3   |

(util = sized-room area ÷ plot; tgtFill = Σ room targets ÷ plot; ā/t = mean
achieved/target over sized leaves; %und/%ovr = leaves below 0.9× / above 1.1×
target.)

**The "56 % empty plot" is a misreading.** Sized rooms already occupy ~50–54 %
of the plot and hold **1.4–1.5× their aggregate target area** (util > tgtFill);
the other ~46 % of the plot is **circulation**, not claimable void (out/uncovered
is only 3–4 %). So rooms are *over*-provisioned in total — there is no unused plot
to hand them.

**The size fails are pure MALDISTRIBUTION, set by SLICING POSITION not by need.**
The median room sits right at target (a/t ≈ 1.0), but a long undersize tail
(p25 ≈ 0.35, min 0.05) starves while a few giant leaves balloon (max **6.8×**
harbor, **14.7×** maple). Decisively, *the same room type with the same target
lands at both extremes* — harbor `r` (target 10 m²) appears at 68 m² (6.8×) and
2.3 m² (0.23×); maple `n` (target 60 m²) appears near target and at 2.7 m²
(0.05×). A leaf's area is dictated by its depth/position in the binary slicing
tree (ratios multiply down the ancestry), essentially independent of its target;
`_size_divisions_from_targets` sets each *local* cut proportionally but cannot
defeat the multiplicative depth effect. This is the same root cause as §13.1 (the
binary-slicing structure), now seen on the size axis.

**The inner loop cannot repair it.** Over budget 80 the size fails move only
−1.6 (harbor) / −3.7 (maple), util is flat-to-down, and %undersize is flat-to-
*worse* (43→54 harbor). On a frozen topology the equal-offset ratio DOF cannot
shrink a 14× leaf to feed a starved one without trading into shape fails (the
0.5ⁿ cliff, §4.5, blocks it), and the symmetric size Gaussian (`quality_size` is
`gaussian(area, 1, target, σ)`) gives no net reward for redistribution.

**VERDICT — the slack is depth-driven maldistribution inside the room set, not
unclaimed plot, and the inner loop (frozen-topology ratios) provably cannot move
it.** This *falsifies plot-fill construction* in the "claim the empty plot" sense
(`erc.4` as scoped — rooms are already 1.4× over aggregate target; the empty-
looking plot is circulation) and *deprioritises the inner-loop slack-expansion
term* (`erc.6` — wrong DOF: ratios on a frozen tree cannot undo a depth-set 14×
leaf, and the blocker is position not a missing expansion reward). The fix must
live UPSTREAM of the inner loop, where leaf area is actually decided: construction
that balances tree DEPTH so equal-target rooms land at comparable depth / caps
giant leaves (re-scope `erc.4` from "plot-fill" to **depth-balanced / giant-
splitting construction**), reinforcing §13.1's call to advance leaf-sharing
(`erc.3`) for the starved tail. Recommendation: re-scope `erc.4`, deprioritise
`erc.6`.

### 13.3 Experiment: leaf-sharing / multi-room leaves (`homemaker-py-erc.3`) — DONE

The lever §13.1 named as the *only* one that moves the floor: collapse same-code
rooms into fewer, larger **shared** leaves so the per-leaf ~1.8 shape tax is paid
once per group instead of once per room. Unlike c3g (§12.4) this removes
ROOM-leaf count, not circulation, so the access/adjacency penalty that sank c3g
need not apply.

**Mechanism — explicit, type-guarded per-leaf multiplicity.** A construction
stamps `leaf.share = k` and `leaf.share_type = code` on each shared leaf
(`operators._share_rooms` groups a sized, multi-instance code into runs of ≤ `N`
= `leaf_share_factor`; `_leaf_mult_from_plan` stamps the survivors and
`_size_divisions_from_targets` sizes them to `k × target`). The fitness honours
`k` only while `leaf.type == leaf.share_type` (`graph.leaf_share`), so any
retype/undivide silently invalidates a stale share — the mutation operators need
no resets, and a small leaf can never *retype* its way into claiming rooms it
does not provide. Two scoring sites, both gated by a default-OFF `leaf_sharing`
key (controls reproduce the §12.2 baseline exactly — 214 tests pass with it off):
- `graph.check_space_counts` counts **coverage** (Σ per-leaf `k`) against
  `req.count`, so one shared leaf satisfies several same-code rooms with no
  missing fail;
- `fitness.quality_size` centres the size Gaussian on `k × target` (σ scaled by
  `k`). `quality_proportion`/`quality_width` need no change — a
  proportionally-scaled leaf keeps its aspect and only gets wider.

*Design history:* the first cut recovered `k` from area
(`round(area/target)`) to avoid genome state, but the §13.2 depth
maldistribution left shared leaves below `k × target`, so `round` undercounted
and **17–44 missing fails leaked back** (harbor `share3`+il: 87.3 total, 16.7
missing; the inner loop could not close it — frozen-topology ratios, §13.2).
Switching to **explicit** `share` (an undersize shared leaf is *present* → a
light size fail, not a heavy missing fail) closes the leak. Because the phenotype
tree is never rebuilt from the genome in the hot path (`genome.decode` is unused;
operators edit `dom.Node` trees in place), the two `Node` fields survive the whole
search via deepcopy without threading through `GNode`/encode/decode; `.dom`
serialisation emits `share` only on a live shared leaf.

**Floor probe** (`experiments/diag_leaf_sharing.py`, harbor + maple, seeds 0/1/2)
— build the §12.2 seed both ways, score at the seed geometry and again after
`innerloop.optimise` (nm, budget 80) under the *same* objective. Averaged fails:

| programme | mode        | leaves | total | missing | size | crink |
|-----------|-------------|-------:|------:|--------:|-----:|------:|
| harbor    | OFF +il     |  45.0  | 120.3 |   0.0   | 21.7 | 33.7  |
| harbor    | share2 +il  |  31.7  |  86.0 |   0.0   | 15.3 | 22.0  |
| harbor    | share3 +il  |  25.7  |  73.3 |   0.0   | 12.7 | 17.7  |
| maple     | OFF +il     |  73.0  | 194.7 |   0.0   | 37.3 | 58.3  |
| maple     | share2 +il  |  52.0  | 145.7 |   0.0   | 25.7 | 41.3  |
| maple     | share3 +il  |  47.0  | 133.0 |   0.0   | 21.0 | 39.3  |

**The floor moves and the leak is closed** — `share3` cuts the achievable floor
**−39 % harbor (120.3 → 73.3) / −32 % maple (194.7 → 133.0)** with **zero missing
fails**, and the missing did *not* re-emerge as size fails (size still falls,
22→13 harbor / 37→21 maple). The drop is exactly where §13.1 predicted: shape
factors fall with leaf count (harbor leaves 45→26, crinkliness 34→18). Larger
`leaf_share_factor` helps monotonically here (share2 → share3), bounded by
`leaf_share_max` (default 4).

**Verdict — leaf-sharing is the floor-mover §13.1/§13.2 called for: −32…−39 % on
the achievable floor, no missing-fail leak.** The flag is threaded through the
staged driver (`driver.search`/`search_staged` → `constructive_topology` /
`lift_base_to_storeys`) and exposed for the A/B via `LEAFSHARE`/`LEAFSHAREFAC` in
`run_staged_search.py` (which injects the objective into the inner-loop and
final-score fitness, both arms on one programme dir). Smoke-tested end-to-end
(harbor, staged, leaf_sharing+factor 3: re-score OK).

**End-to-end A/B** (`experiments/run_leafshare_ab.sh`, staged search, 20 000
native evals, seeds 0/1/2, `leaf_share_factor=3` vs the default-OFF baseline,
final native re-score):

| programme | baseline (s0/1/2) | mean | leaf-share f3 (s0/1/2) | mean | Δ |
|-----------|-------------------|-----:|------------------------|-----:|------:|
| maple-court  | 129 / 148 / 134 | 137.0 | 78 / 89 / 92 | 86.3 | **−37 %** |
| harbor-house |  72 /  81 /  69 |  74.0 | 50 / 52 / 49 | 50.3 | **−32 %** |

**VERDICT — leaf-sharing is the first lever to move the Phase-8 floor, and it
moves it decisively: −37 % maple / −32 % harbor end-to-end.** The default-OFF
baseline arm reproduces §12.2 exactly (maple 137.0 vs 136.0, harbor 74.0 vs
74.0), so the gap is the lever, not drift; and the separation is total — *every*
share run beats *every* baseline run on the same programme (maple worst-share 92
< best-baseline 129; harbor 52 < 69). Fewer leaves also make each eval cheaper,
so the share arm runs ~35 % faster at equal budget. This is the §13.1/§13.2
prediction realised: the per-leaf ~1.8 shape tax is intrinsic, so collapsing
52→47 / 45→26 room-leaves is what lowers the floor — and the explicit
type-guarded multiplicity (vs the area-derived first cut) is what lets the gain
survive without a missing-fail leak. Scoreboard update: this is the **5th** win
from construction/seed quality and the first floor-mover of Phase 8; it confirms
§12.3's thesis that only lowering the geometry floor (not search machinery) can
help. Follow-ups: surface `leaf_sharing` on the `homemaker-evolve` CLI / as a
`patterns.config` key for production use, sweep `leaf_share_factor`/`max_share`,
and test the `erc.4` depth-balancing synergy (shared leaves at correct absolute
area) now that the leak is closed.

### 13.4 Experiment: depth-balanced construction (`homemaker-py-erc.4`) — DONE (modest)

The lever Diagnostic B (§13.2) called for. B localized the size fails to
depth-driven **maldistribution**: a leaf's area is the product of cut fractions
down its ancestry in the binary slicing tree, so the same-target room lands at
0.05× and 14.7× by *slicing position*, and the inner loop (frozen topology)
provably cannot move it. The fix must live in construction, where leaf area is
decided.

**Mechanism — depth-balanced tree growth.** `_grow_leaves` grew the tree by
splitting a *random* leaf each step → a random caterpillar whose leaves sit at
wildly different depths. The `depth_balanced` flag instead always splits a
*shallowest* current leaf (`operators._leaves_with_depth`), growing a
near-complete binary tree so all leaves land at comparable depth. The
proportion-aware sizing pass (`_size_divisions_from_targets`) then hits each
target with cut fractions near their proportional value instead of compounding
`fmin`/`fmax` clamp error down a deep spine. Type-agnostic and topology-only — it
changes *which* leaf is split, not the type assignment or the proportional sizing
— so it composes with adjacency-aware seeding and leaf-sharing unchanged. Default
OFF (214 tests pass with it off); threaded through `constructive_topology` /
`lift_base_to_storeys` → `driver.search`/`search_staged`, exposed via `DEPTHBAL`
in `run_staged_search.py`.

**Floor probe** (`experiments/diag_depth_balance.py`, harbor + maple, seeds
0/1/2) — build the §12.2 seed OFF vs balanced (vs balanced+share3 as the `erc.7`
preview), score at the seed geometry and after `innerloop.optimise` (nm, budget
80). `dDep` = leaf-depth spread (max−min); `maxR`/`minR` = max/min achieved/target
over sized leaves; `%und` = fraction below 0.9×target. Averaged:

| programme | mode        | leaves | total | size | crink | %und | maxR | minR | dDep |
|-----------|-------------|-------:|------:|-----:|------:|-----:|-----:|-----:|-----:|
| harbor    | OFF +il     |  45.0  | 120.3 | 21.7 | 33.7  | 54.2 | 12.0 | 0.1  | 7.0  |
| harbor    | bal +il     |  45.0  | 106.0 | 21.0 | 31.3  | 25.0 |  8.3 | 0.2  | 1.0  |
| harbor    | bal+sh3 +il |  25.7  |  65.3 | 11.7 | 17.3  | 29.0 |  4.1 | 0.3  | 1.0  |
| maple     | OFF +il     |  73.0  | 194.7 | 37.3 | 58.3  | 42.3 | 16.4 | 0.0  | 6.7  |
| maple     | bal +il     |  73.0  | 173.0 | 37.3 | 61.7  | 22.4 |  6.2 | 0.2  | 1.0  |
| maple     | bal+sh3 +il |  47.0  | 113.7 | 22.3 | 38.7  | 17.7 |  7.9 | 0.4  | 2.0  |

**The depth spread collapses (7→1) and the giant leaf is tamed** — maxR 12.0→8.3
harbor / 16.4→6.2 maple, %undersize 54→25 / 42→22 — at **equal leaf count** (45 /
73, no rooms removed). The achievable floor drops **−12 % harbor (120.3→106.0) /
−11 % maple (194.7→173.0)** purely from tree *shape*, with zero missing-fail
leak. Most of the total drop is in width/proportion (the giants were the wide,
wrong-aspect leaves), not the soft size Gaussian (size barely moves). Crucially
it is **additive with leaf-sharing**: `bal+sh3` beats §13.3's `share3`-alone floor
(harbor 65.3 vs 73.3, maple 113.7 vs 133.0) — balancing places the *survivors* of
sharing at correct absolute area, exactly the synergy `erc.7` was filed for.

**End-to-end A/B** (`experiments/run_depthbal_ab.sh`, staged search, 20 000 native
evals, seeds 0/1/2, `DEPTHBAL=1` vs default-OFF baseline, leaf-sharing OFF in both
arms, final native re-score):

| programme | baseline (s0/1/2) | mean | depth-bal (s0/1/2) | mean | Δ |
|-----------|-------------------|-----:|--------------------|-----:|------:|
| maple-court  | 129 / 148 / 134 | 137.0 | 142 / 126 / 119 | 129.0 | **−5.8 %** |
| harbor-house |  72 /  81 /  69 |  74.0 |  67 /  77 /  71 |  71.7 | **−3.2 %** |

**VERDICT — depth-balancing is a real but MODEST standalone lever: −5.8 % maple /
−3.2 % harbor, much smaller than the −11/−12 % the seed-floor probe predicted, and
the arms OVERLAP** (maple balanced worst 142 > baseline best 129; harbor balanced
77 > baseline 69) — *not* the total separation leaf-sharing showed (§13.3, every
share run beat every baseline). The default-OFF baseline reproduces §12.2 exactly
(maple 137.0 vs 136.0, harbor 74.0 vs 74.0), so the comparison is clean and the
small gap is the lever, not drift. **The 20k search erodes most of the seed-floor
advantage**: the random-caterpillar arm partly catches up via divide/undivide
mutations over the budget, so an 11 % lower *seed* floor realises only ~5 % at
convergence. This is the mirror image of the §12.3/§11 thesis — seed quality
helps, but here the search recovers enough of the gap that depth-balance *alone*
is marginal, unlike the structural leaf-count cut of §13.3 which the search cannot
undo (you cannot mutate 26 leaves back up to 45 cheaply).

Its real promise is the **additive floor with leaf-sharing**: the probe showed
`bal+sh3` beats `share3`-alone by a wide margin (harbor 65.3 vs 73.3, maple 113.7
vs 133.0) because balancing places the *survivors* of sharing at correct absolute
area. The decisive end-to-end test is therefore `erc.7` (depth-balance ×
leaf-sharing synergy + factor sweep), not depth-balance in isolation.
Recommendation: keep `depth_balanced` (default OFF, no test/runtime cost, same
leaf count), advance `erc.7` to test whether the additive seed floor survives to
convergence when stacked on the share lever that the search *cannot* erode.
Scoreboard: a 6th construction/seed lever, but the first Phase-8 lever whose
end-to-end gain is *materially* smaller than its seed-floor gain — a useful
calibration of how much seed-floor reduction the staged search actually banks.

### 13.5 Experiment: leaf-sharing × depth-balancing synergy (`homemaker-py-erc.7`) — DONE (synergy confirmed)

The decisive test the §13.4 floor probe set up. Depth-balancing was only MODEST
standalone (§13.4: −5.8 % maple / −3.2 % harbor, overlapping arms) because the
20k search erodes a tree-shape seed advantage via divide/undivide. But the probe
showed `bal+sh3` beats `share3`-alone at **equal leaf count** (harbor 65.3 vs
73.3, maple 113.7 vs 133.0) — additive on the leaf-COUNT cut the search *cannot*
erode (you cannot mutate 26 leaves back up to 45 cheaply). Question: does that
additive seed-floor advantage survive to convergence once stacked on the share
lever that the search can't undo?

**Setup** (`experiments/run_synergy_ab.sh`, staged search, 20 000 native evals,
seeds 0/1/2, final native re-score). Both arms hold `LEAFSHARE=1` at factor 3 (the
§13.3 winner). The control arm is share-alone (`DEPTHBAL=0`) and must reproduce
§13.3; the experiment arm adds `DEPTHBAL=1` (depth-balanced grow). One programme
dir per programme — `run_staged_search.py` injects `leaf_sharing` into the whole
pipeline so both arms score under the same relaxed objective.

| programme | share-alone db0 (s0/1/2) | mean | bal+share db1 (s0/1/2) | mean | Δ |
|-----------|--------------------------|-----:|------------------------|-----:|------:|
| maple-court  | 78 / 89 / 92 | 86.3 | 76 / 85 / 86 | 82.3 | **−4.6 %** |
| harbor-house | 51 / 52 / 49 | 50.7 | 41 / 41 / 38 | 40.0 | **−21.1 %** |

The control arm reproduces §13.3 exactly (maple 86.3 = 86.3, harbor 50.7 ≈ 50.3),
so the comparison is clean and the gap is the lever, not drift.

**VERDICT — the synergy is REAL and SURVIVES to convergence, unlike depth-balance
alone.** Harbor is **decisive**: −21 %, every seed improves by 10–11 fails, and the
arms are **non-overlapping** (bal+share worst 41 < share-alone best 49) — the total
separation §13.4-standalone never reached. Maple is **modest but uniform**: −4.6 %,
every seed improves (−2 / −4 / −6), ranges overlapping. This is the mirror image of
§13.4: there the seed-floor advantage washed out because the search could erode
tree *shape*; here depth-balancing rides on top of the leaf-COUNT cut that the
search cannot erode, so balancing the survivors of sharing onto their correct
absolute k×target area banks. The probe prediction held — `bal+sh3` beats
`share3`-alone end-to-end, not just at the seed.

**Factor sweep** (`experiments/run_sharefactor_sweep.sh`, `leaf_share_factor` 2/4
under bal+share, seeds 0/1/2, vs the factor-3 bal+share above):

| programme | factor 2 | factor 3 | factor 4 |
|-----------|---------:|---------:|---------:|
| maple-court  | 92.7 | **82.3** | 83.3 |
| harbor-house | 53.0 | 40.0 | **39.7** |

**Factor 3 confirmed as the robust default once depth-balancing is stacked.**
Factor 2 regresses on both (maple +10.4, harbor +13.0) — too little sharing leaves
more, smaller rooms for the depth-balance to fix. Factor 3 and 4 are statistically
tied (maple f3 wins by 1.0, harbor f4 wins by 0.3 — both inside seed noise, ranges
overlap), so factor 4 buys nothing material and gives up maple while risking larger
shared leaves. `leaf_share_max` (scoring cap, default 4) already credits every
multiplicity at factor ≤4 with zero missing-fail leak (final re-score OK in all
runs), so it needs no separate sweep at the chosen factor 3.

Recommendation: make `depth_balanced` + `leaf_sharing` (factor 3) the default
Phase-8 stack (both default OFF today, no test/runtime cost). Scoreboard: the first Phase-8 lever *combination* whose end-to-end gain (harbor
−21 %) exceeds either lever alone (share −32 %→ this stacks a further −21 % on top;
depth-balance −3 % alone), confirming the §13.4 thesis that levers the search
cannot erode compound where shape levers do not.

### 13.6 Experiment: interior-O courtyard / light-well seeding (`homemaker-py-ld2`) — DONE (positive on dense floors)

The construction lever aimed at the erc crinkliness residual directly. The
adjacency-aware seeder placed ONE `O` on the most PERIPHERAL leaf — where the
adjacent rooms already have plot facade, wasting the daylight source — while the
landlocked rooms (no facade, no uncovered-`O` neighbour → `area_outside` ≈ 0 →
crinkliness ≈ 0 → fail) get nothing. This arm instead seeds `O` as INTERIOR light
wells (the most-landlocked leaves first, greedily spread so each illuminates a
fresh room set) and scales their count with the room count.

**Seed diagnostic first** (the epic mandate). Decomposing every crinkliness fail
in the bal+share seed by side of the gaussian: **all** are UNDER-exposed
(crink < 0.62, landlocked) — **zero** over-exposed slivers (crink > 21.7). So the
residual is genuine under-daylighting, validating the premise (and correcting the
epic's loose "high perimeter/area" wording — the *failing* leaves are starved, not
over-walled). The naive default `outside_divisor=6` was **null** (too few/small
wells; harbor seed 147→142, crinkliness even rose). Sweeping the divisor found
`odiv=3` seed-optimal: harbor seed fails 147→129 (−18), maple 219→206 (−14),
landlocked fails down — at the cost of more leaves (harbor +4, maple +8). Because
it ADDS leaves it carries the §13.4 wash-out risk, so the convergence A/B decides.

**Setup** (`experiments/run_interioro_ab.sh`, staged search, 20 000 native evals,
seeds 0/1/2, final native re-score). Both arms hold the default stack
`LEAFSHARE=1` (factor 3) + `DEPTHBAL=1`. Control is interior-OFF (peripheral `O`)
— must reproduce §13.5 bal+share; experiment adds `INTERIORO=1` (odiv=3).

| programme | peripheral off (s0/1/2) | mean | interior odiv=3 (s0/1/2) | mean | Δ |
|-----------|-------------------------|-----:|--------------------------|-----:|------:|
| maple-court  | 77 / 85 / 86 | 82.7 | 74 / 78 / 89 | 80.3 | −2.8 % |
| harbor-house | 41 / 43 / 38 | 40.7 | 28 / 39 / 35 | 34.0 | **−16.4 %** |

The control reproduces §13.5 (maple 82.7 ≈ 82.3, harbor 40.7 ≈ 40.0), so the gap
is the lever, not drift.

**VERDICT — positive on the DENSE floor, marginal elsewhere.** Harbor is the win
the issue targeted (it named "harbor-house ~19 rooms/floor" as where the single
peripheral `O` is wasted): **−16.4 %**, every seed improves (−13 / −4 / −3), arms
nearly non-overlapping (interior worst 39 ≈ control best 38). Maple is **−2.8 %**,
within seed noise — two seeds improve, one regresses (+3), ranges overlap. This is
the §13.4 pattern: the seed advantage (harbor −18, maple −14) survives roughly a
THIRD on harbor but mostly washes out on maple, because a dense floor has enough
landlocked rooms that the daylight gain outweighs the added-leaf tax, whereas on
the sparser maple the +8 leaves nearly cancel it. Unlike depth-balance-alone
(§13.4) which washed out *entirely*, interior-O holds on the dense floor.

Recommendation: make `interior_outside` (odiv=3) a default-ON Phase-8 lever
(default OFF today). Harbor is decisive and maple is net-neutral (mean still
−2.8 %, no programme regresses on mean), so the flip is strictly ≥ on both means
and matches the dense-programme target. Follow-up `homemaker-py-*` flips the
default (mirroring `pll` after erc.7). `outside_divisor` left at 3 (seed-optimal
joint); a finer odiv sweep under convergence is low-prior given maple's marginal
response.

### §13.7 High-budget harbor floor probe — 71d go/no-go (homemaker-py-71d.1)

The whole Phase-8 construction stack is now default-ON (leaf-sharing factor 3,
depth-balanced, interior-O odiv=3, circ_divisor 3, proportion-aware). Cumulative
floor vs the §12.2 leu.2 baseline (all under the §13.3 leaf-share-relaxed
objective, staged, seeds 0/1/2): **maple 136.0 → 80.3 (−41 %), harbor 74.0 → 34.0
(−54 %)** — the entire drop from construction levers, zero from search machinery,
exactly the epic's thesis.

This probe decides **71d** (failure-directed topology-repair operator). 71d's
premise: the pre-stack harbor 3M-eval plateau (`3m.dom`, re-scores to 27 fails)
is dominated by **13 crinkliness** fails, characterised as **landlocked** rooms
(`area_outside == 0` → `crink == 0` → `quality_uncrinkliness` hits the
`if not crink: return 0.0` branch, fitness.py:355 → guaranteed fail for ALL
ratios), repairable only by topology — *specifically interior O courtyards /
facade access*. That fix has since shipped DEFAULT-ON (interior_outside, §13.6),
so the premise needs re-measuring on the current stack.

**Setup** (`experiments/probe_harbor_floor.py`, harbor-house, full default stack,
seed 0, **500 000** native evals, staged, SERIAL — the leaf-share relaxed
objective is injected by a parent-process `fitness.load_config` monkeypatch that
does NOT reach `ProcessPoolExecutor` workers, so every §13.x floor run is serial;
see homemaker-py-x3b for the production CLI wiring). The probe re-scores the best
and splits each crinkliness fail into **landlocked** (`area_outside == 0`, 71d's
ratio-invariant target) vs **under-exposed** (`0 < crink < target`, reachable by
ratios/seeding).

| metric | old 3M plateau (pre-stack) | full default stack, 500k |
|--------|---------------------------:|-------------------------:|
| total fails | 27 | **20** |
| crinkliness | 13 | **4** |
| landlocked crinkliness | ~13 | **2** |
| top residual class | crinkliness | edge-too-long (6) |

Final residual histogram (20 fails): 6 edge-too-long, 4 crinkliness, 4 size,
2 proportion, 2 width, 2 level-not-connected. Re-score OK (relaxed config
consistent end-to-end).

**VERDICT — NO-GO on 71d as scoped; interior-O already dissolved its target.**
The landlocked-crinkliness block 71d was built to repair collapsed from ~13 to
**2 of 20** — because interior-O seeding *is* 71d's named fix (interior O
courtyards) and now does it by default. Crinkliness is no longer the dominant
class; the residual is small and spread across edge-too-long / size / proportion
/ width / connected, with **no concentrated ratio-invariant block** for a targeted
repair operator to attack. A deterministic repair operator remains a genuine new
operator class (not refuted by the §11.4/§11.5/§12.3 search-machinery losses), but
its expected value is now low: its highest-leverage target is gone, and what
remains is diffuse. Recommendation: close 71d (and prerequisites 7u5/jrb/u8x) as
superseded-by-construction; the floor 71d targeted was lowered by interior-O, not
by search machinery — consistent with the epic scoreboard. The deprioritised P4
levers erc.5 (compactness cuts — Diag A: floor is leaf-count not cut-quality, and
leaf-sharing over-delivered) and erc.6 (inner-loop slack — Diag B: wrong DOF)
close wont-fix on unmet revisit conditions, completing the epic.

Caveat (honest): single seed, 500k not 3M, relaxed config vs the old strict
standalone 27 — so the 20-vs-27 *total* is not a clean apples-to-apples. The
robust signal is the **composition collapse** (crinkliness 13→4, landlocked
13→2), which the §13.6 three-seed data corroborates (interior-O reliably cuts
harbor landlocked fails). Follow-up observation, not part of this verdict:
edge-too-long is now the single largest harbor class (6) — a candidate seed for
any future floor work, distinct from the crinkliness regime Phase-8 addressed.

### 13.8 Experiment: share-aware edge-too-long cap (`homemaker-py-hph`) — DONE (positive, harmless)

§13.7's follow-up observation (edge-too-long = harbor's top class, 6 fails) is the
seed. **Dissection first** (`experiments/diag_edge_too_long.py` on the 500k probe
best): the 6 fails are only **2 distinct locations**. (1) DOMINANT ~4/6: leaf
`lllr` is a `share=3` leaf — one quad holding 3 rooms (247 m², edges 15–17 m,
aspect 1.2, NEARLY SQUARE). Its walls exceed the flat 8 m cap purely because it
*aggregates 3 rooms* — a leaf-sharing REPRESENTATION ARTIFACT, not a design flaw.
§13.3 relaxed size/missing for shared leaves (`quality_size` centres on k×target)
but `edge_cost` (fitness.py) and `outside_edge_cost` still used a flat 8 m
regardless of `leaf.share` — the same §13.3 leak on a different measure. (2) ~2/6:
leaf `llll`, a 1.2 m × 16.7 m sliver (aspect 14) — a REAL narrow-room pathology,
already independently caught by width/proportion; its edge-too-long is the wall it
shares with `lllr`. No corridors involved.

**Fix.** New `Fitness._edge_cap(*leaves)` scales the 8 m cap by the largest
type-guarded `leaf_share` (graph.leaf_share, §13.3's helper) among the adjoining
leaves, mirroring `quality_size`'s k×target; non-shared leaves keep the flat cap.
Used by both `edge_cost` (interior wall, max share of the two leaves) and
`outside_edge_cost` (one leaf). Gated behind a new `share_edge_cap` config knob
(`SHAREEDGE` env), default OFF, so the §13.x controls reproduce. On the probe best
the lever clears all 6 edge-too-long (20→14 total fails); the `llll` sliver stays
flagged via width/proportion.

**Setup** (`experiments/run_shareedge_ab.sh`, full Phase-8 default stack
LEAFSHARE=1/fac3 + DEPTHBAL=1 + INTERIORO=1/odiv3, staged, 20 000 native evals,
seeds 0/1/2, final native re-score). Control SHAREEDGE=0 (flat cap) — must
reproduce §13.6/§13.7; experiment SHAREEDGE=1.

| programme | flat cap off (s0/1/2) | mean | share-aware on (s0/1/2) | mean | Δ |
|-----------|-----------------------|-----:|-------------------------|-----:|------:|
| maple-court  | 74 / 78 / 89 | 80.3 | 73 / 78 / 71 | 74.0 | −7.9 % |
| harbor-house | 28 / 41 / 35 | 34.7 | 27 / 39 / 27 | 31.0 | −10.6 % |

The control reproduces §13.7 (maple 80.3 *exactly*, harbor 34.7 ≈ 34.0), so the
gap is the lever, not drift.

**VERDICT — positive and HARMLESS; recommend default-ON.** Both programmes improve
on the mean with **zero regressions across all 6 seeds**: harbor every seed
(−1/−2/−8), maple two flat/down + one −18 (seed2). The asymmetry of magnitude
(maple's big seed2 swing) is search noise, but the *direction* is structural: the
lever only ever *removes* a false-positive fail on an aggregate shared leaf — it
cannot add one (non-shared leaves are untouched), so it is monotone-harmless on the
objective. This is unlike the §13.4-family construction levers that trade leaves
for fails; there is no tax to wash out. Recommendation: flip `share_edge_cap`
default-ON for leaf-sharing runs (it is the §13.3 relaxation completed on the wall
measure), mirroring the `pll`/`interior_outside` default flips. A follow-up issue
flips the default + rebaselines the §13.x floor numbers (harbor 34.7→31.0,
maple 80.3→74.0 become the new full-stack baseline). Repro:
`experiments/diag_edge_too_long.py`, `experiments/run_shareedge_ab.sh`.

### 13.9 Flip `share_edge_cap` default-ON + rebaseline §13.x floor (`homemaker-py-rq2`) — DONE

Acting on the §13.8 recommendation. `Fitness.__init__` now defaults the
share-aware edge cap to `self._leaf_sharing` when `share_edge_cap` is unset:
under leaf-sharing the cap is ON, mirroring the `pll` bal+share and §13.6
`interior_outside` default flips. An explicit `share_edge_cap=False` still
reproduces the pre-flip control arm, so the §13.8 A/B and any §13.x control stay
reproducible (`run_staged_search.py` now pins `conf["share_edge_cap"] = share_edge`
explicitly in both arms; the `SHAREEDGE` override is preserved). Non-sharing runs
(every example `patterns.config`, where `leaf_sharing` is absent) are untouched —
a control re-score of `programme-house` reproduces bit-for-bit.

**New §13.x full-stack floor** (Phase-8 default stack, staged, 20 000 evals,
seeds 0/1/2): **maple-court 80.3 → 74.0, harbor-house 34.7 → 31.0** — the
share-aware arm from §13.8 becomes the baseline. `test_edge_cap_flat_when_lever_off_even_with_sharing`
now pins `share_edge_cap=False`; `test_edge_cap_defaults_on_under_leaf_sharing`
guards the flip. 222 tests pass.
