from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from mem_sync.core import PROTOCOL_VERSION, disable, enable, status, sync_project


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
    assert "Codex, Claude Code, and OpenCode" in shared
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


def test_claude_cleanup_is_authoritative_and_does_not_restore_removed_text(monkeypatch, tmp_path):
    project, _ = configure(monkeypatch, tmp_path)
    result = enable(project)
    native_memory = Path(result["claude_project_dir"]) / "memory" / "MEMORY.md"
    native_memory.write_text(
        "# Memory\n\n- current fact\n- stale fact\n- duplicate fact\n- duplicate fact\n",
        encoding="utf-8",
    )
    sync_project(project)

    # Claude may save a cleanup by atomically replacing MEMORY.md, which breaks
    # the AGENTS/CLAUDE hard link until the next daemon pass.
    replacement = native_memory.parent / "MEMORY.cleaned"
    replacement.write_text("# Memory\n\n- current fact\n", encoding="utf-8")
    os.replace(replacement, native_memory)
    sync_project(project)
    sync_project(project)

    expected = "# Memory\n\n- current fact\n"
    assert (project / "AGENTS.md").read_text(encoding="utf-8") == expected
    assert (project / "CLAUDE.md").read_text(encoding="utf-8") == expected
    assert "stale fact" not in native_memory.read_text(encoding="utf-8")


def test_existing_project_gets_one_time_opencode_protocol_upgrade(monkeypatch, tmp_path):
    project, _ = configure(monkeypatch, tmp_path)
    enable(project)
    state_path = project / ".mem-sync/state.json"
    canonical = project / ".mem-sync/memory/MEMORY.md"

    # Simulate a project enabled by v0.1, before OpenCode was explicit.
    canonical.write_text("# Existing memory\n\n- keep this fact\n", encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.pop("protocol_version", None)
    old_hash = hashlib.sha256(canonical.read_bytes()).hexdigest()
    state["hashes"] = {name: old_hash for name in ("AGENTS.md", "CLAUDE.md", "canonical")}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    upgraded = sync_project(project)
    first = canonical.read_text(encoding="utf-8")
    sync_project(project)
    second = canonical.read_text(encoding="utf-8")

    assert upgraded["protocol_version"] == PROTOCOL_VERSION
    assert first.count("mem-sync:protocol:v2:start") == 1
    assert "keep this fact" in first
    assert second == first


def test_status_declares_opencode_instruction_adapter(monkeypatch, tmp_path):
    project, _ = configure(monkeypatch, tmp_path)
    enable(project)

    adapter = status(project)["adapters"]["opencode"]

    assert adapter["instruction_surface"] == "AGENTS.md"
    assert adapter["live_instruction_updates"] is True
    assert adapter["native_memory_harvest"] is False


def test_opencode_agents_edit_propagates_to_claude(monkeypatch, tmp_path):
    project, _ = configure(monkeypatch, tmp_path)
    enable(project)

    # OpenCode edits AGENTS.md, often via atomic rename.
    replacement = project / "AGENTS.new"
    replacement.write_text("# Clean shared memory\n\n- OpenCode decision\n", encoding="utf-8")
    os.replace(replacement, project / "AGENTS.md")
    sync_project(project)

    expected = "# Clean shared memory\n\n- OpenCode decision\n"
    assert (project / "CLAUDE.md").read_text(encoding="utf-8") == expected
    native = Path(status(project)["claude_project_dir"]) / "memory" / "MEMORY.md"
    assert native.read_text(encoding="utf-8") == expected
