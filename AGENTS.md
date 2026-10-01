# Agent Instructions

**`CLAUDE.md` is canonical. Read that.** This file holds only the block below,
which `bd setup` generates and rewrites (note the `hash:` in its marker) — so
anything hand-written here can be silently overwritten, and duplicating
CLAUDE.md's rules here lets the two drift apart.

§39.69 moved this file's one piece of unique guidance (the non-interactive
`cp`/`mv`/`rm` warning) into CLAUDE.md for that reason. If you are adding
instructions for agents, add them to CLAUDE.md.

2026-10-01 removed two more duplicates from inside the marker block: copies of
CLAUDE.md's *Room-code namespaces* and *Session Completion*. Both sat where
`bd setup codex` would overwrite them, and the Room-code copy had already
demonstrated the drift this file warns about — in the direction nobody expects.
It was the CORRECT account of `homemaker-py-1v7` ("no first-character type test
left") while canonical CLAUDE.md still claimed two survived. Being the stale
copy is not a property of the non-canonical file. The lesson is not to maintain
this copy more carefully; it is that the second copy should not exist (§39.63).

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
