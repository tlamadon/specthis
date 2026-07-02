"""Remote compute cache: fetch bytes instead of recomputing them.

git holds claims, caches hold bytes, digests join them. The cache is
keyed by an entry's composed signature (the ``signature`` field of its
``runs.toml`` row): ``<url>/cache/<signature>/<entry>.tar.gz``.

The load-bearing property: **the cache writes no ledger rows and mints
no trust**. A collaborator's run row travels through git; on a fresh
clone the entry reads *ready* with the bytes marked non-materialized.
``fetch`` pulls the archive for the recorded signature, verifies the
unpacked outputs against the recorded ``output_sha``, and only then
moves them into place. A poisoned or corrupt archive fails the digest
check and nothing lands on disk.

For entries whose bytes never land anywhere else (remote-compute runs
certified via :mod:`specthis.remote`), the cache is not an optimization
but the home of record: next to each archive sits a
``<entry>.manifest.json`` sidecar carrying the claim metadata.

Backends (chosen by URL scheme, from ``[cache] url`` in
``specs/bindings.toml`` or the ``SPECTHIS_CACHE_URL`` env var):

- ``file:///path`` — a directory: shared network drive, or tests.
- ``s3://bucket/prefix`` — S3; requires the ``specthis[s3]`` extra.

Only the entry's *declared* outputs are archived. Undeclared sidecar
files are not cached (they are not covered by any claim).
"""

from __future__ import annotations

import os
import tarfile
import tempfile
from pathlib import Path

from . import hashing
from .ledger import Run, read_runs
from .parse import Entry, Project


class CacheError(Exception):
    pass


# ------------------------------------------------------------- backends


class _LocalStore:
    def __init__(self, base: Path) -> None:
        self.base = base

    def put(self, key: str, src: Path) -> None:
        dest = self.base / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())

    def get(self, key: str, dest: Path) -> bool:
        src = self.base / key
        if not src.is_file():
            return False
        dest.write_bytes(src.read_bytes())
        return True

    def has(self, key: str) -> bool:
        return (self.base / key).is_file()

    def keys(self) -> list[str]:
        if not self.base.is_dir():
            return []
        return sorted(
            p.relative_to(self.base).as_posix() for p in self.base.rglob("*.tar.gz")
        )


class _S3Store:
    def __init__(self, bucket: str, prefix: str) -> None:
        try:
            import boto3  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - needs missing dep
            raise CacheError(
                "the s3:// cache backend needs boto3 — pip install 'specthis[s3]'"
            ) from exc
        self.client = boto3.client("s3")
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, src: Path) -> None:  # pragma: no cover - needs AWS
        self.client.upload_file(str(src), self.bucket, self._key(key))

    def get(self, key: str, dest: Path) -> bool:  # pragma: no cover - needs AWS
        try:
            self.client.download_file(self.bucket, self._key(key), str(dest))
            return True
        except self.client.exceptions.ClientError:
            return False

    def has(self, key: str) -> bool:  # pragma: no cover - needs AWS
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except self.client.exceptions.ClientError:
            return False

    def keys(self) -> list[str]:  # pragma: no cover - needs AWS
        paginator = self.client.get_paginator("list_objects_v2")
        prefix = self._key("cache/")
        out = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if self.prefix:
                    key = key[len(self.prefix) + 1 :]
                out.append(key)
        return sorted(out)


def _store(project: Project):
    url = os.environ.get("SPECTHIS_CACHE_URL") or project.cache_url
    if not url:
        raise CacheError(
            "no cache configured — set `[cache] url = ...` in specs/bindings.toml "
            "or the SPECTHIS_CACHE_URL env var (file:///path or s3://bucket/prefix)"
        )
    if url.startswith("file://"):
        return _LocalStore(Path(url[len("file://") :]))
    if url.startswith("s3://"):
        bucket, _, prefix = url[len("s3://") :].partition("/")
        return _S3Store(bucket, prefix)
    raise CacheError(f"unsupported cache url scheme: {url}")


# ------------------------------------------------------------ operations


def _key(entry: str, signature: str) -> str:
    return f"cache/{signature}/{entry}.tar.gz"


def _manifest_key(entry: str, signature: str) -> str:
    return f"cache/{signature}/{entry}.manifest.json"


def _upload_archive(project: Project, entry: Entry, key: str) -> None:
    """Tar the entry's declared outputs (repo-relative names) and upload."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "out.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            for rel in entry.outputs:
                tf.add(project.root / rel, arcname=rel)
        _store(project).put(key, archive)


def _row(project: Project, name: str) -> Run:
    row = read_runs(project.specs_dir).get(name)
    if row is None:
        raise CacheError(f"`{name}` has no runs.toml row — nothing claimed to cache")
    return row


def push(project: Project, name: str) -> str:
    """Archive the entry's declared outputs under its recorded signature.

    Refuses unless the bytes on disk match the recorded claim — the
    cache must only ever hold bytes some run row certifies.
    """
    entry = project.entries[name]
    row = _row(project, name)
    disk_sha = hashing.output_sha(project.root, entry.outputs)
    if disk_sha != row.output_sha:
        raise CacheError(
            f"`{name}`: outputs on disk do not match the recorded run "
            "(re-run before pushing — the cache only holds certified bytes)"
        )
    key = _key(name, row.signature)
    _upload_archive(project, entry, key)
    return key


def _extract_verified(archive: Path, entry: Entry, row: Run, tmp: Path) -> dict[str, Path]:
    """Extract declared outputs to tmp and verify them against the claim.

    Only declared member names are read — anything else in the archive
    (including path-traversal names) is ignored outright.
    """
    staged: dict[str, Path] = {}
    with tarfile.open(archive, "r:gz") as tf:
        for i, rel in enumerate(entry.outputs):
            try:
                member = tf.getmember(rel)
            except KeyError as exc:
                raise CacheError(f"cached archive is missing `{rel}`") from exc
            src = tf.extractfile(member)
            if src is None:
                raise CacheError(f"cached archive entry `{rel}` is not a regular file")
            dest = tmp / f"staged-{i}"
            with src, open(dest, "wb") as out:
                out.write(src.read())
            staged[rel] = dest
    pairs = [(rel, hashing.file_sha(p)) for rel, p in staged.items()]
    fetched_sha = hashing.composed_output_sha(pairs)  # type: ignore[arg-type]
    if fetched_sha != row.output_sha:
        raise CacheError(
            "cached bytes do not match the recorded output digest — refusing to unpack"
        )
    return staged


def fetch(project: Project, name: str) -> str:
    """Materialize the entry's recorded outputs from the cache.

    Writes nothing to any ledger: the run row already carries the
    claim; this only supplies the bytes, verified against it.
    """
    entry = project.entries[name]
    row = _row(project, name)
    key = _key(name, row.signature)
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        archive = tmp / "out.tar.gz"
        if not _store(project).get(key, archive):
            raise CacheError(f"cache miss for `{name}` at signature {row.signature[:12]}…")
        staged = _extract_verified(archive, entry, row, tmp)
        for rel, src in staged.items():
            dest = project.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
    return key


def has(project: Project, name: str) -> bool:
    return _store(project).has(_key(name, _row(project, name).signature))


def list_keys(project: Project) -> list[str]:
    return _store(project).keys()


def try_fetch(project: Project, name: str, expected_signature: str) -> bool:
    """Best-effort fetch for `run --fetch`: True if the bytes landed.

    Only applicable when the recorded claim matches what a run right
    now would compute — otherwise the cached bytes answer a stale
    question and the entry genuinely needs recomputing.
    """
    runs = read_runs(project.specs_dir)
    row = runs.get(name)
    if row is None or row.signature != expected_signature:
        return False
    try:
        fetch(project, name)
        return True
    except CacheError:
        return False
