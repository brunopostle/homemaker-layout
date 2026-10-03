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
<!-- END BEADS INTEGRATION -->

## Working with `bd`

**The block above is generated; everything from here down is hand-written.**
`bd setup claude` rewrites whatever sits between the `BEGIN`/`END BEADS
INTEGRATION` markers, matching on the `hash:` in the marker. Until 2026-10-01
this file's whole bd section *and* its Session Completion workflow sat *inside*
those markers — so the command bd itself keeps recommending (`bd setup claude
--check` reports "installed but stale: Run: bd setup claude") would have deleted
about a hundred lines of project policy. That is §39.69's AGENTS.md failure,
latent here. Both sections are outside the markers now, so a regeneration is
safe. Keep it that way: **never put project guidance between those markers.**

`bd setup claude --print` shows what a regeneration would write without writing
it, and `bd setup claude` was run once on 2026-10-01 to prove this restructure
holds — every hand-written section survived. **Do not run it again**, because
what it writes is worse than merely redundant:

- a **second `## Session Completion`** inside the block, whose workflow
  contradicts the one below it ("Handle git/sync by active profile", "Do not
  commit or push without clear authority"). Two headings of the same name in one
  file saying opposite things is §39.63's two-copies failure, in prose;
- an **Agent Context Profiles** section presenting *Conservative* as the default;
- the claim that "`.beads/issues.jsonl` is a passive export" — a Dolt remote
  now does carry `refs/dolt/data` here (see *This machine*), but containers
  hand-edit the JSONL without bd, so it is not passive on this project;
- and in `.claude/settings.json` it **deletes the `PreCompact` hook** and rewrites
  `SessionStart` to `bd prime --hook-json`. That JSON form is the better
  invocation — it emits a proper `hookSpecificOutput` envelope — but it hardcodes
  `hookEventName: SessionStart`, which is presumably why bd drops the PreCompact
  hook instead of converting it. Losing it means bd context is not reloaded after
  a compaction, which is when it is most needed.

### The git-authority profile is a config key, not something to argue with

`bd prime` injects a git policy into every session, and 1.3.1's default
(`agent.profile=conservative`) reads "do not commit, push, or run dolt remote
sync without explicit authority" — the opposite of *Session Completion* below.
1.0.4's prime did not say this, so **the upgrade introduced the contradiction**.

The fix is configuration, not annotation:

```bash
bd config set agent.profile team-maintainer   # already set; see .beads/config.yaml
```

`team-maintainer` is bd's own name for a repository that opts into agents
committing and pushing as part of session close — precisely what *Session
Completion* mandates. It persists in the **git-tracked** `.beads/config.yaml`, so
it is a repo-level ruling and not a per-machine one, and `bd prime` then reads
"commit, sync, and push are routine unless explicitly restricted". **If injected
bd context ever tells you not to push, check this key before believing it.**
Two related levers, deliberately unused: `bd config set no-git-ops true` strips
git commands from prime altogether, and a `.beads/PRIME.md` replaces prime's
workflow text with the project's own.

### This machine

bd **1.3.1** at `~/.local/bin/bd`, a hand-placed binary owned by no package.
Storage is an embedded Dolt DB at `.beads/embeddeddolt`, schema **v66**, with
**a Dolt remote, `origin`** — the same GitHub repo as git
(`git+ssh://git@github.com/brunopostle/homemaker-layout.git`), where the Dolt
data lives under `refs/dolt/data` beside the git branches. It is configured by
`sync.remote` in `.beads/config.yaml` (written as a nested `sync:` mapping
since 9f2f4d9) and was pushed to on 2026-10-01; before that this file described
the machine as local-only.
`bd dolt remote list` shows it. So `bd dolt push` (step 4 of Session
Completion) now does real work, and the designated-migrator gate (#4259) can
fire again on a future schema change.

**Two copies of issue state now exist, and both must be kept in step.** The
Dolt DB itself is gitignored; `refs/dolt/data` is the copy `bd dolt push`
carries. `.beads/issues.jsonl` is git-tracked and is still the copy a container
without bd reads and hand-edits (see *In an agent container*). Neither syncs the
other for you: export before committing (below), and after pulling a JSONL that
someone edited without bd, `bd import .beads/issues.jsonl` before writing, or
the next export will silently revert their edit. That is §39.63's two-copies
failure, and the reason this paragraph exists.

**Memories travel only by the Dolt remote.** They live in the DB, and
`bd export` **excludes them by default** (bd deems them possibly-sensitive agent
context), so they never reach the JSONL unless you pass `--include-memories`.
After `bd remember`/`bd forget`, `bd dolt push` is what makes the change outlive
this machine. A container without bd never sees them, so findings that every
agent must have still go in `DESIGN.md` and working knowledge here; `bd
remember` is for notes useful to sessions that run bd.

**Export before committing issue changes.** 1.3.1 writes to stdout, so it is an
explicit step rather than something that happens for you:

```bash
bd export -o .beads/issues.jsonl
```

**A write does not refresh it.** Settled 2026-10-01 by running `bd create` and
reading `git status`: the tree stayed clean, so the new bead existed only in the
gitignored Dolt DB. Nothing reaches git until you export. Treat an unexported
`bd create`/`update`/`close` as lost work.

`bd doctor` is unsupported in embedded mode. Of the checks that do run,
`--check=pollution` flags `homemaker-py-1ue` and `homemaker-py-gug` as test
artefacts because their titles begin with "test" — both are real issues, so
**never run it with `--clean`**. `bd export` is issues only, not Dolt history,
branches or working-set state; `bd backup init|sync|restore` is the full-backup
family.

bd ships usage metrics **on**. `bd metrics off` disables them and lands in
`~/.config/bd/config.yaml` — user-global, outside this repo, so a fresh clone
does not re-enable them but a fresh *machine* does. bd also drops a zero-byte
`.beads.gate.lock` at the **repo root**, where `.beads/.gitignore`'s `*.lock`
cannot reach it; the root `.gitignore` covers it.

### Installing or upgrading bd

Use the prebuilt release binaries. They need neither a Go toolchain (there is
none on this box) nor the libicu build below:

```bash
# The repo MOVED: steveyegge/beads -> gastownhall/beads (the API serves a 301).
V=1.3.1
curl -sL -o bd.tgz https://github.com/gastownhall/beads/releases/download/v$V/beads_${V}_linux_amd64.tar.gz
curl -sL -o checksums.txt https://github.com/gastownhall/beads/releases/download/v$V/checksums.txt
sha256sum -c <(grep "beads_${V}_linux_amd64.tar.gz" checksums.txt)   # verify BEFORE installing
tar xzf bd.tgz && cp -f bd ~/.local/bin/bd && bd metrics off
```

**`bd upgrade` does not upgrade bd** — it only tracks and acknowledges version
changes (`status`/`review`/`ack`). Schema migration happens automatically on
store open; `bd migrate schema` is the idempotent, observable form.

Building from source instead needs `libicu-devel` (Fedora) / `libicu-dev`
(Debian), a cgo dependency of Dolt's regex library, and then — note that the
**Go module path did not follow the repo move**, it is still `steveyegge` at
v1.3.1:

```bash
go install github.com/steveyegge/beads/cmd/bd@v1.3.1
```

**Keep the JSONL committed whenever bd is in use.** bd **1.0.4** rewrote
`.beads/issues.jsonl` on *every* invocation, and twice deleted it outright while
leaving the database empty — recoverable only because the file is git-tracked
(`git checkout -- .beads/issues.jsonl`). 1.3.1 does not touch it on reads.

**The import/export round-trip is semantically lossless but not byte-lossless.**
Verified 2026-10-01 over 208 issues, 116 dependency edges and 23 comments: all
present, and no content field moved. What does move: four closed issues gain a
`closed_at` they were missing; every dependency's `created_by` is flattened to
`auto-import` (it was `Bruno Postle` x108 / `Claude` x8, and two distinct values
mean `bd import --actor` cannot restore it); comment UUIDs are reissued. Key and
list ordering churn as well, so the first export after an import is a ~200-line
diff on a git-tracked file.

Separately, **the v66 schema migration bumped `updated_at` on 59 issues** to its
own clock, which is `homemaker-py-a72v` — `bd stale` is unreliable for anything
last touched before 2026-10-01. That one was missed on the first pass because
the check iterated a hand-typed field list that omitted `updated_at`. **When you
verify a migration, diff every key present in either record**, not the ones you
thought to name.

### In an agent container

A container is not this machine: **assume `bd` is absent**, not merely off
`PATH`. It is a Go binary, not part of the repo, and a restart removes it —
`command -v bd || ls ~/go/bin /root/go/bin` before anything else.

The owner's standing preference is to **leave bd unconfigured in a container and
hand-edit `.beads/issues.jsonl`**, which is plain JSONL and the thing that
actually carries issue state. Match an existing record's keys exactly,
**preserve the other lines byte-for-byte** (rewriting the file with `json.dumps`
reorders keys on every record and churns all ~200 lines for nothing), and
re-parse the file afterwards. Beware that `bd create` fails *silently* under
`&&` chaining and the work then looks done — that is how a bead id which never
existed reached DESIGN.md once (§39.53).

If you do install it there, a local-only DB works: `bd init --prefix
homemaker-py` with no remote, then `bd import .beads/issues.jsonl`. Bootstrapping
from the configured `sync.remote` instead is possible — the Dolt remote
was pushed by bd 1.3.1 (schema v66) on 2026-10-01 — but a local DB built from
the JSONL avoids depending on it. The schema gate that once blocked this (a
remote at v32 against a bd wanting v66) should not recur at v66.
`sync.remote` in
`.beads/config.yaml` is still a `git+ssh://` URL and containers have no `ssh`
binary, but bd resolves that URL over HTTPS itself — the ssh premise once
recorded here was wrong.

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
- Corpora on disk, newest first. `coldstart-07b2058+orth-*` is the **newest
  complete** one (12/12, all verified, §39.82). §39.84 moved the objective a day
  later; re-scored with that code only maple-court s1 differs (x1/64, six
  revealed adjacency fails), so it remains the right comparison for the next
  sweep. Check the live stamp before relying on any of this.
  `coldstart-c836457+orth-*` is one generation behind and
  `coldstart-1138ff1+orth-*` two; all three were measured with the switch
  **on**. The older `coldstart-055d710-*` and `coldstart-99c85ec-*` were
  measured with it **off**, at different objectives again — do not compare to
  these at all. Do not trust a stamp written out here: this
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
- `experiments/build_hand_3storey.py` — rebuilds the repo's one HUMAN design from
  its trace (§39.70), and `--baseline` scores the evolved `+orth` artefacts both as
  committed and after the same ratio solve, which is the control any "hand design
  vs evolved" comparison needs.
- **The operator census, the pattern worth copying.** `diag_t7q_shaft_breakage.py`
  applies EVERY operator to every corpus artefact and counts how often an invariant
  stops holding; `diag_v2k_migrate.py` and `diag_t7q_repair.py` do the same for one
  operator's effect, the second with a `--from-broken` mode that measures on
  children an operator has just damaged rather than on converged artefacts. That
  distinction changed an answer by twenty-fold (§39.75), and the census pattern
  found defects in code landed the same week, twice (§39.73, §39.75). Both are
  seconds to minutes in a container.
- `experiments/diag_m4d_stair_stack.py` — the counterfactual pattern: re-score the
  whole corpus with one rule monkeypatched, to price a change to the objective
  before proposing it (§39.72). It priced one at "two artefacts much worse" and
  stopped a plausible-looking fix. **Prefer exact arithmetic to a monkeypatch where
  the rule only feeds `0.5 ** len(failures)`** — §39.80 patched one of the three
  producers of a failure cascade and mis-reported the effect by 4x until the
  discrepancy was chased.
- `experiments/diag_operator_invariants.py` — the census widened from one invariant
  to the structural ones (typeless leaves, half-divided nodes, stale `below`
  pointers, genome round-trip, scorer exceptions), with `--from-broken` and a
  **negative control**. 21,120 applications, zero violations (§39.79).
- `experiments/diag_ekc_shapecurve.py` — how exact the shape-curve DP's verdict
  really is, split into false positives, false negatives, and which mechanism
  causes each (§39.78).
- `experiments/diag_r8c_warmstart.py` — the seven-arm ladder that priced
  `solve_ratios`' target model against the objective (§39.76). The arm pattern
  (each arm = the one above plus a single change) is reusable for any
  "which of these candidate fixes actually helps" question.
- `experiments/diag_3i3_missing_room.py` — what omitting a required room costs, and
  where in a run it fires; `--verbosity-only` is the per-code penalty table (§39.80).
- `experiments/diag_ruling_omit_vs_circulation.py` — an owner ruling turned into a
  generic check (§39.85): on any programme and artefact, the cheapest single-room
  omission must outscore "no circulation". Run it after any objective change;
  `--self-test` is its negative control, and `tests/test_ruling_omit_vs_circulation.py`
  pins it. The pattern to copy when a ruling is about an ORDERING.
- `experiments/trace_harbor_house.py` — reads an architectural SVG, and asks whose
  it is FIRST. §39.77 is the write-up of not doing that.

### A census that reports zero is worth nothing until its checks have been shown to fire

§39.79 ran 21,120 operator applications across five structural checks and found no
violations. That null is only readable because each check was first pointed at a
tree corrupted in exactly the way it is supposed to catch — and on the first run
**two of the five stayed silent**. Both times the CONTROL was wrong rather than the
check (one aimed a storey root at the level-0 root, and both have id `""`, so it
corrupted nothing; the other set a bogus leaf type, which `genome.decode`
faithfully reapplies). Had it shipped without the control, two of five columns
would have been zeros that meant nothing.

So: **write the negative control before you believe a null.** It is cheap, it goes
in the tool rather than in your head, and `diag_operator_invariants.py --self-test`
is the worked example. The same discipline is why
`tests/test_stair_shaft_is_a_full_column.py` carries a monkeypatch negative
control.


## Conventions & Patterns

### argparse help strings: write `%%`

Python 3.14 expands every help string when the option is DEFINED, so a bare `%`
("6-14% of draws") makes the parser raise on every call — `homemaker-evolve`
could not start at all on the owner's desktop (§39.82). Containers run an older
Python that fails only on `--help`, so the bug is invisible there.
`test_help_renders` in `tests/test_evolve_cli.py` asks for `--help`, which
catches it on any version.

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
  The CONSTRUCTOR agreed with none of that until `homemaker-py-1v7`: three
  sites in `operators.py` matched adjacency by first character, which
  over-credits — `b1` counted a neighbour typed `b2`, `de1` counted `dp1`, and
  in harbor-house a room `of` counted as outside space `o`. Fixed at 75795b9;
  all three now ask `graph.code_matches_requirement`, the single place that
  answers "does this leaf count as the thing the programme asked to be next
  to", and `tests/test_constructor_adjacency_match.py` checks the SOURCE so a
  fourth cannot creep back (the third site was found by that test, not by
  reading). **No first-character type test remains anywhere.**

When adding or editing a programme, run
`python experiments/audit_programme_config.py` — it reports reserved-name
collisions, the usage class each code picks up, and per-room-spec satisfiability.

### The stair shaft is a full-height column (owner's ruling, DESIGN.md §39.72)

**A staircase exists only where the cell is identical on every floor.** The owner's
reasoning, and it is not a port artefact: a mid-landing needs flights going both up
and down where a ground-floor landing needs only one going up, so a split cell
*could* in principle hold a stair — but fitting flights into one automatically is
hard, and Alexander's pattern allocates the whole vertical shaft to stairs. So the
simplification is the model, for now.

The scorer reads it that way: `graph.stack_corners_in_use` walks `dom._above_node`
— the EXACT id path — and wants a leaf typed exactly `"C"` on every storey. Every
*other* vertical predicate in `dom` walks the forgiving `_above_more`, so this is
easy to mistake for a bug; §39.72 measured what relaxing it would do (two artefacts
much worse, via `staircase_max`, the entrance corners fed to `_stair_fit`, and
`has_public_access_inside`) and `tests/test_stair_shaft_is_a_full_column.py` pins it
with the ruling in its docstring.

What this means when you touch operators:

- a building with no intact shaft pays **x0.0225** — `staircase volume` at its 0.09
  floor, times 0.5 for each of the two fails — so breaking one is expensive;
- `operators._shaft_paths` (every intact shaft, largest first) and `_shaft_cells`
  (their nodes on every storey) are the shared predicates. A move that must not
  cost the building its staircase consults them; `mutate_support_outside` and
  `mutate_level_add_migrate` both do;
- **a repair that trades one hard fail for another is broken** — that is why
  `support_outside` is guarded (§39.74) while the six exploratory operators that
  also break shafts are not: exploration may trade, and the comparator decides.
  Removing exploratory moves is an A/B, and it needs the box (`homemaker-py-t7q`);
- `mutate_repair_shaft` (default ON, §39.75) is the move back: it CUTS a ~2.6 m
  shaft through an aligned column rather than retyping one, because retyping a
  column buries its neighbours' daylight — measured, and it lost on all six
  artefacts it fired on.

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

- **There is often no corpus at the live objective.** The objective has moved
  faster than sweeps can follow (~127 run-hours, 18.6 h on the owner's desktop,
  §39.82), so `verify_results_table.py`
  reporting every row skipped is §39.43 working, not a fault. Compare a new sweep
  only to a corpus at the same stamp, and never across the `+orth` switch
  (§39.12 clause 3).
- **The stamp can move without the objective changing.** It is
  `git log -1 -- OBJECTIVE_SOURCES`, so a pure rename in one of those five files
  moves it (§39.65 is the worked example, §39.80 the second: a docstring edit to
  `graph.py` recording an owner ruling). Re-score before concluding anything
  changed — §39.80 captured all twelve artefact scores before and after and
  diffed them, which is the cheap way to prove it.
- **A sweep needs the box.** Anything calling `homemaker-evolve` at a real budget
  (a single 500k run is hours) cannot be done in a container. Check whether a box
  is available before planning a measurement; if it is not, the beads marked as
  needing it are genuinely blocked. **The owner's desktop is a box** (Ryzen 5
  3400G, 4 cores / 8 threads, 5 GB, Python 3.14): it ran §39.82's sweep and
  §39.81's 72-run A/B. Ask whether it is free; do not assume either way.

### What a container can and cannot do

**Can**, so none of this is ever blocked:

- the full test suite — `pytest`, six to seven minutes; the count is whatever
  `pytest -q` prints on the last line, and it grows every week;
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
search A/Bs — nothing that depends on POPULATION DYNAMICS, which is what a search
actually is.

Do not read that as "no measurement", though. §39.73-§39.75 answered three
decision-relevant questions in a container by calling the operators directly:
which operators break an invariant and how often (apply each to every artefact
and count), what a move does to the layout it is applied to, and — the one that
mattered most — what it does to a child that another operator has just damaged,
which is the state a search actually offers it. That last distinction changed an
answer by twenty-fold. What none of it captures is whether the search KEEPS the
children a move produces, so this kind of measurement informs a default and never
settles one.

Which open beads that blocks is recorded **in each bead's own description**, not
here, so it cannot go stale in two places. This file listed them once and the list
was wrong within a week. There is no command that derives them either — the
blocker is prose, and every bead words it differently:

```bash
# a starting point, NOT an oracle: it under-reports (a bead that says
# "3M evaluations" and never says "box" is just as blocked) and over-reports
# (a bead that merely mentions a sweep is not)
python -c "import json,re;p=re.compile(r'\bbox\b|real budget',re.I);[print(r['id'],'-',r['title'][:60]) for r in (json.loads(l) for l in open('.beads/issues.jsonl') if l.strip()) if r['status']!='closed' and p.search(r.get('description',''))]"
```

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

**Measured at `07b2058+orth` (§39.82), on the owner's desktop at `--slots 8`:**
127 run-hours, makespan **18 h 34 m**. Per run: maple-court ~17 h (the longest,
and the floor on makespan), harbor-house 13.5-15.7 h, health-centre 8-10 h,
programme-house ~2 h. `c836457+orth` took the same 126 run-hours; the
436-hour / 63-hour figures this section used to quote were `1138ff1+orth`'s. More
slots than the 12 runs buys nothing, and the makespan is already within ~2 h of
the longest run. **Run all twelve on one machine**: the
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

**Compare the shape, not the fail count**, whenever the fail SET has moved
between two sweeps (§39.12 clause 3): per-programme deltas and the family
census. At `07b2058+orth` (§39.82, 261 fails) those are **crinkliness 45.2%,
proportion 11.1%, size 6.5%**; at `c836457+orth` (248 fails) crinkliness was
39.1% and size 11.7%. **Write down what you expect before the next one runs** —
§39.82 did not, so it is a description rather than a check.

Quote those two figures carefully. `decompose_coldstart.py --objective
c836457+orth` re-scores the committed artefacts with **today's** code, so it now
reports 38.0% and 11.4% against a 255-fail total. Both are right and they answer
different questions; the script says so in a banner when the two diverge, but
only since §39.61 — before that it claimed to reproduce the rows exactly while
differing from them by seven.

### Crinkliness: the largest fail family, and three measured nulls

Crinkliness is far and away the biggest family — **45.2%** of the fail set at
`07b2058+orth` (118 of 261, §39.82), up from 39.1% at `c836457+orth`. When §39.31
measured it, 69% of its residual sat at `crink == 0`: fully buried leaves.

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
