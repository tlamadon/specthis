"""Template instances: one entry, one code binding, N instances (§15).

A parameter grid stays flat in the artifacts a human writes. The
expansion itself is the *pipeline's* job — DVC's ``foreach``, scripthut's
dynamic task generation, or simply several steps in ``pipeline.toml`` —
and specthis reads the steps that result. It performs no elaboration of
its own, so the instance set stays a function of committed files.

**Identity comes from the output path, never the step id** (§15.3). A
step declaring ``data/chile/wages.parquet`` matches the pattern
``data/{dataset}/wages.parquet`` and binds ``dataset = chile``. That is
why every prop must appear in every output pattern: it makes the match
total, and it means DVC's ``clean-wages@chile`` and any other backend's
naming both work with no configuration.

Pure: reads the project, returns instances, changes nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parse import Entry, Project

PLACEHOLDER = re.compile(r"\{([a-zA-Z][\w-]*)\}")


@dataclass(frozen=True)
class Instance:
    """One concrete realization of a template entry."""

    entry: str  # the template's name
    props: tuple[tuple[str, str], ...]  # bound values, sorted by prop
    step: str  # the pipeline step that produces it
    outputs: tuple[str, ...]  # its resolved output paths

    @property
    def name(self) -> str:
        """``clean-wages[dataset=chile]`` — the ledger and report key."""
        return f"{self.entry}[{','.join(f'{k}={v}' for k, v in self.props)}]"

    @property
    def binding(self) -> dict[str, str]:
        return dict(self.props)


def props_of(entry: Entry) -> list[str]:
    """Free variables declared by this entry, in declaration order.

    Per-entry ``- props:`` when the entry uses the target format's field
    list, else the file's frontmatter.
    """
    return list(entry.props or ())


def is_template(entry: Entry) -> bool:
    return bool(props_of(entry))


def placeholders(pattern: str) -> set[str]:
    return set(PLACEHOLDER.findall(pattern))


def _matcher(pattern: str) -> re.Pattern[str]:
    """A regex binding each ``{prop}`` to one path segment.

    Values never span ``/``: a prop is a short scalar distinguishing
    instances that must coexist, not a path fragment.
    """
    out, last = [], 0
    for m in PLACEHOLDER.finditer(pattern):
        out.append(re.escape(pattern[last : m.start()]))
        out.append(f"(?P<{m.group(1)}>[^/]+)")
        last = m.end()
    out.append(re.escape(pattern[last:]))
    return re.compile("^" + "".join(out) + "$")


def bind(pattern: str, path: str) -> dict[str, str] | None:
    """Bind a pattern's props against a concrete path, or ``None``."""
    m = _matcher(pattern).match(path)
    return m.groupdict() if m else None


def resolve(pattern: str, props: dict[str, str]) -> str:
    return PLACEHOLDER.sub(lambda m: props.get(m.group(1), m.group(0)), pattern)


def instances(project: Project, entry: Entry) -> list[Instance]:
    """Every instance of a template entry the pipeline declares.

    A step qualifies when its outputs bind *every* output pattern
    consistently — one set of prop values explaining the whole step, so
    a step producing half an instance is not silently accepted.
    """
    patterns = list(entry.outputs)
    if not (is_template(entry) and patterns and project.steps):
        return []

    found: list[Instance] = []
    for sid, step in sorted(project.steps.items()):
        bound: dict[str, str] = {}
        resolved: list[str] = []
        for pattern in patterns:
            hit = next(
                (b for out in step.outs if (b := bind(pattern, out)) is not None), None
            )
            if hit is None or any(bound.get(k, v) != v for k, v in hit.items()):
                bound = {}
                break
            bound.update(hit)
            resolved.append(resolve(pattern, hit))
        if not bound:
            continue
        found.append(
            Instance(
                entry=entry.name,
                props=tuple(sorted(bound.items())),
                step=sid,
                outputs=tuple(resolved),
            )
        )
    return found


def template_problems(project: Project) -> list[str]:
    """§15.6, the invariants that keep instances distinguishable."""
    out: list[str] = []
    for name, entry in sorted(project.entries.items()):
        declared = props_of(entry)
        if not declared:
            for pattern in entry.outputs:
                if placeholders(pattern):
                    out.append(
                        f"`{name}` uses a placeholder in `{pattern}` but declares no props"
                    )
            continue
        if not entry.outputs:
            out.append(f"`{name}` declares props but produces nothing to distinguish them")
        for pattern in entry.outputs:
            missing = sorted(set(declared) - placeholders(pattern))
            if missing:
                out.append(
                    f"`{name}`: prop(s) {', '.join(missing)} absent from output pattern "
                    f"`{pattern}` — instances could collide"
                )
            unknown = sorted(placeholders(pattern) - set(declared))
            if unknown:
                out.append(
                    f"`{name}`: `{pattern}` uses undeclared prop(s) {', '.join(unknown)}"
                )
        for script in entry.binding.scripts:
            if placeholders(script):
                out.append(
                    f"`{name}`: code binding `{script}` is parameterized — every instance "
                    "runs the same code, which is what lets one vouch cover the template"
                )
    return out


def by_step(project: Project) -> dict[str, tuple[Entry, "Instance"]]:
    """Pipeline step id -> the template entry and instance it realizes.

    The seam runs on step ids, but claims are keyed by instance name, so
    adoption needs this one lookup — and it is derived from the output
    patterns, never from how a backend chose to name its steps.
    """
    out: dict[str, tuple[Entry, Instance]] = {}
    for entry in project.entries.values():
        if is_template(entry):
            for inst in instances(project, entry):
                out[inst.step] = (entry, inst)
    return out


def resolve_key(project: Project, key: str) -> tuple[Entry, "Instance | None"]:
    """A ledger key -> the entry it claims about, and its instance if any.

    ``clean-wages`` is an entry; ``clean-wages[dataset=chile]`` is one
    instance of it. Raises ``KeyError`` for anything else.
    """
    if key in project.entries:
        return project.entries[key], None
    head, sep, _ = key.partition("[")
    if sep and head in project.entries:
        entry = project.entries[head]
        for inst in instances(project, entry):
            if inst.name == key:
                return entry, inst
    raise KeyError(key)
