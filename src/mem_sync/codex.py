from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .core import canonical_file, digest, safe_read, utc_now
from .paths import codex_sqlite_home, latest_versioned_db
from .store import atomic_write, read_json, write_json


def _within(path: str, root: Path) -> bool:
    try:
        candidate = Path(path).resolve()
        return candidate == root or root in candidate.parents
    except OSError:
        return False


def harvest_codex_memories(root: Path, state_path: Path) -> int:
    memory_db = latest_versioned_db(codex_sqlite_home(), "memories")
    state_db = latest_versioned_db(codex_sqlite_home(), "state")
    if not memory_db or not state_db:
        return 0
    state = read_json(state_path, {})
    imported: dict[str, int] = state.setdefault("codex_imports", {})
    with sqlite3.connect(state_db) as state_conn:
        rows = state_conn.execute("SELECT id, cwd FROM threads").fetchall()
    eligible = {thread_id for thread_id, cwd in rows if _within(cwd, root)}
    if not eligible:
        return 0
    placeholders = ",".join("?" for _ in eligible)
    with sqlite3.connect(memory_db) as memory_conn:
        rows = memory_conn.execute(
            f"SELECT thread_id, source_updated_at, raw_memory, rollout_summary "
            f"FROM stage1_outputs WHERE thread_id IN ({placeholders}) ORDER BY source_updated_at",
            tuple(eligible),
        ).fetchall()
    new_rows = [row for row in rows if int(row[1]) > int(imported.get(row[0], 0))]
    if not new_rows:
        return 0
    canonical = canonical_file(root)
    current = safe_read(canonical) or "# Shared project memory\n"
    archive = canonical.parent / "codex"
    archive.mkdir(parents=True, exist_ok=True)
    additions: list[str] = []
    for thread_id, watermark, raw, summary in new_rows:
        body = raw.strip() if raw and raw.strip() else (summary or "").strip()
        if not body:
            imported[thread_id] = int(watermark)
            continue
        atomic_write(archive / f"{thread_id}.md", body + "\n")
        additions.append(f"\n## Imported Codex memory `{thread_id}`\n\n{body}\n")
        imported[thread_id] = int(watermark)
    if additions:
        proposed = current.rstrip() + "\n" + "".join(additions)
        if len(proposed.encode("utf-8")) <= 24_000:
            atomic_write(canonical, proposed)
        else:
            index = "\n## Additional Codex memory\n\nDetailed imported records are under `.mem-sync/memory/codex/`.\n"
            if index.strip() not in current:
                atomic_write(canonical, current.rstrip() + "\n" + index)
    state["codex_imports"] = imported
    state["last_codex_harvest_at"] = utc_now()
    write_json(state_path, state)
    return len(new_rows)


def rewrite_rollout_session_cwd(path: Path, source: Path, target: Path) -> bool:
    # str.splitlines() also breaks on Unicode separators such as U+0085 and
    # U+2028. Those are valid inside JSON strings and are not JSONL record
    # boundaries, so splitting on them would corrupt the transcript.
    lines = path.read_text(encoding="utf-8").split("\n")
    if not lines:
        return False
    changed = False
    output: list[str] = []
    for line in lines:
        if not line:
            continue
        record = json.loads(line)
        if record.get("type") == "session_meta":
            payload = record.get("payload", {})
            if payload.get("cwd") == str(source):
                payload["cwd"] = str(target)
                changed = True
        output.append(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
    if changed:
        atomic_write(path, "".join(output))
    return changed
