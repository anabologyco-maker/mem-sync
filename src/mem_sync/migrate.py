from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from .codex import rewrite_rollout_session_cwd
from .paths import claude_home, codex_home, codex_sqlite_home, discover_claude_project_dir, latest_versioned_db, resolve_root
from .store import registry_locked


def _lock_is_held(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                pass
    return False


def _path_is_open(path: Path) -> bool:
    """Best-effort Linux check used to avoid rewriting an active Claude log."""
    proc = Path("/proc")
    if not proc.is_dir():
        return False
    target = path.resolve()
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        descriptors = process / "fd"
        try:
            for descriptor in descriptors.iterdir():
                try:
                    if descriptor.resolve() == target:
                        return True
                except OSError:
                    continue
        except (FileNotFoundError, PermissionError):
            continue
    return False


def _migrate_codex(session_id: str, source: Path, target: Path, dry_run: bool) -> dict[str, Any] | None:
    database = latest_versioned_db(codex_sqlite_home(), "state")
    if not database:
        return None
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT cwd, rollout_path FROM threads WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        cwd, rollout_value = row
        if Path(cwd).resolve() != source:
            raise ValueError(f"Codex session {session_id} belongs to {cwd}, not {source}")
        rollout = Path(rollout_value)
        lock = codex_home() / "thread-writer-locks" / f"{session_id}.lock"
        active = _lock_is_held(lock)
        if dry_run:
            return {"agent": "codex", "session_id": session_id, "from": str(source), "to": str(target), "active": active, "pending_rollout_rewrite": active}
        backup_dir = target / ".mem-sync" / "migrations" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{session_id}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_db = backup_dir / database.name
        with sqlite3.connect(backup_db) as destination:
            connection.backup(destination)
        if rollout.exists():
            shutil.copy2(rollout, backup_dir / rollout.name)
        connection.execute("UPDATE threads SET cwd = ? WHERE id = ?", (str(target), session_id))
        connection.commit()
    pending = active
    if rollout.exists() and not active:
        rewrite_rollout_session_cwd(rollout, source, target)
        pending = False
    result = {
        "agent": "codex",
        "session_id": session_id,
        "from": str(source),
        "to": str(target),
        "active": active,
        "pending_rollout_rewrite": pending,
        "rollout_path": str(rollout),
        "backup_dir": str(backup_dir),
    }
    if pending:
        with registry_locked() as (_, registry):
            registry.setdefault("migrations", []).append(result)
    return result


def _rewrite_claude_jsonl(path: Path, source: Path, target: Path) -> None:
    output: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("cwd") == str(source):
            record["cwd"] = str(target)
        output.append(json.dumps(record, separators=(",", ":"), ensure_ascii=False))
    from .store import atomic_write
    atomic_write(path, "\n".join(output) + "\n")


def _migrate_claude(session_id: str, source: Path, target: Path, dry_run: bool) -> dict[str, Any] | None:
    matches = list((claude_home() / "projects").glob(f"*/{session_id}.jsonl"))
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"multiple Claude transcripts match session {session_id}")
    transcript = matches[0]
    source_dir = discover_claude_project_dir(source)
    if transcript.parent.resolve() != source_dir.resolve():
        raise ValueError(f"Claude session {session_id} belongs to {transcript.parent}, not {source}")
    target_dir = discover_claude_project_dir(target)
    destination = target_dir / transcript.name
    active = _path_is_open(transcript)
    if dry_run:
        return {"agent": "claude", "session_id": session_id, "from": str(source), "to": str(target), "active": active, "transcript_from": str(transcript), "transcript_to": str(destination)}
    if active:
        raise ValueError(f"Claude session {session_id} is active; exit it before migrating")
    if destination.exists():
        raise FileExistsError(f"target transcript already exists: {destination}")
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = target / ".mem-sync" / "migrations" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{session_id}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(transcript, backup_dir / transcript.name)
    shutil.copy2(transcript, destination)
    _rewrite_claude_jsonl(destination, source, target)
    companion = transcript.with_suffix("")
    if companion.is_dir():
        shutil.copytree(companion, target_dir / companion.name, dirs_exist_ok=True)
        shutil.rmtree(companion)
    transcript.unlink()
    return {"agent": "claude", "session_id": session_id, "from": str(source), "to": str(target), "transcript": str(destination), "backup_dir": str(backup_dir)}


def migrate(session_id: str, source_value: str, target_value: str, dry_run: bool = False) -> dict[str, Any]:
    source = resolve_root(source_value)
    target = resolve_root(target_value)
    if source == target:
        raise ValueError("source and target are the same directory")
    result = _migrate_codex(session_id, source, target, dry_run)
    if result is None:
        result = _migrate_claude(session_id, source, target, dry_run)
    if result is None:
        raise ValueError(f"session not found in Codex or Claude Code state: {session_id}")
    return result


def finalize_pending_migrations() -> int:
    completed = 0
    with registry_locked() as (_, registry):
        remaining = []
        for migration in registry.get("migrations", []):
            if migration.get("agent") != "codex" or not migration.get("pending_rollout_rewrite"):
                remaining.append(migration)
                continue
            session_id = migration["session_id"]
            lock = codex_home() / "thread-writer-locks" / f"{session_id}.lock"
            if _lock_is_held(lock):
                remaining.append(migration)
                continue
            rollout = Path(migration["rollout_path"])
            if rollout.exists():
                rewrite_rollout_session_cwd(rollout, Path(migration["from"]), Path(migration["to"]))
            completed += 1
        registry["migrations"] = remaining
    return completed
