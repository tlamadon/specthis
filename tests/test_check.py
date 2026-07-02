"""The status-derivation matrix — the guarantee specthis makes."""

from pathlib import Path

import pytest

from specthis.check import CheckError, Status, check_project, frontier
from specthis.parse import load_project

from .conftest import COMPUTE_ALPHA, fake_run, make_ready, vouch_ok, write


def statuses(root: Path) -> dict[str, Status]:
    return {name: r.status for name, r in check_project(load_project(root)).items()}


def report(root: Path, entry: str):
    return check_project(load_project(root))[entry]


# ------------------------------------------------------------- the ladder


def test_unimplemented_when_code_missing(root: Path) -> None:
    (root / "scripts/fit_alpha.py").unlink()
    assert statuses(root)["fit-alpha"] is Status.UNIMPLEMENTED


def test_audit_needed_when_never_vouched(root: Path) -> None:
    assert statuses(root)["fit-alpha"] is Status.AUDIT_NEEDED


def test_stale_when_vouched_but_never_run(root: Path) -> None:
    vouch_ok(root, "fit-alpha")
    assert statuses(root)["fit-alpha"] is Status.STALE


def test_ready_when_vouched_and_run(root: Path) -> None:
    make_ready(root)
    assert set(statuses(root).values()) == {Status.READY}


def test_rejected(root: Path) -> None:
    from specthis.check import code_sha
    from specthis.ledger import Vouch, record_vouch

    project = load_project(root)
    e = project.entries["fit-alpha"]
    c = code_sha(project, e)
    assert c is not None
    record_vouch(
        project.specs_dir,
        "fit-alpha",
        Vouch(e.spec.spec_sha, c, "rejected", "critic", "t", "wrong loss"),
    )
    assert statuses(root)["fit-alpha"] is Status.REJECTED


# ------------------------------------------------ what expires a vouch


def test_spec_body_edit_returns_to_audit_needed(root: Path) -> None:
    make_ready(root)
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA + "\nTighter contract.\n")
    assert statuses(root)["fit-alpha"] is Status.AUDIT_NEEDED


def test_frontmatter_edit_counts_as_contract_edit(root: Path) -> None:
    make_ready(root)
    write(root, "specs/compute-alpha.md", COMPUTE_ALPHA.replace("tier: quick", "tier: intensive"))
    assert statuses(root)["fit-alpha"] is Status.AUDIT_NEEDED


def test_code_edit_returns_to_audit_needed(root: Path) -> None:
    make_ready(root)
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    assert statuses(root)["fit-alpha"] is Status.AUDIT_NEEDED


def test_package_edit_returns_every_entry_to_audit_needed(root: Path) -> None:
    make_ready(root)
    write(root, "src/pkg/helpers.py", "X = 2\n")
    s = statuses(root)
    assert s["fit-alpha"] is Status.AUDIT_NEEDED
    assert s["fit-beta"] is Status.AUDIT_NEEDED


# --------------------------------------------------- what makes it stale


def test_workflow_file_edit_is_stale_not_audit(root: Path) -> None:
    # hut.*.json is an execution input, not judged code: signature moves,
    # vouch stands.
    make_ready(root)
    write(root, "hut.fit-alpha.json", '{"backend": "pbs"}\n')
    r = report(root, "fit-alpha")
    assert r.status is Status.STALE
    assert r.moved == ["hut.fit-alpha.json"]


def test_output_edited_on_disk_is_stale(root: Path) -> None:
    make_ready(root)
    write(root, "results/alpha/fit.json", '{"loss": 999}')
    r = report(root, "fit-alpha")
    assert r.status is Status.STALE
    assert "output" in r.moved[0]


def test_output_deleted_reads_ready_bytes_remote(root: Path) -> None:
    # Absent is not edited: the claim stands, the bytes are elsewhere.
    # (One of two declared outputs gone counts as absent — partial bytes
    # cannot be verified per-file against the composed digest.)
    make_ready(root)
    (root / "reports/fig_beta.dat").unlink()
    r = report(root, "fig-beta")
    assert r.status is Status.READY
    assert not r.materialized
    local, _waiting, ready = frontier(check_project(load_project(root)))
    assert "fig-beta" not in {x.entry for x in local}
    assert ready == 3


def test_upstream_rerun_makes_downstream_stale(root: Path) -> None:
    """THE composed-signature case: upstream re-ran, own files untouched."""
    make_ready(root)
    write(root, "results/alpha/fit.json", '{"loss": 2.0}')
    fake_run(root, "fit-alpha", execute=False)  # re-record: new output_sha, READY again
    s = statuses(root)
    assert s["fit-alpha"] is Status.READY
    assert s["fit-beta"] is Status.STALE, "upstream re-run must not be invisible"
    assert "upstream:fit-alpha" in report(root, "fit-beta").moved


# ------------------------------------------------------------ propagation


def test_upstream_break_propagates_without_expiring_vouches(root: Path) -> None:
    make_ready(root)
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    s = statuses(root)
    assert s["fit-alpha"] is Status.AUDIT_NEEDED  # local break
    assert s["fit-beta"] is Status.UPSTREAM_UNVERIFIED  # vouch stands, ground moved
    assert s["fig-beta"] is Status.UPSTREAM_UNVERIFIED  # transitive


def test_frontier_itemizes_local_summarizes_downstream(root: Path) -> None:
    make_ready(root)
    (root / "scripts/fit_alpha.py").write_text("# rewritten\n")
    local, waiting, ready = frontier(check_project(load_project(root)))
    assert [r.entry for r in local] == ["fit-alpha"]
    assert waiting == 2
    assert ready == 0


def test_consumes_cycle_is_an_error(root: Path) -> None:
    write(
        root,
        "specs/compute-alpha.md",
        COMPUTE_ALPHA.replace(
            "references:\n  - models.md", "consumes:\n  - fig-beta"
        ),
    )
    with pytest.raises(CheckError, match="cycle"):
        check_project(load_project(root))


def test_check_never_writes(root: Path) -> None:
    make_ready(root)
    ledgers = [root / "specs/vouches.toml", root / "specs/runs.toml"]
    before = [p.read_bytes() for p in ledgers]
    check_project(load_project(root))
    assert [p.read_bytes() for p in ledgers] == before
