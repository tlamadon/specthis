"""Smoke tests for `specthis install` and `specthis init`."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from specthis.cli import main
from specthis.install import (
    AGENT_NAMES,
    COMMAND_NAMES,
    init_specs_dir,
    install_agents,
    install_commands,
)


def test_install_writes_all_agents(tmp_path: Path) -> None:
    installed, skipped = install_agents(project_path=tmp_path)
    assert sorted(installed) == sorted(AGENT_NAMES)
    assert skipped == []
    for name in AGENT_NAMES:
        target = tmp_path / ".claude" / "agents" / f"{name}.md"
        assert target.exists(), f"{name} should have been written"
        body = target.read_text(encoding="utf-8")
        assert body.startswith("---"), "agent template must carry YAML frontmatter"
        assert f"name: {name}" in body


def test_install_writes_commands(tmp_path: Path) -> None:
    installed, skipped = install_commands(project_path=tmp_path)
    assert installed == list(COMMAND_NAMES)
    assert skipped == []
    body = (tmp_path / ".claude" / "commands" / "specthis-vouch.md").read_text()
    assert "spec-critic" in body
    # idempotent without force
    installed, skipped = install_commands(project_path=tmp_path)
    assert installed == [] and len(skipped) == len(COMMAND_NAMES)


def test_critic_carries_the_license_conditions(tmp_path: Path) -> None:
    install_agents(project_path=tmp_path, agents=["spec-critic"])
    body = (tmp_path / ".claude" / "agents" / "spec-critic.md").read_text()
    assert 'spec-critic (for <name>)' in body  # attester convention
    assert "DOUBT" in body  # doubts never touch the ledger


def test_install_is_idempotent_without_force(tmp_path: Path) -> None:
    install_agents(project_path=tmp_path)
    installed, skipped = install_agents(project_path=tmp_path)
    assert installed == []
    assert len(skipped) == len(AGENT_NAMES)


def test_install_force_overwrites(tmp_path: Path) -> None:
    install_agents(project_path=tmp_path)
    target = tmp_path / ".claude" / "agents" / "spec-auditor.md"
    target.write_text("clobbered", encoding="utf-8")
    installed, _ = install_agents(project_path=tmp_path, force=True)
    assert "spec-auditor" in installed
    assert target.read_text(encoding="utf-8").startswith("---")


def test_install_selected_agent_only(tmp_path: Path) -> None:
    installed, skipped = install_agents(
        project_path=tmp_path, agents=["spec-auditor"]
    )
    assert installed == ["spec-auditor"]
    assert skipped == []
    assert (tmp_path / ".claude" / "agents" / "spec-auditor.md").exists()
    assert not (tmp_path / ".claude" / "agents" / "spec-implementer.md").exists()


def test_init_creates_specs_templates(tmp_path: Path) -> None:
    created, skipped = init_specs_dir(project_path=tmp_path)
    assert (tmp_path / "specs" / "README.md") in created
    assert (tmp_path / "specs" / "AGENTS.md") in created
    assert skipped == []
    body = (tmp_path / "specs" / "AGENTS.md").read_text(encoding="utf-8")
    assert "Four named operations" in body


def test_cli_install_runs(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["install", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "agents" / "spec-auditor.md").exists()
    assert (tmp_path / ".claude" / "agents" / "spec-critic.md").exists()
    assert (tmp_path / ".claude" / "commands" / "specthis-vouch.md").exists()


def test_cli_install_agent_filter_skips_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main, ["install", "--path", str(tmp_path), "--agent", "spec-auditor"]
    )
    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".claude" / "commands").exists()


def test_cli_init_runs(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "specs" / "README.md").exists()
