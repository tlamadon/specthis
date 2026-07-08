"""Display vocabulary for ledger timing: durations and ages."""

from datetime import datetime, timezone

from specthis.timefmt import fmt_ago, fmt_duration

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def test_fmt_duration_bands() -> None:
    assert fmt_duration(4) == "4s"
    assert fmt_duration(192) == "3m 12s"
    assert fmt_duration(3840) == "1h 04m"


def test_fmt_ago_bands() -> None:
    assert fmt_ago("2026-07-08T11:59:30+00:00", NOW) == "just now"
    assert fmt_ago("2026-07-08T11:55:00+00:00", NOW) == "5m ago"
    assert fmt_ago("2026-07-08T09:00:00+00:00", NOW) == "3h ago"
    assert fmt_ago("2026-07-05T12:00:00+00:00", NOW) == "3d ago"
    assert fmt_ago("2026-05-30T12:00:00+00:00", NOW) == "5w ago"
    assert fmt_ago("2026-01-01T00:00:00+00:00", NOW) == "6mo ago"


def test_fmt_ago_tolerates_bad_rows() -> None:
    # old or hand-edited ledger rows are data, never a render error
    assert fmt_ago("", NOW) == ""
    assert fmt_ago("not-a-date", NOW) == ""
