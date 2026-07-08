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


def test_run_duration_roundtrips_and_none_is_omitted(tmp_path: Path) -> None:
    timed = Run(
        signature="sig",
        output="out.json",
        output_sha="abc",
        ran="2026-01-01T00:00:00+00:00",
        executor="local",
        duration_seconds=12.5,
    )
    record_run(tmp_path, "timed", timed)
    untimed = Run(
        signature="sig2",
        output="out2.json",
        output_sha="def",
        ran="2026-01-01T00:00:00+00:00",
        executor="remote",
    )
    record_run(tmp_path, "untimed", untimed)
    rows = read_runs(tmp_path)
    assert rows["timed"].duration_seconds == 12.5
    # TOML has no null: an unknown duration is omitted, not written
    assert rows["untimed"].duration_seconds is None
    assert "duration" not in (tmp_path / "runs.toml").read_text().split("[untimed]")[1].split("[")[0]


def test_legacy_run_row_without_duration_parses(tmp_path: Path) -> None:
    (tmp_path / "runs.toml").write_text(
        '[e]\nsignature = "sig"\noutput = "out.json"\noutput_sha = "abc"\n'
        'ran = "2026-01-01T00:00:00+00:00"\nexecutor = "local"\n\n[e.inputs]\n'
        '"scripts/x.py" = "d1"\n',
        encoding="utf-8",
    )
    row = read_runs(tmp_path)["e"]
    assert row.output_sha == "abc"
    assert row.duration_seconds is None


def test_vouch_decomposed_fields_roundtrip_and_empties_omitted(tmp_path: Path) -> None:
    v = Vouch(
        spec_sha="s1",
        code_sha="c1",
        verdict="ok",
        attester="critic",
        vouched="2026-01-01T00:00:00+00:00",
        spec_block_sha="b1",
        code_manifest={"scripts/x.py": "d1", "package": "p1"},
    )
    record_vouch(tmp_path, "rich", v)
    record_vouch(tmp_path, "legacy-shaped", _vouch())
    rows = read_vouches(tmp_path)
    assert rows["rich"] == v
    assert rows["legacy-shaped"].code_manifest == {}
    text = (tmp_path / "vouches.toml").read_text()
    # empty optionals are omitted, not written as empty values
    assert "spec_block_sha" not in text.split("[legacy-shaped]")[1].split("[rich]")[0]


def test_concurrent_vouches_do_not_lose_rows(tmp_path: Path) -> None:
    # parallel critic sessions vouch different entries at once; the
    # ledger lock must serialize the read-modify-write cycles
    from concurrent.futures import ThreadPoolExecutor

    entries = [f"e{i:02d}" for i in range(12)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda e: record_vouch(tmp_path, e, _vouch()), entries))
    assert sorted(read_vouches(tmp_path)) == entries


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
