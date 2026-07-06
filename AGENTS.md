# AGENTS.md — developing specthis

For any agent (or human) working on the specthis codebase itself.
Not to be confused with
[`src/specthis/templates/specs/AGENTS.md`](src/specthis/templates/specs/AGENTS.md),
which is the operations manual `specthis init` ships *into* user
projects.

## The one rule: the agent interface ships with the code

specthis's users include agents. `specthis install` / `init` drop
subagents, slash commands, and an operations manual into every
project, and those documents describe how the tool behaves — which
makes them part of the product surface, not documentation that can
catch up later. **A feature is not done until every surface that
describes the changed behavior says the new truth.** Update them in
the same change as the code:

| surface | describes |
|---|---|
| `README.md` | the tool, for humans browsing the repo |
| `src/specthis/templates/specs/README.md` | the spec-directory convention: grammar, frontmatter, `bindings.toml` vocabulary (including `[package]`, `[cache]`, `[preview]`) |
| `src/specthis/templates/specs/AGENTS.md` | the operations manual every project agent reads first: the model, the statuses, the four operations, the boundaries |
| `src/specthis/templates/agents/*.md` | the four subagents: auditor, implementer, experiment-runner, critic |
| `src/specthis/templates/commands/*.md` | the slash commands: `/specthis-vouch`, `/specthis-run`, `/specthis-lint`, `/specthis-journal` |

The test per surface is: *does this change alter what the document
tells its reader to do or expect?* Some recurring mappings —

- a new or changed **grammar problem** → `/specthis-lint`'s problem
  list (it explains and fixes the mechanical ones);
- new **`bindings.toml` vocabulary** → the templates README, plus a
  note in AGENTS.md saying whether editing it moves digests (that
  distinction routes agent behavior);
- a new or changed **status / badge / check output** → AGENTS.md's
  model section and the auditor (it must neither re-derive nor
  misread the ledger);
- a new **verb or flag** an agent should reach for → the subagent or
  slash command that owns that operation.

Two supporting habits:

- **Pin load-bearing claims with tests.** When an agent doc asserts a
  ledger property ("a `[preview]` edit moves no digest", "bytes
  remote is not staleness"), add a test that fails if the code stops
  making it true — e.g. `test_preview_stanza_moves_no_digest`,
  which exists because three agent docs lean on it.
- **Remember templates are copied, not linked.** Projects pick up
  template changes only on the next `specthis install` / `init`.
  Behavior that *must* reach existing projects belongs in the tool,
  not the templates.
