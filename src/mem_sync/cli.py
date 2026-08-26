from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from . import __version__
from .core import disable, enable, status, sync_project
from .daemon import run as run_daemon
from .migrate import migrate
from .paths import state_home
from .store import read_json


def _print(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _normalize(argv: list[str]) -> list[str]:
    if not argv:
        return ["status"]
    actions = {"on", "off", "status", "sync"}
    if len(argv) >= 2 and argv[1] in actions and argv[0] not in actions:
        return [argv[1], argv[0], *argv[2:]]
    return argv


def _service(action: str) -> str:
    unit = Path("/etc/systemd/system/mem-sync.service")
    if os.geteuid() != 0 or not unit.exists() or not shutil.which("systemctl"):
        return "not-installed"
    result = subprocess.run(
        ["systemctl", action, "mem-sync.service"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return "active" if result.returncode == 0 and action == "start" else ("stopped" if result.returncode == 0 else "error")


def _any_enabled_projects() -> bool:
    registry = read_json(state_home() / "registry.json", {"projects": {}})
    return any(entry.get("enabled") for entry in registry.get("projects", {}).values())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mem-sync",
        description="Project-scoped shared memory for Codex, Claude Code, and OpenCode",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("on", "off", "status", "sync"):
        child = sub.add_parser(command)
        child.add_argument("path", nargs="?", default=os.getcwd())
    daemon = sub.add_parser("daemon")
    daemon.add_argument("--interval", type=float, default=2.0)
    daemon.add_argument("--once", action="store_true")
    migration = sub.add_parser("migrate")
    migration.add_argument("session_id")
    migration.add_argument("source")
    migration.add_argument("target")
    migration.add_argument("--dry-run", action="store_true")
    sub.add_parser("install-service")
    return parser


def install_service() -> dict[str, str]:
    source_unit = Path(__file__).resolve().parents[2] / "systemd" / "mem-sync.service"
    destination = Path("/etc/systemd/system/mem-sync.service")
    if os.geteuid() != 0:
        raise PermissionError("install-service currently requires root; run it with sudo")
    command = Path("/usr/local/bin/mem-sync")
    source_command = Path(__file__).resolve().parents[2] / "bin" / "mem-sync"
    if command.exists() or command.is_symlink():
        if command.resolve() != source_command.resolve():
            raise FileExistsError(f"refusing to replace existing command: {command}")
    else:
        command.symlink_to(source_command)
    shutil.copy2(source_unit, destination)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "mem-sync.service"], check=True)
    return {"command": str(command), "unit": str(destination), "status": "enabled and started"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(_normalize(list(sys.argv[1:] if argv is None else argv)))
    try:
        if args.command == "on":
            result = enable(args.path)
            result["service"] = _service("start")
            _print(result)
        elif args.command == "off":
            result = disable(args.path)
            result["service"] = "active" if _any_enabled_projects() else _service("stop")
            _print(result)
        elif args.command == "status":
            _print(status(args.path))
        elif args.command == "sync":
            _print(sync_project(args.path))
        elif args.command == "daemon":
            return run_daemon(args.interval, args.once)
        elif args.command == "migrate":
            _print(migrate(args.session_id, args.source, args.target, args.dry_run))
        elif args.command == "install-service":
            _print(install_service())
    except (OSError, ValueError, PermissionError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"mem-sync: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
