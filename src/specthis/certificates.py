"""Code identity as a file, so a manager can hash it (spec §6).

**Most projects need none.** A step lists its code among its
dependencies anyway, so those digests are already in the manager's key
and in the manifest — which is what joins a run to a vouch, directly on
``(path, sha)``.

A certificate earns its place in exactly one case: ``[package] globs``.
A glob has no stable file list, so it cannot be a step dependency; the
only way its composed digest enters a manager's key is as a file.

**Keyed content is code identity only** — no verdict, no ``spec_sha``,
no timestamp. If any entered, vouching something would rebuild it and
rewording prose would rebuild it, destroying the property that a
clarification costs zero compute.

**Serialization is deterministic**: sorted keys, fixed indent, trailing
newline. Regenerating unchanged code must produce a byte-identical file,
or every regeneration would bust every cache — the mechanism would
defeat itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import hashing
from .check import code_manifest
from .parse import Entry, Problem, Project

CERTIFICATE_VERSION = 1
CERT_DIR = "certificates"


def content(project: Project, entry: Entry) -> dict:
    """The certificate document for one entry."""
    manifest = code_manifest(project, entry)
    doc: dict = {
        "certificate_version": CERTIFICATE_VERSION,
        "entry": entry.name,
        "code": {k: v for k, v in sorted(manifest.items()) if k != "package"},
    }
    if "package" in manifest:
        doc["package"] = manifest["package"]
    return doc


def render(doc: dict) -> str:
    """Byte-identical for identical code. Nothing here may vary run to run."""
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def path_for(project: Project, entry_name: str) -> Path:
    return project.specs_dir / CERT_DIR / f"{entry_name}.json"


def certified(project: Project) -> list[str]:
    """The entries that get a certificate: every one with code bound."""
    return sorted(name for name, e in project.entries.items() if e.binding.scripts)


def write_all(project: Project, names: list[str] | None = None) -> list[Path]:
    """Emit a certificate per entry that has code bound — or, given
    ``names``, for those entries only.

    Returns the paths written. Rewriting an unchanged certificate leaves
    the bytes alone, so a regeneration never stales anything — but a
    *changed* one stales every step that depends on it, which is why the
    write can be scoped: certifying two new entries must not also publish
    the uncommitted script edits of sixteen others.
    """
    out: list[Path] = []
    for name in certified(project) if names is None else names:
        target = path_for(project, name)
        text = render(content(project, project.entries[name]))
        if not target.is_file() or target.read_text(encoding="utf-8") != text:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        out.append(target)
    return out


def lagging(project: Project) -> list[tuple[str, Path]]:
    """Certificates on disk whose content is not what ``certify`` would
    write now — ``(entry, path)``, sorted.

    A certificate is derived state with a committed copy, so it can lag
    the code it describes. Where a step lists the certificate (not the
    scripts) among its dependencies, that lag hides a code edit from the
    compute axis: the dependency's bytes did not move, so the run reads
    current while the code under it changed. Nothing else would say so.
    A missing certificate is not lagging — a step that needs it reads
    the path as missing, which is already a break.
    """
    out: list[tuple[str, Path]] = []
    with hashing.memoizing():
        for name in certified(project):
            target = path_for(project, name)
            if not target.is_file():
                continue
            if target.read_text(encoding="utf-8") != render(content(project, project.entries[name])):
                out.append((name, target))
    return out


def certificate_findings(project: Project) -> tuple[list[Problem], list[Problem]]:
    """Lagging certificates as (problems, warnings).

    A problem when some step depends on the certificate — `check` cannot
    be trusted on that step's run axis until it is regenerated — and a
    warning otherwise, where the lag misleads only a reader.
    """
    problems: list[Problem] = []
    warnings: list[Problem] = []
    for name, target in lagging(project):
        rel = target.relative_to(project.root).as_posix()
        users = sorted(sid for sid, step in project.steps.items() if rel in step.deps)
        if users:
            problems.append(
                Problem(
                    "bindings.toml",
                    f"certificate `{rel}` lags `{name}`'s code — step(s) "
                    f"{', '.join(users)} depend on it and cannot see the change; "
                    f"run `specthis certify {name}`",
                )
            )
        else:
            warnings.append(
                Problem(
                    "bindings.toml",
                    f"certificate `{rel}` lags `{name}`'s code — run `specthis certify {name}`",
                )
            )
    return problems, warnings
