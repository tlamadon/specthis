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
files, vocabulary-convention conformance, and the cold-implementer
read (facts an implementer would need that no spec states). The
mention checks below stop exactly where judgment starts: a slug close
to a known name is a typo; a slug close to nothing may be an
undefined concept, and naming it takes the reader.

Scope: `skip: true` specs ARE scanned — a dormant contract is still a
contract, and unchecked dormant text is the rot this module exists to
stop. `draft: true` specs are excluded: their body is prose by
declaration. Pure: reads the loaded project, returns problems, changes
nothing.
"""

from __future__ import annotations

import difflib
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

#: A backticked token — the convention specs use to mention an input,
#: an output, a script, or an entry by name.
_BACKTICK = re.compile(r"`([^`\n]+)`")

#: A hyphenated slug: the entry-name shape. Two segments minimum, so
#: ordinary backticked identifiers (`winsor`, `educ99`) never match.
_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")

#: Slug-shaped vocabulary that is legitimately not an entry: the tool's
#: own agents and commands, which contract prose may name.
_TOOL_SLUGS = frozenset(
    {
        "spec-auditor",
        "spec-reader",
        "spec-critic",
        "spec-implementer",
        "experiment-runner",
        "specthis-vouch",
        "specthis-run",
        "specthis-lint",
        "specthis-journal",
        "specthis-yolo",
    }
)


def _pathlike(token: str) -> str | None:
    """The token, normalized, iff it reads as a project-relative path.

    Deliberately strict — commands, placeholders, globs, and URLs all
    disqualify — because a warning must under-fire: a path we are not
    sure is a path is prose.
    """
    t = token.strip()
    if not t or any(c.isspace() for c in t):
        return None
    if any(c in t for c in "*{}$<>()\\") or "//" in t or ":" in t:
        return None
    if "/" not in t:
        return None
    return t.lstrip("./").rstrip("/")


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

    # Everything a path mention may legitimately name: declared outputs
    # and logical products (which need not exist on disk yet), bound
    # scripts, and the map's translations. Dormant specs included — a
    # mention of a dormant product is wired, not dangling.
    declared: set[str] = set()
    # Every name a slug mention may legitimately use.
    known_names: set[str] = set(spec_names) | set(_TOOL_SLUGS)
    for s in project.specs:
        for e in s.entries:
            known_names.add(e.name)
            known_names.update(e.logical)
            declared.update(e.outputs)
            declared.update(e.logical)
            if e.binding is not None:
                declared.update(e.binding.scripts)
                declared.update(e.binding.produces.values())

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

        # Dangling mentions — only in contract-bearing files (a meta or
        # definitions spec's backticked paths are examples, not claims).
        # Two shapes, both deduped per file:
        #   a path mention nothing declares and nothing on disk matches;
        #   a slug mention that is no known name but is CLOSE to one —
        #   the rename/typo class. A slug close to nothing stays quiet
        #   (spec-reader's job: it may be a concept, not an entry).
        if spec.entries:
            flagged: set[str] = set()
            for line in _body_lines(spec.body):
                for token in _BACKTICK.findall(line):
                    if token in flagged:
                        continue
                    path = _pathlike(token)
                    if path is not None:
                        if path in declared:
                            continue
                        if (project.root / path).exists() or (
                            project.specs_dir / path
                        ).exists():
                            continue
                        flagged.add(token)
                        warnings.append(
                            Problem(
                                fname,
                                f"{fname}: mentions `{token}` — nothing produces it, "
                                "no binding names it, and it is not on disk",
                            )
                        )
                        continue
                    if _SLUG.match(token) and token not in known_names:
                        close = difflib.get_close_matches(token, known_names, n=1, cutoff=0.8)
                        if close:
                            flagged.add(token)
                            warnings.append(
                                Problem(
                                    fname,
                                    f"{fname}: mentions `{token}` — no such entry; "
                                    f"did you mean `{close[0]}`?",
                                )
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
