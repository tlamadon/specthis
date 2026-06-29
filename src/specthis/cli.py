"""specthis command-line entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__
from .install import install_agents, init_specs_dir


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="specthis")
def main() -> None:
    """Spec-driven research workflow: dashboard, agents, refresh pipeline."""


@main.command("install")
@click.option(
    "--path",
    "project_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path.cwd(),
    show_default="current directory",
    help="Project root in which to install .claude/agents/.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing agent files.",
)
@click.option(
    "--agent",
    "selected",
    multiple=True,
    type=click.Choice(["spec-auditor", "spec-implementer", "experiment-runner"]),
    help="Install only the named agent(s). Repeatable. Default: all three.",
)
def install_cmd(project_path: Path, force: bool, selected: tuple[str, ...]) -> None:
    """Copy the specthis subagent templates into <project>/.claude/agents/."""
    installed, skipped = install_agents(
        project_path=project_path,
        force=force,
        agents=list(selected) if selected else None,
    )
    for name in installed:
        click.echo(f"  installed  {name}")
    for name, reason in skipped:
        click.echo(f"  skipped    {name}  ({reason})", err=True)
    if not installed and skipped:
        click.echo("\nNothing changed. Re-run with --force to overwrite.", err=True)
        sys.exit(1)


@main.command("init")
@click.option(
    "--path",
    "project_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path.cwd(),
    show_default="current directory",
    help="Project root in which to create specs/.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing template files in specs/.",
)
def init_cmd(project_path: Path, force: bool) -> None:
    """Create specs/ with README.md and AGENTS.md spec-format templates."""
    created, skipped = init_specs_dir(project_path=project_path, force=force)
    for path in created:
        click.echo(f"  created    {path}")
    for path, reason in skipped:
        click.echo(f"  skipped    {path}  ({reason})", err=True)


@main.command("audit")
@click.option(
    "--specs",
    "specs_dir",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    default=Path("specs"),
    show_default=True,
    help="specs/ directory to audit.",
)
def audit_cmd(specs_dir: Path) -> None:
    """Run the consistency audit over specs/. (stub — port pending)"""
    click.echo(
        f"specthis audit: not yet implemented. Would audit {specs_dir}.\n"
        "Until then, invoke the spec-auditor subagent in Claude Code.",
        err=True,
    )
    sys.exit(2)


@main.command("refresh")
@click.option(
    "--specs",
    "specs_dir",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    default=Path("specs"),
    show_default=True,
)
def refresh_cmd(specs_dir: Path) -> None:
    """Re-run stale entries respecting the lock file. (stub — port pending)"""
    click.echo("specthis refresh: not yet implemented.", err=True)
    sys.exit(2)


@main.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=int, default=8765, show_default=True)
def serve_cmd(host: str, port: int) -> None:
    """Serve the specs.html dashboard with live reload. (stub — port pending)"""
    click.echo("specthis serve: not yet implemented.", err=True)
    sys.exit(2)


@main.command("lock")
@click.argument("subcommand", type=click.Choice(["status", "record", "clear"]))
@click.argument("entry", required=False)
def lock_cmd(subcommand: str, entry: str | None) -> None:
    """Manage the spec inputs_certified content-hash lock. (stub — port pending)"""
    click.echo(f"specthis lock {subcommand}: not yet implemented.", err=True)
    sys.exit(2)


if __name__ == "__main__":
    main()
