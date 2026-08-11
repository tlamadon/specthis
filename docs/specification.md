# specthis — specification

**Status: 2026-08-11. Target system.** The implementable reference:
every artifact, schema, digest and rule. No rationale and no history —
those live in `design-notes-from-cakm.md` (why the format is what it
is), `attestation-model.md` (why claims work this way) and
`architecture.md` (why execution is delegated). Where this document and
those disagree, this one wins.

§16 is the migration path from v0.0.32.

Items marked **[NEW]** are settled in design but not yet implemented.

---

## 1. The two axes

The system holds four materials — **spec**, **code**, **pipeline**,
**bytes** — paired into two axes of the same shape. Each axis is a
contract beside the thing that fulfils it, with an actor attesting the
correspondence:

| Axis | Specification | Realization | Realized by | Verified by |
|---|---|---|---|---|
| **logic** | spec — prose and interface, written by the author | code **+ the pipeline step** | implementer | judge |
| **compute** | pipeline step — declarative | bytes | compute manager | compute manager |

**Realizing a spec means writing code *and* wiring it.** The prose
describes a transformation; the implementer makes it concrete as a script
*and* as a step feeding that script the right inputs. A judge reads both
— a step passing `wages_OLD.parquet` leaves the code perfect and the
realization wrong.

So a vouch pins the **step's semantic content** — command, deps, outs
(§5.6) — alongside the code. Scheduling concerns (resources, executor,
retries) are pinned by nothing and judged by nobody (§5.7).

The axis names what is at stake; the **capability** names who must be
re-invoked when a claim breaks — a **mind** on the logic axis, a
**machine** on the compute axis. Attestations (§8) and ledger files (§9)
use the second vocabulary.

The **map** (§4) sits between the axes and translates: the spec speaks
in logical names, the pipeline in paths and commands.

### The chain

A step lists its code among its dependencies, so the manifest records
those paths with their digests — and the vouch pins the same paths at the
same digests. The two attestations **join directly on `(path, sha)`**:

```
spec ──(vouch)── code ──(shared rows)── step ──(manifest)── bytes
```

So *"was this figure produced by code that satisfies its
specification?"* is answerable by composing the two ledgers. Where
`[package] globs` are used, a certificate (§6) carries the glob's
composed digest into the same chain.

**Source entries have no step**: leaf bytes arrive from outside any
pipeline, pinned by `record` and vouched for provenance (§2).

### Vocabulary

| Term | Meaning |
|---|---|
| **entry** | the unit of claim and of work; named by a repo-unique slug |
| **logical name** | what an entry produces, named abstractly (`wages-panel`) |
| **physical path** | where those bytes live (`data/wages.parquet`) |
| **actor** | a mind, a machine, or a human — anything holding a capability |
| **capability** | what an actor can do that the notary cannot: judge, or execute |
| **attestation** | a claim by an actor, pinning `{path: sha}`, with a verdict |
| **pinned tuple** | the digests an attestation covers |
| **recorded table** | the `{path: sha}` an attestation pinned (the past) |
| **implied table** | the `{path: sha}` the same subject resolves to now (the present) |

**The engine, once:** compare recorded against implied. Equal → the
claim stands. Different → its subject moved, and the table diff is the
explanation.

---

## 2. Entry types

Type is **inferred from fields**; lint enforces the legal combinations
and names the missing ingredient on failure.

| Type | Ingredients | Vouch attests | Pipeline step | Run claim |
|---|---|---|---|---|
| **source** | prose + `produces:` *physical path* | provenance — "this data is what it claims" | no | yes (pins bytes) |
| **library** | prose + bare `code` | "these functions meet their contract" | no | **no** — chain stops at code |
| **computable** | prose + `consumes` + `produces` (logical) | "this transformation is implemented correctly" | yes | yes |
| **template** | prose + `props` + interface | the template, or one instance (§15.4) | per instance | per instance |

*Templates are specified in §15. A singleton — a template with no props —
is the degenerate case, so nothing written today is rewritten.*

A **report** is not a type — it is a computable with several `produces`.

---

## 3. The spec format

A spec file is ordinary markdown. Five rules:

1. **Frontmatter is display metadata only** — `title`, `group`,
   `priority`. Nothing semantic. Excluded from every digest, so
   retitling never invalidates a claim.
2. **A heading whose section contains a `- key: value` field list
   declares an entry.** The heading text is the entry name: slug-like,
   unique repo-wide.
3. **An entry's block runs from its heading to the next heading of any
   level.** Everything inside is hashed into `block_sha`. Prose outside
   any entry is unsigned narrative.
4. **Recognized fields:** `consumes`, `produces`, `code`, `props`.
   Unknown keys are lint **errors**.
5. **Type is inferred** from the fields present (§2).

### Fields

| Field | Form | Notes |
|---|---|---|
| `consumes` | list of entry names | artefact flow; enters signatures; forms the DAG |
| `produces` | list of logical names | physical paths legal **only** in a source entry |
| `code` | bare key, no value | library marker |
| `props` | list of names | free variables; template tier (§15) |

### Example

```markdown
---
group: data
---

# Wage data

Opening prose is narrative: context for the reader, signed by no one.

### raw-wages

IPUMS extract #14, men 25–55. Education recoded upstream — see the
codebook oddity on `educ99`. Never re-download without bumping the
extract number here.

- produces: data/raw/wages.parquet

### wage-helpers

`winsor(x, p)` truncates symmetrically at percentile p, preserving NaN.

- code

### clean-wages

Drop negative wages, winsorize at the 99th percentile via `winsor`,
harmonize education. One row per worker-year; no duplicates.

- consumes: raw-wages
- produces: wages-panel
```

**No physical paths, no commands, no output locations** outside a source
entry. A refactor of your directory layout must never touch a contract.

---

## 4. The map — `specs/bindings.toml`

The map is the **translation layer between the spec's vocabulary and the
pipeline's**. It is **not a claim**: no verdict, no expiry, no signature.
Actor-writable.

The pipeline is authored by the implementer in the backend's own format
(§7), so everything about *how* a step runs — command, config, resources,
executor — lives there and **not** here. The map holds only the two facts
no pipeline format can express:

```toml
[package]
globs = ["src/**/*.py"]          # coarse net for unmapped code

[preview.".tex"]                 # dashboard rendering; not a claim
command = "latexmk -pdf {input} -o {out}"
format  = "pdf"
inputs  = ["paper/preamble.tex"]

[entries.clean-wages]
scripts  = ["src/clean_wages.py"]                   # which deps are judged code
produces = { wages-panel = "data/wages.parquet" }   # logical name -> physical path
declared_by = "implementer-agent"                   # [NEW] provenance
declared_at = "2026-08-11T09:14:02Z"                # [NEW]
```

| Field | Answers | On change |
|---|---|---|
| `scripts` | *which of this step's dependencies is judged code?* | unvouched *and* stale |
| `produces` | *which file **is** `wages-panel`?* | stales if a path moves |
| `[package] globs` | *what code is covered bluntly?* | unvouched, bluntly |
| `[preview]` | dashboard vocabulary | nothing |

**Why only these two.** Every pipeline format lumps code and data into
one dependency list (DVC's `deps`, scripthut's `inputs`), so nothing but
the map can say which dependencies are *judged* — and that boundary is
the boundary between the two axes. Likewise the pipeline says a step
writes `data/wages.parquet`; only the map says that file **is**
`wages-panel`, since physical paths never appear in a spec (§3).

`produces` keys must exactly match the entry's spec `produces` list, and
its values must exactly match the step's declared outputs (§13).

---

## 5. Digests

All digests are **sha256, lowercase hex**.

### 5.1 File digest
`file_sha(path)` = sha256 of the file's bytes. Missing file → the
sentinel `MISSING`.

### 5.2 Block digest
`block_sha(entry)` = sha256 of the entry's block text (§3 rule 3), UTF-8,
newlines normalised to `\n`, with frontmatter excluded.

### 5.3 Table
A **table** is `{path: sha}`, keys sorted bytewise.

### 5.4 Composition
```
compose(table) = sha256( "\n".join(f"{path}\0{sha}" for path,sha in sorted(table)) )
```
Deterministic, path-sensitive (so swapping two files' contents is
detected), and used only where a single opaque handle is required —
certificates and the package blob. **Tables are authoritative
everywhere a comparison is made**; composed digests are caches.

### 5.5 Package blob
`package_sha` = `compose` over every file matching `[package] globs`,
**excluding** files bound to a `library` entry — so a module edit flags
its own entry and its consumers, not the world.

### 5.6 Step digest
The **semantic content** of a pipeline step, as a single digest:

```
step_sha(step) = sha256( step.command + "\0" +
                         "\n".join(sorted(step.deps)) + "\0" +
                         "\n".join(sorted(step.outs)) )
```

Command, dependency **paths** (not their contents — those are separate
table rows), and output paths. Nothing else the step carries.

It appears in a pinned table as the pseudo-path `step:<entry>`, so both
axes see it: the judge is claiming about it (§8), and it enters the
currency table so specthis and the manager stay in agreement (§10.2 —
managers key on the command too).

### 5.7 What never enters a specthis digest
Display metadata (`title`, `group`, `priority`); **resources, executor,
retries, hooks** and every other scheduling concern a step carries;
timestamps and durations.

The rule: a digest covers what determines the *result*, never what
determines the *scheduling*. Resizing a job must not expire a judgment
or stale a run — which is also why scripthut and DVC exclude resources
from their cache keys.

**Arguments should still be files.** A command carrying `--winsor 0.99`
moves `step_sha`, so nothing is missed — but the break reports as
`step:clean-wages moved` instead of naming what changed. Lint warns
(§13); an attribution concern, not a correctness one.

---

## 6. Certificates **[NEW, optional]**

**Most projects need none.** A step lists its code among its
dependencies anyway, so those digests are already in the manager's key
and in the manifest. A certificate earns its place in exactly one case:
**`[package] globs`**, which has no stable file list and so can enter a
key only as a composed digest in a file.

One file per entry, generated by specthis into `specs/certificates/`.

```json
{
  "certificate_version": 1,
  "entry": "clean-wages",
  "code": { "src/clean_wages.py": "9f2c…" },
  "package": "b72a…"
}
```

**Rules:**

- **Keyed content is code identity only.** No verdict, no `spec_sha`, no
  timestamp. If any entered, vouching would trigger a rebuild and
  rewording prose would trigger a rebuild.
- **Serialization must be deterministic** — sorted keys, 2-space indent,
  trailing newline, no floats. Regenerating unchanged code must produce
  a byte-identical file, or every regeneration busts every cache.
- Where used, a **library** entry's certificate is the natural way for
  its consumers to depend on it without the library being a step (§7.5).

**Location:** generated, gitignored — reproducible from the repository,
and byte-identical on regeneration.

---

## 7. The pipeline

**Authored by the implementer**, in the backend's own format — a
`dvc.yaml`, a scripthut workflow document, whatever the chosen manager
reads. specthis **reads and verifies** it; it never writes it.

Generating it was rejected: pipelines churn, and a generator would put
specthis permanently between the implementer and every new capability
their backend grows.

### 7.1 What specthis reads from it

Exactly four things per step:

| Field | Meaning |
|---|---|
| `id` | the entry name — the shared vocabulary |
| `command` | what the step runs |
| `deps` | declared input paths |
| `outs` | declared output paths |
| `after` | which steps must precede it |

`command`, `deps` and `outs` together are the step's **semantic
content**, digested as `step:<entry>` (§5.6) and pinned by both axes.

**Everything else the backend supports is invisible and unrestricted** —
resources, matrices, hooks, retries, `foreach`. The
implementer uses their tool fully; specthis reads four fields and ignores
the rest. The only real requirement is that inputs and outputs be
*declared*, which any content-addressed manager needs anyway.

### 7.2 The adapter

Four operations per backend:

```
parse(pipeline_file)              -> [ {id, command, deps, outs, after} ]
submit(entries=None, force=False) -> handle
poll(handle)                      -> running | done | failed
manifests(handle)                 -> { entry: manifest }
```

- **`parse`** is a reader — cheap, and lenient about unknown fields.
- **`submit`** with no `entries` means *bring the whole pipeline up to
  date*. `entries` scopes it; `force` bypasses the cache, which is the
  integrity repair path (§10.3).
- **`poll`** exists only because runs can be long; a cluster job is not
  synchronous.
- **`manifests`** returns, per step, input hashes as used, output paths
  and hashes, and the exit code (§14, MUST 3).

Optional fifth: `probe(steps) -> {entry: hit | miss}`, answering **cost**
(§11). Never required for correctness.

A DVC adapter is `dvc.yaml` parsing, `dvc repro`, and reading
`dvc.lock`. A scripthut adapter is workflow-document parsing, a submit
call, and `run manifest`.

### 7.3 Which entries have steps

| Type | Step? | Why |
|---|---|---|
| computable | yes | one step |
| source | **no** | bytes arrive from outside; `record` pins them |
| library | **no** | no product of its own |
| template | one per instance | expanded by the pipeline (§15) |

Lint enforces this correspondence in both directions (§13).

### 7.4 How a step's dependencies are classified

specthis partitions each step's declared dependencies:

| A dependency that is… | is treated as | and on change |
|---|---|---|
| listed in `map.scripts` | **judged code** | unvouched **and** stale |
| an upstream entry's `map.produces` value | an **upstream artefact** | stale |
| anything else (config, data, certificates) | an **execution input** | stale |

The first row is why the map exists (§4).

### 7.5 Libraries

A library entry has no step. Consumers list its code among their own
dependencies — or, where `[package] globs` cover it, its certificate
(§6). Either route puts those paths in a consumer's step, so §7.4
applies unchanged.

### 7.6 Multi-output entries
Every logical name in `spec.produces` needs a `map.produces` entry whose
value appears among the step's declared outputs. Adoption records each
path separately.

---

## 8. Attestations

One envelope; the capability decides the pinned tuple.

```json
{
  "attestation_version": 1,
  "entry": "clean-wages",
  "capability": "mind",
  "pinned": { "spec:block": "c05d…", "step:clean-wages": "3a7e…",
              "src/clean_wages.py": "9f2c…", "package": "b72a…" },
  "verdict": "ok",
  "actor": { "id": "critic-agent", "kind": "agent" },
  "when": "2026-08-11T09:12:03Z",
  "evidence": { "note": "winsorization matches the 99th-percentile clause",
                "duration_seconds": 47.0 }
}
```

| Capability | `pinned` contains | `verdict` |
|---|---|---|
| `mind` | `spec:block`, `step:<entry>` (§5.6), every bound script, `package` | `ok` \| `rejected` |
| `machine` | `step:<entry>`, every step dependency, plus `out:<path>` per output | `ok` \| `failed` |

`step:<entry>` appears on both axes and is the only row they share
besides the code: a judge claims the wiring is right, a manager records
which wiring produced the bytes. A **source** entry has no step, so the
row is absent from both.

### 8.1 Acceptance

1. `attestation_version` is known, else reject.
2. Every path in `pinned` resolves to real content whose digest matches.
   Absent output bytes are permitted (§10.3); absent *inputs* are not.
3. Record. **The verdict is never inspected.**

### 8.2 Rejections
A `rejected` mind-attestation binds at exactly its pinned table. An `ok`
at a table carrying a standing rejection is refused; a digest must move,
or a *different* actor must lift it at a moved table. This is the one
policy rule in the notary, and it is deliberate.

### 8.3 Manifests → attestations
A compute manager emits a manifest (§14). `adopt` translates it:
`inputs` → pinned, `outputs` → `out:<path>` entries, `exit_code == 0` →
`verdict: ok`, executor → `actor`. Failed manifests are never adopted.

---

## 9. Ledgers

`specs/ledger/*.toml`, **globbed, never enumerated in code** — a third
capability lands a third file with its own lock and its own diff stream.
Today: `mind.toml`, `machine.toml`.

One table per entry, keyed by entry name. Latest claim wins; history is
git's job.

```toml
[clean-wages]
capability = "mind"
verdict    = "ok"
actor      = "critic-agent"
when       = "2026-08-11T09:12:03Z"
note       = "winsorization matches the 99th-percentile clause"
duration_seconds = 47.0

[clean-wages.pinned]
"spec:block"           = "c05d…"
"step:clean-wages"     = "3a7e…"
"src/clean_wages.py"   = "9f2c…"
"package"              = "b72a…"
```

```toml
[clean-wages]
capability = "machine"
verdict    = "ok"
actor      = "scripthut:hpc-cluster"
when       = "2026-08-11T09:20:11Z"
duration_seconds = 812.0

[clean-wages.pinned]
"step:clean-wages"           = "3a7e…"
"src/clean_wages.py"         = "9f2c…"
"config/clean.toml"          = "1ab4…"
"data/raw/wages.parquet"     = "77d0…"
"out:data/wages.parquet"     = "e51f…"
```

**Writes are serialized per file** (the file is the lock; non-POSIX
degrades to none). Optional fields are omitted, never null — TOML has no
null.

---

## 10. Derivation

`check` is a **pure function**: (specs, map, content, ledgers) → verdicts.
No cache, no daemon, no persisted status. Runnable at any moment, by
anyone, concurrently.

### 10.1 Certification
Implied table = `{spec:block}` ∪ `{step:<entry>}` (§5.6) ∪ code table ∪
`{package}`. Compare to the mind-attestation's `pinned`.

A **source** entry has no step row; a **library** entry has neither step
nor upstream.

| Condition | Certification |
|---|---|
| no `scripts` bound | `unimplemented` |
| no attestation | `unvouched` |
| tables differ | `unvouched` + table diff |
| verdict `rejected` | `rejected` |
| otherwise | `certified` |

**Expiry is judged on the table**, and `spec:block` is the *entry's
block*, not the file — editing a sibling entry must not expire this one.

### 10.2 Currency
Implied table = `{step:<entry>}` ∪ the step's declared dependencies
(§7.1) hashed now, where a non-local upstream artefact contributes the
upstream's **recorded** output digest (the claim, not the bytes).
Compare to the machine-attestation's input pins.

| Condition | Realization |
|---|---|
| library entry | *n/a* — chain stops at code |
| no attestation | `never-run` |
| tables differ | `stale` + table diff |
| otherwise | `current` |

### 10.3 Integrity
For each `out:<path>`, rehash the file.

| Condition | Result |
|---|---|
| absent | claim stands, **not materialized** |
| differs | `stale`, attributed `output edited on disk` |
| matches | intact, materialized |

*Absent bytes are not edited bytes.* The claim is about bytes, not about
this disk; they may be in the manager's store.

**Integrity is the one break a manager cannot see.** Its key is over
*inputs*, which a hand-edited output leaves untouched — so it reports a
cache hit and does nothing while the artefact no longer matches its
provenance. (DVC checks outs against `dvc.lock` and would catch it; a
purely input-keyed manager would not.) Repair is therefore
**specthis-initiated**: `run --force <entry>` (§12), submitting that
step with caching bypassed. It is the only condition under which specthis
asks for *specific* work — currency is the manager's to decide (§14,
MUST 2).

### 10.4 Propagation
Both trees, independently. An entry whose own tables all match but whose
transitive upstream has a break is **`upstream-unverified`** on that
tree. Never attested by anyone; derived by walking `consumes`.

Cycles are an error.

---

## 11. Reporting

Per entry: **certification × realization × materialization**, plus
per-tree propagation. **No fused status word** — the flattened enum is
retired (§16).

`check` prints two queues and exits non-zero if either has a local
member:

```
definitions needing a mind:
  unvouched    fit-beta       code: +src/helpers.py
  rejected     fit-delta      standing rejection (critic-agent, 2026-08-02)

realizations needing a machine:
  stale        fig-gamma      moved: data/wages.parquet
  never-run    tab-two

waiting on upstream: 3 on minds, 1 on machines
certified 11/16 · current 12/16
```

Break attribution is always a **table diff**: `+path` added, `-path`
removed, `~path` content moved. Never "something moved".

`status <entry>` prints both tables side by side.

The one question `check` cannot answer offline is **cost** — restore or
real compute. That needs the manager's probe.

---

## 12. Verbs

| Verb | Does | Writes |
|---|---|---|
| `check` | derive; two queues; non-zero on local breaks | nothing |
| `status [entry]` | table / detail, both axes, both tables | nothing |
| `vouch <entry>` | file a mind-attestation | `ledger/mind.toml` |
| `lint` | spec ↔ map ↔ pipeline correspondence (§13) | nothing |
| `certify` | regenerate certificates, if `[package] globs` are used (§6) | `specs/certificates/` |
| `adopt <entry>` | verify a manifest, countersign | `ledger/machine.toml` |
| `record <entry>` | pin bytes for a manual edge or a source entry | `ledger/machine.toml` |
| `run --stale` | `submit()` the whole pipeline → `poll` → adopt | via `adopt` |
| `run --force <entry>` | `submit(entries, force=True)` — the integrity repair path (§10.3) | via `adopt` |
| `init` / `install` | scaffolding, agent templates | project files |
| `export` / `serve` | dashboard; `serve` live-reloads | html |
| `migrate` | v0.0.32 → this (§16) | specs, map, ledgers |

`run --stale` **never forks a compute process** and **never selects
steps**. It hands the manager the whole pipeline and adopts what comes
back; the manager decides what actually executes (§14, MUST 2).

specthis **never writes the pipeline** (§7).

---

## 13. Lint

Because the pipeline is authored rather than generated (§7), lint —
**not construction** — is what keeps the three artifacts corresponding.
It replaces a compiler, and must therefore be complete.

**Errors — within the spec:**

- unknown field key in an entry block
- entry name not unique repo-wide
- field combination matching no type (§2)
- physical path in `produces` outside a source entry
- `consumes` naming an unknown entry
- a cycle in `consumes`
- a logical name produced by two entries

**Errors — spec ↔ map:**

- `map.produces` keys not matching the entry's spec `produces` list
- a computable entry with no `scripts` bound *(reported as
  `unimplemented`, not a hard error)*

**Errors — spec ↔ pipeline:**

- a **computable** entry with no step of that id
- a step whose id matches no entry
- a step for a **source** or **library** entry *(those have no steps —
  §7.3)*
- a `consumes` edge with no corresponding dependency: `X`'s
  `map.produces` value absent from `Y`'s step `deps`, where
  `Y consumes X`
- a step `deps` entry naming another entry's output path with no
  matching `consumes` edge *(the pipeline builds an edge the contract
  does not declare)*

**Errors — map ↔ pipeline:**

- a `map.produces` value absent from that step's declared `outs`
- a `map.scripts` path absent from that step's declared `deps` — the
  code would be judged but not hashed by the manager, so an edit would
  expire the vouch without staling the run

**Warnings:**

- a step command carrying flags or arguments beyond file paths (§5.6) —
  parameters belong in a config file listed among `deps`. Nothing is
  missed either way (the flag moves `step:<entry>`), but the break
  reports as `step:clean-wages moved` instead of naming the file that
  changed
- a step `outs` path not named by any `map.produces` — produced but
  anonymous, so no downstream entry can consume it
- code matched by `[package] globs` but bound to no entry — covered
  bluntly by the blob, invisible per-entry
- an entry demanding independence whose vouch actor equals its
  implementer *(pending §17)*

---

## 14. The compute manager contract

**MUST:**

1. Honor declared dependency order; never start a step before its deps
   succeeded.
2. **Decide only on content** — content digests over declared inputs.
   No mtimes, no timestamp heuristics. Deciding *is* its job; deciding
   on the wrong evidence breaks the claims.
3. Emit a per-step manifest: input hashes **as used**, output paths +
   content hashes, exit code. Distinguish *not hashed* from *empty*.
4. Never reuse a failed result.
5. Make cache hits invisible — identical hashes on hit and miss.
6. Preserve entry ↔ step identity.
7. Land outputs where declared.

**SHOULD:** exclude resources from the cache key; offer a
side-effect-free probe; **support a per-step cache bypass** (the
integrity repair path, §10.3 — scripthut's `cache: false`, DVC's
`repro -f`); fail loudly on unverifiable inputs; avoid partial outputs;
keep logs addressable per step.

**MUST NOT:** write specthis's ledgers; edit the map.

**Needs to know nothing about** specs, prose, vouches, or judgment.

**Qualifying:** scripthut (`cache_scope: "inputs"`, `task probe`, local
backend, `manifest_version: 1` — all shipped); DVC; a reference runner.
**dud does not qualify** — no rebuild on command change.

---

## 15. Templates **[NEW]**

One spec entry, one map row, one code binding — and **N instances**, each
with its own bytes and its own run claim. This is how a parameter grid
stays flat in the artifacts you write by hand.

**Pipeline tools expand the instances** — DVC's `foreach`, scripthut's
dynamic task generation — and specthis reads the steps that result. It
performs no elaboration of its own. The instance set stays a function of
committed files, because the pipeline is one.

### 15.1 The spec

```markdown
### clean-wages

Drop negative wages, winsorize at the 99th percentile via `winsor`,
harmonize education. One row per worker-year; no duplicates. Applies to
any country panel carrying the standard column set.

- props: dataset
- consumes: raw-wages[dataset]
- produces: wages-panel[dataset]
```

`props` declares free variables. A bracketed prop name in `consumes`
binds **by name**: `raw-wages[dataset]` means *the `raw-wages` instance
sharing this instance's `dataset` value*.

### 15.2 The map

```toml
[entries.clean-wages]
scripts  = ["src/clean_wages.py"]
produces = { wages-panel = "data/{dataset}/wages.parquet" }
```

`{prop}` placeholders are substituted per instance. **`scripts` stays
concrete** — every instance runs the same code, which is what makes one
vouch able to cover the template.

### 15.3 Instance identity comes from the output path

specthis does **not** parse step ids, and imposes no naming convention on
the backend. A step declaring output `data/chile/wages.parquet` matches
the pattern `data/{dataset}/wages.parquet`, binding `dataset = chile`.
The instance is `clean-wages[dataset=chile]`.

This is why every prop must appear in every `produces` pattern (§15.6):
it makes the match total and instances non-colliding. It also means DVC's
`clean-wages@chile` and scripthut's generated task names work equally
well without configuration.

### 15.4 Ledgers

- **Machine ledger:** one row per instance, keyed
  `clean-wages[dataset=chile]`. Each instance produces different bytes.
- **Mind ledger:** keyed **either** `clean-wages` (covers the template,
  hence every instance) **or** `clean-wages[dataset=chile]` (covers one).

No field declares which — **the judge chooses by where the vouch is
filed.** Sign the template when the transformation is genuinely
data-agnostic; sign instances when it is not.

### 15.5 Derivation

For instance `I` of template `E`:

- **Certification** — satisfied by a matching vouch on `E` *or* on `I`.
  Both pin the same code table, since instances share code; only the
  ledger key differs. An instance vouch on `I` takes precedence when
  both exist.
- **Currency, integrity, propagation** — per instance, entirely
  ordinary. Instances are ordinary entries to everything downstream of
  §7.

### 15.6 Lint

**Errors:**

- a prop absent from some `produces` pattern — instances could collide,
  and §15.3 matching would be partial
- a bracketed name in `consumes` that is not a declared prop
- two template entries whose `produces` patterns can match the same path
- a `props` entry whose `scripts` contains a `{prop}` placeholder — code
  bindings are concrete

**Warnings:**

- a template with exactly one instance in the pipeline — a singleton is
  the degenerate case and costs nothing, but the rule of three applies
  before promoting

**Demotion:** when one instance needs different code, drop `props` and
give it its own entry and `scripts`.

---

## 16. Migration from v0.0.32

| v0.0.32 | Target | Mechanical? |
|---|---|---|
| `kind:` frontmatter | inferred from fields (§2) | yes |
| `tier:` frontmatter | dropped; cost is the pipeline's business | yes |
| file-level `consumes:` in frontmatter | per-entry `- consumes:` field | yes |
| `## Entry` / `### name` + `Output:` | `### name` + `- produces:` logical | **no** — needs a name per output |
| `Output: path` | `map.produces = { name = "path" }` | semi |
| `Export outputs:` | several `produces` | semi |
| `spec_sha` (file-level) deciding | `spec:block` deciding | yes |
| `code_sha` deciding | code **table** deciding | yes |
| `vouches.toml`, `runs.toml` | `ledger/mind.toml`, `ledger/machine.toml` | yes |
| `Run.output` comma-joined | `out:<path>` per output | yes |
| fused status enum | two coordinates (§11) | yes — vocabulary only |
| `map.run`, `map.workflows`, `map.executor` | the authored pipeline (§7) | **no** — write the pipeline |
| `[cache] url`, remote cache | the manager's store | drop |
| executor, dispatch, scheduler | the manager | delete |

The map **shrinks** rather than grows: `scripts` and `produces` survive,
everything else moves into the pipeline the implementer already wants to
write.

**Order that keeps the tool working throughout:**

1. **`spec:block` decides certification.** One-line change, removes a
   whole class of false expiry, needs no format change — the field is
   already recorded.
2. **Tables authoritative** on both axes; composed digests demoted.
3. **Retire the fused word.** Vocabulary only; do it before anything
   structural, because it is what makes the state readable.
4. **Ledger move + `out:<path>` outputs.** `migrate` rewrites in place.
5. **Format migration** — logical `produces`, `map.produces`, drop
   `kind`/`tier`. Needs human input: naming each output.
6. **Adopt an authored pipeline.** Write the `dvc.yaml` or scripthut
   workflow, move `run`/`workflows`/`executor` into it, and ship `lint`
   (§13) — which must land *with* this step, since it is what replaces
   the guarantees a generator would have given.
7. **The adapter** — `parse` / `submit` / `poll` / `manifests` (§7.2),
   scripthut first, then a reference runner.
8. **Delete** executor, dispatch, scheduler, remote cache, composed
   signature.

Steps 1–3 are pure wins available today and independent of delegation.
Step 6 is the one that cannot be half-done: an authored pipeline without
complete lint is strictly worse than today, because nothing checks that
the graph specthis reports is the graph that runs.

---

## 17. Open

- **Declaring independence** per entry — the field, and whether the lint
  is a warning or an error.
- **Append-only ledgers.** The case strengthens now that the machine
  ledger is an archive rather than a decision input; both ledgers would
  have to move together for "was this certified at the time" to work.
- **Certificate location** — gitignored is specified above; committed
  makes a clone self-describing without running specthis.
- **Source-entry ceremony** — `record` for a leaf pins bytes with no
  command; whether that reuses the machine capability or earns a third.
