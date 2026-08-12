# specthis — the attestation model

**Status: 2026-08-10.** Third design document, after
`design-notes-from-cakm.md` (the cakm-evidence redesign) and
`two-trees-and-delegation.md` (the two trees + the scripthut split).
This one is a **reframe, not an extension**: the two trees turn out to
be two instances of one thing, and saying so collapses several
distinctions that were being maintained by hand. §14 lists what it
supersedes.

If the argument below feels abstract, `analogy.md` says the same thing
as a bakery — an approved formula on the wall, a label on every batch,
and a levain that outlives every loaf made from it.

The reframe was reached by pulling on one thread — *what, exactly, can
specthis verify?* — and finding the answer is **nothing**. Everything
below is the closure of that.

---

## 1. The reframe

specthis is an **attestation system**. It records claims that actors
make about content, and reports which claims the content still
supports.

Two claim species exist today:

- **Certification** — *this code satisfies this spec.* Pinned over
  `(spec block, code files)`.
- **Realization** — *these outputs came from this code on these
  inputs.* Pinned over `(code files, inputs, outputs)`.

They are not two subsystems. They are one record type with different
pinned tuples, run through one comparison.

**Code sits in both tuples**, which is the whole reason the two axes
break the way they do — and it is a consequence of the tuples, not a
rule anyone maintains:

| Edit | Certification | Realization |
|---|---|---|
| spec prose | breaks | untouched |
| code | breaks | breaks |
| config / `workflows` | untouched | breaks |
| upstream artifact | untouched | breaks |

---

## 2. Capabilities, not actors

A claim depends on a **capability the notary lacks**:

- Certification needs *reading code against a spec* — a mind or agent.
- Realization needs *executing code on inputs* — an HPC, a GPU, a laptop.

"Needs a mind / needs a machine" is therefore not a taxonomy to
maintain. It is a **field on the attestation**: which capability must
be re-invoked to refresh this claim. The two queues are a `group by`
on that field. A third capability costs nothing structural.

Nothing in the core's vocabulary — entities, edges, file sets, pinned
digests, capability — mentions research, pipelines, or markdown.

---

## 3. Nothing the notary can verify

The earlier documents lean on manifest-verified adopt as a *structural*
trust guarantee. It is weaker than advertised, and correcting this is
what makes the model symmetric.

Adopt rehashes the bytes and confirms the manifest is internally
consistent with content specthis can see. That verifies **transcription,
not derivation**. It does not establish that those outputs *came from*
that code on those inputs — establishing that means re-running, which
needs the capability specthis doesn't have. Exactly as a vouch's
soundness needs a mind specthis doesn't have.

So the notary's job on intake is the same for every species:

1. the attestation is well-formed;
2. the digests it pins are digests of real content;
3. record who claimed what, over which bytes, when.

It never inspects a verdict. **Re-verification is always re-invoking an
actor**, never something specthis does itself.

Two residues, neither about verifiability:

- **Payload.** A realization names a *retrievable artifact* — a content
  address. That is why a byte cache exists on that axis and cannot exist
  on the other: there is no "restore a judgment."
- **Cheap oracle.** Scripthut's dry-run probe answers "would this hit?"
  without executing. There is no analog for "would a mind still vouch?"
  Same claim shape, very different pre-check cost.

What is *not* a residue: completeness. Neither axis can confirm its own
scope. A trace tells you a file was opened, never that the run depended
on it; relevance is judgmental on both sides. See §6.

---

## 4. Three artifacts, three questions

| Artifact | Question | Key | Expires? |
|---|---|---|---|
| **spec** | what does this entry *mean*? | entry | — it is the subject, not a claim |
| **bindings** | what is this entry made of, *now*? | entry | no — a declaration of what is |
| **ledger** | what was claimed, over which digests? | (entry, capability) | yes — when pinned content moves |

The spec file is the seam between the notary and the mind, not a thing
on one side of it. The notary reads its **skeleton** — entry names,
edges, block boundaries → digests. The mind reads its **flesh** — the
prose. Same artifact, two depths of reading. Splitting prose from
interface would let a mind judge text the ledger doesn't pin, which
unanchors the vouch entirely.

The map carries the physical facts **both** capabilities need:

| Field | Serves | Effect when changed |
|---|---|---|
| `scripts` | both | unvouched *and* stale |
| `run` | machine | task compilation |
| `workflows` | machine | **stale, not unvouched** |
| `executor` | machine | dispatch target |
| `[package] globs` | mind (coarse net) | catches unmapped code, bluntly |
| `[preview]`, `[cache]` | neither | vocabulary, not a claim |

`workflows` is the concrete instance of the file-vs-prose doctrine: a
retuned config is machine-work and the vouch stands; the same parameter
pinned in spec prose is a contract change that expires it. One knob,
two doors, chosen by where you put it.

**Output locations belong in the map**, not the spec (the
`design-notes-from-cakm.md` §9 product-location seam). Where a file
lands is a fact about directory layout, not about what an entry means;
a refactor should cost a map edit and a stale run, never a contract
edit and an expired judgment.

---

## 5. The engine: two tables

One comparison, everywhere:

```
recorded table  (from the attestation — what was claimed)
implied table   (from the map + content on disk — what is)
```

Match → the claim stands. Mismatch → the claim's subject moved, **and
the diff of the two tables is the explanation.** Nothing inferred.

This is `two-trees-and-delegation.md` §8, already the engine on the run
axis, now the engine on both.

Composed digests (`code_sha`, `signature`) are **folds over the
tables**. Keep them as a fast path; they are caches, not the truth. The
fold is one-directional — table → digest always, digest → table never —
which settles which one is authoritative.

---

## 6. Why the map is irreducible

A recurring temptation: if the attestation already pins `{path: sha}`,
why keep a separate map?

Because **a claim can guard its own contents, but not its own scope.**

| Change | Detected from the ledger alone? |
|---|---|
| pinned file's content moves | yes — sha differs |
| pinned file deleted | yes — recorded table names the path |
| pinned file renamed | yes — surfaces as the delete half |
| **file added to the entry** | **no — nothing names it, so nothing looks** |

Growth is the single blind spot, and declaring scope is the map's
entire reason to exist. The ledger answers *what did this consist of
when I claimed it* — a question about the past. The map answers *what
does it consist of now* — a question about the present. A diff needs
both; no signature can supply the second, because the actor signed at a
moment that has passed.

The map has a second job: supplying present-world facts when **no**
attestation exists yet — cold-start task construction, `run`,
`executor`, output locations.

**Detection does not depend on the map.** `[package] globs`
(`hashing.py:51`) already blobs unmapped code; a new file there moves
the blob and breaks things bluntly. The map buys **granularity, not
detection** — it is the three-position blast-radius dial of
`two-trees-and-delegation.md` §6, and doing nothing is a valid choice
with a known cost. So the implementer is never being asked to *enable*
invalidation; they are choosing its precision.

The residual risk is unchanged: code neither mapped nor glob-covered is
invisible to everyone. Guards stay the package blob (coarse, mechanical)
and the critic reading imports (precise, judgmental).

---

## 7. Declaration, not event

The map is a *declaration of what is*, never a log of what happened.
Given that scope changes are the implementer's responsibility either
way, why a map rather than an `invalidate` call?

1. **State, not event.** "What is this entry made of?" has a readable
   answer.
2. **Diffable.** `+helpers.py` in a git diff explains itself.
3. **The failure modes differ in kind.** Forget to update the map:
   `helpers.py` is undeclared, so the vouch says "I judged `check.py`
   against this spec" — *incomplete but true*. Forget to invalidate in a
   scope-less imperative model: the file silently joins the entry via
   import and the vouch means "I judged the implementation," which is
   now *false*.

A declared scope converts a potential falsehood into a visible gap.
That is the notary stance: never report more than the content supports.

**Who writes it changes; what it is does not.** Drop "hand-edited" —
the implementer emits its map alongside its code, and each entry
carries provenance (who declared, when). A human editing the map
without an attestation stays meaningful and is the operation you want:
adding a path makes the entry unvouched immediately, which is "this
code belongs here and no mind has judged it," said in one line.

---

## 8. The seam: task down, attestation up

**Task, going down** — emitted when a claim needs refreshing:

```
entity:     clean-wages
capability: mind | machine
reason:     the table diff — {moved: [...], added: [...], removed: [...]}
subject:    spec_block: {path, anchor, sha}
            code:    {path: sha, ...}
            inputs:  {path: sha, ...}      # machine only
            outputs: [path, ...]           # declared, not yet hashed
prior:      the attestation this replaces, or null
```

**Attestation, coming up** — filed by any actor:

```
version:    1
entity:     clean-wages
capability: mind
pinned:     {path: sha, ...}      # the subject as the actor actually saw it
verdict:    ok | rejected | failed
actor:      {id, kind}
when:       iso8601
evidence:   note | exit_code | duration | log ref
```

Acceptance rule, one line: **recompute `pinned` from current content;
accept only if it matches.** Scripthut's `manifest_version: 1` is
already this document with `capability: machine` filled in.

**The actor files one document; the notary splits it.** The attestation
is recorded as the pinned table *and* refreshes the map from the same
list. One write from the actor, two artifacts, neither hand-transcribed.

Actors do two separable things: **change content** and **file
attestations**. Writing code is the first — it produces bytes, not
claims, and the notary simply notices a digest moved. Only judging and
executing produce attestations. "Implementer" is therefore not a
capability in the ledger's sense.

---

## 9. Worked procedure: a spec is edited

1. **A human rewords `### clean-wages`.** Nothing happens. specthis
   doesn't watch; state is derived on ask.
2. **`specthis check`.** The spec block's sha no longer matches what
   the mind-attestation pinned → certification breaks. The
   machine-attestation pinned `(code, inputs, outputs)`; the spec isn't
   in that tuple → **the run claim is untouched.** Rewording a contract
   costs zero compute.
3. **Queue: one mind task**, carrying the table diff as `reason`.
4. **The actor reads.** Either:
   - *still satisfied* → files a fresh mind-attestation pinning the new
     spec sha. Done; nothing ran, nothing downstream moved; **or**
   - *no longer satisfied* → it edits code. Code is in both tuples, so
     this breaks certification *and* realization. It files a
     mind-attestation over `(new spec, new code)`; independently a
     machine task appears.
5. **The machine runs**, files a machine-attestation with input/output
   hashes.
6. **Propagation.** Downstream entries pinned the old upstream output
   digests → they go stale. Cascade by derivation; no attestation
   involved.

Step 4 is where the queues genuinely decouple: a clarification drains
the mind queue alone; a semantic change fills both.

Attestations are **shallow** — each covers only its own entry's blobs.
The third answer, *patience* (`upstream-unverified`), is never attested
by anyone; it is derived by walking the DAG. **Two attestations plus one
propagation rule** is the complete picture.

---

## 10. The elephant: one actor, two acts

In practice the same agent implements *and* vouches. A model that
pretends otherwise records a lie. Acknowledge it and make independence
**visible and optional**:

- **Record `actor` on every attestation** (the field exists —
  `ledger.py:37`), and record the two acts separately even when one
  agent performs both. A combined attestation destroys the only evidence
  that no independent mind looked.
- **Let independence be declared per entry**, not enforced globally.
  Most entries genuinely don't need it — a plotting script judged by its
  author is fine; the identification strategy is not. A lint over the
  ledger, not a new engine.
- **Default to permitting self-certification and surfacing it.**
  Ceremony people route around is worse than a recorded fact.

The reassuring property: because the actor files what it *pinned*, and
the notary verifies that pin against content, **a self-certifying actor
cannot lie about which bytes it judged — only about the verdict.** The
damage surface is one bit per entry, attributable to a named actor with
a timestamp. That is a far better position than the usual one, where "I
checked it" attaches to nothing at all.

---

## 11. What to record: two granularity axes

Recording resolution is a design dial, and conflating its two axes is
what left a live defect in the current code.

- **Axis 1 — record at the claim's true granularity. Affects
  validity.** Too coarse and the claim expires for things that are not
  its subject. This is invariant #1: a judgment should expire exactly
  when its subject changes, never for layout, never for someone else's
  edit.
- **Axis 2 — record finer than the claim's atom. Affects diagnosis
  only.** It can never preserve a claim: the claim is indivisible (a
  mind judged the whole entry) and relevance is judgmental. Finer
  digests help a *human* triage — comment tweak vs. logic change — and
  the notary can never act on them.

**Resolution cannot be raised retroactively.** Information not recorded
at claim time is gone, and recovering it costs a re-attestation — a
mind or a GPU. Recording is bytes; re-attesting is the expensive thing
in this system. Record generously.

---

## 12. Findings against the current code

Ordered by value, highest first.

1. **Spec expiry decides on the wrong digest — an axis-1 defect.**
   `_certify` compares the *file-level* `spec_sha` (`check.py:197`),
   while `spec_block_sha` is used only to print the attribution —
   literally `spec: wages.md moved outside this entry's block`
   (`check.py:167`). So editing entry B's prose expires entry A's vouch
   in the same file, **and specthis already reports that the expiry was
   spurious while expiring it anyway.** Deciding on `spec_block_sha`
   removes the whole class, and matches
   `design-notes-from-cakm.md` §4 rule 3. The field is already in the
   ledger; this is the smallest correctness win available.
2. **Outputs never got the table treatment.** `Run.output` is a
   comma-joined path string and `output_sha` a single composed digest
   (`ledger.py:56`), so a multi-output entry cannot say which output
   moved. Scripthut's manifest already supplies `outputs: {path: sha}` —
   adopting it fills this in rather than as separate work.
3. **Make the tables authoritative on the vouch axis.**
   `code_manifest` is already recorded and already marked "diagnostic
   only" (`ledger.py:40`). Promoting it is a change in *which field the
   engine reads*, not a format change. Buys `code: +helpers.py` in place
   of `code moved`.
4. **Output locations move from the spec to the map** (§4).
5. **`record_vouch`'s rejection rule is policy, not notarization.** It
   refuses an `ok` at a pair carrying a standing rejection
   (`ledger.py:125`). Worth re-examining under this frame: the notary
   records, a policy layer may object.

---

## 13. Storage layout

**One file per concurrent writer stream.** The critic writes vouches
while the runner writes runs — different actors, different cadence —
and `ledger.py:69` already locks per file for exactly this reason. The
map has one writer role, so it is one file. Both outcomes fall out of
the same rule; neither is an aesthetic choice.

Two consequences:

- **Glob `ledger/*.toml`; never enumerate the species in code.** A third
  capability then lands its own file, its own lock, its own diff stream,
  and touches nothing.
- **The map cannot split even if you wanted it to** — `scripts` serves
  both capabilities, and duplicating it would create a drift source.

The apparent duplication of the map into `runs.toml` is not
duplication: at the moment a claim is filed the recorded table *must*
equal the resolved map — that is what "this is what I ran" means. They
are the same list at two times, and the divergence is the only signal
anyone wants. The overlap is also partial: `run`/`executor`/globs are
map-only, upstream digests are ledger-only.

---

## 14. What this supersedes

- **`two-trees-and-delegation.md` §13 invariant 4** ("judgment attaches
  to definitions; mechanics attach to bytes") — still true as
  behavior, but it is a *consequence* of the two pinned tuples, not a
  species distinction. The two are one record type.
- **`two-trees-and-delegation.md` §14**, on manifest-verified adopt as a
  structural trust guarantee — weakened per §3. Adopt verifies
  transcription; it does not close the runner-trust gap, because
  derivation is unverifiable without the capability. The manifest seam
  is still right; the claimed guarantee was too strong.
- **`design-notes-from-cakm.md` §9 product-location seam** — resolved in
  favor of the map (§4).
- **`bindings.toml`'s "hand-edited" framing** — actor-writable with
  provenance (§7). "Not a claim" stands and is now load-bearing.

Unchanged and reaffirmed: the pure-contract spec format (§4 of the cakm
notes), the blast-radius dial, arguments-as-files, the deferred template
tier, and the complexity budget — **one engine; every feature reduces
to the two-table comparison or stays out.** This document adds no
engine.

---

## 15. Open

- **Module boundary before repo split.** The core must import nothing
  that knows about markdown, kinds, tiers, or prose; the spec front-end
  compiles specs + bindings into structural input. Enforce as a module
  boundary now; defer a second repo until a second front-end or an
  outside consumer demands it. One unfinished seam (the scripthut
  adapter) is enough.
- **The scripthut adapter itself.** All three agreed features shipped
  (`cache_scope: "inputs"`, `task probe`, the local backend) plus the
  per-task manifest. The specthis half — plan down via
  `generates_source`, scripthut manifests adopted as the only write path
  to `runs.toml`, and deletion of the executor/scheduler/dispatch —
  is untouched. Note specthis's own `remote.py` manifest format now
  competes with scripthut's; one should win.
- **How independence is declared** per entry (§10).
- **Append-only ledgers.** Today one row per entry, replacing; history
  lives in git.
- **The template tier** remains deferred behind its own trigger, and its
  blocker is untouched by this reframe: a template vouch is a
  universally quantified claim, the strongest thing a mind can be asked
  to sign.
