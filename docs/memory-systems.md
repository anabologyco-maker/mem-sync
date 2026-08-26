# Codex, Claude Code, and OpenCode memory-system map

Research baseline: 2026-08-26. Upstream behavior can change; links below are
the official vendor documentation used for this implementation.

## Codex

### Instruction precedence

Codex builds `AGENTS.md` guidance once per launched session:

1. Under `CODEX_HOME` (default `~/.codex`), `AGENTS.override.md` wins over
   `AGENTS.md`; only the first non-empty global file is used.
2. From the project root down to the current working directory, at most one
   file per directory is selected in this order:
   `AGENTS.override.md`, `AGENTS.md`, then configured fallback names.
3. Files are concatenated root-to-leaf, so closer files appear later and have
   more specific precedence.
4. The default combined project-document cap is 32 KiB.

Official source: [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

### Local memories

Local Codex memories are off by default unless `[features] memories = true` is
enabled. Chat-level controls decide whether a chat may consume memory and/or
contribute to future memory. Generation is asynchronous, may skip active or
short sessions, redacts generated fields, and can be rate-limit gated.

The supported storage root is `CODEX_HOME` (default `~/.codex`). Current Codex
builds use generated files and versioned SQLite state beneath that root; these
are generated implementation state, not a hand-editing API. mem-sync reads
completed per-thread extraction records and copies their Markdown output into
its own canonical store. It never inserts or updates Codex memory records.

Official source: [Memories](https://learn.chatgpt.com/docs/customization/memories).

### Configuration and sessions

Codex configuration values resolve from highest to lowest as: CLI flags and
`--config`, trusted project `.codex/config.toml` layers from root to leaf,
the selected `~/.codex/<profile>.config.toml`, user `~/.codex/config.toml`,
system `/etc/codex/config.toml`, then built-in defaults. Managed defaults and
administrator `requirements.toml` constraints sit above or constrain that
user-controlled stack.

- Managed defaults: `/etc/codex/managed_config.toml` on Unix; managed
  preferences/MDM can take still higher precedence.
- Admin constraints: `/etc/codex/requirements.toml` on Unix or supported cloud
  and device-management delivery.
- User config: `~/.codex/config.toml` (or `CODEX_HOME/config.toml`).
- Selected profile: `~/.codex/<profile>.config.toml`.
- Trusted project config: `.codex/config.toml` in each directory from project
  root to CWD; closer layers win. Some machine-local provider, auth,
  notification, profile, and telemetry fields are intentionally ignored here.
- Extra developer prompt text: the `developer_instructions` config key or a
  configured `model_instructions_file`; these are not the built-in product
  prompt and are not synced by v0.2.
- Hooks: `hooks.json` or inline `[hooks]` beside each active config layer.
- Command rules: `rules/*.rules` beside active config layers.
- Skills: `.agents/skills/` from CWD through repo root, then
  `~/.agents/skills/`; system and admin skill locations may also contribute.
- Custom prompts: top-level Markdown files in `~/.codex/prompts/`.
- MCP servers, plugins, subagent roles, model defaults, approvals, and sandbox
  defaults: the active `config.toml` layers.
- Session state root: `CODEX_HOME`; current builds index threads in a versioned
  state database and retain JSONL rollouts under `sessions/`.
- A saved chat records its working directory. `codex resume` can use either the
  saved directory or current directory, governed by `tui.resume_cwd` and `-C`.
- Credentials may be in `auth.json` or an OS keyring. They are never synced.

Official sources: [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference),
[Advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced), and
[Codex CLI commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli).

### Existing Claude import

Codex has an official `/import` flow for Claude Code setup, project memories,
and recent chats; the desktop app can keep imported work updated. It is a useful
one-way import baseline, but the documented contract does not make Claude Code
consume memories subsequently created by Codex. mem-sync supplies the symmetric
project-local layer.

Official source: [Import from another agent](https://learn.chatgpt.com/docs/import).

## Claude Code

### Instruction and setting precedence

Claude loads:

- managed policy (highest),
- command-line arguments,
- `.claude/settings.local.json`,
- `.claude/settings.json`,
- `~/.claude/settings.json` (lowest).

Array settings can merge rather than replace. Project instructions can live in
`CLAUDE.md` or `.claude/CLAUDE.md`; personal project instructions can live in
`CLAUDE.local.md`; global instructions live at `~/.claude/CLAUDE.md`.
Instruction files above the working directory load at launch from root toward
the current directory. Nested files below it load when Claude reads that
subtree. `@path` imports recurse to a bounded depth. `CLAUDE.md` arrives as
project context after the system prompt, not as part of the built-in prompt.

Official sources: [How Claude remembers your project](https://code.claude.com/docs/en/memory) and
[Claude Code settings](https://code.claude.com/docs/en/settings).

### Complete authored-state inventory

Project files are at the repository root or under `.claude/`; corresponding
user files are under `~/.claude/`:

| Surface | Project | User/global |
| --- | --- | --- |
| Main instructions | `CLAUDE.md` or `.claude/CLAUDE.md` | `~/.claude/CLAUDE.md` |
| Personal project instructions | `CLAUDE.local.md` | — |
| Topic/path rules | `.claude/rules/*.md` | `~/.claude/rules/*.md` |
| Settings, permissions, hooks, env, model defaults | `.claude/settings.json` | `~/.claude/settings.json` |
| Personal setting overrides | `.claude/settings.local.json` | — |
| Team MCP | `.mcp.json` | — |
| Personal/local MCP and app state | — | `~/.claude.json` |
| Skills | `.claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>/SKILL.md` |
| Legacy/single-file commands | `.claude/commands/*.md` | `~/.claude/commands/*.md` |
| Output styles (system-prompt customization) | `.claude/output-styles/*.md` | `~/.claude/output-styles/*.md` |
| Subagents | `.claude/agents/*.md` | `~/.claude/agents/*.md` |
| Subagent persistent memory | `.claude/agent-memory/<name>/` | `~/.claude/agent-memory/<name>/` |
| Plugins | enabled in project settings | installed/configured below `~/.claude/` |
| Auto memory | — | `~/.claude/projects/<project>/memory/` |
| Sessions | — | `~/.claude/projects/<project>/<session-id>.jsonl` |

Managed settings outrank the table above. On Linux/WSL they may be delivered
as `/etc/claude-code/managed-settings.json`, alphabetically merged drop-ins in
`/etc/claude-code/managed-settings.d/*.json`, and managed MCP configuration.
Server-managed and OS policy sources can outrank file-based managed settings.

Official source: [The `.claude` directory](https://code.claude.com/docs/en/claude-directory).

### Auto memory

Auto memory is on by default in current Claude Code and can be toggled with
`/memory`, `autoMemoryEnabled`, or `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.
Each project normally has:

```text
~/.claude/projects/<derived-project>/memory/
├── MEMORY.md
└── optional-topic-files.md
```

The first 200 lines or 25 KiB of `MEMORY.md`, whichever comes first, load at
session start. Topic files are read on demand. Worktrees and subdirectories in
one Git repository share the same native auto-memory directory. This is why
mem-sync redirects native auto-memory only when its exact enabled path is the
Git root.

Official source: [How Claude remembers your project](https://code.claude.com/docs/en/memory).

### Sessions and application data

- Transcripts: `~/.claude/projects/<derived-project>/<session-id>.jsonl`.
- Large tool results: a companion `<session-id>/tool-results/` directory.
- File checkpoints: `~/.claude/file-history/<session-id>/`.
- Prompt recall: `~/.claude/history.jsonl`.
- Default cleanup age: 30 days, configurable with `cleanupPeriodDays`.
- Alternate state root: `CLAUDE_CONFIG_DIR`.

Transcripts are plaintext and can contain file contents, command output,
pasted text, and secrets. mem-sync migrates them only on an explicit `migrate`
command and never treats them as shared memory.

Official sources: [Manage sessions](https://code.claude.com/docs/en/sessions) and
[The `.claude` directory](https://code.claude.com/docs/en/claude-directory).

### Custom system-prompt surfaces

The built-in Claude Code system prompt is runtime product behavior. Supported
customization surfaces include output styles, `--append-system-prompt`, and the
Agent SDK's preset/custom prompt API. `CLAUDE.md` is separate project context.
mem-sync maps only the latter to shared project guidance.

Official sources: [Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts)
and [Output styles](https://code.claude.com/docs/en/output-styles).

## OpenCode

### Project instructions and live updates

OpenCode V2's ambient project-instruction surface is `AGENTS.md`. It loads a
global file from `$XDG_CONFIG_HOME/opencode/AGENTS.md` and the `AGENTS.md` chain
from the current location toward the project and home roots. Nested instruction
files are discovered when OpenCode reads files in those directories. Before
each model attempt, OpenCode reconciles changed ambient instructions and can
inject a replacement system update, so daemon changes do not require restarting
the harness.

This makes the mem-sync adapter intentionally small: OpenCode reads the managed
root `AGENTS.md`, which is the same canonical inode Codex and Claude Code use.
The v0.2 shared-memory protocol tells OpenCode that remember, forget, and cleanup
requests are edits to that file. OpenCode does not document a separate automatic
durable-memory store, so there is no native memory database to harvest.

Official source: [OpenCode V2 instructions](https://opencode.ai/v2/docs/instructions).

### Configuration, agents, and sessions

- Global configuration defaults to `~/.config/opencode/opencode.json` (or the
  XDG equivalent); project configuration may use `opencode.json[c]` and
  `.opencode/` resources.
- Custom agents, skills, commands, plugins, MCP configuration, permissions, and
  provider credentials are executable or machine-specific state and are not
  copied by mem-sync.
- OpenCode persists sessions in local application data. Its supported CLI can
  export and import sessions, and the TUI provides `/move` to change a session's
  project. mem-sync uses that native boundary rather than editing OpenCode's
  live SQLite database.

Official sources: [OpenCode agents](https://opencode.ai/v2/docs/agents),
[OpenCode CLI](https://opencode.ai/docs/cli), and
[session move API](https://v2.opencode.ai/docs/api/session/v2-session-move/).

## Deliberately unsynced

| State | Reason |
| --- | --- |
| Built-in system prompts | Host-owned, not a supported editable file, different tool/safety contracts |
| Credentials and tokens | Secrets; unrelated to durable project context |
| Permission policies | Different semantics and security boundaries |
| Full transcripts | Large, sensitive, agent-specific format; migrated only by explicit command |
| Tool caches/checkpoints | Operational state, not memory |
| User-global instructions | Enabling one project must not mutate higher/global scope |
| Skills, plugins, MCP, hooks | Valuable future adapters, but executable/config state needs explicit conversion and trust review |
