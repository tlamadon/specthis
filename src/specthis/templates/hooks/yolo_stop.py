#!/usr/bin/env python3
"""Stop hook for ``/specthis-yolo``: hold the loop closed until it converges.

An agent driving this pipeline stops early for a structural reason: the
project's own operations manual tells it to. `AGENTS.md` says *"wait for
explicit confirmation"* and *"stop, propose the vouch"*, and the shipped
commands each end with "report both queues and stop". That is the right
default and the wrong one for an unattended run, so `/specthis-yolo`
suspends it — and this hook is what makes the suspension real. Nothing
else can: every other mechanism ends up asking the model to decide
whether it is finished, which is the judgment that was failing.

**Why a hook and not a prompt.** Draining the queues once is never
enough. Building an entry moves its output, so its consumers go stale —
the machine queue grows as you drain it. Repairing a definition moves
the spec or the code, which expires that entry's vouch — the mind queue
grows as you drain it. Convergence is a fixed point, and a fixed point
needs a test evaluated *after* the agent believes it is done. `Stop` is
that moment.

**What it decides.** `specthis check --json` reports the project;
`.specthis/auto.json` holds the loop's own scratch state (what compute
is in flight, what has been set aside). Neither alone is enough: an
entry whose job is still queued is genuinely `never-run`, so the
project looks like it needs a machine when in fact it needs patience.
Actionability is the intersection, so it is computed here rather than in
specthis, which stays a passive oracle.

**Fail open, always.** A hook that can hold a session open must never do
it by accident. A missing sentinel, unparseable JSON, an absent
`specthis`, a timeout, an unexpected exception — every one of them
allows the stop. The failure mode is "yolo quietly stopped working",
never "the session will not end".

Four independent ways out, so a run always terminates: the queues drain,
the iteration budget runs out, the wall-clock deadline passes, or the
fingerprint stops moving. Esc still wins over all of them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

#: Consecutive blocked stops with an identical fingerprint before the run
#: is called stalled. The fingerprint covers both axes of every entry plus
#: its spec and code digests, so anything the loop actually does moves it —
#: an edit that has not yet been judged still counts as progress. Three
#: rounds of moving nothing is a loop that has run out of ideas.
STALL_ROUNDS = 3

#: `check` re-hashes every declared byte. Generous, because a slow answer
#: is not a wrong one — and a timeout only ever ends the run early.
CHECK_TIMEOUT_S = 120


def find_specthis(root: Path) -> str | None:
    """The `specthis` to ask, in the order a project is most likely to mean.

    A hook runs in whatever environment the editor had, which is often
    not the one the project installs into: under `uv` or a plain venv the
    console script sits in `.venv/bin` and never reaches PATH, so
    `which` alone would silently fail open on the most common setup
    there is. `SPECTHIS_BIN` is the escape hatch for everything else.
    """
    override = os.environ.get("SPECTHIS_BIN")
    if override and Path(override).exists():
        return override
    for venv in (".venv", "venv"):
        candidate = root / venv / ("Scripts" if os.name == "nt" else "bin") / "specthis"
        if candidate.exists():
            return str(candidate)
    return shutil.which("specthis")


def allow(message: str | None = None) -> None:
    """Let the turn end. The only thing this hook does by default."""
    out: dict = {}
    if message:
        out["systemMessage"] = message
    print(json.dumps(out))
    sys.exit(0)


def block(reason: str) -> None:
    """Refuse the stop. ``reason`` is injected as a system prompt, so it
    has to be the next command — not encouragement to keep going."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "Stop",
                    "decision": "block",
                    "reason": reason,
                }
            }
        )
    )
    sys.exit(0)


def write_sentinel(path: Path, data: dict) -> None:
    """Replace the sentinel atomically; never let a crash leave half a file."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def disarm(path: Path, data: dict, message: str) -> None:
    """End the run: mark the sentinel inactive, then allow the stop.

    Every terminal path goes through here, which is what stops a crashed
    or interrupted session from leaving a hook armed against the next one.
    """
    data["active"] = False
    data["ended"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["ended_because"] = message
    try:
        write_sentinel(path, data)
    except OSError:
        pass  # the message still gets through, and `active` is advisory
    allow(f"specthis-yolo: {message}")


def summarize(entries: list[dict], key: str = "entry", limit: int = 4) -> str:
    """A few names and a count — enough to steer, short enough to read."""
    names = [e[key] for e in entries]
    head = ", ".join(names[:limit])
    return head if len(names) <= limit else f"{head}, +{len(names) - limit} more"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        allow()

    root = Path(payload.get("cwd") or Path.cwd())
    sentinel_path = root / ".specthis" / "auto.json"

    try:
        sentinel = json.loads(sentinel_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        allow()  # not a yolo run, or the sentinel is unreadable
    if not isinstance(sentinel, dict) or not sentinel.get("active"):
        allow()

    deadline = sentinel.get("deadline")
    if deadline:
        try:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(deadline):
                disarm(sentinel_path, sentinel, "deadline reached — stopping")
        except ValueError:
            pass  # an unparseable deadline is not a reason to trap the session

    left = sentinel.get("iterations_left")
    if not isinstance(left, int) or left <= 0:
        disarm(sentinel_path, sentinel, "iteration budget spent — stopping")

    specthis = find_specthis(root)
    if specthis is None:
        allow()
    try:
        proc = subprocess.run(
            [specthis, "check", "--json", "--path", str(root)],
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT_S,
            check=False,  # a dirty project exits 1; that is the normal case
        )
        state = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        allow()  # cannot see the project; never guess at it

    # What the loop is already waiting on, and what it has given up on.
    # Both are the loop's own bookkeeping, which is why the intersection
    # with the project's queues is computed here and not by `check`.
    # `set_aside` applies to BOTH axes: the manual tells the loop to set
    # aside mind entries (a critic doubted twice) and machine entries (a
    # step failed twice, a source with no bytes) alike, and an entry set
    # aside must stop counting as work on whichever axis it sits.
    watching = sentinel.get("watching") or []
    watched = {e for w in watching if isinstance(w, dict) for e in (w.get("entries") or [])}
    set_aside = {
        e.get("entry") for e in (sentinel.get("set_aside") or []) if isinstance(e, dict)
    }

    problems = state.get("lint", {}).get("problems", 0)
    # A rejection is a mind's standing "no". The loop may move the spec or
    # the code underneath it, but it may never answer it — so it is not
    # work this hook will hold the session open for.
    mind = [
        m
        for m in state.get("mind", [])
        if m.get("certification") != "rejected" and m.get("entry") not in set_aside
    ]
    machine = [
        m
        for m in state.get("machine", [])
        if m.get("entry") not in watched and m.get("entry") not in set_aside
    ]

    if not (problems or mind or machine):
        if watching:
            # Everything left is in flight. Allow the stop but stay armed:
            # the backgrounded `scripthut run watch` re-invokes the session
            # when the run goes terminal, and the loop picks up from there.
            # Blocking here would spin the model against a cluster.
            # Deliberately BEFORE the sentinel write below: an in-flight
            # wait consumes no iteration and moves no stall fingerprint —
            # an allow ends the turn, so there is nothing to charge for.
            # A watch that never returns is bounded by the deadline alone.
            allow(f"specthis-yolo: waiting on {len(watching)} run(s) in flight")
        parts = [f"ready {state.get('ready', '?')}"]
        if state.get("blocked"):
            parts.append(f"{len(state['blocked'])} blocked ({summarize(state['blocked'])})")
        if set_aside:
            parts.append(f"{len(set_aside)} set aside ({', '.join(sorted(set_aside))})")
        disarm(sentinel_path, sentinel, "converged — " + "; ".join(parts))

    fingerprint = state.get("fingerprint")
    repeat = sentinel.get("repeat", 0) + 1 if fingerprint == sentinel.get("last_fingerprint") else 0
    if repeat >= STALL_ROUNDS and not watching:
        disarm(
            sentinel_path,
            sentinel,
            f"stalled — {STALL_ROUNDS} rounds with nothing moving; "
            f"{len(mind)} on minds, {len(machine)} on machines",
        )

    sentinel["iterations_left"] = left - 1
    sentinel["last_fingerprint"] = fingerprint
    sentinel["repeat"] = repeat
    try:
        write_sentinel(sentinel_path, sentinel)
    except OSError:
        allow()  # cannot count iterations, so cannot bound the loop

    # The reason becomes a system prompt, so it names the next command.
    # Order matters and is the manual's: specs must parse before anything
    # below them can be trusted, and the two queues then drain in parallel.
    steps = []
    if problems:
        steps.append(
            f"{problems} spec problem(s) — run `specthis lint` and fix them. "
            "Your pen here covers specs/*.md and specs/bindings.toml, nothing else."
        )
    if machine:
        steps.append(
            f"machine queue ({len(machine)}): {summarize(machine)} — build them. "
            "Submit long work to scripthut and background "
            "`scripthut run watch <id> --exit-status`, recording the run in "
            ".specthis/auto.json under `watching`."
        )
    if mind:
        steps.append(
            f"mind queue ({len(mind)}): {summarize(mind)} — spawn a fresh spec-critic "
            "subagent per entry, batched, ~4 in flight. You must not run "
            "`specthis vouch` yourself, even for entries you did not write. "
            "If spec text changed since the last spec-reader pass, commission "
            "spec-reader over specs/ BEFORE the critics — a text contradiction "
            "is cheaper to fix than for critics to rediscover per entry."
        )
    if watching:
        steps.append(f"{len(watching)} run(s) already in flight — do not resubmit them.")

    block(
        "specthis-yolo is active: do not stop, do not report and wait. "
        f"{sentinel['iterations_left']} iteration(s) left.\n"
        + "\n".join(f"- {s}" for s in steps)
        + "\n\nRe-check afterwards — the queues grow as you drain them: a rebuilt "
        "output makes its consumers stale, and a repaired definition expires its "
        "own vouch. Entries listed under `bytes_not_local` are NOT stale; never "
        "rebuild one to fetch its bytes."
    )


if __name__ == "__main__":
    main()
