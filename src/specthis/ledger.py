"""The two ledgers: ``specs/vouches.toml`` and ``specs/runs.toml``.

Attested claims (vouches) are written ONLY by ``specthis vouch``;
derived claims (runs) ONLY by ``specthis run``. Nothing in this module
lets one verb touch the other's file, and nothing here reads the
working tree — a ledger row is a claim, not an observation.
"""

from __future__ import annotations

import sys
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


@dataclass
class Run:
    signature: str
    output: str  # single path, or comma-joined for multi-output entries
    output_sha: str
    ran: str  # ISO8601 UTC
    executor: str
    inputs: dict[str, str] = field(default_factory=dict)


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _write_toml(path: Path, data: dict) -> None:
    path.write_text(tomli_w.dumps(data), encoding="utf-8")


def read_vouches(specs_dir: Path) -> dict[str, Vouch]:
    raw = _read_toml(specs_dir / VOUCHES_FILE)
    return {name: Vouch(**row) for name, row in raw.items()}


def read_runs(specs_dir: Path) -> dict[str, Run]:
    raw = _read_toml(specs_dir / RUNS_FILE)
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
    vouches = read_vouches(specs_dir)
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
    _write_toml(specs_dir / VOUCHES_FILE, {n: asdict(v) for n, v in sorted(vouches.items())})


def record_run(specs_dir: Path, entry: str, run: Run) -> None:
    """Write one derived claim (replacing any prior row for the entry)."""
    runs = read_runs(specs_dir)
    runs[entry] = run
    _write_toml(specs_dir / RUNS_FILE, {n: asdict(r) for n, r in sorted(runs.items())})
