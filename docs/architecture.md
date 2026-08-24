# Architecture

## Design goals

- Symmetric: either agent can change durable memory; source identity never
  determines precedence.
- Project-scoped: enabling `/a/b` does not edit `/a` or user-global memory.
- Auditable: canonical memory is Markdown, conflicts retain both originals,
  and session migrations are backed up.
- Reversible topology: `off` stops propagation but preserves the latest bytes.
- Conservative around private state: native databases are read for memory
  extraction, never used as the canonical store.

## Data flow

```text
                     .mem-sync/memory/MEMORY.md
                              (canonical)
                          /         |         \
                         /          |          \
                  AGENTS.md     CLAUDE.md    Claude auto-memory/
                    Codex       Claude Code       MEMORY.md + topics
                         \          |          /
                          \         |         /
                           background reconciler
                                      ^
                                      |
                           Codex generated-memory DB
                              (read-only harvest)
```

`AGENTS.md` and `CLAUDE.md` use the same inode when hard links are supported.
Claude's native project memory directory points at the canonical memory
directory when the requested scope is exactly the Git root. The daemon repairs
atomic-save link breaks, mirrors cross-filesystem fallbacks, and imports new
Codex background-memory records associated with the root or its descendants.

## State

Project-owned state:

```text
.mem-sync/
├── memory/
│   ├── MEMORY.md
│   ├── codex/<thread-id>.md
│   └── <Claude-created topic files>
├── state.json
├── backups/
├── conflicts/
└── migrations/
```

Machine registry:

```text
/var/lib/mem-sync/registry.json       # root service
$XDG_STATE_HOME/mem-sync/registry.json # user service/CLI
```

The registry contains project paths and pending safe-finalization work, not
memory content.

## Conflict policy

The common case is single-writer: one changed surface becomes canonical. If
multiple surfaces changed to identical bytes, the result is also unambiguous.
If multiple unique edits arrive in one polling interval, mem-sync does not
choose Codex, Claude, newest mtime, or lexical order as the winner. It stores
each original and creates a labeled union that both agents see. This may need a
human cleanup, but it is lossless and symmetric.

## Session migration

Session migration changes the working-directory/project index, not conversation
semantics.

- Codex: transactionally updates the `threads.cwd` row in the newest local
  state database. It rewrites only the `session_meta.cwd` field in the JSONL
  rollout once no writer lock is held. Historical per-turn working directories
  remain historical facts.
- Claude Code: moves `<session-id>.jsonl` between project buckets and rewrites
  top-level `cwd` fields. Companion spilled tool-result directories move with
  it.

The operation validates that the recorded source matches the caller's source
argument. It will not silently adopt a session from another project.

## Why no shared system prompt

The agents' built-in prompts encode different tools, safety policy, UI
behavior, and orchestration contracts. They are not durable project memory and
neither vendor exposes the CLI's built-in prompt as a supported editable file.
Trying to make those prompts identical would weaken the hosts' contracts and
still would not make their tool semantics equal. mem-sync therefore shares the
highest portable layer both products officially support: project instructions
and local durable memory.

