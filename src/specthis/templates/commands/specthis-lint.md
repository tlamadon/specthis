---
description: Check the spec directory's grammar (frontmatter, entry blocks, bindings, edges), explain every problem, and fix the mechanical ones.
---

The user ran `/specthis-lint $ARGUMENTS` — make the spec directory
parse cleanly. This is author's-pen work: you may edit `specs/*.md`
and `specs/bindings.toml`, and run `specthis certify <entry>` for a
lagging certificate — nothing else.

1. Run `specthis lint`. If it prints "specs are clean", say so and
   stop.
2. For each problem, explain in one line what the grammar wants, then
   fix the mechanical ones directly:
   - **library entry needs `scripts` in bindings.toml** — find the
     implementing module(s) (search the package for the names the
     spec's contract uses); add the `[entries.<name>]` stanza. If more
     than one module plausibly matches, ask the user rather than
     guess.
   - **`name:` does not match the filename stem** — fix the
     frontmatter.
   - **retired `depends_on:`** — split into `consumes:` (upstream
     entry names whose artifacts the code reads) and `references:`
     (vocabulary spec files); when a target is ambiguous, ask.
   - **library entry declares an output** — either drop the `Output:`
     line (it is judged code, not a deliverable) or, if it really
     produces an artifact, tell the user it belongs in a compute spec
     instead and ask.
   - **unknown kind / tier, missing frontmatter, missing `Output:`** —
     fix per `specs/README.md`.
   - **`[preview]` problems** (key without a leading dot, command
     missing `{out}`, unknown `format`, unknown keys) — mechanical;
     fix per the Previews section of `specs/README.md`. The command
     must place its artifact at `{out}`; keys are output suffixes
     like `".tex"`.
   - **consumes/references unknown targets** — usually a typo or a
     renamed entry; grep the specs for near-matches before asking.
   - **state leak (`Script:` / `Status:` / `depends_on:` in a body)** —
     delete the line: status is derived, scripts live in
     bindings.toml. If it carried real information (a binding, an
     edge), move it where it belongs first.
   - **consumes draft entry** — the upstream contract is unchecked
     prose; either finish that spec (drop its `draft:` flag) or
     unwire the edge. Do not silently draft the consumer too.
   - **`appears` beside `produces` / `code` / `props`** — an exhibit
     prints a result and makes none. Give the result its own entry (it
     produces), and leave the exhibit consuming it; drop the conflicting
     field from the exhibit.
   - **`appears` is not `<document>#<label>`** — fix the syntax:
     `- appears: paper#tab:paths`.
   - **appears in undeclared document** — add `[documents.<name>]
     path = "<file>"` to `specs/bindings.toml`. If the spec wrote a
     path (`paper/paper.tex#…`), replace it with the name: a contract
     names the document, never its path.
   - **consumes exhibit** — an exhibit is terminal; unwire the edge
     (consume what the exhibit consumes, if that was the intent).
   - **an exhibit bound in bindings.toml** — delete its
     `[entries.<exhibit>]` stanza: it has no code and produces nothing.
   - **a label defined twice / sitting in no environment, or a
     malformed `specthis:begin`/`end` marker** — these live in the
     manuscript, which is the authors' text, not your pen. Report the
     `file:line` and the fix (rename the duplicate label; wrap
     unenclosed prose in a marker pair, each marker on its own line)
     and ask before touching the document.
   - **certificate lags its code** — run `specthis certify <entry>` for
     the entry named. A certificate is derived state, so regenerating it
     is always correct — and it stales every step that depends on it,
     which is the point: those runs were blind to the code edit.
   And act on the warnings — they are advisory, not optional noise:
   - **references target never mentioned in the body** — drop the
     edge, or add the sentence that uses it.
   - **link resolves to nothing** — fix the target or delete the link.
   - **mentions a path nothing produces / an entry that doesn't
     exist ("did you mean")** — usually a rename the prose missed;
     update the mention, or wire the thing it names if it should
     exist.
   - **compute entry outputs under `reports/`** — the artefact belongs
     to the paired report spec; propose the move.
   - **report entries but no `## Artefact design`** — author the
     section (what the artefact looks like is part of the contract).
   - **spec is draft** — fine while genuinely half-written; flag to
     the user if it has clearly outgrown the flag.
   - **label claimed by no exhibit (an orphan)** — a result the
     manuscript prints that nothing in the graph backs. Report every
     one. Never quiet one by adding it to `unbacked` yourself: declaring
     a result needs no backing is the human's decision. If its producer
     is evident, propose the exhibit (`- consumes:` that entry,
     `- appears:` the label).
   - **`unbacked` lists a label the document does not define, or one
     an exhibit claims** — delete it from the list (mechanical).
   - **no file at a document's `path`** — fix the `path` if the
     manuscript moved; otherwise report it.
3. Warn the user where a fix will move digests: editing a spec file
   returns its entries to *unvouched*, and adding/changing a
   binding does the same for that entry. That is correct behavior,
   not damage — say so plainly. (The exceptions: `[preview]` stanzas
   are dashboard-only, and a `[documents]` stanza's `environments` and
   `unbacked` only configure lint — neither moves a digest. Its `path`
   moves an exhibit's digest only where the span reads differently.)
4. Never touch `vouches.toml` / `runs.toml`, never run
   `specthis vouch`, never run project scripts, never edit the
   manuscript without asking.
5. Re-run `specthis lint` until clean, then finish with
   `specthis check` so the user sees both queues.
