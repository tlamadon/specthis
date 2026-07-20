"""Certify-where-the-bytes-are: the claim travels, the bytes need not.

Two machines are simulated as two directory trees sharing a file://
cache: the "hpc" clone runs the entry and certifies (`specthis
manifest`), the "laptop" holds the git pen and adopts (`specthis run
--adopt`). The bytes never touch the laptop unless it fetches.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis import hashing
from specthis.cache import fetch
from specthis.check import Status, check_project, frontier
from specthis.cli import main
from specthis.ledger import read_runs
from specthis.parse import load_project
from specthis.remote import RemoteError, adopt, certify

from .conftest import make_ready, vouch_ok

PY = sys.executable


@pytest.fixture
def store(tmp_path_factory, monkeypatch) -> Path:
    """A shared file:// cache, as both machines would see it."""
    store = tmp_path_factory.mktemp("cache-store")
    monkeypatch.setenv("SPECTHIS_CACHE_URL", f"file://{store}")
    return store


def clone(root: Path, tmp_path_factory) -> Path:
    """Materialize what `git clone` would: tracked files, no results."""
    dst = tmp_path_factory.mktemp("hpc-clone")
    for d in ("specs", "scripts", "src"):
        shutil.copytree(root / d, dst / d)
    shutil.copy(root / "hut.fit-alpha.json", dst / "hut.fit-alpha.json")
    (dst / "reports").mkdir()
    shutil.copy(root / "reports/paper.tex", dst / "reports/paper.tex")
    return dst


def run_script(tree: Path, script: str) -> None:
    subprocess.run([PY, script], cwd=tree, check=True)


def report(tree: Path, entry: str):
    return check_project(load_project(tree))[entry]


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


# ---------------------------------------------------------------- certify


def test_certify_uploads_and_records_locally(root: Path, store: Path) -> None:
    run_script(root, "scripts/fit_alpha.py")
    m = certify(load_project(root), "fit-alpha", executor="test:hpc")

    assert (store / f"cache/{m.signature}/fit-alpha.tar.gz").is_file()
    sidecar = store / f"cache/{m.signature}/fit-alpha.manifest.json"
    data = json.loads(sidecar.read_text())
    assert data["entry"] == "fit-alpha" and data["signature"] == m.signature
    real_sha = hashing.file_sha(root / "results/alpha/fit.json")
    assert data["outputs"]["results/alpha/fit.json"]["sha256"] == real_sha
    assert data["output_sha"] == real_sha  # single output: raw file digest

    row = read_runs(root / "specs")["fit-alpha"]  # same claim `run` would write
    assert row.signature == m.signature
    assert row.output_sha == m.output_sha
    assert row.executor == "test:hpc"


def test_certify_requires_bytes_and_leaves_no_partial_state(
    root: Path, store: Path
) -> None:
    with pytest.raises(RemoteError, match="missing on this disk"):
        certify(load_project(root), "fit-alpha")
    assert not list(store.rglob("*")), "nothing may land at the final key"


def test_certify_refuses_library_entries(root: Path, store: Path) -> None:
    from .conftest import write

    write(
        root,
        "specs/lib.md",
        "---\nname: lib\nkind: library\n---\n\n# lib\n\n## Entry\n\n### pkg-core\n\nCore.\n",
    )
    bindings = (root / "specs/bindings.toml").read_text()
    write(
        root,
        "specs/bindings.toml",
        bindings + '\n[entries.pkg-core]\nscripts = ["src/pkg/helpers.py"]\n',
    )
    with pytest.raises(RemoteError, match="library entry"):
        certify(load_project(root), "pkg-core")


# ------------------------------------------------------------------ adopt


def test_adopt_records_the_claim_without_the_bytes(
    root: Path, store: Path, tmp_path_factory
) -> None:
    vouch_ok(root, "fit-alpha")
    hpc = clone(root, tmp_path_factory)
    run_script(hpc, "scripts/fit_alpha.py")
    m = certify(load_project(hpc), "fit-alpha", executor="test:hpc")

    run = adopt(load_project(root), "fit-alpha")

    assert run.signature == m.signature and run.output_sha == m.output_sha
    assert run.executor == "test:hpc" and run.ran == m.created
    assert not (root / "results").exists(), "adoption must not move bytes"
    r = report(root, "fit-alpha")
    assert r.status is Status.READY and not r.materialized
    local, _, _ = frontier(check_project(load_project(root)))
    assert "fit-alpha" not in {x.entry for x in local}


def test_adopted_entry_materializes_via_fetch(
    root: Path, store: Path, tmp_path_factory
) -> None:
    vouch_ok(root, "fit-alpha")
    hpc = clone(root, tmp_path_factory)
    run_script(hpc, "scripts/fit_alpha.py")
    certify(load_project(hpc), "fit-alpha")
    adopt(load_project(root), "fit-alpha")

    fetch(load_project(root), "fit-alpha")

    assert (root / "results/alpha/fit.json").read_bytes() == (
        hpc / "results/alpha/fit.json"
    ).read_bytes()
    r = report(root, "fit-alpha")
    assert r.status is Status.READY and r.materialized


def test_adopt_refuses_a_drifted_tree(root: Path, store: Path, tmp_path_factory) -> None:
    hpc = clone(root, tmp_path_factory)
    run_script(hpc, "scripts/fit_alpha.py")
    certify(load_project(hpc), "fit-alpha")

    (root / "scripts/fit_alpha.py").write_text("# drifted since dispatch\n")
    with pytest.raises(RemoteError, match="no remote claim"):
        adopt(load_project(root), "fit-alpha")
    assert "fit-alpha" not in read_runs(root / "specs")


def test_adopt_refuses_a_tampered_manifest(
    root: Path, store: Path, tmp_path_factory
) -> None:
    hpc = clone(root, tmp_path_factory)
    run_script(hpc, "scripts/fit_alpha.py")
    certify(load_project(hpc), "fit-alpha")

    sidecar = next(store.rglob("fit-alpha.manifest.json"))
    data = json.loads(sidecar.read_text())
    data["output_sha"] = "0" * 64  # claim different bytes than the per-file digests
    sidecar.write_text(json.dumps(data))

    with pytest.raises(RemoteError, match="does not match its own per-file digests"):
        adopt(load_project(root), "fit-alpha")
    assert "fit-alpha" not in read_runs(root / "specs")


def test_adoption_follows_the_dag(root: Path, store: Path, tmp_path_factory) -> None:
    """Same-workflow chain: certify composes downstream signatures on the
    hpc clone (via its working-copy runs.toml); the laptop adopts in
    dependency order and cannot skip ahead."""
    vouch_ok(root, "fit-alpha")
    vouch_ok(root, "fit-beta")
    hpc = clone(root, tmp_path_factory)
    run_script(hpc, "scripts/fit_alpha.py")
    certify(load_project(hpc), "fit-alpha")
    run_script(hpc, "scripts/fit_beta.py")
    certify(load_project(hpc), "fit-beta")

    with pytest.raises(RemoteError, match="no recorded run"):
        adopt(load_project(root), "fit-beta")

    adopt(load_project(root), "fit-alpha")
    adopt(load_project(root), "fit-beta")
    for entry in ("fit-alpha", "fit-beta"):
        r = report(root, entry)
        assert r.status is Status.READY and not r.materialized
    beta = read_runs(root / "specs")["fit-beta"]
    alpha = read_runs(root / "specs")["fit-alpha"]
    assert beta.inputs["upstream:fit-alpha"] == alpha.output_sha


# -------------------------------------------------------------------- CLI


def test_cli_manifest_then_adopt(root: Path, store: Path, tmp_path_factory) -> None:
    vouch_ok(root, "fit-alpha")
    hpc = clone(root, tmp_path_factory)
    run_script(hpc, "scripts/fit_alpha.py")

    result = run_cli("manifest", "fit-alpha", "--executor", "hut:test", "--path", str(hpc))
    assert result.exit_code == 0, result.output
    assert "certified `fit-alpha`" in result.output

    result = run_cli("run", "fit-alpha", "--adopt", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "adopted remote run" in result.output
    assert read_runs(root / "specs")["fit-alpha"].executor == "hut:test"

    result = run_cli("status", "fit-alpha", "--path", str(root))
    assert "not local" in result.output


def test_cli_adopt_flag_combinations_refused(root: Path, store: Path) -> None:
    assert run_cli("run", "--stale", "--adopt", "--path", str(root)).exit_code != 0
    result = run_cli("run", "fit-alpha", "--adopt", "--fetch", "--path", str(root))
    assert result.exit_code != 0
    assert "--adopt" in result.output


def test_run_stale_leaves_remote_bytes_alone(root: Path, store: Path) -> None:
    make_ready(root)
    (root / "results/alpha/fit.json").unlink()

    result = run_cli("run", "--stale", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "rebuilt 0 entries" in result.output
    assert not (root / "results/alpha/fit.json").exists(), (
        "never recomputed just because the bytes are not local"
    )


def test_check_names_non_materialized_entries(root: Path, store: Path) -> None:
    make_ready(root)
    (root / "results/alpha/fit.json").unlink()
    result = run_cli("check", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "bytes not local" in result.output and "fit-alpha" in result.output
