---
description: Rebuild the machine queue (stale and never-run spec entries) in dependency order, fetching from the cache when configured, and report both queues after.
---

The user ran `/specthis-run $ARGUMENTS` — clear the machine queue.
This is machine work: no judgment, no vouching, runs.toml is the only
ledger touched. An unvouched entry still rebuilds — certification
does not gate compute; only a `rejected` definition does.

1. Run `specthis check`. If there is no "realizations needing a
   machine" section, report the queues as-is and stop — what remains
   needs a mind (`/specthis-vouch`) or an author, not a machine.
2. Decide the command:
   - Arguments given → they are entry names: `specthis build <entry>`.
   - No arguments → `specthis build`. specthis hands the **whole**
     pipeline to the compute manager, which decides what actually runs;
     it never selects steps itself, because only the manager knows what
     is already in its cache and whether a rerun reproduces identical
     bytes.
   - Parallelism, remote execution and caching are the **manager's**
     business, not specthis's. If the user wants them, the project needs
     a backend that has them (`[backend] class` in
     `specs/bindings.toml`); the bundled runner walks the DAG serially
     and nothing else.
   - Entries reading `current` with `bytes not local` are NOT stale and
     need nothing: the claim stands, the bytes live in the manager's
     store. Never rebuild an entry just to get bytes back.
   - An entry a manager ran elsewhere is recorded from its manifest:
     `specthis adopt <entry> path/to/manifest.json` — no execution.
   - An artefact edited on disk is the one case needing a targeted
     repair: `specthis build <entry> --force`.
3. **Respect the tiers.** If the machine queue contains
   `tier: intensive` entries (check the spec frontmatter or
   `specs/_index.json`), do not block on them casually:
   - confirm with the user before launching anything expected to burn
     hours of compute, unless they already said to proceed;
   - launch in the background (`run_in_background`, output to a log
     file) and monitor for milestones/errors instead of tailing —
     or hand off to the `experiment-runner` subagent.
   Quick-tier queues can just run in the foreground.
4. **Relay progress, not silence.** `specthis build` narrates
   itself: an upfront plan line (`3 entries in the machine queue:
   a -> b -> c`), a `[k/N]` counter per entry, and after each run its wall
   time plus what it did to the DAG — `output unchanged — downstream
   claims unaffected` (the cascade is cut there) or `output moved — N
   consumer(s) now stale: …` (the queue just grew). For a long or
   background run, surface these lines to the user as they appear —
   the plan line first, then each `[k/N] recorded run …` milestone —
   instead of going quiet until the end. Durations are also recorded
   in the run row (`duration_seconds`) and shown by
   `specthis status <entry>`, so use past timings to set expectations
   for a queue before launching it.
5. When the run finishes, run `specthis check` again and report:
   what was rebuilt, what was fetched from cache, how long it took,
   what was skipped (rejected/unimplemented definitions), and both
   queues fresh — anything under "definitions needing a mind" is the
   `/specthis-vouch` queue.

Never run `specthis vouch` here. If a run fails, report the failure
and the entry's log tail — nothing is recorded for failed runs, so
the ledger is already honest.
