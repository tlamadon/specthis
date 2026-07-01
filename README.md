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
| **Spec** | The source of truth. A clean, declarative description of what the pipeline should be — every step, its inputs, and the artifact it produces. Specs carry contracts, not results. |
| **Package** | Reusable library code the scripts import (models, loaders, helpers). |
| **Scripts** | The executable steps. One script per spec entry, turning inputs into an artifact. |
| **Outputs (artifacts)** | What the scripts produce — JSON, data files, `.tex`, tables, figures. They live next to the data, never inside the spec. |

**One invariant — the certificate.** specthis maintains a set of content
hashes proving that **spec ↔ code ↔ outputs are mutually in sync**. The
certificate is cheap to check (`specthis check`), and when it is broken
it tells you *exactly which node* broke. That is the whole point: a spec
is only trustworthy if you can certify that the code implements it and
the artifacts on disk came from that code.

### The DAG: two kinds of node

The pipeline is a dependency graph, and it has **two kinds of node**.
They are certified differently because they *are* different things — a
step that produces code is not a step that produces data.

```
   ┌──────────┐ produces ┌──────────────┐ feeds ┌──────────┐
   │  code    │─────────▶│   artifact   │──────▶│   code   │─── ...
   │  node    │          │     node     │       │   node   │
   └──────────┘          └──────────────┘       └──────────┘
   authorship cert        execution cert         authorship cert
```

1. **Code nodes — certified by authorship.** A script that must satisfy
   a spec. Certified when the code matches its contract: specthis hashes
   `(spec contract + script + package deps)`. If the spec's *contract*
   later changes — a new output schema, different columns, a new
   argument — the hash drifts and the node surfaces as **audit needed**:
   the code must be re-checked against the new spec before it can be
   trusted again. Code nodes are *authored*, not run.

2. **Artifact nodes — certified by execution.** A file produced by
   running a code node on its inputs. Certified by an **input
   signature** hash over `(producing code's hash + upstream artifact
   signatures + config)`. If the code or any upstream artifact changes,
   the signature changes and the artifact is known-**stale**. An
   artifact node is *fresh* only when the file on disk matches its
   recorded signature.

`specthis check` walks the DAG, re-derives every node's hash from the
working tree, compares against the lock in `specs/_lock.json`, and
reports **green** or the first broken node on each path.

### Two tiers of steps

Not every artifact node deserves the same treatment. specthis splits
them by cost:

- **Intensive steps** (a long fit, a big extract). Never rerun blindly.
  The input signature is the cache key: specthis first tries a
  **remote cache** (fetch the artifact instead of recomputing), and
  only falls back to a local rerun on a miss. After a fresh run it can
  push the artifact back so collaborators skip the compute entirely.
  The certificate ties each cached artifact to the exact inputs that
  produced it.

- **Quick steps** (an export, a table, a plot). Cheap enough to just
  rebuild. These are handled **Makefile-style**: reproduced on demand,
  driven by ordinary mtime dependencies, no remote cache required.

The dividing line is declared in the spec, so `specthis refresh` knows
which steps to fetch-or-compute and which to simply remake.

## The spec format in one paragraph

Every spec file under `specs/` carries YAML frontmatter (`name`,
`kind`, `depends_on`) and, for the executable kinds, one or more
`### entry` blocks. Each entry pins one node of the DAG: a `Script:`
(the code node), an `Output:` (the artifact node it produces), and a
`Status:`. `depends_on` wires the edges.

`Status:` is `script TBD` (the code does not yet satisfy the contract)
or `script ready` (it does, and a smoke-test passed). Whether a script
has *run* and whether its output *exists* are observable facts reported
by the audit — not part of the spec.

The current templates ship a **research/paper instantiation** of this
format (a `kind: compute` step producing JSON, a `kind: report` /
`figure` step exporting `.tex` figures and tables and routing them into
a host document). That is one concrete domain, not the only one — the
certificate / DAG model is domain-general, and generic (non-LaTeX)
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

- **`spec-auditor`** — read-only consistency check: does each entry's
  code satisfy its contract, and is each artifact fresh?
- **`spec-implementer`** — author (and certify) a script for a
  `script TBD` entry.
- **`experiment-runner`** — launch a long intensive run in the
  background, watch its log for milestones / errors, report completion.

## CLI

```
specthis install    Copy the subagent templates into <cwd>/.claude/agents/
specthis init       Create specs/ skeleton (README.md + AGENTS.md)
specthis audit      Report per-entry code + artifact state (stub — port pending)
specthis check      Verify the certificate: re-derive hashes, report drift (planned)
specthis lock       Record / inspect the content-hash certificate (stub — port pending)
specthis refresh    Fetch-or-compute intensive steps, remake quick steps (stub — port pending)
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
5. **`specthis lock` / `specthis check`** — the content-hash
   certificate: record, verify, and report which node drifted.
6. **`specthis refresh`** — the two-tier orchestrator (remote-cached
   intensive steps, Makefile-style quick steps).
7. **`specthis cache`** — the remote (S3) cache backend.

Every module ships a config-driven surface (paths set via
`specthis.toml`), with no hard-coded assumptions about the host
project's layout beyond the documented defaults.

## License

MIT — see [LICENSE](LICENSE).
</content>
</invoke>
