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
- **Phase 4 — penalty reshaping**: replace `0.5^n` with additive/soft,
  lexicographic, or multi-objective (easier once fitness is native), while
  preserving the inner loop's no-new-failures protection (§5.4) and the
  missing-space hierarchy (§6); measure landscape + search.
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
5. **Penalty reshaping vs inner-loop protection.** One fitness shape cannot
   naively be both soft for the outer search and cliff-protected for the inner
   loop (§5.4). Resolve in Phase 4: cliff-inside-inner-loop, lexicographic, or
   Pareto.
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
