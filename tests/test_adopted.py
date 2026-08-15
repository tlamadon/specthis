"""The adopted set: what specthis tells the manager back (§7.8).

The bug this covers: `adopt` wrote the ledger and told the manager
nothing, so `check` called an entry current while `build` re-executed
the step that produced it — permanently, with no rebuild that converged.
Where the command submits cluster jobs, that is a queue, not a core.
"""

import json
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis import hashing
from specthis.adopt import adopted_steps, publish, step_of
from specthis.check import Realization, check_project
from specthis.cli import main
from specthis.parse import load_project
from specthis.runner import run_pipeline
from specthis.seam import DOCUMENT, SeamError, read_adopted, satisfies, write_adopted

from .conftest import PY, write

#: `fit-alpha` is built off-machine: its command submits a job and
#: returns, so running it locally makes no bytes and leaves a trace.
PIPELINE = f"""\
[steps.fit-alpha]
command = '{PY} scripts/submit.py fit-alpha'
deps    = ["scripts/fit_alpha.py", "hut.fit-alpha.json"]
outs    = ["results/alpha/fit.json"]

[steps.fit-beta]
command = '{PY} scripts/fit_beta.py'
deps    = ["scripts/fit_beta.py", "results/alpha/fit.json"]
outs    = ["results/beta/fit.json"]
"""

SUBMIT_PY = """\
import pathlib, sys
with pathlib.Path("submissions.log").open("a") as fh:
    fh.write(sys.argv[1] + "\\n")
"""

ALPHA_BYTES = '{"loss": 1.0}'


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


def submitted(root: Path) -> list[str]:
    """Every job the pipeline submitted — the expensive side effect."""
    log = root / "submissions.log"
    return log.read_text().split() if log.is_file() else []


@pytest.fixture
def cluster(root: Path) -> Path:
    """A project whose alpha fit arrives from a cluster, already adopted."""
    write(root, "pipeline.toml", PIPELINE)
    write(root, "scripts/submit.py", SUBMIT_PY)
    write(root, "results/alpha/fit.json", ALPHA_BYTES)  # the cluster's bytes
    manifest = root / "cluster-manifest.json"
    manifest.write_text(json.dumps(cluster_manifest(root)))
    result = run_cli("adopt", "fit-alpha", str(manifest), "--path", str(root))
    assert result.exit_code == 0, result.output
    return root


def cluster_manifest(root: Path, **extra) -> dict:
    """What a manager reports about work it did somewhere else."""
    paths = ["scripts/fit_alpha.py", "hut.fit-alpha.json", "results/alpha/fit.json"]
    digests = {p: hashing.file_sha(root / p) for p in paths}
    return {
        "manifest_version": 1,
        "step": "hut.omega.42",  # the manager's own id, which we never trust
        "command": "scripthut workflow run hut.fit-alpha.json",
        "inputs": {p: digests[p] for p in paths[:2]},
        "outputs": {"results/alpha/fit.json": digests["results/alpha/fit.json"]},
        "exit_code": 0,
        "finished_at": "2026-01-01T00:00:00+00:00",
        "executor": "scripthut",
        **extra,
    }


def realization(root: Path, name: str) -> Realization:
    return check_project(load_project(root))[name].realization


# ------------------------------------------------------ the disagreement


def test_check_and_build_agree_about_an_adopted_entry(cluster: Path) -> None:
    """The invariant that was silently missing. `check` reading the
    ledger and `build` reading the manager's bookkeeping must not reach
    opposite conclusions about the same entry."""
    assert realization(cluster, "fit-alpha") is Realization.CURRENT
    assert "fit-alpha" in read_adopted(cluster)

    result = run_cli("build", "--path", str(cluster))
    assert result.exit_code == 0, result.output
    assert submitted(cluster) == [], "build re-ran a step check called current"
    assert realization(cluster, "fit-alpha") is Realization.CURRENT


def test_building_downstream_does_not_re_execute_an_adopted_step(cluster: Path) -> None:
    """The acceptance case: the adopted step is skipped, the requested
    one is built."""
    result = run_cli("build", "fit-beta", "--path", str(cluster))
    assert result.exit_code == 0, result.output
    assert (cluster / "results/beta/fit.json").is_file()
    assert "adopted fit-beta" in result.output


def test_a_steps_side_effect_is_not_invoked_for_an_adopted_step(cluster: Path) -> None:
    """The case that makes the bug expensive rather than slow: the
    command submits a job. Re-running it costs a cluster queue and
    re-derives bytes that are already on disk and verified."""
    assert run_cli("build", "fit-beta", "--path", str(cluster)).exit_code == 0
    assert submitted(cluster) == []

    # The document is what does the work: hand the manager the same
    # pipeline without it and the job goes back to the queue.
    (cluster / DOCUMENT).unlink()
    run_pipeline(cluster, only=["fit-beta"])
    assert submitted(cluster) == ["fit-alpha"]


def test_adopt_reports_what_the_manager_can_now_skip(root: Path) -> None:
    write(root, "pipeline.toml", PIPELINE)
    write(root, "results/alpha/fit.json", ALPHA_BYTES)
    manifest = root / "m.json"
    manifest.write_text(json.dumps(cluster_manifest(root)))
    result = run_cli("adopt", "fit-alpha", str(manifest), "--path", str(root))
    assert f"{DOCUMENT}: 1 step(s) the manager can skip" in result.output


# ------------------------------------------------------------ staleness


def test_touching_a_dep_puts_an_adopted_step_back_on_the_list(cluster: Path) -> None:
    """An adopted step is never pinned as permanently satisfied."""
    write(cluster, "scripts/fit_alpha.py", "# a different fit\n")
    assert realization(cluster, "fit-alpha") is Realization.STALE

    run_cli("build", "--path", str(cluster))
    assert submitted(cluster) == ["fit-alpha"], "an edited dep did not re-submit"


def test_editing_the_output_puts_an_adopted_step_back_on_the_list(cluster: Path) -> None:
    write(cluster, "results/alpha/fit.json", '{"loss": 999}')
    assert realization(cluster, "fit-alpha") is Realization.STALE

    run_cli("build", "--path", str(cluster))
    assert submitted(cluster) == ["fit-alpha"]


def test_rewiring_the_command_puts_an_adopted_step_back_on_the_list(cluster: Path) -> None:
    """The record pins the command, so a rewire cannot be a silent hit."""
    write(cluster, "pipeline.toml", PIPELINE.replace("submit.py fit-alpha", "submit.py alpha2"))
    run_cli("build", "--path", str(cluster))
    assert submitted(cluster) == ["alpha2"]


def test_force_bypasses_the_adopted_set(cluster: Path) -> None:
    """--force is the integrity repair path: it must reach the manager
    past every record, this one included."""
    result = run_cli("build", "fit-alpha", "--force", "--path", str(cluster))
    assert result.exit_code == 0, result.output
    assert submitted(cluster) == ["fit-alpha"]


# ------------------------------------- what never reaches the adopted set


def test_a_failed_manifest_never_becomes_a_satisfied_step(root: Path) -> None:
    write(root, "pipeline.toml", PIPELINE)
    write(root, "results/alpha/fit.json", ALPHA_BYTES)
    manifest = root / "m.json"
    manifest.write_text(json.dumps(cluster_manifest(root, exit_code=3)))
    result = run_cli("adopt", "fit-alpha", str(manifest), "--path", str(root))
    assert result.exit_code != 0
    assert not (root / DOCUMENT).exists()


def test_a_step_missing_any_of_its_bytes_is_not_published(cluster: Path) -> None:
    """Partial adoption is not adoption: a manager cannot skip work whose
    products are not all here."""
    (cluster / "results/alpha/fit.json").unlink()
    assert "fit-alpha" not in adopted_steps(load_project(cluster))


def test_a_never_run_step_is_not_published(cluster: Path) -> None:
    assert "fit-beta" not in adopted_steps(load_project(cluster))


def test_an_unvouched_entry_is_still_published(cluster: Path) -> None:
    """Adoption is a machine-currency claim. It must never imply a mind
    judged anything — and must not wait on one either."""
    assert not (cluster / "specs/vouches.toml").exists()
    assert "fit-alpha" in adopted_steps(load_project(cluster))


def test_publishing_touches_no_vouch(cluster: Path) -> None:
    publish(load_project(cluster))
    assert not (cluster / "specs/vouches.toml").exists()


# ------------------------------------------- a projection, not a ledger


def test_republishing_an_unchanged_project_rewrites_identical_bytes(cluster: Path) -> None:
    """Derived state: no timestamps, no accumulation, no drift."""
    before = (cluster / DOCUMENT).read_bytes()
    publish(load_project(cluster))
    assert (cluster / DOCUMENT).read_bytes() == before


def test_deleting_the_document_loses_nothing(cluster: Path) -> None:
    before = (cluster / DOCUMENT).read_bytes()
    (cluster / DOCUMENT).unlink()
    result = run_cli("adopted", "--path", str(cluster))
    assert result.exit_code == 0, result.output
    assert (cluster / DOCUMENT).read_bytes() == before
    assert "1 step(s) accounted for" in result.output
    assert "fit-alpha" in result.output


def test_a_project_without_a_pipeline_gets_no_document(root: Path) -> None:
    from .conftest import fake_run

    fake_run(root, "fit-alpha")
    publish(load_project(root))
    assert not (root / DOCUMENT).exists()


def test_removing_every_step_empties_a_stale_document(cluster: Path) -> None:
    write(cluster, "pipeline.toml", "")
    publish(load_project(cluster))
    assert read_adopted(cluster) == {}


# ------------------------------------------------ step id <-> entry key


def test_an_instance_is_published_under_the_step_that_produces_it(root: Path) -> None:
    """Identity comes from the output path (§15.3). The step id here
    shares no substring with the ledger key, which is the point: for a
    template the ids are historical and carry no meaning."""
    from .test_templates import templated

    templated(root)
    write(root, "data/chile/wages.parquet", "chile wages")
    project = load_project(root)
    key = "clean-wages[dataset=chile]"
    assert step_of(project, key) == "clean-chile"

    manifest = root / "m.json"
    manifest.write_text(json.dumps({
        "manifest_version": 1,
        "exit_code": 0,
        "outputs": {"data/chile/wages.parquet": hashing.file_sha(root / "data/chile/wages.parquet")},
        "executor": "scripthut",
    }))
    assert run_cli("adopt", key, str(manifest), "--path", str(root)).exit_code == 0

    published = read_adopted(root)
    assert published["clean-chile"]["entries"] == [key]
    assert "clean-argentina" not in published, "a sibling instance is not adopted by association"


def test_a_source_entry_has_no_step_and_publishes_nothing(cluster: Path) -> None:
    project = load_project(cluster)
    assert step_of(project, "fig-beta") is None  # no step in this pipeline


# ------------------------------------------------------- the format


def test_an_unknown_version_is_a_clean_error_not_a_silent_empty_set(cluster: Path) -> None:
    """Ignoring the document would re-run every adopted step — exactly
    the failure it exists to prevent. `build` republishes before handing
    over so it never meets a version it cannot read; a manager driven by
    hand can, and must hear about it."""
    (cluster / DOCUMENT).write_text(json.dumps({"adopted_version": 99, "steps": {}}))
    with pytest.raises(SeamError, match="adopted_version"):
        read_adopted(cluster)
    with pytest.raises(SeamError):
        run_pipeline(cluster)
    assert submitted(cluster) == []


def test_an_unreadable_document_is_a_clean_error(cluster: Path) -> None:
    (cluster / DOCUMENT).write_text("{not json")
    with pytest.raises(SeamError, match="unreadable"):
        read_adopted(cluster)


def test_an_absent_document_is_not_an_error(root: Path) -> None:
    assert read_adopted(root) == {}


def test_publishing_is_atomic(cluster: Path) -> None:
    """`adopt` and `build` can run at once, and a manager may read while
    either writes: a reader sees one document or the other, never half."""
    project = load_project(cluster)
    errors: list[Exception] = []

    def republish() -> None:
        for _ in range(10):
            publish(project)

    def consult() -> None:
        for _ in range(200):
            try:
                read_adopted(cluster)
            except Exception as exc:  # noqa: BLE001 — the assertion is "never"
                errors.append(exc)

    threads = [threading.Thread(target=republish), threading.Thread(target=consult)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert not list((cluster / ".specthis").glob("*.tmp"))


def test_the_document_carries_what_a_manager_needs_and_no_more(cluster: Path) -> None:
    record = read_adopted(cluster)["fit-alpha"]
    assert set(record) == {"entries", "command", "deps", "outs"}
    assert record["entries"] == ["fit-alpha"]
    assert set(record["deps"]) == {"scripts/fit_alpha.py", "hut.fit-alpha.json"}
    assert record["outs"] == {
        "results/alpha/fit.json": hashing.file_sha(cluster / "results/alpha/fit.json")
    }
    assert json.loads((cluster / DOCUMENT).read_text())["adopted_version"] == 1


# ------------------------------------------- the shared decision procedure


RECORD = {"command": "run it", "deps": {"a.py": "aaa"}, "outs": {"o.txt": "ooo"}}


def digest_of(table: dict[str, str]):
    return lambda p: table.get(p, "MISSING")


def test_satisfies_accepts_an_unchanged_step() -> None:
    assert satisfies(RECORD, "run it", {"a.py": "aaa"}, ["o.txt"], digest_of({"o.txt": "ooo"}))


@pytest.mark.parametrize(
    "command, deps, outs, disk",
    [
        ("run it differently", {"a.py": "aaa"}, ["o.txt"], {"o.txt": "ooo"}),  # rewired
        ("run it", {"a.py": "bbb"}, ["o.txt"], {"o.txt": "ooo"}),  # dep edited
        ("run it", {"a.py": "aaa", "b.py": "bbb"}, ["o.txt"], {"o.txt": "ooo"}),  # dep added
        ("run it", {"a.py": "aaa"}, ["o.txt", "p.txt"], {"o.txt": "ooo"}),  # out added
        ("run it", {"a.py": "aaa"}, ["o.txt"], {"o.txt": "edited"}),  # artefact edited
        ("run it", {"a.py": "aaa"}, ["o.txt"], {}),  # artefact deleted
    ],
)
def test_satisfies_refuses_anything_that_moved(command, deps, outs, disk) -> None:
    assert not satisfies(RECORD, command, deps, outs, digest_of(disk))


def test_satisfies_refuses_an_absent_or_empty_record() -> None:
    assert not satisfies(None, "run it", {}, [], digest_of({}))
    assert not satisfies({"command": "run it", "deps": {}}, "run it", {}, [], digest_of({}))


def test_a_legacy_record_without_a_command_is_not_trusted() -> None:
    """Same rule as the runner's lock: no command, no hit."""
    legacy = {"deps": {"a.py": "aaa"}, "outs": {"o.txt": "ooo"}}
    assert not satisfies(legacy, "run it", {"a.py": "aaa"}, ["o.txt"], digest_of({"o.txt": "ooo"}))


def test_write_adopted_round_trips(tmp_path: Path) -> None:
    write_adopted(tmp_path, {"s": RECORD})
    assert read_adopted(tmp_path) == {"s": RECORD}
