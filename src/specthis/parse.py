"""Parse ``specs/*.md`` (frontmatter + entry blocks) and ``specs/bindings.toml``.

The grammar (documented for users in the bundled ``specs/README.md``
template):

- Every ``.md`` file starts with YAML frontmatter declaring ``name``,
  ``kind``, and the two edge lists: ``consumes:`` (entry names —
  artefact flow, enters signatures) and ``references:`` (spec files —
  vocabulary, ledger-invisible). Compute specs add
  ``tier: intensive | quick``.
- Executable kinds (``compute``, ``report``, ``figure``) carry a
  ``## Entry`` (single) or ``## Entries`` (multi) section whose
  ``### <entry-name>`` blocks each declare ``Output:`` (compute, one
  path) or ``Export outputs:`` (report/figure, one or more paths).

``bindings.toml`` is hand-edited vocabulary, not a claim: it maps each
entry to the scripts that implement it, the command that runs it, and
(optionally) scripthut workflow files and an executor label. A
``[package]`` table declares the shared-library globs whose blob
digest enters every code manifest.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from .hashing import sha256_text

KINDS = {"meta", "definitions", "templates", "library", "compute", "report", "figure"}
ENTRY_KINDS = {"library", "compute", "report", "figure"}
TIERS = {"intensive", "quick"}

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_ENTRY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_BACKTICKED = re.compile(r"`([^`]+)`")


class SpecError(Exception):
    """A spec file or bindings file violates the documented grammar."""


@dataclass
class Problem:
    """One grammar violation, attributed to a file.

    ``message`` is self-describing (it already names the file);
    ``file`` exists so views can group problems per file.
    """

    file: str
    message: str


@dataclass
class Binding:
    scripts: list[str]
    run: str | None
    workflows: list[str] = field(default_factory=list)
    executor: str | None = None


@dataclass
class Entry:
    name: str
    spec: "SpecFile"
    outputs: list[str]
    binding: Binding

    @property
    def consumes(self) -> list[str]:
        return self.spec.consumes

    @property
    def tier(self) -> str:
        return self.spec.tier


@dataclass
class SpecFile:
    path: Path
    name: str
    kind: str
    tier: str
    consumes: list[str]
    references: list[str]
    spec_sha: str  # sha256 of the FULL file text, frontmatter included
    body: str  # markdown after the frontmatter (the contract prose)
    title: str = ""  # display title: frontmatter `title:`, else first heading, else name
    entries: list[Entry] = field(default_factory=list)
    host_doc: str | None = None
    section_label: str | None = None


@dataclass
class Project:
    root: Path
    specs_dir: Path
    specs: list[SpecFile]
    entries: dict[str, Entry]
    package_globs: list[str]
    cache_url: str | None = None
    #: scripts bound to library entries — excluded from the package blob,
    #: so a module edit flags only its own entry and its consumers.
    library_scripts: frozenset[str] = frozenset()


def _field_paths(block: str, label: str) -> list[str]:
    """Extract path(s) declared by ``<label>:`` inside an entry block.

    Paths are taken from backticked spans on the field line and on any
    immediately following ``- `` list lines; without backticks the
    first whitespace-delimited token is used.
    """
    lines = block.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(f"{label}:"):
            continue
        paths: list[str] = []
        rest = stripped[len(label) + 1 :].strip()
        if rest:
            ticked = _BACKTICKED.findall(rest)
            paths.extend(ticked if ticked else [rest.split()[0]])
        for follow in lines[i + 1 :]:
            item = follow.strip()
            if not item.startswith("- "):
                break
            ticked = _BACKTICKED.findall(item)
            paths.extend(ticked if ticked else [item[2:].split()[0]])
        return paths
    return []


def _str_list(raw: object, where: str, what: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise SpecError(f"{where}: `{what}` must be a list of strings")
    return raw


def parse_spec(path: Path) -> SpecFile:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(text)
    if not m:
        raise SpecError(f"{path.name}: missing YAML frontmatter block")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SpecError(f"{path.name}: bad frontmatter YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise SpecError(f"{path.name}: frontmatter must be a mapping")

    if "depends_on" in meta:
        raise SpecError(
            f"{path.name}: `depends_on:` is retired — split it into "
            "`consumes:` (upstream entry names) and `references:` (vocabulary specs)"
        )
    kind = meta.get("kind")
    if kind not in KINDS:
        raise SpecError(f"{path.name}: `kind: {kind}` is not one of {sorted(KINDS)}")
    name = meta.get("name")
    if name != path.stem:
        raise SpecError(f"{path.name}: `name: {name}` must match the filename stem")

    tier = meta.get("tier", "intensive" if kind == "compute" else "quick")
    if tier not in TIERS:
        raise SpecError(f"{path.name}: `tier: {tier}` is not one of {sorted(TIERS)}")

    body = text[m.end() :]
    heading = re.search(r"^# +(.+?)\s*$", body, re.MULTILINE)
    spec = SpecFile(
        path=path,
        name=name,
        kind=kind,
        tier=tier,
        consumes=_str_list(meta.get("consumes"), path.name, "consumes"),
        references=_str_list(meta.get("references"), path.name, "references"),
        spec_sha=sha256_text(text),
        body=body,
        title=str(meta.get("title") or (heading.group(1) if heading else name)),
        host_doc=meta.get("host_doc"),
        section_label=meta.get("section_label"),
    )

    if kind in ENTRY_KINDS:
        label = "Output" if kind == "compute" else "Export outputs"
        for block_match in re.finditer(
            r"^### +(.+?)\s*$\n(.*?)(?=^### |^## |\Z)", body, re.MULTILINE | re.DOTALL
        ):
            entry_name = block_match.group(1).strip()
            if not _ENTRY_NAME.match(entry_name):
                raise SpecError(f"{path.name}: bad entry name `{entry_name}`")
            if kind == "library":
                # A library entry is judged code with no artifact: the
                # chain stops at code, so an Output: is a contradiction.
                if _field_paths(block_match.group(2), "Output") or _field_paths(
                    block_match.group(2), "Export outputs"
                ):
                    raise SpecError(
                        f"{path.name}: library entry `{entry_name}` must not declare an output"
                    )
                outputs: list[str] = []
            else:
                outputs = _field_paths(block_match.group(2), label)
                if not outputs:
                    raise SpecError(
                        f"{path.name}: entry `{entry_name}` declares no `{label}:` path"
                    )
                if kind == "compute" and len(outputs) > 1:
                    raise SpecError(
                        f"{path.name}: compute entry `{entry_name}` must declare exactly one output"
                    )
            spec.entries.append(
                Entry(name=entry_name, spec=spec, outputs=outputs, binding=None)  # type: ignore[arg-type]
            )
    return spec


def _load_bindings(specs_dir: Path) -> tuple[dict[str, Binding], list[str], str | None]:
    path = specs_dir / "bindings.toml"
    if not path.is_file():
        return {}, [], None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f"bindings.toml: {exc}") from exc
    globs = _str_list(data.get("package", {}).get("globs"), "bindings.toml", "package.globs")
    cache_url = data.get("cache", {}).get("url")
    bindings: dict[str, Binding] = {}
    for entry_name, table in data.get("entries", {}).items():
        bindings[entry_name] = Binding(
            scripts=_str_list(table.get("scripts"), "bindings.toml", "scripts"),
            run=table.get("run"),
            workflows=_str_list(table.get("workflows"), "bindings.toml", "workflows"),
            executor=table.get("executor"),
        )
    return bindings, globs, cache_url


def _default_binding(entry_name: str) -> Binding:
    # The documented naming convention: an unbound entry is implemented
    # by scripts/<entry>.py and run with the project's python.
    script = f"scripts/{entry_name}.py"
    return Binding(scripts=[script], run=f"python {script}")


def load_project_lenient(root: Path) -> tuple[Project, list[Problem]]:
    """Parse ``<root>/specs/``, collecting grammar problems instead of dying.

    Unparseable files are excluded from the project; invalid edges are
    dropped; an unbound library entry keeps an empty binding (deriving
    *unimplemented*). Every accommodation is recorded as a
    :class:`Problem` so callers can surface the full list. Only a
    missing ``specs/`` directory still raises.
    """
    specs_dir = root / "specs"
    if not specs_dir.is_dir():
        raise SpecError(f"no specs/ directory under {root}")

    problems: list[Problem] = []
    specs: list[SpecFile] = []
    for path in sorted(specs_dir.glob("*.md")):
        try:
            specs.append(parse_spec(path))
        except SpecError as exc:
            problems.append(Problem(path.name, str(exc)))

    try:
        bindings, package_globs, cache_url = _load_bindings(specs_dir)
    except SpecError as exc:
        problems.append(Problem("bindings.toml", str(exc)))
        bindings, package_globs, cache_url = {}, [], None

    entries: dict[str, Entry] = {}
    for spec in specs:
        for entry in list(spec.entries):
            if entry.name in entries:
                problems.append(
                    Problem(
                        spec.path.name,
                        f"duplicate entry name `{entry.name}` "
                        f"({entries[entry.name].spec.path.name} and {spec.path.name})",
                    )
                )
                spec.entries.remove(entry)
                continue
            if spec.kind == "library":
                # Modules live at arbitrary package paths; no naming
                # convention can guess them, so the binding is mandatory.
                binding = bindings.get(entry.name)
                if binding is None or not binding.scripts:
                    problems.append(
                        Problem(
                            spec.path.name,
                            f"{spec.path.name}: library entry `{entry.name}` needs "
                            "`scripts` in specs/bindings.toml (no convention default)",
                        )
                    )
                    entry.binding = Binding(scripts=[], run=None)
                else:
                    entry.binding = binding
            else:
                entry.binding = bindings.get(entry.name, _default_binding(entry.name))
            entries[entry.name] = entry

    spec_names = {s.name for s in specs}
    for spec in specs:
        for up in list(spec.consumes):
            if up not in entries:
                problems.append(
                    Problem(spec.path.name, f"{spec.path.name}: consumes unknown entry `{up}`")
                )
                spec.consumes.remove(up)
        for ref in spec.references:
            if Path(ref).stem not in spec_names:
                problems.append(
                    Problem(spec.path.name, f"{spec.path.name}: references unknown spec `{ref}`")
                )

    project = Project(
        root=root,
        specs_dir=specs_dir,
        specs=specs,
        entries=entries,
        package_globs=package_globs,
        cache_url=cache_url,
        library_scripts=frozenset(
            s
            for e in entries.values()
            if e.spec.kind == "library"
            for s in e.binding.scripts
        ),
    )
    return project, problems


def load_project(root: Path) -> Project:
    """Parse ``<root>/specs/`` into a validated DAG; any problem raises.

    The strict form, used by the writing verbs (run/vouch/migrate) —
    a ledger should never be written against a tree that doesn't
    parse. Readers (check/lint/export/serve) use
    :func:`load_project_lenient` and surface the problems instead.
    """
    project, problems = load_project_lenient(root)
    if problems:
        raise SpecError("\n".join(p.message for p in problems))
    return project
