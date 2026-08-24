from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from mem_sync.migrate import migrate


def test_codex_session_migration(monkeypatch, tmp_path):
    source = tmp_path / "old"
    target = tmp_path / "new"
    source.mkdir()
    target.mkdir()
    codex = tmp_path / "codex"
    sessions = codex / "sessions"
    sessions.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setenv("CODEX_SQLITE_HOME", str(codex))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("MEM_SYNC_STATE_DIR", str(tmp_path / "state"))
    rollout = sessions / "rollout.jsonl"
    rollout.write_text(json.dumps({"type": "session_meta", "payload": {"cwd": str(source)}}) + "\n", encoding="utf-8")
    database = codex / "state_5.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, cwd TEXT, rollout_path TEXT)")
        connection.execute("INSERT INTO threads VALUES (?, ?, ?)", ("abc", str(source), str(rollout)))

    result = migrate("abc", str(source), str(target))

    assert result["agent"] == "codex"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT cwd FROM threads WHERE id='abc'").fetchone()[0] == str(target)
    record = json.loads(rollout.read_text(encoding="utf-8"))
    assert record["payload"]["cwd"] == str(target)


def test_migration_validates_source(monkeypatch, tmp_path):
    actual = tmp_path / "actual"
    wrong = tmp_path / "wrong"
    target = tmp_path / "target"
    for path in (actual, wrong, target):
        path.mkdir()
    codex = tmp_path / "codex"
    codex.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setenv("CODEX_SQLITE_HOME", str(codex))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    database = codex / "state_1.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, cwd TEXT, rollout_path TEXT)")
        connection.execute("INSERT INTO threads VALUES ('abc', ?, '/missing')", (str(actual),))

    try:
        migrate("abc", str(wrong), str(target))
    except ValueError as error:
        assert "belongs to" in str(error)
    else:
        raise AssertionError("expected source validation failure")


def test_claude_session_migration(monkeypatch, tmp_path):
    source = tmp_path / "old"
    target = tmp_path / "new"
    source.mkdir()
    target.mkdir()
    codex = tmp_path / "codex"
    codex.mkdir()
    claude = tmp_path / "claude"
    source_bucket = claude / "projects" / str(source).replace("/", "-")
    source_bucket.mkdir(parents=True)
    transcript = source_bucket / "claude-session.jsonl"
    transcript.write_text(json.dumps({"cwd": str(source), "type": "user"}) + "\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setenv("CODEX_SQLITE_HOME", str(codex))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("MEM_SYNC_STATE_DIR", str(tmp_path / "state"))

    result = migrate("claude-session", str(source), str(target))

    moved = Path(result["transcript"])
    assert result["agent"] == "claude"
    assert moved.exists() and not transcript.exists()
    assert json.loads(moved.read_text(encoding="utf-8"))["cwd"] == str(target)
