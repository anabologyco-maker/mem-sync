"""Compatibility metadata for build frontends that do not consume PEP 621."""

from setuptools import find_packages, setup


setup(
    name="codex-claude-mem-sync",
    version="0.2.0",
    description="Project-scoped shared memory for Codex, Claude Code, and OpenCode",
    packages=find_packages("src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    entry_points={"console_scripts": ["mem-sync=mem_sync.cli:main"]},
)
