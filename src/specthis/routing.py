"""Host-doc routing: do the declared artefacts actually reach the paper?

Report/figure specs may declare ``host_doc:`` + ``section_label:`` in
frontmatter, promising that their ``.tex`` exports are pulled into that
labelled section of a top-level LaTeX document. This module scans the
host docs and cross-checks:

- **orphaned export** — the spec exports a ``.tex`` file that the
  labelled section never ``\\input``s / ``\\includegraphics``es.
- **stale routing** — the labelled section inputs something the spec
  does not export (reported as ``extra_inputs``; may be legitimate
  shared content, so it is informational).
- missing host doc / missing label.

Routing findings are *view-layer* consistency warnings, not ledger
claims: they never touch a status and never affect ``check``'s exit
code. A "section" is approximated as the text from one ``\\label{}``
to the next (or EOF) — good enough when labels are section labels,
and cheap. Non-``.tex`` outputs (``.dat`` sidecars, data files) are
exempt: they are read by the figure code, not by the host doc.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .parse import Project, SpecFile

_LABEL = re.compile(r"\\label\{([^}]*)\}")
_INPUT = re.compile(r"\\input\{([^}]*)\}")
_INCLUDEGRAPHICS = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}")
_COMMENT = re.compile(r"(?<!\\)%.*$", re.MULTILINE)


@dataclass
class Section:
    label: str
    line: int  # 1-based line of the \label
    inputs: list[str] = field(default_factory=list)
    includegraphics: list[str] = field(default_factory=list)


@dataclass
class RoutingReport:
    spec: str
    host_doc: str
    section_label: str | None
    host_doc_exists: bool
    label_found: bool
    routed: dict[str, bool] = field(default_factory=dict)  # .tex output -> reached?
    extra_inputs: list[str] = field(default_factory=list)

    @property
    def orphaned(self) -> list[str]:
        return [out for out, ok in self.routed.items() if not ok]

    @property
    def ok(self) -> bool:
        return self.host_doc_exists and self.label_found and not self.orphaned


def scan_host_doc(path: Path) -> dict[str, Section]:
    """Map each ``\\label{}`` in the doc to the inputs of its region."""
    text = _COMMENT.sub("", path.read_text(encoding="utf-8"))
    labels = list(_LABEL.finditer(text))
    sections: dict[str, Section] = {}
    for i, m in enumerate(labels):
        end = labels[i + 1].start() if i + 1 < len(labels) else len(text)
        region = text[m.end() : end]
        sections[m.group(1)] = Section(
            label=m.group(1),
            line=text.count("\n", 0, m.start()) + 1,
            inputs=_INPUT.findall(region),
            includegraphics=_INCLUDEGRAPHICS.findall(region),
        )
    return sections


def _candidates(output: str) -> set[str]:
    """Forms under which a host doc may reference an export path."""
    p = Path(output)
    return {
        output,
        p.as_posix().removesuffix(p.suffix),
        p.name,
        p.stem,
    }


def _spec_report(spec: SpecFile, project: Project, scans: dict[str, dict[str, Section]]) -> RoutingReport:
    report = RoutingReport(
        spec=spec.name,
        host_doc=spec.host_doc or "",
        section_label=spec.section_label,
        host_doc_exists=False,
        label_found=False,
    )
    doc_path = project.root / spec.host_doc  # type: ignore[arg-type]
    report.host_doc_exists = doc_path.is_file()
    if not report.host_doc_exists:
        return report
    if spec.host_doc not in scans:
        scans[spec.host_doc] = scan_host_doc(doc_path)
    section = scans[spec.host_doc].get(spec.section_label or "")
    report.label_found = section is not None
    if section is None:
        return report

    referenced = set(section.inputs) | set(section.includegraphics)
    referenced_forms: set[str] = set()
    for ref in referenced:
        referenced_forms |= _candidates(ref)

    tex_outputs = [
        out
        for entry in spec.entries
        for out in entry.outputs
        if out.endswith(".tex")
    ]
    for out in tex_outputs:
        report.routed[out] = bool(_candidates(out) & referenced_forms)

    exported_forms: set[str] = set()
    for entry in spec.entries:
        for out in entry.outputs:
            exported_forms |= _candidates(out)
    report.extra_inputs = sorted(
        ref for ref in referenced if not (_candidates(ref) & exported_forms)
    )
    return report


def check_routing(project: Project) -> list[RoutingReport]:
    """One report per spec that declares a ``host_doc:``. Pure, no writes.

    Skipped specs are exempt: their artefacts are dormant, so their
    routing is nobody's warning."""
    scans: dict[str, dict[str, Section]] = {}
    return [
        _spec_report(spec, project, scans)
        for spec in project.specs
        if spec.host_doc and not spec.skip
    ]


def build_routing_json(project: Project) -> dict:
    """The ``_routing.json`` view: per host doc, per label, what it pulls in."""
    docs: dict[str, dict] = {}
    for spec in project.specs:
        if not spec.host_doc or spec.host_doc in docs:
            continue
        path = project.root / spec.host_doc
        if not path.is_file():
            docs[spec.host_doc] = {"exists": False, "sections": {}}
            continue
        docs[spec.host_doc] = {
            "exists": True,
            "sections": {
                label: {
                    "line": s.line,
                    "inputs": s.inputs,
                    "includegraphics": s.includegraphics,
                }
                for label, s in scan_host_doc(path).items()
            },
        }
    return {"host_docs": docs}
