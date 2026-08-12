"""Parse ``specs/*.md`` (frontmatter + entry blocks) and ``specs/bindings.toml``.

The grammar (documented for users in the bundled ``specs/README.md``
template):

- Every ``.md`` file starts with YAML frontmatter declaring ``name``,
  ``kind``, and the two edge lists: ``consumes:`` (entry names —
  artefact flow, enters signatures) and ``references:`` (spec files —
  vocabulary, ledger-invisible). Compute specs add
  ``tier: intensive | quick``. Optional ``title:`` (display title),
  ``group:`` (string) and ``priority:`` (int, default 0, higher first)
  name and organize specs in the dashboard; they are display-only and
  excluded from ``spec_sha``, so retitling/retagging never invalidates
  vouches.
- Executable kinds (``compute``, ``report``) carry a
  ``## Entry`` (single) or ``## Entries`` (multi) section whose
  ``### <entry-name>`` blocks each declare ``Output:`` (compute, one
  path) or ``Export outputs:`` (report, one or more paths).

``bindings.toml`` is hand-edited vocabulary, not a claim: it maps each
entry to the scripts that implement it, the command that runs it, and
(optionally) scripthut workflow files and an executor label. A
``[package]`` table declares the shared-library globs whose blob
digest enters every code manifest. A ``[preview]`` table maps output
suffixes to the shell commands the dashboard uses to render previews
(:mod:`specthis.preview`) — same species as executors: a configured
ingredient for a view, never an authority over any claim.
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
from .pipeline import PipelineError, Step, load_pipeline
from .preview import CONTENT_TYPES

KINDS = {"meta", "definitions", "templates", "library", "compute", "report"}
ENTRY_KINDS = {"library", "compute", "report"}
TIERS = {"intensive", "quick"}

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_ENTRY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_BACKTICKED = re.compile(r"`([^`]+)`")
#: Display-only frontmatter lines carved out of ``spec_sha`` — they
#: name and organize things in the dashboard, never the contract, so
#: editing them must not invalidate vouches.
_DISPLAY_LINE = re.compile(r"^(?:group|priority|title):[^\n]*(?:\n|$)", re.MULTILINE)


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
    #: ``produces = { wages-panel = "data/wages.parquet" }`` — which file
    #: **is** a logical name (spec §4). The one translation between the
    #: spec's vocabulary and the pipeline's; empty when an entry declares
    #: physical paths directly.
    produces: dict[str, str] = field(default_factory=dict)


@dataclass
class PreviewRecipe:
    """How the dashboard renders one output suffix; vocabulary, not a claim.

    The command runs at the project root and must place its artifact at
    ``{out}``; ``{input}`` is also substituted.
    ``inputs`` are glob patterns whose digests fold into the preview
    cache key — declare the preamble and the recipe script itself so
    editing either invalidates exactly the affected previews.
    """

    command: str
    format: str = "pdf"  # what lands at {out}; decides the content type served
    inputs: list[str] = field(default_factory=list)


@dataclass
class Entry:
    name: str
    spec: "SpecFile"
    outputs: list[str]
    binding: Binding
    #: sha256 of this entry's ``###`` block text — **what a vouch pins**
    #: (``check.spec_moved``). The claim unit is the entry, not the
    #: file: editing a sibling entry is somebody else's business.
    block_sha: str = ""
    #: Per-entry edges and props, from the target format's field list
    #: (§3). ``None`` means this entry uses the legacy file-level
    #: frontmatter, and the properties below fall back to it.
    own_consumes: list[str] | None = None
    own_props: list[str] | None = None
    #: The logical names this entry declares, when the map translated
    #: them into ``outputs``. Empty when the spec named paths directly.
    logical: list[str] = field(default_factory=list)

    @property
    def consumes(self) -> list[str]:
        return self.spec.consumes if self.own_consumes is None else self.own_consumes

    @property
    def props(self) -> list[str]:
        return self.spec.props if self.own_props is None else self.own_props

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
    title: str = ""  # frontmatter `title:` (display-only, outside spec_sha), else first heading, else name
    skip: bool = False  # commented out: entries dormant, body not grammar-checked
    group: str | None = None  # sidebar group label; display-only, outside spec_sha
    priority: int = 0  # sidebar rank, higher first; display-only, outside spec_sha
    #: `props:` — free variables making this file's entries templates
    #: (spec §15). Semantic, so inside spec_sha: adding a prop changes
    #: what the contract promises.
    props: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)


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
    #: entry name -> spec filename, for entries dormant under `skip: true`.
    skipped_entries: dict[str, str] = field(default_factory=dict)
    #: output suffix (".tex") -> preview recipe, from [preview] in bindings.
    previews: dict[str, PreviewRecipe] = field(default_factory=dict)
    #: ``[backend] class`` — a dotted path to the project's own adapter
    #: (``mypkg.adapters:ScripthutBackend``). None means the bundled
    #: runner. Config, not a claim: it enters no digest.
    backend_class: str | None = None
    #: step id -> Step, from ``pipeline.toml`` when the project has one.
    #: Empty otherwise, and then no claim carries a ``step:`` row — a
    #: project without a pipeline behaves exactly as before it existed.
    steps: dict[str, "Step"] = field(default_factory=dict)


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


#: A `- key: value` line in an entry block — the target format's field
#: list (spec §3 rule 2). Values may be backticked; a bare `- code`
#: takes no value.
_ENTRY_FIELD = re.compile(r"^- +([a-z_]+)\s*(?::\s*(.*?))?\s*$", re.MULTILINE)
ENTRY_FIELDS = {"consumes", "produces", "code", "props"}


def entry_fields(block: str, where: str) -> dict[str, list[str]]:
    """Parse an entry block's field list, or ``{}`` if it has none.

    Absent means the entry uses the legacy ``Output:``/``Export
    outputs:`` form; both are accepted so a project migrates at its own
    pace. Unknown keys are errors either way — a typo must not silently
    demote an entry to narrative.
    """
    fields: dict[str, list[str]] = {}
    for m in _ENTRY_FIELD.finditer(block):
        key, raw = m.group(1), (m.group(2) or "").strip()
        if key not in ENTRY_FIELDS:
            raise SpecError(
                f"{where}: unknown entry field `{key}` — expected one of "
                f"{', '.join(sorted(ENTRY_FIELDS))}"
            )
        values = [v.strip().strip("`") for v in raw.split(",") if v.strip()]
        fields.setdefault(key, []).extend(values)
    return fields


def infer_kind(fields: dict[str, list[str]], outputs: list[str]) -> str:
    """Type from fields (§2), for entries written in the target format.

    A bare ``code`` marks a library; a physical path in ``produces``
    marks a source; anything producing logical names is computable.
    """
    if "code" in fields and not fields.get("produces"):
        return "library"
    if any("/" in p or "." in p for p in fields.get("produces", ())):
        return "source"
    return "compute"


def _infer_file_kind(body: str) -> str:
    """A file's kind from what its entries declare (§2).

    Only needed while `kind:` is optional-but-supported: the target
    format has no file-level kind at all, since type is a per-entry
    consequence of fields. A file with no entry blocks is `definitions`
    — prose nobody signs.
    """
    kinds = set()
    for block in re.finditer(
        r"^### +(.+?)\s*$\n(.*?)(?=^### |^## |\Z)", body, re.MULTILINE | re.DOTALL
    ):
        fields = entry_fields(block.group(2), "spec")
        if not fields:
            continue
        kinds.add(infer_kind(fields, []))
    if not kinds:
        return "definitions"
    if kinds == {"library"}:
        return "library"
    # `source` is a target-format type (§2) with no equivalent in the
    # legacy vocabulary yet: an entry that produces bytes from outside
    # any pipeline still reads as compute here, and its lack of code
    # derives `unimplemented` exactly as a source entry should.
    kinds.discard("library")
    return "report" if len(kinds) > 1 else "compute"


def _spec_sha(text: str, m: "re.Match[str]") -> str:
    """``spec_sha`` with display-only frontmatter lines removed.

    A file that never uses ``title:``/``group:``/``priority:`` hashes
    exactly as the raw text, so its vouches survive this carve-out.
    """
    fm = m.group(1)
    stripped = _DISPLAY_LINE.sub("", fm)
    if stripped == fm:
        return sha256_text(text)
    return sha256_text(text[: m.start(1)] + stripped + text[m.end(1) :])


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
    if kind is None:
        # Target format (§2): type is inferred from the fields entries
        # declare, so `kind:` is optional. Files whose entries carry no
        # field list default to prose-only.
        kind = _infer_file_kind(text[m.end() :])
    if kind not in KINDS:
        raise SpecError(f"{path.name}: `kind: {kind}` is not one of {sorted(KINDS)}")
    name = meta.get("name")
    if name is not None and name != path.stem:
        raise SpecError(f"{path.name}: `name: {name}` must match the filename stem")
    name = path.stem

    props = meta.get("props") or []
    if isinstance(props, str):
        props = [props]
    if not isinstance(props, list) or not all(isinstance(x, str) for x in props):
        raise SpecError(f"{path.name}: `props:` must be a name or a list of names")

    tier = meta.get("tier", "intensive" if kind == "compute" else "quick")
    if tier not in TIERS:
        raise SpecError(f"{path.name}: `tier: {tier}` is not one of {sorted(TIERS)}")

    skip = meta.get("skip", False)
    if not isinstance(skip, bool):
        raise SpecError(f"{path.name}: `skip: {skip}` must be true or false")

    group = meta.get("group")
    if group is not None and (not isinstance(group, str) or not group.strip()):
        raise SpecError(f"{path.name}: `group: {group}` must be a non-empty string")
    priority = meta.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise SpecError(f"{path.name}: `priority: {priority}` must be an integer")

    body = text[m.end() :]
    heading = re.search(r"^# +(.+?)\s*$", body, re.MULTILINE)
    spec = SpecFile(
        path=path,
        name=name,
        kind=kind,
        tier=tier,
        consumes=_str_list(meta.get("consumes"), path.name, "consumes"),
        references=_str_list(meta.get("references"), path.name, "references"),
        spec_sha=_spec_sha(text, m),
        props=props,
        body=body,
        title=str(meta.get("title") or (heading.group(1) if heading else name)),
        skip=skip,
        group=group.strip() if group else None,
        priority=priority,
    )

    if kind in ENTRY_KINDS:
        label = "Output" if kind == "compute" else "Export outputs"
        for block_match in re.finditer(
            r"^### +(.+?)\s*$\n(.*?)(?=^### |^## |\Z)", body, re.MULTILINE | re.DOTALL
        ):
            entry_name = block_match.group(1).strip()
            if not _ENTRY_NAME.match(entry_name):
                raise SpecError(f"{path.name}: bad entry name `{entry_name}`")
            fields = entry_fields(block_match.group(2), f"{path.name}: `{entry_name}`")
            if spec.skip:
                # Commented out: keep the entry names (for views and for
                # "consumes skipped entry" diagnostics) but grammar-check
                # nothing — a half-written body is the point of skipping.
                outputs = _field_paths(block_match.group(2), label) if kind != "library" else []
            elif kind == "library":
                # A library entry is judged code with no artifact: the
                # chain stops at code, so an Output: is a contradiction.
                if _field_paths(block_match.group(2), "Output") or _field_paths(
                    block_match.group(2), "Export outputs"
                ):
                    raise SpecError(
                        f"{path.name}: library entry `{entry_name}` must not declare an output"
                    )
                outputs = []
            elif fields.get("produces"):
                # Target format (§3): the field list carries the products,
                # so the legacy `Output:` line is neither needed nor read.
                outputs = fields["produces"]
            else:
                outputs = _field_paths(block_match.group(2), label)
                if not outputs:
                    raise SpecError(
                        f"{path.name}: entry `{entry_name}` declares no `{label}:` path "
                        "(or a `- produces:` field)"
                    )
                if kind == "compute" and len(outputs) > 1:
                    raise SpecError(
                        f"{path.name}: compute entry `{entry_name}` must declare exactly one output"
                    )
            spec.entries.append(
                Entry(
                    name=entry_name,
                    spec=spec,
                    outputs=outputs,
                    binding=None,  # type: ignore[arg-type]
                    block_sha=sha256_text(block_match.group(0)),
                    own_consumes=fields.get("consumes"),
                    own_props=fields.get("props"),
                )
            )
    return spec


def _parse_previews(data: dict) -> dict[str, PreviewRecipe]:
    """The ``[preview]`` table: suffix -> recipe, string or table form."""
    previews: dict[str, PreviewRecipe] = {}
    for suffix, raw in data.get("preview", {}).items():
        where = f'bindings.toml: [preview] "{suffix}"'
        if not suffix.startswith("."):
            raise SpecError(f"{where}: keys are output suffixes and must start with a dot")
        if isinstance(raw, str):
            raw = {"command": raw}
        if not isinstance(raw, dict) or not isinstance(raw.get("command"), str):
            raise SpecError(f"{where}: must be a command string or a table with `command`")
        if unknown := set(raw) - {"command", "format", "inputs"}:
            raise SpecError(f"{where}: unknown key(s) {sorted(unknown)}")
        if "{out}" not in raw["command"]:
            raise SpecError(f"{where}: the command must place its artifact at {{out}}")
        fmt = raw.get("format", "pdf")
        if fmt not in CONTENT_TYPES:
            raise SpecError(f"{where}: `format = \"{fmt}\"` is not one of {sorted(CONTENT_TYPES)}")
        previews[suffix.lower()] = PreviewRecipe(
            command=raw["command"],
            format=fmt,
            inputs=_str_list(raw.get("inputs"), where, "inputs"),
        )
    return previews


def _load_bindings(
    specs_dir: Path,
) -> tuple[dict[str, Binding], list[str], str | None, dict[str, PreviewRecipe], str | None]:
    path = specs_dir / "bindings.toml"
    if not path.is_file():
        return {}, [], None, {}, None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f"bindings.toml: {exc}") from exc
    globs = _str_list(data.get("package", {}).get("globs"), "bindings.toml", "package.globs")
    backend_class = data.get("backend", {}).get("class")
    cache_url = data.get("cache", {}).get("url")
    bindings: dict[str, Binding] = {}
    for entry_name, table in data.get("entries", {}).items():
        bindings[entry_name] = Binding(
            scripts=_str_list(table.get("scripts"), "bindings.toml", "scripts"),
            run=table.get("run"),
            workflows=_str_list(table.get("workflows"), "bindings.toml", "workflows"),
            executor=table.get("executor"),
            produces=_produces_map(entry_name, table.get("produces")),
        )
    return bindings, globs, cache_url, _parse_previews(data), backend_class


def _produces_map(entry_name: str, raw: object) -> dict[str, str]:
    """``[entries.X] produces`` — logical name -> physical path."""
    if raw is None:
        return {}
    where = f"bindings.toml: [entries.{entry_name}] produces"
    if not isinstance(raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
    ):
        raise SpecError(f"{where}: must be a table of logical-name = \"path\"")
    return dict(raw)


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
        bindings, package_globs, cache_url, previews, backend_class = _load_bindings(specs_dir)
    except SpecError as exc:
        problems.append(Problem("bindings.toml", str(exc)))
        bindings, package_globs, cache_url, previews, backend_class = {}, [], None, {}, None

    steps: dict[str, Step] = {}
    pipeline_file = root / "pipeline.toml"
    if pipeline_file.is_file():
        try:
            steps = load_pipeline(pipeline_file)
        except PipelineError as exc:
            problems.append(Problem("pipeline.toml", str(exc)))

    entries: dict[str, Entry] = {}
    skipped_entries: dict[str, str] = {}
    for spec in specs:
        if spec.skip:
            # Dormant: entries stay out of the DAG, bindings are
            # best-effort for the views, and nothing is validated —
            # skipping is how you silence a spec mid-development.
            for entry in spec.entries:
                entry.binding = bindings.get(entry.name) or (
                    # no convention fallback for library modules: an
                    # invented path must not be carved out of the blob
                    Binding(scripts=[], run=None)
                    if spec.kind == "library"
                    else _default_binding(entry.name)
                )
                skipped_entries.setdefault(entry.name, spec.path.name)
            continue
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
            # Logical names become paths here, and only here: the spec
            # speaks in names, the pipeline in files, and the map is the
            # one translation between them (§4).
            if entry.binding.produces:
                missing = [p for p in entry.outputs if p not in entry.binding.produces]
                if missing and not any(
                    "/" in p or "." in p for p in entry.outputs
                ):
                    problems.append(
                        Problem(
                            spec.path.name,
                            f"{spec.path.name}: `{entry.name}` produces "
                            f"{', '.join(missing)}, which specs/bindings.toml gives no path for",
                        )
                    )
                entry.logical = list(entry.outputs)
                entry.outputs = [
                    entry.binding.produces.get(p, p) for p in entry.outputs
                ]
            entries[entry.name] = entry

    # A `consumes` target may name a logical product rather than the
    # entry producing it (§3): naming the product is more precise when
    # one entry produces several. Resolve those to their producer before
    # validating, so both forms reach the same graph.
    producer_of = {
        name: e.name for e in entries.values() for name in e.logical
    }
    if producer_of:
        for e in entries.values():
            if e.own_consumes is not None:
                e.own_consumes[:] = [producer_of.get(u, u) for u in e.own_consumes]
        for spec in specs:
            spec.consumes[:] = [producer_of.get(u, u) for u in spec.consumes]

    spec_names = {s.name for s in specs}
    for spec in specs:
        if spec.skip:
            continue  # dormant edges are nobody's problem
        for up in list(spec.consumes):
            if up in entries:
                continue
            if up in skipped_entries:
                problems.append(
                    Problem(
                        spec.path.name,
                        f"{spec.path.name}: consumes skipped entry `{up}` "
                        f"({skipped_entries[up]} has skip: true) — skip this spec "
                        "too, or unwire the edge",
                    )
                )
            else:
                problems.append(
                    Problem(spec.path.name, f"{spec.path.name}: consumes unknown entry `{up}`")
                )
            spec.consumes.remove(up)
        # Per-entry `- consumes:` edges get the same validation as the
        # file-level ones: an unknown upstream is dropped and reported,
        # never left to crash a lookup downstream.
        for entry in spec.entries:
            if entry.own_consumes is None:
                continue
            for up in list(entry.own_consumes):
                if up in entries:
                    continue
                where = f"{spec.path.name}: `{entry.name}`"
                problems.append(
                    Problem(
                        spec.path.name,
                        f"{where} consumes skipped entry `{up}`"
                        if up in skipped_entries
                        else f"{where} consumes unknown entry `{up}`",
                    )
                )
                entry.own_consumes.remove(up)
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
        # Skipped library modules stay carved out of the blob: their
        # claims are dormant, not deleted, and re-enabling the spec
        # must not shift every other entry's code manifest.
        library_scripts=frozenset(
            s
            for spec in specs
            if spec.kind == "library"
            for e in spec.entries
            for s in e.binding.scripts
        ),
        skipped_entries=skipped_entries,
        previews=previews,
        steps=steps,
        backend_class=backend_class,
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
