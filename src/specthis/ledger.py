"""The two ledgers: ``specs/vouches.toml`` and ``specs/runs.toml``.

Attested claims (vouches) are written ONLY by ``specthis vouch``;
derived claims (runs) ONLY by ``specthis run``. Nothing in this module
lets one verb touch the other's file, and nothing here reads the
working tree — a ledger row is a claim, not an observation.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

VOUCHES_FILE = "vouches.toml"
RUNS_FILE = "runs.toml"


class LedgerError(Exception):
    """A write would violate a ledger rule."""


@dataclass
class Vouch:
    spec_sha: str
    code_sha: str
    verdict: str  # "ok" | "rejected"
    attester: str
    vouched: str  # ISO8601 UTC
    note: str = ""
    #: Decomposable forms of the two digests, recorded so an expired
    #: vouch can be attributed (which script, the package blob, or
    #: where in the spec file the movement happened). Diagnostic only:
    #: expiry itself is still judged on the composed pair above.
    #: Empty on rows written before these fields existed.
    spec_block_sha: str = ""
    code_manifest: dict[str, str] = field(default_factory=dict)
    #: Wall-clock seconds the judgment took (``vouch --took``). Claim
    #: metadata like a run's duration: enters no digest, omitted from
    #: the TOML row when unknown.
    duration_seconds: float | None = None


@dataclass
class Run:
    signature: str
    output: str  # single path, or comma-joined for multi-output entries
    output_sha: str
    ran: str  # ISO8601 UTC
    executor: str
    inputs: dict[str, str] = field(default_factory=dict)
    #: Wall-clock seconds the run command took. Claim metadata only:
    #: it enters no signature and moves no digest. ``None`` (omitted
    #: from the TOML row) for rows that predate the field or were
    #: adopted from a remote manifest that did not record one.
    duration_seconds: float | None = None


@contextmanager
def _locked(path: Path):
    """Serialize a ledger's read-modify-write cycle across processes.

    Parallel critic sessions vouch different entries concurrently; an
    unserialized cycle would let one rewrite lose the other's row. The
    ledger file itself is the lock (created empty if absent — same
    meaning as missing). Non-POSIX platforms degrade to no locking.
    """
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover — Windows
            pass
        yield
    finally:
        os.close(fd)  # closing drops the flock


def _read_toml(path: Path, shared_lock: bool = True) -> dict:
    """Read a ledger, by default under a shared lock so a reader racing
    a writer (`run --stale -p N` checks statuses while workers record)
    sees a complete file, never a truncated rewrite mid-flight. A
    missing file is read as empty without creating it — reads stay
    writeless. ``shared_lock=False`` is for reads already inside a
    ``_locked`` cycle: flock conflicts across descriptors even within
    one process, so re-locking there would self-deadlock."""
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        if shared_lock:
            try:
                import fcntl

                fcntl.flock(f, fcntl.LOCK_SH)
            except ImportError:  # pragma: no cover — Windows
                pass
        return tomllib.load(f)


def _write_toml(path: Path, data: dict) -> None:
    path.write_text(tomli_w.dumps(data), encoding="utf-8")


def read_vouches(specs_dir: Path, _shared_lock: bool = True) -> dict[str, Vouch]:
    raw = _read_toml(specs_dir / VOUCHES_FILE, shared_lock=_shared_lock)
    return {name: Vouch(**row) for name, row in raw.items()}


def read_runs(specs_dir: Path, _shared_lock: bool = True) -> dict[str, Run]:
    raw = _read_toml(specs_dir / RUNS_FILE, shared_lock=_shared_lock)
    return {name: Run(**row) for name, row in raw.items()}


def record_vouch(specs_dir: Path, entry: str, vouch: Vouch) -> None:
    """Write one attested claim, enforcing the rejection rule.

    A rejection binds at its exact ``(spec_sha, code_sha)`` pair: an
    ``ok`` verdict at a pair carrying a standing rejection is refused —
    something (spec, code, or the rejector's mind, expressed as a new
    rejection-lifting vouch by someone else at a *moved* pair) must
    change first. Digest movement expires rejections exactly as it
    expires vouches, so this only ever blocks the verbatim pair.
    """
    if vouch.verdict not in ("ok", "rejected"):
        raise LedgerError(f"verdict must be 'ok' or 'rejected', got {vouch.verdict!r}")
    if not vouch.attester:
        raise LedgerError("a vouch requires a named attester")
    with _locked(specs_dir / VOUCHES_FILE):
        vouches = read_vouches(specs_dir, _shared_lock=False)
        prior = vouches.get(entry)
        if (
            vouch.verdict == "ok"
            and prior is not None
            and prior.verdict == "rejected"
            and (prior.spec_sha, prior.code_sha) == (vouch.spec_sha, vouch.code_sha)
        ):
            raise LedgerError(
                f"`{entry}` carries a standing rejection by {prior.attester} at this exact "
                "(spec, code) pair — change the spec or the code before vouching ok"
            )
        vouches[entry] = vouch
        # TOML has no null: optional fields (note, spec_block_sha,
        # code_manifest) are omitted when empty.
        rows = {
            n: {k: val for k, val in asdict(v).items() if val not in (None, "", {})}
            for n, v in sorted(vouches.items())
        }
        _write_toml(specs_dir / VOUCHES_FILE, rows)


def record_run(specs_dir: Path, entry: str, run: Run) -> None:
    """Write one derived claim (replacing any prior row for the entry)."""
    with _locked(specs_dir / RUNS_FILE):
        runs = read_runs(specs_dir, _shared_lock=False)
        runs[entry] = run
        # TOML has no null: optional fields (duration_seconds) are omitted.
        rows = {
            n: {k: v for k, v in asdict(r).items() if v is not None}
            for n, r in sorted(runs.items())
        }
        _write_toml(specs_dir / RUNS_FILE, rows)
