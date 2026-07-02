---
description: Rebuild the machine-repairable (stale) spec entries in dependency order, fetching from the cache when configured, and report the new frontier.
---

The user ran `/specthis-run $ARGUMENTS` — clear the machine-repairable
part of the frontier. This is machine work: no judgment, no vouching,
runs.toml is the only ledger touched.

1. Run `specthis check`. If nothing is `stale`, report the frontier
   as-is and stop — what remains needs a mind (`/specthis-vouch`) or
   an author, not a machine.
2. Decide the command:
   - Arguments given → they are entry names: run each with
     `specthis run <entry>`, upstream-first if several.
   - No arguments → `specthis run --stale` (topo order, skips
     entries that need a mind).
   - Add `--fetch` when a cache is configured (`[cache] url` in
     `specs/bindings.toml` or `SPECTHIS_CACHE_URL` is set) — verified
     bytes beat recompute. Add `--push` too if the user asked to
     share results.
   - Entries reading `ready` with `bytes not local` are NOT stale and
     need nothing: the claim stands, the bytes live in the cache.
     `--fetch` materializes them only if a local step actually needs
     the files; never re-run an entry just to get bytes back.
   - An entry that ran remotely and was certified there
     (`specthis manifest` on the compute machine) is recorded here
     with `specthis run <entry> --adopt` — no execution, no bytes.
3. **Respect the tiers.** If the stale queue contains
   `tier: intensive` entries (check the spec frontmatter or
   `specs/_index.json`), do not block on them casually:
   - confirm with the user before launching anything expected to burn
     hours of compute, unless they already said to proceed;
   - launch in the background (`run_in_background`, output to a log
     file) and monitor for milestones/errors instead of tailing —
     or hand off to the `experiment-runner` subagent.
   Quick-tier queues can just run in the foreground.
4. When the run finishes, run `specthis check` again and report:
   what was rebuilt, what was fetched from cache, what was skipped as
   needing a mind (that list is the `/specthis-vouch` queue), and the
   new frontier.

Never run `specthis vouch` here. If a run fails, report the failure
and the entry's log tail — nothing is recorded for failed runs, so
the ledger is already honest.
