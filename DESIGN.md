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

### 11.8 Topology diversity × selection pressure, co-tuned (`homemaker-py-6zy`) — DONE (negative)

Premise (loose end from §11.5): structural niching was A/B'd against the legacy
fitness-scalar dedup with selection pressure **held fixed** at a binary tournament
(`driver._tournament`, `k=2`). §11.5's own mechanism note named the coupling as
the reason for its null — "Maximal diversity (16/16) with the fixed tournament
pressure just **diffuses** effort" — i.e. diversity and pressure are coupled but
were varied as if independent: niching widens the population, but `k` was never
**sharpened** to convert the extra exploration back into exploitation. This issue
isolates that coupling — sweep tournament size jointly with niching to test
whether sharper selection turns the 16/16 structural diversity into lower fails.
The project had already pivoted to the canonical encoding (`homemaker-py-9gp`);
this is a falsification check so the lever is not silently lost, not an expected
win (§11.4/§11.5 both located the plateau in **reachability**).

**Implementation (knob only; default-off behaviour unchanged).** Exposed
`tournament_k: int = 2` on `search` / `search_staged`, threaded into both
`_tournament` call sites (crossover pair + mutation parent) and all three internal
`search()` calls of the staged path; reuses the §11.5 `genome.signature` /
`niche_by_signature` machinery unchanged. The experiments harness reads
`HOMEMAKER_TOURNAMENT_K` (mirrors `NICHE`) in `run_search_scaled.py` /
`run_staged_search.py`; `experiments/run_6zy_ab.sh` runs the joint grid (RESUME-able).

- *Commands (reproduce, `URB_NO_OCCLUSION=1`, 20000 evals; blank-slate seed
  `init.dom` to match §11.5):*
  ```bash
  # grid: NICHE ∈ {0,1} × HOMEMAKER_TOURNAMENT_K ∈ {2,3,4}
  NICHE=0 HOMEMAKER_TOURNAMENT_K=2 python3 experiments/run_search_scaled.py \
    examples/programme-house 20000 <seed> examples/programme-house/init.dom scratch/out.dom
  # harbor (staged): run_staged_search.py, seed examples/harbor-house/init.dom
  bash experiments/run_6zy_ab.sh        # full grid → scratch/6zy/summary.tsv
  ```

- *Diversity (mechanism check) — confirmed biting.* `niche=on` holds the final
  population at **16/16** distinct topologies at every `k`; `niche=off` sits at
  **4–11/16**. The pressure knob is genuinely varied (`k`=2,3,4). So both levers
  are live — the null below is not a machinery artefact.

- *Fail count (the gate) — no cell beats the baseline.* Blank-slate
  programme-house, total fails at budget over **5 seeds** (0–4), mean (sd):

  | niche \ k |     k=2     |     k=3     |     k=4     |
  |:---------:|:-----------:|:-----------:|:-----------:|
  | **off**   | **4.80** (1.60) | 6.40 (2.50) | 6.00 (2.00) |
  | **on**    | 6.20 (1.72) | 7.00 (1.41) | 6.60 (1.85) |

  The legacy `(off, k=2)` cell is the **best** of the six (4.80); every
  higher-pressure row and every `niche=on` row is equal-or-worse (6.0–7.0). All
  differences sit within ~1 sd at 5 seeds, so the grid is a wash — but the central
  tendency is unambiguous: sharpening `k` and adding niching both *slightly hurt*,
  the opposite of the rescue the premise hypothesised. Harbor-house (staged, seed
  0) reinforces it: `niche=on` is uniformly worse than `off` at every `k`
  (k2 72→83, k3 77→82, k4 67→75); within the `niche=on` row higher `k` helps
  monotonically (83→82→75) but never catches the `niche=off` row, and the best
  cell overall (`off, k=4` = 67) is a single-seed wiggle within noise of the
  `off, k=2` = 72 baseline.

- *Why it fails — the coupling is real but points the wrong way.* Sharper
  selection does **not** convert the extra structural diversity into lower fails;
  if anything the 16/16 niched population at high `k` over-commits the
  larger spread to a handful of basins and loses the occasional lucky low-fail
  draw the smaller fitness-scalar population stumbles into. §11.5's "diffuses
  effort" diagnosis survives co-tuning: the bottleneck is **reachability**
  (operators + encoding cannot reach the low-fail basins), so reshaping
  selection/population pressure cannot recover what the search space does not
  expose — the same conclusion §11.4 reached from the comparator side and §11.5
  from the diversity side.

- *Verdict: §11.5 null is robust to selection pressure — reject `k>2` and niching
  as defaults; binary tournament + fitness-scalar dedup stand.* `tournament_k` is
  kept (default-2) as a reusable knob alongside `niche_by_signature`. With
  §11.4/§11.5/§11.8 all negative on the outer loop, the residual is confirmed
  structural: the principled lever is the canonical encoding + richer topology
  operators (`homemaker-py-9gp`), not selection or population management.

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

- *§12.3 re-run at fixed worker count — CONFIRMED, no new run needed
  (`homemaker-py-h10`, 2026-07-30).* §12.4's own writeup flagged the §12.3
  reassoc/feas negatives (+3.3/+4.0) as sub-±3-adjacent and asked for a re-run
  "at a single fixed worker count" post-fix, since they predate the
  completion-order determinism fix above. Checked before re-running the full
  8.3-hour sweep: `experiments/run_9gp_ab.sh` invokes `run_staged_search.py`,
  which never threads a worker count through to `driver.search_staged` —
  every §12.3 arm therefore already ran at `n_workers=1` (serial), the one
  mode §12.4 itself already proved "was already byte-for-byte reproducible"
  even *before* the fix (the bug was in `ProcessPoolExecutor`
  `as_completed` ordering, parallel-only; serial has no futures to reorder).
  Confirmed empirically too: re-running one arm (harbor-house seed 0,
  baseline config, budget 300) twice back-to-back reproduced identical fail
  counts at every logged checkpoint. So the §12.3 table was already measured
  at a fixed (and the most reproducible available) worker count — the
  determinism fix changes nothing for it. **Verdict stands as CONFIRMED-NULL**
  without re-spending the ~8 core-hours a full re-run would cost; upgrades
  §12.3's negative from "should be re-run" to "already valid as measured."

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

### 13.10 Productionise leaf-sharing: per-code `share` + CLI wiring (`homemaker-py-x3b`) — DONE

Make the §13.3 lever a first-class, programme-author-controllable feature instead
of an experiment-only env var + monkeypatch. Three pieces:

**1. Per-code grain (`SpaceReq.share`).** `patterns.config` spaces accept an
optional `share: N` → `SpaceReq.share` (int, default 1 = not shareable; a
`has_share` flag distinguishes an explicit `share: 1` from the default).
`operators._share_grain(req, leaf_share_factor)` resolves each code's grain from
the global selector:
- `leaf_share_factor == 0` — **per-code opt-in**: a code shares iff it sets
  `share: N≥2`; this is the safe default-on philosophy (sharing off unless the
  author asks, per space).
- `leaf_share_factor ≥ 2` — **global mode**: every sized code shares at the
  factor, with an explicit `share` overriding (`share: 1` opts a code OUT,
  `share: N` sets that code's grain to N). Reproduces the §13.3 experiment with
  **no edits to example programmes** (so §13.3/§13.9 baselines stay reproducible).

Only sized codes are ever shareable (an unsized c/o/s absorbs slack — no target
to centre `k` rooms on). `_share_rooms` now groups per resolved grain.

**2. End-to-end conf injection.** The §13.3 scoring sites gate on a `leaf_sharing`
conf key, but example `patterns.config` files don't set it — the experiment
harness monkeypatched `fitness.load_config` to inject it. Productionised cleanly:
`load_config(dir, overrides=None)` merges run-level keys last, and
`driver.search` / `innerloop.optimise` / `NativeEvaluator` / `_fitness_for` thread
`conf_overrides={"leaf_sharing": True}` through both the inner-loop scorer and the
off-tree grade/feasibility scorer when sharing is on. So the whole pipeline scores
under the relaxed objective the shared seed targets, with no monkeypatch and no
on-disk edits. (`share_edge_cap`'s §13.9 default-ON-under-sharing derivation in
`Fitness.__init__` rides along automatically.)

**3. CLI.** `homemaker-evolve` gains `--leaf-sharing/--no-leaf-sharing` (default
ON, `HOMEMAKER_LEAF_SHARING`) and `--leaf-share-factor N` (default 3,
`HOMEMAKER_LEAF_SHARE_FACTOR`), threaded to `driver.search`.

Default-OFF parity holds: `overrides=None` leaves `load_config` byte-identical and
`_share_rooms` is never reached. Smoke-checked end-to-end on harbor-house (sharing
on 37 fails vs `--no-leaf-sharing` 95 at budget 160). 233 tests pass.

### 13.11 Residual diagnostic on the current full default construction stack (`homemaker-py-91f`) — DONE

The §13.1/§13.2 (`erc.1`/`erc.2`) per-leaf diagnostics predate the depth-balanced
+ leaf-sharing synergy flip (`erc.7`) and the share-aware edge cap flip (`rq2`/
`x3b`) — the current §13.9 floor (harbor 31.0, maple 74.0) had never been
decomposed by fail category. Unlike `erc.1` (which scores a single constructed
seed at target geometry, a cheap proxy), this reads the actual best individual
from a REAL `driver.search_staged` run — budget 20000, seeds 0/1/2, harbor-house
and maple-court, the full default stack (`leaf_sharing`/`leaf_share_factor=3`,
`depth_balanced`, `interior_outside`/`outside_divisor=3`, `share_edge_cap`
default-on under sharing) — the actual reported floor, not a proxy.

**Methodology note — a scoring pitfall found along the way.** The obvious
approach (dump each run's best to `.dom`, reload, rescore with matching conf)
gives a WRONG, but stable and easy-to-miss, fail count once `collapse_insearch`
is doing real relabelling work: on harbor-house seed 0 the search itself
reported 37 fails, and `copy.deepcopy(r.best.root)` rescored immediately
in-process reproduces 37 exactly, but `dom.dump` + `dom.load` + rescore of the
*same* topology gives a stable 53 — 15 extra `missing`/`adjacency`/`level`
fails for a level-0 `count: 3` code that collapse-relabelling satisfies in the
live tree but that is not present as a literal leaf type once round-tripped.
Root cause not yet found (hash-seed randomness and float round-trip loss are
both ruled out); filed as `homemaker-py-iio` (P2). A narrower, separate bug —
`run_staged_search.py`'s own final sanity rescore omits the `collapse_insearch`
override entirely, so its own "MISMATCH" line cannot be trusted whenever
leaf-sharing is on — was filed as `homemaker-py-7ua` (P3, fixed) but the fix
only covers the `LEAFSHARE`/`MULTIUSE` monkeypatch path; the same rescore is
still wrong on baseline (`LEAFSHARE=0`/`MULTIUSE=0`) runs since
`driver.search_staged` has no `collapse_insearch` param and always runs its
inner evaluator with it on regardless of those flags — tracked as
`homemaker-py-4ok` (P3). This diagnostic
sidesteps both: `experiments/run_and_capture_91f.py` scores
`copy.deepcopy(r.best.root)` immediately after `search_staged` returns, and
writes the fails list to a `*.fails.json` sidecar (verified `rescore_match` on
all 6 runs); `experiments/diag_residual_91f.py` tallies fail categories from
those sidecars, never rescoring a `.dom` from disk.

**Result (mean fails/seed; category % of all fails, combined):**

| programme | seeds (fails) | mean | vs §13.9 cited floor |
|---|---|---|---|
| harbor-house | 37, 33, 30 | 33.3 | 31.0 |
| maple-court | 82, 84, 78 | 81.3 | 74.0 |

(Both a bit above the cited floor, as expected — a single staged run per seed
here vs. whatever selection produced the cited numbers; same order of
magnitude, good sanity check that the stack is wired correctly.)

| category | combined n | % |
|---|---|---|
| **crinkliness** | 165 | **48.0%** |
| **size** | 71 | **20.6%** |
| adjacency (not adjacent) | 20 | 5.8% |
| proportion | 13 | 3.8% |
| access | 12 | 3.5% |
| edge too long (outside) | 12 | 3.5% |
| missing (adjacency/level/vertical cascade) | 12 | 3.5% |
| circulation not connected | 9 | 2.6% |
| edge too long (wall) | 9 | 2.6% |
| missing required space | 6 | 1.7% |
| (remaining: too-many-spaces, covered-outside, stairs, width, public-access) | 12 | 3.4% |

Per-programme shares are consistent (crinkliness 43%/size 21% on harbor-house,
crinkliness 50%/size 20.5% on maple-court) — this is not an artefact of one
programme.

**VERDICT — shape-intrinsic fails (crinkliness + size ≈ 69% of the residual)
now completely dominate; construction-completeness fails (missing space,
adjacency, level, vertical connectivity — the failure modes the §11–§13 series
of construction levers targeted) are now a small tail, ≤6% each.** This
revises the `erc.1` recommendation. `erc.1` (§13.1) found per-leaf crinkliness
FLAT vs. slicing density and concluded the floor was intrinsic to leaf COUNT,
prioritising leaf-sharing (`erc.3`) over compactness-aware cuts (`erc.5`,
deprioritised: "cuts are already squarest ... little headroom at fixed count").
Leaf-sharing (plus depth-balancing, interior-O, and the edge cap) is now fully
deployed as the default stack, and crinkliness is not just still present but
*more* dominant proportionally than in any earlier per-category breakdown in
this document (cf. §7's 27/85 and §9's 346/939-ish shares) — the "reduce leaf
count" avenue has been substantially exploited by the current stack, yet the
per-leaf shape tax persists and is now, by a wide margin, the single largest
lever available. **Recommendation: reopen `erc.5`-style compactness-aware
cutting (or a crinkliness-targeted construction/mutation lever specifically,
since crinkliness outweighs size ~2.3:1) as the next concrete construction
lever** — the same diagnostic-first logic that turned §13.7's edge-too-long
finding directly into `hph`.

## 14. Island model: multi-run recombination (`homemaker-py-psk`) — DONE (null)

**Lever (user-proposed).** Perl Urb ran the search many times and kept the best,
because independent runs settle into different local minima. The Python tool is
deterministic per `--seed`, so the analog is an *island model with synchronous
migration*: run N independent seeds to convergence (Phase A), then PRIME a fresh
population with those N converged elites and run a second, crossover-heavy phase
(Phase B) to recombine basins. Distinct from §11.5 (`c4c.5`), which injected
**fresh** random/constructive seeds for raw diversity and landed null — here the
migrants are **fully-converged elites**, high-quality building blocks, so the
"diversity does not help" result does not directly refute it. The one untested
sub-mechanism: can crossover *stack* wins across independent basins (run A solved
cluster X, run B solved cluster Y, child inherits both)?

**Design (`experiments/run_island_ab.py`).** Three numbers per programme, all
`leaf_sharing` OFF so controls track the §12.2 baselines (maple 136 / harbor 74),
all on **equal actual eval budget** (the staged search has a hard ~`pop·child·2`
bootstrap floor, so we account `r.n_evals`, never the request):
- **`bestN@A`** — best-of-N over Phase A (the FREE reference; these N runs happen
  anyway — the legitimate descendant of Urb's multi-run habit).
- **`island`** — Phase B result: a population primed from the N Phase-A elites via
  the existing `seed_factory`+`bootstrap` path (no new representation), evolved at
  `p_crossover=0.7`. Total budget = Phase A + migration.
- **`bestN@T`** — best-of-N over N independent runs at the *same total* per seed
  (the "N+ longer independent runs" control). **THE BAR**: island must beat it.

A default-off `child_probe` hook (`driver.search`) instruments the deciding
mechanism: for every crossover child it records whether the spliced child beats
`max`/`min(parent fails)`. Parent fails are appended to the child lineage as
`|pf=a,b` (only when the probe is set) so the signal survives the
`ProcessPoolExecutor` pickle round-trip an `id(root)` key cannot.

**Result (N=4, master_seed 0, 28160 actual evals/arm, 4 workers):**

| programme | bestN@A | island | **bestN@T** | verdict | crossover beat-min-parent |
|-----------|--------:|-------:|------------:|---------|--------------------------:|
| harbor    |      73 |     68 |      **67** | loses by 1 (within noise) | 1 / 65 |
| maple     |     134 |    124 |     **116** | loses by 8 (decisive)     | 3 / 63 |

**Verdict: NULL / negative.** The island model does **not** beat best-of-N at
equal total budget. On harbor it ties-to-loses inside the parallel noise band; on
maple it loses clearly (124 vs 116) — a single *longer* independent run reached
116 while the migration phase, given the same budget, stalled at 124. The migration
phase buys nothing a longer independent run does not.

**The mechanistic probe explains why (the deciding diagnostic).** Crossover across
independently-converged elites almost never synthesizes: of ~64 crossover children
only **1/65 (harbor) and 3/63 (maple)** beat the *better* parent, with a best
fail-drop of just 2 and 5. This confirms the issue's **alignment** hypothesis:
`operators.crossover` is *area-matched* subtree exchange, but two independently
evolved trees encode similar arrangements at different paths/areas (the encoding
is non-canonical — `9gp` closed negative), so the splice is mostly disruptive, not
combinatorial, and the inner loop re-solves ratios at the boundary (spliced quality
not preserved). The null is therefore **mechanistic, not budget**.

**Noise caveat (carry forward).** Phase A is unaffected by the probe, yet harbor
seed 2 scored 71 then 73 on byte-identical re-runs — parallel/BLAS
non-determinism, the same ±2-3 effect §12.4 flagged. Sub-±3 verdicts under
`n_workers>1` are noise; both arms here ran at the same worker count so the
*comparison* stays fair, and maple's −8 is safely outside the band.

This is the third search-machinery null after §11.4 (graded objective) and §11.5
(niching+restarts) / §12.3 (M3 + shape filter), against four construction/seed
wins (§11.6, §11.7, §12.2, §13.x). best-of-N at the Phase-A budget remains a free,
worthwhile habit; a dedicated migration phase is not worth its budget. The residual
stays geometry/shape-bound. NOT gated on canonical encoding (`9gp` closed); the
`child_probe` hook is kept default-off for reuse.

## 15. Leaf-sharing output honesty: unfold + polish auto-finish (`homemaker-py-3l6`) — DONE

**Bug.** Leaf-sharing (§13.3/§13.10, default ON) is a *fitness-evaluation* knob: a
shared leaf of code X with `share=k` is credited as satisfying k programme entries,
its size Gaussian re-centred on `k*target`. So the evolve inner objective rewards
genomes that under-materialise the programme (fewer, larger rooms), but the winning
`.dom` written to disk is that un-materialised genome. Re-scored by the canonical
`homemaker-fitness` (sharing OFF), the un-materialised copies become *missing
required space (critical)* fails. Measured on harbor-house (init.dom, 3M budget):
internal best `1.03e-05` but **canonical `6.73e-29`, 90 fails (15 critical)**. The
default silently optimised an objective the canonical scorer does not credit and
wrote a catastrophically worse building than its reported internal fitness implied.

**Investigation (`homemaker-py-yaa`).** Four fixes were scoped (make no-sharing the
default; re-score-and-warn on write; materialise shared leaves on write; anneal the
grain to 0 mid-run). yaa characterised the transferability of a sharing-phase
solution to the honest objective and reached a **conclusive** result:
- Naive warm-start from a raw sharing seed **stalls** (harbor 8.66e-08, 70 fails) —
  `place_missing`/`divide` cannot dig out the ~15-room count deficit fast enough.
- Warm-start **+ unfold** (`operators.unfold_shared_leaves` at the transition)
  **catches the direct no-sharing route** (4.19e-06, 15 fails, 0 critical),
  matching the `--no-leaf-sharing` baseline (`nols-2` 4.19e-06). Bruno's key idea
  confirmed: the sharing phase's transferable value is the **adjacency/topology
  skeleton**, and the sole blocker to reusing it is the **materialisation (count)
  deficit** — not the `k*target` sizing mismatch. Unfold pays that deficit down.

**`operators.unfold_shared_leaves(root)`.** Replaces every live shared leaf
(`share>1`, `share_type==type`) with a balanced binary subtree of k same-code
leaves splitting its footprint, sizes each for squarest proportion, and clears the
share stamps. Footprint (plot area) is preserved; the adjacency skeleton is
otherwise untouched. Returns the number of extra leaves created.

**Fix — auto-finish before write (`driver.polish_finish`).** Rather than unfold on
write alone (honest room *count* but un-polished proportion/width/size on the fresh
children), the finish runs yaa's proven unfold-**then-polish** as an automatic
terminal phase. When a run used `--leaf-sharing`, before write:
1. deep-copy the best, `unfold_shared_leaves` it (materialise the deficit);
2. warm-start a `leaf_sharing=False` search (`bootstrap=False`) from the unfolded
   genome for `--polish-budget` evals — local search under the *honest* objective
   cleans up the newly materialised rooms.

The returned `best.fitness` is then the canonical score (sharing OFF ⇒ internal ==
canonical), and eval/topology/history accounting is stitched onto the sharing run
with the two phases tagged `share:`/`polish:` (the objectives are not comparable, so
the histories are concatenated, not merged). `--polish-budget` (env
`HOMEMAKER_POLISH_BUDGET`): `-1` = auto = `budget//2`, `0` = unfold + single rescore
only (no search). An **interrupt** forces `polish_budget=0` so a stopped run still
writes an honest output without triggering a long extra phase.

The default stays `--leaf-sharing` ON: its ~35 %-faster topology search (§13.3) is
retained, and the output is made honest by the finish instead of by disabling the
lever. Option 1 (no-sharing default) and option 2 (warn-only) from the bug were
therefore not needed; the annealing option is its own follow-up (Schedule B,
`homemaker-py-kpu`) — the single-transition finish here is its proven precursor, and
`unfold_shared_leaves` is the primitive it will reuse at each grain step.

**Verification.** harbor-house, budget 3000 + polish 1500: the reported polish
fitness `4.79788e-27` **matches the canonical `homemaker-fitness` byte-for-byte**,
**0 critical fails** (the missing-room criticals are gone — the 15 shared-leaf
copies are materialised). Small budget so absolute quality is low, but the
honesty — the point of the bug — is restored. Tests: `driver.polish_finish` ×3
(unfold+rescore stitching, polish-search accounting, no-best noop); 254 pass.


## 16. In-run leaf-share grain annealing — Schedule B (`homemaker-py-kpu`) — DONE (negative)

**Premise.** §15's finish crosses the sharing→off objective cliff in a *single*
hard transition (unfold every shared leaf at once, then polish). Schedule B (yaa's
still-open option) instead **ramps the grain down within one continuous run** —
e.g. `4 → 3 → 2 → off` — carrying the whole population across each step. Graduated
non-convexity: the coarse early grain fixes gross topology/adjacency on a small
effective problem (few, large rooms); each step materialises a little more and
refines per-room size/proportion/width; no single fitness cliff is crossed at once.
The question (kpu): **does a graduated ramp beat the single hard unfold transition**
(yaa's warm-chain 4.19e-06) and the direct no-sharing baseline (5.14e-06)?

**8iv settled the unfold primitive first (NEGATIVE).** kpu originally "wanted" the
circulation-aware unfold from `homemaker-py-8iv` (route the materialised subtree's
access through interior children). 8iv built and A/B-tested it and it **lost** to the
plain balanced-grid `unfold_shared_leaves` (slice 41 fails vs grid 25 at 150k evals,
grid leading throughout). So Schedule B reuses the **existing grid unfold** at every
grain step — no slicing reintroduced; access is left to local search on the squarer
grid seed (which yaa showed reaches 4.19e-06).

**Mechanism (`driver.search_annealed`).** One phase per descending grain in
`grain_ladder` (default `(4, 3, 2)`), then a de-share polish:

1. **Phase 0** (`grain = ladder[0]`): a normal `search` — constructs the population
   at `leaf_share_factor = cap` with the evaluator's `leaf_share_max` capped to
   `cap` (new `max_share` override, threaded through `_overrides_for`/`_fitness_for`/
   `_evaluate`).
2. **Each grain step** (`cap` lowered): before resuming, unfold every population leaf
   whose `share` *exceeds* the new cap — `operators.unfold_shared_leaves(root,
   above=cap)` — so the leaves the lower cap would under-credit become real rooms
   instead of fresh missing fails; the rest stay collapsed for the next step. The
   whole population is then handed to the next `search` via the new `seed_pop`
   argument (each root re-optimised and re-scored under the lower cap), preserving
   topology/adjacency continuity rather than restarting from a single best.
3. **Finish** (`grain off`): unfold all remaining shared leaves (`above=1`) and run a
   `leaf_sharing=False` search (or a single rescore when `polish_budget <= 0` / on
   interrupt), so the returned `best.fitness` is the honest canonical score exactly
   as §15 guarantees (verified: annealed output re-scored by `homemaker-fitness`
   matches the reported best byte-for-byte).

`budget` is split evenly across the sharing phases; `polish_budget` funds the finish.
Phases are stitched with cumulative eval/topology accounting and a grain-tagged
history (`g4:`/`g3:`/`g2:`/`polish:`) — objectives differ across grains so histories
are concatenated, never merged. CLI: `homemaker-evolve --anneal-grain 4,3,2` (implies
sharing; self-finishing, so the §15 finish is not applied on top).

**Verification (plumbing).** harbor-house, budget 900 (300/phase) + polish 300,
4 workers: unfolds 33 → 22 → 9 leaf-copies across the ramp, population carried
(`anneal-seed/*` lineages), honest share-free output whose reported best
`3.36672e-29` **matches `homemaker-fitness` byte-for-byte**. (Fails rise at this toy
budget — 64 leaves materialised with almost no recovery budget — so absolute quality
is meaningless here; the head-to-head below runs at the baselines' budget.) Tests:
`unfold_shared_leaves(above=)` grain-cap selectivity; `search(seed_pop=)` population
seeding; `search_annealed` phase stitching / honest finish / degenerate-ladder
fallback; 258 pass.

**Head-to-head (DONE — NEGATIVE).** harbor-house, `init.dom`, seed 0, pop 16, child
80, grain `4,3,2`, budget 1.5M (500k/phase) + polish 1.5M = **3M total** (workers 4,
~22h), matched to the yaa baselines. Result: **1.26e-08, 23 fails** (canonical
`homemaker-fitness` byte-for-byte). Both targets **beat it decisively**:

| route | fitness | fails |
|-------|---------|-------|
| direct `--no-leaf-sharing` | 5.14e-06 | 15 |
| yaa warm-chain (single hard unfold) | 4.19e-06 | 15 |
| **Schedule B (graduated 4→3→2→off)** | **1.26e-08** | **23** |

~400× worse fitness, +8 fails. **Verdict: the graduated grain ramp loses to the
single hard sharing→off transition (§15).** The trajectory shows why — each grain
step spikes the fail count as its unfolded leaves acquire independent shape fails
(phase-end fails 19 → 21 → 27, then the final de-share unfold 27 → 36), and the
per-phase budget re-polishes a partially-materialised state that the *next* step
materialises further, so the coarse-grain gains (19 fails at grain 4) do not carry
forward. Splitting the budget across three intermediate materialisations left the
polish phase starting from a deeper hole (36 fails) than the warm chain's single
clean transition, and 1.5M polish evals recovered only to 23 — short of the 15 both
baselines reach. Graduated non-convexity is **falsified** for this materialisation
cliff: the transferable value is the sharing-phase topology skeleton (yaa), and it is
best cashed in **once**, at full grain, not annealed. (Caveat: this run used
`workers=4` vs the baselines' `workers=1`; the ~400×/+8-fail gap is far larger than
worker-count trajectory noise, so the direction is robust.)

The machinery is retained (`search_annealed`, `--anneal-grain`, `unfold_shared_leaves(
above=)`, `search(seed_pop=)`, the `max_share` evaluator override) — it is correct,
tested, and honest, and the `seed_pop` / grain-cap primitives are reusable — but the
default finish stays §15's single-transition unfold+polish. Tests: 258 pass.


## 17. Finish-time global cell→room collapse (`homemaker-py-94g`) — DONE (positive)

**Motivation — label-relative fails.** A layout's leaf carries a room *type*, and
many of a good layout's residual fails are **label-relative**: a cell fails `size` /
`width` / `proportion` only because the room *assigned* to it wants dimensions it
lacks — relabel that cell to a room it fits and the fail vanishes; a `wrong-level`
fail is likewise a labelling error. On the harbor-house best layout (`evolved-3M-nols-3`,
15 fails) ~11 of 15 are label-relative. This is separable from the **geometry-intrinsic**
fails §13 chased at the shape floor — long-thin useless cells (`width`/`proportion`/
`crinkliness`) and `not-connected` — which *no* relabelling can fix because the cell's
geometry, not its label, is wrong. The collapse targets only the former.

**Mechanism (`Fitness.collapse_global`).** A one-shot, finish-time pass that relabels
the whole building's room cells in one optimal assignment — the 9o5 per-class collapse
(interchange superposition) generalised from one equivalence class to a **global**
N inside-leaves ↔ M required-rooms matching (`_best_assignment`: brute-force under the
class cap, else Hungarian). SUPPLY = leaves whose type is an assignable room code;
DEMAND = every such code expanded by its required count. Constraints, each landed after
an empirical correction (below):
- **c/o/s partition.** Assignable codes exclude any starting `c`/`o`/`s`. `check_space_counts`
  (graph.py) skips those as circulation/outside/sahn — *including room codes that collide
  with the convention* (`cr1` Common Room, `st1`/`st2` Storage). Those leaves are the
  circulation/structure skeleton and must never be relabelled; the collapse uses the
  same partition the scorer counts against.
- **Hard level.** A leaf may take a room only if its storey matches the room's required
  level (a −1e12 forbid penalty), so the collapse never *adds* a wrong-level fail.
- **Adjacency relaxation.** Geometry is fixed at finish time, so each leaf's graph
  neighbours are fixed and only labels move. Required adjacencies become a labelling
  relaxation: warm-started from the evolved labels, each pass is a linear assignment over
  the base value plus a bonus for each of a code's adjacencies satisfied by the *current*
  neighbour labels, iterated to a fixpoint (Jacobi/WFC-style). Only room↔room adjacencies
  can break — adjacencies to `c`/`o` are invariant since those leaves are never relabelled.
- **Threshold objective.** The base per-cell value is either continuous fit
  (`sum(usage_quality*area)`, as 9o5) or — the default — the **count** of `size`/`width`/
  `proportion` factors that pass (≥ `FAIL_THRESHOLD`), with continuous fit only as a
  tiebreak. A satisfied adjacency and a passing factor carry the same unit weight
  (`_COLLAPSE_FAIL_W`), so the collapse minimises (adjacency + size/width/proportion)
  fails *jointly*.
- **Public-access pin.** The building-level "no outside public access" check is
  existential (∃ a public street-edge outside leaf with an l/c/k neighbour) — invisible to
  the per-leaf objective. When the sole provider is an l/k *room* neighbour (no circulation
  fallback), that leaf is pinned (kept, its demand slot decremented) so the collapse cannot
  drop the check.

**Two corrections found by measurement.** A naive first cut (level-only, per-leaf,
continuous fit) went **15→46 fails**. Diagnosis killed two hypotheses: (1) the count
explosion was *not* a merge effect (`merge_divided` merges only outside/sahn siblings,
never rooms) but the c/o/s partition bug above — pulling `cr1`/`st1`/`st2` into the
assignment shredded the circulation skeleton; fixing the partition took +31→+1. (2) The
residual +1 was the continuous objective *shuffling* a `size` fail from one leaf to
another (pushing one just over the 0.1 threshold and another just under); the threshold
objective optimises the fail count directly and removes it.

**Keep-better + wiring.** `Fitness.collapse_finish` scores baseline and collapsed on
throwaway copies (scoring merges in place) and keeps the collapse only if the fail count
does not increase — a strictly monotone safety belt. `driver.collapse_best` applies it to
a `SearchResult`'s best, canonically re-scoring and tagging lineage `+collapse`.
`evolve.py` runs it after the §15 sharing finish behind `--collapse`/`--no-collapse`
(**default ON**). Standalone `homemaker-collapse <file.dom>` (`collapse_cmd.py`) applies it
to an existing layout, writing `<stem>.collapsed.dom`.

**Verification.** Sweep over 6 harbor-house evolved layouts (total fails, base 195):
`adj_off/quality` 192, `adj_on/quality` 185, `adj_off/threshold` 181, `adj_on/threshold`
**171**. The default (`adjacency=True, objective="threshold"`, public-access pin) is
**monotone across all 6** (never worse than baseline; keep-better guard is a belt, not
needed here) — best layout 15→12, and e.g. 32→26, 90→82. The residual on the best layout
is geometry-/building-bound, not label slack: the collapse searches **labels only, never
geometry**, so it cannot touch long-thin cells or `not-connected` — those are spun out to
`homemaker-py-7fm` (shape reshape) and `homemaker-py-qi6` (circulation placement). Running
the collapse *inside* search per-eval (rather than finish-time) is `homemaker-py-qpk`,
gated on the 9o5 landscape-flattening risk (§13 / `homemaker-py-xi7`) and its own A/B.
Tests: `tests/test_collapse_global.py` ×6 (demand-set relabel, level hard constraint, c/o/s
exclusion, no-op safety, keep-better/unmerged); 267 pass.

## 18. Graded circulation-connectivity signal (`homemaker-py-qi6`) — DONE (negative)

**Motivation — the binary fail is flat.** After the §17 collapse, the residual fails on the
harbor-house set are dominated by `level N not connected` (2 of the best layout's 12; also on
5 of the 6 sweep layouts). That fail comes from `connected_circulation` (`graph.py`): remove
every non-circulation vertex from a storey's adjacency graph and require the remaining
circulation cells (`C` stairs plus the `cr`/`st` room-codes that collide with the c/s prefix)
to form ONE connected component. On the evolved layouts they instead fragment into **4–7
components per storey**.

**Why finish-time repair fails (measured, negative).** The obvious §17-style companion — a
finish-time pass that re-types boundary cells to circulation to bridge the components, kept
only if the fail count does not rise — was prototyped (Steiner-MST bridge set per disconnected
storey, keep-better guard) and measured on the 6 layouts: **195 → 560 fails (+365)**. The
`not connected` fail is *binary* (one fail per storey regardless of fragmentation), but each
storey needs 3–7 bridge cells, and every needed-room→circulation conversion triggers a
missing-room fail cascade (2–5 fails) that dwarfs the single connectivity fail it clears.
Keep-better reverts every one → no-op. **Conclusion: connectivity cannot be bought at finish
time when every cell is a needed room; it must come from the outer search allocating connected
circulation topology.** But the binary fail gives the search *zero gradient* — a 7-component
storey scores identically (both in fail count and in the `0.5^n` scalar) to a 2-component one —
so the search cannot tell it is making progress.

**Mechanism — a graded proximity on the same channel §11.4 built.** `graph.circulation_connectivity(G)`
returns the fraction of circulation cells in the largest connected circulation component ∈
[0,1] (1.0 = a single connected spine, lower = more fragmented, 0.0 = no circulation), measured
on the same circ subgraph the fail uses so the two agree at the connected endpoint. Summed over
storeys it is the graded proximity scalar `Fitness.score_with_grade` already carries for the
outer comparator, gated by the `conn_grade` conf flag: when on it *replaces* the §11.4 leaf
quality-proximity on that channel (a distinct, better-motivated use — §11.4 was rejected because
within a fail-tier the `0.5^n` scalar is NOT flat there and grade merely displaced a working
signal; connectivity is the opposite case, genuinely flat under the binary fail). Like §11.4 it
leaves the scalar fitness and fail count **byte-identical** (verified) — it is only the secondary
key `(-n_fails, grade, fitness)` (driver `use_lex and use_grade`), strictly beneath fail-count so
the §6 missing-space hierarchy and the §5.4 inner-loop cliff are untouched. Among equally-failing
neighbours the search now prefers the one whose circulation is closer to one component, restoring
the gradient toward connected topologies.

**Wiring.** `conn_grade` threads through `_overrides_for`/`_fitness_for`/`_evaluate` and the
`search` signature; enabling it implies the grade key. `evolve.py` exposes `--conn-grade`
(env `HOMEMAKER_CONN_GRADE`, default OFF); the grade is read off the optimised tree, one extra
native eval per child.

**Build.** Signal, fitness wiring, CLI, and 9 tests landed (`tests/test_conn_grade.py`: pure-graph
fraction contract, non-circ cells ignored, monotone under (dis)connection, and the score/fail-
count-invariance of the flag). 276 tests pass.

**A/B verdict (measured, 2026-07-22, qpk protocol, `experiments/run_qi6_ab.sh`) — NEGATIVE.**
Equal-budget `conn_grade` ON vs OFF, both arms finished with the standard finish-time `--collapse`
(94g), 4 workers, canonical `homemaker-fitness` re-score for the `.fails` breakdown:

- **harbor-house** (`init.dom`, budget 2500, seeds 1–3): **byte-identical output** in every seed
  (dom, fail list, fitness all diff-clean ON vs OFF) — the secondary comparator key never fired,
  i.e. the search trajectory never actually hit a tie at fail-count that the grade could break.
  This is the programme §18 was motivated on (2 of 15 fails on the best layout are `not
  connected`), and the signal moved nothing.
- **programme-house** (`init.dom`, budget 3000, seeds 1–5): 3/5 seeds tie exactly (byte-identical
  `.fails`); seeds 1 and 2 diverge to a **different topology** with one fewer total fail (8→7
  each) — but the diff is entirely adjacency/crinkliness/width/access/size fails, not
  connectivity. In all 4 seed-arms across both programmes where a `not connected` fail was
  actually present (harbor 1&3, programme 3&4), the fail is **unchanged** in both arms — zero
  cases of the grade clearing one.
- **Conclusion: the grade does not do what §18 designed it to do.** It occasionally perturbs
  tie-breaking among equal-fail-count neighbours (programme-house seeds 1/2), which can
  incidentally shift the total fail count, but that perturbation never targets circulation
  connectivity specifically — consistent with a comparator key that is either too weak relative
  to the primary `(-n_fails, fitness)` keys to steer topology choice, or whose grade values are
  rarely distinct enough between the actual neighbours the search compares to break a tie in the
  intended direction.

**Status / next.** Kept default OFF (already was). Mechanism (b) (graded proximity as a tertiary
key) is falsified by this A/B, not just unconfirmed — do not re-attempt without a different
mechanism. The remaining candidate from the original issue is mechanism (a): an explicit
insert/relocate-circulation mutation/repair operator, which does not depend on the search
stumbling onto a fail-count tie to act. Not started; low priority per DISCOVERED-FROM epic
`homemaker-py-94g`'s framing (fitness fidelity, not search capability).

## 19. Geometry/topology repair for shape-intrinsic fails (`homemaker-py-7fm`) — DONE (negative)

**Motivation.** §17 established that ~12 of the harbor-house best layout's 15 residual fails
survive the label-only collapse — long-thin cells (`width`/`proportion`/`crinkliness`) whose
geometry, not room assignment, is wrong. `bd memory collapse-global-94g-and-any-label-usage-
optimisation` spun this out as its own problem: a mechanism that moves *geometry*, evaluated for
net fail-count effect on the same 6-layout sweep §17 used.

**Diagnosis (rules out mechanism (a)).** Re-ran the full-fitness ratio inner loop
(`innerloop.optimise`, Nelder-Mead, 1500 evals, warm-started from the evolved ratios — far above
the ~80-200/child budget search actually spends) on the 12-fail collapsed best layout: **zero
change**, byte-identical fail lines. These are not local optima of the ratio search reachable
with more budget. Tracing two representative fails back through the tree found two distinct
structural causes, neither fixable by re-solving ratios on the existing cuts: (1) **area
starvation** — a leaf's *defining branch* (several levels up) was allocated too little total
area for what it has to share with its siblings (a storage leaf wanting 18m² sat in a 6.4m²
branch whose sibling got 52.8m² of outside space); (2) **orientation mismatch** — a leaf is the
correctly-area-sized-but-thin remainder of a cut whose *rotation* runs parallel to its parent
rectangle's long axis, so no ratio value on that axis avoids a sliver.

**Mechanism (`operators.mutate_shape_rotate`, `operators.mutate_deslim`).** Two targeted repair
operators addressing each cause, in the `mutate_level_fix` style (structural, not blind-random):
`_shape_failing(leaf, fit)` identifies a named-room leaf whose width or proportion factor
actually fails (`< FAIL_THRESHOLD` under `Fitness.quality_width`/`quality_proportion` — not a
geometric proxy, which over-flags leaves the Gaussian tail still passes). `mutate_shape_rotate`
re-orients the live cut that produced a failing leaf (targets cause 2); `mutate_deslim` merges a
failing leaf into its sibling, undoing the division that starved it (targets cause 1), leaving
the displaced room for `mutate_place_missing` (already in `MUTATIONS`) to re-insert elsewhere.
Both are registered in `MUTATIONS`/`mutate()`, gated on a `fit` argument (a new `fit_ops` class
alongside the existing `reqs_ops`) so they no-op — and are excluded from the outer search's
`weights` — wherever a `Fitness` instance isn't threaded through, exactly as `place_missing` etc.
gate on `reqs`. `driver.search`/`evolve.py` do **not** yet pass `fit` through (see Status below),
so the operators exist but are currently unreachable from the GA — they were evaluated instead
as a finish-time greedy hill-climb (below).

**Verification (measured, negative).** A finish-time hill-climb applied both operators
exhaustively — for every live cut driving a shape fail, all 3 alternate rotations were tried
(not just `mutate_shape_rotate`'s single random draw) alongside a `deslim` + `place_missing` +
ratio-resolve, keeping the best only if it did not increase the fail count — on the same 6
harbor-house evolved layouts as §17 (total fails 187): **0 improving moves found on any layout,
on any candidate cut, under any of the 4 tried variants.** Manually inspecting the rejected
candidates for the representative case (harbor-house evolved-3M-nols-3, leaf `0/rlrlr` "la1",
the proportion fail traced above) shows why: every one of the 3 rotations and the deslim+
reinsert produced a **worse** layout — new `no outside public access`, `not adjacent to c`,
`access`, or `edge too long` fails, in every trial. This is §4.2's core lesson (proxy/partial-
objective repair of a co-evolved local optimum "is structurally unable to win" — every cut
position is *simultaneously* a size/shape knob **and** an adjacency/access/circulation knob) now
confirmed for structural topology repair, not just ratio-solving: on a tightly co-evolved
layout, the cut that makes a leaf thin is *also* the cut providing some other leaf's public-
access or adjacency, so straightening it elsewhere is not free. The residual geometry-intrinsic
fails on the harbor-house best layout appear to be close to a genuine Pareto floor for this
topology, not a repairable inefficiency — consistent with §17's own framing ("geometry-/
building-bound").

**Status / next.** `mutate_shape_rotate`/`mutate_deslim` land in `operators.py`, default-excluded
from `mutate()` (no `fit` threaded through the outer search yet), with dedicated tests
(`tests/test_operators.py`: fail detection, noop-without-`fit`, targeted-cut selection, merge +
`place_missing` repairability) plus automatic coverage via the existing
`test_mutations_yield_canonical_genomes` parametrisation. 282 tests pass. The finish-time
hill-climb script is **not** productionised (unlike §17's `collapse_cmd.py`) because it never
found an improving move to apply — there is nothing to wire up. Not tested: whether these
operators help as *in-search* GA moves (mechanism (c)) — a full multi-generation run gives
selection pressure and population diversity a chance to accept a locally-worse move that a later
step or recombination completes, a fundamentally different regime from single-step greedy
hill-climbing on an already-finished layout. That A/B (thread `fit` through `driver.search`,
gate with an `enable_shape_repair`-style flag as §12.3 did for `reassociate`, run full-budget
with/without) is the remaining open question and would need to be its own measured experiment
before further code changes — this session's finding is that the *finish-time* half of the
issue's candidate mechanisms is a dead end, not that geometry repair is impossible in general.

**In-search follow-up (measured, 2026-07-22, `homemaker-py-161`) — also negative.**
`driver.search`/`search_staged` gained `enable_shape_repair: bool = False`, threading a cached
`Fitness` instance into `operators.mutate()` only when set (mirrors `enable_reassociate`'s clean-
toggle pattern; default off reproduces prior runs byte-for-byte). Full A/B on harbor-house
`init.dom` cold-start, budget=1,000,000, pop=16, child_budget=80, workers=4, seeds 0–3: fails
`[14,15,12,17]` mean 14.50 (off) vs `[17,14,16,12]` mean 14.75 (on) — no improvement, and the 0.25
delta is far inside the 12–17 seed-to-seed spread in both arms. A smaller pilot (budget=20000, 3
seeds) matched: off mean 31.33, on mean 32.00. In-search selection pressure and population
diversity do **not** rescue `shape_rotate`/`deslim` on harbor-house-scale programmes either — the
residual fails look like a genuine floor for this representation on this programme, not an
inefficiency reachable by richer local operators, in either regime. Code kept (not reverted) for
reuse/reproducibility per the `enable_reassociate` precedent; test
`test_enable_shape_repair_threads_fit_into_mutate` in `tests/test_driver.py`. Both halves of §19's
candidate mechanism space (finish-time and in-search) are now closed negative.

## 20. In-search global collapse (`homemaker-py-qpk`) — DONE (positive, size-dependent)

**Motivation.** §17 (`94g`) landed the FINISH-TIME global cell↔room collapse — a one-shot label
search over the already-searched geometry, applied once to the best layout at the end (harbor-house
best 15→12). The original 94g thrust was the PER-EVAL version: run the same collapse inside every
fitness eval during search, so the outer GA optimises the collapsed (relabelled) objective directly
instead of discovering it only at the end. Deferred behind its own A/B because 9o5 (§13/`xi7`) found
the analogous per-class collapse-as-relaxation NULL/NEGATIVE (OFF beat ON on both example
programmes) — the risk carried forward here, AMPLIFIED to global scope, is that `max`-over-labellings
flattens the fitness landscape (many topologies collapse to similar scores) and removes the gradient
the outer search climbs.

**Mechanism (build).** `Fitness.collapse_global` (§17) is called inside `_evaluate_full`, gated by a
new `collapse_insearch` conf flag (default OFF, bit-identical when off — same contract as `superpose`/
`conn_grade`), at the same point `collapse_superposition` (9o5) already runs: before any Phase-1
check, on the unmerged tree, so `check_space_counts`/adjacency/quality downstream see the collapsed
labels. Two knobs, both conf-driven: `collapse_insearch_adjacency` (default True — the fixpoint
Jacobi relaxation §17 describes) and `collapse_insearch_iters` (default 3, vs finish-time's 6 — a
per-eval cost, not a one-shot polish; lower until profiling says otherwise). `preserve_public_access`
is always on (never safe to drop silently mid-search). Plumbed through the same minimal path as
`conn_grade` (`driver._overrides_for`/`_fitness_for`/`_evaluate`/`search`, `evolve.py
--collapse-insearch` / `HOMEMAKER_COLLAPSE_INSEARCH`) — not threaded into `search_staged`/
`search_annealed`/`polish_finish`, matching `conn_grade`'s existing footprint.

**Verified (build-time).** On `evolved-3M-nols-3.dom` (harbor-house, the §17 15→12 fixture),
`collapse_insearch` reaches the byte-identical 12-fail collapsed state as the finish-time pass —
expected, since it is the same `collapse_global` call moved earlier in the same pipeline on a fixed
geometry. Flag off reproduces baseline score/fails exactly. `tests/test_collapse_insearch.py` (8):
defaults, conf knobs, `_evaluate_full` wiring (mocked call-site assertion: fires with the right
kwargs when on, never when off), and the end-to-end 15→12 cross-check. 290 tests pass. A 60-eval CLI
smoke run (`--collapse-insearch`, programme-house) confirms the plumbing only, no crash — not a
result (mirrors qi6's smoke-only checkpoint).

**Cost (measured, `evolved-3M-nols-3.dom`, 20-eval average).** Baseline eval 106 ms; with
`collapse_insearch` + adjacency 205 ms (**1.9×**); adjacency off 157 ms (1.5×). Per-eval cost is
therefore real but not prohibitive at this building size — no incremental/cached variant was needed
to make the experiment affordable, contrary to the issue's worst-case worry. A full-budget run will
cost roughly 2× the wall-clock of an equal-budget baseline run.

**A/B verdict (measured, 2026-07-19, xi7 protocol) — POSITIVE, and the OPPOSITE of the 9o5/xi7
prior.** Equal-budget `collapse_insearch` ON vs OFF, both arms finished with the standard
finish-time `--collapse` (94g) so the comparison is apples-to-apples on the final COLLAPSED score,
4 workers:

- **harbor-house** (`init.dom`, budget 2500, seeds 1–3): **ON wins 3/3**, mean fails 80.3 → 72.0
  — **WITHDRAWN, see §38.21.** Re-measured at n=24 this arm is null (+1.21 fails, p = 0.50,
  13W/10L/1T). Harbor's paired σ ≈ 6.2 fails means n=3 could only resolve a margin above ~15,
  and 25% of 3-seed subsets show a 3/3 sweep by chance. The default rests on programme-house.
  (s1 85→74, s2 76→65, s3 80→77) — a consistent ~10% fail reduction, no losses.
- **programme-house** (`init.dom`, budget 3000, seeds 1–5): ON wins 3/5, mean fails 8.4 → 7.8
  (s1 8→5, s2 8→7, s4 10→9 win; s3 8→9, s5 8→9 loss by one fail) — a weaker, noisier signal on
  this much smaller building, already closer to its geometry floor (§13/§19).
- **Combined head-to-head: ON 6, OFF 2.**

Unlike 9o5 (a per-CLASS relaxation over interchangeable-but-not-identical codes, where `max`-over-
labellings blurred which topology was actually good), the global WFC-style matching here is the
*same* mechanism §17 already proved monotone/positive at finish time — running it every eval just
lets the outer search see the condensed objective instead of discovering it only once, and evidently
that gradient is real, not flattening, at least at the scale tested. The effect scales WITH building
size (more leaves → more relabelling headroom per eval), the opposite of what the 9o5 fear predicted.

**Cost (wall-clock, matches the profiled 1.5–1.9× per-eval figure above).** harbor-house mean
102.6s (OFF) → 177.8s (ON), ~1.73×. programme-house mean 39.0s (OFF) → 43.7s (ON), ~1.12× (smaller
building → collapse is a smaller fraction of total eval cost).

**Status (2026-07-19).** Kept **default OFF** — the programme-house result is too mixed (2 losses in
5 seeds) to flip the default on a small sample, and 9o5/xi7 is a fresh enough scar to want a second,
larger-budget confirmation before doing so. But this is a genuine, working, opt-in improvement for
larger buildings: `--collapse-insearch` is documented and ready to use on harbor-house-scale (or
bigger) programmes today. A natural follow-up (not filed, low priority) would be a larger-N seed
sweep on programme-house alone to see whether the mixed result is just small-sample noise around a
true small positive, or a genuine size threshold below which in-search collapse doesn't pay for its
~1.1–1.9× cost.

**Larger-N confirmation (`homemaker-py-1ph`, 2026-07-24) — DEFAULT FLIPPED TO ON.** Re-ran the
programme-house arm alone at 4× the sample: same protocol (`init.dom`, budget=3000, 4 workers, both
arms finished with the standard finish-time `--collapse`), 20 fresh seeds (1–20) instead of 5, on
the current codebase (post-qpk commits through `161`, none of which touch the default-off code
path):

- Mean fails: **7.95 (OFF) → 7.10 (ON)**, a ~10.7% reduction — consistent in direction and
  magnitude with the original 5-seed sample (8.4 → 7.8) and with harbor-house.
- Head-to-head (excluding 3 ties): **11 wins / 6 losses** for ON (was 3/2 at N=5).
- Paired t-test on the 20 per-seed diffs: mean diff 0.85 fails, t=2.38, df=19, two-tailed
  **p ≈ 0.028** — the mixed 3/5 result was small-sample noise around a true small positive, not a
  genuine programme-house-scale exception.
- Cost: ON still ~1.2–1.3× OFF wall-clock at this size (20.9s mean OFF → 26.4s mean ON), same order
  as the original measurement.

**Re-validated under the current objective (`homemaker-py-ioe`, §38.19):** the default still
stands, but the margin is about a third smaller (+0.57 fails/seed against the +0.85 below) and is
**no longer detectable at this section's N=20** (p = 0.085 there); it takes N=60 to reach
p = 0.017. Do not re-check this default at N=20.

Confirms the qpk verdict holds at both example scales tested. `collapse_insearch` default flipped
**OFF → ON** in `evolve.py` (`--collapse-insearch`/`--no-collapse-insearch`,
`HOMEMAKER_COLLAPSE_INSEARCH`) and `driver.py` (`_overrides_for`, `_fitness_for`, `_evaluate`,
`search`, `polish_finish`) — opt out per-run with `--no-collapse-insearch` if a specific programme
needs the cheaper finish-time-only path. `fitness.Fitness` itself is unchanged (still defaults off
when `collapse_insearch` is absent from conf — the default lives in the driver/CLI override layer,
same contract as `leaf_sharing`).

**Caveat added retroactively (`homemaker-py-iio`, 2026-08-02).** A stale-leaf-share bug (§35) meant
every `collapse_insearch=ON` eval during this era's runs (and any leaf-sharing run's finish-time
`--collapse`) could occasionally value one candidate cell of the collapse assignment using leftover
`share`/`share_type` metadata from a code the leaf no longer held. §35's re-verification shows this
is real per-seed noise (not a directional bias) that does not appear to overturn the ON-beats-OFF
verdict above, but the exact historical per-seed numbers quoted in this section were not re-measured
under the fix. See §35 for the mechanism and what was (and wasn't) re-confirmed.

**Caveat DISCHARGED for this section (`homemaker-py-d86`, §38.18).** The 1ph protocol has now been
re-run at N=20 on a pre-iio commit with and without the fix backported: all 40 (seed, arm) cells are
identical, and the reason is structural rather than lucky — programme-house declares `count: 1` for
every code, so no leaf ever acquires a share and the stale-share bug cannot fire on this programme
at all. The numbers above stand. The caveat remains live for harbor-house/qpk, where shares do exist
and §35 measured real divergence.

## 21. Insert/relocate-circulation repair operator (`homemaker-py-8sh`) — DONE (mixed, kept off)

**Motivation.** qi6's remaining candidate (§18): mechanism (a), an explicit search-time
mutation/repair operator that inserts or relocates a circulation cell to bridge a disconnected
circulation component directly, rather than relying on the outer GA to discover connectivity via a
comparator-key gradient (mechanism (b)/(c), measured NEGATIVE — the grade never fired on
harbor-house and never cleared a genuine `not connected` fail on programme-house).

**Mechanism (build).** `operators.mutate_bridge_circulation`: for each storey, builds the leaf
adjacency graph (`geometry.leaf_graph`) and the circulation sub-components (`dom.is_circulation`
nodes only, mirroring `graph.connected_circulation`'s subgraph). When a storey has more than one
component, finds the cheapest path between any pair via a weighted Dijkstra search — edge weight is
the average of its endpoints' conversion cost (`0` for an already-circulation node or a generic
outside `O` leaf — nothing displaced, same rationale as `place_missing`'s host ranking; `1` for any
other non-required leaf; `5` for a leaf typed as a required programme room, crossed only if no
cheaper route exists) — and retypes every intermediate leaf on the cheapest cross-component path to
`C`. A displaced required room becomes a missing-space fail for the existing `place_missing`
operator to re-insert elsewhere on a later step, the same division of labour `mutate_deslim` (§19)
uses. Registered in `operators.MUTATIONS` as a "`reqs`-optional" op — unlike `level_fix`/
`place_missing` it is never zero-weighted for lacking `reqs` (it needs only the tree's own adjacency
graph), so gating is done the `reassociate` way instead: `driver.search`'s new
`enable_bridge_circulation` flag (default OFF) zeroes its `mutation_weights` entry rather than
relying on an argument being `None`. Threaded through `search_staged` and exposed as
`evolve.py --bridge-circulation` / `HOMEMAKER_BRIDGE_CIRCULATION`. 6 unit tests
(`tests/test_operators.py`): noop when already connected, bridges a synthetic 3-leaf fragmented
fixture via the free leaf, falls back to bridging through a required room when it is the only route,
and prefers a free `O` leaf over a required room when both routes tie in hop length. 296 tests pass.

**A/B verdict (measured, 2026-07-24, qi6/qpk protocol,
`experiments/run_8sh_ab.sh`).** Equal-budget `enable_bridge_circulation` ON vs OFF, both arms
finished with the standard finish-time `--collapse` (94g), 4 workers, canonical `homemaker-fitness`
re-score for the `.fails` breakdown — harbor-house (`init.dom`, budget 2500, seeds 1–3),
programme-house (`init.dom`, budget 3000, seeds 1–5):

| programme | seed | fails OFF→ON | not-connected OFF→ON |
|---|---|---|---|
| harbor-house | 1 | 74→67 | 0→**2** |
| harbor-house | 2 | 65→65 (byte-identical) | 1→1 |
| harbor-house | 3 | 77→77 (byte-identical) | 1→1 |
| programme-house | 1 | 5→5 (tie, fitness differs) | 0→0 |
| programme-house | 2 | 7→7 (tie, fitness differs) | 0→0 |
| programme-house | 3 | 9→7 | 1→1 |
| programme-house | 4 | 9→8 | 1→**0** |
| programme-house | 5 | 9→7 | 1→**0** |

Total fails: harbor-house mean 72.0→69.7, programme-house mean 7.8→6.8 — **never worse** on any
seed (4 wins, 4 ties, 0 losses on total fail count across both programmes). Of the 5 seed-arms
whose OFF baseline actually had a `not connected` fail, **2/5 cleared it** (programme-house seeds
4 and 5) — a genuine improvement over qi6 mechanism (b)'s 0/4. But harbor-house seed 1 shows the
flip side: its OFF baseline had *no* `not connected` fail (0), and ON introduces **two** — while
simultaneously landing the sweep's single largest fail-count win (74→67, fitness 3.2e-26→5.0e-24,
almost two orders of magnitude apart) via a visibly different topology, not a locally-adjusted one.
`mutate_bridge_circulation` only ever converts a leaf *to* circulation, never away from it, so it
cannot mechanically increase fragmentation itself — the regression is trajectory-divergence noise
(adding any nonzero-weight entry to `operators.mutate`'s weighted draw perturbs the RNG mapping for
*every* subsequent draw, not just the ones that select the new operator, exactly as observed for
`enable_reassociate`/`enable_shape_repair`/homemaker-py-161 — the same-seed off/on comparison is
two genuinely different searches from the same seed, not a controlled single-variable diff). Two of
the three harbor-house seeds never diverged at all (byte-identical fitness to 6 significant figures)
— at `_MUTATION_WEIGHTS`' default uniform weighting the operator is drawn roughly 1-in-17 times a
mutation fires, and evidently often never lands on a fragmented storey within a 2500-budget run.

**Status.** Directionally positive and clearly better-targeted than qi6's graded signal (which
cleared zero `not connected` fails in its own measured protocol), but the N=3/N=5 sample is too
small and too trajectory-noisy to separate a true small positive from chance, per the same caution
`collapse_insearch` was held to before its `homemaker-py-1ph` larger-N confirmation. Kept **default
OFF** (`enable_bridge_circulation=False` in `driver.search`/`search_staged`,
`--no-bridge-circulation` in `evolve.py`). Candidate follow-ups, not yet filed: (a) a larger-N seed
sweep (the `1ph` protocol) to resolve whether the mean improvement is real; (b) raising
`bridge_circulation`'s `_MUTATION_WEIGHTS` entry above the uniform default (mirroring
`place_missing`'s `2.0`) so it fires more often per budget, since a `not connected` fail is exactly
as fatal to fitness as a missing space and the operator is currently drawn no more eagerly than
cosmetic ops like `rotate`. See §22 for the larger-N confirmation of both follow-ups — **result:
null, weight change reverted, default stays OFF.**

## 22. bridge_circulation larger-N + weight confirmation (`homemaker-py-lj3`/`homemaker-py-qjg`) — DONE (null)

**Motivation.** §21's two identified follow-ups — (a) a `1ph`-style larger-N seed sweep to resolve
whether 8sh's small positive mean-fail improvement was real or small-sample noise, and (b) raising
`bridge_circulation`'s `_MUTATION_WEIGHTS` entry to `2.0` (matching `place_missing`) so it fires
more often — were filed as separate beads (`lj3` for the weight, `qjg` for the sample size) but
`lj3`'s own description flagged them as confounded if tested separately: weight and sample-size are
different variables, and a real effect from raising the weight could get masked or amplified by the
same small-N noise that made §21 inconclusive in the first place. Tested together in one sweep
instead of two.

**Protocol.** `driver._MUTATION_WEIGHTS["bridge_circulation"] = 2.0` (matching `place_missing`,
still zeroed via `mutation_weights` unless `enable_bridge_circulation` is set — no behaviour change
for the default-off path). Same qpk/1ph protocol as §20/§21: equal-budget ON vs OFF, both arms
finished with the standard finish-time `--collapse` (94g), 4 workers, canonical `homemaker-fitness`
re-score for the `.fails` breakdown, `experiments/run_lj3_qjg_ab.sh`. Matching 1ph's own 4× scale-up:
programme-house (`init.dom`, budget 3000) 20 seeds (1–20, vs §21's 5), harbor-house (`init.dom`,
budget 2500) 12 seeds (1–12, vs §21's 3).

**A/B verdict (measured, 2026-07-25) — NULL, opposite of §21's directional signal.**

- **programme-house (N=20):** mean fails 7.10 (OFF) → 6.95 (ON), mean per-seed diff 0.15 fails.
  6 wins / 5 losses / 9 ties for ON. Paired t-test on the 20 diffs: t=0.38, df=19,
  two-tailed **p≈0.71** — indistinguishable from zero.
- **harbor-house (N=12):** mean fails 71.8 (OFF) → 72.3 (ON), mean per-seed diff **−0.5** fails (ON
  slightly worse on average). 4 wins / 4 losses / 4 ties. Paired t-test: t=−0.41, df=11,
  two-tailed **p≈0.69** — also indistinguishable from zero.
- **Connectivity-specific effect, and the concerning part:** of the 10 programme-house seeds whose
  OFF baseline had a genuine `not connected` fail, 4 cleared it on ON (seeds 3, 4, 5, 6) — but 3
  *new* `not connected` fails appeared on seeds whose OFF baseline had none (seeds 1, 9, 13), a
  higher new-fail rate than §21's original uniform-weight sweep saw (0/5 programme-house seeds
  introduced a new not-connected fail at N=5; here 3/20 = 15% did at the raised weight). harbor-house
  cleared 1/10 and introduced 0 new, but its total-fail mean still went the wrong way.
  `mutate_bridge_circulation` still only ever converts a leaf *to* circulation, never away — the new
  fails are §21's trajectory-divergence mechanism (a nonzero-weight operator entry perturbs the RNG
  draw sequence for every subsequent mutation, not just its own draws), and raising the weight
  increases how often that perturbation-inducing draw happens, which plausibly explains why the
  new-fail rate went up rather than down.
- **Cost:** essentially unchanged from §21 — programme-house 28.1s (OFF) → 28.1s (ON, 1.00×),
  harbor-house 130.0s (OFF) → 132.6s (ON, 1.02×).

**Interpretation.** §21's 4-win/4-tie/0-loss, 2/5-not-connected-cleared result at N=3/N=5 was small-
sample noise around a true near-zero effect, not a genuine small positive — the same question 1ph
asked of `collapse_insearch` (§20), but here the larger-N answer goes the other way: not confirmed.
Raising the mutation weight did not help and, if anything, correlates with a worse trajectory-noise
profile (more new not-connected fails per seed) than leaving it at the uniform default, consistent
with the weight bump increasing how often the RNG-perturbing draw fires.

**Status.** `_MUTATION_WEIGHTS["bridge_circulation"] = 2.0` **reverted** — back to the implicit
uniform weight (not present in `_MUTATION_WEIGHTS`), matching pre-`lj3` behaviour exactly.
`enable_bridge_circulation` stays **default OFF**. No further weight/sample-size follow-up planned;
`operators.mutate_bridge_circulation` remains available opt-in
(`--bridge-circulation`/`HOMEMAKER_BRIDGE_CIRCULATION`) for anyone who wants the connectivity-
targeting behaviour despite the neutral aggregate measurement, but is not a candidate for a default
flip on the current evidence.

## 23. Ruin-and-recreate LNS: rebuild a wing with the adjacency-aware constructor (`homemaker-py-f1d`) — DONE (positive, size-dependent)

**Motivation.** DESIGN.md's own experiment log by this point is one-sided: every "search machinery"
change tried (§11.5 niching+restarts, §11.4 graded objective, §12.3 Wong-Liu reassociation +
shape-feasibility, §12.4 granularity, §14 island model, §16 grain annealing, §18 graded
connectivity, §19 shape repair, §21/§22 circulation-repair ops) has come back null-to-negative,
while construction/seeding QUALITY (§11.6/§11.7 adjacency-aware seeding, §12.2 proportion-aware
seeding) is the only lever that has ever moved the fail count. `operators._assign_adjacency_aware`
— the constructor behind both `constructive_topology` and `lift_base_to_storeys` — currently only
ever runs once, at seeding. The proposal: reuse it repeatedly DURING search as a large-neighbourhood-
search (LNS) ruin-and-recreate move, betting that the one technique with a real track record
generalises better than another new comparator-key or population-management idea.

**Mechanism (build).** `operators.mutate_ruin_recreate`: pick a divided, live-cut subtree ("wing")
of one storey holding a genuine partial neighbourhood of that storey's leaves (>=2, <= half — not a
single-leaf relabel already covered by `retype`/`swap`, not a whole-floor rebuild already covered by
the initial seed), un-divide it back to one leaf, then regrow and retype it with
`_assign_adjacency_aware`, seeded (`fixed_circ`) from whichever already-typed circulation leaves
border the wing — the same mechanism `lift_base_to_storeys` uses to grow an upper storey off an
inherited core (§11.7), so the rebuilt interior spine reconnects to the surviving one instead of
growing a disconnected island. The wing's required-space room-code budget is preserved exactly
(same multiset); only its internal circulation/outside counts and split are rebuilt, at the same
circ_divisor=3/outside_divisor=3 ratio the constructive seeders default to (not threaded from the
run config — kept parameter-light, like `bridge_circulation`).

`_assign_adjacency_aware` gained a new `scope` parameter (leaves eligible for retyping; `fixed_circ`
may then name border leaves OUTSIDE `scope` as dominating-set seeds only, never retyped) so the wing
rebuild can share the exact constructor code without touching the rest of the storey. `scope=None`
(every existing caller) reproduces the prior unrestricted behaviour exactly — verified no other
caller's output changed. Gated like `reassociate`/`bridge_circulation`: zero mutation weight unless
`enable_ruin_recreate=True` (`driver.search`/`search_staged`, `evolve.py
--ruin-recreate`/`HOMEMAKER_RUIN_RECREATE`, default off).

**Verified (build-time).** 200 applications of `mutate_ruin_recreate` chained onto fresh
`constructive_topology` harbor-house seeds (40 seeds × 5 steps): zero missing-space regressions
(`graph.check_space_counts`), every child a canonical genome (`encode(decode(encode(x))) == encode(x)`).
297 existing tests pass unchanged (the new op is exercised by the existing
`test_mutations_yield_canonical_genomes` parametrization, which calls it with `reqs=None` and gets
the documented noop). A `child_probe`-instrumented `driver.search` run confirmed the operator is
actually selected by `mutate()` at its configured weight (not dead code).

**Initial A/B (measured, 2026-07-25/26, qpk protocol) — NULL, but underpowered.** Equal-budget
`enable_ruin_recreate` ON (implicit uniform mutation weight, ~7.5% draw probability among ~13 active
ops) vs OFF, both arms finished with the standard finish-time `--collapse` (94g), 4 workers:

- **harbor-house** (budget 2500, seeds 1–3): 1 loss (74→81), 2 ties.
- **programme-house** (budget 3000, seeds 1–5): 4 ties, 1 win (9→8).
- **Combined: 1 win / 1 loss / 6 ties out of 8**, mean fails 31.9 (OFF) → 32.6 (ON) — indistinguishable
  from zero, in the same direction as most of this log's other null results.
- A direct `child_probe` instrumentation of one of the tied harbor-house runs found
  `ruin_recreate` fired **once in 32 children** — the initial sample is dominated by trajectories
  where the operator simply never got a turn, not by turns it lost. Six of the eight exact ties
  (fitness scalar identical to 6 significant figures, not just fail count) are consistent with
  this: the op's rare draws mostly didn't survive tournament selection into the recorded lineage.

**Weight follow-up (measured, 2026-07-26) — reran the ON arm only** with
`_MUTATION_WEIGHTS["ruin_recreate"] = 3.0` (matching `place_missing`, mirroring the `lj3` weight-bump
precedent) at the same seeds/budgets, directly comparable to the existing OFF baseline:

- **programme-house** (seeds 1–5): **4 wins, 1 tie, 0 losses** — 7→1, 9→7, 9→8, 9→7, 5→5. A striking,
  one-sided result, including one seed dropping from 7 fails to 1 (verified deterministic on rerun).
- **harbor-house** (seeds 1–3): 1 win (77→73), 1 loss (74→82), 1 tie — still mixed.

**Larger-N confirmation (measured, 2026-07-26)** — extended both arms to 10 fresh programme-house
seeds (6–15) and 5 fresh harbor-house seeds (4–8) at the same weight=3.0, same protocol:

- **programme-house, all 15 seeds combined: 8 wins / 1 loss / 6 ties.** Mean fails **7.07 (OFF) →
  6.00 (ON)**, a ~15% reduction. Wilcoxon signed-rank p≈0.041; sign-test p≈0.020 (one-sided) — holds
  up at conventional significance, not small-sample noise around zero (the 8sh/1ph/qi6/lj3 pattern
  this log warns about).
- **harbor-house, all 8 seeds combined: 3 wins / 2 losses / 3 ties.** Mean fails **73.0 (OFF) → 74.5
  (ON)** — no consistent effect, if anything a very slight negative lean, echoing §20's
  (`collapse_insearch`) opposite-direction size split but with the SMALLER building this time as
  the one that benefits.

**Interpretation.** A rare case in this log where a search-machinery idea shows a real,
statistically-supported effect — but only on the smaller/simpler example programme. Plausible
reading: programme-house's smaller room count means a wing rebuild samples a much larger fraction of
the whole floor's topology per move (higher effective locality-vs-scope ratio), so the constructor's
proven adjacency-aware placement quality dominates; harbor-house's much larger room count means the
same wing size is a small, noisier perturbation relative to the whole building, and correlates with
the ~2× per-op cost of `_assign_adjacency_aware` (leaf-graph rebuild + dominating-set search) not
translating into more useful search steps within the same eval budget on that scale.

**Status (2026-07-26).** `enable_ruin_recreate` stays **default OFF** — harbor-house shows no
benefit and the two example programmes disagree on direction, so flipping the global default is not
supported by this evidence (same conservative bar §20 applied before its own larger-N confirmation).
`_MUTATION_WEIGHTS["ruin_recreate"] = 3.0` is kept in the source (only takes effect when the flag is
on) since it is the validated-effective setting. `--ruin-recreate`/`HOMEMAKER_RUIN_RECREATE` is
documented and ready to use today on programme-house-scale (smaller/simpler) programmes; a natural
follow-up (not filed, low priority) would be a third or fourth example programme at a size between
the two tested here, to locate the size threshold this result implies rather than inferring it from
just two data points.

## 24. Ruin-and-recreate size-threshold sweep (`homemaker-py-y51`) — INCONCLUSIVE, no clean threshold

**Motivation.** §23's follow-up: locate the room-count threshold where `ruin_recreate` (weight=3.0)
stops helping, rather than inferring it from programme-house (6 rooms, win) vs harbor-house (37 room
instances, null/slight-negative) alone.

**No natural third example exists.** `programme-house2` is the same 6-room size as programme-house
(a geometry-fix variant, not a size variant); `maple-court` (26 space *types*, many with `count`,
~more room instances than harbor-house) is bigger than harbor-house, not between the two. So this
used option (b) from §23: a synthetic room-count sweep on programme-house's own `patterns.config`,
scaling the `b1`/`t1`/`b2`/`t2` bedroom+ensuite module count by an integer factor (k=2..5 → 10/14/18/22
room instances), holding room-type mix, storey limits, ratios and adjacency constant, with the
footprint (`init.dom`) scaled in area to match (`examples/y51-sweep-{10,14,18,22}`). budget=3000
calibrated so every size leaves nontrivial residual fails at seed 1 (14/29/27/43), not saturated to 0.

**Measured (2026-07-26, `experiments/run_y51_sweep.sh` + `run_y51_sweep_ln.sh`)** — paired seeds,
`--ruin-recreate` (weight=3.0) ON vs OFF, both arms finish with the default `--collapse` (94g), 4
workers. Initial pass: 5 seeds at every size. Larger-N confirmation: 5 more seeds (N=10 total) at the
two sizes whose initial 5-seed read was most striking (n=14, the only size that initially *lost*;
n=18, the strongest initial win) — mirroring this log's own larger-N-confirmation pattern.

| n_rooms | N  | W/L/T   | mean fails OFF→ON | Δ%    | Wilcoxon p |
|---------|----|---------|--------------------|-------|-----------|
| 10      | 5  | 3W/1L/1T | 17.80 → 16.40     | +7.9%  | 0.625 |
| 14      | 10 | 3W/5L/2T | 28.90 → 28.70     | +0.7%  | 0.945 |
| 18      | 10 | 7W/2L/1T | 36.50 → 33.10     | +9.3%  | 0.098 |
| 22      | 5  | 2W/3L/0T | 41.20 → 40.80     | +1.0%  | 0.875 |

**Interpretation.** This does **not** reproduce a clean monotonic decay of the effect as room count
rises from programme-house's 6 to harbor-house's 37. n=14 came back a clean null after larger-N
confirmation (the initial 5-seed 0W/4L read did not hold — noise, exactly the pattern this log
repeatedly warns about). n=18 shows the strongest trend of the four synthetic sizes (a plausible-but-
not-quite-significant ~9% mean improvement, p≈0.10) despite sitting *between* two much weaker/null
sizes (14 and 22) — a non-monotonic bounce inconsistent with a simple "smaller wing-rebuild-to-floor
ratio → bigger effect" threshold as a function of room count alone.

Two readings, not mutually exclusive:
1. **Still underpowered.** §23's own programme-house confirmation needed N=15 seeds to reach p=0.041
   for a similar-magnitude effect (~15% reduction); N=5/N=10 here is likely too little to resolve an
   effect this size cleanly at any of these sizes, so the bounce may just be sampling noise on top of
   a real but weak trend across 10-22 rooms.
2. **Methodological caveat: this sweep is not a clean proxy for "room count."** It scales room count
   by *duplicating already-anonymous, already-interchangeable* room codes (`count:` on b1/t1/b2/t2) —
   the same mechanism harbor-house itself uses "to reduce complexity" (its own patterns.config
   comment). Duplicating interchangeable codes may make placement systematically *easier* for
   `_assign_adjacency_aware` than harbor-house's mix of many genuinely distinct room types at the same
   instance count would be, so this sweep's room-count axis may not isolate the same "topology
   fraction sampled per wing move" variable that §23 hypothesised drives the effect.

**Status (2026-07-26).** `enable_ruin_recreate` stays default OFF; no per-size default flip is
supported by this evidence — the sweep did not locate a clean threshold. §23's practical guidance
(safe to opt in on programme-house-scale, ~6-room programmes; not validated at harbor-house scale)
stands unchanged. A real follow-up, if pursued, needs either (a) much larger N (~15+ seeds) at a
smaller set of sizes to resolve whether the n=18 trend is real, or (b) a genuinely distinct third
example programme (real room-type diversity at an intermediate room count, not a duplicated-code
sweep on programme-house) to avoid the interchangeable-room confound above.

## 25. 2-opt local search past the collapse_global Jacobi plateau (`homemaker-py-9wi`) — DONE (positive, opt-in)

**Motivation.** §17's `collapse_global` adjacency relaxation is a Jacobi/WFC-style loop: each round
re-solves a *linear* assignment (`_best_assignment`) using an adjacency bonus computed from the
*previous* round's neighbour labels. That is exact per round, but the true objective is quadratic — a
satisfied adjacency depends on a **pair** of labels, not one — so synchronous Jacobi can plateau short
of the joint optimum. Worked example (`test_two_opt_polish_escapes_jacobi_plateau`): a 4-cell chain
`p1─q1─p2─q2` with two disjoint adjacency requirements (`p1<->p2`, `q1<->q2`) has a fully-satisfying
relabelling (`p1─p2─q1─q2` or similar), but starting from the interleaved layout the Jacobi loop
**2-cycles** between two labellings that each satisfy **zero** of the four requirements, and never
escapes within `iters`.

**Mechanism (`Fitness._two_opt_adjacency_polish`).** Runs once, after the Jacobi loop reaches its
fixpoint (or exhausts `iters`). For every **same-level** pair of supply leaves, try swapping their
current labels; keep the swap only if it **strictly** increases the total reward (own quality/threshold
value + `fail_w` per satisfied adjacency) summed over the two leaves and every leaf adjacent to either
— the only cells a label swap between `i` and `j` can change. Repeats to a fixpoint (or
`local_search_passes`, default 20). Same-level-only pairing keeps the hard level constraint for free
(both codes already matched their own leaf's level pre-swap, and the two leaves share a level, so the
swap is valid on both sides). A swap is applied only on strict improvement, so this is **monotone by
construction** — it can only reduce, never increase, the objective's implied fail count, same guarantee
as the Hungarian solve it refines. `Fitness._collapse_value` factors the shared (leaf, code) → base-value
computation out of the `collapse_global` assignment-matrix build so both the matrix and the polish score
a pair identically.

**Why 2-opt over CP-SAT/OR-Tools.** The issue proposed either a 2-opt local search or a CP-SAT (OR-Tools)
encoding of the labelling QAP. Went with 2-opt: no new dependency (the project has no `ortools`), and it
extends the existing Jacobi machinery directly rather than replacing it with a separate solver. QAP is
NP-hard in general, so this is a local search, not an exact solve — but it strictly dominates the
Jacobi-only result by construction, and `collapse_finish`'s keep-better wrapper is an additional safety
net regardless.

**Wiring.** `collapse_global(local_search=False, local_search_passes=20)` — the method-level default
stays off (see §28: it's also called every fitness eval via `collapse_insearch`/`qpk`, a hot path this
polish was never measured against). `homemaker-collapse --local-search`/`--no-local-search` and
`evolve.py`'s `--collapse` now default it **on** at the one-shot finish-time call sites — see §28
(`homemaker-py-cdl`) for the broader sweep and wiring that flipped those defaults.

**Verification.** Swept all 11 harbor-house `evolved-*`/`3m`/`materialised-3M` `.dom` files, comparing
`collapse_global(local_search=False)` against `local_search=True`: 10/11 matched exactly (Jacobi was
already at the 2-opt-local optimum on those layouts), **0 regressed**, 1 improved
(`evolved-anneal-3M.dom` 21→19 fails — resolved a genuine mutual `da1<->k1` adjacency miss the Jacobi
loop couldn't reach). Runtime <1s even on the largest file (`evolved-3M.dom`, 90 base fails). §28 extends
this to a 46-file sweep and turns the finish-time default on. Tests:
`tests/test_collapse_global.py` gains `test_two_opt_polish_escapes_jacobi_plateau` (7 total in that file);
298/298 pass project-wide.

## 26. Multi-use leaves / type superposition (`homemaker-py-9o5`/`xi7`/`b3v`) — DONE (negative), backfilled

*Closed 2026-06-30 (`9o5`, `xi7`) / 2026-07-17 (`b3v`); written up retroactively — this section was
missing when §17/§20 above were written, even though both reference its verdict directly ("mirrors
9o5", "the opposite of the 9o5/xi7 verdict"). Numbered at the end of the log rather than renumbering
§14-§25 to preserve every existing cross-reference.*

**Motivation.** A leaf that legitimately serves several DIFFERENT compatible programme codes at once
(study+guest bedroom, kitchen+dining — Stewart Brand's "loose-fit" long-life rooms), distinct from
§13.3 leaf-sharing which aggregates *k* instances of the *same* code. Two readings were scoped: (a)
superposition as a SEARCH RELAXATION — carry an uncommitted set of candidate types per leaf during
search, collapse (argmax re-type) to specific usages only at scoring time, for a smoother landscape;
(b) multi-use as the permanent DESIGN GOAL, surviving into the output with no collapse. Path (a) was
built and validated (below); path (b) was never started.

**Mechanism (path a, built).** `programme.derive_interchange_classes`: codes form an equivalence class
(connected component, size ≥ 2) under a symmetric `interchangeable()` relation — S1 both sized and
non-generic (no `c`/`o`/`s`), S2 size/width/proportion targets within LOCKED ratio bounds (`R_SIZE=1.5`,
`R_WIDTH=1.3`, `R_PROP=1.5`), S3 compatible level and service stack, S4 no direct required-adjacency
edge between the two codes (adjacency pairs are coexisting rooms, not one substitutable leaf). Pure
function of the parsed programme — classes are auto-derived, no hand-authored list needed on the happy
path. `Fitness.collapse_superposition` re-types every superposed leaf to its best in-class usage each
eval, before any check: per class, an optimal supply (leaves currently in the class) → demand (class
codes × required count) matching, area-weighted usage quality as the objective (brute-force ≤`CLASS_CAP`
= 4! permutations, else scipy Hungarian — the same `_best_assignment` §17/§25 later reuse at global
scope). Runs on the UNMERGED tree, so counts/adjacency/quality downstream see the condensed types with
**no changes needed** to `graph.py`/`dom.py`/`operators.py` — the key design realisation was that
because collapse re-types at eval time, `Node` never needs a persisted class/serves field and no
mutation operator needs a "retype within class" move; the genome can carry *any* in-class type and
collapse fixes it. Gated behind `superpose` (default OFF, bit-identical when off — verified against
233 pre-existing tests). `tests/test_superposition.py` (20): derivation (service/adjacency/level
guards, the real programme-house programme), assignment (brute force + Hungarian + surplus supply/demand),
end-to-end collapse re-typing, veto-hatch behaviour.

**A/B verdict (`xi7`, measured 2026-06-30) — NULL/NEGATIVE.** Equal-budget `--superpose` ON vs OFF,
measuring the COLLAPSED (final) score:
- **programme-house** (`init.dom`, budget 3000, 4 workers, seeds 1–5): OFF wins 4/5 (s1 8f>10f, s2
  11f>12f, s3 10f>12f, s4 10f>10f-tied-fitness — all OFF strictly better or equal fails), ON wins only
  s5 (10f→8f).
- **harbor-house** (`init.dom`, budget 2500, seeds 1–3): OFF wins 2/3 (s2 33f<38f, s3 43f<48f); ON
  wins s1 alone (50f<51f).
- Superposition does **not** reach better layouts; in most seeds ON has ≥ OFF fails — the per-eval
  collapse re-typing perturbs counts/adjacency rather than smoothing the search, the same failure
  mode later sections would call "landscape flattening."

**Relaxation-gap instrumentation (`xi7` §7.4) — ruled OUT as the cause.** Logged relaxed (unconstrained
best-case usage-quality) vs collapsed value on the same matched leaves across the 5 programme-house ON
runs: total `gap_ratio` 1.01–1.23 (per-class peaks up to 1.52) — small-to-moderate, not the large gap
the original risk note feared. Because collapse is *per-eval*, there is no separate relaxed phase to
diverge from — search already optimises the collapsed objective by construction. **Conclusion: path
(a) underperforms not from a relaxation gap but because the geometry floor (§11–§13) dominates** — type
labels are not the binding constraint on these programmes, so easing them buys nothing while the
re-typing adds feasibility noise. This is the diagnosis §20 (`qpk`) later cites when arguing its own
in-search collapse is a *different* mechanism (a hard-constraint-respecting global relabel, not a
per-class relaxation over interchangeable-but-not-identical codes) and so isn't pre-falsified by this
verdict.

**Veto hatch (`b3v`, closed 2026-07-17) — the one real false-positive found.** Harbor-house's programme
auto-derives a **transitive 8-code chain** `{da1,ef1,k1,la1,m,me1,n,ws1}` spanning a 6× size range
(Meeting 10 m² .. Dining/Neighbourhood 60 m²) — semantically nonsensical (Meeting↔Dining↔Kitchen↔
Mechanical are not interchangeable) but sanctioned by the S1–S4 relation as written (each adjacent pair
in the chain individually satisfies the ratio bounds; connectivity is transitive). `xi7`'s harbor-house
losses show ON *adding* fails in both loss seeds (38→33 became 38 vs 33; 48→43 became 48 vs 43) —
consistent with this misgroup actively hurting. Fix: `SpaceReq.interchange` (default `True`), settable
`interchange: false` per code in `patterns.config`, honoured by `interchangeable()`'s S0 check — an
architect veto for one code without disabling superposition globally. `superpose` itself stays default
OFF regardless (the `xi7` verdict was null/negative overall), so the hatch only matters if/when
superposition is deliberately enabled on a real config.

**Status.** `--superpose` stays default OFF; path (a) is not recommended without a fundamentally
different mechanism (the geometry floor, not the labelling relaxation, is what needs to move — the
same conclusion §11–§13's construction-quality work and §19's negative geometry-repair result both
reach from other directions). Path (b) (multi-use as a permanent design goal, no collapse) was never
attempted — remains open if revisited, but low priority given (a)'s outcome and the project's broader
0-for-several record on search-machinery/fitness-shaping bets vs construction-quality bets (see `mi7`,
§27, for the same pattern one experiment later).

## 27. 3D bubble-diagram adjacency fitness signal (`homemaker-py-mi7`) — DONE (negative)

*Closed 2026-07-25, the session immediately before §25's `9wi`. `bubble.py` was left in the repo
**uncommitted** as a documented reference per the original close note; committed alongside this
write-up so the reference this section makes to it is actually resolvable.*

**Motivation.** `graph.py`'s adjacency checks are binary (is X adjacent to Y, yes/no) and, like §18's
connectivity fail, give the search no gradient toward a better overall spatial *arrangement* — only
toward satisfying each declared pair. Idea: build the programme's required-space adjacency as a graph,
relax it into a 3D "bubble diagram" (a spring/repulsion physics simulation, architecture's traditional
adjacency-diagramming technique), then score a candidate layout by how well its real room-to-room
distances correlate with a relaxed target's distances — an additional graded fitness term / search-
guidance signal, in the spirit of §18's graded connectivity but for general spatial layout rather than
circulation topology specifically.

**Mechanism (`bubble.py`, prototype only, never wired into `fitness.py`).**
`requirement_graph`: one node per required room instance (`code`, or `code#i` for `count>1`), generic
`c`/`o`/`s` adjacency targets collapsed to one shared hub node per code (per whole building, not per
storey — a known simplification), edges to a multi-count code fan out to all its instances at reduced
weight (satisfying adjacency needs only *one* matching neighbour). `generate_targets`: relax the
requirement graph from `n_restarts` random 3D starts with a spring force (ideal edge length = sum of
target-area-equivalent circle radii) plus overlap-only repulsion plus a level-height pull on the z axis;
because relaxation is non-convex and multi-modal (different starts settle on e.g. opposite-handed but
equally valid arrangements), keep up to `keep` distinct low-energy solutions (pairwise-distance-vector
correlation ≥ `dedup_corr` = duplicate) rather than one canonical target. `similarity`: weighted Pearson
correlation between an actual Dom layout's real weighted shortest-path distances and a target bubble's
Euclidean distances, over matched non-generic room instances, weighted `1/hop_distance` in the
requirement graph so the many hub-mediated "just wants to be near circulation" pairs (weak positional
evidence) don't drown out the few directly-declared adjacencies (strong evidence). `best_similarity`
takes the max across the kept alternative targets. `matched_leaves` maps anonymous multi-count codes to
actual leaves by a fixed centroid-order rule — flagged in the module docstring as a known simplification,
not a real assignment solver. `topological_similarity` is a cheaper no-embedding alternative: hop-distance
correlation directly on graph topology (real multi-cell circulation network on both sides), skipping the
physics simulation and multi-restart dedup entirely.

**Validation (measured 2026-07-25) — NULL on both formulations, both programmes.** Correlated each
similarity metric against real evolved trajectories (not static examples) via `driver.search`:
- **programme-house** (n=100 recorded individuals): `embedding` ρ≈0.05, `topological` ρ≈−0.06 — flat.
  This is the cleanest data point: programme-house has **zero** multi-count anonymous codes, so
  `matched_leaves`' fixed centroid-order heuristic cannot be confounding the result, and it's still flat.
- **harbor-house** (budget 6000, n=75, fitness 3e-28→3.9e-17, fails 83→51 over the trajectory):
  `similarity()` (embedding) spearman=0.164, p=0.16 (n.s.); `topological_similarity()` spearman=−0.160,
  p=0.17 (n.s.) — noisier than programme-house (heavy anonymous-count codes: `n`×5, `m`×3, `t`×6, `r`×10,
  `of`×2, a real uncontrolled confound for the centroid-order matching there) but tells the same story.
- **No statistically significant correlation anywhere**, across 2 independent formulations (spatial
  embedding vs pure topology) × 2 programmes, with real search trajectories rather than canned batches.

**Status.** Do not pursue graph-relaxation-derived or pure-topological adjacency-matching as a fitness
signal for this project without a fundamentally different formulation. If revisited, the harbor-house
anonymous-code confound would need a real assignment solver (Hungarian/brute-force, mirroring `9o5`'s
`CLASS_CAP` pattern) before drawing any programme-specific conclusion there — but programme-house's
clean, confound-free null already argues against the core idea regardless. `bubble.py` stays in the repo
as a working, documented reference, not wired into `fitness.py`. Consistent with the project's broader
pattern (§11.4/11.5, §12.3/12.4, §14, §16, §21, §22, §26 above): search-machinery / fitness-shaping
changes have been null-to-negative essentially every time they've been tried; only construction/seeding
quality and representation-relaxation changes (leaf-sharing §13.3, global collapse §17/§25) have moved
the needle. This is another data point for that pattern, not an exception.

## 28. Default the `9wi` 2-opt polish on for finish-time collapse (`homemaker-py-cdl`) — DONE (positive)

**Motivation.** §25 (`homemaker-py-9wi`) validated the 2-opt adjacency polish on harbor-house alone (11
files, 1 improvement, 0 regressions) and left it opt-in pending a broader, non-synthetic sweep and the
`evolve.py`/`driver.collapse_best` wiring to expose it outside the standalone `homemaker-collapse` CLI.
This closes that follow-up.

**Broader sweep.** Extended the harbor-house comparison to programme-house's 34 `.dom` files (real
evolved candidates, not synthetic), 46 files total across both example sets. Compared
`collapse_finish(local_search=False)` against `local_search=True` (both keep-better against the
uncollapsed base, per §17): **0 regressions**, 2 improvements — the known harbor-house
`evolved-anneal-3M.dom` (21→19 fails) plus a new one on programme-house,
`a82f07068e4408fdd0d5e3dc469a8dee.dom` (3→2 fails); every other file matched exactly. Confirms the
finding generalises past the single synthetic dataset §25 was validated on.

**Where the default did NOT change.** `collapse_global`'s own `local_search=False` default (§25) was
left untouched. `collapse_global` runs twice in this codebase: once as a one-shot finish-time pass
(`collapse_finish`, `homemaker-collapse`, `driver.collapse_best`) and once **per fitness eval** inside
`_evaluate_full` when `collapse_insearch`/`qpk` (§20) is on — the latter is the hot path of the entire
evolutionary search, run thousands of times per run, and the 46-file sweep only measured the one-shot
cost (<1s even on the largest file). Flipping the method-level default would have silently turned the
2-opt pass on inside that hot loop too, an untested and likely-costly change out of scope for this
issue. So the default stays `False` at the method level, and each one-shot call site turns it on
explicitly instead.

**Wiring.** `homemaker-collapse --local-search`/`--no-local-search` (`collapse_cmd.py`) now defaults
`True` (was `False`). Added `homemaker-evolve --collapse-local-search`/`--no-collapse-local-search`
(`evolve.py`), default `True`, passed through to `driver.collapse_best(..., local_search=...)` — which
already forwarded arbitrary `**collapse_kw` to `fit.collapse_finish`, so no signature change was needed
there. The new flag is a no-op under `--no-collapse` (nothing to polish if the finish-time collapse
itself is skipped).

**Verification.** 298/298 tests pass (no test changes needed — `test_collapse_global.py`'s explicit
`local_search=True`/`False` cases already covered both method-level defaults). Re-ran
`homemaker-collapse` standalone on `evolved-anneal-3M.dom` with no flags to confirm the new CLI default
reproduces the 19-fail result end-to-end.

## 29. Beam/best-first search over adjacency-aware room placement (`homemaker-py-c94`) — DONE (inconclusive, mixed on harbor-house, null on programme-house)

**Motivation.** Construction/seeding quality is the one lever with a consistent positive track record
(§11.6/§11.7 adjacency-aware seeding, §12.2 proportion-aware seeding, §23 `f1d`'s reuse of the same
constructor mid-search). `operators._assign_adjacency_aware` places rooms onto the circulation-dominated
leaf set with a single greedy pass: hardest-constrained code first, each dropped onto whichever open
slot currently satisfies the most of its declared secondary adjacency (beyond `c`) against
*already-placed* neighbours. Because the pass never revisits a placement, an early code with no
already-typed neighbours to match against (every mutual pair's first-placed half, e.g. harbor-house's
`k1`↔`da1`) picks blind — any open slot scores identically at that step — and an unlucky tie-break could
strand it from a partner that would only be placed several steps later. The proposal: explore the same
per-room slot decisions with a width-K beam/best-first search instead of one irrevocable pass, scored by
a cheap proxy (no geometry/fitness calls), and measure whether it ever finds a genuinely better seed
before considering investing further (e.g. wiring it into the outer search config).

**Mechanism (build).** `_assign_adjacency_aware` gained a `beam_width: int = 1` parameter (`operators.py`);
`beam_width<=1` (default) is byte-identical to the prior greedy code path — verified by
`test_construction_beam_width_default_matches_greedy` and by the full 298-test suite passing unchanged
before any beam-specific test was added (302/302 after adding four new beam-specific tests). `beam_width>1` instead routes room placement through the new
`_beam_place_rooms`: keeps up to `beam_width` partial placements alive, each step branching every
surviving state into its top-`beam_width` candidate slots for the current code (same ranking greedy
uses), scored by the running total of secondary-adjacency matches satisfied so far. This is genuinely
cheap — no geometry or fitness calls, since circulation/outside are already fixed before room placement
starts and the leaf-adjacency graph (`_nbrs`, `deg`, `idx`, `dominated`) is shared read-only across every
branch — then prunes back to `beam_width` states before the next code, returning the highest-scoring
complete placement. Threaded through as `construction_beam_width` in `constructive_topology`,
`lift_base_to_storeys`, `driver.search`, and `driver.search_staged` (all default `1`, matching the
project's existing knob-threading convention for `circ_divisor`/`depth_balanced`/etc. — no CLI flag added,
consistent with those other construction-only knobs). Not threaded into `mutate_ruin_recreate` (kept
parameter-light, like `bridge_circulation`/`ruin_recreate`'s own circ/outside ratios, §23).

**Verified functioning (synthetic, not a no-op).** A hand-built adversarial 4-slot graph (two disjoint
adjacent pairs, codes `a`↔`b` mutually required plus a filler `x` placed between them) confirms the
mechanism is real: `beam_width=1` places `a` by an arbitrary tie-break, `x` then greedily grabs `a`'s only
neighbour before `b` gets a turn, stranding the pair (`a-b adjacent=False`); `beam_width>=2` recovers the
correct joint placement (`a-b adjacent=True`) by keeping `a`'s alternate slot choice alive long enough for
`b`'s later score to reward it. This is exactly the "no lookahead" failure mode `_assign_adjacency_aware`'s
one-shot pass is structurally prone to, and confirms the beam can and does out-score greedy when the
graph offers a genuine trade-off.

**Raw-seed check (2026-07-27) — misleadingly byte-identical, later shown insufficient.** Before running
any search, a cheap diagnostic scored `constructive_topology`'s raw output directly (no GA, one
`score_with_fails` call per seed): `beam_width` 1/4/8, 15 rng trials each, on programme-house and
harbor-house — fail counts and adjacency/access fail counts identical to the last digit across all three
widths, every trial. Extended to `lift_base_to_storeys` (the Stage-2 seeder) at widths 1/4/8/20, 10
trials: again byte-identical at every width, including `beam_width=20` (near-exhaustive for the ~15-17
codes per storey these programmes carry). A step-by-step trace of a real harbor-house construction
(`da1`→`k1`→`ws1`) confirmed the beam *does* explore physically distinct slot branches, but every branch
reached the same cumulative score every time — harbor-house's circulation-spine geometry usually offers
several equally-good neighbours per code, so a lone raw-seed sample rarely hits a real trade-off. **This
was wrongly taken as proof an end-to-end run would also be byte-identical** (a single root's construction
never diverging was treated as sufficient to conclude the full bootstrap population never would either) —
see the correction below.

**End-to-end correction (2026-07-28, prompted by user question "should the default be 1? can we find out
by running the two example programmes from a clean start?") — the raw-seed argument was wrong.** Ran
`driver.search` from a clean bootstrap (`init.dom`, `n_workers=1` for reproducibility, budget 1500) at
`construction_beam_width` 1 vs 4, same seed both arms, 5 seeds each programme:

| programme | seed | bw=1 fails | bw=4 fails | result |
|---|---|---|---|---|
| harbor-house | 1 | 60 | 58 | bw4 win |
| harbor-house | 2 | 67 | 52 | bw4 win (large) |
| harbor-house | 3 | 53 | 53 | tie |
| harbor-house | 4 | 52 | 52 | tie |
| harbor-house | 5 | 52 | 62 | bw4 **loss** |
| programme-house | 1–5 | (9,6,11,11,9) | identical | tie, all 5 |

harbor-house: **2 wins / 1 loss / 2 ties**, mean fails 56.8 (bw1) → 55.4 (bw4) — a small mean improvement
pulled mostly by seed 2's outlier, with a real loss on seed 5. programme-house: 5/5 ties, matching the
raw-seed prediction exactly. The harbor-house divergence itself confirms the raw-seed reasoning's flaw:
`driver.search`'s bootstrap builds `pop_size` individuals, each consuming a different slice of the RNG
stream (unlike the single-root raw-seed check), and once even one population member's construction hits a
genuine beam-vs-greedy tie-break divergence, the GA's subsequent *structure*-dependent choices (which
subtree a mutation targets, crossover points) cascade into a different trajectory from there — even
though the raw RNG numbers drawn are bit-identical between arms. "The one seed I checked never diverged"
does not imply "no seed in a population of many ever will."

**Interpretation.** The mechanism works (§ above, verified on a synthetic graph built to need it), and
does occasionally get real traction on harbor-house's larger, more room-dense programme — but the 5-seed
result is the same small-N, mixed-direction shape this log has repeatedly warned produces false signal
(§23 `f1d`'s initial 8-run sweep, explicitly flagged there as "the 8sh/1ph/qi6/lj3 pattern"): a genuine
loss (seed 5) sits alongside the two wins, and N=5 is far short of what `f1d`'s own larger-N confirmation
needed (N=15/8) to separate a real effect from noise. programme-house shows no effect at any N tested,
consistent with both the raw-seed check and its smaller, simpler room graph.

**Status.** `construction_beam_width` stays default `1` — the *direct answer* to "should the default be
1": yes, current evidence does not clear this project's bar for flipping a default (cf. §20/§23's own
"only after larger-N confirmation" standard), though harbor-house's mixed result (unlike programme-house's
clean tie) means this is genuinely unresolved rather than a confident null. The code and tests stay in the
tree as a working, verified-functioning building block (`operators._beam_place_rooms`), consistent with
keeping validated-but-inconclusive mechanisms available rather than reverting them (cf. `bubble.py`, §27).
A natural follow-up — not filed, low priority, matching `f1d`'s own unfiled size-threshold follow-up
(§23/§24) — would be a larger-N harbor-house-only sweep (N=15+, matching `f1d`'s and `y51`'s bar) to
determine whether the mean-improvement lean is real or an artefact of seed 2's outlier.

## 30. `c94` beam-width larger-N confirmation (`homemaker-py-e01`) — DONE (confirmed null)

**Motivation.** §29's own filed follow-up: the 5-seed harbor-house end-to-end result (2W/1L/2T, mean
fails 56.8→55.4) was flagged as the same small-N, mixed-direction shape that has repeatedly produced
false signal in this log (`8sh`/`1ph`/`qi6`/`lj3`, §23's initial `f1d` sweep) — the mean was pulled
mostly by seed 2's outlier (67→52), and N=5 falls well short of the N=15/8 bar `f1d`'s own larger-N
confirmation needed to separate a real effect from noise.

**Measured (2026-07-29, `experiments/run_e01_sweep.py`)** — identical protocol to §29: `driver.search`
from a clean bootstrap (`init.dom`), `n_workers=1`, `budget=1500`, same seed both arms,
`construction_beam_width` 1 vs 4, harbor-house only (programme-house showed zero effect at any N in
§29 and was not re-checked). Extended seeds 1-5 (reproduced byte-identical to the §29 table, confirming
the protocol) up to N=15:

| seed | bw=1 fails | bw=4 fails | result |
|---|---|---|---|
| 1 | 60 | 58 | win |
| 2 | 67 | 52 | win (large, the outlier) |
| 3 | 53 | 53 | tie |
| 4 | 52 | 52 | tie |
| 5 | 52 | 62 | loss |
| 6 | 65 | 65 | tie |
| 7 | 50 | 50 | tie |
| 8 | 68 | 64 | win |
| 9 | 49 | 55 | loss |
| 10 | 63 | 59 | win |
| 11 | 63 | 62 | win |
| 12 | 61 | 61 | tie |
| 13 | 52 | 53 | loss |
| 14 | 47 | 45 | win |
| 15 | 53 | 58 | loss |

N=15: 6 wins / 4 losses / 5 ties, mean fails 57.0 (bw=1) → 56.6 (bw=4), Wilcoxon signed-rank p=0.84 —
no signal by any conventional threshold. Confirming the §29 suspicion directly: excluding seed 2's
outlier, the mean *flips slightly negative* (56.3 → 56.9, bw=4 marginally worse), i.e. the entire
5-seed "mean improvement" that motivated this follow-up was that one outlier — the other 14 seeds
average to a null-to-negative effect.

**Interpretation.** The beam mechanism remains verified-functioning on its adversarial synthetic case
(§29) but confirmed to find no reliable real-world traction on either example programme at any N tested.
This resolves §29's "genuinely unresolved" status to a clean null, matching programme-house's result and
consistent with `y51`'s own experience (§24) that small-N mixed-direction results in this codebase are
usually noise rather than an early real signal.

**Status.** `construction_beam_width` stays default `1`, now on confirmed (not just precautionary)
grounds. Code and tests stay in the tree as a working, verified-functioning building block
(`operators._beam_place_rooms`), consistent with keeping validated-but-null mechanisms available rather
than reverting them (cf. `bubble.py` §27, `mi7`).

## 31. `y51` n=18 larger-N confirmation (`homemaker-py-xyu`) — INCONCLUSIVE, weak but not evaporated

**Motivation.** §24's own filed follow-up (a): of `y51`'s four synthetic room-count sizes (10/14/18/22),
n=18 showed the strongest trend at N=10 (7W/2L/1T, +9.3% mean fails, Wilcoxon p=0.098) despite sitting
non-monotonically between two much weaker sizes — consistent either with a real-but-weak effect that
N=10 underpowered, or with n=18 simply being the noisiest extremum of four small-N estimates. Extends
only this one size to N=15, matching the sample size that resolved a similar-magnitude effect for `f1d`'s
own programme-house confirmation (§23, p=0.041 at N=15).

**Measured (2026-07-29, `experiments/run_xyu_sweep.sh`)** — 5 fresh seeds (11-15) appended to `y51`'s
existing n=18 seeds 1-10, same protocol (`--ruin-recreate` weight=3.0 ON vs OFF, budget=3000, 4 workers,
finish-time `--collapse`):

| seed | OFF fails | ON fails | diff (OFF-ON) |
|---|---|---|---|
| 1 | 27 | 25 | +2 |
| 2 | 33 | 29 | +4 |
| 3 | 28 | 26 | +2 |
| 4 | 30 | 30 | 0 |
| 5 | 34 | 28 | +6 |
| 6 | 45 | 35 | +10 |
| 7 | 33 | 34 | -1 |
| 8 | 46 | 42 | +4 |
| 9 | 52 | 37 | +15 |
| 10 | 37 | 45 | -8 |
| 11 | 36 | 35 | +1 |
| 12 | 29 | 28 | +1 |
| 13 | 40 | 40 | 0 |
| 14 | 44 | 44 | 0 |
| 15 | 35 | 36 | -1 |

N=15 combined: **9W/3L/3T**, mean fails **36.60 (OFF) → 34.27 (ON)**, Δ≈**6.4%** (down from N=10's 9.3%).
Wilcoxon signed-rank two-sided **p≈0.059** (just misses conventional significance), one-sided (directional,
matching the effect's own sign) **p≈0.029**; sign test on the 12 non-tied seeds is weaker, one-sided
**p≈0.073**. The 5 new seeds alone were 2W/1L/2T — same direction as the original 10, weaker than them,
but not reversed.

**Interpretation.** Extending N=10→15 at the size that was *itself selected* for follow-up because it had
the strongest of four initial signals is a scenario primed for regression to the mean, and that partly
happened — the effect size shrank from 9.3% to 6.4% and the two-sided p moved from 0.098 to 0.059, i.e.
still on the "not quite" side of both conventional thresholds. But the trend did not evaporate or flip
the way §22's `lj3` weight bump or §24's own n=14 size did on their larger-N passes — it stayed
directionally consistent across all 15 seeds' aggregate and crossed p<0.05 on the one-sided directional
test. This is a genuinely ambiguous middle case: not the clean confirmation `f1d` got at the same N, not
the clean reversal-to-null `lj3`/n=14 got either.

**Status.** `enable_ruin_recreate` stays default **OFF** — this result alone does not clear the bar for a
default flip even at n≈18-room scale, and harbor-house (37 room instances) remains null-to-negative
(§23). §24's methodological caveat (the synthetic sweep scales room count by duplicating
already-interchangeable codes, the same mechanism harbor-house itself uses, so it may not isolate the
same "topology fraction sampled per wing move" variable the `f1d` hypothesis needs) is **not** addressed
by this larger-N pass — only option (a) of §24's two follow-ups was run here. Option (b), a genuinely
distinct third example programme (real room-type diversity at an intermediate room count, not a
duplicated-code scale-up), remains the more likely route to a clean answer and is refiled as a fresh
follow-up rather than closed out by this inconclusive N=15 read.

## 32. `health-centre` non-synthetic third example (`homemaker-py-9yx`) — CLEAN NULL

**Motivation.** §31's own filed follow-up (option b): `y51`'s n=10/14/18/22 sweep scales room count by
duplicating already-interchangeable `programme-house` codes (`b1`/`t1`/`b2`/`t2`/`l1`) via `count:` — the
same mechanism `harbor-house` itself uses "to reduce complexity". `harbor-house` has real room-type
diversity (16 distinct codes) but sits out of the tested range at 37 room instances, and its own result
was already null-to-negative (§23) — so it cannot distinguish "the effect needs more real rooms than
harbor-house has" from "the effect never existed outside the duplicated-code mechanism". A genuinely
distinct programme at an intermediate, non-duplicated room count was needed to isolate room count as the
variable.

**Programme.** `examples/health-centre`: a small primary-care health centre, a building type unlike either
`programme-house` (a house) or `harbor-house`/`maple-court` (dormitory-style co-housing). 19 distinct,
individually-sized room codes, n=20 room instances (matching `xyu`'s own n=18 test point closely, without
leaning on `count:` as the scaling knob — the only duplication is a realistic pair of public WCs).

A first draft's room sizes formed a single transitive interchange class spanning all 19 codes — `9o5`'s
auto-derived interchange relation chains through any sequence of pairwise-close-enough neighbours, so a
smooth size gradient from a 3 m² WC up to a 28 m² waiting room reconnects the whole building into one
class regardless of the individual rooms being genuinely different types. This would have silently
reintroduced the exact confound the issue exists to eliminate. Fixed by deliberately tiering room widths
with >1.3x gaps at three boundaries (micro/utility, office/support, large clinical/public), which resolves
to three bounded classes (sizes 6, 9, 4) instead of one whole-building chain — the same shape of result
`harbor-house` itself gets from a real programme, and consistent with `9o5`/`b3v`'s own experience that
this needs active management rather than resolving itself.

**Measured (2026-07-30, `experiments/run_9yx_sweep.sh`)** — 15 fresh seeds (1-15), same protocol as `xyu`
(`--ruin-recreate` weight=3.0 ON vs OFF, budget=3000, 4 workers, finish-time `--collapse` default):

| seed | OFF fails | ON fails | diff (OFF-ON) |
|---|---|---|---|
| 1 | 42 | 42 | 0 |
| 2 | 44 | 40 | +4 |
| 3 | 53 | 46 | +7 |
| 4 | 47 | 46 | +1 |
| 5 | 46 | 43 | +3 |
| 6 | 43 | 47 | -4 |
| 7 | 41 | 47 | -6 |
| 8 | 51 | 43 | +8 |
| 9 | 44 | 48 | -4 |
| 10 | 50 | 54 | -4 |
| 11 | 45 | 43 | +2 |
| 12 | 44 | 44 | 0 |
| 13 | 47 | 42 | +5 |
| 14 | 45 | 39 | +6 |
| 15 | 50 | 53 | -3 |

N=15: **8W/5L/2T**, mean fails **46.13 (OFF) → 45.13 (ON)**, Δ≈**2.2%** — well below `xyu`'s already-weak
6.4% at the same scale. Wilcoxon signed-rank two-sided **p≈0.40**, one-sided (directional) **p≈0.20**;
sign test on the 13 non-tied seeds one-sided **p≈0.29**. Nowhere near any conventional threshold, in either
direction.

**Interpretation.** At a real, diverse ~20-room programme, `ruin_recreate`'s effect is indistinguishable
from noise — much weaker than even `xyu`'s own inconclusive N=15 reading (6.4%, p≈0.059) at essentially
the same room count. This is the cleanest evidence yet that the `y51`/`xyu` signal was substantially (if
not entirely) an artifact of the duplicated-interchangeable-code scaling mechanism itself — repeatedly
placing several copies of the *same* small room set — rather than a genuine effect of room count/topology
scale that would transfer to a building with that many *different* rooms. It converges with `harbor-house`
(37 real instances, null-to-negative, §23) rather than with `y51`'s own synthetic n=18 reading, closing the
gap that made §31 ambiguous.

**Status.** `enable_ruin_recreate` stays default **OFF**, now on a broader evidence base: null-to-negative
on every real (non-duplicated-code) programme tested at any scale from 6 rooms (`programme-house`) to 37
(`harbor-house`), and only ever weakly positive on the synthetic duplicated-code sweep that this result
suggests was measuring the wrong thing. No further follow-up is filed — the room-count hypothesis from
`f1d` (§23) is now addressed on the diversity axis `xyu` (§31) could not reach.

## 33. Multi-use leaves as a permanent design goal (`homemaker-py-1s3`, §26 path b) — DONE (NULL, N=3 signal did not replicate)

**Motivation.** §26 scoped two readings of "multi-use leaves" — a leaf legitimately serving several
DIFFERENT compatible programme codes at once (study+guest bedroom, kitchen+dining, Stewart Brand's
"loose-fit" long-life rooms). Path (a), superposition as a per-eval search relaxation, was built and
measured NULL/NEGATIVE (§26): the geometry floor dominates, not the type-labelling relaxation gap. Path
(b) — multi-use as the *permanent design goal*, surviving into the output with no collapse — was never
attempted. The framing going in: path (b) is structurally the same lever as leaf-sharing (§13.3,
`homemaker-py-x3b`) — the single biggest positive lever in the project (−32…−39% on the achievable fail
floor) — extended from *same*-code multiplicity to *different*-but-compatible codes, with a materially
larger addressable set on programmes with many small single-instance rooms (`health-centre`'s 19 distinct
codes, §32).

**Mechanism.** Explicit, architect-declared `co_locate: [code, ...]` per `SpaceReq` (unlike `interchange`
classes, never auto-derived — fusing two codes onto one leaf is a much stronger commitment than a soft
substitution class). `programme.derive_colocate_pairs` keeps a declared pair only if it *also* passes the
existing `interchangeable()` S1-S4 relation (§26/`9o5`) — reusing the already-validated bounds instead of
inventing a second relation — and returns pairs only, never folding them into connected components, so the
`b3v` transitive-chain failure mode (§26) cannot arise by construction. `Node.co_type` (new field, sibling
to `share`/`share_type`) records the second code a leaf serves; `graph.leaf_codes()` is the resolver every
programme-check function (`check_space_counts`, `check_adjacency`, `check_level_constraints`,
`check_vertical_connectivity`, `has_adjacency`, `has_vertical_connection`) now routes through instead of
comparing `leaf.type` directly — returning `[type, co_type]` only while `multi_use` is on AND the pair is
still a currently-valid declared co-location (a retype silently drops a stale `co_type`, the same
self-healing type-guard `leaf_share` uses). `fitness.quality_size` combines a fused leaf's two codes
**additively** (target and sigma both sum — the same operation as leaf-sharing's k×target, generalised
from k identical terms to 2 different ones — area genuinely sums across two uses). Construction-time only
(no mutation operator): `operators._colocate_rooms` greedily fuses available same-storey instances of a
declared pair (before `_share_rooms`, so same-code sharing still groups whichever code is kept primary),
`_leaf_colocate_from_plan` stamps the winning leaves, and `_size_divisions_from_targets` grows the fused
leaf to the combined target. Gated behind `multi_use` (default OFF, bit-identical when off — 335/335 tests
pass including 33 in `tests/test_multi_use.py`). Threaded end-to-end through `driver.py`/`evolve.py
--multi-use`, mirroring `superpose`'s existing wiring.

**Shape-combination sub-experiment — `quality_width`/`quality_proportion`.** Unlike area, a leaf's width and
aspect are the SAME physical measurement serving two potentially-different codes' targets at once, so
"additive" makes no sense — three combination strategies were tried, in this order, each triggered by
review of the previous:

1. **Naive max-target/min-sigma ("stricter of both").** The first cut: pick whichever code's target is
   harder to satisfy. Simple, but ad hoc — it does not correspond to any principled combination of the two
   codes' evidence.
2. **Precision-weighted product (`fitness._gaussian_product`).** The product of two Gaussian curves
   evaluated at the same point is itself proportional to a Gaussian: precisions (`1/sigma^2`) ADD, and the
   combined target is the precision-weighted average — an INTERMEDIATE target (never simply the stricter
   one) with a NARROWER spread than either input. The standard way to combine two pieces of independent
   evidence about the same quantity.
3. **Mixture (`fitness._clipped_gaussian` + `max()`).** A different philosophy: the leaf need not compromise
   between the two codes' targets at all — score it against whichever target the realised geometry ends up
   closer to (a wide, bimodal tolerance), echoing this project's own per-leaf usage collapse (§26 path a)
   but applied within one leaf's shape terms instead of across its whole type. Appealing in principle (no
   forced compromise) but, per the A/B below, empirically the worst of the three.

**Declared pairs.** Architect-authored in each programme's `patterns.config`, hand-picked from the pool of
`interchangeable()`-eligible candidates on semantic grounds (not every eligible pair is a sensible fusion —
e.g. `health-centre`'s public/staff WCs and sterilisation room pass the S1-S4 bounds but were deliberately
left undeclared): `harbor-house` — foyer/meeting-room (`ef1`/`m`), laundry/plant-room (`la1`/`me1`);
`health-centre` — admin/manager's office (`ao1`/`mo1`), admin/staff-room (`ao1`/`br1`), dental/minor-surgery
(`de1`/`ms1`), storage/records (`dp1`/`re1`).

**End-to-end A/B, all three shape-combination strategies** (`experiments/run_multiuse_ab.sh`, staged search,
20 000 native evals, seeds 0/1/2, 4 workers, final native re-score, mirrors §13.3's harness; each run
verified single-process before launch — an early attempt let two runs overlap and contaminate the results,
discarded entirely, see the bead's history):

| combination | harbor-house (s0/1/2) | mean | Δ | health-centre (s0/1/2) | mean | Δ |
|---|---|---:|---:|---|---:|---:|
| baseline (no multi_use) | 95/101/103 | 99.7 | — | 63/82/71 | 72.0 | — |
| 1. stricter-of-both | 92/101/94 | 95.7 | **−4.0%** | 81/111/77 | 89.7 | **+24.5%** |
| baseline (re-measured) | 95/101/90 | 95.3 | — | 63/82/71 | 72.0 | — |
| 2. precision-weighted | 82/117/83 | 94.0 | **−1.4%** | 65/78/43 | 62.0 | **−13.9%** |
| baseline (re-measured) | 95/102/97 | 98.0 | — | 63/82/71 | 72.0 | — |
| 3. mixture | 81/110/81 | 90.7 | **−7.5%** | 91/92/77 | 86.7 | **+20.4%** |

(Baseline drifts slightly run-to-run — the staged search's own within-seed run-to-run noise at this
budget/worker-count, not a bug; each combination's Δ is against its own paired baseline row.)

Among the three, the precision-weighted single-compromise-peak model was the only one to improve BOTH
programmes at N=3, so it is the one landed in the shipped code (`_clipped_gaussian`/mixture kept in
`fitness.py`, documented and unit-tested, as a recorded negative alternative). But per the confirmations
below, this N=3 comparison — used to pick a combination strategy — turned out to be too small a sample to
trust for the multi_use verdict itself.

**Larger-N confirmation — the N=3 signal did not replicate.** N=3 is a thin sample (§31/§32's own standard
is N=15), so the precision-weighted result was checked two ways before considering any default-flip
recommendation:

| test | conditions | harbor-house Δ | health-centre Δ |
|---|---|---:|---:|
| original | N=3, staged search, budget 20 000 | **−1.4%** (2W/1L) | **−13.9%** (2W/1L) |
| confirm #1 | N=15, plain search, budget 3 000 (mirrors `xyu`/`9yx`'s own protocol exactly) | +6.1% worse (5W/10L, p=0.30) | +6.6% worse (3W/11L/1T, Wilcoxon p=**0.044**) |
| confirm #2 | N=15, staged search, budget 20 000 (**same conditions as the original**, more seeds) | +6.6% worse (4W/11L, p=0.15) | +4.7% worse (6W/9L, p=0.48) |

Confirm #1 uses a cheaper protocol (budget 3000, and for the multi-storey `harbor-house`, plain search
rather than staged — `search_staged` only falls through to plain search on single-storey programmes) so it
answers a related but distinct question. Confirm #2 is the true same-conditions replication — identical to
the original A/B except 15 seeds instead of 3 — and it **also trends negative on both programmes**, though
neither reaches significance at this N. Two of the three measurements, including the one that actually
matches the original protocol, disagree with the original finding's *direction*. The honest read: the N=3
positive result was very likely sampling noise from an unlucky (or lucky) three-seed draw, not a real
effect — `harbor-house`'s original 2W/1L was already a coin-flip-sized sample, and `health-centre`'s dramatic
−13.9% at N=3 (driven substantially by one seed swinging from 71→43 fails) did not hold up at N=15 (mean
Δ flipped to +4.7%, p=0.48 — indistinguishable from no effect).

**Diagnosis.** Leaf-sharing's k×target scaling never changes the SHAPE constraint: k identical rooms share
one identical width/proportion target, so a shared leaf is exactly as easy or hard to satisfy geometrically
as any single instance of that code, just bigger. Multi-use fusion is different — the combined leaf's
larger area target competes with every other room for the same limited plot area, and (whichever shape
combination is used) the fused leaf's shape constraint is at best as forgiving as either code alone, never
more so. The mechanism does not appear to reliably pay for this cost the way leaf-sharing's pure count
relaxation does — consistent with the broader pattern in this log (§11.4/11.5, §14, §16, §21, §22, §26,
§27, §30) that search-machinery/fitness-shaping-adjacent levers rarely move the needle, and that small-N
results in this problem class need real confirmation before being trusted (the same lesson `y51`/`xyu`/`9yx`,
§31/§32, already taught once).

**Status.** `multi_use` stays default **OFF** and is not recommended even as a promising candidate — the
larger-N evidence points toward NULL-to-mildly-negative rather than positive. The mechanism itself (declared
`co_locate` pairs, `graph.leaf_codes()` resolver, precision-weighted shape combination, construction-time
fusion) is complete, fully tested (335/335 passing, `tests/test_multi_use.py`), gated OFF by default and
bit-identical when off, so it remains available if a future architect wants to opt a specific programme into
it manually despite the null aggregate result — but no further investment (default flip, additional
combination strategies, or a larger sweep) is planned. This closes out `homemaker-py-1s3` and, with it, both
halves of §26's original multi-use-leaves question: path (a) (search relaxation) was NULL/NEGATIVE, path (b)
(permanent fusion) is NULL after replication.

## 34. Spike: autodiff/gradient-based inner-loop ratio optimisation (`homemaker-py-2ax`) — DONE (negative, wall-clock)

**Motivation.** `innerloop.py`'s default inner-loop optimiser (`nm_search`, multi-start Nelder-Mead) is
derivative-free — a legacy of the Perl-subprocess oracle era when fitness was not differentiable. Fitness is
now a native Python port (`fitness.py`) built from ordinary arithmetic (Heron's-formula areas, Gaussian
quality terms), plausibly differentiable. Nobody had tried gradient-based optimisation since the port. Real
risk flagged going in: the deliberately-preserved `0.5^n` failure-count penalty cliff (§4.5) is a sharp
discontinuity by design, which could make raw gradients unreliable near failure boundaries.

**What was actually built.** The full fitness pipeline (`_evaluate_full`, 1700+ lines) is not literally
differentiable end-to-end regardless of the geometry — staircase fit truncates to integers
(`_risers_number`/`_ideal_going`/`_*_turn`), physical adjacency is a `door_width` threshold on wall overlap,
`access` is a categorical neighbour-type test, and `check_space_counts`/`check_adjacency`/etc. are graph
algorithms over discrete labels. Porting all of that to an autodiff framework was out of scope for a spike
and would still bottom out in the same non-smooth primitives. Built instead: `experiments/autodiff_spike.py`,
a torch mirror of `geometry.py`'s coordinate recursion (`coordinate`/`coord_a`/`coord_b`/`area`/
`edge_length`/`angle`/`aspect`, exact port, tensors instead of floats) driving the 5 per-leaf quality factors
that vary continuously with the ratios (perpendicular, proportion, size, width, crinkliness) plus the
cost/value accumulation (leaf cost, edge cost, outside-edge cost). Every *structural* fact that doesn't vary
continuously for a frozen topology — which leaves are adjacent, boundary ids, leaf types/params, which fails
are structural (missing/adjacency/level/vertical/access/staircase/storey/edge-too-long) — is snapshotted
ONCE from a real `fitness.py` evaluation at the start ratios (`TorchTopology._snapshot`) and held frozen;
`building_factor` (programme area-ratio Gaussians, staircase volume, storey/public-access checks) is folded
into one calibration constant rather than ported. The `0.5^n` cliff itself is relaxed to a steep sigmoid
(`soft_fail`, steepness 60) on each continuous factor's `FAIL_THRESHOLD` test, so the proxy is smooth
everywhere — this directly probes the flagged risk rather than assuming it away. `torch.optim.Adam` ascends
the proxy; the true fitness (`NativeEvaluator`-equivalent) is re-checked and the topology re-snapshotted
periodically, a trust-region-style refresh since the frozen adjacency set can in principle drift as ratios
move.

**Measured, two frozen topologies (CPU, no GPU in this environment):**

| topology | DOF | nm_search (200 evals) | torch: 1 fwd+bwd step | ratio |
|---|---:|---|---|---:|
| `programme-house/candidate-002.dom` | 6 | 200 evals / **3.0 s**, fitness 0.0142 (2 fails) | 200 Adam steps (10 resnaps) / **106 s**, fitness 0.0041 (3 fails) — worse on both axes | **~35×** slower, worse result |
| `harbor-house/3m.dom` | 36 | 200 evals / **14.6 s** | 1 step ≈ **2.1 s** (200 steps ⇒ ~420 s projected, before resnapshot overhead) | **~29×** slower per unit of search progress |

The slowdown is per-op tensor dispatch overhead (each leaf/edge is a handful of scalar torch ops, no
batching across leaves — nothing here is a large matmul torch is built to accelerate) plus the snapshot/
re-snapshot cost (a real `fitness.py` evaluation on a deep copy, same cost class as one `nm_search` eval, but
paid on top of the gradient step rather than instead of it). A small-step gradient test (`lr` 0.01/0.03/0.1
from the same `x0`) confirmed the flagged cliff risk concretely: 0.03 improved true fitness, but 0.01 and 0.1
from the *same descent direction* both crossed into a new failure and scored worse than the start —
gradient *direction* carries real local signal, but step size right next to the cliff is as fragile as the
issue predicted, and nothing about autodiff removes that fragility (it only makes the direction cheaper to
compute, and the wall-clock numbers show it isn't even cheaper here).

**Verdict.** NULL/NEGATIVE — not recommended. Even setting aside the failure-cliff sensitivity, the
autodiff path is decisively slower per unit of progress than `nm_search` at both scales tested, and does
not reach a better fitness in the equal-"budget" comparison at the small scale. The theoretical case for
autodiff (avoid the ~DOF-proportional cost of finite-difference-style multi-start search) does not survive
contact with this problem's actual shape: very few, cheap-to-evaluate scalar dimensions per leaf, no
batching opportunity, and a real per-step evaluation cost (snapshot refresh) comparable to a full oracle
call anyway. `experiments/autodiff_spike.py` is kept as a reference/starting point (not wired into
`innerloop.py`) should a future architect want to revisit this at a very different scale (e.g. thousands of
DOF, where nm_search's `O(DOF)` per-iteration cost would start to dominate) — not worth further investment
at current programme/topology sizes (6-40 DOF).

## 35. Stale leaf-share leak into `collapse_global`'s candidate valuation (`homemaker-py-iio`) — FIXED, retroactive impact partially assessed

**Discovery.** Found while diagnosing `homemaker-py-91f`: rescoring a dumped `.dom` under the
`leaf_sharing`+`collapse_insearch` stack did not reproduce `driver.search_staged`'s own reported
`n_fails`. `copy.deepcopy(r.best.root)` rescored in-process matched the search's own number exactly
(37 fails, harbor-house seed=0, budget=20000, full default stack); `dom.dump`+`dom.load` of the exact
same tree, rescored identically, gave 64. Ruled out first: hash-seed randomness (stable across
`PYTHONHASHSEED` 0-4), float-precision loss (`dom.dump`/`dom.load` round-trips a Python `float` exactly
— `yaml`'s float representer uses `repr()`, which is round-trip-exact by construction — confirmed no
`numpy.float64` leaks into `.division`, all such writes already go through `float(...)`), and
below-link/geometry staleness (the leading hypothesis going in — `dom._link` is re-run after every
structural mutation, so this turned out to be a dead end).

**Root cause.** Not geometry at all — a metadata leak in `Fitness._collapse_value` and
`Fitness._usage_quality` (`fitness.py`). Both temporarily overwrite `leaf.type` to probe a
*hypothetical* candidate code (`_collapse_value` inside `collapse_global`'s Hungarian assignment build;
`_usage_quality` inside `collapse_superposition`/9o5), call `quality_size`, and restore the original
type in a `finally`. `quality_size` reads `graph.leaf_share(leaf, max_share)`, which returns the
leaf-sharing multiplier `k` only when `leaf.share > 1 and leaf.share_type == leaf.type` — by design,
this makes a share stamp "stale" (harmless) the moment a leaf is retyped away from the code it was
stamped for (§13.3's own documented contract). But because the probe overwrites `leaf.type` to the
*candidate*, not the leaf's real current type, `leaf_share`'s guard compares the stale `share_type`
against the CANDIDATE code — so whenever a probed candidate happens to equal a leaf's old, stale
`share_type`, the k× size-target credit spuriously reactivates for that one (leaf, candidate) cell,
even though the leaf never actually committed to that code. This skews that one cell of the Hungarian
matrix and can flip which leaf `collapse_global` assigns to which room.

`dom._emit` only serialises `share` when `share_type == type` (the same live/stale guard, correctly
applied to the leaf's REAL type) — so a stale `share`/`share_type` combo is silently dropped on
`dom.dump`+`dom.load`. That is exactly why the live in-process tree (still carrying the stale
metadata) and its dump/reload round trip (metadata gone) fed different values into the same
`collapse_global` call and landed on different optimal assignments. Structural diff of the live vs.
reloaded harbor-house tree that triggered this showed exactly two leaves differing, both in
`share`/`share_type` only (e.g. `share=3, share_type='n'` live vs. `share=1, share_type=None`
reloaded) — nothing else (no type, division, or below-link differences).

**Fix** (`src/homemaker_layout/fitness.py`): in both `_collapse_value` and `_usage_quality`,
temporarily clear `leaf.share_type` for the duration of the probe whenever the candidate differs from
the leaf's real current type, restoring it in the `finally` block. The leaf's own real current type
(the non-hypothetical, `code == orig` case — e.g. `_two_opt_adjacency_polish`'s `reward()`, which
always evaluates a leaf's own current type, never a hypothetical one, and so was never exposed to this
bug) still legitimately carries a live share.

**Verification.** Two new regression tests in `tests/test_collapse_global.py`
(`test_collapse_value_ignores_stale_share_for_hypothetical_code`,
`test_collapse_global_dump_reload_agree_with_stale_share`), both confirmed to fail pre-fix and pass
post-fix. Full suite 337/337. Re-ran the exact 91f repro (harbor-house seed=0, budget=20000): search /
in-process rescore / dump-reload rescore now agree at 37/37/37 (previously 35/35/64).

**Retroactive impact: who was exposed.** The bug requires `leaf_sharing=True` (default since §13.10
`x3b`) *and* `collapse_global` running on a tree carrying a stale share — either every eval
(`collapse_insearch=True`, default since §20 `1ph`, 2026-07-24) or once at finish time (`--collapse`,
94g, §17, default on since before that). That describes essentially the whole "full default stack"
used for every experiment from `x3b` onward, including the very studies that justified defaulting
these features on (`94g`, `qpk`/`1ph`, `8sh`, and everything downstream). Two things are NOT exposed:
the `9wi`/`cdl` 2-opt polish (`reward()` always probes a leaf's own current type — see above), and
`9o5`/`superpose`-only runs (exposed via `_usage_quality`, but only when `superpose=True`, which has
always defaulted off and — as far as this investigation went — was not cross-checked against whether
`leaf_sharing` was also on in that specific historical A/B).

**Re-verification performed (2026-08-02).** Re-ran the qpk protocol's harbor-house arm
(`examples/harbor-house/init.dom`, budget 2500, seeds 1-3, 4 workers, `--collapse-insearch` ON/OFF,
canonical `homemaker-fitness` re-score) on **today's codebase**, once with the `iio` fix in place and
once with it reverted (`git show 929be5b~1:src/homemaker_layout/fitness.py` swapped in temporarily via
the editable install, then restored — no commit was made with the bug reintroduced):

| seed | collapse_insearch | fixed | pre-fix (buggy) |
|---|---|---:|---:|
| 1 | OFF | 85 | 85 |
| 2 | OFF | 76 | 76 |
| 3 | OFF | 80 | 80 |
| 1 | ON | 82 | 74 |
| 2 | ON | 65 | 65 |
| 3 | ON | 72 | 77 |

OFF is byte-identical between the two code versions on all 3 seeds — expected, since OFF never calls
`collapse_global` during search, only once at finish time, and none of these three final trees
happened to carry a triggering stale share at that point. ON diverges on 2 of 3 seeds, by a real
margin (seed 1: 74 vs. 82, an 8-fail swing; seed 3: 77 vs. 72, a 5-fail swing) — and, critically, **not
directionally**: the bug's noise landed better on seed 1 and worse on seed 3. This is consistent with
the mechanism (a coincidental corruption of one assignment-matrix cell, not a systematic push in either
direction).

**What this does and doesn't establish.** It establishes the bug was not merely theoretical: it
demonstrably perturbed real per-seed outcomes under `collapse_insearch=ON` on this exact protocol, by
margins (5-10% of the fail count) that are not negligible next to the ~10% mean effect `qpk`/`1ph`
reported. Because the perturbation is non-directional noise rather than a systematic bias, it's
unlikely to have flipped `1ph`'s aggregate, statistically-tested verdict (N=20 programme-house seeds,
paired t-test p≈0.028, consistent direction and magnitude with the original N=5 sample and with
harbor-house) — random per-seed noise in both directions tends to average out rather than compound
across a 20-seed sample. But this was NOT rigorously confirmed: the comparison above reran today's
code (fix vs. no-fix), not the actual historical commit at the time `1ph`/`qpk` were measured, and used
only 3 harbor-house seeds, not the original seed sets. Any specific historical per-seed number quoted
in §17/§20/§21 (and elsewhere the full default stack was used) should be treated as carrying real,
now-quantified uncertainty from this bug; the qualitative "leaf-sharing helps" / "in-search collapse
helps" conclusions are probably still sound but were not independently re-proven against the fix.

**Follow-up (not done here, low priority, filed as `homemaker-py-d86`):** a rigorous re-verification
would check out the codebase near the `1ph` commit (2026-07-24), backport the `iio` fix there in an
isolated worktree, and re-run the *actual* historical seed set (programme-house N=20, harbor-house
N=3) to get a direct before/after comparison against the published numbers, rather than today's
much-improved baseline (which, at these budgets, mostly saturates to 0 fails and so is no longer a
useful testbed — see below).

**Aside: today's baseline has moved far past the `qpk`-era regime.** An earlier pass at this
re-verification (same protocol, same code) produced a systematic false "0 fails" for every arm/seed —
traced to a bug in the *verification script*, not the product: it built `homemaker-fitness`'s target
path as `realpath "../../$dom"` (copied from `experiments/run_8sh_ab.sh`, where the equivalent `$dom`
is relative to the repo root) against an already-absolute scratch path, `realpath` failed, the error
was swallowed by `>/dev/null 2>&1`, and the harness's `fails=0` fallback silently reported success
instead of an error. Once the path bug was fixed, real (non-zero) numbers came back matching the
historical scale. Two things worth remembering from this: (1) `programme-house` at the `1ph` budget
(3000) now reaches 0 fails on every seed/arm tried under today's full default stack — a large
improvement since `1ph` from the many subsequent Phase-8/9+ landings — so it is no longer a useful
regression testbed for this particular question at that budget; harbor-house (budget 2500, still
65-85 fails) still has real headroom and is what the table above uses. (2) a silent-failure-shaped
"suspiciously good" result is a smell — a fallback default that never reports "ERR" loudly is worth
distrusting on sight (the harness now sets `fails=ERR` on a missing `.fails` file instead of `0`,
kept in `qpk_verify_ab.sh`/`qpk_verify_hh_ab.sh` in scratch, not committed).

## 36. Expert review of the numeric/scoring path (`homemaker-py-zrx`) — DONE, 3 confirmed bugs filed

Motivated by §35: the `iio` stale-share leak survived unnoticed because it corrupted scores without
crashing anything. This review read the whole numeric path end-to-end — `fitness.py`, `solver.py`,
`collapse_cmd.py`, the `collapse_insearch` path through `innerloop.py`/`driver.py`, plus the
`geometry.py`/`graph.py`/`dom.py` substrate and `evolve.py` plumbing — hunting specifically for that
bug class (stale shared state, valuation/accounting mismatches, parallel non-determinism). Three
confirmed bugs and one hygiene task, each verified with a runnable probe before filing:

- **`homemaker-py-r5a` (P2) — stale-share *resurrection* through the collapse commit.** The `iio`
  fix guards the *probes*, but when `collapse_global` (or a 2-opt swap) commits a leaf back to its
  stale `share_type`, the k× credit reactivates — a credit the Hungarian matrix just valued at 1× —
  and the resurrected stamp then serialises (`type == share_type` again), so it persists. Minimal
  repro diverges live vs dump/reload evals of the *same tree* 12 vs 19 fails (scores 7.4e-08 vs
  7.3e-11): the §35/91f divergence class, reopened through the commit door. Recommended fix:
  canonicalise stale stamps at `_evaluate_full` entry, mirroring `dom._emit`'s guard.
- **`homemaker-py-cvw` (P2) — parallel staged runs read stale geometry through `id()` reuse.** With
  `n_workers>1`, `search_staged` stage 1 computes `substrate_readiness` in the *parent* process,
  which never scores and so never clears `geometry._cache`; evicted individuals' id-keyed entries
  alias freshly unpickled children. Churn probe: 24/300 readiness values corrupted (worst error ~1.0
  on a [0,1] signal), cache growing unboundedly. Address-dependent stage-1 selection bias — a
  concrete non-BLAS candidate for part of `b8g`'s irreproducibility. Serial runs are safe.
- **`homemaker-py-sd3` (P3) — `collapse_best`'s keep-better guard is vacuous.** Its evaluator is
  built with `_fitness_for`'s default `collapse_insearch=True` (the run flag cannot be threaded
  through), so `base_fails` is measured on a copy that *re-collapses in-eval*: base == collapsed on
  5/5 probed files (logs "12 → 12" where the canonical evaluator shows 15 → 12). The 94g safety
  property is not actually checked against the true base, and a `--no-collapse-insearch` run's
  finish evaluator contradicts its own objective (the deterministic `7ua` mechanism, in the product).
- **`homemaker-py-pek` (P3)** — `fitness.py` carries two `process_storey` definitions; the first is
  dead code silently shadowed by the second, a silent-bug vector for future edits.

Reviewed clean: the gaussian/truncated-e ports, `_gaussian_product`, count/adjacency/level checks and
missing-id suppression, `collapse_global`'s pin/slot/forbid accounting and Jacobi update, the `xcy`
submission-order determinism fix, `NativeEvaluator` deepcopy hygiene (the per-eval
`geometry.clear_cache()` at `_evaluate_full` entry protects the whole in-eval path), and
`merge_divided` (o/s-only, so no share-stamp interaction). `solver.py` is experiments-only — nothing
on the search path calls it. `collapse_finish`'s cand-deepcopy id-reuse hazard was probed 0/6 (Node
trees are reference cycles, so the dead copy outlives the reuse window); a defensive clear at
`collapse_global` entry is folded into `cvw`. Verdict on the method: the §35 hypothesis held — all
three confirmed bugs are silent, non-crashing, and invisible to the test suite (337/337 green
throughout), and two of them sit exactly on the leaf-share/collapse seam `iio` came from.

## 37. Phase 9 plan: ground truth, exact evaluation, solver-directed search (`homemaker-py-2g7`)

**Epic:** `homemaker-py-2g7`. **Status:** scoped 2026-08-02, pre-implementation.
Strategic review of §11–§13 + the 3M-eval runs (`examples/harbor-house/evolve-3M*.log`:
1.7 M evals / 2.4 days inside one 15-fail tier, hard structural fails — level
connectivity, wrong-level — surviving > 1 M evals despite dedicated repair
operators). The scoreboard is lopsided: every fail-count win of Phases 6–8 was a
construction/objective-honesty lever; every search-machinery lever (§11.4 grade,
§11.5 niching/restarts, §11.8 tournament-k, §14 islands, §16 annealing, §29/§30
beam, §27 bubble, §34 autodiff) was null or negative. Three root causes, three
tracks:

1. **No ground truth.** Every non-empty `.dom` in the repo is evolution output —
   there are *no human-generated plans in the corpus*, so nobody has ever
   measured what a known-good design scores; "the examples are solvable" is
   currently unfalsifiable, and the residual taxonomy (crinkliness = 48 %,
   §13.11) may be miscalibrated rather than unmet.
   → `2g7.1` plan→dom composer + traced human solutions (guillotine-cut
   extraction from rectangular partitions; non-slicible input is itself a
   representability finding) → `2g7.2` objective calibration against them →
   `2g7.3` hard/soft fail tiering ("solved" = 0 hard fails; guards: §4.5/§4.9
   inner-loop cliff protection must survive) — **DONE, PASS, see §37.1**.
2. **Evaluation is ~10²–10³× too expensive.** The 80-eval NM inner loop answers
   a question the classic Otten/Stockmeyer slicing-floorplan shape-curve DP
   answers exactly in one bottom-up pass (feasibility + optimal ratios for the
   size/width/proportion family). → `2g7.4` (prototype on harbor-house-l0,
   rectangular-plot approximation, DP as pre-filter + NM warm start), unlocking
   `2g7.9` parallel best-of-N + racing (blocked by `cvw`/`b8g`; §14 showed
   best-of-N ≥ islands; the box has 4 cores and 3M runs used 1–2 workers) and
   `2g7.10` MAP-Elites (elite-per-niche archive — mechanically distinct from the
   failed §11.5/§11.8 diversity-under-one-selection).
3. **Evolution used as a constraint solver.** Discrete subproblems have exact
   methods: `2g7.5` CP-SAT type assignment for a fixed tree (the optimal big
   brother of the §11.6/§11.7 greedy assignment — the biggest Phase-6 win);
   `2g7.6` spike on graph-first construction (rectangular dualization /
   adjacency-realizing slicing trees); `2g7.7` LLM repair operator at stagnation
   (generalising the §4.10 compound-operator lesson: fails are semantic and
   localized, so an LLM proposes the valley-crossing multi-edit; native fitness
   disposes; plateau-only for cost) and later `2g7.8` AlphaEvolve-style operator
   synthesis against the existing A/B harness.

Prerequisite hygiene: the open scoring-path bugs (`cvw`, `r5a`, `7ua`, `sd3`,
`pek`) land first so Phase-9 A/Bs measure a sound objective. Recommended
opening moves: `2g7.1`+`2g7.2` (days, and they redefine the target for
everything else) in parallel with `2g7.4` (the compute multiplier).

### 37.1 `homemaker-py-2g7.3` hard/soft fail tiering — measured 2026-08-02

**Implementation.** `fitness.classify_fail_tier`/`tier_counts` (fitness.py)
classify every fail string emitted across `fitness.py` and `graph.py` into two
tiers, raising `ValueError` on anything unrecognised (no silent default) so a
new fail-emission site must declare a tier:

- **HARD** — no amount of ratio-only optimisation within the current topology
  can fix it; needs a topology mutation (add/remove/retype/reconnect a node):
  missing/excess required space (and its "would need … check" cascade
  placeholders), wrong/required level, level circulation connectivity
  ("level N not connected", "N inaccessible usable space"), vertical/stair
  connectivity, adjacency ("not adjacent to"), stairs count, covered-outside
  support, storey limit/minimum, no outside public access.
- **SOFT** — a continuous per-leaf/edge shape or quality metric the inner-loop
  ratio solve can improve without changing the tree: perpendicular,
  proportion, size, width, crinkliness, access (grouped with the shape family,
  not with `graph.py`'s structural adjacency checks, because `evaluate_leaf`
  computes it identically to proportion/crinkliness — a per-leaf continuous
  factor thresholded against `FAIL_THRESHOLD` — and `_GRADED_FACTORS` already
  groups it there), edge-too-long, staircase volume.

`driver.Individual` gained `n_hard`/`n_soft` (populated from
`innerloop.Result.fail_lines`); `driver.search(use_tiers=True)` swaps the
outer comparator from `(-n_fails, fitness)` to `(-n_hard, -n_soft, fitness)`.
Default off (`evolve.py --use-tiers` / `HOMEMAKER_USE_TIERS`), so existing
runs/reproductions are unaffected.

**Guard 1 (§4.5/§4.9 inner-loop 0.5^n cliff protection).** Not re-measured
empirically — the change touches neither `innerloop.py` nor the existing
`value *= 0.5 ** len(failures)` line in `fitness.py`; tiering only adds pure
functions that classify `driver.py`'s already-collected `r.fail_lines` after
the fact. The cliff is unaffected by construction.

**Guard 2 (§4.9 outer A/B — no scalar-pathology regression).** The tiered key
is still a lexicographic tuple, not a blended scalar, so it structurally
cannot reproduce the §4.8 pathology (a worse-tier design winning on raw
fitness). Encoded as a regression test,
`tests/test_driver.py::test_use_tiers_prefers_fewer_hard_over_fewer_total_fails`:
constructs a seed (0 hard, 2 soft) vs. a mutated child with FEWER total fails
and HIGHER raw fitness but 1 hard fail — the flat comparator picks the child,
the tiered comparator keeps the seed.

**Acceptance A/B** (`experiments/tier_ab_2g7_3.py`, `URB_NO_OCCLUSION=1`,
harbor-house + maple-court, 3 seeds, budget 20 000 native evals/run,
`leaf_sharing=True`, `n_workers=4`, ~2h53m wall):

| programme     | scheme | hard (mean) | soft (mean) | total (mean) |
|---------------|--------|-------------|-------------|---------------|
| harbor-house  | flat   | 11.67       | 29.00       | 40.67         |
| harbor-house  | tiered | **5.33**    | 42.33       | 47.67         |
| maple-court   | flat   | 19.33       | 71.33       | 90.67         |
| maple-court   | tiered | **14.00**   | 87.67       | 101.67        |

Hard-fail mean strictly improves on both programmes (harbor 11.67→5.33,
maple 19.33→14.00) at the cost of more soft fails and a higher raw total —
exactly the intended trade: budget stops being spent polishing shape fails
while structural fails remain. **ACCEPTANCE: PASS.** Full per-seed log:
`scratch/tier_ab_2g7_3/log.txt` (not checked in — regenerate via the script).

**Not yet done** (follow-on, not blocking this bead's acceptance criteria):
`2g7.2`-style calibration of whether tiered search reaches 0 hard fails
faster in wall-clock/eval terms than flat lex at the SAME budget (this A/B
measured fail composition at fixed budget, not convergence speed); an
apples-to-apples "evals to 0 hard fails" race is a natural follow-up once
`2g7.1`/`2g7.2` ground truth lands.

### 37.2 `homemaker-py-2g7.4` shape-curve DP prototype — measured 2026-08-02, ACCEPTANCE: PASS

**What was built.** `experiments/shapecurve_spike.py` + `experiments/
validate_shapecurve.py`: an Otten/Stockmeyer-style shape-curve DP answering
"does some equal-offset ratio assignment clear the size/width/proportion
FAIL_THRESHOLD for every leaf" in one bottom-up pass, for a frozen topology on
harbor-house-l0. Each leaf's feasible (width, height) region is bounded by an
area hyperbola, a min-width line, and an aspect-ratio wedge — closed-form
FAIL_THRESHOLD inversions of `quality_size`/`quality_width`/
`quality_proportion` (`leaf_constraints`, verified against the real Gaussian
formulas by construction, not reimplemented magic numbers: same `conf`/
`get_space_params` lookups `fitness.py` uses, including the "any type code
starting with 'c' or 's'/'o' hits the circulation/outside branch, not its own
programme params" quirk — confirmed at the time as existing product behaviour,
not a bug, by reading `get_space_params`/`quality_size` together. **SUPERSEDED
by §39.4**: that quirk was a real bug, it silently dropped 14% of harbor-house's
programme, and the generic-type tests now match `C`/`O`/`S` exactly, so a
programme code takes its declared params whatever letter it starts with). Regions compose
bottom-up through the slicing tree: a node's cut ALWAYS sums its two
children's contributions into the node's own "w" (`edge0+edge2`) dimension,
with "h" (`edge1+edge3`) the shared/cross dimension — a fixed convention of
`geometry.py`'s division formula (`coord_a`/`coord_b` always interpolate
between edge(0,1) and edge(3,2)), not a per-node choice. The only variable is
which of a CHILD's own (w, h) plays which role relative to its parent, an
EXACT function of that child's `rotation` parity (`_child_contrib` — see the
correction below). Composition runs on a shared log-spaced grid (interval-sum
+ a numpy-vectorised inversion, `_invert`); leaf curves themselves are exact
closed forms, so all discretisation error is confined to internal-node
composition. A top-down `realise()` back-substitution converts a feasible
root point into actual `division` ratios, so the DP's output is a real,
scoreable `.dom` tree, not just a yes/no.

**Explicit scope (per the plan's own caveats).** Only size/width/proportion
is modelled — crinkliness/adjacency/access/level connectivity are graph
terms, out of scope by design. Every quad is approximated by a rectangle with
edge-length-derived (w, h) — exact only for a true rectangle/parallelogram
(see the rotation-invariance correction below for why this is edge lengths,
not a bounding box). `leaf_sharing`/`co_type` target-adjustment is not
modelled (harbor-house-l0's programme doesn't exercise either).

**Correction 1 (caught in review): bounding-box (w, h) is not rotation-invariant.**
The first version measured each quad's (w, h) from its axis-aligned bounding
box in global x/y — silently correct only because harbor-house-l0's plot
happens to be near-parallel to its own x/y axes (~7.5% bbox-area error, see
below). Flagged in review: Urb's Perl ancestor (`Urb::Quad::Straighten`/
`Straighten_Root`) explicitly keeps internal walls mutually orthogonal but
NEVER assumes them axis-aligned — `Straighten()` aligns a division parallel/
perpendicular to its PARENT's own division line, not to global x/y, so a
real building's walls can legitimately run at any angle (45° tried explicitly
below) to the survey/CRS axes the plot's `node:` corners are recorded in.
Confirmed by rotating harbor-house-l0's plot 45° about its centroid: bbox
area error jumped from 7.5% to **102%** (a rotated square's bbox is up to 2x
its true area). Fix: `_dims` measures (w, h) from `(edge0+edge2)/2` and
`(edge1+edge3)/2` — the same pairing `geometry.aspect()` already uses —
which depends only on the quad's own edge lengths, never on global
coordinates. This port's equal-offset division convention already gives the
local-orthogonality property Urb's `Straighten()` provides explicitly (no
such pass exists or is needed in `operators.py`), so this is a safe
substitution, not a new modelling assumption.

**Correction 2 (caught in review, and this one REGRESSED accuracy before
being fixed properly): which dimension sums is not a matter of degree.**
Switching to edge-length (w, h) alone was not sufficient — a first attempt
kept the "measure orientation empirically, per node" structure from the bbox
version (comparing children's summed dims against the parent's under two
hypotheses, picking whichever fit better) and this DROPPED agreement on the
untouched harbor-house-l0 benchmark from 99.0% to **95.5%**, with a false
negative appearing for the first time (previously zero). Root cause:
`geometry.coordinate()` applies a node's OWN `rotation` field even when
reading corners it inherited from its parent — a node with odd rotation has
its local edge0/edge2 pair correspond to its PARENT's edge1/edge3 pair
instead (rotation parity selects between a quad's two possible opposite-edge
pairings; `operators.mutate_divide` randomises this on every newly-divided
node, so it's common, not an edge case). This is not something to measure and
approximate — it's an exact algebraic identity: verified numerically
(float-exact, `29.533730484465025 == 29.533730484465025`) that
`left.w + right.h == parent.w` whenever `left.rotation` is even and
`right.rotation` is odd, independent of skew or global orientation.
`_child_contrib(curve, rotation)` applies this directly (`curve.w_of_h` for
even rotation, `curve.h_of_w` for odd) — no geometry measurement, no
baseline-ratio pass, no heuristic threshold, and the empirical `_orientation`/
`annotate_orientations` machinery from both prior versions was deleted
entirely (simpler code, not just more correct).

**Validation** (`experiments/validate_shapecurve.py`, harbor-house-l0, 200
`driver.random_topology` topologies, 2-14 leaves, seed 12345): compared
against NM search **minimising shape-fail count directly** (`ShapeFailEvaluator`,
budget 100), not `innerloop.optimise`'s full aggregate objective — an earlier
version of this harness used the full objective and found spurious
"disagreements" where the DP's own realised point independently verified at
**zero** shape fails but NM's full-objective search had wandered away from it,
because on a topology missing most of its programme, the 0.5^n missing-space
penalty swamps the objective and NM has no pressure to preserve
shape-feasibility specifically. Minimising shape-fail count alone is the
correct apples-to-apples comparison against what the DP claims to solve.

| metric | harbor-house-l0 (unrotated) | harbor-house-l0 rotated 45° |
|---|---|---|
| agreement | 198/200 = **99.0%** (target >= 95%) | 100/100 = **100.0%** |
| false positives (DP feasible, NM can't reach 0) | 2 | 0 |
| false negatives (DP infeasible, NM reaches 0 anyway) | **0** | 0 |
| speedup (grid_n=150, vs 100-eval NM) | **97.2x** (target >= 50x) | 97.1x |
| plot-level (w,h)-approximation area error | **+7.5%** (bbox, pre-fix) / ~0.1% (edge-length, post-fix) | 102% (bbox, pre-fix) / ~0.1% (edge-length, post-fix) |

The unrotated-plot numbers are BACK to matching the original (pre-Correction-2)
99.0%/0-false-negative result exactly — same 2 mismatches, same seeds
(`623465425`/`1523713848`) — confirming Correction 2 fixed the regression it
introduced without disturbing the genuine, separately-diagnosed residual
error below. The 45°-rotated run (`python experiments/validate_shapecurve.py
100 100 150 45` -- same protocol, `n=100` for wall-clock, the plot's `node:`
corners rotated 45° about their centroid into a scratch copy via
`rotated_plot_dir`) is the direct, reproducible test of the concern that
motivated Correction 1: 100% agreement, confirming the fix generalises and
isn't overfit to harbor-house-l0's near-axis-aligned plot. Zero false
negatives in both: the DP never wrongly rejects a topology NM finds feasible
— the safe direction for a pre-filter (worst case it fails to prune, never
wrongly prunes a viable topology). `_invert`'s pure-Python O(N²) double loop
was ~70% of DP wall-clock before vectorising with numpy (profiled: 170ms →
40ms/topology at grid_n=300 from that change alone; grid_n=150 is the
shipped default, no measured accuracy cost vs. 300 on this benchmark).

**Remaining approximation error, root-caused (unchanged by Corrections 1/2 —
a different, smaller error source).** Both unrotated false positives trace to
the rectangle-vs-true-skewed-quad approximation itself (§37.2's plan-flagged
"equal-offset skew-quad geometry" caveat), not to global rotation or to
composition: the DP's own realised point for both cases had one leaf whose
edge-length-approximated area was comfortably inside its feasible bound, but
whose true `geometry.area` (a real, slightly non-parallelogram quad) fell
just below the true lower bound — an ~8-12% approximation gap, the same
magnitude as harbor-house-l0's own plot-level residual skew. This is a
strictly smaller, already-anticipated error source, distinct from the two
corrections above (which were about measuring w/h and composing them
correctly, not about the rectangle-vs-skew-quad approximation itself).

**ACCEPTANCE: PASS** — all three criteria cleared (agreement, speedup,
quantified approximation error), on both the original and the rotated plot.
**Not done in this session** (follow-on, new bead needed before this can
replace `operators.predicted_shape_fails` in `driver.py`'s real pre-filter
path): wiring the DP into `driver._evaluate`/`innerloop.optimise` as an
actual pre-filter + NM warm-start, multi-storey (`below`-link) support,
`leaf_sharing`/`co_type` modelling, and a true skew-quad (non-rectangle) leaf
region to remove the remaining ~8-12% approximation-error source rather than
just quantify it. `experiments/shapecurve_spike.py` is kept as a reference/
prototype (the §34 `autodiff_spike.py` precedent), not wired into
`innerloop.py`.

### 37.3 `homemaker-py-2g7.1` plan→dom composer — implemented 2026-08-03, trace still open

**Finding that reframed this bead.** `examples/harbor-house/drawings/harbor-house 1.svg`
looked like it might already be a usable human trace. It isn't: it has
exactly 32 `IfcSpace` path elements, matching the upper-storey leaf count of
`examples/harbor-house/3m.dom` (23 + 32 leaves across two storeys), and its
file timestamp is 6 minutes after `3m.dom.ifc`. It's a Bonsai/Blender SVG
export of `3m.dom`'s own IFC — a rendering of evolution output, not an
independent reference. There is currently no human-generated plan anywhere
in the repo; producing one needs the user to actually trace a building by
hand, which is out of scope for a single session. This session built and
tested the **composer** — the code half of the bead — and specified the
trace format so a real trace can be authored later without redesigning
anything.

**Trace format — lines + labels, not room shapes.** Urb's data model
requires every storey to share the ground-floor plot exactly: in
`geometry.coordinate()`, a level root with a `below` link always inherits
its 4 corners from the level below, and `dom.link()` always finds that link
for a root (`by_id("")` is trivially the root itself, so the below-chain
never breaks at level-root granularity). So there is only ever *one* site
outline (the ground plot), never one per storey to keep aligned. Per storey,
the trace is only straight open cut lines + text labels — never closed room
polygons, which is what makes a rough hand sketch usable: room outlines are
*derived* by recursively finding a line that spans the current region
edge-to-edge (with a snapping tolerance for overlap/undershoot/misalignment
slop), never drawn and matched.

**Metadata sidecar = a stub `.dom` file, not a new schema** (this was the
user's call, and it's the right one — reuses `dom.load()`/`dom.dumps()`
verbatim). A "boundary" `.dom` carries `node` (the plot, level 0 only),
`perimeter`, `height`/`elevation`/`wall_inner`/`wall_outer` per level (via
`above` chaining) and nothing else — no `division`, no `type`, no `l`/`r`.
The composer fills in `division`/`left`/`right`/`rotation` per level from
the SVG trace and re-links. Composer matches against the boundary's
`node_file` (raw, as-authored corners) rather than the wall-inset `node` —
a human traces the visible/surveyed outer wall face, not the wall-thickness
inset the geometry engine derives internally.

**Composer only has to get topology right; `solver.solve_ratios` fixes
geometry.** Traced cut positions from a hand sketch are rough. The composer
converts a detected cut into an initial `division` ratio; `compose.refine()`
then calls `solver.solve_ratios(root, targets, strip=False)` to slide cuts
to the best fit for the programme's target dimensions, exactly like the
existing bottom-up solve path (`strip=False` is required — the default
`True` would discard the traced starting ratios and start from 0.5). This
means sub-metre trace precision doesn't matter; only which side of which
line a room falls on does.

**Implementation.** `compose.py`: `parse_svg()` reads Inkscape layers named
`storey-N` (flat, not nested) via `xml.etree.ElementTree`, flattening each
element's `transform` stack (translate/scale/matrix/rotate composed as 2x3
affines); a `<line>` or straight 2-point `<path d="M.. L..">` is a cut, a
`<text>` (its own `x`/`y` or its first `<tspan>`'s) is a label. The
recursive core (`_build`/`_find_span`) mirrors `geometry.py`'s own
division-line algebra exactly (`coord_a`/`coord_b`'s two edge-pairs, and the
left/right child corner formulas the engine uses to re-derive coordinates
top-down) so a composed node's `rotation`/`division` reproduce the traced
corners bit-for-bit when read back. A region with interior lines but none
spanning it raises `NonSlicible(storey, corners)`; a leaf with != 1 label
raises `LabelError` — both name the offending region rather than guessing.
`dom._link` was renamed to the public `dom.link` (one-line rename at all
call sites in `genome.py`/`operators.py`/tests) since the composer needs to
re-link after mutating a loaded boundary tree from outside `dom.py`.
`compose_cmd.py` → `homemaker-compose plan.svg boundary.dom -o out.dom
[--tol 0.15] [--scale 1.0] [--refine]`, mirroring `fitness_cmd.py`'s CLI
shape; catches `NonSlicible`/`LabelError` and prints the diagnostic to
stderr with exit 1 instead of a traceback.

**Verification.** `tests/test_compose.py` (6 tests, synthetic fixtures
only): a 3-room/2-cut partition (exercising both axes and depth-2
recursion) composes, round-trips through `dom.dumps`/`dom.load`, has
leaf areas summing to the plot area, and scores cleanly through
`fitness.Fitness`; the same partition with endpoints perturbed by less
than the default tolerance still composes (and fails with a tightened
tolerance — the negative control); a dangling interior line that spans
neither edge pair raises `NonSlicible` naming the whole-plot region;
label-count mismatches, missing `storey-N` layers, and a boundary/trace
storey-count mismatch each raise a clear error. Manually verified the CLI
end-to-end against the same fixture, including `homemaker-fitness` scoring
the emitted `.dom` (`0/rl size`, `level 0 no outside space`, etc. — expected
fails with no programme/patterns.config on disk). Full suite: 381 passed.

**ACCEPTANCE: PARTIAL.** Composer half done (round-trips a synthetic
slicible partition; non-slicible input reports the offending region). Still
open: tracing an actual harbor-house or programme-house human plan in
Inkscape and composing/scoring it — needs the user's time, tracked as
follow-up under `2g7.1`. `2g7.2` (objective calibration against the human
reference) stays blocked on that trace landing.

### 37.4 `homemaker-py-6xh` shape-curve DP wired as NM warm-start — measured 2026-08-03, ACCEPTANCE: PARTIAL

**What was built.** `2g7.4`'s validated shape-curve DP (§37.2) was still a
reference-only spike (`experiments/shapecurve_spike.py`), not wired into the
product. This session: (1) promoted it verbatim (plus one bugfix, below) into
`src/homemaker_layout/shapecurve.py`; (2) added `shapecurve.eligible(root,
leaf_sharing, superpose, max_share, multi_use)`, gating on the DP's actual
validated scope — single storey (`len(dom.levels(root)) == 1`) and none of
`leaf_sharing`/`superpose`/`max_share`/`multi_use` (none of which
`leaf_constraints` models); (3) wired it into `driver._evaluate` as an NM
warm-start only: when `shapecurve_warmstart=True`, the caller supplied no
explicit `x0` (never override a real Lamarckian warm-start), and the
topology is eligible, `shapecurve.solve(root, fit)` writes an exact
shape-feasible ratio point onto the tree in place *before*
`innerloop.optimise` runs; `optimise`'s existing `x0=None` behaviour (read
the tree's current ratios) then picks it up unchanged. On ineligible or
DP-infeasible, the tree is left exactly as the cold/proportion-aware seed
left it — no new false-negative risk, because nothing is pruned by this
change. Threaded through `driver.search` and exposed as
`homemaker-evolve --shapecurve-warmstart` (off by default, matching every
other experimental search toggle in `evolve.py`). Deliberately **not**
built this session (tracked as follow-up beads under `2g7`, see below): the
DP-exact hard pre-filter (replacing `predicted_shape_fails`' heuristic
threshold), multi-storey (`below`-link) support, `leaf_sharing`/`co_type`
modelling, and the true skew-quad polygon algebra to remove the ~7-12%
rectangle-approximation error §37.2 already quantified.

**Bug caught promoting the spike: `realise()` leaked `numpy.float64` into
`division`.** `_interp_range`'s interpolation branch computes on a numpy
grid, so `t = wl / w` in `realise()` is a `numpy.float64` whenever that
branch fires (common — any non-grid-exact point) rather than a plain Python
float. `experiments/validate_shapecurve.py` never caught this because it
only ever scored the in-memory tree directly, never round-tripped through
`dom.dumps` (`yaml.safe_dump` cannot represent `numpy.float64` and raises
`RepresenterError`). This session's `tests/test_shapecurve.py` does
round-trip (`dom.dumps`/`dom.load` after `solve()`), caught it immediately,
and the fix is a one-line `float()` cast on both list elements of
`node.division`. This means the shipped `experiments/shapecurve_spike.py`
copy silently carries this latent bug too — harmless for the validation
harness's own in-memory comparisons, but would break the moment anyone
tried to write its output to a `.dom` file.

**A/B** (`experiments/ab_shapecurve_warmstart.py`, `examples/harbor-house-l0`
— the DP's own single-storey validated benchmark; the full multi-storey
`examples/harbor-house` is out of scope until the multi-storey follow-up
lands): `driver.search(..., leaf_sharing=False)` off vs on, budget=2000,
seeds 0-4, same-seed paired runs:

| seed | off hard | off soft | off fitness | on hard | on soft | on fitness |
|---|---|---|---|---|---|---|
| 0 | 3 | 13 | 1.222e-08 | 3 | 13 | 1.222e-08 |
| 1 | 4 | 13 | 1.234e-08 | 4 | 8  | 6.556e-08 |
| 2 | 6 | 15 | 6.95e-10  | 5 | 13 | 9.31e-09  |
| 3 | 3 | 18 | 3.954e-10 | 5 | 9  | 2.522e-09 |
| 4 | 6 | 17 | 5.6e-11   | 6 | 17 | 5.6e-11   |
| **mean** | **4.400** | **15.200** | **5.14e-09** | **4.600** | **12.000** | **1.79e-08** |

Wall-clock is identical (56.4s vs 57.1s mean, as expected — same budget, the
DP adds one cheap solve per eligible child). This run used the default flat
comparator (`use_tiers=False`, i.e. `admit()`'s selection pressure is total
fail count, not hard/soft-tiered), so the metric that actually drove which
children survived is **mean total fails**: OFF 4.4+15.2=19.6 vs ON
4.6+12.0=16.6, a ~15% reduction, tracking the ~3.5x mean-fitness improvement.
Mean **hard**-fail count alone ticked up slightly (4.6 vs 4.4) — driven
entirely by seed 3 (3→5); seed 2 moved the other way (6→5), seeds 0/4 tied.
At n=5 seeds this is noise-dominated, not a signal either direction.

**ACCEPTANCE: PARTIAL — net positive on the metric that drives selection
(total fails / fitness), inconclusive on hard fails specifically.** The
warm-start is unambiguously safe (verified by the off/on-parity test,
`test_shapecurve_warmstart_off_matches_baseline`) and measurably improves
soft-fail/fitness convergence on its validated single-storey envelope at
this budget/seed-count. It is not yet the "evals to N hard fails" race the
`6xh` bead framed as the target metric — reaching that needs either a larger
seed count (this A/B's hard-fail delta is within noise at n=5) or the
DP-exact hard pre-filter (`homemaker-py-wkh`) doing more than warm-starting.
Also unresolved: this envelope (single storey, no sharing) excludes most
real programmes by default (`leaf_sharing` defaults `True` in
`driver.search`; `programme-house`/`harbor-house` both require ≥2 storeys),
so today's win applies only when a caller explicitly opts into both
`leaf_sharing=False` and a single-storey seed — the multi-storey
(`homemaker-py-koo`) and leaf-sharing (`homemaker-py-tym`) follow-ups are
what make this apply to the programmes the search actually runs on day to
day.

**Verification.** `tests/test_shapecurve.py` (4 tests): eligibility guard
correctness (multi-storey, each of leaf_sharing/superpose/max_share/
multi_use independently disqualifying); a small feasible topology's
DP-realised ratios round-trip `dom.dumps`/`dom.load` and independently score
zero shape fails via the real `fitness.Fitness`; an obviously-oversized
topology (60 leaves on harbor-house-l0's plot) is correctly infeasible;
determinism. `tests/test_driver.py` (+3 tests): off/on parity when the flag
is off; `shapecurve.solve` is invoked (and its written ratio is visible to
`innerloop.optimise`) exactly when eligible; `shapecurve.solve` is never
invoked on a multi-storey seed. Full suite: 388 passed. Manual CLI smoke
test: `homemaker-evolve init.dom --programme-dir . --no-leaf-sharing
--shapecurve-warmstart` in `examples/harbor-house-l0` runs to completion and
the emitted `.dom` scores cleanly with `homemaker-fitness` (score matches
the run's own reported best).

### 37.5 `homemaker-py-wkh` DP-exact hard pre-filter — measured 2026-08-03, ACCEPTANCE: PARTIAL

**What was built.** `6xh`'s own deferred item 1: use `shapecurve`'s exact
feasible/infeasible verdict alongside `operators.predicted_shape_fails`'
heuristic-count pre-filter (§12.3/9gp.1) in `driver._evaluate`, instead of
only as an NM warm-start. Added `shapecurve.is_feasible(level_root, fit,
grid_n)` — a read-only refactor of `solve`'s own check phase (`_check`, now
shared by both) that never calls `realise()`/writes `division`, so the new
`shapecurve_prune` flag composes cleanly with `shapecurve_warmstart` and the
two can be A/B'd independently without one experiment's tree mutation
contaminating the other's measurement (a real risk: `solve` always writes a
realised point in place when feasible).

**Composition (the design item the bead's own description flagged as
needed).** Conservative by construction, chosen to extend today's prune
guard (`pred > threshold && pred >= best_n_fails`) rather than replace it,
because — per the bead's own risk framing — a wrong prune permanently
discards a topology that could have beaten the incumbent, unlike a bad
warm-start:

- **DP feasible → veto.** A real ratio point exists clearing every leaf's
  size/width/proportion threshold, so a heuristic-triggered prune must have
  come from `predicted_shape_fails`' own single (proportion-aware) layout
  being an unlucky, non-representative sample — not the topology's true
  floor. Never prunes in this case, and skips the `predicted_shape_fails`
  eval entirely (redundant once the DP has already answered the question it
  approximates).
- **DP infeasible + incumbent already at 0 total fails → exact prune.**
  Infeasible proves the shape-fail floor is ≥1 (0/400 measured false
  negatives across both validation sweeps below), which alone beats a
  zero-fail incumbent — no heuristic count needed, and again the
  `predicted_shape_fails` eval is skipped.
- **DP infeasible + incumbent >0 total fails → defer to the heuristic,
  unchanged.** Infeasible only proves the floor is ≥1, not that it reaches
  an arbitrary `best_n_fails>0`; asserting that would need a hard
  *count*, which the DP (a boolean feasibility oracle) does not give.
  `predicted_shape_fails` still runs and its threshold decides, exactly as
  before `shapecurve_prune` existed.

Threaded as `search(…, shapecurve_prune=False)` (mirrors `shapecurve_warmstart`'s
threading exactly — `_evaluate`, the parallel-batch tuple, the explicit
single-seed call) and `homemaker-evolve --shapecurve-prune` (default off).
Note: like the pre-existing `feasibility_filter`/`feasibility_max_shape_fails`
it augments, `shapecurve_prune` is a no-op unless `feasibility_filter=True`
is also set — that pair has never been exposed as its own CLI flag (a
pre-existing gap in `evolve.py`, not introduced here), so
`--shapecurve-prune` alone only reaches the Python `driver.search` API today.

**False-negative-risk validation (bead item (b)): a second, genuinely
non-rectangular plot, not just a rotated copy of harbor-house-l0.**
`experiments/validate_shapecurve.py` was pointed at the *promoted product
module* (`homemaker_layout.shapecurve`, not the frozen `experiments/
shapecurve_spike.py` it validated in §37.2) — the actual code path
`wkh`'s hard-prune now trusts — and given a `programme_dir` CLI arg (was
silently hardcoded to harbor-house-l0 before) to run against
`examples/programme-house`: an authentically skewed parallelogram plot
(`node:` corners not axis-aligned, unlike harbor-house-l0's near-rectangle),
its own 6-space single-storey programme, 200 random topologies, seed 12345
(same protocol as §37.2):

| metric | harbor-house-l0 (re-run, product module) | programme-house (skewed) |
|---|---|---|
| agreement | 20/20 = 100.0% (n=20 smoke) | 200/200 = **100.0%** |
| false positives | 0 | **0** |
| false negatives | 0 | **0** |
| DP feasible / NM 0-shape-fail | — | 20/200 both |
| speedup | 97.6x | **87.4x** |

Zero false negatives on a structurally distinct, genuinely non-rectangular
plot — the DP-infeasible verdict the hard-prune branch relies on has now
been checked on 400 combined topologies (200 harbor-house-l0 from §37.2 +
200 here) across two plots with no measured false negative either time.
This clears the bead's own bar ("a larger/less-rectangular topology sweep
… before enabling by default" — still shipped **off** by default, matching
every other experimental flag in this codebase, but the safety case for a
future default-on is now measured, not just argued).

**`driver.search` A/B (bead item (c)): NULL on harbor-house-l0 at the
6xh-matching protocol.** `experiments/ab_shapecurve_prune.py`, same
benchmark/budget/seed protocol as §37.4's warm-start A/B
(`feasibility_filter=True, feasibility_max_shape_fails=0`, budget=2000,
seeds 0-4, `leaf_sharing=False`):

| seed | off hard/soft/fit/topo | on hard/soft/fit/topo |
|---|---|---|
| 0 | 3/13/1.222e-08/25 | 3/13/1.222e-08/25 |
| 1 | 4/13/1.234e-08/25 | 4/13/1.234e-08/25 |
| 2 | 6/15/6.95e-10/25 | 6/15/6.95e-10/25 |
| 3 | 3/18/3.954e-10/25 | 3/18/3.954e-10/25 |
| 4 | 6/17/5.6e-11/26 | 6/17/5.6e-11/26 |

Byte-identical off/on across all 5 seeds. Instrumented to find out why
(`shapecurve.is_feasible` call-count/verdict spy, seed 0 alone): 17 calls,
**0 feasible, 17 infeasible** — the veto branch never fired (needs at least
one DP-feasible verdict on a would-be-pruned candidate; got none) and the
incumbent's total fails never reached 0 in this run (best hard=3, soft=13,
so the exact-prune branch's own precondition, `best_n_fails<=0`, was never
true either) — every one of the 17 eligible checks fell through to "defer
to heuristic, unchanged" by construction, so nothing *could* have differed.
Root cause is upstream of `wkh`: at `feasibility_max_shape_fails=0`,
`predicted_shape_fails` itself rarely reaches `best_n_fails` (≈16-18 here)
on harbor-house-l0's modest leaf counts — `test_feasibility_filter_
prunes_cheaply` (tests/test_driver.py) already had to monkeypatch it to a
forced 999 to observe *any* real prune, a pre-existing characteristic of
9gp.1 (documented there as a "scaling lever", i.e. expected to bite on
larger programmes/leaf counts, not this benchmark) — not something `wkh`'s
composition introduced or could route around, since it only ever refines a
decision the base heuristic was already about to make.

**ACCEPTANCE: PARTIAL.** Composition designed and landed conservatively
(never prunes anything the pre-`wkh` filter wouldn't have, per the veto/
defer rules above); DP-exactness (0 false negatives) independently
re-validated on a second, structurally distinct plot at the same 200-
topology scale as §37.2's original result — items (a) and (b) from the
bead's own description are done. Item (c), the `driver.search` A/B, is
measured but **NULL** on harbor-house-l0 at this budget/threshold, for the
structurally-understood reason above (the base 9gp.1 filter barely engages
organically at this scale, so there is nothing for `wkh`'s refinement to
change) rather than a defect in the new logic. A benchmark/threshold where
`predicted_shape_fails` organically prunes — a larger programme or leaf
count, where 9gp.1 is itself expected to start mattering — is the natural
next measurement, tracked as a follow-up rather than blocking this landing;
the multi-storey (`homemaker-py-koo`) and leaf-sharing (`homemaker-py-tym`)
follow-ups remain the more direct route to that (today's DP eligibility
excludes `programme-house`/`harbor-house`'s real ≥2-storey, leaf-sharing-
default programmes, the same gap §37.4 already flagged).

**Verification.** `tests/test_shapecurve.py` (+1 test): `is_feasible` agrees
with `solve`'s own verdict on both the feasible and infeasible fixtures
already used there, and never writes `division` in either case.
`tests/test_driver.py` (+4 tests): off/on parity when the flag is off; the
veto branch (DP feasible skips `predicted_shape_fails` and never prunes,
even when the heuristic would have via a forced 999 return); the exact-prune
branch (DP infeasible + `best_n_fails<=0` prunes for 1 eval, skipping
`predicted_shape_fails`); the defer branch (DP infeasible + `best_n_fails>0`
still consults and obeys `predicted_shape_fails`, unchanged). Full suite:
393 passed.

### 37.6 `homemaker-py-koo` multi-storey (below-link) support for the shape-curve DP — measured 2026-08-03, ACCEPTANCE: PASS

**What was built.** `6xh`'s/`wkh`'s own deferred item: the DP's `eligible`
guard excluded any tree with `len(dom.levels(root)) > 1`, so it never fired
on `programme-house`/`harbor-house`'s real ≥2-storey, `leaf_sharing`-default
programmes — the gap both §37.4 and §37.5 flagged as the more direct route to
making either land's win apply day-to-day. `shapecurve.py` now processes
`dom.levels(root)` bottom-up, one storey at a time, instead of assuming a
single free tree. The key fact this is built on: `geometry.coordinate` mirrors
a `below`-linked node's corners from the storey below **unconditionally**,
regardless of whether that storey's counterpart is itself divided — so a
node with `below.divided` True has both its own outer box AND its split
ratio dictated by the (already-realised) storey below (dead variables,
exactly `solver.free_branches`' own free/fixed criterion), while a node
whose `below` is None or undivided has a genuinely free split — and,
critically, that free node's own outer box is *still* pinned by geometry
whenever `below` is not None (only the split inside that fixed box is
unknown). This means every free region the DP has to solve, at every storey,
reduces to the exact same single-region problem the pre-existing (single-
storey) `_check`/`realise` pair already solved — homemaker-py-koo added zero
new curve-composition math, only `_region_roots` (walks a storey's tree,
descending through `below.divided` spines without solving anything there,
collecting the below-fixed leaves and below-fixed-box/free-split fringe
nodes it bottoms out at) and `_solve_all_levels` (the per-storey sequential
driver: realise storey *i*'s free regions before checking storey *i+1*, since
storey *i+1*'s fixed boxes are read off storey *i*'s just-realised geometry,
not chosen; snapshot every storey's divisions up front and restore them
unless every region at every storey was feasible, preserving `solve`'s and
`is_feasible`'s pre-existing all-or-nothing/never-writes contracts exactly).
A below-fixed leaf (no search freedom — its (w, h) is a single known point)
is checked directly against `leaf_constraints` via `LeafBounds.h_range`
(`_leaf_feasible`) rather than routed through the grid-interpolated curve
machinery, avoiding a discretisation error that would otherwise be paid
uselessly, once per below-fixed leaf per storey, on a real multi-storey
building with dozens of wall-stacked rooms. `eligible` now allows any storey
count; only `leaf_sharing`/`superpose`/`max_share`/`multi_use` (still
unmodelled by `leaf_constraints`, `homemaker-py-tym`'s scope) remain excluded.

**Validation** (`experiments/validate_shapecurve_multistorey.py`, same
protocol as §37.2/§37.5 — DP feasibility vs NM search minimising shape-fail
count directly, shape-fail-count-only comparison, see that module's
docstring for why): 200 topologies against the real, non-de-risked
`examples/harbor-house` (storey_minimum 2, full named-space programme, not
harbor-house-l0's C/O-only single-storey de-risk variant). Each trial starts
from a genuinely 2-storey seed (`operators.mutate_level_add` once on the bare
plot) and grows leaves across BOTH storeys via `driver.random_topology`
(`mutate_divide` picks candidate leaves from every level uniformly), so a
trial topology naturally mixes below-inherited-fixed spines with
below-fixed-box/free-split fringe nodes on the upper storey — exactly
`koo`'s new code path, not a corner case constructed to flatter it:

| metric | harbor-house-l0 single-storey (§37.2, for scale) | harbor-house multi-storey (this session) |
|---|---|---|
| agreement | 198/200 = 99.0% | 199/200 = **99.5%** |
| false positives (DP feasible, NM can't reach 0) | 2 | 1 |
| false negatives (DP infeasible, NM reaches 0 anyway) | **0** | **0** |
| speedup (grid_n=150, vs 80-eval NM) | 97.2x | **117.7x** |
| DP feasible / NM 0-shape-fail | — | 4/200 / 3/200 |

Zero false negatives — the property the hard-prune (`wkh`) branch actually
depends on — holds on the real multi-storey target at the same 200-topology
scale as every prior sweep (harbor-house-l0 unrotated 200 + rotated 100 +
re-run smoke 20, programme-house 200, this session's harbor-house
multi-storey 200 — 0 false negatives throughout, 720 topologies total across
the DP's whole validation history). The single false positive
(topology 119, seed 19314526) is consistent with the already-quantified
rectangle-vs-true-skewed-quad approximation error (§37.2) compounding across
two storeys rather than a new defect — not re-investigated to the same depth
§37.2 gave its own two false positives, since the safety-critical direction
(false negatives) is unaffected and the magnitude matches expectation.
Manual smoke test: `driver.search(..., shapecurve_warmstart=True)` and
`driver.search(..., shapecurve_prune=True, feasibility_filter=True,
feasibility_max_shape_fails=0)` both run to completion from
`examples/harbor-house/init.dom` (budget=300, 2 realised storeys in the
result) without error — the full pipeline this bead was blocking, not just
the DP in isolation.

**Not done in this session** (deliberately out of scope, per the bead's own
framing): a `driver.search` A/B on multi-storey harbor-house at `6xh`/`wkh`'s
budget=2000/5-seed protocol — `koo`'s job was making the DP correct and safe
on multi-storey trees at all, which the DP-vs-NM agreement/false-negative
bar above (the same bar §37.2/§37.5 used) already clears; measuring the
search-level payoff is better sized as its own follow-up once
`leaf_sharing` support (`homemaker-py-tym`, still gating most real programmes
by default) lands too, so one A/B can measure the combined win instead of two
partial ones. `leaf_sharing`/`co_type` modelling and the true skew-quad
(non-rectangle) leaf region remain open, as they were before this session.

**Verification.** `tests/test_shapecurve.py` (+4 tests, 1 renamed): `eligible`
no longer excludes multi-storey (renamed from
`test_eligible_guards_multistorey_and_sharing`); a 2-storey fixture whose
upper storey is a fresh free split pinned to the whole plot (ground storey
undivided) realises zero shape fails end to end; a mixed fixture (upper
storey a structural copy of the ground storey, i.e. below-fixed, with one
leaf further divided into two brand-new below-free leaves) writes ratios on
exactly `solver.free_branches` and leaves every below-fixed node's own
`division` byte-identical; the same mixed fixture with an intentionally
oversized child type is infeasible and rolls back **every** level, including
the ground storey already realised earlier in the same call, not just the
storey where infeasibility was detected; `is_feasible` never writes on either
multi-storey fixture. `tests/test_driver.py`: the multi-storey warm-start
test renamed and inverted (`test_shapecurve_warmstart_handles_multistorey`
now asserts `shapecurve.solve` **is** called on a multi-storey child, where
it previously asserted the opposite). Full suite: 397 passed.

## 37.7 CP-SAT type assignment for a fixed tree (`homemaker-py-2g7.5`) — CLOSED: seeder-level positive in isolation, does NOT survive a full driver.search run; both flags stay default off

`§11.6`/`§11.7`'s greedy connected-dominating-set + hardest-constrained-
code-first room placement (`operators._assign_adjacency_aware`) was Phase
6's single biggest fail-count win, but it is a one-shot heuristic: each
room code is placed onto the locally-best open slot and never revisited.
The bead's premise: for a FIXED topology, room-code-to-leaf assignment
(~30-70 leaves, ~16-26 codes) is small enough for exact solve. DESIGN.md
§25 (line ~3089) explicitly rejected adding OR-Tools for a harder, different
problem (`Fitness.collapse_global`'s finish-time relabel) "because the
project has no ortools" — that gap is now closed (`pyproject.toml`
`ortools>=9.10`), but only for this bead's simpler fixed-topology labelling
problem; `collapse_global` itself is untouched (deferred, see below).

**What shipped.** `src/homemaker_layout/cpsat.py`: a single pure function
`solve_room_labels(slots, codes, reqs, neighbors, context_types)` — a
boolean assignment ILP (`x[i,s]`, one code per slot) with a `sat[i,s,adj]`
reified-AND term per (code, adjacency-requirement, slot), maximising total
satisfied requirements. Matches `graph.check_adjacency`'s REAL semantics
(full-code case-insensitive prefix match) rather than the existing greedy
heuristic's first-character-only local approximation — a strictly closer
proxy for what `homemaker-fitness` actually scores. Wired in as:

- (a) **seeder**: `_assign_adjacency_aware`/`constructive_topology`/
  `lift_base_to_storeys` gain `assign_solver: str = "greedy"|"cpsat"`
  (EXPERIMENTAL, default `"greedy"` — byte-identical to before). Circulation/
  outside placement (the dominating-set step, a graph-connectivity problem,
  not this bead's ~30-70-leaf combinatorial one) is unchanged either way;
  only the room-code-to-slot step is replaced. Falls through to the
  greedy/beam path on any solver failure (unavailable/infeasible/timeout).
- (b) **`operators.mutate_reassign`** (new `MUTATIONS` entry, default weight
  0 unless `driver.search(..., enable_reassign=True)`): the "assignment
  analogue of ruin_recreate" (§23) the bead's own plan named — picks the
  same kind of wing `mutate_ruin_recreate` does, but does NOT un-divide or
  regrow it; only re-solves which leaf gets which code, preserving the
  wing's exact room-code multiset and topology.
- (c) **post-collapse repair** — deferred, filed as `homemaker-py-5bv`
  (child of `2g7`/`2g7.5`): replacing/augmenting `Fitness.collapse_global`'s
  Jacobi+2-opt QAP relaxation is a materially separate, riskier change to a
  delicate routine that runs inside every in-search eval by default
  (`collapse_insearch=True`) — correctness/wall-clock regressions there
  would be felt everywhere, not just behind an opt-in flag.

**Two bugs found and fixed en route, both worth recording.**

1. *Resize fragility.* First measurement (seeder-only, `constructive_topology`,
   harbor-house, 6 seeds): with `proportion_aware=True` (the real default —
   target-size-based ratio resizing right after assignment), `cpsat` was
   WORSE than greedy on real fitness-scored secondary-adjacency fails (104
   vs 92 total) despite tying/slightly-beating it with `proportion_aware=False`
   (86 vs 87). Root cause: resizing can shrink a shared-wall segment below
   the door-width adjacency threshold, silently invalidating an edge the
   exact solve specifically relied on — it packs satisfaction tightly
   against the PRE-resize graph, leaving less slack than the greedy path's
   more conservative, degree-biased placement. Fix: `_cpsat_relabel_settled`
   re-runs the exact solve once more against the now-settled geometry,
   right after `_size_divisions_from_targets` — cheap (same small model),
   never worse (can only improve on wherever resizing left it). This is the
   bead's own "§11.2 lesson … re-run assignment after geometry settles
   (alternating minimization)" applied literally. After the fix: 82 vs 92
   (cpsat now ahead) at the same protocol; a wider 10-seed re-check
   (`tests/test_operators.py::test_assign_cpsat_matches_or_beats_greedy_secondary_adjacency`)
   holds: 13/20 seed-pairs cpsat-better, 4 ties, 3 cpsat-worse, net ~13%
   fewer total real fails.
2. *Symmetry blowup.* Isolated solves on real harbor-house models (~15
   slots — trivial by variable count) occasionally stalled for multiple
   seconds against a 2s `time_limit_s`, non-deterministically (system-load
   dependent, since a timeout returns whatever CP-SAT's branch-and-bound
   had reached). Cause: several codes sharing an identical, unreferenced
   adjacency signature (e.g. four "t" bedroom instances all needing only
   "c") are fully interchangeable — CP-SAT's branch-and-bound was proving
   optimality across their entire permutation space. Fix: group codes that
   share their own adjacency-requirement set AND are never themselves a
   match target for any other code's requirement; force a canonical
   slot-index ordering within each group (never removes an achievable
   objective value, only the redundant permutations of it). All previously-
   slow captured instances now solve in <200ms. A naive first attempt at a
   fix (a lexicographic tie-break term folded into the objective) made
   things WORSE (more instances timed out) by widening the objective's
   coefficient range — reverted in favour of the explicit grouping
   constraint above.

**`driver.search`-level A/B: RUN TO COMPLETION at the bead's own acceptance
protocol (harbor+maple, 3 seeds, budget=20000) — result does NOT clear the
bar.** An earlier pilot (harbor-house only, budget=3000) was inconclusive
because `reassign` never fired in the small child-count that budget
produces. The full run (`experiments/ab_cpsat_assign.py 20000 3
<programme>`, ~12h wall clock, 18 `driver.search` runs total; raw log
`experiments/results/ab_cpsat_assign_20k_harbor_maple.log`) settles it:

| programme | greedy hard/soft | cpsat hard/soft | reassign hard/soft |
|---|---|---|---|
| harbor-house | 9.3 / 35.3 | 13.0 / 32.0 | 8.3 / 35.3 |
| maple-court | 22.7 / 72.3 | 22.3 / 68.3 | 35.3 / 77.7 |

`reassign_fired` (mean over 3 seeds): harbor-house 0.0, maple-court 0.3 —
i.e. it fired in only 1 of 18 runs total (1 of 6 `reassign`-arm runs), even
at 20k budget. None of the bead's three acceptance criteria hold: `cpsat`
is WORSE than greedy on harbor-house hard fails (13.0 vs 9.3) and only
roughly tied on maple-court (22.3 vs 22.7) — no consistent "strictly lower"
win; `reassign` is worse than greedy end-to-end on maple-court (35.3 vs
22.7 hard); and the operator does not reliably fire even once per run.
Likely explanation: CP-SAT's exact optimum at seed geometry (or after
`_cpsat_relabel_settled`) doesn't stay optimal once the inner loop keeps
moving ratios across thousands of further evals — the bead's own §11.2
lesson, but the "re-run after geometry settles" fix only re-solves once,
not continuously, and any seeder-level gain gets swamped by ordinary search
noise over a 20k-eval run. Not pursuing a higher budget or more seeds to
chase this further — the direction (no clear win, one programme regresses)
is consistent enough between the pilot and the full run to close it out.

**Verdict: ship as opt-in EXPERIMENTAL, both default off, and leave it
there** (matching every other flag in this codebase) — the seeder-level win
in isolation (item (a), measured via
`test_assign_cpsat_matches_or_beats_greedy_secondary_adjacency`) is real and
low-noise, but does not survive contact with a full `driver.search` run
across two programmes at the bead's own acceptance budget. `2g7.5` is
CLOSED on this basis. `homemaker-py-5bv` (child of `2g7`/`2g7.5`) remains
open, tracking the deferred item (c).

**Verification.** `tests/test_cpsat.py` (5 tests): a hand-built
counter-example graph (hub + one non-hub edge) where the beam/greedy
heuristic (`operators._beam_place_rooms`) provably strands two codes that
need each other while CP-SAT finds the assignment satisfying all of them;
fixed-context credit without a decision-neighbour; over-capacity code
dropping (least-constrained first); determinism; empty-input degeneracy.
`tests/test_operators.py` (+5): CP-SAT seed satisfies
`graph.check_space_counts`/stays canonical; the 10-seed secondary-adjacency
A/B above; `mutate_reassign` no-ops without `reqs`; fires-and-preserves-
multiset over 20 trials. `tests/test_driver.py` (+2): `assign_solver`
default and `enable_reassign` default both reproduce prior runs
byte-for-byte (`sig`/`n_topologies`/`n_evals` equality), the same clean
single-variable-toggle control every other experimental flag in `driver.
search` uses. Full suite: 409 passed.

## 37.8 Spike: graph-first construction — adjacency-realizing slicing trees / rectangular dualization (`homemaker-py-2g7.6`) — NO-GO

Timeboxed research spike (no code deliverable expected unless the literature
review came back clearly positive; it didn't). Premise: instead of mutating
trees and hoping the programme's adjacency requirements emerge (§11.6/§11.7's
greedy CDS seeding), *construct* a slicing tree that realizes the required
adjacency graph by construction, using the rectangular-dualization literature
(VLSI/architectural floorplanning: planar graph → set of mutually-adjacent
rectangles). Question: does that literature actually apply to our programme
graphs, and if so is realizing-tree enumeration tractable at harbor scale?

**The literature, briefly.** A properly-triangulated planar (PTP) graph — every
internal face a triangle, every internal vertex degree ≥4, no separating
triangle — has a *rectangular dual* (one rectangle per vertex, adjacent iff
edge-connected), constructible in linear time via a regular edge labeling
(Kozminski & Kinnen 1985; Bhasker & Sahni 1986; He 1993). Two caveats that
matter here: (1) an arbitrary requirement graph must first be triangulated to
reach PTP form, and triangulation *adds* edges (chosen by the algorithm, not
the architect) — every added edge is a spurious adjacency constraint the
programme never asked for; (2) not every rectangular dual is **sliceable**
(reachable by our guillotine-cut binary tree) — Yeap & Sarrafzadeh (1993)
characterize the sliceable subset and the standard counterexample is the
"pinwheel": five rectangles arranged around a shared interior point, each
touching its two neighbours, with no single straight cut that separates the
figure. Counting results in the floorplan-combinatorics literature put general
("mosaic") rectangular duals in bijection with Baxter permutations (~8^n
growth) and sliceable ones in a strictly smaller class related to guillotine
partitions (~5.8^n, the Schröder-number growth rate) — both exponential in
room count, sliceable a smaller exponential inside the general one.

**Does our programme graph fit the model at all? No — the load-bearing
mismatch is upstream of sliceability.** Rectangular dualization's central
assumption is **one graph vertex = one final rectangle**. Checked against the
actual required-adjacency graph (`programme.load_programme_dir` +
`derive_colocate_pairs`, computed live for harbor-house: 16 codes / 32 room
instances, `storey_minimum: 2`):

- Every one of the 16 codes requires adjacency to `c` (circulation) — a single
  hub vertex of degree 16 (32 at instance granularity) in graph terms. But `c`
  is never realized as one rectangle: `§11.6` built adjacency-aware seeding
  specifically because "a single circulation leaf cannot border a dozen
  rooms" — circulation is a *connected region of several leaves* (a greedy
  connected dominating set over the geometric leaf graph), shape and leaf
  count both emergent, not fixed in advance. Rectangular-dual theory has no
  vertex type for "one region, unknown number of constituent rectangles,
  shape decided by the rest of the layout" — that is precisely the soft-module
  / non-rectangular-module extension of the literature (L/T-shaped modules),
  a materially harder and less mature body of work than plain PTP
  dualization, and still assumes the module's *adjacency set* is known in
  advance. Ours isn't: which leaves end up in the circulation CDS is a
  function of the tree that doesn't exist yet — circular for a construct-
  first approach.
- The **non-circulation** requirement graph (room ↔ room edges only, `c`/`o`/
  `s` excluded) is, by contrast, close to empty: harbor-house has exactly
  three edges among 16 codes — `da1↔k1` (explicit `adjacency:`), `ef1↔m` and
  `la1↔me1` (`co_locate:`, i.e. §26's fused-leaf pairs) — the rest isolated,
  no code of degree >1. Checked live (`networkx.check_planarity`): trivially
  planar, but planarity was never in doubt at this density — a 3-edge matching
  on 16 nodes needs no dualization machinery, PTP triangulation, or REL
  construction. `operators._assign_adjacency_aware`'s constraint-ordered
  placement (§11.7: "codes with the most non-`c` adjacency requirements are
  placed first … clustering `k1↔da1`, `da1↔o`, etc.") already handles a graph
  this sparse by direct sibling-clustering; confirmed empirically —
  `evolved-3M-nols-3.dom.fails` (the 2g7.7 issue's own named 15-fail plateau
  benchmark) has **zero** secondary-adjacency fails. The residual there is
  8 geometry fails (size/width/proportion/crinkliness on specific leaf paths)
  and 4 structural fails (`level 0 not connected`, `level 1 not connected`,
  `me1 on wrong level`, `r on wrong level`) — connectivity-*within*-a-level and
  cross-storey placement, not room-to-room adjacency. A perfect
  graph-dualization construction for the sparse room graph would not touch
  any of these.
- **Multi-storey stacking has no literature answer.** Harbor's L0/L1 room
  sets are almost disjoint (13 L0-only, 13 L1-only codes/instances, 6 free),
  linked only through `genome.py`'s base-floor-plus-delta encoding and the
  vertical-core-alignment invariant (§11.3/§11.7: upper floors must not
  "recreate the §4.2 partial-objective trap … the vertical core must stay
  aligned and load-bearing walls must stack"). Rectangular dualization is a
  single-plan-per-graph algorithm; nothing in the surveyed literature jointly
  dualizes two graphs under a shared-footprint/aligned-core constraint. Making
  that work would be new research, not an application of an existing result —
  and it would be solving it for the *dense* hub-and-stacking problem that
  the point above already shows the classical model can't represent anyway.

**Enumeration tractability, for completeness.** Even setting the mismatch
aside: the sparse room-graph is realizable by exactly the number of sibling
pairings possible (small, already handled). The circulation hub isn't a
fixed-graph dualization problem at all (previous point), so "how many
realizing trees" isn't well-posed for it — the honest analogue is "how many
binary slicing trees exist over N leaves", which is a Schröder-number-scaling
count (~5.8^N) at harbor's 32-leaf-plus-circulation scale (N≈45-55 leaves
after `§11.6`'s "~one extra leaf per three rooms on circulation") — far too
large to enumerate, which is exactly why the codebase already searches
(evolutionary + CDS-guided constructive seeding) rather than enumerates.

**Verdict: NO-GO.** Classical rectangular dualization does not apply to
harbor's programme graph as posed: the one-vertex-one-rectangle assumption
breaks exactly where the problem is hard (the circulation hub, realized as an
emergent-shape connected leaf-set, not a fixed-adjacency single module), and
where the assumption *would* hold (the 3-edge secondary room graph) the
problem is already trivial and already solved by §11.7's constraint-ordered
seeding — confirmed by zero secondary-adjacency fails on the project's own
named plateau benchmark. Multi-storey joint dualization under a stacking
constraint is open research, not a citable algorithm, and would only matter
for the part of the graph the model can't represent anyway. Not prototyping.
No change to `operators.py`/`genome.py`. `homemaker-py-2g7.6` closes on this
write-up; the useful fraction of the original idea (construct, don't just
mutate, toward required adjacency) is already shipped as §11.6/§11.7's
CDS-based seeding, and the actual harbor plateau (§37.7's own benchmark) is a
connectivity/level-placement/geometry problem, not an adjacency-graph one —
future effort on that plateau (`homemaker-py-2g7.7`'s LLM repair operator, or
a level-connectivity-targeted operator) is better aimed than a graph-dual
construction pass would have been.

## 38. The plateau is an objective-gradient problem, not a search problem (`homemaker-py-2v1`/`ssz`/`hxi`/`tdp`/`gvb`/`1i8`) — measured 2026-08-25

Independent review of why the search "finds solutions that are clearly not the
best and gets stuck in local minima", prompted by the §37 scoreboard: *every*
fail-count win of Phases 6–8 was a construction/objective-honesty lever and
*every* search-machinery lever (§11.4 grade, §11.5 niching/restarts, §11.8
tournament-k, §14 islands, §16 annealing, §29/§30 beam, §27 bubble, §34
autodiff, §37.7 CP-SAT) was null or negative. That pattern is itself the
finding: eight independent attempts to improve the *search* all failed, which
is what you would expect if the search is working correctly and the
**objective's gradient points away from good buildings**.

Reproduce everything below with `experiments/diag_exposure_frontage.py`
(`frontage` / `exposure` / `value` reports; no search run required).

### 38.1 Zero-exposure leaves score a hard quality of 0 (`homemaker-py-ssz`)

`fitness.quality_uncrinkliness` computes `crink = area_outside / area` and
returns a hard `0.0` when `area_outside == 0` — a leaf with no daylit wall
(no non-`private`/`fortified` external edge, no adjacent uncovered outside
leaf). This is the mathematically consistent limit of the formula
(`1/crink → ∞`, and `gaussian(∞, …) → 0`), so it is a **faithful port, not a
porting bug** — but its consequences were never traced:

- `evaluate_leaf` **multiplies** factors into `quality`, and `process_storey`
  accumulates `value += quality * rate * area`. A buried leaf therefore
  contributes **exactly zero value** while still adding cost.
- So the objective cannot distinguish a buried room that is perfectly sized
  from one that is absurd. Both score zero. The only thing the objective can
  still see about a buried room is that it costs money.

Measured share of interior/covered leaves that are zero-exposure, under the
driver's real default stack (`leaf_sharing`, `depth_balanced`,
`interior_outside`, `collapse_insearch`), 3 constructed seeds each:

| programme | zero-exposure | wrong-ratio | ok |
|---|---|---|---|
| harbor-house | **36 (46%)** | 24 | 18 |
| health-centre | **35 (45%)** | 0 | 43 |
| maple-court | **83 (56%)** | 44 | 22 |

On a converged run (`homemaker-evolve init.dom --budget 20000 --seed 1`,
harbor-house, 57 fails) **14 of 17 crinkliness fails are zero-exposure**, and
roughly 470 m² of the 721 m² ground-floor plate sits at zero value.

### 38.2 Buried circulation and outside space are negative-value (`homemaker-py-hxi`)

Programme rooms are pinned in place by the missing-space fail cascade — but
nothing pins circulation (`C`) or outside (`O`) leaves, which carry no
`count:` requirement. Deleting a buried one is therefore a pure win.
Measured on a constructed harbor-house seed (`value` report):

| deleted leaf | score change | fail change |
|---|---|---|
| buried `O`, 45.8 m² | **×85.6 BETTER** | 92 → 85 |
| buried `C`, 46.6 m² | **×61.6 BETTER** | 92 → 86 |
| buried `k1`, 30.3 m² | ×0.00 worse | 92 → 107 |
| buried `da1`, 61.7 m² | ×0.00 worse | 92 → 107 |

**The search is rewarded, by roughly two orders of magnitude, for deleting the
circulation spine.** Observed live: in the 20 000-eval harbor-house run above,
`undivide`/`core_undivide` appear 16 times in the improvement log.

**Refinement (measured 2026-08-25, after the first draft of this section):
zero-exposure is only half of it, and not the half that matters most.**
Repeating the deletion test separately for *lit* and *buried* circulation:

| leaf | exposed wall | `q_crink` | deleting it |
|---|---|---|---|
| `0/llll` `O` | buried | 0 | **×85.6 rewarded** |
| `0/lllr` `C` | buried | 0 | **×61.6 rewarded** |
| `1/rlrr` `C` | buried | 0 | **×6.9 rewarded** |
| `0/rlll` `C` | 27.4 m² | 0.105 | ×0.01 kept |
| `0/lrrl` `O` | 21.2 m² | 0.0004 | ×0.61 kept |
| `0/rrll` `C` | 40.7 m² | **0.736** | **×4.1 rewarded** |

The last row is the important one: a **well-lit** circulation leaf, scoring
0.736 on the very factor §38.1 is about, is *still* worth ×4 to delete. So
there is a second, independent mechanism, and it is the structural one:

**Circulation is priced at `value_circulation = 50` against
`value_inside = 300`** — one sixth the value per m² of the habitable space it
could become. Deleting a circulation leaf merges it into its sibling, which
converts corridor into room: a flat **×6 value gain**. The only thing pushing
back is the `level N not connected` fail, worth **×0.5**. Break-even needs
`0.5^k < 50/300`, i.e. **k > 2.58 — severing must cost at least 3 fails to be
net-negative. It costs 1.** Net incentive to sever: `6 × 0.5 = ×3.0` in
favour, against a measured ×4.06. **The connectivity fail is under-priced by
roughly 3×, so the objective is net-positive on destroying the circulation
spine even when the circulation is perfectly daylit.**

**RETRACTED — see §39.8.** The inference above ("the objective is net-positive
on severing the spine") does not survive measurement. It assumed severing costs
exactly one failure; it does not. Every deletion that actually breaks
connectivity is already punished — measured ×0.00 to ×0.58 across harbor-house
and maple-court, not one rewarded. The ×4.06 figure above is real but was
measured on a deletion that did **not** change the connectivity fail count, so
it is not evidence for this mechanism. The deletions that are rewarded are
rewarded because they remove the deleted leaf's OWN quality failures (7–9 of
them), which is §38.1's zero-value finding, not a connectivity mispricing.

Why `level 0/1 not connected` persist in the best layout is therefore still
open, but it is not that the search is paid to create them.

Together these retro-explain three prior results as one mechanism, and suggest
two of them were measuring a broken gradient rather than a bad idea:

- **§18 graded circulation-connectivity — NEGATIVE.** A secondary comparator
  key cannot beat a ×60 primary-scalar gradient pulling the other way.
- **§21/§22 `bridge_circulation` — mixed/null.** The operator inserts exactly
  the corridor leaves the objective then pays to delete.
- **The 3M-eval run's `level 0/1 not connected` hard fails surviving >1M
  evals.** Not a stubborn search; a correctly-followed gradient.

### 38.3 The binding constraint is a frontage budget (`homemaker-py-tdp`)

Closed form, no search needed. Crinkliness fails when `1/crink > 1.6202`
(solving `gaussian(x, 1, 5/6, 1.1/3) = FAIL_THRESHOLD`), and `crink = L·h/A`,
so every interior leaf needs exposed wall `L ≥ A/(1.6202·h)` — per storey,
`A_storey/4.86` metres at `h = 3`. `area_outside` skips `private` and
`fortified` perimeter edges, and harbor-house/maple-court mark **half their
plot perimeter `private`**:

| programme | daylit frontage | needed per built storey | verdict | floor @20k evals | best known |
|---|---|---|---|---|---|
| harbor-house | 54 m | 148 m | **2.7× short** | 30–40 fails (§13.11) | 15 (`evolved-3M-nols-3`, **1.7 M evals / 2.4 days**) |
| maple-court | 56 m | 162 m | **2.9× short** | 74–84 fails (§13.11) | — |
| health-centre | 43 m | 41 m | feasible | §32 clean null | — |
| programme-house | 24 m | 12 m | 2× surplus | — | **1 fail @ 12k evals** |

**PARTLY RETRACTED — see §39.11.** The "2.7× / 2.9× short" figures below are
computed for a **fully built plot**, which is not what these programmes ask
for. Against actual demand the deficits are far smaller and both are closable:
harbor needs 86 m against 54 m supplied (a 48 m² courtyard, with 304 m² of plot
spare), maple 70 m against 56 m (20 m²). Neither is infeasible. The one
programme that genuinely does not fit is health-centre, for an unrelated and
much simpler reason: it demands 240 m² on a 197 m² plot.

**Frontage deficit predicts the COST of solving, not impossibility.** An
earlier draft of this section claimed the deficit predicts the plateau
outright, quoting §13.11's 20k-budget figure as harbor's floor; that was
wrong. Harbor-house *does* reach 15 fails — it just needs 1.7 M evals and 2.4
days to get there, against programme-house's 1 fail in 12 k. That ~150×
budget gap between a frontage-short and a frontage-surplus programme is the
real signature, and it is what §38.1/§38.2 predict: the deficit forces the
search to find a specific courtyard topology, and the objective punishes every
intermediate step toward one.

**The best-known harbor layout corroborates the mechanism directly.** Its
residual (§37.8) is 8 geometry fails plus 4 structural — and two of those four
are `level 0 not connected` and `level 1 not connected`. After 1.7 M evals,
the best layout ever found still has a **severed circulation spine on both
storeys**. That is not a search failure; it is §38.2 working as designed: the
objective pays ×60 to delete buried circulation, so connectivity is the one
thing that never survives to the end. Any fix to §38.1 should be judged first
on whether those two fails disappear.

Causal check
(`experiments/diag_exposure_frontage.py`, 6 seeds): relabelling harbor's two
`private` edges as open — identical geometry, identical programme, perimeter
labels only — cuts zero-exposure leaves **52% → 19%** and seeder crinkliness
fails 16.5 → 12.0.

The deficit *is* closable: ~108 m² per storey (≈15% of the plate) given over
to ~3 m courtyard slots would satisfy harbor's budget while still leaving
1226 m² of floor against an 835 m² programme demand. **But that is precisely
the move the objective punishes en route** — a small new `O` leaf is itself
buried, hence zero-value, hence worth ×85 to delete. The payoff only arrives
once a slot is wide enough and long enough to serve many rooms at once. Every
intermediate step is punished; the reward is behind a coordinated multi-leaf
move. That is the valley, and no amount of population diversity crosses it
when the gradient opposes you the whole way — which is why §11.5, §14, §16 and
§37.10-style diversity levers were always going to be null here.

### 38.4 Crinkliness is mis-tiered as SOFT (`homemaker-py-gvb`)

`fitness._SOFT_FAIL_MARKERS` lists `" crinkliness"` as SOFT, defined in §37.1
as "a continuous per-leaf shape metric the inner-loop ratio solve can improve
without changing the tree". **False for the zero-exposure case**: no ratio
assignment can give a buried leaf a wall, so by this document's own definition
it is HARD. Zero-exposure share of crinkliness fails: harbor-house 60%,
maple-court 65%, health-centre 100%, and 82% (14/17) on the converged run.
Since crinkliness is the single largest fail category (48% of the residual,
§13.11), **the §37.1 tiered comparator is mis-informed about the largest block
of fails it sorts** — `n_soft` is not the polish-budget signal it was designed
to be. Fix: emit a distinct fail string for the zero-exposure case (which also
makes the condition visible in `.fails` output, where today it is
indistinguishable from an ordinary shape miss) and tier it HARD.

### 38.5 The missing-space cascade is weighted by YAML verbosity (`homemaker-py-1i8`)

`graph.check_space_counts` emits, per missing room instance, 2 base fails
(`missing required space: X` + `(critical)`) plus one `would need <check>`
placeholder for **each of `size`/`width`/`proportion` the programme happens to
declare** — `has_size` is literally `"size" in c` from the YAML. So a missing
room costs 3–5 fails depending only on how many optional keys the author
typed, and under `value *= 0.5 ** len(failures)` that is a **4× difference in
fitness weight between two single rooms**. In programme-house, missing `b1`
(declares all three) = 5 fails = 1/32; missing `t2` (declares `size` only) =
3 fails = 1/8. The tiered comparator inherits it: `n_hard` is dominated by
these cascades, so the primary search key is weighted by config verbosity.

### 38.6 First repair attempt: three crinkliness modes — NOT SUFFICIENT ALONE

`fitness.quality_uncrinkliness` gained `crinkliness_mode` (config key,
EXPERIMENTAL, default `"urb"` = stock hard 0.0, byte-identical to all prior
runs). Three candidate repairs, A/B'd on the §38.2 deletion test (harbor-house,
3 constructed seeds, unpinned `C`/`O` leaves only):

Splitting the deleted leaves by whether they were buried or lit is what makes
the result legible (`experiments/ab_crinkliness_mode_ssz.py`):

| mode | buried rewarded | **lit rewarded** | all | median × |
|---|---|---|---|---|
| `urb` (stock) | 5/8 | **3/8** | 8/16 | ×1.02 |
| `floor` (clamp to 0.01, keep the fail) | 5/8 | **3/8** | 8/16 | ×1.02 |
| `compact_ok` (one-sided: compact is not a defect) | 5/8 | **3/8** | 8/16 | ×1.00 |
| `exempt_circulation` (corridors need no daylight) | **4/8** | **3/8** | 7/16 | ×0.61 |

**None of them removes the incentive, and the `lit` column does not move at
all — 3/8 under every mode, including stock.** That column is mechanism (2)
in isolation: deleting a *well-daylit* corridor is rewarded for reasons that
have nothing to do with crinkliness, so nothing written inside
`quality_uncrinkliness` can ever reach it. `floor` is inert (0.01 of a unit
quality is still ~zero against the cost saving); `exempt_circulation` removes
exactly one buried case.

The modes are kept, default off, as one half of a fix that needs both halves.
**Do not ship any of them as a standalone lever and expect the connectivity
fails to move** — `homemaker-py-2v1` is the half that matters.

### 38.7 Consequences for the Phase 9 plan

§37 track 1 ("no ground truth … the residual taxonomy may be miscalibrated
rather than unmet") was aimed at the right target, and §38.3 supplies a cheap
way to test it that does **not** need `2g7.1`'s traced human plans: the
frontage bound is a pre-flight feasibility check computable from a plot and a
programme alone.

*(As first written this paragraph continued "two of the four corpus programmes
fail it by ~3×, which means a share of the residual those runs are being judged
on is not reachable at all". **That is withdrawn** — see §39.11. The ~3× came
from applying the bound to a fully built plot rather than to the area each
programme demands; harbor-house and maple-court are frontage-feasible with room
to spare. One programme is unsatisfiable, health-centre, and for a cruder
reason: it demands 131% of its plot. So the residual the other runs are judged
on is reachable, and the plateau is not explained by an unsatisfiable brief.)*

Tracks 2 and 3 (cheaper evaluation, exact sub-solvers) remain sound but are
orthogonal: making an evaluation 97× faster, or a labelling exact, does not
change which direction the objective points. Recommended ordering is now
`2v1` (price connectivity above the ×6 circulation→habitable value gap — the
dominant mechanism, and the one the §38.6 A/B isolated) → `ssz`/`hxi`/`gvb`
(restore a value gradient for interior space, re-tier), then `tdp` (ship the
pre-flight bound and re-baseline the corpus), and only then resume
`2g7.9`/`2g7.10`.

*(Both halves of that ordering's rationale have since been measured and did not
survive. `2v1` closed NULL — severing the spine is already punished, §38.2 is
retracted — and `tdp`'s infeasibility claim is retracted above. What the
ordering got right is that `ssz` comes before `2g7.7`; see §38.8 for what `ssz`
turned out to be.)*

**Acceptance test for the combined fix, stated up front so it cannot be
moved:** harbor-house must reach its known 15-fail floor in materially fewer
than 1.7 M evals, *and* `level 0 not connected` / `level 1 not connected` must
be absent from the result. Fail-count parity alone is not a pass — the whole
claim of §38 is that those two fails are bought, not missed.

In particular `2g7.7` (LLM repair operator at
stagnation) is worth deferring until after `ssz`: an LLM asked to propose a
valley-crossing multi-edit against an objective that pays ×85 to delete the
corridor it just inserted will have its work reverted by the next selection
step.

*(**Withdrawn — see §39.12.** Both halves failed. The 15 was measured against
harbor's pre-§39.4 *effective* programme of 32 instances; the same artefact
scores 89 against the real 37-instance one, so the target is not measurable.
And there is no longer a combined fix to accept: `2v1` closed NULL (§39.8).
§39.12 replaces it with the 4×3-seed cold-start baseline — harbor mean 39.3,
sd 5.5, minimum detectable difference 13.7 at n=3 — and demotes the
connectivity clause to a separately-tracked standing defect, since
`level N not connected` appears in 10 of the 12 baseline runs.)*

### 38.8 What `ssz` actually was: the objective demands daylight for rooms that do not need it (`homemaker-py-ssz`)

**First, why §38.6's A/B does not stand.** It measured the three modes against
the §38.2 *deletion test*, and it did so with a script that predates §39.4:
`experiments/ab_crinkliness_mode_ssz.py` selected "unpinned" leaves with
`(leaf.type or "")[:1].upper() in ("C", "O")`, the first-character prefix rule,
so every programme room whose code happens to begin with c or o — `cr1`, `of1`
— was swept in as circulation. Both the premise (§38.2, retracted) and the
selection were wrong. The script is kept, with the prefix rule fixed and a
warning in its docstring, but nothing is decided on its numbers.

**Second, and simpler: none of the three modes ever touched the leaves `ssz` is
about.** `quality_uncrinkliness` reaches `if not crink: return ...` *before* any
of the mode logic that matters, so for a zero-exposure leaf:

| mode | buried leaves | rescued to ≥ `FAIL_THRESHOLD` | windowless habitable rooms still failing |
|---|---|---|---|
| `urb` (stock) | 33 / 46 / 18 | 0% | 11/11, 13/13, 9/9 |
| `floor` | 33 / 46 / 18 | 0% | 11/11, 13/13, 9/9 |
| `compact_ok` *(as measured in §38.6)* | 33 / 46 / 18 | 0% | 11/11, 13/13, 9/9 |
| `exempt_circulation` | 33 / 46 / 18 | 21% / 24% / 33% | 11/11, 13/13, 9/9 |

*(harbor-house / maple-court / health-centre, 3 constructed seeds each, full
default stack.)*

`floor` returns 0.01 — one percent of a unit quality, multiplied into a product
and weighed against a whole leaf's cost, which is why it reads as inert.
`compact_ok` is worse than inert, it is **self-contradictory**: it announces
that being more compact than target is not a defect, and then returns the floor
for the most compact case of all, because `if not crink` fires before its clip
is ever reached. Only `exempt_circulation` moves anything, and it reaches at
most a third of the population. So §38.6's "none of them removes the incentive"
was reading a null that the modes' own implementation guaranteed.

**What the buried leaves actually are.** §39.7 gave every space a declared
`usage:`, which lets the question be asked properly for the first time — of the
leaves scoring a hard zero for want of daylight, how many are rooms a person
sits in?

| programme | buried | habitable (`living`/`kitchen`/`bedroom`) | store, toilet, plant, corridor, covered court |
|---|---|---|---|
| harbor-house | 33 | 11 (33%) | **22 (67%)** |
| maple-court | 46 | 13 (28%) | **33 (72%)** |
| health-centre | 18 | 9 (50%) | 9 (50%) |

**RETRACTED, see §38.11 — the real share is under a tenth.** As written this
claimed that roughly two thirds of the zero-value leaves are spaces that
architecturally do not want a window at all — a broom cupboard, a WC, a plant room, an
internal corridor, a covered courtyard. The objective scores them identically
with a windowless bedroom. That is the miscalibration, and it is not a gradient
problem to be patched with an epsilon; it is the wrong requirement applied to
the wrong rooms.

**The repair: `crinkliness_mode="usage_daylight"`.** Daylight is required of
the uses a person occupies (`programme.DAYLIGHT_USAGES` =
`living`/`kitchen`/`bedroom`) and of nothing else. For every other usage, and
for the generic `C`/`O`/`S` types which carry no programme entry, the factor is
clipped on the **compact side only** — being buried stops being a defect, while
over-exposure still costs, because a crinkly leaf costs envelope whatever it is
used for. A windowless bedroom remains exactly the hard zero it is under stock.

| programme | buried | rescued by `usage_daylight` | windowless habitable rooms still failing |
|---|---|---|---|
| harbor-house | 33 | 22 (67%) | 11/11 |
| maple-court | 46 | 33 (72%) | 13/13 |
| health-centre | 18 | 9 (50%) | 9/9 |

`compact_ok` was also repaired to score the buried limit as compact (1.0), the
behaviour its name always claimed; it now rescues 100% and is kept as the
**upper-bound control** — the mode that deletes the daylight requirement
outright, including for bedrooms. It is not a candidate.

**How this is scored, stated before the result.** `compact_ok`,
`exempt_circulation` and `usage_daylight` all return 1.0 where stock returns
below `FAIL_THRESHOLD`, so scoring an arm under its own objective deletes a fail
category for free and every arm "wins". Every arm below is therefore optimised
under its own objective and **re-scored under stock `urb`** — the comparable
yardstick, and the only one that answers *did optimising under this variant
steer the search to a better building?* The arm's own-objective count is
reported alongside solely to show the size of the definitional discount. A mode
passes on the stock column. `experiments/ab_ssz_search.py`.

**The result: NOT A PASS at this budget, and n=3 cannot decide it.** Budget
3000, 3 seeds, paired per-seed deltas against `urb` (negative = fewer fails):

| mode | harbor hard Δ | mean | maple hard Δ | mean |
|---|---|---|---|---|
| `floor` | [0, −1, −2] | −1.0 | [+5, −2, −1] | +0.7 |
| `compact_ok` | [0, −2, **−12**] | −4.7 | [0, +2, +1] | +1.0 |
| `exempt_circulation` | [+2, −3, −1] | −0.7 | [0, +2, +1] | +1.0 |
| `usage_daylight` | [0, −1, **−10**] | −3.7 | [0, +2, **−10**] | −2.7 |

The means flatter every mode. **The whole signal is seed 2**, in both
programmes, and seed 2 is the seed where stock itself does worst (harbor 22
hard against 16/22; maple 51 against 30/23). Two seeds in three are flat or
slightly worse. What this says is "on a bad run, the permissive modes do less
badly" — which is not nothing, but it is not the claim.

And on that seed the soft count rises by as much as the hard count falls:
harbor seed 2 −10 hard / +9 soft, maple seed 2 −10 hard / +15 soft. **Totals**:
harbor 62 → 61, maple 120 → **125**. Because every arm is scored under stock
`urb`, this is a real change of layout and not a relabelling — the search
genuinely traded hard failures for soft ones. Under the project's tiered
comparator, where `n_hard` is the primary key, that trade is progress. Under
`ssz`'s acceptance criterion — *lowers hard without inflating soft* — it is
not. The criterion is stricter than the comparator the search actually uses;
which of the two is the right yardstick is now the live question, and it is
`homemaker-py-gvb`'s question as much as this one.

`usage_daylight` stays **default off** pending a higher-powered run
(`urb` vs `usage_daylight` only, more seeds, both programmes). Nothing here
justifies shipping it as a default, and nothing here refutes it either: at
n=3 with one dominant seed, the honest reading is *undecided*.

**What is decided** is the diagnostic half, which does not depend on the search
A/B: the daylight requirement is applied to rooms that architecturally do not
want daylight, in two thirds of the buried population, and §38.6's contrary
null was an artefact of three modes that never touched those leaves.

### 38.9 Two corrections to §38.8, and the measurement that matters (`homemaker-py-ssz`)

**Correction 1 — the A/B yardstick above is wrong.** §38.8 scores every arm
under stock `urb`, reasoning that a permissive mode must not be allowed to win
by deleting a fail category. That is sound only if stock is ground truth, and
stock is exactly what this section shows is miscalibrated. Scoring the repair
under the objective it repairs penalises it for repairing: stock counts a
windowless broom cupboard as a failure, and the repair's whole purpose is to
stop counting it. *Does the fix score well on the broken yardstick* is not a
question worth answering, and the §38.8 A/B result should not be read as
evidence against `usage_daylight`.

**The measurement that does matter** asks whether the emitted failures are
*true*, and needs no search at all (`experiments/audit_crinkliness_truth.py`).
Of the `crinkliness` failures the stock objective reports, classified by the
leaf's declared usage:

| layout | crinkliness fails | on spaces that want no daylight |
|---|---|---|
| harbor-house, 3 constructed seeds | 67 | 41 (61%) |
| maple-court, 3 constructed seeds | 112 | 68 (61%) |
| health-centre, 3 constructed seeds | 20 | 10 (50%) |
| harbor-house `generated.dom` (evolved) | 5 | 2 (40%) |
| maple-court `generated.dom` (evolved) | 67 | 43 (64%) |
| **overall** | **271** | **164 (61%)** |

**RETRACTED — the true figure is 9%, see §38.11.** The table above classifies a
fail as a non-defect using `usage:`, exempting corridors, WCs, laundries and
reception; the owner exempts none of those. Only rooms not occupied from day to
day — a cupboard, a store, a plant room — do without daylight. The paragraph as
written said:

> **61% of the crinkliness failures the objective reports are not defects**, and
> it holds on evolved artefacts, not just seeds. Under
`value *= 0.5 ** len(failures)` every one of them halves the fitness of a design
that has done nothing wrong — a design is punished for putting the store in the
middle of the plan, which is what a competent architect does. That is a
correctness fault, and it is not contingent on any A/B.

**Correction 2 — `usage:` is the wrong key, and `usage_daylight` as written in
§38.8 mis-keys it.** §39.7 established `usage:` as an *access-requirement*
class. "Needs no special access" and "needs no window" are different questions,
and the corpus separates them plainly:

- `usage: none` is **Waiting Room**, **Reception**, **Reception Office**,
  **Entrance Foyer** — a waiting room is a space people sit in for long
  stretches and plainly wants daylight, yet `DAYLIGHT_USAGES` exempts it;
- `usage: bedroom` is where the GP consulting rooms, counselling rooms and
  staff offices live — all of which do want daylight, so that half is right,
  but it is right by luck of how the access axis happened to fall.

The audit is robust to the error (reclassifying `none` as wanting daylight
moves the headline 61% → 57%), so the finding stands; the *design* does not.
Daylight needs its own declared axis, per space, decided by the programme
author exactly as `usage:` was — not derived from a different question that
happens to correlate.

`usage_daylight` therefore stays default off and is **not** the shipping fix.
It is retained as the mechanism — the compact-side clip is the right shape for
the factor — pending a `daylight:` attribute to key it on.


### 38.10 The shipping fix: crinkliness is declared per space (`homemaker-py-ssz`)

Owner's ruling, and it is the design as well as the classification: **there is
no daylight attribute, because the daylight requirement is already defined in
the crinkliness.** The crinkliness gaussian's two sides are two real
requirements — the *compact* side is "too little exposed wall per unit floor",
which is exactly a daylight requirement, and the *exposed* side is "too much
envelope for the area", which is cost. §38.9's proposed `daylight:` axis was
redundant, and keying it off `usage:` was worse than redundant.

What was actually missing is that **crinkliness is the only leaf quality factor
with no per-space target**. `size`, `width` and `proportion` are all declared by
the space; crinkliness was one global number for every room in every building.
So a space now states its own:

```yaml
  st1:
    usage: utility
    crinkliness: none   # no window needed
```

Three states, resolved exactly as `size`/`width`/`proportion` resolve:

| in `patterns.config` | meaning |
|---|---|
| key absent | the global `uncrinkliness` target — today's behaviour |
| `crinkliness: none` (or a YAML null) | **no minimum-exposure requirement**: this space may be fully buried |
| `crinkliness: [target, sigma]` | that gaussian, this space's own target |

`none` **clips the factor on the compact side, it does not switch it off**.
Over-exposure is still penalised, because a crinkly leaf costs envelope whatever
it holds. A store may be buried; a store may not be a starfish.

**The mechanism is backward compatible.** An absent key resolves to the global
target, so shipping it changes no score anywhere. Behaviour changes only where a
config declares something — which makes the objective change visible, per
programme, in the config, rather than hidden in a default.

**Owner's classification.** Everything a person occupies wants a window — WCs
and bathrooms included, reception/waiting/foyer included, offices and consulting
rooms included. Only stores, plant, records and laundry (`usage: utility`) do
not. `experiments/migrate_crinkliness_key.py` declared `crinkliness: none` on 18
spaces across the corpus (harbor 5, harbor-l0 3, health-centre 4, maple 6;
programme-house has no utility spaces).

**Effect so far**, from `experiments/audit_crinkliness_truth.py`:

| | crinkliness fails | not defects |
|---|---|---|
| before | 271 | ~~136 (50%)~~ **24 (9%)** — see §38.11 |
| after the declarations | **247** | **0** |

The 28 that went are exactly the utility fails. What remains is two populations
the corpus cannot reach, because neither is a `spaces:` entry:

| remaining phantom | count | key |
|---|---|---|
| generic `C` — internal circulation | **85** | `uncrinkliness_circulation` |
| generic `O`/`S` — covered outside, sahn | 23 | falls through to `uncrinkliness` |

`uncrinkliness_circulation` already exists as its own config key and holds
`[5/6, 1.1/3]` — **byte-identical to the habitable target**, which is the
"estimated years ago and never changed" case in its purest form: a key created
precisely so corridors could differ, never given a different value. It is now
settable to `none` like any space (tested), but the default is deliberately
**left unchanged pending a ruling** — corridors were not among the groups ruled
on, and this is 63% of the remaining phantom fails, so it is not a call to make
by inference.

### 38.11 Owner's ruling on daylight, and the retraction of §38.8's headline

**Ruling: corridors need daylight. Only rooms that are not occupied from day to
day — a cupboard, a store, a plant room — do without it.**

That overturns the classification §38.8 and §38.9 were built on, and with it
their headline number. Those sections exempted, on my inference rather than any
ruling: internal circulation, covered courtyards, WCs and bathrooms, laundries,
and reception/waiting/foyer. **None of those are exempt.** A corridor is
occupied all day, every day; so is a waiting room; a laundry is a room people
spend time in; a sterilisation room is a workplace.

Re-measured against the ruling, with the classification read from the corpus
(a space is exempt exactly when its own `patterns.config` declares
`crinkliness: none`) rather than inferred:

| layout | crinkliness fails | not defects |
|---|---|---|
| harbor-house, 3 constructed seeds | 67 | 8 (12%) |
| maple-court, 3 constructed seeds | 112 | 9 (8%) |
| health-centre, 3 constructed seeds | 20 | 2 (10%) |
| harbor-house `generated.dom` (evolved) | 5 | 1 (20%) |
| maple-court `generated.dom` (evolved) | 67 | 4 (6%) |
| **overall** | **271** | **24 (9%)** |

**9%, not 61%.** The objective's daylight requirement was mildly miscalibrated,
not massively so, and I overstated it by a factor of about six by inventing a
classification instead of asking for one.

**`uncrinkliness_circulation` is therefore left at `[5/6, 1.1/3]`.** §38.10
called its equality with the habitable target "the purest case of a value never
tuned". It is not a bug: corridors want daylight on the same terms as rooms, so
the two targets agreeing is the correct answer, arrived at by default. The key
stays available for a programme that wants to differ.

**The corpus declarations are narrowed to match.** `usage: utility` was too
coarse a proxy — it swept in Laundry Rooms and a Sterilisation Room, all of
which are occupied. 14 spaces now declare `crinkliness: none`, and every one is
genuinely unoccupied:

| programme | declared `crinkliness: none` |
|---|---|
| harbor-house | Ground/First Floor Storage, Mechanical/Electrical Room, Utilities Closet |
| harbor-house-l0 | Ground Floor Storage, Mechanical/Electrical Room |
| health-centre | General Storage, Plant / Mechanical Room, Records Room |
| maple-court | Ground/First/Second Floor Storage, Mechanical/Electrical Room, Utilities Closet |

*(Records Room was queried and ruled on: it is a store, and stays exempt.)*

**What survives §38.8/§38.9 unchanged**, because none of it depended on the
classification:

- the §38.6 critique. `floor` returns 0.01 for a buried leaf, `compact_ok`
  contradicted itself, and `exempt_circulation` reached a third at most. Those
  are facts about the code, and they are why §38.6 measured a null;
- `usage_daylight` was mis-keyed. §38.9's reasoning for that was right even
  though its numbers were not — `usage:` is an access axis;
- the §38.8 A/B's yardstick was wrong: scoring the repair under the objective
  it repairs penalises it for repairing;
- the mechanism. Crinkliness was the only leaf quality factor with no per-space
  target, and §38.10's fix stands on the owner's design, not on my numbers.

**What this does to `ssz` as a whole.** The issue opened on "45–56% of interior
leaves are zero-exposure and score a hard zero, so the objective assigns no
value to any interior room". That measurement was right, but the reading was
wrong: under this ruling **a buried leaf usually IS a defect**, corridors and
WCs included, so scoring it zero is largely *correct*. What remains of the
complaint is narrower and is about search mechanics rather than truth — a hard
`0.0` cannot rank two bad layouts against each other, so the objective is
flat where it should be merely low. That is worth a separate issue; it is not
the calibration fault this section spent its length chasing.

### 38.12 The missing-space cascade was weighted by YAML verbosity (`homemaker-py-1i8`)

`graph.check_space_counts` emitted, per missing room instance, two base failures
plus **one placeholder for each optional key the author happened to type**:

```python
if req.has_size:        failures.append(f"missing {mid}: would need size check")
if req.has_width:       failures.append(...)
if req.has_proportion:  failures.append(...)
```

`has_size`/`has_width`/`has_proportion` are literally `"size" in c` from the
YAML. So a missing room cost 3, 4 or 5 fails depending on nothing but how
verbosely its space was written, and under `value *= 0.5 ** len(failures)` that
is a **4× difference in penalty between two single rooms**. The tiered
comparator inherits it directly, because `n_hard` is dominated by these
cascades — so the search's *primary key* was partly a measure of config style.

**Why it is unambiguously wrong, not merely arbitrary.** A present room is
checked on all three qualities regardless of what was declared:
`get_space_params` fills width and proportion from defaults, deriving width from
size when it is absent. programme-house's `t2` declares `size:` alone and still
receives a real width target of **1.633** which it can fail on. So the two paths
disagreed about the same room: present, it faces three checks; missing, it
emitted one placeholder. The cascade is supposed to stand in for the checks that
could not be run, and it was standing in for the wrong number of them.

**Fix: emit all three placeholders, always.** A fixed 5 fails per missing
instance, mirroring the present-room path.

| programme | before | after | max weight ratio, before → after |
|---|---|---|---|
| programme-house | 3..5 | 5 | 4× → 1× |
| harbor-house | 4..5 | 5 | 2× → 1× |
| maple-court | 4..5 | 5 | 2× → 1× |
| health-centre | 5..5 | 5 | 1× → 1× |

36 of the corpus's 67 codes were under-counted; 31 were already at 5.

**This makes fail counts LARGER, and that is the point.** It is a correctness
fix, not an improvement, and anyone reading the new numbers as a regression has
misread them:

| layout | before (total/hard) | after |
|---|---|---|
| harbor `evolved-3M-nols-3.dom` | 82 / 37 | **84 / 39** |
| harbor `generated.dom` | 155 / 128 | **174 / 147** |
| harbor `evolved-3M.dom` | 131 / 87 | **144 / 100** |
| maple `generated.dom` | 126 / 17 | 126 / 17 (no missing instances) |

**Note the alternative that was NOT taken.** `1i8` also offered "emit exactly one
fail per missing instance and let the placeholders be informational". That would
have fixed the verbosity dependence too, but it silently rescales how much a
missing room matters — from 1/32 to 1/2, the same weight as a single crinkliness
fail. Whether a missing required room *should* cost 1/32 is a real question, and
a separate one; conflating it with this fix would have changed the objective's
priorities under cover of a bug fix. The magnitude is left exactly where it was.

**Baselines.** Every historical corpus fail count is invalidated again, on top of
§39.4 and §38.10/§38.11. This is why the cold-start re-baseline is worth running
*after* the objective work rather than before it.

### 38.13 health-centre's plot enlarged for a courtyard typology (`homemaker-py-7b7`)

§39.11 found health-centre demanding **240 m² of floor on a 183 m² plot — 131%**,
single storey, with nowhere for the overflow to go. Every room came out at
**0.60× its declared target**, 100% of them undersized, uniformly, and no amount
of searching could fix it.

**Owner's ruling: enlarge the plot, sized on the assumption that the building
has a courtyard.** The plot is a quadrilateral in this engine, so the courtyard
is interior space the search carves out (`interior_outside`), not a hole in the
site. What that means for sizing is that the plot must hold three things, only
one of which the programme declares:

| | m² | in `patterns.config`? |
|---|---|---|
| rooms | 240 | yes |
| circulation | ~65 (≈27%) | **no — the search creates `C` leaves** |
| courtyard | ~36 (6×6, usable) | no |
| | **~341 + slack** | |

The plot is scaled about its polygon centroid by **k = 1.4606**, chosen so the
*inset* area (what the leaves actually get, after `wall_outer`) lands on
**400 m²**. Scaling about the centroid preserves the site's irregular shape and
its one `private` edge — this is the same site, larger, not a new one.

| | before | after |
|---|---|---|
| plot (inset) | 183.2 m² | **400.0 m²** |
| rooms / plot | **131%** | **60%** |
| daylit perimeter | 41.5 m | 61.3 m (49.4 needed) |
| median room area / (target × share) | **0.60×** | **1.00×** |

60% is harbor-house's ratio exactly, and harbor works. The room-sizing figure is
the one that matters: it was the unmistakable geometric signature of the
infeasibility, and it is now level with harbor and maple's 1.01×.

**The courtyard is required by the geometry, not merely permitted.** A room can
be at most `1.6202·h` = 4.86 m deep before it fails crinkliness, so a ~20×20 m
plot with a daylit ring around its edge leaves a **10.3 × 10.3 m, 106 m² core
that cannot reach an external wall at all**. That core has to be courtyard or
lightwell. Enlarging the plot did not remove the pressure that produces a
courtyard — it made room for one.

`evolve._preflight` is now silent on health-centre; both its checks pass.

### 38.14 Toilet-to-sleeping adjacency declared where the brief supports it (`homemaker-py-3qj`)

A toilet next to a sleeping room is a positive even with no door between them
(Stewart Brand, *How Buildings Learn*): the adjacency is what makes a later
knock-through possible. The engine already scores this — `check_adjacency` runs
against the UNFILTERED `graph_base_pre`, so a declared adjacency is satisfied by
a neighbouring room regardless of the edges `has_circulation` later strips for
routing. But it is only scored where a programme **declares** it, and only
programme-house did (`t1 -> [b1]`, the ensuite).

**Declared:**

| programme | added | why |
|---|---|---|
| harbor-house | `t` → `n` | Bathrooms serve the Neighborhoods (communal sleeping). Both codes unpinned, 6 t / 5 n. |
| maple-court | `tt` → `r` | Upper Bathrooms among Individual Rooms — both pinned to level 2, and already 62% adjacent at seed time. |

**Not declared, and this is the substantive part.** Two candidates that look
obvious from the room lists are wrong, and checking before declaring is what
caught them:

- **maple `t` → `n` is IMPOSSIBLE.** Adjacency is evaluated per level
  (`graph_base[li]`), and maple pins `t` to level 0, `n` to level 1. Declaring it
  would have added **six permanently unsatisfiable fails**. The measured 0%
  seed-time adjacency was not search difficulty, it was a hard impossibility.
  maple's ground floor holds six bathrooms and exactly one sleeping room (Clinic
  Room ×1) — a ground-floor WC in a communal building is public, so the Brand
  argument does not apply to it anyway.
- **health-centre has no dedicated WC to declare.** The owner's ruling on
  treatment rooms was that one "may give access to a toilet, but this would be a
  *dedicated* toilet". `t9` is a Public WC (×2) and `t10` a Staff WC; making
  either dedicated-adjacent to `tr1` contradicts that. Earning the credit here
  needs a dedicated WC **added to the brief**, which is programme authoring
  beyond this issue.

*(Also worth recording: maple's level 1 carries four Neighborhoods and no toilet
at all. That may be a genuine gap in the brief.)*

**Both declarations are reachable**, so the search gets a gradient rather than a
permanent penalty: best of 8 constructed seeds satisfies 2/3 for harbor `t → n`
and 2/2 for maple `tt → r`. Cost on `evolved-3M-nols-3.dom`: 84 → 89 fails, all
five being the new requirement.

**Cost: the exact assigner got ~8× slower; the default path is free.**
`constructive_topology` seeding, 3-seed average:

| | greedy (default) | cpsat (opt-in) |
|---|---|---|
| harbor before | 0.06 s | 0.28 s |
| harbor after | **0.06 s** | **2.11 s** (7.5×) |
| maple after | 0.03 s | 1.37 s (2.9×) |

`assign_solver` defaults to `greedy`, so ordinary runs pay nothing. One more
adjacency constraint makes the CP-SAT labelling model markedly harder, which
means §39.5's cpsat-versus-greedy verdict was measured on a cheaper problem than
the corpus now poses and is worth re-checking.

**Two tests were over-fitted to the old seeds** and broke here. Both were
repaired to assert their intent rather than a sampled artefact, not relaxed to
pass:

- `test_reassign_fires_and_preserves_room_multiset` pinned constructive seed 0.
  The better-seeded design left nothing for the repair operator to improve, which
  is a legitimate noop — 5 of 6 other seeds still fire. It now sweeps six seeds.
- `test_repair_circulation_reconnects_every_storey` asserted `on_ok == on_tot`,
  hardening a sampled 100% into a guarantee. `repair_circulation_settled` is a
  heuristic over already-settled walls and nothing makes it complete; measured
  25% → 92%, stable across 6 and 12 seeds. It now asserts the real claim (repair
  strictly helps) plus a ≥85% regression bar.

### 38.15 `constructive_topology` was ordered by memory address (`homemaker-py-fdp`)

`assign_solver="cpsat"` gave a different leaf-type signature on every run from
an identical seed, **in the same process**. Narrowed to one line:

```python
assignable = scope if scope is not None else set(leaves)
...
noncirc = [L for L in assignable if L not in circ]      # <-- id() order
room_slots = [L for L in noncirc if L not in o_set]
```

`assignable` is a `set` of `dom.Node`, and `Node` hashes by `id()` — a memory
address. Iterating it ordered `noncirc`, and therefore `room_slots`, by where
the objects happened to land in memory. That changes between calls within one
process as allocation patterns shift, with no seed involved at all.

**Why only cpsat showed it.** The greedy path re-sorts every slot list with
`-idx[L]` as a unique tiebreak, so it is immune to whatever order arrives.
CP-SAT consumes `room_slots` order as its model's variable order, and since the
labelling problem has many equally-optimal solutions, a different variable order
returns a different one. Greedy was not more correct — it was masking a defect
that had been there all along.

**Method note.** Guessing at candidate `set`s would have been slow and
unreliable — there are several, and most are harmless because they feed a `max()`
with a unique tiebreak. What settled it was instrumenting `solve_room_labels`
with an id-free fingerprint of its inputs and outputs, then isolating the
*first* call (later calls legitimately depend on earlier ones through leaf
types). Five runs gave five distinct inputs to the first call, which located the
fault upstream of the solver in one step.

**Fix:** iterate the tree-ordered list, use the set only for membership.

```python
noncirc = [L for L in leaves if L in assignable and L not in circ]
```

**Verified** on programme-house, harbor-house and maple-court: one distinct
signature over 5 runs on both solvers, and — a stronger result than the issue
asked for — one distinct signature across 4 processes started with different
`PYTHONHASHSEED`, so the string-keyed `context_types` sets are not a second
source.

`test_constructive_topology_is_bit_reproducible` guards both solvers. Repetition
*in one process* is what catches this class: allocation order changes without
any seed changing.

**Why this mattered beyond cpsat.** Every A/B in this document rests on being
able to re-run a configuration and get the same answer. A/Bs on the cpsat path
were comparing arms that differed partly by memory layout — §39.5's
cpsat-versus-greedy verdict among them, which is already down for re-measurement
under `homemaker-py-vjd`. This is the same `id()`-keying hazard as the
documented `geometry._cache` issue and a plausible contributor to
`homemaker-py-b8g`.

### 38.16 The staged harness re-scored under a different objective than it searched (`homemaker-py-4ok`)

`run_staged_search.py` reported `MISMATCH` on its **baseline** arm — the
`LEAFSHARE=0/MULTIUSE=0` control that every A/B in this document compares
against. Two facts combined:

- `driver.search_staged` had **no `collapse_insearch` parameter at all**, so
  every inner `search()` call inherited `search()`'s `collapse_insearch=True`
  default, unconditionally;
- no example `patterns.config` sets the key, so the final `_native_score`
  re-score got `False` from a bare `load_config`.

Search optimised one objective; the rescore graded a different one. The
`homemaker-py-7ua` fix pinned the key inside a `fitness.load_config` monkeypatch
— but that patch was installed only `if leaf_share or multi_use`, so it fixed
every arm *except* the control.

**Fix, in the right place: give `search_staged` the parameter it was missing**
(default `True`, byte-identical to the inherited default) and thread it into all
three internal `search()` calls. The harness then chooses the arm explicitly
(`COLLAPSE`, default 1), passes it to the search, and passes **the same value**
to `_native_score`, which now overrides the key rather than hoping the config
carries it. The rescore mirrors the search by construction instead of by
coincidence of which monkeypatch happened to be installed.

Verified on programme-house, budget 150, all four arms:

| arm | before | after |
|---|---|---|
| baseline (no env) | **MISMATCH** 1.56663e-08 vs 1.51708e-08 | **OK** |
| `COLLAPSE=0` | n/a (no knob existed) | **OK**, 1.66216e-08 |
| `LEAFSHARE=1` | OK | **OK** |
| `MULTIUSE=1` | OK | **OK** |

`COLLAPSE=0` scoring differently from `COLLAPSE=1` (1.66216e-08 vs 1.56663e-08)
confirms the knob does real work rather than being a no-op, and the search
result itself is unchanged on the default arm, so no prior staged number moves.

**One sibling had the same bug.** Auditing the other three `search_staged`
callers: `run_and_capture_91f.py` already pins `collapse_insearch: True` in its
overrides and is correct; `run_island_ab.py` never re-scores, so it cannot
mismatch; **`probe_harbor_floor.py` did not pin it** and so re-scored under a
different objective than it searched — and that is the harness which produced
"every §13.x floor number". Now pinned.

**Why a P3 was worth doing.** The mitigating factor recorded on the issue was
that the fail *count* matched and only the continuous score moved, which the
`run_*_ab.sh` greps do not read. That is true and it is also exactly what makes
this dangerous: a harness that reports MISMATCH on its own control, in a way the
metric-of-record cannot see, trains everyone to ignore the warning.

### 38.17 `n_workers` is an algorithm parameter, not noise (`homemaker-py-b8g`)

§14 recorded "harbor seed 2 scored 71 then 73 on byte-identical re-runs —
parallel/BLAS non-determinism", and `b8g` carried that forward as an
uninvestigated noise source widening the error bars on every A/B run at
`n_workers>1`. **The premise does not survive measurement.** Nothing is
non-deterministic:

| test | result |
|---|---|
| score a frozen `.dom`, 20 repeats in one process | bit-identical |
| same `.dom`, 8 processes, different `PYTHONHASHSEED` | bit-identical |
| full search, harbor, seeds 0/1/2/3, `n_workers` 1..4, repeated across processes | bit-identical **per worker count** |
| the same, with `OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1` | **identical to unpinned** |

That last row matters most. `b8g`'s proposed remedy was "likely a one-line env
pin in the worker pool initializer". Pinning the BLAS thread count changes
nothing at all — bit-for-bit — so shipping that mitigation would have looked
like a fix and done nothing, while retiring the issue. BLAS is not implicated.

**What is real, and it is not noise.** The trajectory is a deterministic
*function of* `n_workers`. harbor seed 3, budget 1500:

| `n_workers` | best |
|---|---|
| 1 | 64 fails, 1.6264880162149419e-22 |
| 2 | 64 fails, same bits |
| 3 | 64 fails, same bits |
| 4 | **65 fails, 7.685882216045091e-23** |

Each is perfectly stable on its own across processes. The mechanism is at
`driver.py`'s batch loop:

```python
batch_n = min(n_workers, max(1, (budget - n_evals + child_budget - 1) // child_budget))
```

`batch_n` children are bred from **one population snapshot** before any of them
is admitted, and the shared `rng` is consumed in a different pattern. At
`n_workers=1` each child sees the population its predecessor updated. So a
4-worker run is a partly-generational algorithm and a 1-worker run is
steady-state — the same seed, a different search. (Seeds 0/1/2 happened to agree
across worker counts and seed 3 did not; divergence is occasional, not constant,
which is exactly how it reads as "noise" when sampled.)

**Consequence for the A/B record.** `n_workers` must be treated as part of an
arm's configuration. Comparing a result measured at 4 workers against one
measured at 1 compares two algorithms. The `run_*_ab.sh` harnesses already pin
`WORKERS=4` within a run, so arms inside one harness are sound; the exposure is
comparing across harnesses, or against a historical figure whose worker count
was not recorded.

**§14's original observation was most likely `homemaker-py-xcy`** — the
`as_completed` admission-ordering bug, which was genuinely non-deterministic and
has since been fixed. There is no residual noise behind it.

Guarded by `test_search_is_reproducible_at_a_fixed_worker_count` (parametrised
over 2/3/4 workers, asserting each is internally stable and deliberately not
asserting they agree with each other) and
`test_scoring_a_frozen_design_is_deterministic`.

### 38.18 The 1ph verdict re-verified: the iio bug could never have touched it (`homemaker-py-d86`)

`d86` asked for the rigorous version of §35's spot-check: take the codebase at the
`1ph` commit, backport the `iio` stale-leaf-share fix, and re-run the actual
historical seed sets to see whether the published verdict would have changed.

**One constraint had to be worked around.** This repository's history begins
**2026-07-30**, six days *after* the 1ph commit (2026-07-24) — the historical
checkout the issue asks for does not exist here. The closest reachable stand-in
is `391f510` (2026-07-30), which is a genuine ancestor of the iio fix
(`929be5b`, 2026-08-01) and therefore pre-iio, and which carries that era's
`examples/` and objective. Everything below is measured there, not at the true
1ph commit, and that is a real limitation of the reproduction.

**Protocol as published:** programme-house `init.dom`, budget 3000, 4 workers,
seeds 1–20, ON vs OFF, both arms finished with `--collapse`. Run twice over the
same worktree — once as-is, once with the 22-line `iio` `fitness.py` hunk applied.

| codebase | OFF | ON | W/L/T | mean diff | t (df=19) |
|---|---|---|---|---|---|
| published 1ph (2026-07-24) | 7.95 | 7.10 | 11/6/3 | +0.85 | 2.38 |
| pre-iio `391f510` | **8.05** | **7.10** | **11/6/3** | **+0.95** | **2.59** |
| the same, + iio fix backported | 8.05 | 7.10 | 11/6/3 | +0.95 | 2.59 |

Two results:

1. **The published verdict reproduces.** ON beats OFF, significant at N=20, with
   a win/loss/tie split identical to the published 11/6/3.
2. **The iio fix changes nothing — 0 of 40 (seed, arm) cells differ.** Not a
   coincidence of means: the per-seed fail counts are equal cell by cell.

**And it could not have been otherwise.** The iio bug needs a leaf carrying a
*stale* `share`/`share_type` — leftover multiplicity from a code the leaf has
since been retyped away from. Leaf-sharing only ever stamps a share when a code
has `count > 1`, and **programme-house declares `count: 1` for all six of its
codes**. Measured directly over 8 constructed seeds at that commit:

| programme | leaves | `share > 1` | `share_type` set |
|---|---|---|---|
| programme-house | 56 | **0** | **0** |
| harbor-house | 128 | 24 | 24 |

`_collapse_value` reads `leaf.share_type`; on programme-house it is never set,
so the bug is **structurally unreachable on the 1ph protocol**. That is why §35
saw 2 of 3 harbor seeds diverge by 5–8 fails while programme-house at N=20 moves
not one cell — harbor has codes at counts 10, 6 and 5.

§20's retroactive caveat is therefore **discharged for the 1ph section** and
stays live for harbor-house/qpk, where shares exist and the divergence was
measured. Worth noting for future archaeology: "was this measurement affected by
bug X" is often answerable from the programme's structure without re-running
anything.

### 38.19 `collapse_insearch=True` re-validated under the current objective (`homemaker-py-ioe`)

§38.18 confirmed the `1ph` default-flip was sound *for its own era*. But that
measurement predates three changes to the objective it was measured against —
§39.4's generic-namespace fix, §38.10/§38.11's per-space crinkliness, and
§38.12's missing-space cascade — and `collapse_insearch` runs `collapse_global`
inside every eval, valued against exactly the quality factors those changes
touched. A default carried on a superseded measurement is an assumption, not a
result, so the `1ph` protocol was re-run as published on the current codebase:
programme-house, budget 3000, 4 workers, ON vs OFF, both arms finished with
`--collapse` (`experiments/rerun_1ph_protocol.sh`).

| | N | OFF | ON | W/L/T | mean diff | t | p |
|---|---|---|---|---|---|---|---|
| published `1ph` (2026-07-24) | 20 | 7.95 | 7.10 | 11/6/3 | +0.85 | 2.38 | 0.028 |
| historical re-run (§38.18) | 20 | 8.05 | 7.10 | 11/6/3 | +0.95 | 2.59 | — |
| **current objective** | 20 | 7.85 | 7.15 | 10/7/3 | +0.70 | 1.82 | **0.085** |
| current objective | 40 | 7.60 | 7.03 | 21/14/5 | +0.57 | 2.01 | **0.052** |
| **current objective** | **60** | **7.58** | **7.02** | **29/19/12** | **+0.57** | **2.45** | **0.017** |

*(**Corrected.** The N=20 and N=40 p-values first published here were 0.069 and
0.045, from a normal approximation. The exact paired t-test gives **0.085** and
**0.052** — so **N=40 did not reach significance either**; it took N=60. The
approximation was anti-conservative, i.e. it made results look *more* significant
than they are, which is the same direction of error this section is about.
`experiments/ab_report.py` computes it exactly now, per `homemaker-py-tco`.)*

**Verdict: the default stands.** At N=60, mean diff **+0.567 fails/seed**,
paired t = 2.454 (df=59), **p = 0.0171** exact, 95% CI **[+0.105, +1.029]**
excluding zero. A Wilcoxon signed-rank cross-check agrees (p = 0.0138), which
matters here because fail counts are small integers and normality is not
obvious.

**Two things worth recording beyond the verdict.**

First, **the effect is about a third smaller than published** — +0.57 against
+0.85. Some of that is regression from a slightly lucky N=20 draw, and some is
plausibly real erosion: several of the fails `collapse_global` used to clear
have been redefined out of existence or made harder by the objective work.

Second, and more usefully: **the published protocol's N=20 can no longer detect
its own effect.** At exactly the published sample size the current answer is
p = 0.085 — a null by the conventional threshold. Had this been re-run at N=20
and stopped there, the honest report would have been "the 1ph verdict no longer
reproduces", and the default would have looked unjustified. It took N=60 to
resolve. That is precisely the "8sh/1ph/qi6/lj3 pattern" this document already
warns about, now biting the flagship result itself: **any future re-validation
of this default needs N ≥ 60 (not the "≥ 40" first written here — N=40 gives
p = 0.052), and N=20 should not be trusted to settle it either
way.**

### 38.20 CP-SAT seeding re-measured deterministically: it loses (`homemaker-py-vjd`)

§39.5 concluded, over 6 seeds, that the exact CP-SAT seeder beats greedy
(harbor 102 → 92, maple 156 → 154). Two things have happened since that make it
worth re-checking, and a third turned up on the way.

**First, a live bug in the cap.** `solve_room_labels` sets both a deterministic
work-unit budget (`max_deterministic_time = 4.0`) and a wall-clock backstop
(`max_time_in_seconds`), with the comment that the wall clock "stays as a
pathological-case backstop only". At its 2.0 s value it had stopped being a
backstop and become **the binding constraint**: on harbor, 2 of 24 solves
returned `FEASIBLE` rather than `OPTIMAL`, wall time hit exactly 2010 ms, and
the deterministic budget was never reached (max 2.483 of 4.0). Those two
labellings were therefore both **suboptimal and load-dependent** — the wall
clock is exactly the load-dependent cap §39.5 added the deterministic one to
escape. Cause: §38.14's added `t → n` adjacency makes the model markedly harder,
and the 2 s value dated from when solves finished in ~124 ms. Raised to 30 s so
the deterministic budget governs; all 24/24 harbor and 36/36 maple solves are now
`OPTIMAL`, with the deterministic budget still in headroom (max 3.569 of 4.0).

**Second, the verdict itself.** Re-measured deterministically — `fdp`'s
`id()`-ordering fix means the arms no longer differ by memory layout — over 12
constructed seeds, scored by the canonical evaluator:

| programme | solver | hard | soft | total | s/seed |
|---|---|---|---|---|---|
| harbor-house | greedy | 722 | 601 | **1323** | 0.079 |
| harbor-house | cpsat | 908 | 640 | 1548 | 1.623 |
| maple-court | greedy | 777 | 987 | **1764** | 0.063 |
| maple-court | cpsat | 1213 | 1043 | 2256 | 1.327 |

**CP-SAT loses on both**, by +225 and +492 fails, at ~21× the seeding time. The
gap is concentrated in *hard* fails (+186, +436).

**Third, and it separates two things that looked like one.** §38.14's adjacency
is responsible for the *time* blow-up but almost none of the *quality* gap.
Removing `t → n` from harbor and re-measuring:

| harbor | cpsat − greedy (total) | cpsat s/seed |
|---|---|---|
| with `t → n` | +225 | 1.623 |
| without | **+205** | **0.193** (8.4× faster) |

So the adjacency costs 8.4× the time and about 9% of the quality deficit. The
regression is otherwise pre-existing.

**How this squares with §39.5.** That section's own text records CP-SAT
returning "194 / 180 / 171 / 182 over four identical 10-seed aggregates" before
the determinism work. A 10-fail harbor margin (102 vs 92) sits well inside a
noise band that wide. The measurement was taken with `fdp`'s `id()`-ordered
`room_slots` still live, so **the "cpsat wins" margin was never outside its own
documented noise**. It is restated here rather than contradicted: the honest
position is that the seeder-level claim was never established, and now that the
solver is deterministic it measures the other way.

*(The absolute totals here are ~6× §39.5's because the objective has since
changed — §39.4, §38.10–§38.12 — so these numbers are not directly comparable to
that table. The greedy-vs-cpsat comparison within this measurement is
like-for-like and is what the verdict rests on.)*

**Cost of the cap fix, and what was recovered** (`homemaker-py-7t1`). The two
harbor solves that used to be cut off at 2 s now run to optimality, which took
the suite from ~4.5 min to ~10 min — the `assign_cpsat` tests dominate it. Two
things recovered most of that, and one deliberately was not:

- `test_assign_cpsat_matches_or_beats_greedy_secondary_adjacency` ran the cpsat
  arm **three times and averaged**, for a reason its own comment gives: the
  cpsat path "is not yet bit-reproducible (`homemaker-py-fdp`)", so one 10-seed
  aggregate could straddle greedy's deterministic value and the test was flaky
  by construction. **`fdp` is fixed** (§38.15), so one pass now says exactly what
  three did. The repeat was work spent papering over a bug that no longer exists.
- `constructive_topology` and `_assign_adjacency_aware` now forward an optional
  `cpsat_limits=(time_limit_s, deterministic_limit)`. It is **not a tuning
  knob** — production keeps the defaults so solves stay optimal and
  deterministic. It exists so a test whose claim does not depend on optimality
  can buy its runtime back. `test_construction_assign_cpsat_yields_valid_seed`
  asserts invariants (every required space present, canonical genome) and uses
  it: 91 s → 53 s. The trap there is that too small a budget makes
  `solve_room_labels` return `None`, `_assign_adjacency_aware` falls back to
  **greedy**, and the test passes while exercising nothing — so it counts
  fallbacks and fails if any occur.
- The two *quality* comparisons keep the full budget. Their claims are about
  the optimum, and cheapening them would weaken what they assert.

Net: ~10 min → ~6.8 min. Still above the pre-§38.20 4.5 min, and that residue is
the honest price of solves that now reach optimality deterministically.

**No default changes.** `assign_solver` was already default `greedy` for the
independent reason §37.7 gives, and this reinforces it. What changes is that the
"cpsat wins the seeder A/B" claim should no longer be cited as a reason to
pursue it.

### 38.21 Harbor A/Bs at n=3 could never have resolved their own margins (`homemaker-py-0wr`)

`0wr` asked which harbor results decided by a narrow margin should be
re-checked after §39.4. Measuring harbor's actual variance answers a broader
question than the issue posed.

**Harbor's paired seed-to-seed spread is σ ≈ 6.2 fails** (24 paired ON/OFF runs,
budget 2500). At n=3 that gives a **minimum detectable difference of ~15.4
fails**. Every recorded harbor margin is below it:

| section | harbor margin | resolvable at n=3? |
|---|---|---|
| §13.9 `share_edge_cap` | 34.7 → 31.0 = 3.7 | no |
| §20 `qpk` collapse | 80.3 → 72.0 = 8.3 | no |
| §23 `f1d` ruin-recreate | mixed (1W/1L/1T) | no |
| §37.1 tiering | hard 11.67 → 5.33 = 6.3 | no |
| §17 `94g` | byte-identical | n/a — no margin claimed |

So the finding is not "some harbor results were narrow". It is that **no harbor
A/B run at three seeds could resolve the margin it reported**, whatever §39.4
did to the programme. Of the 220 possible 3-seed subsets of the 24 measured
below, **56 (25%) show a clean 3/3 sweep for ON** — a 3/3 result on this
programme is close to a coin-flip artefact, not evidence.

**§20's harbor arm, re-measured.** Same protocol (budget 2500, ON vs OFF, both
finished with `--collapse`), taken to n=24:

| N | OFF | ON | W/L/T | mean diff | p | 95% CI |
|---|---|---|---|---|---|---|
| 3 | 92.00 | 89.33 | 2/1/0 | +2.67 | 0.560 | [−13.87, +19.21] |
| 12 | 92.75 | 89.25 | 8/3/1 | +3.50 | 0.076 | [−0.43, +7.43] |
| **24** | 88.92 | 87.71 | 13/10/1 | **+1.21** | **0.502** | **[−2.46, +4.88]** |

**Null.** 13W/10L/1T is a coin flip, and the CI comfortably spans zero. The
published "harbor-house: ON wins 3/3, mean 80.3 → 72.0" was a lucky draw — note
even seeds 1–3 measured here give 2W/1L, not a sweep. (Absolute levels differ
from the published ones because the objective has changed; the ON/OFF comparison
within this measurement is like-for-like.)

**Consequence for the `collapse_insearch` default.** §20 concluded "the qpk
verdict holds at **both** example scales tested". That claim is **withdrawn** —
harbor is null at adequate N. What survives is §38.19's programme-house result
(N=60, +0.57 fails/seed, p = 0.017, Wilcoxon 0.014). The default stands on one
programme, not two. It is not refuted on harbor either — the direction is
positive, just indistinguishable from zero — but harbor should no longer be
cited as corroboration.

**The standing lesson.** Combined with §38.19, where programme-house needed N=60
to resolve an effect its own protocol claimed at N=20: *harbor at n=3 resolves
nothing finer than ~15 fails, and programme-house at N=20 resolves nothing
finer than ~1 fail.* Any future A/B on these programmes should state its
detectable difference before running, not after.

### 38.22 A/Bs now report what their sample could resolve (`homemaker-py-tco`)

Three times in this log a verdict turned out to rest on a sample that could not
have produced it: §38.19 (programme-house claimed at N=20, resolves at N=60),
§38.21 (harbor at n=3 resolves nothing finer than ~15 fails, yet every recorded
margin is smaller), and §39.5/§38.20 (a 10-fail cpsat margin inside a ±23-fail
noise band). Each was found years later. `experiments/ab_report.py` makes it
visible at the point the verdict is made:

```
minimum detectable difference (MDD) = t_crit(0.975, N-1) * sd / sqrt(N)
```

A margin below the MDD is not a *weak* result, it is an **absent** one — the
experiment could not have distinguished it from zero however it came out. The
report flags that, refuses to endorse a winner, and states the N that would be
needed. Validated against both datasets measured this session:

| dataset | verdict | MDD | reported |
|---|---|---|---|
| programme-house N=60 | +0.567, p=0.017 | 0.462 | margin exceeds MDD — verdict supported |
| programme-house N=20 | +0.700, p=0.085 | 0.805 | **UNDERPOWERED**, N ≈ 26 needed |
| harbor N=24 | +1.208, p=0.502 | 3.669 | **UNDERPOWERED**, N ≈ **202** needed |

That last row is worth reading twice: harbor's `collapse_insearch` margin would
need ~200 seeds to resolve. At the 3 seeds it was published with, and at any N
this project would realistically run, harbor cannot answer that question at all.

**Degenerate cases are handled explicitly**, because the first version got one
wrong: with all-ties (`sd = 0`) the MDD collapses to zero and the naive test
`abs(mean) < mdd` reported "margin exceeds the MDD — verdict supported" for a
margin of 0.000, with `t = nan`. A reporter that endorses a zero margin is worse
than none. It now says "NO DIFFERENCE: identical on every seed — nothing to
test", and distinguishes that from a constant non-zero difference, where a
t-test is undefined but the result is real.

Wired into `experiments/ab_ssz_search.py`, which prints a power report per arm
before its summary table. `rerun_1ph_protocol.sh` writes a TSV the CLI reads
directly: `python experiments/ab_report.py <results.tsv> off on`.

### 38.23 The shape-curve DP now models leaf-sharing, so it can fire on real runs (`homemaker-py-tym`)

`shapecurve.leaf_constraints` derived each leaf's feasible area from its own
type's base `(target, sigma)`. `Fitness.quality_size` does not: for a leaf
holding `k` same-code rooms it centres the gaussian on `k × target` with
`sigma × k`, and for a co-typed leaf it adds the two codes' targets. The DP
modelled neither, so `shapecurve.eligible` excluded any run with
`leaf_sharing`/`max_share`/`multi_use` — and **`leaf_sharing` defaults `True` in
`driver.search`**, so the guard excluded essentially every real run. The DP was
correct and unreachable.

**Why the guard could not simply be dropped.** On six harbor-house constructed
seeds, **24 of 24 shared leaves (100%)** have a real area outside the unscaled
single-room bounds. Relaxing `eligible` without modelling `k` would have made
the DP call every one of those topologies infeasible — false negatives that
prune feasible topologies and send the NM warm-start to a bad point. The guard
was load-bearing.

**Fix: mirror `quality_size`, by asking the same `Fitness`.** `leaf_constraints`
now computes `k = graph.leaf_share(leaf, fit._max_share)` when `fit._leaf_sharing`
is set, applies `target·k, sigma·k`, and otherwise consults `fit._leaf_co_type`
for the additive co_type case — the same object, the same flags, the same
branch order as the evaluator. It deliberately does **not** re-derive the rule:
§39.5's `cpsat._matches` bug was exactly a solver optimising a relation the
scorer had since moved, and this is the same hazard class.

Verified as an exact inversion, not an approximation: for every shared leaf in a
real seed, `quality_size` evaluated at the DP's `amin` and `amax` returns
`FAIL_THRESHOLD` to 1e-9.

| leaf | type | k | DP amin | DP amax | q(amin) | q(amax) |
|---|---|---|---|---|---|---|
| `llrlr` | m | 3 | 17.12 | 42.88 | 0.100000 | 0.100000 |
| `lrlr` | n | 3 | 128.50 | 231.50 | 0.100000 | 0.100000 |
| `rlrrl` | of | 2 | 14.27 | 35.73 | 0.100000 | 0.100000 |
| `rrlr` | t | 3 | 8.34 | 27.66 | 0.100000 | 0.100000 |

**`superpose` stays excluded, and for a different reason than the rest.** The
others rescale a leaf's target; superposition changes *which type the leaf is
scored as*, and the collapse happens inside evaluation, after the DP has read
`leaf.type`. Bounding the wrong code is not something a rescale can fix — that
needs the collapse modelled.

`shapecurve_warmstart`/`shapecurve_prune` remain default **off**, so this
changes no current run. What it changes is that they are now *applicable*:
`homemaker-py-v4s`'s A/B, which its own issue said to defer until this landed,
is unblocked.

### 38.24 The shape-curve warm-start cannot pay off as wired (`homemaker-py-v4s`)

With `tym` landed the DP finally *runs* on real (leaf-sharing) searches, so
`v4s` asked for the search-level A/B: `shapecurve_warmstart`/`_prune` off vs on,
budget 2000, seeds 0–4. **No A/B was run, because two structural facts make the
payoff zero before any seed is drawn**, and measuring a no-op would have
produced a null that reads like a measurement rather than a fact.

**1. Reach: the warm-start only ever touches the bootstrap population.**
`driver._evaluate` gates it on `x0 is None`, and every child gets
`x0 = innerloop.warm_x0(child_root, ratios)` from its parent (`driver.py:764`).
So `x0 is None` holds only for seed-population individuals. Instrumented over a
4000-eval run: **8 DP solves**, exactly `pop_size`. At the 500k budget the
corpus baseline uses that is 8 evaluations out of 500,000.

**2. Applicability: on the real programmes the DP finds nothing feasible.**
Feasibility of constructed seeds, 6 seeds each:

| programme | leaf_sharing on | off |
|---|---|---|
| harbor-house | **0/6** | **0/6** |
| programme-house | 0/6 | — |
| harbor-house-l0 | 4/6 | 5/6 |

So even those 8 bootstrap individuals get no warm start on harbor or
programme-house. Only `harbor-house-l0` — the reduced programme the DP was
originally validated on (§37.2) — is feasible, at 75% over a real search.

**The infeasibility is correct, not a bug.** This is the dangerous direction, so
it was checked: on 4 harbor topologies the DP calls infeasible, an NM polish
minimising the shape-fail family reaches **14, 16, 17, 16** fails — never 0.
**0/4 false negatives.** The DP is right that these topologies admit no ratio
assignment satisfying every size/width/proportion bound at once; the full harbor
programme is simply shape-infeasible where `l0` is not. Note this is per
*topology*, and says nothing about whether a good design exists — programme-house
reaches 0 hard / 1 soft in the 500k baseline while its constructed seeds are
DP-infeasible.

**`shapecurve_prune` is separately inert.** It only acts inside the
`feasibility_max_shape_fails is not None` branch, and its exact-prune arm
additionally requires `best_n_fails <= 0` — an incumbent with zero total fails.
On these programmes that combination effectively never arises.

**What would have to change** for the feature to be worth an A/B — filed as its
own issue rather than smuggled in here:

- let the DP run for children too, not only where `x0 is None`, so its reach is
  the search rather than the bootstrap; and/or
- treat DP-infeasibility as a *signal* rather than a precondition — an infeasible
  topology still has a best-achievable shape-fail floor, and that floor is
  exactly what a pre-filter wants to rank on.

`tym` was still worth doing: the DP now models leaf-sharing exactly (§38.23) and
fires on real runs, which is what turned an untestable question into a
structural answer.

## 39. Config audit: requirements that actively fight the engine (`homemaker-py-ju3`) — measured 2026-08-25

The corpus `patterns.config` targets and `costs.config` values were estimated
years ago, on the principle that exact values are irrelevant to getting the
evolution engine working. This section asks the inverse question — *do any of
them actively work against it?* — and finds that one does, badly.

Reproduce with `experiments/audit_programme_config.py` (two reports:
namespace collisions, and per-room-spec satisfiability).

### 39.1 Per-room-spec satisfiability — CLEAN (negative result, recorded)

Modelling each leaf as a rectangle of area `A` and aspect `r = w/h ≥ 1`, and
taking the FAIL_THRESHOLD-inverted bounds from the already-validated
`shapecurve.leaf_constraints` (§37.2), no room spec in any of the four corpus
programmes is internally contradictory: for every code there exists an `(A, r)`
satisfying size, width, proportion *and* crinkliness simultaneously, and none
needs more than one exposed side (i.e. none secretly demands a corner). The
hypothesis that the estimated targets are mutually unsatisfiable is
**falsified**, and the audit is kept so the question stays answered.

(One instance of exactly this class was already known and handled:
`get_space_params` derives a width from size and proportion for small
programme spaces rather than falling back to `width_inside` `[4.0, 1.0]`,
"which is impossible for small programme spaces (e.g. a 3 m² WC)".)

### 39.2 Programme codes collide with the generic type namespace — SEVERE

Urb's type system is **prefix-based** — a type starting with `c` is
circulation, `o`/`s` is outside — and programme room codes live in the **same
namespace**. Any code whose name happens to begin with one of those letters is
silently reinterpreted as a generic type. Three independent consequences, none
of them announced anywhere in the output:

1. **`graph.check_space_counts` skips the code entirely** —
   `if code[0].lower() in ("c", "o", "s"): continue`. The room is never
   required, never counted, and produces neither a missing nor a too-many
   failure. **It is optional, silently.**
2. **`Fitness.get_space_params` returns the generic `*_circulation` /
   `*_outside` parameters *before* consulting `self.spaces`**, so the declared
   size/width/proportion are overridden.
3. **`dom.is_circulation` / `is_outside` become true**, changing the leaf's
   value rate, exempting it from crinkliness, and making it supply daylight to
   its neighbours.

`harbor-house` — the project's primary benchmark — is affected;
`maple-court`, `health-centre` and `programme-house` are namespace-clean.

| code | name | declared → effective | flags | value rate |
|---|---|---|---|---|
| `cr1` | Common Room with Fireplace | size **80.0 → 0.0/14.0**, width **6.0 → 2.4**, proportion **2.0 → 1.5** (all three) | `is_circulation` | **50** (vs 300) |
| `of` ×2 | Staff Office | width 2.5 → 3.0, proportion — → 1.5/50 | `is_outside` | 100 |
| `st1` | Ground Floor Storage | width 3.0 → 3.0/0.3, proportion — → 1.5/50 | `is_outside` **and** `is_circulation` | 100 |
| `st2` | First Floor Storage | width 3.0 → 3.0/0.3, proportion — → 1.5/50 | `is_outside` **and** `is_circulation` | 100 |

**5 of harbor-house's 37 room instances (14%) are silently optional.**

**Measured consequences**, on the 20 000-eval run of §38:

- The two `cr1` leaves converged to **32.9 m² and 17.1 m² against a declared
  80 m²** — and produced **no `too many spaces` failure despite `count: 1`**,
  because the count check skips the code.
- `of`, `st1` and `st2` are **absent from the result entirely, with zero
  failures**, because nothing ever asked for them.

This compounds directly with §38.2: `cr1` is the single largest room in the
programme, and classifying it as circulation puts it on the wrong side of the
×6 `value_circulation`/`value_inside` gap — so the objective is paid to shrink
the common room, which is exactly what it did.

**Benchmark-validity consequence.** Every harbor-house fail count in this
document was measured against a **32-instance effective programme, not the
37-instance one its config declares**. Cross-programme comparisons involving
harbor-house (§13.9, §13.11, §17, §20, §23, §37.1, §37.7) are internally
consistent but are not measuring the programme as written.

### 39.3 What shipped — tighten the matching rule at the source

A first pass took the cheaper route from the bead's design: refuse a colliding
programme code at load, and rename harbor's four. **That has been superseded and
the rename reverted** — `cr1`, `of`, `st1`, `st2` are back. The right fix was to
tighten the matching rule so a room may be called anything at all.

**The rule.** Urb has exactly three GENERIC structural types
(`get_space_types`: `qw/C O S/`) — the leaves the *search* creates. Measured
across the whole corpus: **154 `C`, 110 `O`, 1 `S`, and not one lowercase
generic**, while every programme code is lowercase — including single-character
ones (`r`, `t`, `m`, `n`). So **case is the discriminator, not length**, and the
two namespaces are cleanly separable. Every generic test used to be
`type[0].lower() in (...)` — a case-insensitive *prefix* — which swept up any
programme code starting with those letters. They now match the generic set
exactly.

Crucially this is **not** applied to the SEMANTIC prefixes. `l`/`k`/`b`/`t`
classify *programme codes* by first letter (`k1` is a kitchen; `graph.py` builds
bedroom↔toilet and kitchen↔living relations from them) and stay prefix-based.
Only the generic-type tests were tightened — 30 sites across `dom.py`,
`fitness.py`, `graph.py`, `operators.py`, `programme.py`, `shapecurve.py` and
`bubble.py`. Where the two namespaces were mixed in one expression they were
split: `has_circulation`'s `("b","l","k","c")` is now three semantic prefixes
*plus* `dom.is_circulation`, and `access()`'s `("l","c","s")` is the semantic
`l` *plus* the generic circulation set.

New in `dom.py`: `GENERIC_CIRCULATION`/`GENERIC_OUTSIDE`/`GENERIC_TYPES` and
`is_generic()`. New in `fitness.py`: `_generic_class()`, which replaces the
`_t0()` first-character dispatch in `quality_size`/`quality_width`/
`quality_proportion`/`value_rate` — the four terms that mattered most, and the
ones a first sweep missed because they dispatch through a `t0` variable rather
than an inline test.

Two subtleties worth recording:

- **`S` is in both generic sets but takes the OUTSIDE parameter families.** The
  original dispatch was `c0 == "c"` then `c0 in ("o", "s")`, so sahn fell to
  outside. A first translation tested circulation first and silently gave `S`
  the circulation params; `test_get_space_params_sahn_proportion` caught it.
- **Generic adjacency references are lowercase in `patterns.config`** — every
  corpus programme writes `adjacency: [c, o]`. `graph._adjacency_target` resolves
  those to the generic set while leaving every other requirement on Perl's
  prefix semantics (a requirement `t` still matches `t1`, `t2`, …). Previously a
  room next to `cr1` "Common Room" counted as being next to circulation.

`programme.validate_codes` survives but is narrowed to what is still a genuine
ambiguity: a code spelled **exactly** `C`, `O` or `S`. Codes merely starting
with those letters are now fine — that was the bug, not the rule.

**The invariant, asserted as a test.**
`test_scoring_is_invariant_under_programme_code_spelling` builds one harbor
layout, then relabels that exact tree *and* its config together and re-scores:
same geometry, same topology, only the spelling differs. Bit-identical across
12 comparisons (6 seeds × in-search collapse on/off). Renaming a room can no
longer change what a layout scores.

### 39.4 Re-baseline

`homemaker-evolve init.dom --budget 20000 --workers 4 --seed 1` — same seed,
budget and settings as §38's run, so the two are directly comparable. Harbor
keeps its **original** code names throughout; only the matching rule changed.

| | effective programme | fails | `cr1` (declared 80) | `of` ×2 / `st1` / `st2` |
|---|---|---|---|---|
| before §39 | 32 instances | 57 | **32.9 and 17.1** (two leaves against `count: 1`, and no too-many fail) | **absent, zero fails** |
| after §39.3 | **37 instances** | 58 (15 hard / 43 soft) | **79.1** | **12.2, 11.0 / 22.5 / 20.1** |

Every one of the five previously-lost room instances is placed and sized inside
its declared sigma band, and exactly one failure in the whole result mentions
any of the four codes (an adjacency miss on one office). The common room is
within 1 m² of its brief, having previously converged to a fifth of it.

Fail count 57 → 58 on a programme that is 5 instances harder: at one seed each
that is within noise, and the honest claim is **"did not regress"**, not
"improved". The robust result is the room placement. (An intermediate
measurement taken with the codes renamed rather than the rule tightened gave 55
on the same seed — the same picture.)

**Historical numbers.** Every harbor-house fail count recorded before §39 was
measured against the 32-instance effective programme. They remain valid relative
to each other but are not comparable to post-§39.3 numbers; treat 58 as the new
harbor reference point at this budget.

### 39.5 A false alarm on `2g7.5`, and the real bug underneath it — CORRECTED

**This section previously concluded that `2g7.5`'s CP-SAT seeder win did not
survive §39.4. That conclusion was wrong and is retracted.**

The symptom was real: after tightening, the harbor A/B flipped to greedy 102 /
cpsat 114, and a control on namespace-clean maple-court still showed cpsat
winning — which looked like "harbor's programme changed, the solver is fine".
It was not. **`cpsat._matches` was still matching adjacency by raw
`startswith`** while `graph.has_adjacency` had been moved to the generic-aware
matcher, so the exact solver was optimising a *different relation* than the
scorer checked — it still believed a room next to `cr1` satisfied "adjacent to
`c`". The failing test was correctly reporting an incomplete sweep, and it was
misread as a baseline shift.

Fix: `graph.code_matches_requirement` is now the single public answer to "does
this leaf count as the thing the programme asked to be next to", and `cpsat`
uses it for both its adjacency matcher and its symmetry-breaking grouping.
Re-measured over 6 seeds:

| programme | greedy | cpsat | |
|---|---|---|---|
| harbor-house | 102 | **92** | cpsat wins |
| maple-court | 156 | **154** | cpsat wins |

`2g7.5`'s seeder-level result stands. **RESTATED — see §38.20.** This margin
(10 fails on harbor) is inside the ±23-fail noise band this same section
documents below, and it was measured before `homemaker-py-fdp` made CP-SAT's
inputs deterministic. Re-measured deterministically over 12 seeds under the
current objective, cpsat *loses* on both programmes at ~21× the seeding time. Both `assign_solver` flags remain default
off for the independent reason §37.7 gives (it does not survive a full
`driver.search` run).

**The real bug underneath: CP-SAT was never deterministic.** Chasing the flip
turned up that `solve_room_labels` returned different (equally optimal)
assignments across identical runs — measured 194 / 180 / 171 / 182 over four
identical 10-seed aggregates. `num_search_workers = 1` was set with the comment
"determinism (same inputs -> same result)", but that is not sufficient:

- `max_time_in_seconds` is a **wall-clock** cap, so a timeout returns whatever
  branch-and-bound had reached — load-dependent by construction. Now paired
  with `max_deterministic_time`, a load-independent work-unit budget. (Measured
  aside: solves finish in ~124 ms mean / 305 ms max against a 2 s cap, so
  nothing was actually timing out — this was a latent hazard, not the cause.)
- The actual cause: `neighbors[slot]` is a **set of `dom.Node`**, and `Node` is
  `@dataclass(eq=False)`, so it hashes by `id()` — a memory address. Iterating
  it raw made the order the model was built in vary run to run, and among
  several equally-optimal assignments CP-SAT returned a different one each
  time. `sorted()` on the integer slot indices makes the model canonical. This
  is the same id-keying hazard `geometry._cache` already carries a warning for.

After both fixes `solve_room_labels` is reproducible on every captured
instance, and cpsat beats greedy on 4 of 4 repeats. **`constructive_topology`
as a whole is still not bit-reproducible on the cpsat path** — something
upstream of the solver in `_assign_adjacency_aware` still varies (greedy *is*
reproducible; the solver in isolation now is too). Filed as
`homemaker-py-fdp`; it is a plausible contributor to `homemaker-py-b8g`
(parallel-run non-determinism). The A/B test now averages three repeats rather
than asserting on one, so it states what is actually claimed — better in
aggregate — instead of being flaky by construction.

**Lesson worth keeping:** when a matching rule is tightened, every consumer of
that rule has to move at once. A solver optimising yesterday's relation against
today's scorer looks exactly like a baseline shift.

### 39.6 The second namespace: usage prefixes are still implicit — NOT clean

§39.4 separated **programme codes** from the **generic structural types**
(`C`/`O`/`S`). It did not touch the other namespace sharing the same first
character: the **usage prefixes** `b` bedroom, `t` toilet, `l` living,
`k` kitchen. These classify *programme codes* by first letter and are still
prefix-based **by design** — it is how Urb encodes room usage, and unlike the
generic rule they never discard a requirement.

They are not inert, though. `graph.has_circulation` deletes graph edges from
them: a "bedroom" loses its edges to living/kitchen/bedroom/toilet, a "toilet"
loses its edges to outside/living/kitchen/toilet, and b/t keep their *least*
popular circulation neighbour while l/k keep their *most* popular.
`fitness.access` and the public-access check read them too. So a code that
picks one up by accident is silently given another room's connectivity rules —
and connectivity is exactly where §38 found the residual.

`experiments/audit_programme_config.py` now reports this. Four corpus rooms are
misclassified by spelling alone:

| code | name | given usage |
|---|---|---|
| `la1` | Laundry Room | **living** (harbor-house, harbor-house-l0, maple-court) |
| `li1` | Library Corner | **living** (harbor-house, maple-court) |
| `br1` | Staff Room | **bedroom** (health-centre) |
| `tr1` | Treatment Room | **toilet** (health-centre) |

Measured consequences on a constructed health-centre seed: `tr1` "Treatment
Room", treated as a toilet, has its edge to the adjacent outside space `O`
stripped from the circulation graph; `br1` "Staff Room", treated as a bedroom,
has its edge to `t10` "Staff WC" stripped. Both feed `has_circulation` and
therefore the `N inaccessible usable space` / `level N not connected` fails.

**So the honest answer to "is it clean now" is: the generic namespace is
(zero violations across all ten example programmes, asserted by
`test_scoring_is_invariant_under_programme_code_spelling`); the usage namespace
is not.** Filed as `homemaker-py-sel`. The fix is the same shape as §39.4 — an
explicit `usage:` key in `patterns.config` defaulting to the prefix rule for
back-compatibility — but unlike §39.4 it changes fitness for programmes that
are *currently spelled correctly* too, so it needs its own A/B and re-baseline
rather than being folded in here.



### 39.7 `usage:` — access requirements become a declared attribute (`homemaker-py-sel`) — DONE

§39.4 separated programme codes from the generic structural types. This closes
the second namespace sharing the same first character: the **usage prefixes**
`b`/`t`/`l`/`k`, under which a room silently inherited another room's
connectivity rules from its spelling.

**Usage is an ACCESS-REQUIREMENT class, not a room-name category** — "library
corner and staff room are living rooms as they have the same access
requirements". It is now a plain, mandatory attribute of the space definition:

```yaml
spaces:
  la1:
    usage: utility          # controlled, drives engine behaviour
    name: Laundry Room      # free text, building-specific
```

**Why an attribute and not a lookup table.** An interim design proposed a
top-level `usage_classes:` table binding author-coined names to behaviour. It
was withdrawn: an indirect name→behaviour mapping living apart from the thing
it describes is *exactly* the shape of the prefix rule §39 exists to remove,
it is the only such table the schema would contain (every other space property
— `name`, `size`, `adjacency`, `level`, `count`, `share`, `interchange`,
`co_locate` — is a plain attribute), and the need it served was already met:
"building specific" is about what a room is **called**, and `name:` is already
free text. The rule that settles it: **a usage value exists if and only if the
engine treats it differently somewhere.** Config selects among behaviours; it
cannot invent them.

**Mutation safety.** Usage is keyed by CODE, so `usage_of(leaf.type)` is looked
up fresh on every read exactly as size/width/adjacency are; a retype changes the
code and the class follows. It is never stamped on a leaf — 51 sites assign
`leaf.type`, and `share`/`share_type` plus the `r5a` stale-stamp resurrection
are this project's own evidence for why leaf-level attributes rot.

**Vocabulary** (closed): `living`, `kitchen`, `bedroom`, `toilet`, `utility`,
`none`. Missing or unknown is a load error naming the code, from **both** parse
paths. `utility` shares `bedroom`'s access requirements today but is a distinct
value — a genuinely different use, and an axis
`derive_interchange_classes` can relax on (bedroom- and utility-class leaves
interchangeable *during* search, collapsing to their real use at scoring time —
the superposition relaxation §13/§26 already implements).

`graph.has_circulation` now takes the usage map and trims on declared class;
`fitness.access` and the public-access check likewise. **`fitness._t0` is
deleted — no first-character type test remains anywhere in the codebase.**

**The connectivity model was ~4× too permissive.** `none` is not neutral:
nothing is trimmed, so the graph may route *through* the room. 34 of 52 corpus
codes had no class, meaning a Dental Surgery, a Records Room and a Utilities
Closet all served as corridors. Measured on constructed seeds, 3 per programme,
prefix-inferred vs declared:

| programme | codes reclassified | edges trimmed before | after | inaccessible-space fails |
|---|---|---|---|---|
| harbor-house | 12 of 16 | 18 (9%) | **79 (39%)** | 0 → **4** |
| health-centre | 14 of 19 | 12 (8%) | **59 (40%)** | 2 → **3** |
| maple-court | 18 of 26 | 53 (17%) | **123 (39%)** | 1 → **5** |

**Re-baseline** (`--budget 20000 --workers 4 --seed 1`, harbor-house): 58 fails
(15 hard / 43 soft) → **61 (16 hard / 45 soft)**, and the result now reports
`1 inaccessible usable space` ×2, `level 0 not connected` and `level 1 not
connected`. The count went **up because the objective got honest**: those
failures were always true of the layout, and the old model could not see them.
Every harbor number before §39.7 was measured against a connectivity graph that
credited routes through store cupboards.

This sharpens §38.2 rather than competing with it. The objective already pays
×60–85 to delete circulation; until now the corridors it deleted were not
missed, because consulting rooms and storage stood in for them. With that
substitution gone, `homemaker-py-2v1` (connectivity priced at ×0.5 against a ×6
circulation→habitable value gap) is the remaining half of the same problem —
and now measurable, because the fails it should be preventing actually fire.

### 39.8 `homemaker-py-2v1` connectivity weighting — MEASURED NULL, premise retracted

§38.2 concluded that the objective is net-positive on severing a level's
circulation: merging a corridor into a habitable sibling gains
`value_inside / value_circulation` = ×6, while `level N not connected` costs
only ×0.5, so break-even needs `0.5^w < 50/300`, i.e. w > 2.58 — "severing must
cost at least 3 fails and costs 1". **The arithmetic is right and the premise is
wrong.**

**What shipped anyway** (EXPERIMENTAL, default off, byte-identical):
`fitness.connectivity_weight_for(value_inside, value_circulation)` returns the
smallest weight making severing net-negative — 3.0 at the defaults, *derived*
from the rates rather than hard-coded, so it tracks them if either is retuned.
`conf["connectivity_weight"]` takes `1.0` (default, the flat rule), `"auto"`, or
an explicit number, and counts each connectivity failure as w failures in the
`0.5^n` penalty. `is_connectivity_fail` identifies the two strings.

**The measurement.** At `auto` (=3) the §38.2 deletion test does not move at
all: 5/25 deletions rewarded either way, median ×0.26 vs ×0.27. The reason is
immediate once looked for — **the connectivity fail count is unchanged in every
rewarded deletion**:

| seed | deleted | | score | fails | connectivity fails |
|---|---|---|---|---|---|
| 0 | `rlrrr` `O` | buried | ×238 | 115 → 107 | 5 → **5** |
| 0 | `rrrl` `O` | lit | ×346 | 115 → 106 | 5 → **5** |
| 1 | `lrlll` `cr1` | lit | ×257 | 107 → 99 | 3 → **3** |
| 2 | `rlrrl` `O` | buried | ×127 | 78 → 71 | 3 → **3** |

Weighting a failure that never fires changes nothing. And when the deletion
*does* break connectivity, the objective already punishes it — every such case
across harbor-house and maple-court, 4 seeds each:

| programme | deletions sampled | break connectivity | of those, rewarded |
|---|---|---|---|
| harbor-house | 32 | 2 | **0** (×0.00, ×0.01) |
| maple-court | 32 | 5 | **0** (×0.58 … ×0.07) |

So severing is already net-negative: it costs 1–2 connectivity failures *plus*
the cascade that follows them (inaccessible space, broken adjacency), and that
total already outweighs the ×6 value gain. The flat rule was never the problem.

**Where §38.2 went wrong.** The ×4.06 "well-daylit circulation leaf" that
motivated the whole bead was a deletion that did **not** change the
connectivity fail count. It was rewarded for removing the leaf's own quality
failures — §38.1's zero-value finding — and was misread as evidence for a
pricing mechanism. Two lessons, both cheap to state and expensive to learn: a
plausible closed-form arithmetic is not a measurement, and when a fix produces
*exactly* no effect, suspect the premise before the implementation.

**What is still true from §38.** §38.1 (buried leaves score a hard quality of
zero and contribute no value) and §38.3 (the frontage budget) are direct
measurements and stand. §39.7's finding — that the connectivity model was ~4×
too permissive — also stands and is the more useful lever: it made the fails
*fire*, where this bead would only have made them *cost more*.

**Verdict: NULL.** The flag stays default off with this write-up, per house
style for a measured-null lever. `homemaker-py-2v1` is closed. Why
`level 0/1 not connected` survive in the best-known layout is re-opened as a
question (`homemaker-py-yql`) — the evidence now says it is a reachability problem
(connected topologies are hard to construct and hold onto), not an incentive
one. It is newly measurable: §39.7 made the fails fire on constructed seeds
instead of being hidden by routes through store cupboards.

### 39.9 Why `level N not connected` persists: the resize destroys it (`homemaker-py-yql`)

§39.8 closed `2v1` NULL — severing circulation is already punished, so the fail
is not something the search is paid to create. That left the real question: is a
connected layout **rarely constructed**, or **constructed and then lost**?

**Answer: constructed, then lost — at construction time, in the resize.**

`level N not connected` fires from `graph.connected_circulation`, which keeps
only the generic `C`/`S` leaves and asks whether *they* form one component.
Measured over 20 constructed seeds per programme
(`experiments/diag_connectivity_yql.py`):

| programme | levels connected | seeds fully connected |
|---|---|---|
| harbor-house | 21/40 (52%) | **1/20** |
| health-centre | 1/20 (5%) | **1/20** |
| maple-court | 39/60 (65%) | **0/20** |

Then the decisive control — the same seeds with `proportion_aware=False`, i.e.
skipping `_size_divisions_from_targets`:

| programme | with resize | **without resize** |
|---|---|---|
| harbor-house | 52% | **100%** |
| health-centre | 5% | **100%** |
| maple-court | 65% | **100%** |

`_assign_adjacency_aware` picks circulation as a **connected** dominating set —
and it succeeds every time. The resize then moves every wall to hit the
programme's area targets, and the shared boundaries the dominating set relied on
shrink or vanish. On health-centre, **41 of 49 circulation-to-circulation edges
are destroyed by the resize**, and surviving shared walls are squeezed to
0.54–1.11 m against a 1.2 m `door_width`, so they stop counting as edges at all.

This is exactly the failure mode §37.7 recorded for CP-SAT room assignment —
"resizing can shrink a shared-wall segment below the door-width adjacency
threshold, silently invalidating an edge the exact solve relied on" — but nobody
had looked for it in **circulation connectivity**, where it costs 35–95 points.

**§39.7 cost check: zero.** The same measurement under prefix-inferred vs
declared usages is identical (52/5/65% both ways). `has_circulation` never trims
`C`–`C` edges, so the usage change could not and did not make connectivity
harder to achieve.

#### The obvious repair is a net loss — measured

`operators.repair_circulation_settled` applies §37.7's own alternating-
minimisation fix: after the geometry settles, re-connect circulation by retyping
the cheapest bridging leaves to `C` (preferring generic outside, then
unassigned, crossing a required room last — `mutate_bridge_circulation`'s cost
model). It works, completely:

| programme | levels connected, repair OFF | repair ON |
|---|---|---|
| harbor-house | 52% (1/20 seeds full) | **100% (20/20)** |
| health-centre | 5% (1/20) | **100% (20/20)** |
| maple-court | 65% (0/20) | **100% (20/20)** |

And it is still the wrong trade. Mean fails per constructed seed, 12 seeds:

| programme | total | hard | connectivity | missing-room |
|---|---|---|---|---|
| harbor-house | 96.6 → **108.9** | 46.0 → 56.2 | 3.7 → 2.0 | 14.2 → **19.2** |
| health-centre | 62.8 → **84.2** | 24.2 → 46.8 | 2.9 → 2.2 | 2.0 → **10.5** |
| maple-court | 141.8 → **156.6** | 57.4 → 69.2 | 4.7 → 3.5 | 14.8 → **19.8** |

Connectivity failures fall by 0.8–1.7; missing-room failures rise by 5.0–8.5,
because every leaf retyped to `C` displaces a required room and each displacement
costs a 3–5 fail cascade (§38.5). **Robbing Peter to pay Paul.** Kept default
off with this write-up, per house style for a measured-null lever.

**The lever is upstream, not downstream.** The repair is treating a symptom: the
connection should never be destroyed in the first place. The named next move is
to *preserve* it during the resize — constrain `_size_divisions_from_targets` so
a shared boundary between two circulation leaves cannot fall below `door_width`
— rather than to rebuild it afterwards at the cost of the programme. That is a
constraint on an existing solve rather than a new repair pass. Filed as
`homemaker-py-3z0`. Worth noting while there: `solver.py` already carries
`min_width_generic` (default 1.2) to stop generic leaves collapsing to slivers
— the same idea applied to a leaf's WIDTH rather than to a shared BOUNDARY
between two specific leaves, so the new constraint may belong beside it.

### 39.10 Preserving constructed connectivity through the resize (`homemaker-py-3z0`) — NULL, and it reframes §39.9

§39.9 established that `_size_divisions_from_targets` destroys the connected
circulation the seeder builds, and named the upstream fix: keep the connection
*during* the resize rather than rebuilding it after. Built and measured. **It
does not help, and the reason matters more than the lever.**

**Both halves of the re-cut do damage, in different proportions per programme.**
The resize changes each node's ratio *and* re-picks its rotation. Freezing the
rotations and letting only the ratios move (12 seeds, % of levels connected):

| programme | no resize | ratio only | full resize |
|---|---|---|---|
| harbor-house | 100% | 71% | 50% |
| health-centre | 100% | **8%** | 8% |
| maple-court | 100% | 92% | 67% |

health-centre is destroyed entirely by the ratio; maple-court mostly by the
rotation. So any fix has to be able to give back either.

**`operators._size_divisions_preserving_circulation`** snapshots every cut,
resizes, then reverts the cuts on the tree path between each
circulation-to-circulation pair the resize broke. It keeps the programme
completely intact — no retyping, no displacement, only geometry given back —
and it works on connectivity:

| programme | connected, OFF | ON | fails OFF → ON | hard OFF → ON |
|---|---|---|---|---|
| harbor-house | 50% | **92%** | 96.6 → **141.5** | 46.0 → 65.1 |
| health-centre | 8% | 17% | 62.8 → **76.9** | 24.2 → 25.8 |
| maple-court | 67% | **97%** | 141.8 → **175.8** | 57.4 → 70.9 |

(A first attempt reverted greedily — whichever single cut most reduced the
component count — and barely moved: it stalls on the plateau where no *one*
revert helps though two would. Targeting the specific broken pairs is what
made connectivity work.)

Reverting a cut gives back that subtree's area accuracy, and size failures
roughly double on harbor-house (5.2 → 11.4). The obvious defence is that these
are raw constructed seeds and the inner loop has not run yet — the resize exists
to *warm-start* the ratio optimiser, so a worse warm start might cost nothing
once it converges. **Tested, and the defence fails.** Full search, harbor-house,
12 000 evals, seed 1, both arms:

| | fails | hard | soft | connectivity |
|---|---|---|---|---|
| `preserve_circulation` OFF | **43** | **9** | 34 | **3** |
| `preserve_circulation` ON | 65 | 26 | 39 | 4 |

Worse on every axis — including connectivity itself, the thing it was built to
fix.

**The reframing.** §39.9's finding stands as a fact (the resize really does
destroy 41 of 49 circulation edges) but is **not actionable, because
construction-time connectivity is not what determines final connectivity**. The
search reaches 43 fails with 3 connectivity fails starting from a 50%-connected
seed; forcing the seed to 92% connected yields 65 fails and 4 connectivity
fails. The seeder's circulation topology is not the bottleneck — the search
discards and rebuilds it either way, and constraining the seed only spends area
quality the search then cannot recover.

That also retires the framing this whole thread inherited from §38: connectivity
was never a construction problem *or* an incentive problem (§39.8). Both flags
(`repair_circulation`, `preserve_circulation`) stay default off with these
numbers recorded. **Do not revisit either without a new formulation** — the same
standing this document gives `bubble.py`.

### 39.11 The frontage bound, computed correctly (`homemaker-py-tdp`) — shipped as a pre-flight check

§38.3 derived a real constraint — every interior leaf needs
`L >= A/(1.6202·h)` of daylit wall — and then applied it to the wrong quantity.
It measured what a **fully built plot** would need. These programmes do not ask
for a fully built plot.

Recomputed against the area each programme actually demands:

| programme | demanded/storey | % of plot | frontage needed | supplied | gap | courtyard to close | spare plot | |
|---|---|---|---|---|---|---|---|---|
| harbor-house | 418 m² | 60% | 86 m | 53 m | +33 m | 49 m² | 277 m² | **OK** |
| maple-court | 338 m² | 44% | 70 m | 55 m | +15 m | 22 m² | 424 m² | **OK** |
| programme-house | 38 m² | 72% | 8 m | 22 m | −14 m | none | — | **OK** |
| health-centre | 240 m² | **131%** | 49 m | 41 m | +8 m | 12 m² | **−57 m²** | **DOES NOT FIT** |

Plot area and frontage are measured through `geometry`, not from the raw
`init.dom` corners, so they carry the `wall_outer` inset and the plot rotation —
these are the metres and the square metres the leaves actually get. "Daylit"
means what `Fitness.area_outside` means by it: an external boundary counts
unless its perimeter type is `private` or `fortified`.

So harbor-house and maple-court are **not** frontage-infeasible; they need a
courtyard of 49 m² and 22 m² respectively, against 277 m² and 424 m² of spare
plot. §38.3's "2.7× short" overstated it by comparing against a building nobody
asked for.

**The one genuinely infeasible programme is health-centre, and not for daylight
reasons: it demands 240 m² of floor on a 183 m² plot.** That shows up
unmistakably in the geometry — every room comes out at **0.60×** its declared
target, 100% of them undersized, uniformly, no matter what the search does.
Contrast harbor-house and maple-court, where the seeder hits targets almost
exactly (median area / (target × share) = **1.01×**).

*(An intermediate measurement suggested rooms were systematically inflated to
1.26–1.65× target. That was an artefact of not dividing by a shared leaf's
multiplicity — a leaf covering k rooms is legitimately k× a single target.
Corrected above; the seeder's sizing is accurate where the plot allows.)*

**Shipped: `evolve._preflight`.** Both checks now run at startup and print a
warning before a multi-hour run bottoms out against something no amount of
searching can fix:

```
WARNING: programme demands 240 m2 per storey on a 183 m2 plot (131%). Every room
will be squeezed below its target however long the search runs.
WARNING: 418 m2 per storey needs ~86 m of daylit wall; the plot's non-private
perimeter gives 53 m. Roughly 49 m2 of courtyard closes the gap.
```

Advisory only — it never blocks a run, since an author may be deliberately
exploring an over-tight brief. Silent on programme-house. The same numbers are
available in full from `experiments/diag_exposure_frontage.py frontage`.

**What this means for §38.** The frontage bound survives as a *diagnostic* and
is now correctly calibrated, but it does **not** say the corpus is
unsatisfiable. Of the four programmes, three fit their plots and one does not —
and that one fails a much cruder test than daylight. §38.3's claim that the
plateau programmes are "frontage-infeasible as specified" is withdrawn.

### 39.12 The cold-start re-baseline, and what it does to §38.7's acceptance test (`homemaker-py-ut5`)

Every corpus fail count published before §39.4/§39.7/§38.11 was measured
against a different objective and, for harbor-house, against a different
*programme* — the 32-instance effective one, where `cr1`/`of`/`st1`/`st2` were
being read as generic circulation and silently dropped. §38.7 nevertheless
pinned the Phase-9 acceptance test to one of those numbers:

> harbor-house must reach its known **15-fail floor** in materially fewer than
> 1.7 M evals, *and* `level 0 not connected` / `level 1 not connected` must be
> absent from the result.

That figure is not measurable any more, and this section replaces it.

**The bead's migration premise is stale.** `homemaker-py-ut5` asks for
`evolved-3M*.dom` to be migrated with `experiments/migrate_ju3_rename.py`. That
script does not exist: the rename approach was abandoned during `ju3` in favour
of tightening the matching rule at the source (§39.3), so the old artefacts
parse correctly against today's 16-code / 37-instance harbor programme with no
migration at all. Criterion satisfied, differently.

**The 3M artefacts, rescored under the current objective** (all committed at
`0d4ae7a`; `missing` counted as distinct instances, not placeholder lines):

| artefact | fails | hard | soft | `not connected` | missing instances |
|---|---|---|---|---|---|
| `evolved-3M-nols.dom` | 69 | 32 | 37 | 2 | 4 |
| `evolved-3M-nols-3.collapsed.dom` | 85 | 42 | 43 | 2 | 3 |
| `evolved-3M-nols-2.dom` | 87 | 43 | 44 | 2 | 3 |
| `evolved-3M-nols-3.dom` | 89 | 44 | 45 | 2 | 3 |
| `evolved-3M.dom` | 145 | 101 | 44 | 1 | 22 |

So the layout §38.7 called a 15-fail floor scores **89**. Most of the
difference is not a regression in the layout: it is the instances the effective
programme used to drop, now counted, each of which cascades into a
`missing required space` line plus three `would need <check>` placeholders.

**But these numbers cannot be compared to a fresh run.** The 3M artefacts were
*evolved* under one objective and are *scored* under another. Nothing in them
was ever selected for the terms they are now judged on. They are a record of
what the old search produced, not a floor the current search has to beat.

**The cold-start baseline is the reference from here.** Four programmes ×
3 seeds × 500,000 evaluations, from `init.dom`, one worker per run (so
`homemaker-py-b8g`'s parallel non-determinism cannot get in), scored by the
shipped scorer — `experiments/run_coldstart_baseline.py`, results in
`experiments/results/coldstart_baseline.tsv`, artefacts committed as
`examples/*/coldstart-500000-s{0,1,2}.dom`. ~430 h of compute.

| programme | fails (s0/s1/s2) | mean | sd | MDD at N=3 | hard | `not connected` | missing |
|---|---|---|---|---|---|---|---|
| programme-house | 1 / 1 / 1 | 1.0 | 0.00 | 0.0 | 1 | 0 / 1 / 0 | 0 |
| health-centre | 4 / 9 / 5 | 6.0 | 2.65 | 6.6 | 10 | 1 / 1 / 1 | 0 |
| harbor-house | 33 / 43 / 42 | 39.3 | 5.51 | 13.7 | 27 | 2 / 2 / 2 | 0 |
| maple-court | 54 / 73 / 55 | 60.7 | 10.69 | 26.6 | 46 | 3 / 2 / 3 | 0 |

MDD is the smallest mean difference a 3-seed paired comparison could call
significant at 95% (`t_crit(0.975, 2)·sd/√3`, §38.22). For harbor that is
**13.7 fails**: any future A/B on this corpus at n=3 that reports a margin
smaller than that has not measured anything. This is the same trap `0wr`
found in the old harbor A/Bs.

**Two results worth stating plainly.**

*Missing spaces are gone.* Zero `missing required space` fails in all twelve
runs, across all four programmes. The current search places every required
instance of every code, every time. The dominant term in the stale 3M
artefacts is not a term the live search still fails on — which is exactly why
those artefacts could not have served as a floor.

*A third of the residual is a term with no gradient.* Aggregated over all 321
fails in the twelve runs:

| category | count | share | tier |
|---|---|---|---|
| crinkliness | 112 | 34.9% | soft |
| size | 44 | 13.7% | soft |
| edge too long | 29 | 9.0% | soft |
| not adjacent to | 28 | 8.7% | **hard** |
| access | 24 | 7.5% | soft |
| inaccessible usable space | 20 | 6.2% | **hard** |
| proportion | 18 | 5.6% | soft |
| not connected | 18 | 5.6% | **hard** |
| width / too few stairs / staircase volume / other | 28 | 8.7% | mixed |

Crinkliness alone is 35% of what the whole corpus is being judged on, and
`homemaker-py-9gj` says `quality_uncrinkliness` returns a flat hard 0.0 in
precisely that regime — so the inner loop cannot rank two layouts that differ
only there. `homemaker-py-gvb` says the same fails are tiered SOFT while most
are topological and unreachable by a ratio solve. The single largest component
of the residual is one the objective currently cannot descend. That is where
the next real gain is, not in more evaluations.

Of the hard fails, 66 of 84 are one family — `not adjacent to` (28),
`inaccessible usable space` (20), `not connected` (18). All three are access
topology, and §39.9/§39.10 established why they survive: the resize destroys
constructed connectivity, and preserving it through the resize (`3z0`) was
measured NULL.

**The restated acceptance test.** §38.7's version cannot stand as written, for
two independent reasons — its fail-count target came from a stale programme,
and `homemaker-py-2v1`, the fix it was the acceptance test *for*, closed NULL
(§39.8: severing the spine is already punished; §38.2 is retracted). There is
no combined fix left to accept. Replacing it:

1. **Reference, not floor.** The corpus reference is the table above, with its
   seeds and its sd. A change is an improvement when it beats the cold-start
   mean by more than that programme's MDD, on the same budget, at n ≥ 3 seeds
   — not when it beats a single remembered number.
2. **Connectivity is a standing defect, not an acceptance clause.**
   `level N not connected` appears in 10 of 12 runs and in every harbor and
   maple run. It is not something a fail-count improvement will clear as a side
   effect; it has its own open mechanism (§39.9) and two measured-NULL attempts
   behind it. Track it as a defect and count it separately; do not fold it into
   a pass/fail on an unrelated change.
3. **Any target quoted in a document or a test carries the commit it was
   measured at.** The `15` was quoted for months after the programme it
   described had changed underneath it. `tests/test_collapse_insearch.py` now
   computes both sides of its invariant instead of pinning constants, for the
   same reason.

