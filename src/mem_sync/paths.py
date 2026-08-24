from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess


def resolve_root(value: str | os.PathLike[str] | None = None) -> Path:
    root = Path(value or os.getcwd()).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project path is not a directory: {root}")
    return root


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().resolve()


def codex_sqlite_home() -> Path:
    return Path(os.environ.get("CODEX_SQLITE_HOME", str(codex_home()))).expanduser().resolve()


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser().resolve()


def state_home() -> Path:
    override = os.environ.get("MEM_SYNC_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.geteuid() == 0:
        return Path("/var/lib/mem-sync")
    xdg = os.environ.get("XDG_STATE_HOME")
    return Path(xdg).expanduser().resolve() / "mem-sync" if xdg else Path("~/.local/state/mem-sync").expanduser().resolve()


def git_root(path: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        return None
    return Path(result.stdout.strip()).resolve()


def claude_project_key(path: Path) -> str:
    """Return Claude Code's common path-derived project key.

    Claude does not document this encoding as a stable API. Existing transcript
    directories are discovered by content before this fallback is used.
    """
    return re.sub(r"[^A-Za-z0-9-]", "-", str(path.resolve()))


def discover_claude_project_dir(root: Path) -> Path:
    projects = claude_home() / "projects"
    if projects.is_dir():
        for candidate in projects.iterdir():
            if not candidate.is_dir():
                continue
            for transcript in candidate.glob("*.jsonl"):
                try:
                    with transcript.open("r", encoding="utf-8") as handle:
                        for _ in range(20):
                            line = handle.readline()
                            if not line:
                                break
                            if f'"cwd":"{root}"' in line or f'"cwd": "{root}"' in line:
                                return candidate
                except (OSError, UnicodeError):
                    continue
    return projects / claude_project_key(root)


def latest_versioned_db(directory: Path, stem: str) -> Path | None:
    matches: list[tuple[int, Path]] = []
    for path in directory.glob(f"{stem}_*.sqlite"):
        match = re.fullmatch(rf"{re.escape(stem)}_(\d+)\.sqlite", path.name)
        if match:
            matches.append((int(match.group(1)), path))
    return max(matches, default=(0, None))[1]

