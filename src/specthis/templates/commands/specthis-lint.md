---
description: Check the spec directory's grammar (frontmatter, entry blocks, bindings, edges), explain every problem, and fix the mechanical ones.
---

The user ran `/specthis-lint $ARGUMENTS` — make the spec directory
parse cleanly. This is author's-pen work: you may edit `specs/*.md`
and `specs/bindings.toml`, and nothing else.

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
3. Warn the user where a fix will move digests: editing a spec file
   returns its entries to *unvouched*, and adding/changing a
   binding does the same for that entry. That is correct behavior,
   not damage — say so plainly. (The one exception: `[preview]`
   stanzas are dashboard-only and move no digest.)
4. Never touch `vouches.toml` / `runs.toml`, never run
   `specthis vouch`, never run project scripts.
5. Re-run `specthis lint` until clean, then finish with
   `specthis check` so the user sees both queues.
