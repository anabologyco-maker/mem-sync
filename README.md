# mem-sync

`mem-sync` gives Codex and Claude Code one project-scoped durable memory without
making either agent authoritative. It synchronizes the context that can safely
be made portable: project instructions, Claude Code auto-memory, and Codex's
generated local-memory output. It does **not** copy credentials, hidden product
system prompts, permission policy, or arbitrary transcripts into model context.

The project is deliberately local-first. The service keeps a registry in
`/var/lib/mem-sync` when run as root (otherwise under the XDG state directory),
while each enabled project owns its canonical memory under `.mem-sync/`.

## Quick start

From a project root:

```bash
mem-sync on
mem-sync status
```

Or target a project from elsewhere:

```bash
mem-sync /opt/cmd-ctr on
```

Both spellings are accepted:

```bash
mem-sync on /opt/cmd-ctr
mem-sync /opt/cmd-ctr on
```

Enable the background service once:

```bash
sudo mem-sync install-service
systemctl status mem-sync
```

After installation, `on` starts the service if needed. `off` stops it when no
registered project remains enabled.

Disable synchronization without rolling memory back:

```bash
mem-sync off
```

`off` first performs a final sync, then materializes independent copies of
`AGENTS.md`, `CLAUDE.md`, and Claude's auto-memory directory. All content stays
at its latest state; future edits stop propagating.

## What `on` does

1. Resolves exactly the directory supplied. It never enables an ancestor.
2. Backs up existing instruction and Claude memory files under
   `.mem-sync/backups/`.
3. Neutrally merges distinct pre-existing `AGENTS.md`, `CLAUDE.md`, and Claude
   `MEMORY.md` content. Each source is retained and labeled; neither wins.
4. Makes `AGENTS.md` and `CLAUDE.md` hard links to
   `.mem-sync/memory/MEMORY.md` when the filesystem permits it.
5. At a Git root, links Claude Code's native project auto-memory directory to
   the same canonical directory.
6. Registers the exact project root for background reconciliation and Codex
   native-memory harvesting.

Hard links look like ordinary files to Git. Editors that save by atomic rename
can break the link temporarily; the daemon notices and repairs it. If two
surfaces change before a sync pass, mem-sync retains both versions in a neutral
merge and stores the originals under `.mem-sync/conflicts/`.

## Merge and cleanup semantics

mem-sync does not continually append every edit:

- A normal edit from either agent is a replacement of the canonical state.
  Deleting stale lines, consolidating sections, renaming topics, or rewriting
  the whole memory is preserved exactly and propagated to the other agent.
- Claude Code writes directly into the canonical memory directory while sync is
  on. A request such as "clean up your memory" can rewrite `MEMORY.md` and its
  topic files; removed content stays removed.
- Each completed Codex native-memory extraction is imported once, identified by
  its thread and source watermark. Its first import appends a labeled section;
  after Claude or Codex cleans that section up, the daemon does not resurrect it.
- If exactly one surface changed since the previous pass, that complete version
  wins. Multiple identical edits are also unambiguous. Multiple different
  concurrent edits are retained in a labeled neutral union with originals saved
  under `.mem-sync/conflicts/`; neither agent silently wins.

For example:

```text
You: Hey Claude, clean up your project memory. Remove stale facts, consolidate
     duplicates, and keep the current decisions.
Claude: [rewrites its native MEMORY.md]
mem-sync: [makes that exact cleaned version AGENTS.md and CLAUDE.md]
Codex next launch: [loads the cleaned version]
```

If the enabled path is nested below a Git root, mem-sync does not redirect
Claude's repo-wide native auto-memory directory: doing so would affect a larger
scope than requested. `AGENTS.md` and `CLAUDE.md` are still synchronized.

`mem-sync status` reports root-level instruction files that can add to or
shadow the two managed surfaces: `AGENTS.override.md`, `CLAUDE.local.md`, and
`.claude/CLAUDE.md`. v0.1 preserves but does not rewrite those files. Consolidate
durable shared facts into the managed files when the report is non-empty.

## Session migration

Move a saved session's project affiliation without moving the source tree:

```bash
mem-sync migrate SESSION_ID /old/project /new/project
mem-sync migrate SESSION_ID /old/project /new/project --dry-run
```

For Codex, mem-sync updates the documented local thread index and the saved
rollout metadata. When the target session is active, the index is updated
immediately and transcript rewriting is deferred until Codex releases its
writer lock. For Claude Code, the transcript is copied, rewritten, and moved to
the target project bucket. Every migration creates a backup under the target's
`.mem-sync/migrations/` directory.

Migration is intentionally separate from memory sync. A transcript contains
tool output, pasted text, and possibly secrets; it is resumable conversation
state and is never injected into the shared memory file.

After migrating a Codex session, resume it from the destination with:

```bash
cd /new/project
codex resume SESSION_ID
```

## Install from source

The checkout is directly runnable and has no runtime dependencies beyond
Python 3.10+:

```bash
git clone https://github.com/anabologyco-maker/mem-sync.git /opt/mem-sync
sudo ln -s /opt/mem-sync/bin/mem-sync /usr/local/bin/mem-sync
mem-sync --version
```

For development:

```bash
cd /opt/mem-sync
python3 -m pytest
```

## Security and limits

- Memory and transcripts are plaintext in both upstream products. Never put
  credentials in shared memory.
- Built-in Codex and Claude Code system prompts are product-owned runtime
  behavior, not files mem-sync can or should overwrite. User/project
  instruction layers are the portable boundary.
- Codex's local memory schema and Claude's project-key encoding are not
  documented stable APIs. mem-sync discovers installed state defensively,
  writes only to its own memory store, and backs up any session metadata before
  migration.
- Codex loads project instruction documents up to its configured byte limit;
  Claude loads at most the first 200 lines or 25 KiB of `MEMORY.md`. mem-sync
  keeps imported Codex memory in the shared startup file up to 24 KiB and
  archives additional details under `.mem-sync/memory/codex/`.
- v0.1 synchronizes the root instruction pair and native project memories. It
  inventories nested rules, skills, hooks, settings, subagents, and prompt
  customizations but does not translate them; executable/configuration state
  requires an explicit trust-aware adapter rather than blind file copying.
- The bundled system service runs with the privileges used at installation so
  it can reconcile all registered paths. On a multi-user machine, install and
  run a separate service per trusted user instead of sharing a root daemon.

See [the architecture](docs/architecture.md) and the
[memory-system map](docs/memory-systems.md) for the full model and precedence
research.
