"""Human-readable time rendering shared by the CLI and the views.

Display vocabulary only: nothing here is hashed, recorded, or read
back — ledger rows keep ISO8601 timestamps and raw seconds.
"""

from __future__ import annotations

from datetime import datetime, timezone


def fmt_duration(seconds: float) -> str:
    """Wall time: ``4s``, ``3m 12s``, ``1h 04m``."""
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def fmt_ago(iso: str, now: datetime | None = None) -> str:
    """Age of an ISO8601 UTC timestamp: ``just now``, ``5m ago``,
    ``3h ago``, ``2d ago``, ``5w ago``, ``4mo ago``. "" when the
    timestamp is missing or unparseable (old ledger rows are data,
    never an error)."""
    if not iso:
        return ""
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    s = int((now - then).total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 48 * 3600:
        return f"{s // 3600}h ago"
    if s < 14 * 86400:
        return f"{s // 86400}d ago"
    if s < 10 * 7 * 86400:
        return f"{s // (7 * 86400)}w ago"
    return f"{s // (30 * 86400)}mo ago"
