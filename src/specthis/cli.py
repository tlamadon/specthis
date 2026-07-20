"""specthis command-line entry point.

Verb boundaries are load-bearing: ``check``/``status`` never write,
``run`` writes only runs.toml, ``vouch`` writes only vouches.toml.
Executor dispatch (local subprocess vs a configured scripthut submit
command) lives here and only here — everything below the CLI is pure.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click

from . import __version__, hashing
from .check import (
    Certification,
    Realization,
    Report,
    Status,
    check_project,
    code_manifest,
    code_sha,
    expected_inputs,
    is_library,
    machine_repairable,
    queues,
    topo_order,
)
from .install import init_specs_dir, install_agents, install_commands
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
    """Check the spec directory's grammar and list EVERY problem.

    Frontmatter, entry blocks, bindings, consumes/references edges —
    all files, all problems at once (the other verbs stop at the
    first). Exits non-zero if anything is wrong. Reads only.
    """
    _, problems = _load_lenient(project_path)
    if not problems:
        click.echo("specs are clean")
        return
    for p in problems:
        click.echo(f"  {p.message}")
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
        for name in topo_order(project):
            r = reports[name]
            e = project.entries[name]
            kind = e.spec.kind if e.spec.kind == "library" else f"{e.spec.kind}/{e.tier}"
            marker = "" if r.materialized else "   [bytes remote]"
            axes = r.certification.value + (
                f" · {r.realization.value}" if r.realization else ""
            )
            click.echo(f"  {r.status.value:<20} {axes:<24} {name:<28} {kind}{marker}")
        return
    _require_active(project, entry)
    r = reports[entry]
    e = project.entries[entry]
    click.echo(f"entry:     {entry}   ({e.spec.path.name}, {e.spec.kind}/{e.tier})")
    axes = r.certification.value + (f" · {r.realization.value}" if r.realization else "")
    click.echo(f"status:    {r.status.value}  ({axes})")
    click.echo(f"spec_sha:  {r.spec_sha}")
    click.echo(f"code_sha:  {r.code_sha or '(code missing)'}")
    click.echo(f"scripts:   {', '.join(e.binding.scripts)}")
    click.echo(f"outputs:   {', '.join(e.outputs) or '(none — library: chain stops at code)'}")
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


# ------------------------------------------------------------------ run


def _execute_entry(
    project: Project, name: str, push_after: bool = False, position: str = ""
) -> None:
    """Resolve+record upstream digests -> dispatch -> write runs.toml."""
    entry = project.entries[name]
    runs = read_runs(project.specs_dir)
    prior = runs.get(name)

    missing_up = [
        u
        for u in entry.consumes
        if u not in runs and not is_library(project.entries[u])
    ]
    if missing_up:
        raise click.ClickException(
            f"`{name}` consumes entries with no recorded run: "
            f"{', '.join(missing_up)} — run those first (or use --stale)"
        )
    inputs = expected_inputs(project, entry, runs)
    missing_files = sorted(k for k, v in inputs.items() if v == hashing.MISSING)
    if missing_files:
        raise click.ClickException(
            f"`{name}` has missing input files: {', '.join(missing_files)}"
        )
    if not entry.binding.run:
        raise click.ClickException(f"`{name}` has no run command in specs/bindings.toml")

    executor = entry.binding.executor or "local"
    if entry.tier == "intensive" and executor == "local":
        click.echo(
            f"note: intensive entry `{name}` running locally; set "
            "`executor` in specs/bindings.toml to dispatch to scripthut",
            err=True,
        )
    prefix = f"{position} " if position else ""
    click.echo(f"{prefix}running `{name}` via {executor}: {entry.binding.run}")
    started = time.monotonic()
    result = subprocess.run(entry.binding.run, shell=True, cwd=project.root)
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        raise click.ClickException(
            f"`{name}` failed (exit {result.returncode}) after "
            f"{_fmt_duration(elapsed)}; nothing recorded"
        )
    out_sha = hashing.output_sha(project.root, entry.outputs)
    if out_sha is None:
        missing = [p for p in entry.outputs if not (project.root / p).is_file()]
        raise click.ClickException(
            f"`{name}` finished but declared output(s) missing: {', '.join(missing)}"
        )
    record_run(
        project.specs_dir,
        name,
        Run(
            signature=hashing.signature(inputs),
            output=", ".join(entry.outputs),
            output_sha=out_sha,
            ran=_now(),
            executor=executor,
            inputs=inputs,
            duration_seconds=round(elapsed, 3),
        ),
    )
    # Say what the run did to the DAG: a reproduced output cuts the
    # cascade (downstream signatures unmoved); a moved one names the
    # blast radius so the wait ahead is legible.
    consumers = sorted(n for n, e in project.entries.items() if name in e.consumes)
    if prior is None:
        verdict = ""
    elif prior.output_sha == out_sha:
        verdict = " (output unchanged — downstream claims unaffected)"
    elif consumers:
        verdict = f" (output moved — {len(consumers)} consumer(s) now stale: {', '.join(consumers)})"
    else:
        verdict = " (output moved)"
    click.echo(
        f"{prefix}recorded run of `{name}` in {_fmt_duration(elapsed)} "
        f"-> {out_sha[:12]}…{verdict}"
    )
    if push_after:
        from .cache import CacheError, push

        try:
            key = push(project, name)
            click.echo(f"pushed `{name}` -> {key}")
        except CacheError as exc:
            click.echo(f"cache push failed for `{name}`: {exc}", err=True)


def _try_fetch(project: Project, name: str) -> bool:
    """Best-effort cache fetch; True when verified bytes landed."""
    from .cache import try_fetch
    from .ledger import read_runs as _read_runs

    entry = project.entries[name]
    expected = hashing.signature(expected_inputs(project, entry, _read_runs(project.specs_dir)))
    if try_fetch(project, name, expected):
        click.echo(f"fetched `{name}` from cache (no recompute)")
        return True
    return False


def _run_stale_parallel(
    project: Project, jobs: int, do_fetch: bool, do_push: bool
) -> tuple[int, int, list[tuple[str, str]], list[str]]:
    """The --stale walk with a worker pool: an entry is examined the
    moment its last upstream finishes, so independent branches of the
    DAG rebuild concurrently.

    The serial pass's guarantee survives: no entry starts until every
    upstream's claim is recorded, so each worker composes exactly the
    signature a serial pass would have. Ledger writes are already
    flock-serialized; reads take the shared lock. On a failure nothing
    new is scheduled — in-flight entries finish and are recorded.
    """
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    from graphlib import TopologicalSorter

    idx = {n: i for i, n in enumerate(topo_order(project))}
    sorter = TopologicalSorter({n: e.consumes for n, e in project.entries.items()})
    sorter.prepare()
    ran = fetched = dispatched = 0
    skipped: list[tuple[str, str]] = []
    failures: list[str] = []
    unseen = set(project.entries)  # neither dispatched nor resolved yet

    def build(name: str, position: str) -> str:
        if do_fetch and _try_fetch(project, name):
            return "fetched"
        _execute_entry(project, name, push_after=do_push, position=position)
        return "ran"

    def materialize(name: str) -> str:
        return "fetched" if _try_fetch(project, name) else ""

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures: dict = {}
        while True:
            if not failures and sorter.is_active():
                ready = sorted(sorter.get_ready(), key=idx.__getitem__)
                # One derivation per ready batch: a node's staleness is
                # settled once its upstreams are done, and cousins still
                # running cannot move it.
                reports = check_project(project) if ready else {}
                for name in ready:
                    unseen.discard(name)
                    report = reports[name]
                    if machine_repairable(report):
                        dispatched += 1
                        left = sum(1 for m in unseen if machine_repairable(reports[m]))
                        pos = f"[{dispatched}/{dispatched + left}]"
                        futures[pool.submit(build, name, pos)] = name
                    elif do_fetch and not report.materialized:
                        futures[pool.submit(materialize, name)] = name
                    else:
                        if report.certification is not Certification.CERTIFIED:
                            skipped.append((name, report.certification.value))
                        sorter.done(name)
            if futures:
                done_set, _ = wait(list(futures), return_when=FIRST_COMPLETED)
                for fut in done_set:
                    name = futures.pop(fut)
                    try:
                        outcome = fut.result()
                    except click.ClickException as exc:
                        failures.append(exc.message)
                        click.echo(f"  {exc.message}", err=True)
                    except Exception as exc:  # a worker crash, not a failed build
                        failures.append(f"`{name}`: {exc}")
                        click.echo(f"  `{name}`: {exc}", err=True)
                    else:
                        ran += outcome == "ran"
                        fetched += outcome == "fetched"
                    sorter.done(name)
                continue
            if failures or not sorter.is_active():
                break
    return ran, fetched, skipped, failures


@main.command("run")
@click.argument("entry", required=False)
@click.option(
    "--stale",
    "run_stale",
    is_flag=True,
    help="Rebuild every machine-repairable entry in dependency order.",
)
@click.option(
    "-p",
    "--parallel",
    "jobs",
    type=click.IntRange(min=1),
    default=1,
    metavar="N",
    help="With --stale: rebuild up to N independent entries at once. DAG order "
    "still holds — an entry starts only after all its upstreams have recorded.",
)
@click.option(
    "--fetch",
    "do_fetch",
    is_flag=True,
    help="Try the remote cache before recomputing (verified bytes, no ledger writes).",
)
@click.option(
    "--push",
    "do_push",
    is_flag=True,
    help="Push outputs to the remote cache after each successful run.",
)
@click.option(
    "--adopt",
    "do_adopt",
    is_flag=True,
    help=(
        "Record the row for a remotely-certified entry (see `specthis manifest`) "
        "without running anything or holding the bytes."
    ),
)
@_path_option
def run_cmd(
    entry: str | None,
    run_stale: bool,
    jobs: int,
    do_fetch: bool,
    do_push: bool,
    do_adopt: bool,
    project_path: Path,
) -> None:
    """Run one entry (or the whole machine queue) and record the claim.

    Writes runs.toml only; never touches vouches.toml. --stale takes
    the machine queue: every stale or never-run entry with code whose
    definition is not rejected — certification does not gate compute
    (an unvouched entry rebuilds while a mind audits it). With --fetch,
    an entry whose recorded claim already matches today's inputs is
    materialized from the cache instead of recomputed. With --adopt,
    nothing runs and no bytes move: the claim certified where the
    entry ran (`specthis manifest`) is recorded here. With --stale -p N,
    independent branches of the DAG rebuild concurrently.
    """
    project = _load(project_path)
    if run_stale == (entry is not None):
        raise click.ClickException("give exactly one of ENTRY or --stale")
    if do_adopt and (run_stale or do_fetch or do_push):
        raise click.ClickException(
            "--adopt records a remote claim for one entry; it does not run, "
            "fetch, or push bytes"
        )
    if jobs > 1 and not run_stale:
        raise click.ClickException(
            "-p/--parallel applies to --stale — a single entry is one run"
        )
    if entry is not None:
        _require_active(project, entry)
        if is_library(project.entries[entry]):
            raise click.ClickException(
                f"`{entry}` is a library entry — the chain stops at code; "
                "there is nothing to run, only to vouch"
            )
        if do_adopt:
            from .cache import CacheError
            from .remote import RemoteError, adopt

            try:
                run = adopt(project, entry)
            except (RemoteError, CacheError) as exc:
                raise click.ClickException(str(exc)) from exc
            click.echo(
                f"adopted remote run of `{entry}` -> {run.output_sha[:12]}… "
                f"(via {run.executor}; bytes stay remote — "
                f"`specthis cache fetch {entry}` materializes)"
            )
            return
        if do_fetch and _try_fetch(project, entry):
            return
        _execute_entry(project, entry, push_after=do_push)
        return
    order = topo_order(project)
    queue = [n for n in order if machine_repairable(check_project(project)[n])]
    if queue:
        par = f" (up to {jobs} in parallel)" if jobs > 1 else ""
        click.echo(
            f"{len(queue)} entr{'y' if len(queue) == 1 else 'ies'} in the machine "
            f"queue{par}: " + " -> ".join(queue)
        )
    started = time.monotonic()
    failures: list[str] = []
    if jobs > 1:
        ran, fetched, skipped, failures = _run_stale_parallel(project, jobs, do_fetch, do_push)
    else:
        ran, fetched, skipped = 0, 0, []
        for i, name in enumerate(order):
            # Re-derive after every run: an upstream rebuild makes new entries stale.
            reports = check_project(project)
            report = reports[name]
            if machine_repairable(report):
                if do_fetch and _try_fetch(project, name):
                    fetched += 1
                    continue
                # The queue can grow mid-run (an upstream whose output moved
                # makes new entries stale), so the total is re-counted live.
                done = ran + fetched
                left = sum(1 for m in order[i + 1 :] if machine_repairable(reports[m]))
                _execute_entry(
                    project, name, push_after=do_push, position=f"[{done + 1}/{done + 1 + left}]"
                )
                ran += 1
            elif do_fetch and not report.materialized and _try_fetch(project, name):
                # Claim stands, bytes elsewhere: --fetch is the explicit demand
                # to materialize; without it the entry is left alone (never
                # recomputed just because the bytes are not local).
                fetched += 1
            elif report.certification is not Certification.CERTIFIED:
                skipped.append((name, report.certification.value))
    summary = f"rebuilt {ran} entr{'y' if ran == 1 else 'ies'}"
    if fetched:
        summary += f", fetched {fetched} from cache"
    if ran or fetched:
        summary += f" in {_fmt_duration(time.monotonic() - started)}"
    click.echo(summary)
    for name, why in skipped:
        click.echo(f"  skipped {name}: {why} (needs a mind, not a machine)", err=True)
    if failures:
        n = len(failures)
        raise click.ClickException(
            f"{n} entr{'y' if n == 1 else 'ies'} failed; nothing recorded for failed runs"
        )


# ------------------------------------------------------------- manifest


@main.command("manifest")
@click.argument("entry")
@click.option(
    "--executor",
    default="remote",
    show_default=True,
    help="Executor label recorded in the claim (e.g. scripthut:mercury).",
)
@_path_option
def manifest_cmd(entry: str, executor: str, project_path: Path) -> None:
    """Certify THIS machine's bytes for ENTRY and upload them to the cache.

    Run where the repo checkout and the output bytes coexist — an HPC
    task's last step. Uploads the outputs tarball plus a manifest
    sidecar under the entry's composed signature, and records the
    derived row in this clone's runs.toml (so later entries in the same
    workflow compose fresh signatures) — the tool never commits it.
    The git pen stays wherever `specthis run --adopt` is used.
    """
    project = _load(project_path)
    _require_active(project, entry)
    from .cache import CacheError
    from .remote import RemoteError, certify

    try:
        m = certify(project, entry, executor=executor)
    except (RemoteError, CacheError) as exc:
        raise click.ClickException(str(exc)) from exc
    n = len(m.outputs)
    click.echo(
        f"certified `{entry}` at signature {m.signature[:12]}… "
        f"({n} output{'s' if n != 1 else ''}, output_sha {m.output_sha[:12]}…)"
    )
    click.echo(f"adopt on the ledger machine with: specthis run {entry} --adopt")


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
        pending = sorted(up for up in e.consumes if reports[up].status is not Status.READY)
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


# ---------------------------------------------------------------- cache


@main.group("cache")
def cache_group() -> None:
    """Remote byte cache keyed by composed signature (never writes ledgers).

    Configure with `[cache] url = "s3://bucket/prefix"` (or file:///path)
    in specs/bindings.toml, or the SPECTHIS_CACHE_URL env var.
    """


def _cache_op(project_path: Path, entry: str | None = None):
    from . import cache as cache_mod

    project = _load(project_path)
    if entry is not None:
        _require_active(project, entry)
    return cache_mod, project


@cache_group.command("push")
@click.argument("entry")
@_path_option
def cache_push_cmd(entry: str, project_path: Path) -> None:
    """Upload the entry's certified outputs under its recorded signature."""
    cache_mod, project = _cache_op(project_path, entry)
    try:
        key = cache_mod.push(project, entry)
    except cache_mod.CacheError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"pushed {key}")


@cache_group.command("fetch")
@click.argument("entry")
@_path_option
def cache_fetch_cmd(entry: str, project_path: Path) -> None:
    """Materialize the entry's recorded outputs (verified against the claim)."""
    cache_mod, project = _cache_op(project_path, entry)
    try:
        key = cache_mod.fetch(project, entry)
    except cache_mod.CacheError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"fetched {key}")


@cache_group.command("has")
@click.argument("entry")
@_path_option
def cache_has_cmd(entry: str, project_path: Path) -> None:
    """Exit 0 if the cache holds the entry's recorded signature."""
    cache_mod, project = _cache_op(project_path, entry)
    try:
        present = cache_mod.has(project, entry)
    except cache_mod.CacheError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("hit" if present else "miss")
    if not present:
        sys.exit(1)


@cache_group.command("list")
@_path_option
def cache_list_cmd(project_path: Path) -> None:
    """List cached archives."""
    cache_mod, project = _cache_op(project_path)
    try:
        keys = cache_mod.list_keys(project)
    except cache_mod.CacheError as exc:
        raise click.ClickException(str(exc)) from exc
    for key in keys:
        click.echo(key)
    if not keys:
        click.echo("(cache is empty)", err=True)


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
