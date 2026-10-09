# DESIGN-INDEX — what is in DESIGN.md, and where

**Load this file, not DESIGN.md.** DESIGN.md is the project's history: about
15,000 lines, 220 sections, in the order things were found. It is too long to
put in a session's context and almost none of it is needed at once. This file
is the map: read it, then read the two or three sections a task touches, by
line range.

`CLAUDE.md` is how to work here. DESIGN.md is what was found and why. This
index is how to get from a question to the section that answers it.

## How to read the history

- **A section's title is its finding.** "§39.108 Outdoor slivers, re-measured
  at three later corpora: not reproduced" is the result; the body is the
  evidence. Scan the titles below before opening anything.
- **Later sections correct earlier ones, and the earlier text is left
  standing.** Nothing is rewritten in place. If two sections disagree, the
  higher number wins, and it usually names what it retracts. Known cases:
  §38.8's headline is retracted by §38.11; §39.9 is reframed by §39.10;
  §39.14 and §39.15 are corrected by §39.16; §39.28's reading by §39.29 and
  §39.30; §39.55's retraction of the adjacency defect is reversed by §39.56;
  §39.57's "inert" by §39.58; §39.112's "a gene outside the tree" by
  §39.113.
- **Every number carries the objective it was measured at** (`c836457+orth`,
  `59d8aa1+orth`, ...), from §39.32 on. Two numbers at different stamps are
  not comparable, and never across the `+orth` switch (§39.12 clause 3,
  §39.42). The stamp has moved many times; `CLAUDE.md` says how to derive
  today's.
- **An expectation is written down before a run and judged after it.** The
  judging tables (§39.89, §39.91, §39.109, §39.111) are the quickest way to
  see what a result did and did not show.
- **A margin smaller than its MDD is "unresolved", not "small"** (§38.19,
  §38.21, §38.22). `experiments/ab_report.py` prints the MDD beside every
  paired verdict.
- **Sections 1-10 describe a plan that predates most of the code.** Read them
  for the original reasoning, not for the current state.

## The arcs, in order

| sections | what happened |
|---|---|
| §1-§10 | The original design: why a Python successor to Urb, the slicing-tree representation, the first empirical findings (§4), the phased roadmap. |
| §11-§13 | Phases 6-8. Making the topology search work on full multi-storey programmes: programme-aware and adjacency-aware construction (positive), staged search, leaf-sharing, interior courtyards; graded objectives and niching (negative). |
| §14-§36 | One experiment per section, verdict in the title. Mostly nulls and negatives: islands, annealing, graded connectivity, multi-use leaves, bubble diagrams, autodiff. Positives: finish-time and in-search collapse (§17, §20), ruin-and-recreate (§23), the 2-opt polish (§25, §28). |
| §37 | Phase 9 plan and its parts: hard/soft fail tiers, the shape-curve DP, the plan-to-dom composer, CP-SAT assignment, graph-first construction (no-go). |
| §38 | **The turn.** The plateau is the objective, not the search: daylight demanded of rooms that do not need it, the missing-space cascade, the frontage budget. Then the statistics discipline (§38.19-§38.22) and determinism fixes (§38.15-§38.17). |
| §39.1-§39.7 | Config audit: room codes colliding with the generic `C`/`O`/`S` types; `usage:` becomes a declared attribute. |
| §39.8-§39.19 | Connectivity, the frontage bound, what the crinkliness factor really rewards and where its constant comes from (Alexander 159). |
| §39.20-§39.21 | The Perl parity tests had never run; the oracle is removed. `fitness.py` is the only evaluator. |
| §39.22-§39.26 | Owner's rulings on circulation: a corridor may be corridor-shaped; `ratio_circulation` removed. |
| §39.27-§39.35 | The `bk9` re-baseline, read slowly, and the rule that every result carries its objective stamp. |
| §39.36-§39.51 | Orthogonal division: found to be free, implemented, swept, adopted on architecture; `edge too long` and `perpendicular` retired; the sweep runner and verifier hardened. |
| §39.52-§39.59 | Terraces, voids and usable space: four rulings, the area rule turned from a floor into a cap. |
| §39.60-§39.69 | Process: the objective stamp widened to every file a score executes, `search_config` recorded per row, a prune of what a session inherits. |
| §39.70-§39.75 | The owner's hand-built three-storey design (1.89x the best evolved), the storey-adding operator, and the stair shaft: the exact-path ruling, which operators break it, the repair. |
| §39.76-§39.80 | The ratio solver's target, the shape-curve DP's exactness, the operator census with negative controls, what a missing room costs. |
| §39.81-§39.93 | `support_outside` A/Bs (flat, then tiers), two sweeps, the omit-vs-circulation ruling, outdoor width 3.0 -> 2.3 m, the rectangle-frame pivot measured before commitment, export to IFC. |
| §39.94-§39.104 | Format v2 and the native rectangle-frame tree; six scorer defects found on the way and fixed on rulings (daylight counted once, the wall above stays, listing order, stair fit, width from the fitted rectangle). |
| §39.118-§39.119 | A solver pass over seeds (better seeds; the A/B is queued); pitched roofs for the IFC export. |
| §39.120 | The move book read (written after §39.121-§39.122): a learned draw has little to offer on programme-house; a quarter of draws are unnamed re-tunes; `place_missing` applies where the scorer sees nothing missing. |
| §39.121 | The first of the five queued A/Bs: `--child-budget 20` is worse, by losing the staircase in six runs of 36. (§39.120 is reserved for the move book.) |
| §39.122 | Two ideas set aside on the owner's word, with the condition that reopens each. |
| §39.123 | The book of moves widened (owner): a move AIMED at a failing cell removes a fail about five times as often on programme-house; `undivide` carries it. |
| §39.124 | The pair census (written after §39.125): no single move and no pair of moves removes a fail from a design the search has finished with. |
| §39.125 | The owner's hand-drawn harbor-house design (31 fails, inside the evolved range) and what it shows: the ruling that a stair is a cell type `E`, and three open questions on connectivity, entrances and daylight depth. |
| §39.126-§39.127 | Ancestry in the move recorder (and why recordings stay text); `E` built on a branch -- 1,002 scores unmoved by relabelling, 426 designs rewritten, a new `mutate_stair` whose first census caught it removing the only staircase. |
| §39.128 | Storey height tuned by the search (branch, default off): the variable alone moves nothing, a jump move does -- the hand design goes 31 -> 26 fails at 3.6 / 3.6 / 2.7 m. |
| §39.129 | `w4e`: the repaired `core_undivide` resolves nothing either way. And the queue's control arms are byte-identical from one A/B to the next -- half of each run re-derives a table that exists. |
| §39.131 | A light-well move (branch, default off): on evolved designs daylight fails are buried cells, which height does not reach; every well the guarded move cuts leaves fewer fails (5 of 5), and it finds few to cut. (§39.130 is reserved.) |
| §39.115-§39.117 | Outdoor value and the briefs; the kit for drawing a harbor-house design by hand; the terrace's value against three rulings, settled at 120. |
| §39.105-§39.114 | A score at half the cost; closed-form sizing (good cold, harmful on a child); the child inner-loop budget; the 2x2 that closed the `support_outside` question; rulings on the stair shaft, incremental re-scoring and the canonical genome. |

## Owner's rulings, and where each is recorded

These are decisions, not measurements. Do not re-argue one from a score.

| ruling | section |
|---|---|
| Corridors need daylight; only a space not occupied from day to day (a cupboard, a store, a plant room) does without, and it says so with `crinkliness: none` | §38.10, §38.11 |
| A corridor may be corridor-shaped; no aspect or size cap on circulation | §39.22-§39.25 |
| Size, width and proportion are two degrees of freedom, not three: the room-width ruling | §39.37 |
| Orthogonal division is adopted on architectural grounds | §39.46 |
| `edge too long` and `quality_perpendicular` are retired | §39.50 |
| Usable space: the internal-area rule is a CAP (1.2x); `adjacency: [o]` needs usable outside space, not a void; a void costs and earns nothing; an indoor\|outdoor wall is an external wall | §39.56, §39.58, §39.59 |
| `support_outside` is default on -- and stays on while no harm is measured | §39.65, §39.112 |
| A staircase exists only where the cell is identical on every storey | §39.72 |
| The cheapest single-room omission must outscore "no circulation", on every programme | §39.84, §39.85 |
| Outdoor width is a six-foot balcony (2.3 m), not three metres | §39.87 |
| A cropped cell is scored by its fitted rectangle, not its vertex count | §39.90, §39.102 |
| Daylight through a shared wall is counted once; stairs are fitted whichever way is best | §39.95 |
| Undividing a cell does not move the wall above; listing order decides nothing; a boxed-in core is a straight flight | §39.96, §39.100 |
| Usable space should be worth more than it costs; an outdoor cell's value does not follow its daylight until the sun calculation is rebuilt | §39.115 |
| A terrace is worth more than a garden: 120 per m², to be revised when daylight scores outdoor space; circulation is deliberately NOT worth its cost, "a building without any circulation has an efficient plan" | §39.116, §39.117 |
| The briefs' gaps are fixed at a good time, which is just before a full re-baseline | §39.115 |
| The stair shaft's position is found by the search, and it is a cell made by division like any other -- no pre-placed block | §39.112, §39.113 |
| A stair is a cell labelled `E` (escalier), a fourth generic type beside `C`/`O`/`S` -- no longer inferred from a `C` cell stacked on every storey. `E` is circulation; a stacked `C` is no longer a stair anywhere; a shaft may stop below the top; an `E` shaft joins the storeys it serves | §39.125 |
| An entrance foyer is "simply a circulation space that has street access": the brief changes, not the rule | §39.125 |
| A room's depth limit is "only a limit for low ceilings": the daylight threshold stands and the search may raise a storey's height (3.3 m is not unusual for a ground floor) | §39.125 |
| "We want to do the right thing; chasing scores is of no value if they depend on flawed logic" | `CLAUDE.md`, applied throughout §39 |

## Measured and negative: read before proposing again

| idea | section | what happened |
|---|---|---|
| Graded high-fail objective; structural niching; diversity x selection pressure | §11.4, §11.5, §11.8 | negative |
| Island model / multi-run recombination | §14 | null; independent populations' subtrees do not line up |
| Leaf-share grain annealing | §16 | negative |
| Graded circulation-connectivity signal | §18 | negative |
| Geometry/topology repair of shape-intrinsic fails | §19 | negative |
| Multi-use leaves, both formulations | §26, §33 | negative, null |
| 3D bubble-diagram adjacency signal | §27 | negative |
| Autodiff inner loop | §34 | negative on wall-clock |
| Graph-first construction / rectangular dualisation | §37.8 | no-go |
| CP-SAT seeding | §37.7, §38.20 | loses in a full run |
| Shape-curve DP warm start as wired | §38.24, §39.78, §39.106 | cannot pay as wired; inexact; wrong point on a native tree |
| Re-weighting the crinkliness tail (three attempts) | §38.1, §39.13, §39.68 | inert; the tail is 0.034% of corpus value |
| Connectivity weighting | §39.8 | null, premise retracted |
| `support_outside` paying for itself | §39.81, §39.86, §39.91, §39.111 | clears a fail that is now rare; a wash on fails and score |
| Skipping the crop for whole cells | §39.105 | declined: under 2% of a score |
| Closed-form or solver sizing of a child | §39.109 | worse than inherited ratios |
| A local inner loop | §39.110 | no better than halving the budget |
| `--child-budget 20` at equal total budget | §39.121 | negative on programme-house: six runs of 36 end with no staircase, none in the control; large programmes untested |
| Pre-placed stair block; incremental re-scoring; canonical genome | §39.113, §39.112, §39.114 | ruled out; set aside; set aside |
| A learned, state-weighted choice of operator ("book of moves", step 3) | §39.120 | not built: the greedy upper bound is 1.2x of a 1.5% rate on programme-house; harbor-house's 2.5x is two applicability rules on 4 early runs |
| Two randomly aimed moves compiled into one, tuned as one child | §39.124 | null on 46 stuck programme-house designs: 2 of 16,330 pairs remove a fail and neither repeats; aimed pairs, a longer tune and mid-run parents are untested |
| `--core-undivide-repaired` | §39.129 | null at 36 pairs on programme-house; default unchanged |
| A child budget that depends on the move; supporting a terrace without shrinking a room | §39.122 | both SET ASIDE unbuilt, not measured negative; the section says what would bring each back |

## Where the current state is

Not here, and not in DESIGN.md. `CLAUDE.md` > *Current state* has the commands
that derive it: the objective stamp, the open beads, which corpora exist, and
whether a run is in progress. The latest sections at the end of the list
below are the most recent work.

<!-- GENERATED BELOW THIS LINE by experiments/build_design_index.py -- do not edit -->

## Every section of DESIGN.md (235 of them, 16368 lines)

`lines` is where to read: `sed -n '<first>,<last>p' DESIGN.md`, or the Read tool with that offset and limit. A top-level section's range is its own introduction only; its subsections follow with theirs.


**§1 Purpose** -- lines 13-32

**§2 Constraints that fix the representation** -- lines 33-57

**§3 What we built this session (all committed)** -- lines 58-80

**§4 Empirical findings (the core of this document)** -- lines 81-82

- §4.1 · 83-88 · Geometry port — VALIDATED
- §4.2 · 89-120 · Bottom-up area-proxy sizing solver — FALSIFIED
- §4.3 · 121-127 · "Perpendicular" failures were an artifact — RESOLVED
- §4.4 · 128-135 · DOF / over-determination — partially real, not fatal
- §4.5 · 136-165 · Full-fitness frozen-topology optimisation — VALIDATED ✅
- §4.6 · 166-192 · Oracle throughput (measured)
- §4.7 · 193-205 · Occlusion-disabled re-baseline (measured 2026-06-12)
- §4.8 · 206-213 · The `0.5^n` failure penalty is a first-order pathology
- §4.9 · 214-247 · Penalty reshaping decision: lexicographic outer search (measured 2026-06-14)
- §4.10 · 248-334 · Deceptive level-fix valley and compound operators (measured 2026-06-14/15)

**§5 Validated architecture** -- lines 335-390

**§6 Component plan** -- lines 391-448

**§7 Phased roadmap** -- lines 449-558

**§8 Risks & open questions (decisions for the next session)** -- lines 559-604

**§9 How to reproduce (for the next session)** -- lines 605-628

**§10 Key gotchas discovered (carry forward)** -- lines 629-650

**§11 Phase 6 — topology-search quality for full / multi-storey programmes** -- lines 651-657

- §11.0 · 658-694 · Diagnosis (why this phase exists)
- §11.1 · 695-740 · Premise experiment: single-storey harbor (`homemaker-py-c4c.1`) — DONE
- §11.2 · 741-808 · Programme-aware construction + missing-room repair (`homemaker-py-c4c.2`) — DONE
- §11.3 · 809-875 · Staged per-floor search (`homemaker-py-c4c.3`) — DONE
- §11.4 · 876-942 · Graded high-fail objective (`homemaker-py-c4c.4`) — DONE (negative)
- §11.5 · 943-1013 · Topology diversity: structural niching + restarts (`homemaker-py-c4c.5`) — DONE (negative)
- §11.6 · 1014-1070 · Adjacency-aware constructive seeding (`homemaker-py-s44`) — DONE (positive)
- §11.7 · 1071-1114 · Adjacency-aware lift + secondary adjacencies (`homemaker-py-ld5`) — DONE (positive)
- §11.8 · 1115-1189 · Topology diversity × selection pressure, co-tuned (`homemaker-py-6zy`) — DONE (negative)

**§12 Phase 7 — scaling validation & residual reduction (post-c4c)** -- lines 1190-1198

- §12.1 · 1199-1249 · Larger-than-house benchmark: `maple-court` (`homemaker-py-leu.1`) — DONE
- §12.2 · 1250-1356 · Proportion-aware constructive seeding (`homemaker-py-leu.2`) — DONE (positive)
- §12.3 · 1357-1475 · Re-scoped 9gp: shape feasibility + reachability moves (`homemaker-py-9gp`)
- §12.4 · 1476-1558 · Construction granularity A/B (`homemaker-py-c3g`) — DONE (null) + a noise finding

**§13 Phase 8 — lowering the geometry/shape floor (`homemaker-py-erc`)** -- lines 1559-1566

- §13.1 · 1567-1624 · Diagnostic A: per-leaf shape-fail vs density/granularity (`homemaker-py-erc.1`) — DONE
- §13.2 · 1625-1686 · Diagnostic B: undersize-despite-slack localization (`homemaker-py-erc.2`) — DONE
- §13.3 · 1687-1779 · Experiment: leaf-sharing / multi-room leaves (`homemaker-py-erc.3`) — DONE
- §13.4 · 1780-1862 · Experiment: depth-balanced construction (`homemaker-py-erc.4`) — DONE (modest)
- §13.5 · 1863-1922 · Experiment: leaf-sharing × depth-balancing synergy (`homemaker-py-erc.7`) — DONE (synergy confirmed)
- §13.6 · 1923-1975 · Experiment: interior-O courtyard / light-well seeding (`homemaker-py-ld2`) — DONE (positive on dense floors)
- §13.7 · 1976-2037 · High-budget harbor floor probe — 71d go/no-go (homemaker-py-71d.1)
- §13.8 · 2038-2095 · Experiment: share-aware edge-too-long cap (`homemaker-py-hph`) — DONE (positive, harmless)
- §13.9 · 2096-2120 · Flip `share_edge_cap` default-ON + rebaseline §13.x floor (`homemaker-py-rq2`) — DONE
- §13.10 · 2121-2160 · Productionise leaf-sharing: per-code `share` + CLI wiring (`homemaker-py-x3b`) — DONE
- §13.11 · 2161-2246 · Residual diagnostic on the current full default construction stack (`homemaker-py-91f`) — DONE

**§14 Island model: multi-run recombination (`homemaker-py-psk`) — DONE (null)** -- lines 2247-2314

**§15 Leaf-sharing output honesty: unfold + polish auto-finish (`homemaker-py-3l6`) — DONE** -- lines 2315-2378

**§16 In-run leaf-share grain annealing — Schedule B (`homemaker-py-kpu`) — DONE (negative)** -- lines 2379-2466

**§17 Finish-time global cell→room collapse (`homemaker-py-94g`) — DONE (positive)** -- lines 2467-2540

**§18 Graded circulation-connectivity signal (`homemaker-py-qi6`) — DONE (negative)** -- lines 2541-2617

**§19 Geometry/topology repair for shape-intrinsic fails (`homemaker-py-7fm`) — DONE (negative)** -- lines 2618-2704

**§20 In-search global collapse (`homemaker-py-qpk`) — DONE (positive, size-dependent)** -- lines 2705-2821

**§21 Insert/relocate-circulation repair operator (`homemaker-py-8sh`) — DONE (mixed, kept off)** -- lines 2822-2896

**§22 bridge_circulation larger-N + weight confirmation (`homemaker-py-lj3`/`homemaker-py-qjg`) — DONE (null)** -- lines 2897-2952

**§23 Ruin-and-recreate LNS: rebuild a wing with the adjacency-aware constructor (`homemaker-py-f1d`) — DONE (positive, size-dependent)** -- lines 2953-3046

**§24 Ruin-and-recreate size-threshold sweep (`homemaker-py-y51`) — INCONCLUSIVE, no clean threshold** -- lines 3047-3103

**§25 2-opt local search past the collapse_global Jacobi plateau (`homemaker-py-9wi`) — DONE (positive, opt-in)** -- lines 3104-3150

**§26 Multi-use leaves / type superposition (`homemaker-py-9o5`/`xi7`/`b3v`) — DONE (negative), backfilled** -- lines 3151-3227

**§27 3D bubble-diagram adjacency fitness signal (`homemaker-py-mi7`) — DONE (negative)** -- lines 3228-3285

**§28 Default the `9wi` 2-opt polish on for finish-time collapse (`homemaker-py-cdl`) — DONE (positive)** -- lines 3286-3322

**§29 Beam/best-first search over adjacency-aware room placement (`homemaker-py-c94`) — DONE (inconclusive, mixed on harbor-house, null on programme-house)** -- lines 3323-3418

**§30 `c94` beam-width larger-N confirmation (`homemaker-py-e01`) — DONE (confirmed null)** -- lines 3419-3467

**§31 `y51` n=18 larger-N confirmation (`homemaker-py-xyu`) — INCONCLUSIVE, weak but not evaporated** -- lines 3468-3523

**§32 `health-centre` non-synthetic third example (`homemaker-py-9yx`) — CLEAN NULL** -- lines 3524-3590

**§33 Multi-use leaves as a permanent design goal (`homemaker-py-1s3`, §26 path b) — DONE (NULL, N=3 signal did not replicate)** -- lines 3591-3715

**§34 Spike: autodiff/gradient-based inner-loop ratio optimisation (`homemaker-py-2ax`) — DONE (negative, wall-clock)** -- lines 3716-3773

**§35 Stale leaf-share leak into `collapse_global`'s candidate valuation (`homemaker-py-iio`) — FIXED, retroactive impact partially assessed** -- lines 3774-3893

**§36 Expert review of the numeric/scoring path (`homemaker-py-zrx`) — DONE, 3 confirmed bugs filed** -- lines 3894-3935

**§37 Phase 9 plan: ground truth, exact evaluation, solver-directed search (`homemaker-py-2g7`)** -- lines 3936-3981

- §37.1 · 3982-4048 · `homemaker-py-2g7.3` hard/soft fail tiering — measured 2026-08-02
- §37.2 · 4049-4215 · `homemaker-py-2g7.4` shape-curve DP prototype — measured 2026-08-02, ACCEPTANCE: PASS
- §37.3 · 4216-4305 · `homemaker-py-2g7.1` plan→dom composer — implemented 2026-08-03, trace still open
- §37.4 · 4306-4405 · `homemaker-py-6xh` shape-curve DP wired as NM warm-start — measured 2026-08-03, ACCEPTANCE: PARTIAL
- §37.5 · 4406-4543 · `homemaker-py-wkh` DP-exact hard pre-filter — measured 2026-08-03, ACCEPTANCE: PARTIAL
- §37.6 · 4544-4648 · `homemaker-py-koo` multi-storey (below-link) support for the shape-curve DP — measured 2026-08-03, ACCEPTANCE: PASS

**§37.7 CP-SAT type assignment for a fixed tree (`homemaker-py-2g7.5`) — CLOSED: seeder-level positive in isolation, does NOT survive a full driver.search run; both flags stay default off** -- lines 4649-4783

**§37.8 Spike: graph-first construction — adjacency-realizing slicing trees / rectangular dualization (`homemaker-py-2g7.6`) — NO-GO** -- lines 4784-4896

**§38 The plateau is an objective-gradient problem, not a search problem (`homemaker-py-2v1`/`ssz`/`hxi`/`tdp`/`gvb`/`1i8`) — measured 2026-08-25** -- lines 4897-4911

- §38.1 · 4912-4941 · Zero-exposure leaves score a hard quality of 0 (`homemaker-py-ssz`)
- §38.2 · 4942-5010 · Buried circulation and outside space are negative-value (`homemaker-py-hxi`)
- §38.3 · 5011-5070 · The binding constraint is a frontage budget (`homemaker-py-tdp`)
- §38.4 · 5071-5085 · Crinkliness is mis-tiered as SOFT (`homemaker-py-gvb`)
- §38.5 · 5086-5098 · The missing-space cascade is weighted by YAML verbosity (`homemaker-py-1i8`)
- §38.6 · 5099-5127 · First repair attempt: three crinkliness modes — NOT SUFFICIENT ALONE
- §38.7 · 5128-5180 · Consequences for the Phase 9 plan
- §38.8 · 5181-5299 · What `ssz` actually was: the objective demands daylight for rooms that do not need it (`homemaker-py-ssz`)
- §38.9 · 5300-5361 · Two corrections to §38.8, and the measurement that matters (`homemaker-py-ssz`)
- §38.10 · 5362-5430 · The shipping fix: crinkliness is declared per space (`homemaker-py-ssz`)
- §38.11 · 5431-5502 · Owner's ruling on daylight, and the retraction of §38.8's headline
- §38.12 · 5503-5564 · The missing-space cascade was weighted by YAML verbosity (`homemaker-py-1i8`)
- §38.13 · 5565-5609 · health-centre's plot enlarged for a courtyard typology (`homemaker-py-7b7`)
- §38.14 · 5610-5679 · Toilet-to-sleeping adjacency declared where the brief supports it (`homemaker-py-3qj`)
- §38.15 · 5680-5735 · `constructive_topology` was ordered by memory address (`homemaker-py-fdp`)
- §38.16 · 5736-5786 · The staged harness re-scored under a different objective than it searched (`homemaker-py-4ok`)
- §38.17 · 5787-5847 · `n_workers` is an algorithm parameter, not noise (`homemaker-py-b8g`)
- §38.18 · 5848-5900 · The 1ph verdict re-verified: the iio bug could never have touched it (`homemaker-py-d86`)
- §38.19 · 5901-5951 · `collapse_insearch=True` re-validated under the current objective (`homemaker-py-ioe`)
- §38.20 · 5952-6043 · CP-SAT seeding re-measured deterministically: it loses (`homemaker-py-vjd`)
- §38.21 · 6044-6096 · Harbor A/Bs at n=3 could never have resolved their own margins (`homemaker-py-0wr`)
- §38.22 · 6097-6136 · A/Bs now report what their sample could resolve (`homemaker-py-tco`)
- §38.23 · 6137-6184 · The shape-curve DP now models leaf-sharing, so it can fire on real runs (`homemaker-py-tym`)
- §38.24 · 6185-6240 · The shape-curve warm-start cannot pay off as wired (`homemaker-py-v4s`)

**§39 Config audit: requirements that actively fight the engine (`homemaker-py-ju3`) — measured 2026-08-25** -- lines 6241-6250

- §39.1 · 6251-6266 · Per-room-spec satisfiability — CLEAN (negative result, recorded)
- §39.2 · 6267-6316 · Programme codes collide with the generic type namespace — SEVERE
- §39.3 · 6317-6373 · What shipped — tighten the matching rule at the source
- §39.4 · 6374-6400 · Re-baseline
- §39.5 · 6401-6465 · A false alarm on `2g7.5`, and the real bug underneath it — CORRECTED
- §39.6 · 6466-6509 · The second namespace: usage prefixes are still implicit — NOT clean
- §39.7 · 6510-6584 · `usage:` — access requirements become a declared attribute (`homemaker-py-sel`) — DONE
- §39.8 · 6585-6648 · `homemaker-py-2v1` connectivity weighting — MEASURED NULL, premise retracted
- §39.9 · 6649-6731 · Why `level N not connected` persists: the resize destroys it (`homemaker-py-yql`)
- §39.10 · 6732-6798 · Preserving constructed connectivity through the resize (`homemaker-py-3z0`) — NULL, and it reframes §39.9
- §39.11 · 6799-6869 · The frontage bound, computed correctly (`homemaker-py-tdp`) — shipped as a pre-flight check
- §39.12 · 6870-6991 · The cold-start re-baseline, and what it does to §38.7's acceptance test (`homemaker-py-ut5`)
- §39.13 · 6992-7139 · The crinkliness tail underflows, and what rescaling it can and cannot reach (`homemaker-py-9gj`)
- §39.14 · 7140-7278 · What the crinkliness factor actually rewards: surplus daylight, twice-charged (`homemaker-py-9gj`)
- §39.15 · 7279-7380 · The magic numbers, examined (`homemaker-py-u5q`)
- §39.16 · 7381-7460 · The crinkliness constant is Alexander 159, and that corrects §39.14/§39.15 (`homemaker-py-u5q`)
- §39.17 · 7461-7557 · The ground floor is the storey that fails, and §39.11 averaged it away (`homemaker-py-773`)
- §39.18 · 7558-7678 · Quality is a product over a variable number of questions (`homemaker-py-ecx`)
- §39.19 · 7679-7743 · A terrace must not be worth more per square metre than a room (`homemaker-py-ecx`)
- §39.20 · 7744-7801 · The native-vs-Perl parity tests have never run (`homemaker-py-118`)
- §39.21 · 7802-7858 · The Perl oracle is gone (`homemaker-py-118`)
- §39.22 · 7859-7943 · A corridor may be corridor-shaped (`homemaker-py-hxi`)
- §39.23 · 7944-8015 · Twice the corridor is twice as bad, and no worse (`homemaker-py-hxi`)
- §39.24 · 8016-8095 · `ratio_circulation` removed, and a sweep for the rest of its kind (`homemaker-py-hxi`)
- §39.25 · 8096-8176 · The rule Alexander states was off; the one he doesn't was on (`homemaker-py-hxi`)
- §39.26 · 8177-8221 · Two dead paths in the objective (`homemaker-py-dpt`)
- §39.27 · 8222-8318 · The `bk9` re-baseline, read against the right zero (`homemaker-py-bk9`)
- §39.28 · 8319-8451 · The `bk9` hard-fail drop, decomposed (`homemaker-py-bk9`)
- §39.29 · 8452-8501 · The eighth run, and which part of §39.28 survives it (`homemaker-py-bk9`)
- §39.30 · 8502-8585 · Eleven of twelve: one family, and it is not the one §39.28 named (`homemaker-py-bk9`)
- §39.31 · 8586-8710 · `bk9` complete: not a fail-count win, a hard-fail win (`homemaker-py-bk9`)
- §39.32 · 8711-8769 · Every result carries the objective it was measured by (`homemaker-py-bk9`)
- §39.33 · 8770-8844 · The runner did not commit once in twelve runs (`homemaker-py-bk9` fallout, needs a bead)
- §39.34 · 8845-8877 · Where `bk9` leaves the objective (handoff)
- §39.35 · 8878-9000 · The soft `width` rise is not corridors, and twelve runs cannot resolve it anyway (`homemaker-py-413`)
- §39.36 · 9001-9064 · The straightening pass was lost, not the need for it (`homemaker-py-bzv`)
- §39.37 · 9065-9209 · A room's width: the ruling is right, the first implementation was not (`homemaker-py-2f1`)
- §39.38 · 9210-9289 · Orthogonality is free: the second division ratio is already pinned (`homemaker-py-32t`)
- §39.39 · 9290-9347 · A code's spelling decided the collapse (`homemaker-py-s34`)
- §39.40 · 9348-9450 · Orthogonal division, implemented and measured (`homemaker-py-32t`)
- §39.41 · 9451-9526 · Harbor-house: the factor is worthless, the geometry is unproven (`homemaker-py-32t`)
- §39.42 · 9527-9572 · The objective stamp did not name the whole objective (`homemaker-py-32t`)
- §39.43 · 9573-9625 · The verifier could only ever check half the table (`homemaker-py-32t`)
- §39.44 · 9626-9827 · The orthogonal sweep was dead on arrival (`homemaker-py-w49`, `homemaker-py-nq3`)
- §39.45 · 9828-9876 · "GIT FAILED" named the remote, not the failure (`homemaker-py-os2`)
- §39.46 · 9877-9927 · Orthogonal division is adopted on architecture, not on fail counts (`homemaker-py-32t`)
- §39.47 · 9928-9975 · The sweep decomposition, ready before the sweep lands (`homemaker-py-32t`)
- §39.48 · 9976-10036 · `edge too long` is coherent, and is being removed anyway (`homemaker-py-2ww`)
- §39.49 · 10037-10114 · The orthogonal-division baseline, complete (`homemaker-py-32t`)
- §39.50 · 10115-10188 · Two criteria retired: `edge too long` and `quality_perpendicular`
- §39.51 · 10189-10235 · The stamp could not see the working tree (`homemaker-py-jui`)
- §39.52 · 10236-10289 · A terrace over a courtyard is air (`homemaker-py-xhw`)
- §39.53 · 10290-10350 · The owner's layout exists, scores best, and is found one run in six (`homemaker-py-xhw`)
- §39.54 · 10351-10440 · What actually pays for the third storey, and a void that counts as outdoors
- §39.55 · 10441-10521 · Two rulings: the area floor goes, and a void costs nothing
- §39.56 · 10522-10606 · Three rulings, and the adjacency defect reinstated
- §39.57 · 10607-10694 · The overall-size rule is redundant *and* blind — delete it
- §39.58 · 10695-10799 · The area rule as a *cap* — and the retraction of §39.57's "inert"
- §39.59 · 10800-10863 · The four usable-space rulings, landed
- §39.60 · 10864-10903 · The pause, and the discipline it needs
- §39.61 · 10904-10947 · `decompose_coldstart.py` claimed a reproduction it had stopped performing
- §39.62 · 10948-11064 · The operator §39.53 asked for, and the second half of the relation it missed (`homemaker-py-e4r`)
- §39.63 · 11065-11151 · The objective stamp named two of the five files that decide a score
- §39.64 · 11152-11255 · The seeders were still crediting voids the scorer had stopped crediting (`homemaker-py-q4t`)
- §39.65 · 11256-11350 · A row recorded which objective scored it and nothing about the search that produced it — and then `support_outside` became the default
- §39.66 · 11351-11432 · The merge minted a sahn the configuration had switched off (`homemaker-py-4e7`)
- §39.67 · 11433-11616 · Review of the `2g7.7` LLM-repair plan (`homemaker-py-8oq`)
- §39.68 · 11617-11718 · Crinkliness is not mis-tiered: `gvb`'s premise fails twice over, and `k54`'s own gate has resolved against it
- §39.69 · 11719-11834 · What only existed on the owner's machine, and a prune of what a session inherits (`homemaker-py-9dm`)
- §39.70 · 11835-12023 · The owner's three storeys, hand-built: 1.89x the best evolved layout, and the composer could not express it (`homemaker-py-xhw`, `homemaker-py-2g7.1`)
- §39.71 · 12024-12153 · The operator for the storey the search would not add (`homemaker-py-v2k`), and the three things it cannot repair
- §39.72 · 12154-12266 · How much of the corpus loses its stair to the exact-path rule, and why relaxing it is not a one-line change (`homemaker-py-m4d`)
- §39.73 · 12267-12346 · Which operators throw the staircase away (`homemaker-py-t7q` step 1), and the one it caught in my own
- §39.74 · 12347-12465 · The half of `homemaker-py-t7q` that does not need a box: a repair operator, a measured null inside it, and one guard that is a defect fix
- §39.75 · 12466-12533 · The merged storey, opened: subdividing back into alignment, a ranking that measured badly, and the default flipped on §39.65's ruling
- §39.76 · 12534-12658 · What the ratio solver was solving for, and the declaration it was not reading (`homemaker-py-r8c`)
- §39.77 · 12659-12730 · A drawing I took for a human plan, and it was our own output (`homemaker-py-2g7.1`)
- §39.78 · 12731-12825 · The shape-curve DP's verdict is not exact, and neither cause is the rectangle approximation (`homemaker-py-ekc`)
- §39.79 · 12826-12893 · The operator census, widened: the structural invariants hold, and one operator cannot fire
- §39.80 · 12894-12979 · What omitting a required room costs, and why it is not one number (`homemaker-py-3i3`)
- §39.81 · 12980-13034 · The support_outside A/B: it clears the fail, and it does not pay for itself (`homemaker-py-3wq`)
- §39.82 · 13035-13109 · The `07b2058+orth` re-baseline, and three ways the tooling failed on a new machine
- §39.83 · 13110-13171 · What a missing room is worth, priced on the one real case (`homemaker-py-3i3`)
- §39.84 · 13172-13255 · A missing instance exempted its siblings from the checks (`homemaker-py-3i3`)
- §39.85 · 13256-13306 · The ruling, checked on every programme: it holds, by 14 to 152 fail-lines (`homemaker-py-3i3`)
- §39.86 · 13307-13366 · Why `support_outside` does not pay: its terrace is cut too narrow to pass (`homemaker-py-ek07`)
- §39.87 · 13367-13418 · Outdoor width: a six-foot balcony, not three metres (`homemaker-py-6ses`)
- §39.88 · 13419-13527 · The rectangle-frame pivot, measured before committing to it (`homemaker-py-8b2u`)
- §39.89 · 13528-13556 · The `1a24b6a+orth` sweep: §39.84's expectations checked
- §39.90 · 13557-13629 · A shape score for cropped cells: vertex count is the wrong test (`homemaker-py-8b2u.4`)
- §39.91 · 13630-13725 · The support_outside A/B under the tiered comparator: all its effect gone, and §39.86's cheap lever with it (`homemaker-py-ek07`)
- §39.92 · 13726-13760 · Evolved layouts reach IFC through homemaker-addon (`homemaker-py-8b2u.5`)
- §39.93 · 13761-13802 · The `place` trade re-measured at 2.3 m: the same trade, a little cheaper (`homemaker-py-ek07`)
- §39.94 · 13803-13882 · Format v2 reads and writes; the round trip found three things the scorer reads that are not geometry (`homemaker-py-8b2u.2`)
- §39.95 · 13883-13976 · Two of §39.94's three, fixed on the owner's rulings: daylight counted once, and stairs fitted whichever way is best (`homemaker-py-khgi`, `homemaker-py-8b2u.6`)
- §39.96 · 13977-14013 · The merge hands the wall up: the last of §39.94's three (`homemaker-py-3tzk`)
- §39.97 · 14014-14083 · Four more ways to re-describe a building, and crinkliness re-measured without the phantom walls
- §39.98 · 14084-14120 · The stale ratio in a live search: `undivide` moves a wall upstairs one time in six (`homemaker-py-3tzk`)
- §39.99 · 14121-14169 · The native geometry core, and a calibration that held on one corpus (`homemaker-py-8b2u.4`)
- §39.100 · 14170-14238 · Three more rulings: the wall above stays, listing order decides nothing, and a boxed-in core is a straight flight (`homemaker-py-3tzk`, `rwwv`, `8b2u.7`)
- §39.101 · 14239-14298 · Width, proportion and adjacency for a cell that need not be a quad (`homemaker-py-8b2u.4`)
- §39.102 · 14299-14356 · Width and proportion are read from the biggest fitted rectangle (`homemaker-py-8b2u.4`)
- §39.103 · 14357-14427 · The native tree: a v2 file scored as itself (`homemaker-py-8b2u.4`)
- §39.104 · 14428-14507 · The search runs on native trees, with the genes it always had (`homemaker-py-8b2u`)
- §39.105 · 14508-14607 · A score at half the cost, and one saving declined (`homemaker-py-8b2u.9`, `.10`, `.11`)
- §39.106 · 14608-14695 · Two readings taken while the box was busy: `core_undivide`, and the shape-curve DP on a native tree (`homemaker-py-w4e`, `8b2u.14`)
- §39.107 · 14696-14754 · How many trees draw one layout, and what that does and does not cost today (`homemaker-py-8b2u.15`)
- §39.108 · 14755-14791 · Outdoor slivers, re-measured at three later corpora: not reproduced (`homemaker-py-jak`)
- §39.109 · 14792-14914 · Sizing by arithmetic: most of the way on a cold topology, and a step backwards on a child (`homemaker-py-8b2u.12`, `.13`)
- §39.110 · 14915-14971 · What a child's 80 evaluations buy: three or four wins in eleven (`homemaker-py-8b2u.20`)
- §39.111 · 14972-15055 · The 2x2 at one objective: the terrace fail is rare now, and nothing separates the comparators (`homemaker-py-qkp0`)
- §39.112 · 15056-15101 · Three owner rulings on §39.105-§39.111's open questions (2026-10-07)
- §39.113 · 15102-15121 · The stair shaft is a cell made by division, like every other cell (owner's ruling, `homemaker-py-8b2u.16`)
- §39.114 · 15122-15181 · Would a canonical genome help? What the run logs say (`homemaker-py-8b2u.15`)
- §39.115 · 15182-15248 · Rulings on outdoor value and on the briefs, and a kit for drawing a design by hand (`homemaker-py-ecx`, `5nw`, `2g7.1`)
- §39.116 · 15249-15311 · A terrace is worth more than a garden; circulation is outside the rule; and the number is not yet settled (`homemaker-py-ecx`)
- §39.117 · 15312-15341 · The terrace is worth 120, until daylight scores outdoor space (owner's ruling, `homemaker-py-ecx`)
- §39.118 · 15342-15401 · A solver pass does make a better seed (`homemaker-py-8b2u.21`, container half)
- §39.119 · 15402-15508 · Pitched roofs for the IFC export (`homemaker-py-6e5u`)
- §39.121 · 15509-15588 · `child20`: a shorter inner loop loses the staircase one run in six (`homemaker-py-8b2u.20`)
- §39.122 · 15589-15625 · Two ideas set aside, and what would bring each back (owner's ruling, 2026-10-08; `homemaker-py-8b2u.20`, `homemaker-py-ek07`)
- §39.120 · 15626-15756 · The book of moves, read: specialists do what they say, a book adds little on programme-house, and `place_missing` plays where nothing is missing (`homemaker-py-urzf`)
- §39.123 · 15757-15828 · Where a move is played: aimed at a failing cell it removes a fail five times as often, and `undivide` carries most of it (`homemaker-py-urzf`)
- §39.125 · 15829-15956 · A stair gets a cell type of its own, `E` (owner's ruling, 2026-10-08; `homemaker-py-y4p4`)
- §39.124 · 15957-16025 · The pair census: on a design the search has finished with, no move and no pair of moves removes a fail (`homemaker-py-urzf`)
- §39.126 · 16026-16046 · The recorder names a child's parents; and why the recordings stay text files (`homemaker-py-urzf`)
- §39.127 · 16047-16135 · `E` built: no committed score moves, and the first census caught the new move (`homemaker-py-y4p4.1`)
- §39.128 · 16136-16211 · Storey height as something the search tunes: the variable alone does nothing, the jump does (`homemaker-py-y4p4.2`)
- §39.129 · 16212-16274 · `w4e`: the repaired `core_undivide` changes nothing a search can show -- and every A/B in the queue has been re-running the same control (`homemaker-py-w4e`)
- §39.131 · 16275-16368 · A light well: every one the move is willing to cut leaves fewer fails, and it is willing to cut few (`homemaker-py-evxm`)
