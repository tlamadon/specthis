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
| **Spec** | The source of truth. A clean, declarative description of what the pipeline should be — every step, its inputs, and the artifact it produces. Specs carry contracts, not results, and never record *whether* or *where* they are implemented. |
| **Package** | Reusable library code the scripts import (models, loaders, helpers). |
| **Scripts** | The executable code that implements a spec, turning inputs into an artifact. |
| **Outputs (artifacts)** | What the scripts produce — JSON, data files, `.tex`, tables, figures. They live next to the data, never inside the spec. |

**One invariant — the certificate.** specthis maintains a set of content
hashes proving that **spec ↔ code ↔ outputs are mutually in sync**. The
certificate is cheap to check (`specthis check`), and when it is broken
it tells you *exactly which node* broke. That is the whole point: a spec
is only trustworthy if you can certify that some code implements it and
the artifacts on disk came from that code.

### The DAG: three kinds of node

The pipeline is a dependency graph with **three kinds of node**. The
split matters because a description, its implementation, and its output
are three different things — and only one of them (the spec) is
hand-written and stable.

```
   ┌──────────┐         ┌──────────────────┐          ┌──────────┐
   │   spec   │──impl──▶ │  implementation  │──produces─▶│ artifact │──feeds──▶ ...
   │  node    │         │  node            │          │   node   │
   └──────────┘         └──────────────────┘          └──────────┘
   contract              authorship cert               execution cert
   specs/*.md            lock/index                    lock/index
```

1. **Spec nodes — the contract.** A hand-written entry under `specs/`.
   It describes *what* a step must do and *what artifact* it produces
   (path + schema), and it wires the DAG via `depends_on`. It says
   **nothing** about whether that step is implemented yet or where the
   code lives — those are facts about the repo, not the contract.

2. **Implementation nodes — certified by authorship.** The binding
   between a spec and the code that satisfies it (a script plus the
   package modules it depends on). Certified by an authorship hash over
   `(spec contract + script + package deps)`. This node — not the spec —
   records the implementing path and its status; it lives in the
   lock/index and is registered when the code is certified (see
   [The certificate lives in the index](#the-certificate-lives-in-the-index)).
   If the spec's *contract* later changes, the hash drifts and the node
   surfaces as **audit needed**: the code must be re-checked against the
   new contract. Implementation nodes are *authored*, not run.

3. **Artifact nodes — certified by execution.** A file produced by
   running an implementation on its inputs. Certified by an **input
   signature** hash over `(implementation hash + upstream artifact
   signatures + config)`. If the code or any upstream artifact changes,
   the signature changes and the artifact is known-**stale**. An
   artifact node is *fresh* only when the file on disk matches its
   recorded signature.

The certificate is simply that every **edge** carries a verified hash:
`spec → implementation` (authorship) and `implementation → artifact`
(execution). `specthis check` walks the DAG, re-derives each edge's hash
from the working tree, compares against the lock, and reports **green**
or the first broken edge on each path.

### The certificate lives in the index

The spec is the only hand-written, stable part. Everything about the
*current state* of the repo — which specs are implemented, where the
code lives, whether each artifact is fresh — is derived and recorded in
generated side files under `specs/`:

- **`_index.json`** — the materialised DAG: every spec node, its
  registered implementation node (path + status), and its artifact
  node(s), joined against the working tree.
- **`_lock.json`** — the certificate: the authorship and execution
  hashes recorded at the moment each node was certified.

An implementation node is **registered at certify time**: when the code
is authored and spot-checked (by hand or by the `spec-implementer`
subagent), `specthis lock record <spec>` writes the spec→code binding,
its status, and its authorship hash into the lock. A naming convention
supplies the default code path, but the binding is explicit, so a spec
can be re-implemented elsewhere without touching the spec itself.

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
`### entry` blocks. Each entry is a **spec node**: it declares the
contract (what the step must do) and the `Output:` it promises (the
artifact node's path + schema, the interface downstream steps depend
on). `depends_on` wires the edges.

An entry does **not** carry `Script:` or `Status:`. Where the code lives
and whether it satisfies the contract are properties of the
*implementation node*, recorded in `specs/_index.json` /
`specs/_lock.json` and reported by the audit — never written into the
spec by hand.

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

- **`spec-auditor`** — read-only consistency check: is each spec
  implemented, does the code satisfy its contract, and is each artifact
  fresh?
- **`spec-implementer`** — author the code for an unimplemented spec and
  register the implementation node (path + authorship hash) at certify
  time.
- **`experiment-runner`** — launch a long intensive run in the
  background, watch its log for milestones / errors, report completion.

## CLI

```
specthis install    Copy the subagent templates into <cwd>/.claude/agents/
specthis init       Create specs/ skeleton (README.md + AGENTS.md)
specthis audit      Report per-entry code + artifact state (stub — port pending)
specthis check      Verify the certificate: re-derive hashes, report drift (planned)
specthis lock       Register implementation nodes / inspect the certificate (stub — port pending)
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
