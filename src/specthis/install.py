"""Scaffolder: copy bundled templates into a project directory."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

AGENT_NAMES = (
    "spec-auditor",
    "spec-reader",
    "spec-implementer",
    "experiment-runner",
    "spec-critic",
)
COMMAND_NAMES = (
    "specthis-vouch",
    "specthis-run",
    "specthis-lint",
    "specthis-journal",
    "specthis-yolo",
)
SPEC_TEMPLATE_NAMES = ("README.md", "AGENTS.md")
WORKFLOW_NAMES = ("badges",)
HOOK_NAMES = ("yolo_stop",)

#: How Claude Code is told to run the hook. ``$CLAUDE_PROJECT_DIR`` is
#: expanded by the harness, so the entry survives being run from a
#: subdirectory — and doubles as the key for "is it already installed",
#: since matching on the command is what makes a re-install idempotent.
HOOK_COMMAND = 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/yolo_stop.py"'


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


def install_commands(
    project_path: Path,
    force: bool = False,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Copy slash-command templates into ``<project_path>/.claude/commands/``.

    Returns ``(installed, skipped)`` like :func:`install_agents`.
    """
    target_dir = project_path / ".claude" / "commands"
    target_dir.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    skipped: list[tuple[str, str]] = []
    for name in COMMAND_NAMES:
        target = target_dir / f"{name}.md"
        if target.exists() and not force:
            skipped.append((name, "already exists; use --force"))
            continue
        body = _read_template("commands", f"{name}.md")
        target.write_text(body, encoding="utf-8")
        installed.append(name)
    return installed, skipped


def install_hooks(
    project_path: Path,
    force: bool = False,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Install the Stop hook `/specthis-yolo` needs, and register it.

    Two writes, not one: the script into ``.claude/hooks/``, and an entry
    in ``.claude/settings.json`` pointing at it. The second is the part
    that needs care — settings.json is the user's file, may already carry
    unrelated hooks from other tools, and merges with their global
    settings rather than replacing them. So this reads what is there,
    appends one entry, and rewrites; it never authors the file wholesale.

    The hook is inert until `/specthis-yolo` arms it: with no
    ``.specthis/auto.json`` it allows every stop, so installing it
    changes nothing about a normal session.

    Returns ``(installed, skipped)`` like :func:`install_agents`.
    """
    target_dir = project_path / ".claude" / "hooks"
    target_dir.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    skipped: list[tuple[str, str]] = []
    for name in HOOK_NAMES:
        target = target_dir / f"{name}.py"
        if target.exists() and not force:
            skipped.append((name, "already exists; use --force"))
            continue
        body = _read_template("hooks", f"{name}.py")
        target.write_text(body, encoding="utf-8")
        target.chmod(0o755)
        installed.append(name)

    settings_path = project_path / ".claude" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        settings = {}
    except (OSError, ValueError):
        settings = None
    if not isinstance(settings, dict):
        # Unreadable, or not an object. Refuse rather than overwrite: the
        # command still works without registration, and a clobbered
        # settings file is not so easily undone.
        skipped.append(("settings.json", "unreadable — add the Stop hook by hand"))
        return installed, skipped

    hooks = settings.setdefault("hooks", {})
    stop = hooks.setdefault("Stop", [])
    already = any(
        h.get("command") == HOOK_COMMAND
        for group in stop
        if isinstance(group, dict)
        for h in group.get("hooks", [])
        if isinstance(h, dict)
    )
    if already:
        skipped.append(("settings.json", "Stop hook already registered"))
    else:
        stop.append({"hooks": [{"type": "command", "command": HOOK_COMMAND}]})
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        installed.append("settings.json (Stop hook)")
    return installed, skipped


def install_workflows(
    project_path: Path,
    force: bool = False,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Copy the CI workflow templates into ``<project_path>/.github/workflows/``.

    Opt-in, unlike the agents: a workflow pushes a branch under the
    repo's own token, which is not something a scaffolder should arrange
    without being asked.

    Returns ``(installed, skipped)`` like :func:`install_agents`.
    """
    target_dir = project_path / ".github" / "workflows"
    target_dir.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    skipped: list[tuple[str, str]] = []
    for name in WORKFLOW_NAMES:
        target = target_dir / f"{name}.yml"
        if target.exists() and not force:
            skipped.append((name, "already exists; use --force"))
            continue
        body = _read_template("workflows", f"{name}.yml")
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
