# specthis — the analogy

**Status: 2026-08-12.** Intuition, not specification. Read this first if
the formal argument in `attestation-model.md` feels abstract; read
`specification.md` when you need what is actually true.

Everything here is a **bakery**, with two images borrowed from a
building site where a bakery is vague. Baking is the right register
because it is exact: you validate a formula, then the oven does what the
oven does. There is no tasting and adjusting mid-bake, which is the same
separation specthis draws between judging a definition and executing it.

§7 lists the places the analogy would mislead you.

---

## 1. The three things you write

| specthis | bakery |
|---|---|
| **spec** | the **formula** — 100% flour, 68% water, 2% salt, 1.5% levain, and what the loaf must be |
| **code** | the **method** — how you actually mix, fold, shape and bake |
| **pipeline** | the **production sheet** — this method, that flour lot, into those tins |

A formula describes the bread without reference to any batch. That is
what a spec is: what the thing must be, independent of any making of it.

You write all three. Nobody derives the production sheet from the
formula, which is why specthis reads your pipeline and checks it against
your specs rather than generating it.

---

## 2. The two claims are two documents on the wall

This is the whole design, and it is not a metaphor — bakeries really
keep both, and would never merge them.

**The formula is approved once.** Someone bakes it, cuts it, judges the
crumb, and signs it off. That approval survives four hundred bakes. It
is void the moment the method changes or the formula is rewritten.

> *That is a vouch.* Judgment attaches to the **definition**, so it
> survives every repetition and expires only when its subject moves.

**Every batch gets a label.** *Country sourdough — 12 Aug — batch 3 —
flour lot 4471.* One per bake. It survives nothing; tomorrow's batch
gets its own.

> *That is a run claim.* It attaches to **bytes**, so it survives
> nothing.

Different questions, different people, different moments. Two documents.

**And you cannot taste-and-adjust mid-bake.** Once it is in the oven,
the formula either was right or was not. Judgment happens at the
definition; the batch simply runs. That separation is the model.

---

## 3. One entry, end to end

`clean-wages` is your **levain**.

The **formula** says what a levain must be: 100% hydration, doubled in
four hours, smells of yoghurt not acetone. The **method** is how you
refresh it. The **production sheet** says: *this method, that flour, that
crock, twelve hours at 24°C.*

The levain is not "the output of step 2" — it is **levain**, a thing
with a name, and it goes into the country loaf, the baguettes *and*
tomorrow's refresh. Several consumers, one intermediate, and it has an
identity that outlives every batch that used it.

That is the DAG, and it is the normal case rather than a clever one.

---

## 4. Everything else

| specthis | bakery |
|---|---|
| **cache** | the **freezer** — laminated dough you sheeted on Tuesday |
| **probe** | opening the freezer to look, before anyone starts sheeting |
| **`map.scripts`** | **what you make vs what you buy in** — you mill nothing, you laminate everything |
| **`map.produces`** | which crock *is* "the levain", as opposed to where it sits |
| **source entry** | the **flour**, with the miller's spec sheet — protein, ash, lot number |
| **library entry** | a **preferment kept for its own sake** — judged on its own, sold to nobody |
| **template** | one approved formula, forty branches of the chain |
| **propagation** | the levain went acetic — nothing baked from it is trusted |
| **integrity break** | someone cut into a loaf that was going out for judging |
| **the two queues** | what needs approving, and what needs baking |
| **specthis itself** | the production log — not the baker, not the inspector |

**The label is the cache key.** A tub marked only *dough* is useless:
you cannot tell whether it is the *right* dough. To reuse it you must
know which formula and which flour lot — which is why a run claim pins
its whole input table rather than just naming what came out.

**The freezer belongs to the bakery, not the inspector.** specthis never
reads a manager's cache. It reads what the manager reports.

**You hand over the production sheet, not a task.** The bakery decides
what actually gets made, given what is already in the freezer. specthis
hands over the whole pipeline for the same reason: whether a rerun
produces the identical thing is only knowable *after* running it.

---

## 5. The lesson only baking teaches

**Ambient temperature is an undeclared input.**

The dough proofed faster because the kitchen was warm. Nothing in your
log changed. The bread is different. Your log is now *lying* — not
through malice, but because something that moved the output was never
written down.

That is under-declaration: the one risk specthis cannot cover, and the
whole reason **arguments must be files**. A parameter that lives in
somebody's head, or in the room, is a parameter no claim can pin.

---

## 6. Two images borrowed from a building site

**What a vouch really is: building control signs off the rebar.** The
certificate stands for the life of the building, and is void the moment
anyone alters the work it covered. Nothing states the expiry rule that
cleanly.

**Why a broken upstream is not your fault: the footings are not to
spec.** Nobody's workmanship above them is in question. Every
certificate for the second floor is now standing on ground that moved.
That is `upstream-unverified` — waiting, not broken.

---

## 7. Where it would mislead you

**A building site gates; specthis does not.** You cannot cover up work
before inspection — that is the point of building control. specthis went
the other way deliberately: an unvouched entry rebuilds while a mind
audits it, because judgment and computation are independent. The bakery
has this right — tonight's batch does not wait for a formula approved
last spring to be re-approved.

**One fitted closet feeds nothing.** Construction is assembly; your
pipeline is transformation, where an intermediate is a substance that
gets worked on again. That is why the bakery leads here.

**A bakery is a smaller cast.** A restaurant brigade — chef, sous,
commis, supplier — illustrates better that different people hold
different capabilities. Read a production team into the bakery, and the
miller is an external actor either way.

**And no analogy carries the one hard fact:** specthis can verify
neither claim. It cannot cut the loaf and it cannot watch the oven. It
records who claimed what, over which bytes, and reports when the content
those claims rest on has moved. Everything else is somebody else's job —
which is the argument `attestation-model.md` makes properly.
