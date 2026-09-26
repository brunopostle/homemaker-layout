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

**Assume `bd` is absent, not merely off `PATH`.** A container restart removes it
— it is a Go binary, not part of the repo. The older advice here said it lives
at `/root/go/bin/bd` and only needs `export PATH="$PATH:/root/go/bin"`; that is
worth trying first, but on 2026-09-25 **`/root/go` did not exist at all**, so
treat "check `/root/go/bin`" as one possibility rather than the answer. Either
way `bd create` fails *silently* under `&&` chaining and the work looks done —
that is how a bead id that never existed reached DESIGN.md once (§39.53).

So: `command -v bd || ls /root/go/bin`, and if it is genuinely gone, either
install it (below) or append the record straight to `.beads/issues.jsonl` —
plain JSONL, git-tracked, and the thing that actually carries issue state. Match
an existing record's keys exactly, **preserve the other lines byte-for-byte**
(rewriting the file with `json.dumps` reorders keys on every record and churns
all ~200 lines for nothing), and re-parse the file afterwards.

**Installing it, if you need it.** `go install` alone is not enough — the build
fails on `unicode/uregex.h`, a cgo dependency of Dolt's regex library:

```bash
apt-get install -y libicu-dev          # the missing piece; you are root
go install github.com/steveyegge/beads/cmd/bd@v1.3.0
export PATH="$PATH:/root/go/bin"
bd metrics off                          # it phones home by default
```

Roughly 10 minutes and ~200 MB, and it dies with the container.

**But installing it does not give you a working database**, and this is the part
worth reading before you spend the ten minutes. `bd bootstrap` clones the remote
Dolt DB and then refuses it: the remote is at schema **v32** and bd 1.3.0 wants
**v66**. bd will not auto-migrate a remote-backed clone, because migrating one
independently forks the schema and `bd dolt pull` can no longer merge. It asks
for exactly ONE designated migrator — **that is the owner's call and not an
agent's**, since `bd migrate --force && bd dolt push` rewrites the shared issue
DB and any older `bd` stops reading it.

A local-only DB does work (`bd init --prefix homemaker-py` with no remote, then
`bd import .beads/issues.jsonl`) and loads all the issues correctly. The catch
is that `bd export` rewrites every line — key ordering and dependency-list
ordering — so the first export lands a ~200-line diff on a git-tracked file. The
round-trip was verified **semantically lossless** (zero records differ; four
closed issues gain a `closed_at` they were missing), so the churn is cosmetic —
but it is still churn, and **the owner's standing preference is to leave bd
unconfigured in containers and hand-edit the JSONL.** Do that unless told
otherwise.

**Issues persist; memories do not** — but not for the reason this file used to
give. `.beads/issues.jsonl` is git-tracked, so an export followed by a commit is
what carries issue state out of a container. The Dolt database under
`.beads/embeddeddolt/` is gitignored and `bd export` omits memories unless
asked. This file previously added that `sync.remote` is a `git+ssh://` URL "an
agent container cannot use — containers have no `ssh` binary". There is indeed
no `ssh` here, **but `bd bootstrap` reached that URL and cloned from it anyway**
— bd resolves `git+ssh://` over HTTPS itself. So the ssh premise is wrong; what
actually stops a container is the schema gate above. Either way `bd remember`
from a container is not something to rely on: put durable findings in
`DESIGN.md` and durable working knowledge here.

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


## Non-interactive shell commands

**Always pass the non-interactive flag** to file operations. `cp`, `mv` and `rm`
may be aliased to `-i` on some systems, and an agent then hangs forever waiting
for a y/n it cannot see.

```bash
cp -f src dst      rm -f file        rm -rf dir        cp -rf src dst
apt-get -y install ...               ssh/scp -o BatchMode=yes
```

(Moved here from `AGENTS.md` by §39.69: most of that file is a bd-managed block
that `bd setup` rewrites, so hand-written guidance kept there can be overwritten.)

## Build & Test

```bash
pip install -e .
pytest
```

## Architecture Overview

homemaker-layout is a Python successor to the Perl **Urb** project
(`git clone https://bitbucket.org/brunopostle/urb.git` — see *The Perl Urb
source* below; `../urb` in older text was the owner's checkout, not a path that
exists for anyone else). It
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
- `compose.py` / `compose_cmd.py` — `homemaker-compose`: SVG trace + boundary `.dom`
  -> full slicing-tree `.dom` (DESIGN.md §37.3). The only path to a scored HUMAN
  design, and the one that exists is
  `examples/programme-house/hand-3storey.{svg,boundary.dom,dom}` (DESIGN.md §39.70,
  rebuilt by `experiments/build_hand_3storey.py`); every other non-empty `.dom` in
  the repo is evolution output (`homemaker-py-2g7.1`). **A multi-storey trace is
  not a stack of independent storeys**: an upper storey's `rotation` and the
  ratios of a path already divided below are dead fields that `geometry` reads
  from the storey below, so `compose` writes the axis where the engine reads it
  and raises `InheritedCut` for a trace that contradicts the wall downstairs
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
- Corpora on disk, newest first. `coldstart-c836457+orth-*` is the **newest
  complete** one (12/12, all verified) and the right comparison for the next
  sweep, but §39.59 moved the objective hours after it finished, so it is one
  generation behind. `coldstart-1138ff1+orth-*` is two behind (§39.50 retired
  two criteria after it); both were measured with the switch **on**. The older
  `coldstart-055d710-*` and `coldstart-99c85ec-*` were measured with it **off**,
  at different objectives again — do not compare to these at all.
  **There is no corpus at the live objective and no sweep is running**; the box
  is unavailable until ~2026-09-29. Do not trust a stamp written out here: this
  sentence named `691cc21+orth` until §39.66 moved the objective under it, and
  it had gone stale once before that. Derive today's with the command under
  *Current state* below — it is two lines and it cannot be wrong.
- It defaults **off**, so a bare `pytest` or `homemaker-fitness` run is the
  non-orthogonal objective.

### Experiment tooling you will want before writing your own

- `experiments/run_coldstart_baseline.py` — the 12-run sweep. Refuses to start
  if the table already holds rows at this objective and budget (`--resume` runs
  only what is missing, `--restart` drops those rows first, §39.44), and refuses
  if any file in `OBJECTIVE_SOURCES` is uncommitted, since the stamp comes from
  `git log` and would name the commit before the edits (§39.51). Every row also
  carries `search_commit` and `search_config` (§39.65) — the search the run used,
  the second resolving against `experiments/results/search_configs/<hash>.json`.
  Rows from before that read `-`.
- `experiments/verify_results_table.py` — every row in `coldstart_baseline.tsv`
  re-scored from its committed artefact. Run it after any sweep and after any
  change to the objective, where it should report every row skipped (§39.43).
- `experiments/decompose_coldstart.py` — per-programme deltas, fail-family
  census, and the MDD beside every verdict. Refuses to report an incomplete
  sweep; `--partial` marks it PROVISIONAL (§39.47). **Its rows come from the
  table; its family census is re-scored with today's code.** Those agree only
  until the objective moves, after which it prints a banner naming every row
  that no longer reproduces (§39.61) — read it, because the percentages shift
  by about a point and look perfectly plausible either way.
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
cd examples/programme-house          # from the repo root
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

## Current state — derive it, do not trust this file

This file rots. Two commands and one directory listing give you today's truth;
prefer them over any sentence here.

```bash
# the objective stamp (and whether the objective's own source is dirty)
python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit(), m.search_commit(), m.search_config()[0])"

# the queue — bd if it is installed, otherwise the JSONL is the record
bd ready 2>/dev/null || python -c "import json;[print(r['id'],'P%s'%r['priority'],r['title'][:80]) for r in sorted((json.loads(l) for l in open('.beads/issues.jsonl') if l.strip()), key=lambda r:(r.get('priority',9),r['id'])) if r['status']!='closed']"

# which corpora exist, newest last
ls examples/*/coldstart-*.dom | sed 's/.*coldstart-//;s/-500000.*//' | sort -u
```

**DESIGN.md is the history; this file is how to work here.** For what changed
and why, read DESIGN.md from §39.44 forward — it is in commit order and every
number in it carries the objective stamp it was measured at. Do not reconstruct
that narrative here: a dated "where things stand" section in a file nobody prunes
becomes a second, competing history, which is §39.63's two-copies failure in
prose. (§39.69 pruned exactly that.)

**Standing facts that are not dated:**

- **There is normally no corpus at the live objective.** The objective has moved
  faster than the 436-core-hour sweep can follow, so `verify_results_table.py`
  reporting every row skipped is §39.43 working, not a fault. Compare a new sweep
  only to a corpus at the same stamp, and never across the `+orth` switch
  (§39.12 clause 3).
- **The stamp can move without the objective changing.** It is
  `git log -1 -- OBJECTIVE_SOURCES`, so a pure rename in one of those five files
  moves it (§39.65 is the worked example). Re-score before concluding anything
  changed.
- **A sweep needs the box.** Anything calling `homemaker-evolve` at a real budget
  (a single 500k run is hours) cannot be done in a container. Check whether a box
  is available before planning a measurement; if it is not, the beads marked as
  needing it are genuinely blocked.

### What a container can and cannot do

**Can**, so none of this is ever blocked:

- the full test suite — `pytest`, ~6 minutes, 600 tests at the time of writing;
- scoring committed artefacts — `homemaker-fitness`, or `Fitness.score_with_fails`
  in a loop over the twelve `.dom` files, seconds per file. Most measurements in
  DESIGN.md §39.54 onward were made this way;
- every diagnostic in `experiments/` that reads committed artefacts;
- optimising the division ratios of a FIXED topology — `innerloop.optimise`
  (Nelder-Mead against the full objective), seconds to a couple of minutes for a
  programme-house-sized tree. This is not a sweep: no topology moves. §39.70 ran
  it on both arms of a comparison, so that a hand-tuned ratio set was not being
  measured against a machine-tuned one.

**Cannot**: anything calling `homemaker-evolve` at a real budget. No sweeps, no
search A/Bs, no "does this change help" question of any kind.

Which open beads that blocks is recorded **in each bead's own description**, not
here, so it cannot go stale in two places. As of §39.69 they were
`homemaker-py-3wq`, `57z`, `2g7.9`, `2g7.2` and the re-baseline itself.

### The discipline that keeps a sweep readable

A single sweep measures the NET effect of everything landed since the last one,
and nothing can be attributed to any individual change (§39.12 clause 3). So:

- **Prefer search-side work.** "Search-side" means the file is **not in
  `OBJECTIVE_SOURCES`** — five modules, `dom` / `fitness` / `geometry` / `graph` /
  `programme`, because those are the five a score actually executes. It is NOT
  "anything outside `fitness.py` and `geometry.py`": that reading held until
  §39.63 and was wrong. `tests/test_objective_sources.py` measures the set rather
  than trusting anyone's memory of it, and `tests/test_search_config.py` holds a
  partition over every module.
- **Search-side is still recorded.** A sweep row carries `search_commit` and
  `search_config` (§39.65), so changing a search default is a recorded decision
  rather than an invisible one.
- **Land an objective change only if it is an owner ruling or a plain defect** —
  something whose rightness does not depend on the measurement. "Would this score
  better" is a sweep question: design it, file it, leave it.
- **Write down what you expect the sweep to show, before it runs.** Every
  objective change in §39 did this, which is what lets its result be read as a
  check rather than a discovery.

### The Perl Urb source, when you need it

The port's reference implementation is a separate repo and is available to
anyone — it is **not** on the owner's machine only (verified reachable from an
agent container, 2026-09-26):

```bash
git clone https://bitbucket.org/brunopostle/urb.git
```

DESIGN.md cites its files throughout (`lib/Urb/Dom/Fitness/ProgrammeDriven.pm`
and the `Storey`/`Quad` modules are the ones the scorer was ported from). Clone
it and set `URB_ROOT` if you are reconstructing a historical measurement.

**But do not reach for it to settle a question about today's objective.**
`fitness.py` is the only evaluator, the Perl oracle and its parity tests are gone
(§39.21), and those tests had never actually run (§39.20). A rule is **not**
validated by "Urb did it this way" — several defects found in §39 were carried
straight over from the Perl.


### Running the re-baseline (NOT running now — re-read this before starting it)

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

**The stamp is not `HEAD`** — it is the last commit that touched any file in
`OBJECTIVE_SOURCES`, which is usually an older commit, because most work does
not touch the objective. Getting this wrong once already sent someone looking
for the wrong string. Derive it from the runner's own list, do not retype it
(§39.63 was a second, drifted copy of exactly this command):

```bash
python -c "import importlib.util as u; s=u.spec_from_file_location('r','experiments/run_coldstart_baseline.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.objective_commit())"
```

and confirm the runner's first line matches. (Set
`HOMEMAKER_ORTHOGONAL_DIVISION=1` first if you want the `+orth` suffix — the
stamp reads it from the environment.)

`--resume` picks up only what is missing if it is interrupted, and **do not edit
`src/` while it runs** (see below). A dirty objective source no longer needs
watching for: the runner refuses to start over uncommitted `fitness.py` or
`geometry.py`, before the stamp is taken, with no override (§39.51). A dirty
`src/` file that is *not* the objective warns and continues.

**The next sweep is not comparable to `c836457+orth`'s 248 at the fail-count
level** — §39.59 added a criterion (`excess internal area`) and tightened
another (`not adjacent to o`), so the fail SET moved (§39.12 clause 3). Expected,
not a problem to engineer around. What it is fair to compare is the shape:
per-programme deltas and the family census, where **crinkliness at 39.1% and
size at 11.7%** — as recorded at `c836457+orth`, 248 fails — are the numbers to
beat.

Quote those two figures carefully. `decompose_coldstart.py --objective
c836457+orth` re-scores the committed artefacts with **today's** code, so it now
reports 38.0% and 11.4% against a 255-fail total. Both are right and they answer
different questions; the script says so in a banner when the two diverge, but
only since §39.61 — before that it claimed to reproduce the rows exactly while
differing from them by seven.

### Crinkliness: the largest fail family, and three measured nulls

Crinkliness is far and away the biggest family — **39.1%** of the fail set at
`c836457+orth` (97 of 248), with `size` second at 11.7%. 69% of its residual sits
at `crink == 0`: fully buried leaves (§39.31).

**Three attempts to reach it have now been measured, and all three were inert.**
Read §39.68 before starting a fourth:

| attempt | outcome |
|---|---|
| §38.1 `floor` mode | no-op — it mapped 110 of the 112 failing leaves onto one constant |
| §39.13 `ramp` | correct and **inert**; search A/B byte-identical on all twelve pairs |
| `gvb` re-tiering | **premise false** (§39.68); the SOFT tier says "in principle" and ratio moves do reach the buried set |

The common cause: **the failing tail is 0.034% of corpus value**, so no
re-weighting of it can move a search. `homemaker-py-k54` (grade burial by depth)
is still open but its own stated gate has resolved against it.

So the lever is not the factor's shape or its tier. It is either an **operator
that buries less** (topology, not scoring) or a **ruling that `uncrinkliness`'s
per-space minimum exposure is calibrated tighter than the plots can deliver**.
Both are different beads from these three.

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
