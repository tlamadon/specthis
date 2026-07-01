# specthis

A spec-driven coding pipeline. You describe *what the pipeline should
be* in a clean set of specs; specthis keeps the code and the outputs
provably in sync with that description, caches the expensive steps, and
reproduces the cheap ones on demand.

> Status: **early scaffold**. The CLI shell and the agent / spec
> templates work. The dashboard renderer, lock manager, remote cache,
> and refresh orchestrator are stubs awaiting porting from the
> reference implementation. See [Roadmap](#roadmap).

## Philosophy

A specthis project has four parts and one invariant.

**Four parts:**

| Part | What it is |
|---|---|
| **Spec** | The source of truth. A clean, declarative description of what the pipeline should be — every transformation, its inputs, and the artifact it produces. Specs carry contracts, not results, and never record *whether* or *where* they are implemented. |
| **Package** | Reusable library code the scripts import (models, loaders, helpers). |
| **Scripts** | The executable code that implements a spec, turning inputs into an artifact. |
| **Outputs (artifacts)** | What the scripts produce — JSON, data files, `.tex`, tables, figures. They live next to the data, never inside the spec. |

**One invariant — the certificate.** specthis maintains a set of content
hashes proving that **spec ↔ code ↔ outputs are mutually in sync**. The
pipeline is a **chain of custody** from source data through
transformations to final artifacts, and the certificate is a chain of
**links** — one verified hash per link. It is cheap to check
(`specthis check`), and when it is broken it names the **first broken
link**. A certificate is only as strong as its weakest link; that is the
whole point.

### Nodes and links

The DAG has three kinds of **node** — the actual things — and links
between them. A node is a description, a file of code, or a file of
output. A **link** is a single certified edge between two nodes.

```
   spec ──implements──▶ code ──produces──▶ artifact ──▶ (feeds next code) ...
    │                    ╲ may stop here: library code, no artifact
    └──provides──▶ artifact          source data: no code, hashed directly
```

**Nodes:** `spec` (a hand-written contract), `code` (a script or module
that implements a spec), `artifact` (an output file).

**Links — each carries exactly one certificate hash:**

1. **implements** — `spec → code`. An **authorship hash** over
   `(spec + code)` (the code plus what it imports). Certifies that the
   code is a faithful implementation of the spec. If the spec's contract
   or the code changes, the hash drifts and the link is **broken →
   audit needed**. A spec with no `implements` link is **unimplemented**.

2. **produces** — `code → artifact`. An **input signature** over
   `(code + upstream artifacts + config)`. Certifies that the artifact
   was produced by this code from these inputs. If the code or any
   upstream artifact changes, the signature changes and the artifact is
   **stale**. A link that *stops at code* (no `produces`) is library
   code that emits no output — perfectly valid.

3. **provides** — `spec → artifact`. A **content hash** of the artifact
   itself, for **source / external data that no code produces** (a
   hand-dropped dataset, a download). No `code` node to hash, so the
   artifact is certified directly against its spec.

You never need a separate `spec → artifact` certificate for *derived*
data: `implements` ∘ `produces` composes to "this artifact satisfies
this spec." `specthis check` walks the chain, re-derives each link's
hash from the working tree, compares against the lock, and reports
**green** or the first broken link on each path.

### The certificate lives in the index

The spec is the only hand-written, stable part. Everything about the
*current state* of the repo — which specs are implemented, where the
code lives, whether each artifact is fresh — is derived and recorded in
generated side files under `specs/`:

- **`_index.json`** — the materialised DAG: every node and link, joined
  against the working tree (code path + existence, artifact freshness,
  each spec's derived status).
- **`_lock.json`** — the certificate: the authorship / input-signature /
  content hash recorded for each link at the moment it was certified.

The `implements` link is **registered at certify time**: when the code
is authored and spot-checked (by hand or by the `spec-implementer`
subagent), `specthis lock record <spec>` writes the spec→code binding
and its authorship hash into the lock. A naming convention supplies the
default code path, but the binding is explicit, so a spec can be
re-implemented elsewhere without touching the spec itself. The `produces`
link's input signature is stamped when the artifact is built by
`specthis refresh`; `provides` links are registered for source inputs.

### Two tiers of links

Not every `produces` link deserves the same treatment. specthis splits
them by cost:

- **Intensive links** (a long fit, a big extract). Never rerun blindly.
  The input signature is the cache key: specthis first tries a
  **remote cache** (fetch the artifact instead of recomputing), and
  only falls back to a local rerun on a miss. After a fresh run it can
  push the artifact back so collaborators skip the compute entirely.
  The certificate ties each cached artifact to the exact inputs that
  produced it.

- **Quick links** (an export, a table, a plot). Cheap enough to just
  rebuild. These are handled **Makefile-style**: reproduced on demand,
  driven by ordinary mtime dependencies, no remote cache required.

The dividing line is declared in the spec, so `specthis refresh` knows
which links to fetch-or-compute and which to simply remake.

## The spec format in one paragraph

Every spec file under `specs/` carries YAML frontmatter (`name`,
`kind`, `depends_on`) and, for the executable kinds, one or more
`### entry` blocks. Each entry is a **spec node**: it declares the
contract (what the code must do) and the `Output:` it promises (the
artifact's path + schema, the interface downstream links depend on).
`depends_on` wires the dependency edges.

An entry does **not** carry `Script:` or `Status:`. Where the code lives
and whether it satisfies the contract are the `implements` link,
recorded in `specs/_index.json` / `specs/_lock.json` and reported by the
audit — never written into the spec by hand.

The current templates ship a **research/paper instantiation** of this
format (a `kind: compute` link producing JSON, a `kind: report` /
`figure` link exporting `.tex` figures and tables and routing them into
a host document). That is one concrete domain, not the only one — the
certificate / chain model is domain-general, and generic (non-LaTeX)
templates are planned. See
[`src/specthis/templates/specs/README.md`](src/specthis/templates/specs/README.md)
for the full convention as it stands today.

## Install

```bash
pip install specthis          # core: CLI + agent templates
pip install "specthis[s3]"    # adds the remote (S3) cache backend
```

## Scaffold a project

In any project directory:

```bash
specthis install    # writes the Claude Code subagents into .claude/agents/
specthis init       # creates specs/ with README.md + AGENTS.md templates
```

After `init`, edit `specs/README.md` and add your first spec entry.

Three Claude Code subagents cover the daily operations on a spec
directory:

- **`spec-auditor`** — read-only consistency check: is each spec
  implemented, does the code satisfy its contract, and is each artifact
  fresh?
- **`spec-implementer`** — author the code for an unimplemented spec and
  register the `implements` link (path + authorship hash) at certify
  time.
- **`experiment-runner`** — launch a long intensive run in the
  background, watch its log for milestones / errors, report completion.

## CLI

```
specthis install    Copy the subagent templates into <cwd>/.claude/agents/
specthis init       Create specs/ skeleton (README.md + AGENTS.md)
specthis audit      Report per-entry code + artifact state (stub — port pending)
specthis check      Verify the certificate: re-derive link hashes, report the broken link (planned)
specthis lock       Register links / inspect the certificate (stub — port pending)
specthis refresh    Fetch-or-compute intensive links, remake quick links (stub — port pending)
specthis serve      Serve the specs.html dashboard with live reload (stub — port pending)
```

## Roadmap

The reference implementation (a ~7000 LOC private codebase) is being
ported one module at a time. Order:

1. **agent templates + spec format docs** — done (this scaffold).
2. **`specthis install` / `specthis init`** — done.
3. **`specthis audit`** — the index-based consistency audit.
4. **`specthis serve`** — the HTML dashboard renderer +
   `_index.json` / `_routing.json` exporter.
5. **`specthis lock` / `specthis check`** — the chain-of-links
   certificate: record, verify, and report the broken link.
6. **`specthis refresh`** — the two-tier orchestrator (remote-cached
   intensive links, Makefile-style quick links).
7. **`specthis cache`** — the remote (S3) cache backend.

Every module ships a config-driven surface (paths set via
`specthis.toml`), with no hard-coded assumptions about the host
project's layout beyond the documented defaults.

## License

MIT — see [LICENSE](LICENSE).
</content>
</invoke>
