"""Content hashing: file digests, manifests, composed signatures.

Everything in the ledger reduces to SHA-256 over bytes on disk. No
mtime, no hostnames, no absolute paths — the same working tree gives
the same answer on a fresh clone on another machine.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

#: Placeholder digest recorded when an expected input file is absent.
#: It can never equal a real SHA-256, so a missing file always breaks
#: the signature match instead of being silently skipped.
MISSING = "missing"

#: Installed by :func:`observing`. ``None`` — the default, and the only
#: state a library caller ever sees — leaves :func:`file_sha` exactly
#: what it always was. Called ``(path, bytes_read, seconds, cached)``.
_observer: Callable[[Path, int, float, bool], None] | None = None

#: Installed by :func:`memoizing`: path -> digest, for one derivation.
#: A `ContextVar` rather than a module global so two threads deriving at
#: once — `serve` renders off its own thread — cannot share one memo.
_memo: ContextVar[dict[str, str | None] | None] = ContextVar("_memo", default=None)


@contextmanager
def observing(observe: Callable[[Path, int, float, bool], None]) -> Iterator[None]:
    """Report every file digest taken inside the block, then restore.

    Digests are where a derivation spends its time, and they are taken
    from a dozen call sites across two modules; threading a counter
    through all of them would put an accounting concern into every
    signature for the sake of one CLI flag.

    An observer is told the path, the bytes actually read, the elapsed
    time and whether the answer came from the memo — all *after* the
    fact. It cannot change a digest, nothing reads it back, and the
    prior observer is restored even on an exception, so an interrupted
    run cannot leave the hook installed for the next caller in the same
    process.
    """
    global _observer
    prior, _observer = _observer, observe
    try:
        yield
    finally:
        _observer = prior


@contextmanager
def memoizing() -> Iterator[None]:
    """Digest each path at most once for the duration of the block.

    A derivation asks for the same digest from call sites that cannot
    see each other — an entry's script is code to `code_manifest` and a
    dependency to `expected_inputs`; a source entry's data is its code,
    its input table *and* its output. On a real project that was two
    thirds of the wall clock, and no single call site could fix it.

    Caching is the more honest reading as well as the faster one. A
    derivation is a claim about one **moment** (§10): two reads of the
    same path inside it disagreeing would be a torn read, not a
    finding, and acting on the difference would be acting on a race.

    The scope is deliberately narrow — one `check_project`, never a
    whole command. `build` hands work to a manager that *writes*
    outputs and then re-derives; a memo spanning that would answer the
    second derivation with the first one's bytes.
    """
    token = _memo.set({})
    try:
        yield
    finally:
        _memo.reset(token)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def file_sha(path: Path) -> str | None:
    """SHA-256 of a file's bytes, or ``None`` if it does not exist.

    Inside :func:`memoizing`, the first answer for a path is the answer
    for the rest of that block.
    """
    memo = _memo.get()
    if memo is None:
        return _digest(path)
    key = str(path)
    if key in memo:
        if _observer is not None:
            _observer(path, 0, 0.0, True)  # nothing was read; say so
        return memo[key]
    memo[key] = digest = _digest(path)
    return digest


def _digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    if _observer is None:  # the ordinary path, unmeasured and unbranched
        return sha256_bytes(path.read_bytes())
    started = time.perf_counter()
    data = path.read_bytes()
    digest = sha256_bytes(data)
    _observer(path, len(data), time.perf_counter() - started, False)
    return digest


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


def step_sha(command: str, deps: Sequence[str], outs: Sequence[str]) -> str:
    """Digest of a pipeline step's *semantic content* (spec §5.6).

    Command, dependency paths and output paths — never their contents
    (those are separate table rows), and never resources, executor or
    retries. Those change how work is scheduled, not what is
    implemented, so resizing a job must not expire a judgment.
    """
    return sha256_text(
        command + "\x00" + "\n".join(sorted(deps)) + "\x00" + "\n".join(sorted(outs))
    )


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


def composed_output_sha(pairs: Sequence[tuple[str, str]]) -> str:
    """Compose per-file ``(path, sha)`` digests into an entry-level one.

    A single output keeps its raw file digest (readable in the ledger);
    multiple outputs compose to a manifest over them. This is the one
    composition shared by ``run``, cache verification, and remote
    manifests — per-file digests are sufficient, bytes are not needed.
    """
    if len(pairs) == 1:
        return pairs[0][1]
    return manifest_sha(pairs)


def output_sha(root: Path, outputs: Sequence[str]) -> str | None:
    """Digest of an entry's declared output(s), read from disk.

    ``None`` if any declared output is absent — absence is a
    byte-locality fact, distinguishable from edited bytes.
    """
    shas = [file_sha(root / p) for p in outputs]
    if any(s is None for s in shas):
        return None
    return composed_output_sha(list(zip(outputs, shas)))  # type: ignore[arg-type]
