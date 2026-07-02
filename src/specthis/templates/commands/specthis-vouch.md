---
description: Audit the audit-needed spec entries with a fresh spec-critic subagent, which vouches clear passes, rejects clear violations, and reports every doubt for you to judge.
---

The user ran `/specthis-vouch $ARGUMENTS` — an explicit commission to
hand the vouching pen to a fresh critic session.

1. **Commissioning name.** The first token of the arguments is the
   human's name; any remaining tokens are entry names restricting the
   queue. If no name was given, ask for it before doing anything —
   the critic refuses to vouch anonymously.
2. Run `specthis check`. If there are no `audit needed` entries, say
   so and stop — nothing needs a mind.
3. **Do not judge or vouch anything yourself.** Even if this session
   just wrote the code in question — *especially* then. Spawn the
   `spec-critic` subagent with:
   - the commissioning human's name, verbatim,
   - the entry list (from the arguments, or every `audit needed`
     entry),
   - the project root.
   The critic re-reads the specs and code from disk with no memory of
   this session; do not summarize the code for it.
4. Relay the critic's report to the user unchanged: what was vouched,
   what was rejected, and — most importantly — the doubts, which are
   now the human's queue. Finish with `specthis check` so the user
   sees the new frontier.
