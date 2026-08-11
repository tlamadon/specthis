# specthis — the two trees and the delegation of execution

**Status: 2026-07-20/21.** Companion to `design-notes-from-cakm.md` (the
cakm-evidence redesign). This document records the design conversation held
in the specthis repo itself: what **shipped** in v0.0.28–v0.0.32, what was
**designed but deliberately not built**, and the doctrine that emerged.
§12 maps agreements and open deltas against the cakm notes — the two
threads converged independently on the same core and differ on route.

---

## 1. Shipped: the two-tree model (v0.0.29–v0.0.32)

Status used to be one six-value enum. It is now **derived from two
independent coordinates** per entry:

- **Certification** (the vouch axis — the *definition*, a mind's tree):
  `unimplemented → unvouched → certified`, or `rejected`. A judgment about
  the (spec, code) pair, valid for any invocation, expiring only when a
  digest moves.
- **Realization** (the run axis — the *call*, a machine's tree):
  `never-run → stale → current`; `None` for library entries (their chain
  stops at code). `stale` is precisely a **memo miss**: the recorded call
  is not the call today's content implies.

**ready = certified ∧ current, whole lineage.** The legacy status word is
derived from the axes (certification breaks win) so every old surface
still reads; the axes carry the corners the single word could not say —
an entry can be `unvouched · stale` (both queues at once, repaired in
parallel) or `unvouched · current` (pure mind-work).

**Policy (chosen deliberately): mechanical.** Certification does not gate
compute. An unvouched entry rebuilds while a mind audits it; the one
certification state that stops a machine is `rejected` — a machine must
not realize a definition a mind refused.

Surfaces: `specthis check` prints two queues (*definitions needing a
mind*, *realizations needing a machine*) with waiting split by blocking
tree. The dashboard is **one page per tree** — Vouch tree (the landing:
trust state, attester, vouch date, judgment cost, moved-since-vouch,
above the DAG whose rails *and* dots speak the vouch axis) and Run tree
(run state, ran/via/took, byte locality, moved-since-run; libraries
absent) — plus an Activity log. Agent templates address their own queue
only.

## 2. The entry is the atom

The spec *file* is a document; the **entry** is what the system tracks.
Ledger rows, `consumes:` edges, statuses, queues — all keyed by entry
name. A file with three `###` blocks is three independently vouchable,
runnable, consumable claim units sharing one contract's prose. The file
remains the honesty boundary: `spec_sha` covers the whole file, so a
prose edit anywhere expires every entry in it, with block-level
attribution.

## 3. The state and its mirror

The state has two sides, and **the digest is the mirror**:

| world side (what is) | claim side (what named actors asserted) |
|---|---|
| `specs/*.md` — promises | `vouches.toml` — judgments, pinned to `(spec_sha, code_sha)` |
| code | `runs.toml` — execution reports, pinned to `signature(inputs) → output_sha` |
| `specs/bindings.toml` — **the map** | |

`bindings.toml` is state but **not a ledger**: it is a timeless
declaration ("these files produce this output"), hashed *into* claims
rather than pinned *by* digests. Editing it expires claims; it never
makes one. It needs no pen of its own because it is covered by the
critic's pen — a vouch certifies "this spec is satisfied by the code
*this binding names*"; lint validates it; git is its history. There are
deliberately only two claim verbs, because there are only two claims.

## 4. The actors — each provides a thing and files a claim about it

| actor | provides | files |
|---|---|---|
| spec author | contracts (promises + DAG) | the spec files themselves |
| implementer | code **and its map** | the binding: `scripts` (judged) + `workflows` (unjudged execution inputs) |
| runner (external: you, make, cluster, agent) | artifact bytes | the run report, via `specthis run` |
| critic (fresh, commissioned, named mind) | judgment | the vouch, via `specthis vouch` |
| the human | direction; rulings on doubts and rejections | — |

specthis makes nothing, runs nothing (after §5), judges nothing. It does
two things only: **notarize** (accept claims under discipline — one pen
per ledger, named attesters, the standing-rejection rule) and **derive**
(re-hash content, report which claims still hold, compose down the DAG).

## 5. Designed, not built: removing execution

**Decision in spirit; frozen pending demand.** specthis stops executing
recipes entirely (it was never good at owning CPUs, and the recipe never
entered any digest — removal changes zero ledger semantics).

- **`specthis run <entry>` becomes a pure record verb**, symmetric with
  `vouch`: build however you like, then record — inputs resolved and
  outputs digested at record time. Same trust level as `--adopt`,
  honestly labeled (`executor = "manual"` / external). *Discipline:
  build, then record immediately, in dependency order* — a delayed
  record pins today's inputs to yesterday's bytes (false provenance the
  derivation cannot catch). The cakm notes' adopt-manifest protocol is
  the stronger form of this verb (§12).
- **Recipes demote to hints.** A project-level entry point in bindings —
  `[build] command = "./build.sh {entry}"` — plus per-entry `run =` as
  override, printed next to stale entries, never executed.
- **`run --stale` execution, `-p N`, dispatch are deleted** (reverses
  v0.0.27's parallel feature, deliberately). Parallelism goes to `make
  -j` / the cluster / scripthut.
- **The machine queue prints in build order** (plus a porcelain
  `check --queue` for scripting).

### The planner/driver split

specthis remains the **planner**, never the **driver**. It is a passive
oracle — permanently `make -n`: it answers "what, whether, in which
order" completely, and initiates nothing. The driver is a trivial loop
that lives above (an agent, five lines of shell):

```
while machine queue non-empty:
    build <head-of-queue>      # runner: one atom, no questions
    specthis run <it>          # record immediately
    re-check                   # the queue can grow as bytes move
```

### The atom contract (the runner's whole obligation)

Given an entry name: **read inputs already in place, produce this
entry's outputs, unconditionally, and stop.**

- **No freshness opinions.** The runner is only ever invoked on entries
  the planner already declared stale; a delegate that consults mtimes
  (classic make) and no-ops causes false provenance — `.PHONY`, dumb
  scripts, build-every-time-asked.
- **No recursion.** A build script that rebuilds its own inputs is a
  second planner with a drifting graph, and worse: inputs rebuilt as a
  side effect are **unrecorded runs** — new bytes the ledger doesn't
  know, silently referenced downstream. Missing input ⇒ fail loudly
  (planner-order bug, or `bytes remote` ⇒ `cache fetch`).
- **Granularity caveat:** specthis's help stops at the entry boundary.
  An expensive intermediate *inside* one entry's build is invisible; if
  it deserves memoization, **promote it to an entry** and the planner
  plans around it.

### Who reads what: the specs never cross to the build side

The runner reads nothing (an entry name and a dispatch branch); the
record verb needs the *shape* of claims (edges, deliverables) — and
that shape crosses the boundary **compiled, never raw**. Specs carry
logical interfaces only (names and edges — what minds read);
everything physical lives in the implementation map (code, dispatch,
output locations, interim staging — the implementer's readable
pipeline description). specthis is the single program that parses
specs, compiling them into a derived **structure contract** (the cakm
notes' `specthis structure`: entries, edges, code manifests, stamped
with a `spec_state` hash — consumers verify the stamp and fail closed).
The build side — driver loops, scripted runners, adapters, record
intake — consumes structure + map, never markdown. Duplicating edges
into the map instead would be two sources of truth for one graph;
the split is logical/physical, not spec-side/build-side copies. The
shared vocabulary between the two sides is names, and nothing else.

### Reproduction, calibrated

The old per-entry `run =` lines *felt* like a reproduction guarantee but
were never hashed — notes wearing the costume of records. The new story
is stronger: rebuild-anything = *the entry point followed by the entry
name*, at any commit; the signature says exactly which content mattered;
and re-recording **verifies** reproduction (matching `output_sha`).
Outside the fence, as always: the environment (lockfiles in git are that
job).

## 6. Doctrine

- **Arguments are files.** Anything that affects output bytes must be a
  digested file — config bound via per-entry `workflows` — never an
  ephemeral flag. Load-bearing once execution is external. Declared
  sweeps (`Over:`) are the structured future of the same rule.
- **Build files are watched execution inputs.** `[build] watch = [...]`
  hashes them into every entry's signature — edits make entries
  **stale, not unvouched** (the `hut.*.json` pattern: execution input,
  not judged code). Per-entry fragments via `workflows` scope the blast.
- **Blast radius = the honesty of the implementer's map**, on a
  three-position dial: per-entry `scripts` (fine) → `library` entry
  consumed by others (fine *and* judged) → the `[package]` blob (coarse
  safety net). A monolithic build file is either kept thin (a
  dispatcher; wide-but-rare invalidation) or split into bound fragments.
  Sound-but-noisy beats unsound-but-quiet; the escape valve for known
  false positives is a cheap re-record (an honest, named "this edit was
  irrelevant to these bytes").
- **Under-declaration is the residual risk**: code neither bound nor in
  the package globs is invisible. Guards: the package blob (mechanical,
  coarse) and the critic reading imports (judgmental, precise).
- **Parameters: file vs prose is a conscious choice.** In `workflows`,
  retuning is machine-work and the vouch stands; pinned in spec prose,
  changing it is a contract change and expires the vouch. Files decide
  what recomputes; prose decides what gets re-judged.
- **The templates ladder: specs promise, templates advise, libraries
  enforce.** `kind: templates` is ledger-invisible by design — enforced
  by minds at read time (the critic reads `references:`); a template
  edit invalidates nothing mechanically. When that softness stops being
  acceptable, promote the executable part to a `library` module and
  edits cascade.
- **Raw data as leaf entries.** A dataset is a compute entry that
  computes nothing: its run claim pins the bytes; its *vouch* is a mind
  attesting provenance. Downstream, an ordinary upstream. (Convergent
  with the cakm notes' Source type.)

## 7. Anatomy of a compute with inputs (the break matrix)

`gaps-main` binds `scripts = [gaps_main.py]`, `workflows =
[config/gaps.toml]`; its spec consumes `fit-alpha` and `data-lehd`. One
inputs table, one door per input kind — and each edit breaks exactly the
right claim:

| change | result | why |
|---|---|---|
| the bound script | `unvouched · stale` | judged code: both axes |
| `config/gaps.toml` | `stale` only | execution input, not judged |
| the spec prose | `unvouched` only | contract moved; bytes current |
| upstream re-runs, new bytes | `stale` | signature pinned the old bytes |
| new dataset bytes on disk | data entry stale → re-record + re-vouch → consumers stale | data flows like any upstream |

## 8. How the planner decides (the whole algorithm)

For each entry, build **the inputs table a run would pin right now**
and compare it to the one the recorded run did pin:

```
fit-beta, right now:
  scripts/fit_beta.py  = ab12…    ← hash the file on disk, now
  config/beta.toml     = 55aa…    ← workflows file, now
  package              = cd34…    ← package blob, now
  upstream:fit-alpha   = 9f2c…    ← NOT disk: runs.toml's recorded
                                    output_sha — planning reads claims
```

- no row → `never-run`; tables equal → `current` (plus one disk check:
  outputs present-but-different → `stale, output edited`; absent →
  current, `bytes remote`); tables differ → `stale`, and **the diff of
  the two tables is the `moved:` explanation** — nothing inferred.
- The queue = the mismatches, topo-sorted. The loop is *build head →
  record → re-ask*, because recording new upstream bytes changes
  downstream tables — the cascade grows, or stops dead when a rebuild
  reproduces identical bytes.

**Cold start is the degenerate case, not a special one.** No rows
anywhere → everything `never-run` → the queue is the whole DAG in topo
order. Unrecorded upstream lines carry a `MISSING` sentinel, so every
table is well-defined. The loop bootstraps itself: each atom creates the
next atom's input files; each record turns a `MISSING` into a digest.
Raw-data leaves start the chain (place the file, record it); an
`unimplemented` upstream surfaces as a loud downstream failure, never a
silent skip. Meanwhile the mind queue is also full, draining in
parallel. First-ever build and incremental rebuild are the same
algorithm run against different amounts of paper.

## 9. Beyond the specs: where else entries can come from

With the entry-materializing template tier (cakm notes §8), the entry
set is no longer written down — it is **derived by backward chaining
from the roots**. The planner gains one phase, *elaboration*, in front
of the comparison:

```
table-southern-cone (concrete root)
  consumes: wage-moments[dataset=chile]
      ↑ nothing concrete produces it; a template's parameterized
        produces unifies (?d = chile) → INSTANTIATE
          its consumes demand wages-panel[dataset=chile] → instantiate
            clean-wages[dataset=chile] → grounds out at a concrete
            source entry.
```

Demand walks **rootward-up** (make's `%` pattern rules); the elaborated
DAG then builds **top-down** exactly as in §8 — instances like
`clean-wages[dataset=chile]` are ordinary entries in every way: ledger
keys, `arg:dataset = "chile"` as a signature input line, `never-run` at
cold start, one atom each for the runner. Elaboration only changes
*where the entry list comes from*; the comparison engine is untouched.

Commitments that keep it sound: **no registry, ever** (the instance set
is a function of committed spec files — demand *is* the registry;
un-demanded instances vanish from the derived DAG, their ledger rows
going dormant); **the value choice is signed where it is used** (the
root's prose says "we compare Chile and Argentina" — where a referee
asks); **one vouch covers the template**, not the instances — the
ceremony win and also the reason for deferral: a template vouch is a
universally quantified claim, the strongest thing a mind can be asked
to sign. Trigger: cakm's second real dataset, written by hand first
*as if* templated.

### Matrices as data: prose leads, structure carries

Parameter grids will be *conceived* in prose ("all samples × both
periods, except stayers late — identification"), and prose must be
able to lead. But **prose is the origin of structure, never its
carrier**: the matrix itself is a committed data file, named from a
structured field and hashed like any input —

```markdown
Over: `design/gaps-matrix.toml`
Output: `results/gaps/{sample}-{period}/fit.json`
```

with the file enumerating axes and exclusions. Elaboration expands it
deterministically; editing it moves digests, staling exactly the
changed cells; and it stays inside the invariant (*the instance set is
a function of committed files*). An interpreting parser is ruled out
on three counts: rewording must never rewire the pipeline; the ground
truth must not be hallucinable; ambiguity must fail loudly, and only
grammars can refuse. The translation prose → matrix is done **at
write time by minds** (you, or an authoring agent), and the
**critic verifies prose and matrix agree** — meaning is read where
reading meaning is already the job, and its output is a signed
opinion, never a graph edge. Generated grids: the generator is itself
an entry whose *output* is the matrix file — elaboration then consumes
recorded bytes.

### Interim entries: the implementer's refinement (sketch, unbuilt)

The dual front-end: where templates derive nodes from *author-side
demand*, **interim entries** are declared by the *implementer*, in
bindings — build-graph nodes beneath the contract surface:

```toml
[interim.prep-lehd]
scripts  = ["scripts/prep.py"]
consumes = ["data-lehd"]
output   = "cache/lehd-clean.parquet"
```

They live on the **run tree only**: full inputs table, signature, run
rows, staleness, machine-queue membership — memoization for expensive
intermediates shared across spec entries, without forcing the author's
voice onto plumbing. They have no vouch axis, but **judgment folds
upward**: an interim's scripts enter every consuming spec entry's
`code_sha`, so the critic reads them and an edit expires the consumers'
vouches — no unjudged compute, and attestation still scales with
contracts, not plumbing. (Symmetry: `library` is judged code with no
bytes; interim is bytes with no own judgment; the ordinary entry has
both.)

The constitution adjusts by one sentence: *specs declare the contract
pipeline; bindings may refine the build graph beneath it.* The
author's graph remains the only one referees and vouches see. Lint:
one namespace across both tiers, no cycles in the merged graph, no
orphan interims, no interim outputs under contract territory
(`results/`, `reports/`). The placement test is the **referee test**:
if a reviewer would ever ask about a step, it is a contract and
belongs in a spec; if only the machine cares, it is interim. Passes
the §15 budget: a second node source, zero new engine.

## 10. When is anything *done*?

Two rules; everything else is these rules meeting the DAG:

1. A claim breaks when content under it moves.
2. **done = ready = both claims hold here and everywhere upstream** —
   derived on demand, never stored, never sticky.

The two trees repair independently and in parallel; machines walk the
DAG top-down through stale entries regardless of vouch state (rejected
excepted); minds work the unvouched list in any order. They meet only in
the conjunction.

## 11. The "how" symmetry

Both claims have a *what* (named by the shared map + the spec) and a
*how* that lives **nowhere in state**: the critic's judgment procedure,
and the builder's recipe. Principled, not an omission — a
content-addressed system knows procedures only through their effects on
content. The critic's method cannot change the bytes judged (guarded
socially: fresh session, named attester, doubt discipline). The
builder's method *can* — and any part of it that does must first be
reified as a bound file, at which point it has become a *what*. The old
`run =` line was the one "how" living unhashed inside the map of whats;
its removal restores the symmetry.

## 12. Relation to `design-notes-from-cakm.md`

**Independent convergence** (strong evidence the core is right): specthis
as notary; no gate in either direction (= the mechanical policy); the
fused status enum as the root disease; execution delegated out of
specthis; data sources as vouchable leaf entries; templates/sweeps
deferred behind a real trigger; status never persisted as truth
(this repo gitignores the rendered views).

**Open deltas — to reconcile before further building:**

1. **Route.** cakm notes: new pure-contract spec format (logical
   names, per-entry field lists, `produces:`), implementation map with
   command templating, builder *extracted and frozen*. This thread:
   current format kept, evolved incrementally; execution *removed*
   rather than extracted. Removal is the smaller step and compatible
   with later format work; the logical-names migration is the real
   fork (it touches every spec).
2. **Record vs adopt.** This thread's record verb trusts the recorder
   (adopt-grade, labeled). The cakm notes make manifest-verified adopt
   the *only* write path — structurally stronger against the Jul-8
   false-provenance incident. If both threads proceed, the record verb
   should take the manifest-verified form.
3. **The status word.** cakm notes prohibit any fused enum; this thread
   ships the axes but keeps the derived legacy word for compatibility.
   Retiring it is a vocabulary-only follow-up once surfaces are fully
   two-tree.
4. **Vouch-per-stem ceremony** (smoke/full = one judgment, 51/51
   evidence) is designed in the cakm notes and untouched here; it
   composes cleanly with the two-tree model (it is a vouch-axis
   ceremony rule).

## 13. The five invariants

1. Claims pin **content digests** — never mtimes, commands, or memory.
2. What isn't a **declared file** doesn't exist — arguments are files.
3. Actors draw the maps; specthis enforces their **consequences** —
   blast radius equals declared honesty, the package blob underneath.
4. Judgment attaches to **definitions** (survives re-runs); mechanics
   attach to **bytes** (survives nothing).
5. specthis is a **notary with a diff engine** — it makes nothing, runs
   nothing, judges nothing; everyone else makes things and files claims,
   and it only ever reports what the content still supports: needs a
   mind, needs a machine, or needs patience.

## 14. The scripthut split (from-scratch derivation, 2026-07-21)

Persistent unease about the specthis/scripthut boundary forced the
from-scratch question: what is needed, total? Four things — contracts
& judgment (specthis, unambiguously), change detection & planning
(specthis, pure), **execution** (scripthut's entire reason to exist,
half-reimplemented by specthis's light executor — the source of the
unease), and recording (notary intake of facts that originate at
execution time). The split falls out:

- **specthis**: everything mind-side + pure derivation. Never forks a
  process. Keeps `run --stale` as UX — now a thin verb: compile the
  machine queue into tasks, submit to the executor, adopt manifests
  as they land. The loved one-command full rebuild survives, better
  (real parallelism, remote, cached, logs).
- **scripthut**: the machine actor entire. Tasks satisfy the atom
  contract by construction (dep order enforced, no mtime opinions).
- **The seam = two data artifacts**: the *plan* down (structure +
  queue → task definitions; the adapter is ~200 lines via scripthut's
  `generates_source`), the *manifests* up (input/output hashes written
  by the executing machinery at run time, verified at adopt — the
  **only** write path to runs.toml, closing the runner-trust gap
  structurally). Shared vocabulary: entry names.

Night's design absorbed, nothing wasted: the implementation map stays
(its `command` rehabilitated — compiled into tasks, not a demoted
hint); the record verb survives for true manual edges; the reference
runner (~300 lines against plan/manifest) is the no-server fallback;
deleted from specthis: executor, parallel scheduler, dispatch, and
possibly the byte cache into scripthut storage. Cost: two small
scripthut features (inputs-only cache key; dry-run probe) + the
adapter. This supersedes the agent-loop/dispatcher *driver* story of
§5 (those remain the fallback shape); the cakm notes' §7 deferral
clause is hereby considered triggered — by intuition refusing to
settle, which is the honest form of "the bookkeeping hurts."

**Agreed sequencing (2026-07-21): scripthut first.** Three features,
with acceptance criteria from the split's perspective:

1. **Inputs-only cache-key mode** — per-task opt-in dropping the git
   commit from the key. Accept: identical command+env+inputs across
   different commits hit the same cache entry. (Adapter enrolls code
   files as inputs → per-entry invalidation granularity.)
2. **Dry-run probe** — same task JSON, computes the key, returns
   hit/miss + cached output hashes on hit; executes nothing, writes
   nothing. Powers needs-compute vs needs-restore and tier-1 status.
3. **Local escape hatch** — same TaskDefinition, same dep-order,
   same cache, local backend when remote is absent; dumb in the
   atom-contract sense (no mtimes, unconditional unless cache-hit).
   Makes deleting specthis's executor safe for laptop-only work and
   retires the reference runner for the private stack.

Plus: **the per-task manifest as an explicit deliverable** — entry
name, input hashes as used, output paths + content hashes, stable
format; it is what adopt verifies (the only runs.toml write path).
Scripthut already computes every ingredient; the feature is exposure.

## 15. The complexity budget (a standing test)

The recurring worry is that this is getting more complicated than
needed. The guardrail: **there is exactly one engine — the two-table
comparison of §8 — and every feature must reduce to it or stay out.**
Everything in this document passes that test today: the two trees are
two applications of "content moved under a claim"; the delegation
removes machinery without touching the engine; templates add a
*front-end* (elaboration produces the entry list) and change the engine
not at all; doctrine (arguments-as-files, the atom contract, thin
dispatchers) is prose about how actors behave, zero mechanism. A
proposal that needs a second engine — a second staleness notion, a
gate, a stateful scheduler, a registry — is the complexity that was
already rejected once, wearing a new name. Modularity here *is* the
simplicity: four actors, two ledgers, one comparison.
