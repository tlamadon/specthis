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
from datetime import datetime, timezone
from pathlib import Path

import click

from . import __version__, hashing, progress, seam
from .adopt import AdoptError, adopt_manifest, publish, step_of
from .auditlint import spec_text_problems, spec_text_warnings
from .backends import FAILED, BackendError
from .backends import resolve as resolve_backend
from .certificates import write_all as write_certificates
from .check import (
    Certification,
    Realization,
    Report,
    Spend,
    check_project,
    code_manifest,
    code_sha,
    coordinates,
    expected_inputs,
    instance_inputs,
    is_library,
    is_source,
    keys_for,
    locality_of,
    machine_repairable,
    ordered_keys,
    queues,
    sibling_keys,
    spending,
    step_digest,
    tally,
    verified,
    waiting_on,
)
from .correspond import correspondence_problems, correspondence_warnings
from .install import (
    init_specs_dir,
    install_agents,
    install_commands,
    install_hooks,
    install_workflows,
)
from .instances import by_step as instances_by_step
from .instances import resolve_key, template_problems
from .ledger import (
    LOCALITIES,
    RUNS_FILE,
    LedgerError,
    Run,
    Vouch,
    read_runs,
    record_run,
    record_vouch,
)
from .parse import (
    Problem,
    Project,
    SpecError,
    draft_warnings,
    load_project,
    load_project_lenient,
)
from .pipeline import PipelineError
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
    """Reject verbs aimed at unknown or skipped entries, with the right hint.

    An **instance key** is a name here too. ``clean-wages`` is a
    template and has no report of its own; the thing every other
    surface prints, and the thing a user therefore types back, is
    ``clean-wages[country=chile]``. Membership in ``project.entries``
    alone cannot see one, which is why naming an instance used to come
    back "unknown entry" for a key the tool had just printed.

    Both facts are read through the template: a skip lives in a spec's
    frontmatter, so it is a property of the definition and every
    instance of it inherits the flag.
    """
    template = entry.partition("[")[0] or entry
    if template in project.draft_entries:
        raise click.ClickException(
            f"`{entry}` is draft ({project.draft_entries[template]} has "
            "draft: true) — the contract is unchecked prose; finish it and drop the flag"
        )
    if template in project.skipped_entries:
        raise click.ClickException(
            f"`{entry}` is skipped ({project.skipped_entries[template]} has "
            "skip: true) — remove the flag to work on it"
        )
    try:
        resolve_key(project, entry)
    except KeyError:
        raise click.ClickException(f"unknown entry `{entry}`") from None


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
        scripts = project.entries[report.instance_of or report.entry].binding.scripts
        return "no code at " + ", ".join(scripts)
    if report.certification is Certification.UNVOUCHED:
        if report.expired:
            return "moved since vouch: " + "; ".join(report.expired)
        return "spec or code moved since vouch" if report.vouch else "never vouched"
    if report.certification is Certification.REJECTED and report.vouch is not None:
        v = report.vouch
        return f"rejected by {v.attester}" + (f": {v.note}" if v.note else "")
    return ""


def _publish_adopted(project: Project, entry: str | None = None) -> dict[str, dict]:
    """Republish the adopted set after a ledger write, and say so.

    Every verb that records a derived claim goes through here. A claim
    the manager never hears about is the whole bug: `check` calls the
    entry current, the manager re-executes it, and no amount of
    rebuilding converges. The note is printed only when this entry's own
    step is in the set, so a `record` on a source entry — which has no
    step — stays quiet.
    """
    steps = publish(project)
    if entry is not None and step_of(project, entry) in steps:
        click.echo(f"  {seam.DOCUMENT}: {len(steps)} step(s) the manager can skip")
    return steps


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
    """A notary for a research pipeline. It makes nothing."""


# ---------------------------------------------------------------- check


def _axes_digest(r: Report) -> str:
    """One entry's contribution to the fingerprint.

    Both axes, plus the two digests a repair moves — so an edit that has
    not yet changed either axis (code rewritten, still unvouched) still
    reads as progress rather than as a stalled loop.
    """
    realization = r.realization.value if r.realization else "-"
    return f"{r.certification.value}|{realization}|{r.spec_sha}|{r.code_sha or '-'}"


def _queue_state(
    project: Project, reports: dict[str, Report], problems: list[Problem]
) -> dict:
    """The two queues as data — what a driver needs to decide what next.

    Derived from the same ``queues()`` over the same reports as the
    printed form, so the porcelain and the text can never disagree.
    Two fields exist only for a driver and have no printed counterpart:

    ``verdict`` answers whether looping can still make progress at all,
    and ``fingerprint`` answers whether the last loop actually made
    any — a digest over every entry's two axes plus its spec and code
    digests, in the project's own canonical encoding. Unchanged across
    iterations means nothing moved, which is a fact a driver can act on
    without having to judge it.

    ``blocked`` is advisory, not terminal: a rejection stands only at
    the pair it was filed against, so it clears the moment the spec or
    the code actually moves.
    """
    mind, machine = queues(reports)
    blocked = [r for r in mind if r.certification is Certification.REJECTED]
    open_mind = [r for r in mind if r.certification is not Certification.REJECTED]

    # Build order, not alphabetical. The printed form sorts by name
    # because a reader is scanning for one; a driver is *executing* the
    # list, and a consumer built before the thing it consumes fails on a
    # missing input. Same order the manager would choose, so following
    # this list and handing over the whole pipeline agree.
    rank = {key: i for i, key in enumerate(ordered_keys(project, reports))}

    def in_build_order(rs: list[Report]) -> list[Report]:
        return sorted(rs, key=lambda r: (rank.get(r.entry, len(rank)), r.entry))

    return {
        "verdict": (
            "work" if (problems or machine or open_mind) else "blocked" if blocked else "done"
        ),
        "mind": [
            {
                "entry": r.entry,
                "certification": r.certification.value,
                "hint": _mind_hint(r, project),
            }
            for r in in_build_order(mind)
        ],
        "machine": [
            {
                "entry": r.entry,
                "realization": r.realization.value if r.realization else None,
                "hint": _machine_hint(r),
                "unvouched": r.certification is not Certification.CERTIFIED,
            }
            for r in in_build_order(machine)
        ],
        "blocked": [
            {"entry": r.entry, "why": _mind_hint(r, project)}
            for r in in_build_order(blocked)
        ],
        "lint": {"problems": len(problems), "messages": [p.message for p in problems]},
        # Neither is a break, and both are traps for a loop: waiting heals
        # itself upstream, and absent bytes are a locality fact. Named here
        # so a driver can see them and leave them alone.
        "waiting_on_upstream": sum(
            1
            for r in reports.values()
            if r.certification is Certification.CERTIFIED
            and not machine_repairable(r)
            and not (r.computable and r.realized)
        ),
        "bytes_not_local": sorted(r.entry for r in reports.values() if not r.materialized),
        "ready": f"{sum(1 for r in reports.values() if verified(r))}/{len(reports)}",
        "fingerprint": hashing.manifest_sha(
            [
                (r.entry, _axes_digest(r))
                for r in reports.values()
            ]
            + [("\x00lint", str(len(problems)))]
        ),
    }


@main.command("check")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the two queues as JSON for a driver (see `specthis check --help`).",
)
@_path_option
def check_cmd(project_path: Path, as_json: bool) -> None:
    """Report the two queues: definitions needing a mind, realizations
    needing a machine. An entry can sit in both (the mind audits while
    the machine reruns). Downstream waiting is summarized per tree.

    Exits non-zero if either queue is non-empty or the spec directory
    has grammar problems (see `specthis lint`) — with or without
    `--json`, since the exit code reports the project, not the
    formatting. A driver should read `verdict`, which separates the
    three situations the single exit code cannot.
    """
    project, problems = _load_lenient(project_path)
    # Problem-tier text checks hold the verdict exactly like grammar
    # problems do; the warning tier stays out — the yolo Stop hook
    # blocks on `lint.problems`, and advice must never trap a session.
    problems = problems + spec_text_problems(project)
    reports = check_project(project)
    if as_json:
        click.echo(json.dumps(_queue_state(project, reports, problems), indent=2))
        if problems or any(queues(reports)):
            sys.exit(1)
        return
    _echo_problems(problems)
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
    skipped = ""
    if project.skipped_entries:
        drafts = f", {len(project.draft_entries)} draft" if project.draft_entries else ""
        skipped = f" (+{len(project.skipped_entries)} skipped{drafts})"
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
        + spec_text_problems(project)
    )
    warnings = correspondence_warnings(project) + spec_text_warnings(project) + draft_warnings(
        project
    )
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

#: One colour per state, shared by the summary and the list so a count
#: and the rows it counts never disagree. Three tiers: green — the claim
#: holds; yellow — somebody still has to do the work; red — there is
#: nothing to work with (no code bound) or a mind said no.
_STATE_COLOR = {
    Certification.CERTIFIED: "green",
    Certification.UNVOUCHED: "yellow",
    Certification.UNIMPLEMENTED: "red",
    Certification.REJECTED: "red",
    Realization.CURRENT: "green",
    Realization.STALE: "yellow",
    Realization.NEVER_RUN: "yellow",
}

#: Where the work happened. Remote is the colour that means "somebody
#: else's machine, and probably somebody's budget"; unknown is dim
#: because it is an absence, not a place.
_PLACE_COLOR = {"remote": "cyan", "local": "green", "unknown": None}

#: Row order for ``status -a``: worst break first, and a certification
#: break outranks a realization one — the same precedence the flattened
#: word uses, because a definition nobody trusts makes its bytes moot.
#: Entries with no break of their own sort after these, blocked-upstream
#: before done, and ties break on the topological order.
_SEVERITY = (
    Certification.REJECTED,
    Certification.UNIMPLEMENTED,
    Certification.UNVOUCHED,
    Realization.STALE,
    Realization.NEVER_RUN,
)


def _paint(text: str, color: str | None = None, **kw) -> str:
    """Style, but leave the string alone when there is nothing to say.

    ``click.echo`` drops the codes when stdout is not a terminal, so
    every assertion in the tests — and every pipe into grep — still sees
    the plain words.
    """
    return click.style(text, fg=color, **kw) if (color or kw) else text


def _severity(r: Report) -> int:
    """Sort rank: the worst of this entry's own two states, else whether
    it is merely waiting on somebody upstream."""
    ranks = [_SEVERITY.index(s) for s in (r.certification, r.realization) if s in _SEVERITY]
    if ranks:
        return min(ranks)
    return len(_SEVERITY) if waiting_on(r) else len(_SEVERITY) + 1


def _tree_line(label: str, counts: dict, good, skipped: int = 0, drafts: int = 0) -> str:
    """One tree, one line: how much of it holds, then what is left.

    The fraction leads because it is the number you came for; the broken
    states follow in worst-first order and only when non-zero, so a
    clean tree is a single short phrase rather than a row of noughts.
    """
    total = sum(counts.values())
    done = counts[good]
    head = f"{done}/{total} {good.value}"
    tail = [
        _paint(f"{n} {state.value}", _STATE_COLOR[state])
        for state, n in counts.items()
        if state is not good and n
    ]
    if skipped:
        note = f" ({drafts} draft)" if drafts else ""
        tail.append(_paint(f"+{skipped} skipped{note}", dim=True))
    line = f"{label:<12}" + _paint(head, "green" if total and done == total else None, bold=True)
    return (line + " " * max(3, 22 - len(head)) + "   ".join(tail)) if tail else line


#: Locality order in the machines line: the expensive place first,
#: then the cheap one, then what nobody classified.
_PLACES = ("remote", "local", "unknown")


def _spend(s: Spend) -> str:
    """One place's cost: CPU when somebody measured it, wall otherwise.

    Never both — three places on one line has no room, and CPU is the
    number that was asked for. Wall time is the honest stand-in while a
    manager reports no CPU, and it is labelled so nobody adds the two
    kinds together by eye.
    """
    return f"{_fmt_duration(s.cpu)} cpu" if s.cpu is not None else _fmt_duration(s.wall)


def _machines_line(project: Project, reports: dict[str, Report]) -> str:
    """What the standing claims cost, split by where the work happened.

    Printed only when there is a cost worth a second of anybody's time.
    A project that has never run anything, whose manager reports no
    timings, or whose whole pipeline takes under a second is told
    nothing rather than shown a row of noughts — which is also what
    keeps the glance two lines for everyone who does not have this data.
    """
    spend = spending(project, reports)
    wall = sum(s.wall for s in spend.values())
    cpu = sum(s.cpu for s in spend.values() if s.cpu is not None)
    if not round(wall) and not round(cpu):
        return ""
    runs = sum(s.runs for s in spend.values())
    head = " · ".join(
        part
        for part in (
            f"{_fmt_duration(wall)} wall" if wall else "",
            f"{_fmt_duration(cpu)} cpu" if cpu else "",
        )
        if part
    ) + f" over {runs} runs"
    split = "   ".join(
        _paint(f"{place} {_spend(spend[place])}", _PLACE_COLOR[place])
        for place in _PLACES
        if place in spend and (spend[place].wall or spend[place].cpu is not None)
    )
    untimed = sum(s.untimed for s in spend.values())
    tail = _paint(f"   ({untimed} untimed)", dim=True) if untimed else ""
    return f"{'machines':<12}{_paint(head, bold=True)}{' ' * max(3, 22 - len(head))}{split}{tail}"


def _summary(project: Project, reports: dict[str, Report]) -> None:
    """The two queues at a glance — one line per tree, and that is all.

    ``skipped`` rides on the vouch line because a skip is a fact about a
    definition (``skip: true`` in a spec's frontmatter). Without it the
    totals here would quietly disagree with the number of specs on disk.
    """
    if not reports:
        click.echo("no entries")
        return
    vouch, run = tally(reports)
    skipped = len(project.skipped_entries)
    drafts = len(project.draft_entries)
    click.echo(_tree_line("vouch tree", vouch, Certification.CERTIFIED, skipped, drafts))
    click.echo(_tree_line("run tree", run, Realization.CURRENT))
    if machines := _machines_line(project, reports):
        click.echo(machines)


def _status_rows(project: Project, reports: dict[str, Report]) -> None:
    """Every entry, worst break first — the inventory behind the summary.

    Columns, not the fused ``a · b`` string, because the point of the
    list is to scan one tree at a time: all the yellow in the second
    column is the machine queue.
    """
    order = {name: i for i, name in enumerate(ordered_keys(project, reports))}
    names = sorted(order, key=lambda n: (_severity(reports[n]), order[n]))
    width = max(len(n) for n in names)
    for name in names:
        r = reports[name]
        e = project.entries[r.instance_of or name]
        kind = e.kind if e.kind in ("library", "source") else f"{e.kind}/{e.tier}"
        cert = _paint(f"{r.certification.value:<14}", _STATE_COLOR[r.certification])
        real = (
            _paint(f"{r.realization.value:<12}", _STATE_COLOR[r.realization])
            if r.realization is not None
            else _paint(f"{'—':<12}", dim=True)  # a library is not on this tree
        )
        upstream = waiting_on(r)
        notes = ([] if r.materialized else ["bytes remote"]) + (
            [f"waiting on {' and '.join(upstream)}"] if upstream else []
        )
        note = _paint("   " + " · ".join(notes), dim=True) if notes else ""
        click.echo(f"  {cert}{real}{name:<{width}}   {kind}{note}")


def _timing(meter: progress.Meter, explicit: bool) -> None:
    """Say what the derivation cost — always on `--timing`, otherwise
    only when it was slow enough that you noticed.

    On stderr, so it never lands in a pipe. A verb that comments on its
    own speed after every fast run is noise; one that stays silent
    through five seconds of hashing leaves you guessing.
    """
    if explicit:
        for line in progress.report(meter):
            click.echo(_paint(line, dim=True), err=True)
    elif meter.elapsed >= progress.CHATTY:
        click.echo(_paint(progress.summary(meter), dim=True), err=True)


@main.command("status")
@click.argument("entry", required=False)
@click.option(
    "-a",
    "--all",
    "show_all",
    is_flag=True,
    help="Also list every entry, worst break first.",
)
@click.option(
    "--timing",
    is_flag=True,
    help="Report where the derivation spent its time, on stderr.",
)
@_path_option
def status_cmd(entry: str | None, show_all: bool, timing: bool, project_path: Path) -> None:
    """Both trees in two lines — or one entry in detail.

    Bare, this is the glance: per tree, how much of the project holds
    and what the rest is waiting for. `-a` keeps those two lines and
    adds the inventory behind them, one row per entry, sorted worst
    break first and coloured by state. Name an ENTRY instead for the
    full record — digests, scripts, outputs, and which input moved.

    Deriving means re-hashing every byte the project declares, so a big
    tree spins on stderr while it works and says what that cost when it
    was slow; `--timing` says so every time.

    Reads only, and never exits non-zero on a break: that is `check`'s
    job. This verb reports, it does not judge.
    """
    with progress.watch() as watcher:
        watcher.phase("reading specs")
        project = _load(project_path)
        watcher.phase("deriving")
        reports = check_project(project, observe=watcher.tick)
    if entry is None:
        _summary(project, reports)
        if show_all and reports:
            click.echo()
            _status_rows(project, reports)
    else:
        if show_all:
            raise click.ClickException("`-a` lists every entry — drop the entry name")
        _require_active(project, entry)
        _status_detail(project, reports, entry)
    _timing(watcher.meter, timing)


def _status_detail(project: Project, reports: dict[str, Report], entry: str) -> None:
    """One entry's full record: both axes, both digests, and what moved."""
    if entry not in reports:
        raise click.ClickException(
            f"no claim for `{entry}`"
            + (" — it is a template; name one of its instances" if entry in project.entries else "")
        )
    r = reports[entry]
    e = project.entries[r.instance_of or entry]
    click.echo(f"entry:     {entry}   ({e.spec.path.name}, {e.kind}/{e.tier})")
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
        cost = " · ".join(
            part
            for part in (
                f"took {_fmt_duration(r.run.duration_seconds)}"
                if r.run.duration_seconds is not None
                else "",
                f"{_fmt_duration(r.run.cpu_seconds)} cpu"
                if r.run.cpu_seconds is not None
                else "",
                locality_of(project, r.run),
            )
            if part
        )
        click.echo(f"run:       {r.run.ran} via {r.run.executor} ({cost})")
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
    _publish_adopted(project, entry)


# --------------------------------------------------------------- record


@main.command("record")
@click.argument("entry")
@click.option(
    "--as", "executor", default="hand", show_default=True,
    help="Who or what put these bytes here — a person, a one-off script, a vendor.",
)
@click.option(
    "--where",
    type=click.Choice(LOCALITIES),
    default=None,
    help="Where the work behind these bytes happened. Unset when you would be guessing.",
)
@click.option(
    "--cpu",
    "cpu_seconds",
    type=float,
    default=None,
    help="CPU seconds it cost, if you know. Claim metadata: it enters no digest.",
)
@_path_option
def record_cmd(
    entry: str,
    executor: str,
    where: str | None,
    cpu_seconds: float | None,
    project_path: Path,
) -> None:
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
    try:
        e, inst = resolve_key(project, entry)
    except KeyError:
        raise click.ClickException(f"no entry or instance named `{entry}`") from None
    _require_active(project, e.name)
    outs = list(inst.outputs if inst else e.outputs)
    if not outs:
        raise click.ClickException(f"`{entry}` declares no output — nothing to pin")

    missing = [p for p in outs if not (project.root / p).is_file()]
    if missing:
        raise click.ClickException(
            f"`{entry}`: no bytes at {', '.join(missing)} — place the file first"
        )
    out_sha = hashing.output_sha(project.root, outs)
    assert out_sha is not None
    runs = read_runs(project.specs_dir)
    prior = runs.get(entry)
    inputs = (
        instance_inputs(project, e, inst, runs, sibling_keys(project, e, inst)) if inst
        else expected_inputs(project, e, runs)
    )
    record_run(
        project.specs_dir,
        entry,
        Run(
            signature=hashing.signature(inputs),
            output=", ".join(outs),
            output_sha=out_sha,
            ran=_now(),
            executor=executor,
            inputs=inputs,
            outputs=hashing.files_manifest(project.root, outs),
            where=where,
            cpu_seconds=cpu_seconds,
        ),
    )
    moved = "" if prior is None else (
        " (bytes unchanged)" if prior.output_sha == out_sha else " (bytes moved)"
    )
    click.echo(f"recorded `{entry}` -> {out_sha[:12]}…{moved}")
    _publish_adopted(project, entry)
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

    Before handing over, the **adopted set** is republished (§7.8) so the
    manager can see which steps the ledger already accounts for —
    including those whose bytes were made off-machine and countersigned
    by `adopt`, which it has no other way to learn about.

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

    accounted = publish(project)
    if accounted:
        click.echo(f"{len(accounted)} step(s) already accounted for by the ledger")

    handle = backend.submit(list(entries) or None, force=force)
    state = backend.poll(handle)
    produced = backend.manifests(handle)

    # Steps carry pipeline ids; claims are keyed by entry — or by
    # instance, for a template. The mapping comes from output patterns,
    # never from how a backend chose to name its steps.
    instance_of_step = {sid: inst.name for sid, (_e, inst) in instances_by_step(project).items()}

    adopted, refused, failed = [], [], []
    for sid, manifest in sorted(produced.items()):
        # A failed step is not a refused manifest: the manager is
        # reporting honestly that the work did not happen. Saying
        # "manifest reports a failed step" buried that, and buried the
        # exit code with it.
        if manifest.get("exit_code") not in (0, None):
            failed.append((sid, manifest))
            continue
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
    if adopted:
        publish(project)  # the claims just recorded, back to the manager

    for sid, manifest in failed:
        click.echo(f"  failed: `{sid}` exited {manifest['exit_code']}", err=True)
        click.echo(f"          command: {manifest.get('command', '(not reported)')}", err=True)
        if manifest.get("exit_code") == 127:
            click.echo(
                "          exit 127 is the shell's `command not found` — the command may "
                "not be on PATH in a non-interactive shell", err=True,
            )
    if failed:
        click.echo(
            "  steps downstream of a failure are never attempted, so anything you asked "
            "for above a failed step was not built", err=True,
        )
    for why in refused:
        click.echo(f"  refused: {why}", err=True)
    if failed or refused or state == FAILED:
        raise click.ClickException(
            f"{len(failed)} step(s) failed, {len(refused)} manifest(s) refused; "
            "nothing was recorded for those or for anything downstream"
        )


# -------------------------------------------------------------- adopted


@main.command("adopted")
@_path_option
def adopted_cmd(project_path: Path) -> None:
    """Publish the steps the ledger already accounts for (§7.8).

    The seam's third document. `adopt` records that bytes made elsewhere
    are current, but a compute manager keeps its own bookkeeping and
    consults that — so without this, a manager re-executes exactly the
    work adoption exists to bring in.

    `build` republishes it for you. Run this verb when you drive your
    manager yourself (make, snakemake, a submit script) — then have it
    consult `.specthis/adopted.json`: per step, the command and the
    dependency and output digests, so it can decide for itself.

    It is derived state, not a ledger: regenerating it is always safe,
    and it belongs in .gitignore.
    """
    project = _load(project_path)
    steps = publish(project)
    click.echo(f"{len(steps)} step(s) accounted for -> {seam.DOCUMENT}")
    for sid, record in sorted(steps.items()):
        click.echo(f"  {sid}  ({', '.join(record['entries'])})")


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
    try:
        e, inst = resolve_key(project, entry)
    except KeyError:
        raise click.ClickException(f"unknown entry `{entry}`") from None
    _require_active(project, e.name)
    c = (
        hashing.output_sha(project.root, list(inst.outputs))
        if inst and is_source(e)
        else code_sha(project, e)
    )
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
        # Decomposed digests: the contract tier decides expiry and
        # rejection identity; the block tier lets check/status say WHAT
        # moved instead of only that something did.
        spec_contract_sha=e.contract_sha,
        spec_block_sha=e.block_sha,
        # The wiring is part of what was judged: realizing a spec means
        # writing code *and* feeding it the right inputs (spec §1).
        step_sha=(step_digest(project, e) or "") if inst is None else "",
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
        # An upstream may be a template, which has no report of its own —
        # its instances carry the claims, and any one of them unverified
        # leaves this entry waiting.
        by_entry = keys_for(reports)
        pending = sorted(
            up
            for up in e.consumes
            if not all(verified(reports[k]) for k in by_entry.get(up, []))
        )
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


@main.command("badge")
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Write mind.json + machine.json into this directory instead of stdout.",
)
@click.option(
    "--no-data",
    is_flag=True,
    help="This checkout has no data files. Drops source entries whose bytes are "
    "absent but recorded in a ledger — on those, absence is a fetch away, not a "
    "break. Sources that were never recorded still count. Use it in CI.",
)
@click.option(
    "--markdown",
    "as_markdown",
    is_flag=True,
    help="Print the README snippet for the published badges and exit "
    "(owner/repo read from `git remote origin` unless --repo says otherwise).",
)
@click.option("--repo", default=None, help="owner/repo for --markdown.")
@click.option(
    "--branch",
    default="badges",
    show_default=True,
    help="Branch the workflow publishes the JSON to; used by --markdown.",
)
@_path_option
def badge_cmd(
    out: Path | None,
    no_data: bool,
    as_markdown: bool,
    repo: str | None,
    branch: str,
    project_path: Path,
) -> None:
    """Emit one shields.io endpoint badge per tree: minds, machines.

    A regenerated view like the dashboard and the DAG — it derives
    nothing, it counts the two queues `check` reports and picks a
    colour. Publish the JSON somewhere raw-servable (the shipped
    workflow commits it to a `badges` branch) and point a static
    markdown badge at it.

    **Always exits 0**: a full queue is a fact about the project, not a
    failure of the view. `check` is the verb that gates CI.
    """
    from . import badge as badges

    project, problems = _load_lenient(project_path)
    if as_markdown:
        slug = repo or _origin_slug(project_path)
        if not slug:
            raise click.ClickException(
                "no GitHub remote found — pass --repo owner/repo"
            )
        click.echo(badges.markdown(slug, branch))
        return
    bodies = badges.endpoints(project, check_project(project), problems, no_data)
    if out is None:
        click.echo(json.dumps(bodies, indent=2))
        return
    for path in badges.write(out, bodies):
        click.echo(f"  wrote  {path}")


def _origin_slug(project_path: Path) -> str | None:
    """``owner/repo`` from the checkout's origin remote, if it is GitHub."""
    from . import badge as badges

    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return badges.slug(url)


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
        ["spec-auditor", "spec-reader", "spec-implementer", "experiment-runner", "spec-critic"]
    ),
    help="Install only the named agent(s), and no slash commands. Repeatable. Default: everything.",
)
@click.option(
    "--workflows",
    is_flag=True,
    help="Also write .github/workflows/badges.yml — the job that publishes the "
    "two tree badges. Opt-in: it pushes a `badges` branch under the repo's token.",
)
def install_cmd(
    project_path: Path, force: bool, selected: tuple[str, ...], workflows: bool
) -> None:
    """Copy the specthis subagents into <project>/.claude/agents/, the
    slash commands (e.g. /specthis-vouch) into <project>/.claude/commands/,
    and the /specthis-yolo Stop hook into <project>/.claude/hooks/ —
    registering it in settings.json without disturbing what is there.
    That hook stays inert until /specthis-yolo arms it."""
    installed, skipped = install_agents(
        project_path=project_path,
        force=force,
        agents=list(selected) if selected else None,
    )
    if not selected:
        cmd_installed, cmd_skipped = install_commands(project_path=project_path, force=force)
        installed += [f"/{name} (command)" for name in cmd_installed]
        skipped += cmd_skipped
        # The Stop hook that /specthis-yolo arms. Inert without it.
        hook_installed, hook_skipped = install_hooks(project_path=project_path, force=force)
        installed += [
            n if n.endswith(")") else f".claude/hooks/{n}.py" for n in hook_installed
        ]
        skipped += hook_skipped
    if workflows:
        wf_installed, wf_skipped = install_workflows(project_path=project_path, force=force)
        installed += [f".github/workflows/{name}.yml" for name in wf_installed]
        skipped += wf_skipped
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
