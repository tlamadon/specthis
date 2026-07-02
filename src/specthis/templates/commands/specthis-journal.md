---
description: Write a dated journal entry into journal/ narrating what happened in this session — the decisions, the numbers, the dead ends — with links to the specs and entries involved.
---

The user ran `/specthis-journal $ARGUMENTS` — capture the current
session as a journal entry. A journal entry is narrative, not a
claim: it touches no ledger, needs no vouch, and the dashboard
(`specthis serve` / `specthis export`) picks it up automatically from
the `journal/` directory. Any arguments are a topic hint or an
explicit slug.

1. **Filename.** `journal/YYYY-MM-DD-<slug>.md`, date from `date +%F`,
   slug from the arguments if given, else 3–6 kebab-case words naming
   the session's focus (e.g. `smc-ffbs-resampling-fix`). Create
   `journal/` if it does not exist. If the filename is taken, extend
   the slug rather than overwriting — never clobber an existing entry.
2. **Content.** Start with a `# Title` heading (becomes the card
   title on the dashboard), then narrate from the session context:
   - what was attempted and why — the question, not just the diff;
   - what was decided, including alternatives rejected and the reason;
   - concrete results: numbers, table snippets, error messages that
     mattered;
   - dead ends worth remembering, so nobody walks them twice.
   Write for the reader six months out who has only this file. Do not
   pad: a short honest entry beats a long generated one.
3. **Cross-link.** Link the specs and entries involved by relative
   markdown path (e.g. `[compute-alpha](../specs/compute-alpha.md)`)
   and sibling journal entries by filename — the dashboard rewrites
   these into hash-routed links. If the session produced a small
   shareable artefact tied to the narrative (a JSON bundle, a
   figure), it may be committed next to the entry in `journal/` and
   linked; big or regenerable outputs stay in the results directory.
4. **Report.** Show the user the path and title, and remind them the
   entry appears under "Journal" on the dashboard. If something in
   the session was a claim about spec/code (not narrative), say so —
   that belongs to `/specthis-vouch` or `specthis run`, not the
   journal.
