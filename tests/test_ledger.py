from pathlib import Path

import pytest

from specthis.ledger import (
    LedgerError,
    Run,
    Vouch,
    read_runs,
    read_vouches,
    record_run,
    record_vouch,
)


def _vouch(verdict: str = "ok", spec_sha: str = "s1", code_sha: str = "c1") -> Vouch:
    return Vouch(
        spec_sha=spec_sha,
        code_sha=code_sha,
        verdict=verdict,
        attester="critic",
        vouched="2026-01-01T00:00:00+00:00",
        note="",
    )


def test_vouch_roundtrip(tmp_path: Path) -> None:
    record_vouch(tmp_path, "e", _vouch())
    assert read_vouches(tmp_path)["e"] == _vouch()


def test_run_roundtrip(tmp_path: Path) -> None:
    run = Run(
        signature="sig",
        output="out.json",
        output_sha="abc",
        ran="2026-01-01T00:00:00+00:00",
        executor="local",
        inputs={"scripts/x.py": "d1", "upstream:up": "d2"},
    )
    record_run(tmp_path, "e", run)
    assert read_runs(tmp_path)["e"] == run


def test_ok_refused_over_standing_rejection_at_same_pair(tmp_path: Path) -> None:
    record_vouch(tmp_path, "e", _vouch("rejected"))
    with pytest.raises(LedgerError, match="standing rejection"):
        record_vouch(tmp_path, "e", _vouch("ok"))
    # the rejection still stands
    assert read_vouches(tmp_path)["e"].verdict == "rejected"


def test_rejection_expires_on_digest_movement(tmp_path: Path) -> None:
    record_vouch(tmp_path, "e", _vouch("rejected"))
    record_vouch(tmp_path, "e", _vouch("ok", code_sha="c2"))  # code moved: allowed
    assert read_vouches(tmp_path)["e"].verdict == "ok"


def test_vouch_requires_attester_and_valid_verdict(tmp_path: Path) -> None:
    with pytest.raises(LedgerError, match="attester"):
        record_vouch(tmp_path, "e", Vouch("s", "c", "ok", "", "t"))
    with pytest.raises(LedgerError, match="verdict"):
        record_vouch(tmp_path, "e", Vouch("s", "c", "maybe", "critic", "t"))


def test_ledgers_are_separate_files(tmp_path: Path) -> None:
    record_vouch(tmp_path, "e", _vouch())
    assert not (tmp_path / "runs.toml").exists()
    record_run(tmp_path, "e", Run("sig", "o", "sha", "t", "local"))
    assert (tmp_path / "vouches.toml").exists() and (tmp_path / "runs.toml").exists()
