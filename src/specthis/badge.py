"""Shields.io endpoint badges: one per tree, for a README.

A **view**, like ``export`` and ``dag`` — regenerated, never read back
by the ledger. It derives nothing: :func:`check.queues` decides
membership on both trees, and everything here only counts, words and
colours the result.

The two badges are computable from a bare git checkout with no data in
it, which is what the no-mtime doctrine buys: absent output bytes leave
a realization ``current`` and merely un-``materialized``, and a consumer
pins its upstream's *recorded* output digest rather than the bytes. So
a CI job needs the repo and nothing else. The one exception is a
``source`` entry, whose subject **is** the bytes — see :func:`unfetched`.

Queue membership is entry-local (``queues`` reads each report's own two
axes, never the propagated pair), so dropping an entry from a count here
cannot silently drop anything downstream of it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .check import Certification, Report, is_source, queues
from .parse import Problem, Project

#: The shields.io endpoint contract. Bump only if they do.
SCHEMA_VERSION = 1

GREEN = "brightgreen"
AMBER = "orange"
RED = "red"
GREY = "lightgrey"

#: Badge name -> the file it is written to, and the label it wears.
LABELS = {"mind": "minds", "machine": "machines"}

_REMOTE = re.compile(r"(?:github\.com[:/])([^/]+/[^/]+?)(?:\.git)?/?$")


def unfetched(project: Project, reports: dict[str, Report]) -> set[str]:
    """Report keys for sources whose bytes are absent but *were* recorded.

    A source entry computes nothing: its data is the subject of both
    claims, so ``code_sha`` is the bytes and the run's input table is the
    bytes. On a checkout without the data, one dataset therefore reads
    ``unimplemented`` on the vouch axis and ``stale`` on the run axis —
    two breaks that neither a mind nor a machine can repair, because
    nothing is actually wrong.

    A row in either ledger is what separates that from a dataset nobody
    ever placed: the digest was recorded once, so the bytes exist
    somewhere. ``badge --no-data`` drops exactly this set, and a source
    that was never recorded stays in the mind queue where it belongs.
    """
    absent = set()
    for key, r in reports.items():
        entry = project.entries[r.instance_of or key]
        if is_source(entry) and r.code_sha is None and (r.vouch or r.run):
            absent.add(key)
    return absent


def _endpoint(label: str, message: str, color: str) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "label": label,
        "message": message,
        "color": color,
    }


def _mind(queue: list[Report], empty: bool) -> dict:
    """The vouch tree: how many definitions are waiting on a mind.

    A rejection is not a larger backlog, it is a different fact — a
    judge said no at exactly these digests — so it takes the colour and
    is counted apart from the merely unjudged.
    """
    label = LABELS["mind"]
    if empty:
        return _endpoint(label, "no entries", GREY)
    if not queue:
        return _endpoint(label, "certified", GREEN)
    rejected = sum(1 for r in queue if r.certification is Certification.REJECTED)
    waiting = len(queue) - rejected
    if rejected:
        msg = f"{rejected} rejected"
        return _endpoint(label, msg if not waiting else f"{msg}, {waiting} waiting", RED)
    return _endpoint(label, f"{waiting} waiting", AMBER)


def _machine(queue: list[Report], empty: bool) -> dict:
    """The run tree: how many realizations are waiting on a machine.

    ``never-run`` and ``stale`` are one word here, the same flattening
    ``Status`` already does — from a badge's distance, both mean the
    recorded call is not the call today's content implies.
    """
    label = LABELS["machine"]
    if empty:
        return _endpoint(label, "no entries", GREY)
    if not queue:
        return _endpoint(label, "current", GREEN)
    return _endpoint(label, f"{len(queue)} stale", AMBER)


def endpoints(
    project: Project,
    reports: dict[str, Report],
    problems: list[Problem] | None = None,
    no_data: bool = False,
) -> dict[str, dict]:
    """Both badges, as shields.io endpoint objects keyed by file stem.

    Grammar problems poison both: a lenient load drops what it cannot
    parse, so a green badge over an unparseable tree would be counting
    the entries that survived and calling it the project.
    """
    if problems:
        n = len(problems)
        return {
            name: _endpoint(label, f"{n} spec problem{'s' * (n != 1)}", RED)
            for name, label in LABELS.items()
        }
    skip = unfetched(project, reports) if no_data else set()
    mind, machine = queues(reports)
    empty = not (set(reports) - skip)
    return {
        "mind": _mind([r for r in mind if r.entry not in skip], empty),
        "machine": _machine([r for r in machine if r.entry not in skip], empty),
    }


def write(out_dir: Path, badges: dict[str, dict]) -> list[Path]:
    """Write one JSON file per badge into ``out_dir``, which is created."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, body in badges.items():
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def slug(remote_url: str) -> str | None:
    """``owner/repo`` out of a GitHub remote, ssh or https. None if neither."""
    m = _REMOTE.search(remote_url.strip())
    return m.group(1) if m else None


def markdown(repo: str, branch: str = "badges") -> str:
    """The README snippet: two badges pointed at the published JSON.

    Static — the URLs never change, only the files behind them do. That
    is the whole reason the branch exists: the README is written once.
    """
    base = f"https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/{repo}/{branch}"
    return "\n".join(
        f"[![{label}]({base}/{name}.json)](https://github.com/{repo})"
        for name, label in LABELS.items()
    )
