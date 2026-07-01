"""Spec consistency audit (operation 1 from specs/AGENTS.md).

Status: **stub**. The reference implementation is index-based: it
reads ``specs/_index.json`` and ``specs/_routing.json`` (produced by
:mod:`specthis.export`) and reports, per entry, the implementation
node status (``unimplemented`` / ``ready`` / ``audit needed``),
authorship validity, contract-in-spirit, output schema, export
routing, and artifact freshness in a single markdown table.

Port plan:
- ``walk_index(specs_dir) -> list[EntryReport]``
- ``check_compute_entry(entry, index) -> EntryReport``
- ``check_report_entry(entry, index, routing) -> EntryReport``
- ``format_table(reports) -> str``

Until ported, invoke the bundled ``spec-auditor`` subagent in Claude
Code instead — it implements the same checks by reading the index
files directly.
"""

from __future__ import annotations

from pathlib import Path


def run_audit(specs_dir: Path) -> str:  # pragma: no cover - stub
    raise NotImplementedError(
        "specthis.audit is not yet ported. Use the spec-auditor subagent "
        "(installed by `specthis install`) in the meantime."
    )
