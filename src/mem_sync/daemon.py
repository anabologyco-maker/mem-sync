from __future__ import annotations

import logging
from pathlib import Path
import signal
import time

from . import __version__
from .codex import harvest_codex_memories
from .core import sync_project
from .migrate import finalize_pending_migrations
from .paths import resolve_root, state_home
from .store import read_json


LOG = logging.getLogger("mem-sync")


def source_fingerprint() -> str:
    """Identify the code this process loaded, so an update can be noticed."""
    package = Path(__file__).resolve().parent
    parts = []
    for path in sorted(package.glob("*.py")):
        try:
            info = path.stat()
        except OSError:
            continue
        parts.append(f"{path.name}:{info.st_mtime_ns}:{info.st_size}")
    return "|".join(parts)


def run(interval: float = 2.0, once: bool = False) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Python holds the modules imported at startup, so a pulled update sits on
    # disk unapplied until the process is replaced. Exiting on a source change
    # lets the service manager restart into the new code; the unit sets
    # Restart=always so a clean exit still comes back.
    fingerprint = source_fingerprint()
    LOG.info("mem-sync %s daemon starting", __version__)
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        registry = read_json(state_home() / "registry.json", {"projects": {}})
        for root_value, entry in registry.get("projects", {}).items():
            if not entry.get("enabled"):
                continue
            try:
                root = resolve_root(root_value)
                state_path = root / ".mem-sync" / "state.json"
                harvest_codex_memories(root, state_path)
                sync_project(root)
            except Exception:
                LOG.exception("failed to sync %s", root_value)
        try:
            finalize_pending_migrations()
        except Exception:
            LOG.exception("failed to finalize pending migrations")
        if once:
            break
        if source_fingerprint() != fingerprint:
            LOG.info("source changed on disk; exiting so the service restarts on the new code")
            break
        time.sleep(max(interval, 0.2))
    return 0

