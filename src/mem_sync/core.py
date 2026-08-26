from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
from typing import Any

from .paths import discover_claude_project_dir, git_root, resolve_root
from .store import atomic_write, read_json, registry_locked, write_json


SURFACE_NAMES = ("AGENTS.md", "CLAUDE.md")
PROTOCOL_VERSION = 2
PROTOCOL = """<!-- mem-sync:protocol:v2:start -->
## Shared agent memory protocol

This project's durable memory is shared by Codex, Claude Code, and OpenCode.
When the user asks any agent to remember something, record the durable fact in
this file. When asked to forget, remove it. When asked to clean or consolidate
memory, rewrite this file to remove stale and duplicate facts while preserving
current decisions. These edits are authoritative shared changes; never restore
older text merely because it existed in a prior version. Keep memory concise,
project-specific, and free of credentials or secrets.
<!-- mem-sync:protocol:v2:end -->
"""
DEFAULT_MEMORY = """# Shared project memory

Keep stable architecture facts, commands, conventions, decisions, and workflow
knowledge below this heading.
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def with_protocol(content: str) -> str:
    if "<!-- mem-sync:protocol:v2:start -->" in content:
        return content
    return PROTOCOL.rstrip() + "\n\n" + content.lstrip()


def project_dir(root: Path) -> Path:
    return root / ".mem-sync"


def canonical_file(root: Path) -> Path:
    return project_dir(root) / "memory" / "MEMORY.md"


def project_state_file(root: Path) -> Path:
    return project_dir(root) / "state.json"


def safe_read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, UnicodeError):
        return None


def backup_path(path: Path, backup_root: Path, label: str) -> None:
    if not path.exists() and not path.is_symlink():
        return
    target = backup_root / label
    target.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        target.with_suffix(target.suffix + ".symlink").write_text(os.readlink(path), encoding="utf-8")
    elif path.is_dir():
        shutil.copytree(path, target, symlinks=True)
    else:
        shutil.copy2(path, target)


def neutral_merge(sources: list[tuple[str, str]]) -> str:
    nonempty: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, content in sources:
        normalized = content.strip()
        if not normalized or digest(normalized) in seen:
            continue
        seen.add(digest(normalized))
        nonempty.append((name, content.rstrip() + "\n"))
    if not nonempty:
        return DEFAULT_MEMORY
    if len(nonempty) == 1:
        return nonempty[0][1]
    parts = [
        "# Shared project memory\n\n",
        "> mem-sync preserved multiple pre-existing sources without assigning either agent priority.\n",
    ]
    for name, content in nonempty:
        parts.extend((f"\n## Imported from {name}\n\n", content))
    return "".join(parts)


def replace_with_hardlink(path: Path, canonical: Path) -> None:
    if path.exists() and canonical.exists():
        try:
            if os.path.samefile(path, canonical):
                return
        except OSError:
            pass
    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            raise ValueError(f"expected a file but found a directory: {path}")
        path.unlink()
    try:
        os.link(canonical, path)
    except OSError:
        shutil.copy2(canonical, path)


def materialize_file(path: Path, content: str) -> None:
    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            raise ValueError(f"expected a file but found a directory: {path}")
        path.unlink()
    atomic_write(path, content)


def _install_claude_memory_link(root: Path, native_dir: Path, backup_root: Path) -> str:
    target = canonical_file(root).parent
    native_dir.parent.mkdir(parents=True, exist_ok=True)
    if native_dir.is_symlink() and Path(os.path.realpath(native_dir)) == target.resolve():
        return "linked"
    if native_dir.exists() or native_dir.is_symlink():
        backup_path(native_dir, backup_root, "claude-memory")
        if native_dir.is_symlink() or native_dir.is_file():
            native_dir.unlink()
        else:
            for item in native_dir.iterdir():
                destination = target / item.name
                if destination.exists():
                    destination = target / f"claude-{item.name}"
                if item.is_dir():
                    shutil.copytree(item, destination)
                else:
                    shutil.copy2(item, destination)
            shutil.rmtree(native_dir)
    try:
        native_dir.symlink_to(target, target_is_directory=True)
        return "linked"
    except OSError:
        native_dir.mkdir(parents=True, exist_ok=True)
        for item in target.iterdir():
            if item.is_file():
                shutil.copy2(item, native_dir / item.name)
        return "mirrored"


def enable(root_value: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    root = resolve_root(root_value)
    meta = project_dir(root)
    memory = canonical_file(root)
    previous_state = read_json(project_state_file(root), {})
    if previous_state.get("enabled"):
        return sync_project(root)
    meta.mkdir(parents=True, exist_ok=True)
    memory.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backups = meta / "backups" / timestamp

    claude_project = discover_claude_project_dir(root)
    claude_native = claude_project / "memory"
    existing_sources: list[tuple[str, str]] = []
    for name in SURFACE_NAMES:
        content = safe_read(root / name)
        if content is not None:
            existing_sources.append((name, content))
            backup_path(root / name, backups, name)
    current = safe_read(memory)
    if current is not None:
        existing_sources.insert(0, ("canonical memory", current))
    native_memory = safe_read(claude_native / "MEMORY.md")
    if native_memory is not None:
        existing_sources.append(("Claude auto memory", native_memory))

    merged = with_protocol(neutral_merge(existing_sources))
    atomic_write(memory, merged)
    for name in SURFACE_NAMES:
        replace_with_hardlink(root / name, memory)

    repo_root = git_root(root)
    native_mode = "not-linked-nested-root"
    if repo_root is None or repo_root == root:
        native_mode = _install_claude_memory_link(root, claude_native, backups)

    state = {
        "version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "enabled": True,
        "root": str(root),
        "enabled_at": utc_now(),
        "last_sync_at": utc_now(),
        "canonical": str(memory),
        "claude_project_dir": str(claude_project),
        "claude_memory_mode": native_mode,
        "git_root": str(repo_root) if repo_root else None,
        "hashes": {name: digest(merged) for name in (*SURFACE_NAMES, "canonical", "claude-memory")},
        "codex_imports": previous_state.get("codex_imports", {}),
        "conflicts": previous_state.get("conflicts", []),
    }
    write_json(project_state_file(root), state)
    with registry_locked() as (_, registry):
        registry.setdefault("projects", {})[str(root)] = {
            "enabled": True,
            "root": str(root),
            "state_file": str(project_state_file(root)),
            "updated_at": utc_now(),
        }
    return state


def _candidate_files(root: Path, state: dict[str, Any]) -> list[tuple[str, Path]]:
    candidates = [(name, root / name) for name in SURFACE_NAMES]
    candidates.append(("canonical", canonical_file(root)))
    native = Path(state.get("claude_project_dir", "")) / "memory" / "MEMORY.md"
    if state.get("claude_memory_mode") == "mirrored":
        candidates.append(("claude-memory", native))
    return candidates


def sync_project(root_value: str | os.PathLike[str]) -> dict[str, Any]:
    root = resolve_root(root_value)
    state_path = project_state_file(root)
    state = read_json(state_path, {})
    if not state.get("enabled"):
        raise ValueError(f"mem-sync is not enabled for {root}")

    candidates = _candidate_files(root, state)
    previous = state.get("hashes", {})
    changed: list[tuple[str, str]] = []
    available: list[tuple[str, str]] = []
    for name, path in candidates:
        content = safe_read(path)
        if content is None:
            continue
        available.append((name, content))
        if digest(content) != previous.get(name):
            changed.append((name, content))

    unique_changed = {digest(content): (name, content) for name, content in changed}
    if len(unique_changed) == 1:
        merged = next(iter(unique_changed.values()))[1]
    elif len(unique_changed) > 1:
        conflict_dir = project_dir(root) / "conflicts" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        conflict_dir.mkdir(parents=True, exist_ok=True)
        for name, content in changed:
            atomic_write(conflict_dir / name.replace("/", "_"), content)
        merged = neutral_merge(changed)
        state.setdefault("conflicts", []).append(str(conflict_dir))
    else:
        merged = safe_read(canonical_file(root)) or neutral_merge(available)

    # Upgrade existing enabled projects exactly once. After recording the
    # version, later user/agent cleanup remains authoritative even if it removes
    # or rewrites this protocol block.
    if int(state.get("protocol_version", 1)) < PROTOCOL_VERSION:
        merged = with_protocol(merged)
        state["protocol_version"] = PROTOCOL_VERSION

    atomic_write(canonical_file(root), merged)
    for name in SURFACE_NAMES:
        replace_with_hardlink(root / name, canonical_file(root))
    if state.get("claude_memory_mode") == "mirrored":
        native = Path(state["claude_project_dir"]) / "memory" / "MEMORY.md"
        atomic_write(native, merged)

    current_hash = digest(merged)
    state["hashes"] = {name: current_hash for name, _ in candidates}
    state["last_sync_at"] = utc_now()
    write_json(state_path, state)
    return state


def disable(root_value: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    root = resolve_root(root_value)
    state_path = project_state_file(root)
    state = read_json(state_path, {})
    if not state.get("enabled"):
        raise ValueError(f"mem-sync is not enabled for {root}")
    sync_project(root)
    content = safe_read(canonical_file(root)) or DEFAULT_MEMORY
    for name in SURFACE_NAMES:
        materialize_file(root / name, content)

    native_dir = Path(state.get("claude_project_dir", "")) / "memory"
    if native_dir.is_symlink():
        target = Path(os.path.realpath(native_dir))
        native_dir.unlink()
        shutil.copytree(target, native_dir)
    elif state.get("claude_memory_mode") == "mirrored":
        atomic_write(native_dir / "MEMORY.md", content)

    state["enabled"] = False
    state["disabled_at"] = utc_now()
    state["last_sync_at"] = utc_now()
    write_json(state_path, state)
    with registry_locked() as (_, registry):
        entry = registry.setdefault("projects", {}).setdefault(str(root), {})
        entry.update({"enabled": False, "root": str(root), "state_file": str(state_path), "updated_at": utc_now()})
    return state


def status(root_value: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    root = resolve_root(root_value)
    state = read_json(project_state_file(root), {"version": 1, "enabled": False, "root": str(root)})
    state["surfaces"] = {}
    canonical = canonical_file(root)
    for name in SURFACE_NAMES:
        path = root / name
        linked = False
        try:
            linked = canonical.exists() and path.exists() and os.path.samefile(path, canonical)
        except OSError:
            pass
        state["surfaces"][name] = {"exists": path.exists(), "hardlinked": linked}
    shadow_candidates = (
        root / "AGENTS.override.md",
        root / "CLAUDE.local.md",
        root / ".claude" / "CLAUDE.md",
    )
    state["shadowing_files"] = [
        str(path) for path in shadow_candidates if (safe_read(path) or "").strip()
    ]
    state["adapters"] = {
        "codex": {
            "installed": shutil.which("codex") is not None,
            "instruction_surface": "AGENTS.md",
            "native_memory_harvest": True,
        },
        "claude-code": {
            "installed": shutil.which("claude") is not None,
            "instruction_surface": "CLAUDE.md",
            "native_memory_linked": state.get("claude_memory_mode") == "linked",
        },
        "opencode": {
            "installed": shutil.which("opencode") is not None,
            "instruction_surface": "AGENTS.md",
            "native_memory_harvest": False,
            "live_instruction_updates": True,
        },
    }
    return state
