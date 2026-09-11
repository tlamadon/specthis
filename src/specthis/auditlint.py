"""Mechanical checks on spec *text* — the cheap half of the audit.

The pipeline is authored, not generated (`specification.md` §7), so
lint replaces a compiler — and a compiler would also have rejected
text that points at nothing: a `references:` edge the body never
mentions, a markdown link to a file that is not there, project state
pasted into a contract. Every check here is exact and needs no model;
discovering the same defects through per-entry critics is the most
expensive instrument in the system, and one bad yolo session proved it.

Deliberately **not** here — these need a reader, not a regex, and
belong to the `spec-reader` agent: enumeration counts in prose ("six
steps" over five bullets), claim contradictions within or across
files, and vocabulary-convention conformance.

Scope: `skip: true` specs ARE scanned — a dormant contract is still a
contract, and unchecked dormant text is the rot this module exists to
stop. `draft: true` specs are excluded: their body is prose by
declaration. Pure: reads the loaded project, returns problems, changes
nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

from .parse import Problem, Project, SpecFile

#: Project state has no place in a contract: status is derived, never
#: authored, and scripts live in bindings.toml. Line-anchored so prose
#: *about* these keys (backticked mid-sentence) stays legal.
_STATE_LEAK = re.compile(r"^(?:- )?(Script|Status|depends_on):")

#: ``[text](target)`` — the same link population export's viewer
#: rewrites; a target it cannot resolve renders dangling there.
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

#: Targets that are not files of ours: schemes, protocol-relative
#: URLs, and pure in-page anchors.
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)")

_ARTEFACT_DESIGN = re.compile(r"^##\s+Artefact design\b", re.MULTILINE)


def _body_lines(body: str):
    """Body lines outside fenced code blocks — examples are not leaks."""
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            yield line


def _checked(project: Project) -> list[SpecFile]:
    return [s for s in project.specs if not s.draft]


def spec_text_problems(project: Project) -> list[Problem]:
    """Text defects that fail lint and hold the check verdict."""
    problems: list[Problem] = []
    for spec in _checked(project):
        fname = spec.path.name
        for line in _body_lines(spec.body):
            leak = _STATE_LEAK.match(line)
            if leak:
                problems.append(
                    Problem(
                        fname,
                        f"{fname}: `{leak.group(1)}:` is project state in a spec body — "
                        "status is derived, scripts live in bindings.toml",
                    )
                )
    return problems


def spec_text_warnings(project: Project) -> list[Problem]:
    """Advisory findings: never fatal, and never in ``check --json`` —
    the yolo Stop hook blocks on problems, and advice must not trap a
    session."""
    warnings: list[Problem] = []
    spec_names = {s.name for s in project.specs}
    journal_stems = {p.stem for p in (project.root / "journal").glob("*.md")}

    for spec in _checked(project):
        fname = spec.path.name

        # A references: edge the body never speaks of is either a
        # leftover or a missing paragraph. Stem-substring on purpose —
        # a warning must under-fire, not over-fire.
        for ref in spec.references:
            if Path(ref).stem not in spec.body:
                warnings.append(
                    Problem(
                        fname,
                        f"{fname}: references `{ref}` but the body never mentions it — "
                        "drop the edge or add the prose",
                    )
                )

        # Markdown links to .md files nothing can resolve render
        # dangling in the exported viewer (export._rewrite_spec_links
        # leaves unknown stems untouched).
        for line in _body_lines(spec.body):
            for target in _MD_LINK.findall(line):
                if _EXTERNAL.match(target):
                    continue
                path = target.partition("#")[0]
                if not path.endswith(".md"):
                    continue
                stem = Path(path).stem
                if stem in spec_names or stem in journal_stems:
                    continue
                if any(
                    (base / path).is_file()
                    for base in (spec.path.parent, project.specs_dir, project.root)
                ):
                    continue
                warnings.append(
                    Problem(fname, f"{fname}: link to `{path}` resolves to nothing")
                )

        # Scope creep: a compute entry that outputs under reports/ is
        # doing a report spec's job. Only the Output-path half is
        # mechanical; compute *code* importing plotting libraries needs
        # a reader of code, which lint is not.
        for entry in spec.entries:
            if entry.kind != "compute":
                continue
            for out in entry.outputs:
                if out.lstrip("./").startswith("reports/"):
                    warnings.append(
                        Problem(
                            fname,
                            f"{fname}: compute entry `{entry.name}` outputs `{out}` — "
                            "figures and tables belong to the paired report spec",
                        )
                    )

        if any(e.kind == "report" for e in spec.entries) and not _ARTEFACT_DESIGN.search(
            spec.body
        ):
            warnings.append(
                Problem(
                    fname,
                    f"{fname}: report entries but no `## Artefact design` section — "
                    "the artefact's look is part of the contract",
                )
            )
    return warnings
