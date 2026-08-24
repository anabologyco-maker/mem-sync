# Shared project memory

This file is the project-scoped durable context shared by Codex and Claude Code.
Both agents may update it. Keep stable architecture facts, commands, conventions,
decisions, and workflow knowledge here; do not store credentials or secrets.
Cleanup, consolidation, rewrites, and deletions are authoritative shared changes:
do not restore stale entries merely because they appeared in an older version.
