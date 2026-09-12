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

### Room-code namespaces (DESIGN.md §39.4/§39.6)

Leaf types share a first character across three namespaces:

- **`C` / `O` / `S`** — generic structural types (circulation / outside / sahn),
  uppercase, reserved. A programme code spelled exactly one of these is rejected
  at load.
- **programme room codes** — lowercase, may start with *any* letter. The generic
  tests match `C`/`O`/`S` exactly, so `cr1` is a room, not circulation.
- **`usage:`** — every space declares its access-requirement class
  (`living`/`kitchen`/`bedroom`/`toilet`/`utility`/`none`), mandatory, no
  fallback (DESIGN.md §39.7). A code's spelling decides nothing: `name:` is free
  text, `usage:` drives behaviour. There is no first-character type test left
  anywhere in the codebase.

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
