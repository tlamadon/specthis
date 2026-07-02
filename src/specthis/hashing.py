"""Content hashing: file digests, manifests, composed signatures.

Everything in the ledger reduces to SHA-256 over bytes on disk. No
mtime, no hostnames, no absolute paths — the same working tree gives
the same answer on a fresh clone on another machine.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

#: Placeholder digest recorded when an expected input file is absent.
#: It can never equal a real SHA-256, so a missing file always breaks
#: the signature match instead of being silently skipped.
MISSING = "missing"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def file_sha(path: Path) -> str | None:
    """SHA-256 of a file's bytes, or ``None`` if it does not exist."""
    if not path.is_file():
        return None
    return sha256_bytes(path.read_bytes())


def manifest_sha(pairs: Iterable[tuple[str, str]]) -> str:
    """Digest of ``(key, sha)`` pairs, order-independent.

    Canonical encoding: pairs sorted by key, each joined with NUL,
    lines joined with newline. This is the one encoding shared by the
    code manifest, the package blob, and the composed signature.
    """
    lines = [f"{key}\x00{sha}" for key, sha in sorted(pairs)]
    return sha256_text("\n".join(lines))


def signature(inputs: Mapping[str, str]) -> str:
    """Composed signature of a runs-ledger ``[inputs]`` table."""
    return manifest_sha(inputs.items())


def package_sha(root: Path, globs: Sequence[str], exclude: frozenset[str] = frozenset()) -> str:
    """Blob digest of the shared package: manifest over glob matches.

    ``exclude`` lists relative paths carved out of the blob — scripts
    bound to library entries, which carry their own claims.
    """
    pairs: list[tuple[str, str]] = []
    for pattern in globs:
        for path in root.glob(pattern):
            rel = path.relative_to(root).as_posix()
            if path.is_file() and rel not in exclude:
                digest = file_sha(path)
                assert digest is not None
                pairs.append((rel, digest))
    return manifest_sha(pairs)


def files_manifest(root: Path, paths: Sequence[str]) -> dict[str, str]:
    """Map each relative path to its digest (``MISSING`` if absent)."""
    return {p: file_sha(root / p) or MISSING for p in paths}


def output_sha(root: Path, outputs: Sequence[str]) -> str | None:
    """Digest of an entry's declared output(s).

    A single output hashes to its raw file digest (readable in the
    ledger); multiple outputs hash to a manifest over them. ``None``
    if any declared output is absent.
    """
    shas = [file_sha(root / p) for p in outputs]
    if any(s is None for s in shas):
        return None
    if len(outputs) == 1:
        return shas[0]
    return manifest_sha(zip(outputs, shas))  # type: ignore[arg-type]
