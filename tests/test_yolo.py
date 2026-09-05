"""The `/specthis-yolo` driver: the JSON porcelain and the Stop hook.

The hook is what makes the loop survive an agent that would otherwise
stop early, so the tests that matter most here are the ways it *ends* a
run — budget, deadline, convergence, stall — plus the one case that
would make it useless in practice: compute already in flight must let the
turn end, or the loop spins against a cluster.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis.cli import main
from specthis.install import COMMAND_NAMES, install_hooks

from .conftest import COMPUTE_ALPHA, FIT_ALPHA_PY, fake_run, vouch_ok, write
from .test_templates import templated

HOOK = Path(__file__).parent.parent / "src" / "specthis" / "templates" / "hooks" / "yolo_stop.py"


def check_json(root: Path) -> dict:
    result = CliRunner().invoke(main, ["check", "--json", "--path", str(root)])
    return json.loads(result.output)


@pytest.fixture
def specthis_bin(tmp_path: Path) -> str:
    """A `specthis` the hook can exec, without depending on PATH.

    The hook shells out on purpose — it runs in the editor's environment,
    not the project's — so the test gives it a real console script rather
    than monkeypatching the call away.
    """
    shim = tmp_path / "specthis-shim"
    shim.write_text(
        f"#!{sys.executable}\nfrom specthis.cli import main\nmain()\n", encoding="utf-8"
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return str(shim)


def run_hook(root: Path, specthis_bin: str, path: str | None = None) -> dict:
    env = {**os.environ, "SPECTHIS_BIN": specthis_bin}
    if path is not None:
        env["PATH"] = path
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"cwd": str(root), "hook_event_name": "Stop"}),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def arm(root: Path, **fields) -> Path:
    path = root / ".specthis" / "auto.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    sentinel = {"active": True, "iterations_left": 40, **fields}
    path.write_text(json.dumps(sentinel), encoding="utf-8")
    return path


def sentinel_of(root: Path) -> dict:
    return json.loads((root / ".specthis" / "auto.json").read_text(encoding="utf-8"))


def decision(out: dict) -> str | None:
    return out.get("hookSpecificOutput", {}).get("decision")


def converge(root: Path) -> None:
    """Bring the fixture project to ready on both trees."""
    for entry in ("fit-alpha", "fit-beta", "fig-beta"):
        vouch_ok(root, entry)
        fake_run(root, entry)


def drive(root: Path, specthis_bin: str) -> int:
    """Stand in for the agent: do only what the hook's reason names.

    Each round re-reads the queues, because they change underneath it —
    which is the behaviour under test. Returns the number of rounds.
    """
    rounds = 0
    while decision(run_hook(root, specthis_bin)) == "block":
        rounds += 1
        assert rounds < 20, "not converging"
        state = check_json(root)
        for item in state["mind"]:
            vouch_ok(root, item["entry"])  # stands in for a fresh critic
        for item in state["machine"]:
            fake_run(root, item["entry"])  # stands in for the manager
    return rounds


# ------------------------------------------------------------ the porcelain


def test_check_json_reports_both_queues(root: Path) -> None:
    state = check_json(root)
    assert state["verdict"] == "work"
    assert {m["entry"] for m in state["mind"]} == {"fit-alpha", "fit-beta", "fig-beta"}
    assert {m["entry"] for m in state["machine"]} == {"fit-alpha", "fit-beta", "fig-beta"}
    assert state["lint"] == {"problems": 0, "messages": []}
    assert state["ready"] == "0/3"
    assert state["fingerprint"]


def test_check_json_names_template_instances(root: Path) -> None:
    """The queues are keyed by instance, and the porcelain must say so.

    `specs/_index.json` looks up reports by entry name and so reports
    every instance as `skipped`; a driver inheriting that would decide a
    templated project had nothing to do.
    """
    templated(root)
    state = check_json(root)
    named = {m["entry"] for m in state["mind"]}
    assert "clean-wages[dataset=chile]" in named
    assert "clean-wages[dataset=argentina]" in named
    assert "clean-wages" not in named, "the template itself is not a claim unit"


def test_check_json_verdict_is_done_when_converged(root: Path) -> None:
    converge(root)
    state = check_json(root)
    assert state["verdict"] == "done"
    assert state["mind"] == [] and state["machine"] == []
    assert state["ready"] == "3/3"


def test_check_json_verdict_is_blocked_when_only_a_rejection_remains(root: Path) -> None:
    converge(root)
    CliRunner().invoke(
        main, ["vouch", "fig-beta", "--as", "ben", "--reject", "--path", str(root)]
    )
    state = check_json(root)
    assert state["verdict"] == "blocked"
    assert [b["entry"] for b in state["blocked"]] == ["fig-beta"]


def test_check_json_fingerprint_moves_on_a_vouch(root: Path) -> None:
    before = check_json(root)["fingerprint"]
    assert check_json(root)["fingerprint"] == before, "must be deterministic"
    vouch_ok(root, "fit-alpha")
    after = check_json(root)
    assert after["fingerprint"] != before
    # ...even though nothing became ready: progress the loop must notice.
    assert after["ready"] == "0/3"


def test_check_json_keeps_the_exit_code(root: Path) -> None:
    """Formatting does not change what the verb says about the project."""
    runner = CliRunner()
    assert runner.invoke(main, ["check", "--json", "--path", str(root)]).exit_code == 1
    converge(root)
    assert runner.invoke(main, ["check", "--json", "--path", str(root)]).exit_code == 0


# ---------------------------------------------------------------- install


def test_install_hooks_registers_without_clobbering(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(git status)"]},
                "hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "x"}]}]},
            }
        ),
        encoding="utf-8",
    )
    installed, _ = install_hooks(project_path=tmp_path)
    assert "yolo_stop" in installed

    hook = tmp_path / ".claude" / "hooks" / "yolo_stop.py"
    assert hook.exists()
    assert hook.stat().st_mode & stat.S_IXUSR, "a hook the harness cannot exec is no hook"

    merged = json.loads(settings.read_text(encoding="utf-8"))
    assert merged["permissions"] == {"allow": ["Bash(git status)"]}
    assert merged["hooks"]["PostToolUse"], "an unrelated hook must survive"
    assert len(merged["hooks"]["Stop"]) == 1


def test_install_hooks_does_not_double_register(tmp_path: Path) -> None:
    install_hooks(project_path=tmp_path)
    _installed, skipped = install_hooks(project_path=tmp_path, force=True)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert len(settings["hooks"]["Stop"]) == 1
    assert any("already registered" in reason for _, reason in skipped)


def test_install_hooks_refuses_an_unreadable_settings_file(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{ not json", encoding="utf-8")
    installed, skipped = install_hooks(project_path=tmp_path)
    assert "yolo_stop" in installed, "the script still lands"
    assert any("unreadable" in reason for _, reason in skipped)
    assert settings.read_text(encoding="utf-8") == "{ not json", "never overwrite it"


def test_yolo_ships_as_a_command() -> None:
    assert "specthis-yolo" in COMMAND_NAMES


# --------------------------------------------------------------- the hook


def test_hook_allows_when_not_armed(root: Path, specthis_bin: str) -> None:
    """Installed but unarmed changes nothing about an ordinary session."""
    assert run_hook(root, specthis_bin) == {}


def test_hook_fails_open_on_a_broken_sentinel(root: Path, specthis_bin: str) -> None:
    path = root / ".specthis" / "auto.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")
    assert run_hook(root, specthis_bin) == {}


def test_hook_fails_open_when_specthis_cannot_be_found(root: Path, tmp_path: Path) -> None:
    arm(root)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    out = run_hook(root, "/nonexistent/specthis", path=str(empty))
    assert out == {}, "never guess at a project it cannot see"


def test_hook_finds_specthis_in_the_project_venv(root: Path, specthis_bin: str) -> None:
    """The setup `which` alone would miss, and the one this user has."""
    venv_bin = root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "specthis").write_text(
        Path(specthis_bin).read_text(encoding="utf-8"), encoding="utf-8"
    )
    (venv_bin / "specthis").chmod(0o755)
    arm(root)
    empty = root / "empty-bin"
    empty.mkdir()
    out = run_hook(root, "/nonexistent/specthis", path=str(empty))
    assert decision(out) == "block", "the venv copy should have been found"


def test_hook_blocks_while_work_remains(root: Path, specthis_bin: str) -> None:
    arm(root)
    out = run_hook(root, specthis_bin)
    assert decision(out) == "block"
    reason = out["hookSpecificOutput"]["reason"]
    assert "machine queue" in reason and "mind queue" in reason
    assert "must not run `specthis vouch` yourself" in reason
    assert sentinel_of(root)["iterations_left"] == 39


def test_hook_disarms_when_converged(root: Path, specthis_bin: str) -> None:
    converge(root)
    arm(root)
    out = run_hook(root, specthis_bin)
    assert decision(out) is None
    assert "converged" in out["systemMessage"]
    assert sentinel_of(root)["active"] is False


def test_hook_disarms_when_the_budget_is_spent(root: Path, specthis_bin: str) -> None:
    arm(root, iterations_left=0)
    out = run_hook(root, specthis_bin)
    assert decision(out) is None
    assert "budget spent" in out["systemMessage"]
    assert sentinel_of(root)["active"] is False


def test_hook_disarms_at_the_deadline(root: Path, specthis_bin: str) -> None:
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    arm(root, deadline=past)
    out = run_hook(root, specthis_bin)
    assert "deadline" in out["systemMessage"]
    assert sentinel_of(root)["active"] is False


def test_an_unparseable_deadline_does_not_trap_the_session(root: Path, specthis_bin: str) -> None:
    arm(root, deadline="the day after tomorrow")
    assert decision(run_hook(root, specthis_bin)) == "block", "bad date, but work remains"


def test_hook_waits_without_spinning_while_compute_is_in_flight(
    root: Path, specthis_bin: str
) -> None:
    """The case that decides whether this is usable against a cluster.

    A submitted entry is still `never-run`, so the machine queue is not
    empty and a naive hook would block — pinning the model against a job
    it cannot hurry. It must allow the stop and stay armed instead: the
    backgrounded `scripthut run watch` is what re-enters the session.
    """
    for entry in ("fit-alpha", "fit-beta", "fig-beta"):
        vouch_ok(root, entry)
    arm(
        root,
        watching=[{"run_id": "r-1", "entries": ["fit-alpha", "fit-beta", "fig-beta"]}],
    )
    out = run_hook(root, specthis_bin)
    assert decision(out) is None, "must not block on work it cannot advance"
    assert "in flight" in out["systemMessage"]
    assert sentinel_of(root)["active"] is True, "the run is not over, only this turn"


def test_hook_disarms_when_nothing_moves(root: Path, specthis_bin: str) -> None:
    arm(root)
    # The first stop only establishes the baseline; STALL_ROUNDS identical
    # ones after it are what count as a stall.
    for _ in range(4):
        out = run_hook(root, specthis_bin)
    assert decision(out) is None
    assert "stalled" in out["systemMessage"]
    assert sentinel_of(root)["active"] is False


def test_progress_resets_the_stall_counter(root: Path, specthis_bin: str) -> None:
    arm(root)
    run_hook(root, specthis_bin)
    run_hook(root, specthis_bin)
    vouch_ok(root, "fit-alpha")  # the loop did something
    assert decision(run_hook(root, specthis_bin)) == "block"
    assert sentinel_of(root)["repeat"] == 0


def test_a_set_aside_entry_stops_counting_as_work(root: Path, specthis_bin: str) -> None:
    """Otherwise a doubt the loop cannot answer holds the session open.

    The contract moves, not the code: a spec edit expires the vouch
    without entering the run signature, so this is a mind-only break —
    which is the only axis a critic's doubt can leave behind.
    """
    converge(root)
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + "\nA contract the critic doubts.\n")
    assert [m["entry"] for m in check_json(root)["mind"]] == ["fit-alpha"]
    arm(root, set_aside=[{"entry": "fit-alpha", "why": "critic doubt, 2 rounds"}])
    out = run_hook(root, specthis_bin)
    assert decision(out) is None
    assert "set aside" in out["systemMessage"]


def test_the_loop_converges(root: Path, specthis_bin: str) -> None:
    """The whole point, end to end: drive only on what the hook says.

    A stand-in for the agent — it does exactly what the block reason
    tells it to and nothing else, so if the hook ever fails to name the
    next action, or fails to notice the queues are drained, this hangs
    or stops early. Note the two queues are re-read every round: they
    grow as they drain (a recorded run makes its consumers stale), which
    is why one pass of each would not get here.
    """
    arm(root)
    assert drive(root, specthis_bin) >= 1
    assert check_json(root)["verdict"] == "done"
    assert sentinel_of(root)["active"] is False


def test_the_machine_queue_grows_as_it_drains(root: Path, specthis_bin: str) -> None:
    """Why a driver has to loop rather than make one pass per queue.

    From a fully converged project, one script changes. Rebuilding that
    entry moves its output, which makes its consumer stale — a queue
    entry that did not exist when the round began. The cascade walks the
    chain one level per round, so a driver that drained each queue once
    and reported would stop with two thirds of the work undone.
    """
    converge(root)
    write(root, "scripts/fit_alpha.py", FIT_ALPHA_PY.replace('"loss": 1.0', '"loss": 2.0'))
    assert [m["entry"] for m in check_json(root)["machine"]] == ["fit-alpha"]

    arm(root)
    rounds = drive(root, specthis_bin)
    assert check_json(root)["verdict"] == "done"
    assert rounds >= 3, f"the cascade should take a round per level, took {rounds}"


def test_a_rejection_is_not_work_the_hook_holds_out_for(root: Path, specthis_bin: str) -> None:
    converge(root)
    CliRunner().invoke(
        main, ["vouch", "fig-beta", "--as", "ben", "--reject", "--path", str(root)]
    )
    arm(root)
    out = run_hook(root, specthis_bin)
    assert decision(out) is None, "a mind said no; the loop may not answer it"
    assert "blocked" in out["systemMessage"]
