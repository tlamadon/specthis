---
description: Audit the audit-needed spec entries with a fresh spec-critic subagent, which vouches clear passes, rejects clear violations, and reports every doubt for you to judge.
---

The user ran `/specthis-vouch $ARGUMENTS` — an explicit commission to
hand the vouching pen to a fresh critic session.

1. **Commissioning name.** Run `git config user.name` and use its
   output as the commissioning human's name. If it is empty, ask the
   user for their name before doing anything — the critic refuses to
   vouch anonymously. Any arguments are entry names restricting the
   queue.
2. Run `specthis check`. If there are no `audit needed` entries, say
   so and stop — nothing needs a mind. Otherwise tell the user the
   queue upfront: the entries to be judged, in order.
3. **Do not judge or vouch anything yourself.** Even if this session
   just wrote the code in question — *especially* then. Spawn a fresh
   `spec-critic` subagent **per entry, in parallel** (batch them in a
   single message so they run concurrently; cap a very large queue at
   ~4 in flight), each with:
   - the commissioning human's name, verbatim,
   - its single entry name,
   - the project root.
   Each critic re-reads the spec and code from disk with no memory of
   this session or of the other entries; do not summarize the code
   for it. One entry per critic keeps every judgment independently
   fresh, isolates it from its siblings' conclusions, and cuts the
   wall-clock wait. Concurrent `specthis vouch` writes are safe — the
   ledger serializes them.
4. **Relay progress as it happens.** As each critic returns, echo one
   line: the running tally (`3/7 judged — 2 vouched, 0 rejected,
   1 doubt`), the entry's verdict, and the critic's cost line (what
   it read and how long it took). The user must never face a silent
   multi-entry wait.
5. When the queue is done, relay the merged report unchanged: what
   was vouched, what was rejected, per-entry cost, and — most
   importantly — the doubts, which are now the human's queue. Finish
   with `specthis check` so the user sees the new frontier.
