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
- `fitness.py` — native Python fitness evaluator (replaces Perl oracle)
- `fitness_cmd.py` — `homemaker-fitness` CLI entry point
- `collapse_cmd.py` — `homemaker-collapse` CLI: finish-time global cell→room collapse (94g)
- `graph.py` — leaf-adjacency graph for programme-driven fitness checks
- `genome.py` — topology genome: base-floor tree + per-storey deltas
- `operators.py` — high-locality mutation and subtree crossover
- `innerloop.py` — ratio optimisation inner loop (Nelder-Mead / CMA-ES)
- `driver.py` — memetic search outer loop
- `evolve.py` — `homemaker-evolve` CLI entry point
- `oracle.py` — legacy Perl shim, kept for validation only; do not use in new code

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

Do **not** use `urb-fitness.pl` directly — `oracle.py` and the Perl tool are
kept only for cross-validation.
