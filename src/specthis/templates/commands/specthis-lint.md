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
   - **consumes/references unknown targets** — usually a typo or a
     renamed entry; grep the specs for near-matches before asking.
3. Warn the user where a fix will move digests: editing a spec file
   returns its entries to *audit needed*, and adding/changing a
   binding does the same for that entry. That is correct behavior,
   not damage — say so plainly.
4. Never touch `vouches.toml` / `runs.toml`, never run
   `specthis vouch`, never run project scripts.
5. Re-run `specthis lint` until clean, then finish with
   `specthis check` so the user sees the frontier.
