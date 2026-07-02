"""Journal: dated narrative entries under ``<root>/journal/``.

A journal entry is prose, not a claim: the ledger neither reads nor
hashes it, and no status ever depends on one. The convention (carried
over from the original POC) is one markdown file per entry named
``journal/YYYY-MM-DD-<slug>.md`` — the narrative behind a result, the
dead ends, the numbers — plus any sidecar artefacts (JSON bundles,
figures) committed next to it so they stay downloadable even when the
results directory is gitignored.

Parsing is deliberately lenient — there is no journal grammar to
violate. The date comes from the filename prefix (missing → sorted
last), the title from frontmatter ``title:``, else the first ``#``
heading, else the prettified slug.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .parse import _FRONTMATTER

JOURNAL_DIR = "journal"

_DATE_PREFIX = re.compile(r"\A(\d{4}-\d{2}-\d{2})(?:-|\Z)")


@dataclass
class JournalEntry:
    path: Path
    stem: str  # filename stem, e.g. ``2026-06-30-smc-ffbs-resampling-fix``
    date: str  # ``YYYY-MM-DD`` from the filename, or "" when it carries none
    title: str
    body: str  # markdown after the (optional) frontmatter


def _title_and_body(text: str, stem: str, date: str) -> tuple[str, str]:
    title = None
    body = text
    m = _FRONTMATTER.match(text)
    if m:
        body = text[m.end() :]
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        if isinstance(meta, dict) and meta.get("title"):
            title = str(meta["title"])
    if title is None:
        heading = re.search(r"^# +(.+?)\s*$", body, re.MULTILINE)
        if heading:
            title = heading.group(1)
    if title is None:
        slug = stem[len(date) :].lstrip("-") if date else stem
        title = slug.replace("-", " ").replace("_", " ").strip() or stem
    return title, body


def load_journal(root: Path) -> list[JournalEntry]:
    """Read ``<root>/journal/*.md``, newest first (undated files last)."""
    journal_dir = root / JOURNAL_DIR
    if not journal_dir.is_dir():
        return []
    entries = []
    for path in journal_dir.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        m = _DATE_PREFIX.match(path.stem)
        date = m.group(1) if m else ""
        title, body = _title_and_body(text, path.stem, date)
        entries.append(JournalEntry(path=path, stem=path.stem, date=date, title=title, body=body))
    return sorted(entries, key=lambda e: (e.date != "", e.date, e.stem), reverse=True)
