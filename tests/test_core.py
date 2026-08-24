from __future__ import annotations

import json
import os
from pathlib import Path

from mem_sync.core import disable, enable, status, sync_project


def configure(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    claude = tmp_path / "claude"
    codex = tmp_path / "codex"
    state = tmp_path / "state"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setenv("CODEX_SQLITE_HOME", str(codex))
    monkeypatch.setenv("MEM_SYNC_STATE_DIR", str(state))
    return project, claude


def test_enable_merges_without_priority_and_links_surfaces(monkeypatch, tmp_path):
    project, claude = configure(monkeypatch, tmp_path)
    (project / "AGENTS.md").write_text("Codex fact\n", encoding="utf-8")
    (project / "CLAUDE.md").write_text("Claude fact\n", encoding="utf-8")

    result = enable(project)

    shared = (project / ".mem-sync/memory/MEMORY.md").read_text(encoding="utf-8")
    assert "Codex fact" in shared and "Claude fact" in shared
    assert os.path.samefile(project / "AGENTS.md", project / "CLAUDE.md")
    assert result["enabled"] is True
    assert status(project)["surfaces"]["AGENTS.md"]["hardlinked"] is True


def test_daemon_repairs_atomic_save(monkeypatch, tmp_path):
    project, _ = configure(monkeypatch, tmp_path)
    enable(project)
    replacement = project / "replacement"
    replacement.write_text("new durable fact\n", encoding="utf-8")
    os.replace(replacement, project / "CLAUDE.md")

    sync_project(project)

    assert (project / "AGENTS.md").read_text(encoding="utf-8") == "new durable fact\n"
    assert os.path.samefile(project / "AGENTS.md", project / "CLAUDE.md")


def test_off_preserves_bytes_and_breaks_links(monkeypatch, tmp_path):
    project, _ = configure(monkeypatch, tmp_path)
    enable(project)
    (project / "AGENTS.md").write_text("final state\n", encoding="utf-8")

    result = disable(project)

    assert result["enabled"] is False
    assert (project / "AGENTS.md").read_text(encoding="utf-8") == "final state\n"
    assert (project / "CLAUDE.md").read_text(encoding="utf-8") == "final state\n"
    assert not os.path.samefile(project / "AGENTS.md", project / "CLAUDE.md")


def test_on_is_idempotent_and_preserves_import_watermarks(monkeypatch, tmp_path):
    project, _ = configure(monkeypatch, tmp_path)
    enable(project)
    state_path = project / ".mem-sync/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["codex_imports"] = {"thread": 42}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = enable(project)

    assert result["codex_imports"] == {"thread": 42}
