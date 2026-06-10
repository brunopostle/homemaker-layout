# homemaker — Design & Plan

**Status:** validated direction, pre-implementation.
**Audience:** a fresh session that will break this into `bd` (beads) tasks. Self-contained — assumes no memory of the originating conversation.

---

## 1. Purpose

`homemaker-py` is a clean-room Python successor to the Perl **Urb** project
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

Package `src/homemaker/`:

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
  the best. Urb's EA under-optimises geometry (its slide mutations are weak/
  under-applied).
- A **full-objective geometry inner loop is genuinely valuable** (the proxy
  solver is not).
- The EA/search should therefore own **topology**; geometry is delegated to the
  inner loop. This is the memetic architecture (§5).

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
- The memetic search can be **prototyped on the batched oracle** before any
  fitness port. A **native Python fitness is strongly desirable** (faster
  assessment, independence, enables penalty reshaping and large programmes) but
  is **a later speed/scale optimisation, not a hard gate**.

### 4.7 The `0.5^n` failure penalty is a first-order pathology
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
   against the oracle on the 35-file corpus) is a later speed/scale optimisation
   — desirable, not a gate.
4. **Reshape the failure penalty** (§4.7) — additive/soft or multi-objective —
   so the search has a gradient and isn't dominated by flag-count.
5. **Representation upgrade (later):** canonical slicing encoding (normalized
   Polish expression / skewed slicing tree, Wong–Liu) for redundancy-free,
   high-locality topology moves; bottom-up shape feasibility checks. Defer until
   the inner loop + native fitness are in place.

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
| **geometry inner loop** | ❌ to build | full-objective ratio optimiser (DOF = free branches); batch/population so the oracle batches |
| **topology genome + operators** | ❌ to build | base tree + per-floor deltas; high-locality moves |
| **search driver** | ❌ to build | memetic EA / SA over topology |
| **native fitness** | ❌ later | speed/scale optimisation (not gating); port + validate vs oracle |
| **penalty reshaping** | ❌ to design | additive/soft or multi-objective |
| canonical encoding (Polish expr.) | ❌ later | representation upgrade once core lands |

Urb fitness terms the native port must reproduce (all couple to geometry):
**size, width, proportion, adjacency, access/inaccessible, crinkliness,
perpendicular, level, staircase volume/count, public access, circulation &
outside ratios, min internal area.** Source of truth:
`/home/bruno/src/urb/lib/Urb/Dom/Fitness/ProgrammeDriven.pm` and the `Storey`/
`Building`/`Leaf`/`Base` submodules.

---

## 7. Phased roadmap

- **Phase 0 — diagnostics** *(done this session)*: geometry port validated;
  proxy solver falsified; full-fitness geometry headroom validated; oracle
  throughput measured (~1 s/dom batched).
- **Phase 1 — geometry inner loop (on batched oracle)**: full-objective ratio
  optimiser; use a population/batch optimiser so a generation scores in one
  oracle call. Reproduce/exceed the §4.5 gains. Integrate as
  `optimise(topology) -> (geometry, fitness)`.
- **Phase 2 — topology search (on batched oracle)**: base-tree + per-floor-delta
  genome, high-locality operators, memetic driver wrapping the Phase-1 inner
  loop. Compare against `urb-evolve` from the same seeds/programmes.
- **Phase 3 — native Python fitness**: port Urb's programme-driven fitness;
  validate score + failure set against the oracle across the 35-file corpus
  (float tolerance, identical failure sets). Swap behind the same interface for
  speed/scale; retire the oracle.
- **Phase 4 — penalty reshaping**: replace `0.5^n` with additive/soft or
  multi-objective (easier once fitness is native); measure landscape + search.
- **Phase 5 — representation upgrade**: canonical slicing encoding
  (Polish expression) + bottom-up shape feasibility; scale to larger programmes.

Each phase has a concrete go/no-go gate; do not advance on faith.

---

## 8. Risks & open questions (decisions for the next session)

1. **Native-fitness fidelity vs simplification.** Port Urb's fitness exactly
   (maximise comparability) or take the opportunity to clean up known issues
   (the `0.5^n` cliff, the t3 width-default contradiction below)? Recommend:
   *port faithfully first*, validate, then reshape in Phase 3.
2. **Programme contradictions exist.** e.g. t3 (3 m² WC) inherits a 4 m default
   width — geometrically impossible; the original "passes" only by failing
   `size` instead. Need a sane width default scaled to area, or per-room widths.
3. **Inner-loop optimiser choice.** Nelder-Mead worked for diagnostics; for
   production consider CMA-ES, Powell, or gradient-based once native fitness is
   differentiable-ish. DOF is small (≈ rooms−1).
4. **Search algorithm for topology.** Memetic GA (keep crossover — now
   meaningful, since a subtree = a contiguous region) vs simulated annealing
   (the floorplanning workhorse with M1/M2/M3 moves on Polish expressions).
5. **End-state confirmed: 100% Python**; Perl oracle is scaffold only.

---

## 9. How to reproduce (for the next session)

```bash
cd /home/bruno/src/homemaker-py
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
