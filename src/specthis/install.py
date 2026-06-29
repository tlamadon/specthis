"""Scaffolder: copy bundled templates into a project directory."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

AGENT_NAMES = ("spec-auditor", "spec-implementer", "experiment-runner")
SPEC_TEMPLATE_NAMES = ("README.md", "AGENTS.md")


def _read_template(subdir: str, filename: str) -> str:
    """Read a bundled template file from the installed package."""
    package = f"specthis.templates.{subdir}"
    return resources.files(package).joinpath(filename).read_text(encoding="utf-8")


def install_agents(
    project_path: Path,
    force: bool = False,
    agents: list[str] | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Copy agent templates into ``<project_path>/.claude/agents/``.

    Returns ``(installed, skipped)`` where ``installed`` is a list of agent
    names written and ``skipped`` is a list of ``(name, reason)``.
    """
    selected = agents or list(AGENT_NAMES)
    target_dir = project_path / ".claude" / "agents"
    target_dir.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    skipped: list[tuple[str, str]] = []
    for name in selected:
        if name not in AGENT_NAMES:
            skipped.append((name, "unknown agent"))
            continue
        target = target_dir / f"{name}.md"
        if target.exists() and not force:
            skipped.append((name, "already exists; use --force"))
            continue
        body = _read_template("agents", f"{name}.md")
        target.write_text(body, encoding="utf-8")
        installed.append(name)
    return installed, skipped


def init_specs_dir(
    project_path: Path,
    force: bool = False,
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Create ``<project_path>/specs/`` with the README and AGENTS templates.

    Returns ``(created, skipped)``.
    """
    target_dir = project_path / "specs"
    target_dir.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    for filename in SPEC_TEMPLATE_NAMES:
        target = target_dir / filename
        if target.exists() and not force:
            skipped.append((target, "already exists; use --force"))
            continue
        body = _read_template("specs", filename)
        target.write_text(body, encoding="utf-8")
        created.append(target)
    return created, skipped
