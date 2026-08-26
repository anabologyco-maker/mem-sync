<!-- mem-sync:protocol:v2:start -->
## Shared agent memory protocol

This project's durable memory is shared by Codex, Claude Code, and OpenCode.
When the user asks any agent to remember something, record the durable fact in
this file. When asked to forget, remove it. When asked to clean or consolidate
memory, rewrite this file to remove stale and duplicate facts while preserving
current decisions. These edits are authoritative shared changes; never restore
older text merely because it existed in a prior version. Keep memory concise,
project-specific, and free of credentials or secrets.
<!-- mem-sync:protocol:v2:end -->

# Shared project memory

Keep stable architecture facts, commands, conventions, decisions, and workflow
knowledge below this heading.
