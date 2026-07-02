import tarfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from specthis.cache import CacheError, fetch, has, list_keys, push
from specthis.check import Status, check_project
from specthis.cli import main
from specthis.parse import load_project

from .conftest import make_ready, write


@pytest.fixture
def cached(root: Path, tmp_path_factory, monkeypatch) -> Path:
    """A ready project with a file:// cache configured via env var."""
    store = tmp_path_factory.mktemp("cache-store")
    monkeypatch.setenv("SPECTHIS_CACHE_URL", f"file://{store}")
    make_ready(root)
    return store


def run_cli(*args: str):
    return CliRunner().invoke(main, list(args))


def status_of(root: Path, entry: str) -> Status:
    return check_project(load_project(root))[entry].status


def test_no_cache_configured_is_a_clear_error(root: Path, monkeypatch) -> None:
    monkeypatch.delenv("SPECTHIS_CACHE_URL", raising=False)
    make_ready(root)
    with pytest.raises(CacheError, match="no cache configured"):
        push(load_project(root), "fit-alpha")


def test_cache_url_from_bindings_toml(root: Path, tmp_path_factory, monkeypatch) -> None:
    monkeypatch.delenv("SPECTHIS_CACHE_URL", raising=False)
    store = tmp_path_factory.mktemp("cache-store")
    bindings = (root / "specs/bindings.toml").read_text()
    write(root, "specs/bindings.toml", f'[cache]\nurl = "file://{store}"\n\n' + bindings)
    make_ready(root)
    push(load_project(root), "fit-alpha")
    assert list(store.rglob("*.tar.gz"))


def test_push_requires_run_row(root: Path, monkeypatch, tmp_path_factory) -> None:
    monkeypatch.setenv("SPECTHIS_CACHE_URL", f"file://{tmp_path_factory.mktemp('c')}")
    with pytest.raises(CacheError, match="no runs.toml row"):
        push(load_project(root), "fit-alpha")


def test_push_refuses_uncertified_bytes(root: Path, cached: Path) -> None:
    write(root, "results/alpha/fit.json", '{"loss": 999}')  # tampered after run
    with pytest.raises(CacheError, match="only holds certified bytes"):
        push(load_project(root), "fit-alpha")


def test_push_fetch_roundtrip_restores_ready(root: Path, cached: Path) -> None:
    project = load_project(root)
    key = push(project, "fit-alpha")
    assert has(project, "fit-alpha")
    assert key in list_keys(project)

    ledgers = [root / "specs/vouches.toml", root / "specs/runs.toml"]
    before = [p.read_bytes() for p in ledgers]
    (root / "results/alpha/fit.json").unlink()
    r = check_project(load_project(root))["fit-alpha"]  # fresh-clone shape:
    assert r.status is Status.READY and not r.materialized  # claim stands, bytes elsewhere

    fetch(project, "fit-alpha")
    r = check_project(load_project(root))["fit-alpha"]
    assert r.status is Status.READY and r.materialized
    assert [p.read_bytes() for p in ledgers] == before  # zero ledger writes


def test_multi_output_roundtrip(root: Path, cached: Path) -> None:
    project = load_project(root)
    push(project, "fig-beta")
    (root / "reports/fig_beta.tex").unlink()
    (root / "reports/fig_beta.dat").unlink()
    fetch(project, "fig-beta")
    assert status_of(root, "fig-beta") is Status.READY


def test_fetch_refuses_tampered_archive(root: Path, cached: Path) -> None:
    project = load_project(root)
    push(project, "fit-alpha")
    archive = next(cached.rglob("fit-alpha.tar.gz"))
    poison = archive.parent / "poison"
    poison.mkdir()
    bad = poison / "results/alpha/fit.json"
    bad.parent.mkdir(parents=True)
    bad.write_text('{"loss": "poisoned"}')
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(bad, arcname="results/alpha/fit.json")

    (root / "results/alpha/fit.json").unlink()
    with pytest.raises(CacheError, match="do not match the recorded output digest"):
        fetch(project, "fit-alpha")
    assert not (root / "results/alpha/fit.json").exists()  # nothing landed


def test_fetch_miss_is_an_error(root: Path, cached: Path) -> None:
    with pytest.raises(CacheError, match="cache miss"):
        fetch(load_project(root), "fit-alpha")


def test_cli_cache_verbs(root: Path, cached: Path) -> None:
    assert run_cli("cache", "has", "fit-alpha", "--path", str(root)).exit_code == 1
    assert run_cli("cache", "push", "fit-alpha", "--path", str(root)).exit_code == 0
    result = run_cli("cache", "has", "fit-alpha", "--path", str(root))
    assert result.exit_code == 0 and "hit" in result.output
    result = run_cli("cache", "list", "--path", str(root))
    assert "fit-alpha.tar.gz" in result.output
    (root / "results/alpha/fit.json").unlink()
    assert run_cli("cache", "fetch", "fit-alpha", "--path", str(root)).exit_code == 0
    assert status_of(root, "fit-alpha") is Status.READY


def test_run_stale_fetch_skips_recompute(root: Path, cached: Path) -> None:
    for entry in ("fit-alpha", "fit-beta", "fig-beta"):
        run_cli("cache", "push", entry, "--path", str(root))
    (root / "results/alpha/fit.json").unlink()
    (root / "results/beta/fit.json").unlink()

    # If anything tries to EXECUTE, it fails loudly: sabotage the run
    # commands (bindings are not hashed, so statuses are untouched).
    bindings = (root / "specs/bindings.toml").read_text()
    write(
        root,
        "specs/bindings.toml",
        bindings.replace('run = \'"', 'run = \'false && "'),
    )

    result = run_cli("run", "--stale", "--fetch", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "fetched 2 from cache" in result.output
    assert status_of(root, "fit-alpha") is Status.READY
    assert status_of(root, "fit-beta") is Status.READY


def test_run_push_after_execute(root: Path, cached: Path) -> None:
    write(root, "hut.fit-alpha.json", '{"backend": "pbs"}\n')  # -> stale (signature)
    result = run_cli("run", "fit-alpha", "--push", "--path", str(root))
    assert result.exit_code == 0, result.output
    assert "pushed `fit-alpha`" in result.output
    assert has(load_project(root), "fit-alpha")