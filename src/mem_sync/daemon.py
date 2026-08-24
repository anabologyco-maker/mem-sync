from __future__ import annotations

import logging
import signal
import time

from .codex import harvest_codex_memories
from .core import sync_project
from .migrate import finalize_pending_migrations
from .paths import resolve_root, state_home
from .store import read_json


LOG = logging.getLogger("mem-sync")


def run(interval: float = 2.0, once: bool = False) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
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
        time.sleep(max(interval, 0.2))
    return 0

