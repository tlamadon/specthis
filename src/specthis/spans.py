"""Document spans: one addressed piece of a manuscript, as a digest (§5.8).

The chain used to end at bytes. The thing a research project ships — the
manuscript — sat one link past the end, so the judgment that mattered most
in a paper audit, *the paper describes what the spec says*, had no subject
to attach to, and a table nobody declared was invisible. An **exhibit**
entry (§2) makes the manuscript a terminal node of the graph, and this
module supplies the one digest kind it needs: ``doc:<document>#<label>``,
the digest of one span of a document — so one manuscript carries many
independently pinned subjects, the way one spec file carries many blocks.

**Locating a span is the only LaTeX known here.** A label written
``\\label{tab:paths}`` addresses the innermost environment enclosing it
(``\\begin{table}`` … ``\\end{table}``), skipping ``document`` and the
alignment wrappers in :data:`TRANSPARENT`. A marker pair on lines of their
own — ``% specthis:begin{L}`` … ``% specthis:end{L}`` — addresses the lines
between them, for prose that has no environment, and overrides the
environment rule for its label. specthis never parses a number.

**The digest covers what the paper prints, not how its source is laid
out.** Co-authors reflow paragraphs constantly, so whitespace runs collapse
to one space and, in a ``.tex`` file, comments are dropped the way TeX
drops them (a ``%`` eats its line break). A reflow or a comment never
expires a judgment; a changed word always does.

Pure: reads files, returns digests and findings, writes nothing.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import hashing
from .parse import Appearance, Document, Entry, Problem, Project

#: Environments a label never names. ``document`` encloses everything; the
#: alignment wrappers carry no identity of their own — a label inside
#: ``\begin{center}`` names the float around it, and pinning only the
#: wrapper would leave a table note below ``\end{center}`` outside the
#: claim. A wider span costs a re-judgment; a narrower one is drift that
#: nobody sees, which is the failure a notary exists to prevent.
TRANSPARENT = frozenset({"document", "center", "flushleft", "flushright"})

#: The class a marker-pair span reports in place of an environment name.
MARKER = "marker"

_ENV = re.compile(r"\\(begin|end)\s*\{([^{}\s]+)\}")
_LABEL = re.compile(r"\\label\s*\{([^{}]+)\}")
_MARKER = re.compile(r"specthis:(begin|end)\{([^{}\s]+)\}")


def is_tex(rel: str) -> bool:
    """Comment rules apply to LaTeX sources only: in markdown, ``3.2%`` is
    printed text, and treating it as a comment would unpin the rest of
    its line."""
    return rel.lower().endswith(".tex")


# ------------------------------------------------------------ comments


def _comment_at(line: str) -> int:
    """Index of the first comment ``%`` in a line, or -1.

    A ``%`` after an odd run of backslashes is escaped (``\\%``); after an
    even run it is a comment again (``\\\\%`` is a line break, then one).
    """
    run = 0
    for i, ch in enumerate(line):
        if ch == "\\":
            run += 1
            continue
        if ch == "%" and run % 2 == 0:
            return i
        run = 0
    return -1


def _blank_comments(text: str) -> str:
    """The text with every comment overwritten by spaces — same length,
    same offsets — so environments and labels are found only where TeX
    would see them."""
    out = []
    for line in text.split("\n"):  # TeX's line ends, not str.splitlines'
        body = line.rstrip("\r")
        cut = _comment_at(body)
        if cut >= 0:
            line = body[:cut] + " " * (len(body) - cut) + line[len(body):]
        out.append(line)
    return "\n".join(out)


def _strip_comments(text: str) -> str:
    """Drop comments as TeX does: a ``%`` eats the rest of its line, the
    line break, and the next line's leading blanks — so ``foo%`` then
    ``bar`` reads ``foobar``, exactly what is printed."""
    parts: list[str] = []
    glue = False
    for line in text.split("\n"):
        if glue:
            line = line.lstrip(" \t")
        elif parts:
            parts.append("\n")
        cut = _comment_at(line)
        parts.append(line if cut < 0 else line[:cut])
        glue = cut >= 0
    return "".join(parts)


def normalize(text: str, tex: bool) -> str:
    """The span as printed: comments gone (``.tex``), whitespace collapsed."""
    if tex:
        text = _strip_comments(text)
    return " ".join(text.split())


# ---------------------------------------------------------------- scan


@dataclass(frozen=True)
class Site:
    """Where one label lives, and the span it addresses.

    ``env`` is the span's environment class, :data:`MARKER` for a marker
    pair, or ``None`` when the label sits in no environment — a section
    label, say — and so addresses nothing until it is marked.
    """

    label: str
    file: str  # project-relative
    line: int  # 1-based: the label's line, or the begin marker's
    env: str | None
    start: int = 0  # character offsets of the span in the file's text
    end: int = 0
    lines: tuple[int, int] = (0, 0)  # the span's first and last line


@dataclass
class Scan:
    """Every label one document defines, and what is malformed in it."""

    files: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    sites: dict[str, list[Site]] = field(default_factory=dict)
    #: Marker errors — specthis's own grammar inside the manuscript.
    problems: list[str] = field(default_factory=list)


@lru_cache(maxsize=64)
def _scan_text(rel: str, text: str) -> tuple[dict[str, tuple[Site, ...]], tuple[str, ...]]:
    """Index one file. Cached on its content: a pure function of the
    text, so a hit can never be stale — and a paper printing forty
    exhibits is indexed once, not forty times."""
    clean = _blank_comments(text) if is_tex(rel) else text
    newlines = [i for i, ch in enumerate(text) if ch == "\n"]

    def line_of(pos: int) -> int:
        return bisect.bisect_right(newlines, pos - 1) + 1

    # Environments, by a stack walk: a stray \end closes the nearest
    # open environment of its name, and an unclosed \begin encloses
    # nothing — LaTeX would refuse the file, and guessing an extent
    # would pin text the author never grouped.
    stack: list[tuple[str, int]] = []
    envs: list[tuple[str, int, int]] = []
    for m in _ENV.finditer(clean):
        kind, name = m.group(1), m.group(2)
        if kind == "begin":
            stack.append((name, m.start()))
            continue
        for depth in range(len(stack) - 1, -1, -1):
            if stack[depth][0] == name:
                envs.append((name, stack[depth][1], m.end()))
                del stack[depth:]
                break

    sites: dict[str, list[Site]] = {}
    for m in _LABEL.finditer(clean):
        pos = m.start()
        around = [
            e for e in envs if e[1] < pos < e[2] and e[0].rstrip("*") not in TRANSPARENT
        ]
        if around:
            name, a, b = max(around, key=lambda e: e[1])  # innermost
            site = Site(
                m.group(1), rel, line_of(pos), name, a, b, (line_of(a), line_of(b - 1))
            )
        else:
            site = Site(m.group(1), rel, line_of(pos), None)
        sites.setdefault(m.group(1), []).append(site)

    # Marker pairs, on the raw text (they live in comments): the span is
    # the lines strictly between them.
    problems: list[str] = []
    opened: dict[str, tuple[int, int]] = {}
    marked: dict[str, list[Site]] = {}
    offset = 0
    for no, line in enumerate(text.split("\n"), 1):
        width = len(line) + 1  # the newline the split consumed
        for m in _MARKER.finditer(line):
            kind, label = m.group(1), m.group(2)
            if kind == "begin":
                if label in opened:
                    problems.append(
                        f"{rel}:{no}: `specthis:begin{{{label}}}` opens a span already "
                        f"open since line {opened[label][0]}"
                    )
                else:
                    opened[label] = (no, offset + width)  # starts after this line
            elif label not in opened:
                problems.append(f"{rel}:{no}: `specthis:end{{{label}}}` closes no span")
            else:
                first, start = opened.pop(label)
                if first == no:
                    problems.append(
                        f"{rel}:{no}: `specthis:begin{{{label}}}` and its end share a line "
                        "— put each marker on a line of its own"
                    )
                    continue
                marked.setdefault(label, []).append(
                    Site(label, rel, first, MARKER, start, offset, (first, no))
                )
        offset += width
    for label, (no, _) in sorted(opened.items(), key=lambda kv: kv[1]):
        problems.append(f"{rel}:{no}: `specthis:begin{{{label}}}` is never closed")
    sites.update(marked)  # a marker pair overrides the environment rule
    return {k: tuple(v) for k, v in sites.items()}, tuple(problems)


def files_of(project: Project, doc: Document) -> list[str]:
    """The document's files, project-relative: each ``path`` entry is a
    file, or a glob over several (a paper split into section files is
    still one label namespace, as LaTeX compiles it)."""
    out: list[str] = []
    for pattern in doc.paths:
        if any(c in pattern for c in "*?["):
            out.extend(
                sorted(
                    p.relative_to(project.root).as_posix()
                    for p in project.root.glob(pattern)
                    if p.is_file()
                )
            )
        else:
            out.append(pattern)
    return list(dict.fromkeys(out))


def scan(project: Project, doc: Document) -> Scan:
    """Every label across the document's files. A label defined twice —
    in one file or across two — is kept twice, so the ambiguity stays
    visible instead of one definition silently winning."""
    out = Scan(files=files_of(project, doc))
    for rel in out.files:
        text = hashing.file_text(project.root / rel)
        if text is None:
            out.missing.append(rel)
            continue
        sites, problems = _scan_text(rel, text)
        for label, found in sites.items():
            out.sites.setdefault(label, []).extend(found)
        out.problems.extend(problems)
    return out


# ------------------------------------------------------------- resolve

#: Why an appearance addresses no span — the kind decides who reports it.
#: A missing file or label is a *state* (the exhibit is unimplemented,
#: like code not yet written); an ambiguous or unplaceable label is the
#: author's grammar to fix, so lint names it.
UNDECLARED, NO_FILE, NO_LABEL, AMBIGUOUS, NO_ENVIRONMENT = (
    "undeclared",
    "no-file",
    "no-label",
    "ambiguous",
    "no-environment",
)


@dataclass(frozen=True)
class Resolution:
    site: Site | None
    why: str = ""
    kind: str = ""


def resolve(project: Project, a: Appearance) -> Resolution:
    """The span one appearance addresses, or why it addresses none."""
    doc = project.documents.get(a.document)
    if doc is None:
        return Resolution(
            None, f"no document `{a.document}` in specs/bindings.toml [documents]", UNDECLARED
        )
    found = scan(project, doc)
    sites = found.sites.get(a.label, [])
    if not sites:
        present = [f for f in found.files if f not in found.missing]
        if not present:
            where = ", ".join(found.missing) or ", ".join(doc.paths)
            return Resolution(None, f"{a.document}: no file at {where}", NO_FILE)
        return Resolution(
            None, f"no `\\label{{{a.label}}}` in {a.document} ({', '.join(present)})", NO_LABEL
        )
    if len(sites) > 1:
        where = ", ".join(f"{s.file}:{s.line}" for s in sites)
        return Resolution(
            None,
            f"`{a.label}` is defined {len(sites)} times in {a.document} ({where}) — "
            "a span needs one address",
            AMBIGUOUS,
        )
    site = sites[0]
    if site.env is None:
        return Resolution(
            None,
            f"`\\label{{{a.label}}}` ({site.file}:{site.line}) sits in no environment — "
            f"mark its span with `% specthis:begin{{{a.label}}}` … "
            f"`% specthis:end{{{a.label}}}`",
            NO_ENVIRONMENT,
        )
    return Resolution(site)


def span_sha(project: Project, a: Appearance) -> str | None:
    """``doc:<document>#<label>`` — the normalized span's digest, or
    ``None`` when the appearance addresses no span."""
    site = resolve(project, a).site
    if site is None:
        return None
    text = hashing.file_text(project.root / site.file) or ""
    return hashing.sha256_text(normalize(text[site.start : site.end], is_tex(site.file)))


def exhibit_manifest(project: Project, entry: Entry) -> dict[str, str]:
    """What an exhibit's vouch pins besides its own contract (§8).

    One ``doc:`` row per appearance — the span as printed — and one
    ``spec:<entry>`` row per consumed entry, carrying that entry's
    *contract* digest (§5.2b): the description is judged against the
    contract, so it expires exactly when the contract it describes does,
    and a sibling's edit in the same file moves nothing. An unresolved
    span is :data:`hashing.MISSING`, which no digest equals.
    """
    rows = {a.row: span_sha(project, a) or hashing.MISSING for a in entry.appears}
    for up in entry.consumes:
        up_entry = project.entries.get(up)
        rows[f"spec:{up}"] = up_entry.contract_sha if up_entry is not None else hashing.MISSING
    return rows


def unresolved(project: Project, entry: Entry) -> list[str]:
    """Why an exhibit has nothing to judge — empty when every span resolves."""
    if not entry.appears:
        return ["it appears in no declared document"]
    return [r.why for a in entry.appears if (r := resolve(project, a)).site is None]


# ---------------------------------------------------------------- lint


def _exhibits(project: Project, live_only: bool) -> list[tuple[str, Entry]]:
    """(spec file, exhibit) pairs. Dormant exhibits still *claim* labels
    — a dormant contract is still a contract — but only live ones are
    held to a resolvable span."""
    out = []
    for spec in project.specs:
        if spec.draft or (live_only and spec.skip):
            continue
        out.extend((spec.path.name, e) for e in spec.entries if e.kind == "exhibit")
    return out


def claims(project: Project) -> dict[str, dict[str, list[str]]]:
    """document -> label -> the exhibits appearing there."""
    out: dict[str, dict[str, list[str]]] = {}
    for _, e in _exhibits(project, live_only=False):
        for a in e.appears:
            out.setdefault(a.document, {}).setdefault(a.label, []).append(e.name)
    return out


def policed(doc: Document, found: Scan) -> list[Site]:
    """The labels lint holds to an exhibit: every label whose span is an
    environment of a configured class (``table*`` counts as ``table``),
    and every marker pair — a marker exists only to be claimed."""
    classes = {c.rstrip("*") for c in doc.environments}
    out = []
    for sites in found.sites.values():
        site = sites[0]
        if site.env == MARKER or (site.env is not None and site.env.rstrip("*") in classes):
            out.append(site)
    return sorted(out, key=lambda s: (s.file, s.line))


@dataclass
class Census:
    """One document's labels, sorted by what backs them."""

    orphans: list[Site] = field(default_factory=list)
    unbacked: list[str] = field(default_factory=list)


def census(project: Project, doc: Document, found: Scan | None = None) -> Census:
    """Orphans — policed labels no exhibit claims and nobody declared
    unbacked — and the labels declared unbacked that the document has."""
    found = scan(project, doc) if found is None else found
    claimed = claims(project).get(doc.name, {})
    declared = set(doc.unbacked)
    return Census(
        orphans=[
            s for s in policed(doc, found) if s.label not in claimed and s.label not in declared
        ],
        unbacked=[label for label in doc.unbacked if label in found.sites],
    )


def document_problems(project: Project) -> list[Problem]:
    """What fails lint: malformed marker pairs, and live exhibits whose
    span is ambiguous or unplaceable. (A missing file or label is a
    state, reported by ``check`` as unimplemented — like absent code.)"""
    with hashing.memoizing():  # one read per document, however many exhibits
        return _document_problems(project)


def _document_problems(project: Project) -> list[Problem]:
    out: list[Problem] = []
    for name, doc in sorted(project.documents.items()):
        out.extend(
            Problem("bindings.toml", f"document `{name}`: {p}") for p in scan(project, doc).problems
        )
    for fname, e in _exhibits(project, live_only=True):
        for a in e.appears:
            r = resolve(project, a)
            if r.kind in (AMBIGUOUS, NO_ENVIRONMENT):
                out.append(Problem(fname, f"{fname}: `{e.name}` appears at `{a.key}`, but {r.why}"))
    return out


def document_warnings(project: Project) -> list[Problem]:
    """The orphan detector, and the drift in its own configuration.

    Warnings, never failures: the manuscript is co-authored prose, and a
    table nobody has traced yet is the finding, not a broken build.
    """
    with hashing.memoizing():
        return _document_warnings(project)


def _document_warnings(project: Project) -> list[Problem]:
    out: list[Problem] = []
    all_claims = claims(project)
    for name, doc in sorted(project.documents.items()):
        found = scan(project, doc)
        for rel in found.missing:
            out.append(
                Problem("bindings.toml", f"document `{name}`: no file at `{rel}` — "
                        "nothing printed there can be judged")
            )
        if not found.files:
            out.append(
                Problem("bindings.toml", f"document `{name}`: `path` matches no file")
            )
        claimed = all_claims.get(name, {})
        for site in census(project, doc, found).orphans:
            what = "marked span" if site.env == MARKER else site.env
            out.append(
                Problem(
                    "bindings.toml",
                    f"{name} ({site.file}:{site.line}): {what} `{site.label}` is claimed by "
                    "no exhibit — write one that consumes what produced it, or list it in "
                    f"[documents.{name}] unbacked",
                )
            )
        for label in doc.unbacked:
            if label not in found.sites and found.files and not found.missing:
                out.append(
                    Problem(
                        "bindings.toml",
                        f"[documents.{name}] lists `{label}` as unbacked, but {name} "
                        "defines no such label",
                    )
                )
            elif label in claimed:
                out.append(
                    Problem(
                        "bindings.toml",
                        f"[documents.{name}] lists `{label}` as unbacked, yet "
                        f"{', '.join(claimed[label])} claims it — drop it from unbacked",
                    )
                )
        for label, sites in sorted(found.sites.items()):
            if len(sites) > 1 and label not in claimed:
                where = ", ".join(f"{s.file}:{s.line}" for s in sites)
                out.append(
                    Problem(
                        "bindings.toml",
                        f"{name}: `{label}` is defined {len(sites)} times ({where})",
                    )
                )
    return out


def location(site: Site) -> str:
    """``paper/paper.tex:40-52 (table)`` — for ``status`` and the critic,
    who must read exactly the lines the digest covers."""
    first, last = site.lines
    lines = f"{first}-{last}" if last > first else f"{first}"
    return f"{site.file}:{lines} ({site.env})"
