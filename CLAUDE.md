# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

### Running `bd` in a remote agent container

**A container restart removes `bd` entirely.** It is a Go binary installed into
`/root/go/bin`, not part of the repo, so it does not survive. `bd create` then
fails *silently* under `&&` chaining and the work looks done — that is how a
bead id that never existed reached DESIGN.md once (§39.53). Check `command -v
bd` before relying on it, and if it is gone, append the record straight to
`.beads/issues.jsonl` (it is plain JSONL, git-tracked, and is the thing that
actually carries issue state — see below). Match an existing record's keys
exactly and re-parse the file afterwards.

**`bd` is installed at `/root/go/bin/bd`, and that directory is not on `PATH`.**
So `command -v bd` finds nothing and a bare `bd` reports `command not found`,
which looks exactly like "beads is not available here". It is available. Run
`export PATH="$PATH:/root/go/bin"` first, and never conclude beads is missing
from `command not found` without checking `/root/go/bin`.

**Issues persist; memories do not.** `.beads/issues.jsonl` is git-tracked, so
`bd export -o .beads/issues.jsonl` followed by a commit is what actually carries
issue state out of a container. The Dolt database under `.beads/embeddeddolt/`
is gitignored, `bd export` omits memories unless asked, and `sync.remote` is a
`git+ssh://` URL that an agent container cannot use — containers have no `ssh`
binary. **A `bd remember` written in a container therefore reaches nobody.**
Put anything durable in `DESIGN.md` (findings) or this file (how to work here),
and leave `bd remember` for sessions running on the owner's own machine.

### Room-code namespaces (DESIGN.md §39.4/§39.6)

Leaf types share a first character across three namespaces:

- **`C` / `O` / `S`** — generic structural types (circulation / outside / sahn),
  uppercase, reserved. A programme code spelled exactly one of these is rejected
  at load.
- **programme room codes** — lowercase, may start with *any* letter. The generic
  tests match `C`/`O`/`S` exactly, so `cr1` is a room, not circulation.
- **`usage:`** — every space declares its access-requirement class
  (`living`/`kitchen`/`bedroom`/`toilet`/`utility`/`none`), mandatory, no
  fallback (DESIGN.md §39.7). A code's spelling decides nothing to the SCORER:
  `name:` is free text, `usage:` drives behaviour, and
  `test_scoring_is_invariant_under_programme_code_spelling` holds the line.
  **Two first-character tests do survive in `operators.py`'s constructive
  adjacency heuristic** (`homemaker-py-1v7`) — they do not affect scoring, but
  they drop and mis-match adjacency requirements while building seeds. Do not
  add more, and do not read this section as saying none exist.

When adding or editing a programme, run
`python experiments/audit_programme_config.py` — it reports reserved-name
collisions, the usage class each code picks up, and per-room-spec satisfiability.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```

   **There is one remote: `origin`, which is
   `github.com/brunopostle/homemaker-layout`.** Everything — this workflow, the
   cold-start runner, agent containers — pushes there and nowhere else. That is
   the record, and `git status` saying "up to date with origin" means it.

   The project was briefly also on `hub.postle.net`; that remote is gone. The
   episode is worth one line of memory, because it cost a week: the runner
   pushed results to one host while an agent polled the other and reported,
   truthfully from where it stood, that nothing had arrived. **If a second
   remote is ever added, give it its own name and never make it a second push
   URL of `origin`** — two hosts answering to one name is the failure mode, and
   agent containers have no `ssh` binary, so a host reachable only over ssh on
   `origin`'s push path turns every agent push into a permanent half-failure.
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->


## Build & Test

```bash
pip install -e .
pytest
```

## Architecture Overview

homemaker-layout is a Python successor to the Perl [Urb](../urb) project. It
represents a building as a binary slicing tree where leaves carry **target
dimensions** from the programme and division ratios are **solved bottom-up**
(inverting Urb's top-down approach). The evolutionary search explores topology,
types, and adjacency only.

Key modules:
- `dom.py` — read/write Urb `.dom` YAML into a `Node` tree
- `geometry.py` — faithful port of Urb's top-down geometry
- `programme.py` — parse `patterns.config` space requirements
- `solver.py` — bottom-up ratio solve (scipy)
- `shapecurve.py` — Otten/Stockmeyer shape-curve DP: exact size/width/proportion feasibility for a frozen topology, any storey count (DESIGN.md §37.2/§37.4-§37.6); used as `driver._evaluate`'s NM warm-start/hard pre-filter
- `cpsat.py` — exact room-code-to-leaf labelling via OR-Tools CP-SAT for a fixed topology (DESIGN.md §37.7); replaces `operators._assign_adjacency_aware`'s greedy/beam room placement behind `assign_solver="cpsat"`, and powers the `operators.mutate_reassign` in-search repair operator
- `fitness.py` — native Python fitness evaluator (replaces Perl oracle)
- `fitness_cmd.py` — `homemaker-fitness` CLI entry point
- `collapse_cmd.py` — `homemaker-collapse` CLI: finish-time global cell→room collapse (94g)
- `graph.py` — leaf-adjacency graph for programme-driven fitness checks
- `genome.py` — topology genome: base-floor tree + per-storey deltas
- `operators.py` — high-locality mutation and subtree crossover
- `innerloop.py` — ratio optimisation inner loop (Nelder-Mead / CMA-ES)
- `driver.py` — memetic search outer loop
- `evolve.py` — `homemaker-evolve` CLI entry point
- `bubble.py` — 3D bubble-diagram adjacency fitness-signal prototype (DESIGN.md §27, `mi7`); validated NULL, not wired into `fitness.py` — reference only, do not build on without a new formulation

### `HOMEMAKER_ORTHOGONAL_DIVISION` — a runtime switch that changes the objective

`geometry.py` reads this from the environment at import. With it set to `1`,
`coord_b` places every division parallel or perpendicular to the plot's longest
boundary (DESIGN.md §39.38/§39.40/§39.44) instead of inheriting the plot's skew.
**It changes the geometry of every layout, so it is a different objective**, and
it leaves no commit — which is why the objective stamp carries a `+orth` suffix
(§39.42).

Three consequences that bite:

- **Score a `+orth` artefact with the switch on, or you get a different
  layout.** `verify_results_table.py` handles this per row; if you score by hand,
  set the variable.
- Corpora on disk: `coldstart-1138ff1+orth-*` was measured with it **on** but is
  at a **superseded objective** (§39.50 retired two criteria after it). The older
  `coldstart-055d710-*` and `coldstart-99c85ec-*` were measured with it **off**,
  at different objectives again. **There is currently no corpus at the live
  objective** — one is being swept.
- It defaults **off**, so a bare `pytest` or `homemaker-fitness` run is the
  non-orthogonal objective.

### Experiment tooling you will want before writing your own

- `experiments/run_coldstart_baseline.py` — the 12-run sweep. Refuses to start
  if the table already holds rows at this objective and budget (`--resume` runs
  only what is missing, `--restart` drops those rows first, §39.44), and refuses
  if `fitness.py` or `geometry.py` are uncommitted, since the stamp comes from
  `git log` and would name the commit before the edits (§39.51).
- `experiments/verify_results_table.py` — every row in `coldstart_baseline.tsv`
  re-scored from its committed artefact. Run it after any sweep and after any
  change to the objective, where it should report every row skipped (§39.43).
- `experiments/decompose_coldstart.py` — per-programme deltas, fail-family
  census, and the MDD beside every verdict. Refuses to report an incomplete
  sweep; `--partial` marks it PROVISIONAL (§39.47).
- `experiments/ab_report.py` — the paired statistics the above borrows. **Use
  it rather than computing a mean difference by hand**: this project has twice
  reported margins its sample could not resolve (§38.19/§38.21, §39.47).

## Conventions & Patterns

### Scoring .dom files

Use the native `homemaker-fitness` command. Like the old `urb-fitness.pl`, you
**must `cd` to the directory containing the `.dom` file first** — the tool
resolves `patterns.config`, `costs.config`, and writes `.score`/`.fails`
relative to `cwd`:

```bash
cd /home/bruno/src/homemaker-layout/examples/programme-house
homemaker-fitness cf0b8a77e8b2325f92a7e7d150184a55.dom
```

The score is written to `<file>.dom.score` and failures to `<file>.dom.fails`; the numeric score is also printed to stderr.

`fitness.py` is the **only** evaluator. The Perl oracle it was ported from —
`oracle.py`, `urb-fitness.pl`, and the parity tests against them — is gone
(DESIGN.md §39.21). Those parity tests had never actually run: no oracle
`.score` was ever committed, so on a clean checkout every case skipped, and the
only cases that ever executed compared the native scorer with itself (§39.20).

The corollary matters when reading the objective: a constant or a rule that
looks odd is **not** thereby validated by "Urb did it this way". Several
defects found in §39 were carried straight over from the Perl — see §39.19 on
`value_supported`, and `homemaker-py-hxi` on circulation, which the owner has
ruled needs fixing.

## Where things stand (2026-09-24)

Read this before planning work; then `bd ready` for the queue and DESIGN.md
§39.44–§39.51 for the detail.

**A re-baseline sweep is running** at objective `c836457+orth`, on an 8-core box
separate from the laptop, started 2026-09-24. Until it lands there is **no
corpus at the live objective**: `verify_results_table.py` reports every row
skipped, which is §39.43's designed answer to an objective change, not a fault.

**While it runs, `src/` is frozen** (see the last section). `experiments/`,
`tests/` and the docs are safe to change.

What happened, in order:

1. The orthogonal-division baseline completed: twelve of twelve at
   `1138ff1+orth`, no failed runs, every row verified (§39.49). Orthogonal
   division is adopted as an **architectural requirement**, needed whether or
   not it costs fails (§39.46) — do not reopen that as a fitness question. The
   fail-count comparison against `bk9` was both underpowered at N=12 and
   confounded, and supports no conclusion either way.
2. Then §39.50 retired two criteria: `edge too long` / `outside edge too long`
   (with `_edge_cap` and the `share_edge_cap` lever) and `quality_perpendicular`
   (nulled in `CONF_DEFAULTS`, so no new programme inherits it). Both were owner
   rulings. Wall cost is bit-for-bit unchanged; only the fail set moved.
3. Then §39.51 closed the gap that `objective_commit` could not see the working
   tree. The runner now refuses to start when the objective's own source is
   uncommitted. It also un-skipped three guards that had keyed on *rows at the
   current objective* and so stopped running for the whole window between an
   objective change and its re-baseline.

Scoring the §39.49 artefacts under the new objective gives 284 → 256 fails,
exactly the 28 edge-too-long fails removed. **That is not a new baseline** — the
search would find different layouts under the new objective. It is only a check
that the change did what it said.

### The re-baseline (running since 2026-09-24; re-read this before restarting it)

```bash
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/run_coldstart_baseline.py \
    --budget 500000 --seeds 3 --slots $(nproc)
```

**Set `--slots` to the core count** (it defaults to 4, the old laptop). Each run
is a single-worker `homemaker-evolve`, so slots are the only parallelism.
**Pin the BLAS threads** — nothing in the repo does it, and without it every
slot's scipy tries to use every core, which at 8 slots can be slower than 4.

Makespan, simulated against the measured per-run times of the `1138ff1+orth`
sweep (4-core-laptop numbers, so upper bounds on a faster box):

| slots | makespan |
|---|---|
| 4 | 118 h |
| 8 | 63 h |
| 12 | 60 h |

436 core-hours of work in total. 8 slots is within ~3 h of the perfect-packing
bound, which is set by maple-court s0 alone — the longest single run — so more
slots than cores buys nothing. **Run all twelve on one machine**: the
single-worker design avoids `homemaker-py-b8g`, but that does not make results
portable across CPUs, and a baseline split over two boxes is not internally
comparable.

**The stamp is not `HEAD`** — it is the last commit that touched
`fitness.py` or `geometry.py`, which is usually an older commit, because most
work does not touch the objective. Getting this wrong once already sent someone
looking for the wrong string. Derive it, do not guess:

```bash
git log -1 --format=%h -- src/homemaker_layout/fitness.py \
                          src/homemaker_layout/geometry.py
```

and confirm the runner's first line matches, with `+orth` appended.

`--resume` picks up only what is missing if it is interrupted, and **do not edit
`src/` while it runs** (see below). A dirty objective source no longer needs
watching for: the runner refuses to start over uncommitted `fitness.py` or
`geometry.py`, before the stamp is taken, with no override (§39.51). A dirty
`src/` file that is *not* the objective warns and continues.

The new sweep is not comparable to §39.49's at the fail-count level — two
criteria fewer (§39.12 clause 3). Expected, not a problem to engineer around.

### After that, crinkliness

It was 39% of the fail set before this change and is a larger share now that 28
fails went. §39.31 established that 69% of its residual sits at `crink == 0` —
fully buried leaves, where no rescaling of the factor can order anything.
`homemaker-py-k54` and `homemaker-py-gvb` hold the analysis.

### Known limits of the orthogonal geometry

`homemaker-py-ao9`: a slicing cut straightens only the wall family it creates;
the crossing family is inherited from the plot boundary, so some internal walls
still run a few degrees off. Measured at 3.3° on programme-house. The real fix
is `homemaker-py-bzv`, Urb's lost `Straighten()` pass, which moved corners
rather than cuts. Retiring `quality_perpendicular` means nothing measures that
residual any more — an accepted trade (the geometry is the fix, not the score),
recorded so it stays a decision rather than becoming an oversight.

### The standing principle, in the owner's words

> We want to do the right thing; chasing scores is of no value if they depend on
> flawed logic.

Applied repeatedly through §39: `perpendicular` scored what no operator could
fix, `width` asked a third question of two degrees of freedom, circulation was
charged two questions nobody asked. **But not every odd-looking rule is
defective** — §39.48 records a case where the measurement was right and the
model in the reviewer's head was wrong. When a long-standing rule looks
incoherent, the likeliest explanation is still that someone had a reason; ask
before writing it up. And §39.50 retired a rule that was working correctly,
because being correct is not the same as belonging in this objective.

### Never run a sweep and edit `src/` at the same time

Worker runs are separate `homemaker-evolve` processes reading the editable
install, and the objective stamp is read once at start-up. A mid-sweep commit to
`src/` silently splits the sweep in two. `experiments/` and `tests/` are safe to
change while one runs; `src/` is not.
