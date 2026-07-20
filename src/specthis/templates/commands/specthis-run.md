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
   - Arguments given → they are entry names: run each with
     `specthis run <entry>`, upstream-first if several.
   - No arguments → `specthis run --stale` (topo order, the machine
     queue; skips only `rejected` and `unimplemented` definitions).
   - Add `-p 4` (`--parallel`) when the machine queue spans independent
     branches of the DAG — independent entries rebuild concurrently,
     and an entry still starts only after all its upstreams have
     recorded their claims. Keep intensive-tier queues serial unless
     the user asked for parallelism: `-p` multiplies concurrent
     compute burn. On a failure nothing new is scheduled; in-flight
     entries finish and are recorded.
   - Add `--fetch` when a cache is configured (`[cache] url` in
     `specs/bindings.toml` or `SPECTHIS_CACHE_URL` is set) — verified
     bytes beat recompute. Add `--push` too if the user asked to
     share results.
   - Entries reading `current` with `bytes not local` are NOT stale
     and need nothing: the claim stands, the bytes live in the cache.
     `--fetch` materializes them only if a local step actually needs
     the files; never re-run an entry just to get bytes back.
   - An entry that ran remotely and was certified there
     (`specthis manifest` on the compute machine) is recorded here
     with `specthis run <entry> --adopt` — no execution, no bytes.
3. **Respect the tiers.** If the machine queue contains
   `tier: intensive` entries (check the spec frontmatter or
   `specs/_index.json`), do not block on them casually:
   - confirm with the user before launching anything expected to burn
     hours of compute, unless they already said to proceed;
   - launch in the background (`run_in_background`, output to a log
     file) and monitor for milestones/errors instead of tailing —
     or hand off to the `experiment-runner` subagent.
   Quick-tier queues can just run in the foreground.
4. **Relay progress, not silence.** `specthis run --stale` narrates
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
