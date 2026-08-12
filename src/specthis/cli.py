"""specthis command-line entry point.

Verb boundaries are load-bearing: ``check``/``status`` never write,
``run`` writes only runs.toml, ``vouch`` writes only vouches.toml.
Executor dispatch (local subprocess vs a configured scripthut submit
command) lives here and only here — everything below the CLI is pure.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from . import __version__, hashing
from .certificates import write_all as write_certificates
from .check import (
    Certification,
    Realization,
    Report,
    check_project,
    code_manifest,
    coordinates,
    code_sha,
    expected_inputs,
    is_library,
    is_source,
    machine_repairable,
    queues,
    step_digest,
    ordered_keys,
    verified,
)
from .adopt import AdoptError, adopt_manifest
from .backends import FAILED, BackendError, resolve as resolve_backend
from .correspond import correspondence_problems, correspondence_warnings
from .instances import by_step as instances_by_step, template_problems
from .install import init_specs_dir, install_agents, install_commands
from .pipeline import PipelineError
from .ledger import (
    RUNS_FILE,
    LedgerError,
    Run,
    Vouch,
    read_runs,
    record_run,
    record_vouch,
)
from .parse import Problem, Project, SpecError, load_project, load_project_lenient
from .timefmt import fmt_duration as _fmt_duration


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(project_path: Path) -> Project:
    try:
        return load_project(project_path)
    except SpecError as exc:
        raise click.ClickException(str(exc)) from exc


def _load_lenient(project_path: Path) -> tuple[Project, list[Problem]]:
    try:
        return load_project_lenient(project_path)
    except SpecError as exc:
        raise click.ClickException(str(exc)) from exc


def _echo_problems(problems: list[Problem]) -> None:
    if problems:
        click.echo("spec problems (grammar — fix before trusting anything below):", err=True)
        for p in problems:
            click.echo(f"  {p.message}", err=True)


def _require_active(project: Project, entry: str) -> None:
    """Reject verbs aimed at unknown or skipped entries, with the right hint."""
    if entry in project.skipped_entries:
        raise click.ClickException(
            f"`{entry}` is skipped ({project.skipped_entries[entry]} has "
            "skip: true) — remove the flag to work on it"
        )
    if entry not in project.entries:
        raise click.ClickException(f"unknown entry `{entry}`")


def _path_option(f):
    return click.option(
        "--path",
        "project_path",
        type=click.Path(file_okay=False, exists=True, path_type=Path),
        default=Path.cwd(),
        show_default="current directory",
        help="Project root (the directory containing specs/).",
    )(f)


def _mind_hint(report: Report, project: Project) -> str:
    """Why this definition needs a mind (the vouch-axis diagnosis)."""
    if report.certification is Certification.UNIMPLEMENTED:
        scripts = project.entries[report.entry].binding.scripts
        return "no code at " + ", ".join(scripts)
    if report.certification is Certification.UNVOUCHED:
        if report.expired:
            return "moved since vouch: " + "; ".join(report.expired)
        return "spec or code moved since vouch" if report.vouch else "never vouched"
    if report.certification is Certification.REJECTED and report.vouch is not None:
        v = report.vouch
        return f"rejected by {v.attester}" + (f": {v.note}" if v.note else "")
    return ""


def _machine_hint(report: Report) -> str:
    """Why this realization needs a machine (the run-axis diagnosis)."""
    if report.realization is Realization.NEVER_RUN:
        return "never run"
    if report.realization is Realization.STALE:
        return "moved: " + ", ".join(report.moved)
    return ""


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="specthis")
def main() -> None:
    """A notary for a DAG it also knows how to build."""


# ---------------------------------------------------------------- check


@main.command("check")
@_path_option
def check_cmd(project_path: Path) -> None:
    """Report the two queues: definitions needing a mind, realizations
    needing a machine. An entry can sit in both (the mind audits while
    the machine reruns). Downstream waiting is summarized per tree.

    Exits non-zero if either queue is non-empty or the spec directory
    has grammar problems (see `specthis lint`).
    """
    project, problems = _load_lenient(project_path)
    _echo_problems(problems)
    reports = check_project(project)
    mind, machine = queues(reports)
    if mind:
        click.echo("vouch tree — definitions needing a mind:")
        for r in sorted(mind, key=lambda r: r.entry):
            click.echo(f"  {r.certification.value:<14} {r.entry:<28} {_mind_hint(r, project)}")
    if machine:
        click.echo("run tree — realizations needing a machine:")
        for r in sorted(machine, key=lambda r: r.entry):
            joint = "" if r.certification is Certification.CERTIFIED else " (unvouched)"
            real = r.realization.value if r.realization else ""
            click.echo(f"  {real:<14} {r.entry:<28} {_machine_hint(r)}{joint}")
    waiting = [
        r
        for r in reports.values()
        if r.certification is Certification.CERTIFIED
        and not machine_repairable(r)
        and not (r.computable and r.realized)
    ]
    if waiting:
        minds_up = sum(1 for r in waiting if not r.computable)
        machines_up = sum(1 for r in waiting if not r.realized)
        detail = ", ".join(
            part
            for part in (
                f"{minds_up} on minds" if minds_up else "",
                f"{machines_up} on machines" if machines_up else "",
            )
            if part
        )
        click.echo(f"waiting on upstream: {len(waiting)} ({detail})")
    remote = sorted(r.entry for r in reports.values() if not r.materialized)
    if remote:
        click.echo(
            f"bytes not local (claim stands; `specthis cache fetch` materializes): "
            f"{', '.join(remote)}"
        )
    ready = sum(1 for r in reports.values() if r.computable and r.realized)
    skipped = f" (+{len(project.skipped_entries)} skipped)" if project.skipped_entries else ""
    click.echo(f"ready: {ready}/{len(reports)}{skipped}")

    if mind or machine or problems:
        sys.exit(1)


# ----------------------------------------------------------------- lint


@main.command("lint")
@_path_option
def lint_cmd(project_path: Path) -> None:
    """Check that spec, map and pipeline describe the same graph.

    All files, all problems at once (the other verbs stop at the
    first): frontmatter, entry blocks, bindings, consumes edges — and,
    when the project has a pipeline.toml, the correspondence between
    the contract's graph and the one that will actually run.

    That last group is load-bearing. The pipeline is authored rather
    than generated, so lint is what replaces a compiler's guarantee
    that the two agree. Exits non-zero if anything is wrong. Reads only.
    """
    project, problems = _load_lenient(project_path)
    problems = (
        problems
        + [Problem('specs', m) for m in template_problems(project)]
        + correspondence_problems(project)
    )
    warnings = correspondence_warnings(project)
    for p in problems:
        click.echo(f"  {p.message}")
    for w in warnings:
        click.echo(f"  warning: {w.message}", err=True)
    if not problems:
        clean = "specs are clean"
        click.echo(clean if not warnings else f"{clean} ({len(warnings)} warning(s))")
        return
    click.echo(f"{len(problems)} problem(s)", err=True)
    sys.exit(1)


# ---------------------------------------------------------------- status


@main.command("status")
@click.argument("entry", required=False)
@_path_option
def status_cmd(entry: str | None, project_path: Path) -> None:
    """Show every entry's derived status, or one entry in detail."""
    project = _load(project_path)
    reports = check_project(project)
    if entry is None:
        for name in ordered_keys(project, reports):
            r = reports[name]
            e = project.entries[r.instance_of or name]
            kind = e.spec.kind if e.spec.kind == "library" else f"{e.spec.kind}/{e.tier}"
            marker = "" if r.materialized else "   [bytes remote]"
            click.echo(f"  {coordinates(r):<44} {name:<28} {kind}{marker}")
        return
    _require_active(project, entry)
    if entry not in reports:
        raise click.ClickException(
            f"no claim for `{entry}`"
            + (" — it is a template; name one of its instances" if entry in project.entries else "")
        )
    r = reports[entry]
    e = project.entries[r.instance_of or entry]
    click.echo(f"entry:     {entry}   ({e.spec.path.name}, {e.spec.kind}/{e.tier})")
    click.echo(f"state:     {coordinates(r)}")
    click.echo(f"spec_sha:  {r.spec_sha}")
    click.echo(f"code_sha:  {r.code_sha or '(code missing)'}")
    click.echo(f"scripts:   {', '.join(e.binding.scripts)}")
    outs = list(r.run.outputs) if r.run and r.run.outputs else list(e.outputs)
    click.echo(f"outputs:   {', '.join(outs) or '(none — library: chain stops at code)'}")
    if e.consumes:
        click.echo(f"consumes:  {', '.join(e.consumes)}")
    if r.vouch:
        v = r.vouch
        note = f" — {v.note}" if v.note else ""
        took = (
            f" (took {_fmt_duration(v.duration_seconds)})"
            if v.duration_seconds is not None
            else ""
        )
        click.echo(f"vouch:     {v.verdict} by {v.attester} at {v.vouched}{took}{note}")
        if r.expired:
            click.echo("moved since last vouch:")
            for what in r.expired:
                click.echo(f"  - {what}")
    else:
        click.echo("vouch:     (none)")
    if r.run:
        took = (
            f" (took {_fmt_duration(r.run.duration_seconds)})"
            if r.run.duration_seconds is not None
            else ""
        )
        click.echo(f"run:       {r.run.ran} via {r.run.executor}{took}")
    else:
        click.echo("run:       (none)")
    if not r.materialized:
        click.echo(
            f"bytes:     not local — claim stands; `specthis cache fetch {entry}` "
            "materializes (verified)"
        )
    if r.moved:
        click.echo("moved since last run:")
        for k in r.moved:
            click.echo(f"  - {k}")


# ---------------------------------------------------------------- adopt


@main.command("adopt")
@click.argument("entry")
@click.argument("manifest_file", type=click.Path(exists=True, path_type=Path))
@_path_option
def adopt_cmd(entry: str, manifest_file: Path, project_path: Path) -> None:
    """Countersign a manager's MANIFEST_FILE as ENTRY's derived claim.

    A manifest is an unsigned factual report from a machine; adopting it
    is the notary act. Every digest it asserts is checked against the
    bytes on disk and the whole thing is refused if any disagrees.

    That proves *transcription*, not derivation: it catches a garbled or
    mismatched manifest, and it does not make the manager trustworthy —
    establishing that the outputs came from that code on those inputs
    would mean re-running, which needs the capability specthis lacks.

    `build` does this for you; use this verb for a manager specthis did
    not launch.
    """
    project = _load(project_path)
    try:
        doc = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"{manifest_file}: {exc}") from exc
    try:
        result = adopt_manifest(project, entry, doc)
    except AdoptError as exc:
        raise click.ClickException(str(exc)) from exc
    note = " (output unchanged — downstream claims unaffected)" if result.reproduced else ""
    click.echo(f"adopted `{entry}` -> {result.run.output_sha[:12]}…{note}")


# --------------------------------------------------------------- record


@main.command("record")
@click.argument("entry")
@click.option(
    "--as", "executor", default="hand", show_default=True,
    help="Who or what put these bytes here — a person, a one-off script, a vendor.",
)
@_path_option
def record_cmd(entry: str, executor: str, project_path: Path) -> None:
    """Pin the bytes already on disk for ENTRY, without running anything.

    The way content that no pipeline produced enters the ledger: a
    downloaded dataset, an extract a collaborator sent, the output of a
    one-off nobody wants to automate. Place the file, record it, and it
    becomes an ordinary upstream — a source entry is a compute entry
    that computes nothing.

    Records a derived claim only; it never writes a vouch. Whether the
    data is what it claims to be is a *provenance* judgment, and that
    needs a mind: `specthis vouch`.
    """
    project = _load(project_path)
    _require_active(project, entry)
    e = project.entries[entry]
    if not e.outputs:
        raise click.ClickException(f"`{entry}` declares no output — nothing to pin")

    missing = [p for p in e.outputs if not (project.root / p).is_file()]
    if missing:
        raise click.ClickException(
            f"`{entry}`: no bytes at {', '.join(missing)} — place the file first"
        )
    out_sha = hashing.output_sha(project.root, e.outputs)
    assert out_sha is not None
    runs = read_runs(project.specs_dir)
    prior = runs.get(entry)
    record_run(
        project.specs_dir,
        entry,
        Run(
            signature=hashing.signature(expected_inputs(project, e, runs)),
            output=", ".join(e.outputs),
            output_sha=out_sha,
            ran=_now(),
            executor=executor,
            inputs=expected_inputs(project, e, runs),
            outputs=hashing.files_manifest(project.root, e.outputs),
        ),
    )
    moved = "" if prior is None else (
        " (bytes unchanged)" if prior.output_sha == out_sha else " (bytes moved)"
    )
    click.echo(f"recorded `{entry}` -> {out_sha[:12]}…{moved}")
    if is_source(e):
        click.echo("note: provenance is a judgment — `specthis vouch` says it is what it claims")


# -------------------------------------------------------------- certify


@main.command("certify")
@_path_option
def certify_cmd(project_path: Path) -> None:
    """Write a code-identity certificate per entry (spec §6).

    Most projects need none: a step lists its code among its deps, so
    those digests already reach the manager and the manifest. Certificates
    earn their place when `[package] globs` are used — a glob has no
    stable file list, so its composed digest can only enter a key as a
    file.

    Deterministic: unchanged code regenerates byte-identical bytes, so
    running this never stales anything.
    """
    project = _load(project_path)
    written = write_certificates(project)
    click.echo(f"{len(written)} certificate(s) in {project.specs_dir / 'certificates'}")


# ---------------------------------------------------------------- build


@main.command("build")
@click.argument("entries", nargs=-1)
@click.option(
    "--force",
    is_flag=True,
    help="Bypass the manager's cache for the named entries — the integrity "
    "repair path, for an artefact edited on disk.",
)
@click.option(
    "--pipeline",
    "pipeline_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Pipeline file (default: pipeline.toml at the project root).",
)
@_path_option
def build_cmd(
    entries: tuple[str, ...], force: bool, pipeline_path: Path | None, project_path: Path
) -> None:
    """Hand the pipeline to a compute manager and adopt what comes back.

    specthis never selects steps: the whole pipeline goes over, and the
    manager decides what actually executes (it alone can know whether a
    rerun reproduces identical bytes). Naming ENTRIES scopes a repair;
    --force bypasses the manager's cache for them.

    Every manifest is verified against the bytes on disk before it is
    recorded. That proves transcription, never derivation.
    """
    project = _load(project_path)
    try:
        backend = resolve_backend(project, pipeline_path)
        steps = backend.parse()
    except (BackendError, PipelineError) as exc:
        raise click.ClickException(str(exc)) from exc

    unknown = sorted(set(entries) - set(steps))
    if unknown:
        raise click.ClickException(f"no pipeline step for: {', '.join(unknown)}")
    if force and not entries:
        raise click.ClickException("--force needs the entries to force; it is a repair, not a mode")

    handle = backend.submit(list(entries) or None, force=force)
    state = backend.poll(handle)
    produced = backend.manifests(handle)

    # Steps carry pipeline ids; claims are keyed by entry — or by
    # instance, for a template. The mapping comes from output patterns,
    # never from how a backend chose to name its steps.
    instance_of_step = {sid: inst.name for sid, (_e, inst) in instances_by_step(project).items()}

    adopted, refused = [], []
    for sid, manifest in sorted(produced.items()):
        key = instance_of_step.get(sid, sid)
        if key not in project.entries and key not in instance_of_step.values():
            continue  # a step with no entry: lint's business, not adoption's
        try:
            adopted.append(adopt_manifest(project, key, manifest))
        except AdoptError as exc:
            refused.append(str(exc))

    for a in adopted:
        note = " (output unchanged — downstream claims unaffected)" if a.reproduced else ""
        click.echo(f"  adopted {a.entry} -> {a.run.output_sha[:12]}…{note}")
    click.echo(f"{len(adopted)} claim(s) recorded from {backend.name}")
    for why in refused:
        click.echo(f"  refused: {why}", err=True)
    if refused or state == FAILED:
        raise click.ClickException(
            "some steps failed or their manifests were refused; nothing recorded for those"
        )


# ---------------------------------------------------------------- vouch


@main.command("vouch")
@click.argument("entry")
@click.option(
    "--as",
    "attester",
    required=True,
    help="Who is attesting. No git-config default on purpose — friction is the feature.",
)
@click.option(
    "--reject",
    is_flag=True,
    help="Record that the code does NOT satisfy the contract at these digests.",
)
@click.option("--note", default="", help="Free-text note recorded with the verdict.")
@click.option(
    "--took",
    "took_seconds",
    type=float,
    default=None,
    help="Wall-clock seconds the judgment took — claim metadata, moves no digest.",
)
@_path_option
def vouch_cmd(
    entry: str,
    attester: str,
    reject: bool,
    note: str,
    took_seconds: float | None,
    project_path: Path,
) -> None:
    """Attest that the entry's code satisfies its contract at the current
    digests. Only someone who did NOT author the change may vouch.

    Writes vouches.toml only; never touches runs.toml.
    """
    project = _load(project_path)
    _require_active(project, entry)
    e = project.entries[entry]
    c = code_sha(project, e)
    if c is None:
        raise click.ClickException(
            f"`{entry}` has no code on disk ({', '.join(e.binding.scripts)}) — nothing to judge"
        )
    vouch = Vouch(
        spec_sha=e.spec.spec_sha,
        code_sha=c,
        verdict="rejected" if reject else "ok",
        attester=attester,
        vouched=_now(),
        note=note,
        # Decomposed digests: when this vouch later expires, check/status
        # can say WHAT moved instead of only that something did.
        spec_block_sha=e.block_sha,
        # The wiring is part of what was judged: realizing a spec means
        # writing code *and* feeding it the right inputs (spec §1).
        step_sha=step_digest(project, e) or "",
        code_manifest=code_manifest(project, e),
        duration_seconds=took_seconds,
    )
    try:
        record_vouch(project.specs_dir, entry, vouch)
    except LedgerError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"recorded {vouch.verdict} for `{entry}` by {attester}")
    # Informational, never a gate: a vouch is a local claim, so it is
    # recorded regardless of upstream state — just say why the entry
    # won't read `ready` yet.
    if vouch.verdict == "ok" and e.consumes:
        reports = check_project(project)
        pending = sorted(up for up in e.consumes if not verified(reports[up]))
        if pending:
            click.echo(
                f"note: upstream not yet verified ({', '.join(pending)}) — "
                f"`{entry}` cannot show ready until its upstream chain is"
            )


# ------------------------------------------------------ export / serve


@main.command("export")
@_path_option
def export_cmd(project_path: Path) -> None:
    """Render the dashboard: specs/specs.html + specs/_index.json.

    Both are regenerated views — `check` never reads them, and nothing
    in them is hand-edited.
    """
    from .export import write_artefacts

    try:
        written = write_artefacts(project_path)
    except SpecError as exc:
        raise click.ClickException(str(exc)) from exc
    for path in written:
        click.echo(f"  wrote  {path}")


@main.command("dag")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["svg", "json"]),
    default="svg",
    show_default=True,
    help="svg: self-contained document; json: nodes (statuses, layer/row, "
    "geometry) + edges + canvas size, for rendering it your own way.",
)
@click.option(
    "--view",
    type=click.Choice(["layered", "rails"]),
    default="layered",
    show_default=True,
    help="layered: node-link figure showing the pipeline's shape; "
    "rails: git-log-style list in story order (the dashboard's view).",
)
@click.option(
    "--orient",
    type=click.Choice(["tb", "lr"]),
    default="tb",
    show_default=True,
    help="Layered view only. tb: flow runs downward (rows pack nodes at "
    "natural width); lr: left-to-right (columns as wide as their widest label).",
)
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write to a file instead of stdout.",
)
@_path_option
def dag_cmd(fmt: str, view: str, orient: str, out: Path | None, project_path: Path) -> None:
    """Print the spec-level DAG: standalone SVG, or layout JSON.

    Two views of the same graph the dashboard shows: `layered` (the
    default) is a node-link figure of the pipeline's shape; `rails` is
    the dashboard's git-log-style list, story-ordered with trust
    flowing down status-colored rails. The SVG is self-contained
    (styles inlined), so it renders anywhere: a repo README, an issue,
    slides. The JSON carries the graph plus both computed placements,
    so you can tune a rendering of your own without re-deriving
    either. A regenerated view like the dashboard; nothing ever reads
    it back.
    """
    from .dag import dag_json, dag_standalone_svg
    from .parse import load_project_lenient

    try:
        project, _ = load_project_lenient(project_path)
    except SpecError as exc:
        raise click.ClickException(str(exc)) from exc
    reports = check_project(project)
    if fmt == "json":
        data = dag_json(project, reports, orient)
        text = json.dumps(data, indent=2) + "\n" if data is not None else ""
    else:
        text = dag_standalone_svg(project, reports, orient, view)
    if not text:
        raise click.ClickException("no consumes edges between specs — nothing to draw")
    if out:
        out.write_text(text, encoding="utf-8")
        click.echo(f"  wrote  {out}")
    else:
        click.echo(text, nl=False)


@main.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=int, default=8765, show_default=True)
@_path_option
def serve_cmd(host: str, port: int, project_path: Path) -> None:
    """Serve the dashboard with live reload (writes nothing).

    Re-renders whenever specs, ledgers, bindings, scripts, or outputs
    change; the page reloads itself.
    """
    from .serve import serve

    _load(project_path)  # fail fast with a clear message if specs/ is absent/broken
    serve(host, port, project_path)


# -------------------------------------------------------------- migrate


@main.command("migrate")
@click.option(
    "--lock",
    "lock_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Old _lock.json to import (default: specs/_lock.json).",
)
@click.option(
    "--write", "do_write", is_flag=True, help="Actually write runs.toml (default: dry-run)."
)
@click.option("--force", is_flag=True, help="Overwrite runs.toml rows that already exist.")
@_path_option
def migrate_cmd(
    lock_path: Path | None, do_write: bool, force: bool, project_path: Path
) -> None:
    """One-time import of an old _lock.json into runs.toml.

    Emits derived claims only — NEVER vouches: judgment does not
    migrate. Rows import with their certified inputs as-is; package and
    upstream digests fill in on the first real `run` (until then the
    entry reads stale, which is honest).
    """
    project = _load(project_path)
    lock_path = lock_path or project.specs_dir / "_lock.json"
    if not lock_path.is_file():
        raise click.ClickException(f"no lock file at {lock_path}")
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    rows = data.get("entries", data)
    existing = read_runs(project.specs_dir)

    imported, skipped = [], []
    for name, row in rows.items():
        if not isinstance(row, dict):
            continue
        if name not in project.entries:
            skipped.append((name, "no spec entry with this name"))
            continue
        if is_library(project.entries[name]):
            skipped.append((name, "library entry — nothing derived to import"))
            continue
        if name in existing and not force:
            skipped.append((name, "runs.toml row exists (use --force)"))
            continue
        inputs = {k: str(v) for k, v in (row.get("inputs_certified") or {}).items()}
        e = project.entries[name]
        out_sha = (
            row.get("output_sha")
            or row.get("content_hash")
            or hashing.output_sha(project.root, e.outputs)
            or hashing.MISSING
        )
        imported.append(
            (
                name,
                Run(
                    signature=hashing.signature(inputs),
                    output=", ".join(e.outputs),
                    output_sha=out_sha,
                    ran=str(row.get("ts") or _now()),
                    executor="migrated",
                    inputs=inputs,
                ),
            )
        )

    verb = "importing" if do_write else "would import"
    click.echo(f"{verb} {len(imported)} run row(s) from {lock_path.name}:")
    for name, run in imported:
        click.echo(f"  {name}  ({len(run.inputs)} certified inputs)")
    for name, why in skipped:
        click.echo(f"  skipped {name}: {why}", err=True)
    click.echo("vouches imported: 0 (by design — judgment does not migrate)")
    if do_write:
        for name, run in imported:
            record_run(project.specs_dir, name, run)
        click.echo(f"wrote {project.specs_dir / RUNS_FILE}")
    elif imported:
        click.echo("dry run — re-run with --write to record")


# ------------------------------------------------- scaffolding (kept)


@main.command("install")
@click.option(
    "--path",
    "project_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path.cwd(),
    show_default="current directory",
    help="Project root in which to install .claude/agents/.",
)
@click.option("--force", is_flag=True, help="Overwrite existing agent/command files.")
@click.option(
    "--agent",
    "selected",
    multiple=True,
    type=click.Choice(
        ["spec-auditor", "spec-implementer", "experiment-runner", "spec-critic"]
    ),
    help="Install only the named agent(s), and no slash commands. Repeatable. Default: everything.",
)
def install_cmd(project_path: Path, force: bool, selected: tuple[str, ...]) -> None:
    """Copy the specthis subagents into <project>/.claude/agents/ and the
    slash commands (e.g. /specthis-vouch) into <project>/.claude/commands/."""
    installed, skipped = install_agents(
        project_path=project_path,
        force=force,
        agents=list(selected) if selected else None,
    )
    if not selected:
        cmd_installed, cmd_skipped = install_commands(project_path=project_path, force=force)
        installed += [f"/{name} (command)" for name in cmd_installed]
        skipped += cmd_skipped
    for name in installed:
        click.echo(f"  installed  {name}")
    for name, reason in skipped:
        click.echo(f"  skipped    {name}  ({reason})", err=True)
    if not installed and skipped:
        click.echo("\nNothing changed. Re-run with --force to overwrite.", err=True)
        sys.exit(1)


@main.command("init")
@click.option(
    "--path",
    "project_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path.cwd(),
    show_default="current directory",
    help="Project root in which to create specs/.",
)
@click.option("--force", is_flag=True, help="Overwrite existing template files in specs/.")
def init_cmd(project_path: Path, force: bool) -> None:
    """Create specs/ with README.md and AGENTS.md spec-format templates."""
    created, skipped = init_specs_dir(project_path=project_path, force=force)
    for path in created:
        click.echo(f"  created    {path}")
    for path, reason in skipped:
        click.echo(f"  skipped    {path}  ({reason})", err=True)


if __name__ == "__main__":
    main()
