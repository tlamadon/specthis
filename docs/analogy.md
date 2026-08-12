# specthis — the analogy

**Status: 2026-08-12.** Intuition, not specification. Read this first if
the formal argument in `attestation-model.md` feels abstract; read
`specification.md` when you need what is actually true.

Everything here is a *professional kitchen*, with two images borrowed
from a building site where the kitchen is vague. The correspondence is
close enough that most questions about specthis can be answered by
asking what a kitchen would do — and §6 lists the places where that
would mislead you.

---

## 1. The three things you write

| specthis | kitchen |
|---|---|
| **spec** | the dish as the chef defines it — what it must taste like, look like, *be* |
| **code** | the technique — how you actually make the stock |
| **pipeline** | the prep list — this technique, those bones, into that container |

The spec is the standard. The technique is how it's done. The prep list
binds a technique to particular ingredients for a particular product.

You write all three. Nobody derives the prep list from the menu, which
is why specthis reads your pipeline and checks it against your specs
rather than generating it.

---

## 2. The two claims are two documents you have seen

This is the whole design, and it is not a metaphor — kitchens really
keep both, and would never merge them.

**The chef approves the dish.** Once, during menu development. It
survives four hundred services. It is void the moment the technique
changes or the standard is rewritten.

> *That is a vouch.* Judgment attaches to the **definition**, so it
> survives every repetition, and expires only when its subject moves.

**Every container gets a label.** *Chicken stock — 12 Aug — JM.* One per
batch. It survives nothing; tomorrow's batch gets its own.

> *That is a run claim.* It attaches to **bytes**, so it survives
> nothing.

Different questions, different people, different moments. Two documents.

---

## 3. One entry, end to end

`clean-wages` is your **stock**.

The **spec** says what stock must be: clear, no scum, gelatine set when
cold. The **technique** is how you make it. The **prep list** says: *this
technique, yesterday's bones, into the six-litre container.*

The **stock itself** is not "the output of step 3" — it is stock, a
thing with a name, and tonight it goes into the soup, the risotto *and*
the sauce. Three consumers, one intermediate. That is the DAG, and it is
the normal case rather than a clever one.

---

## 4. Everything else

| specthis | kitchen |
|---|---|
| **cache** | the **freezer** — you made that exact gravy yesterday |
| **probe** | opening the freezer to look, before anyone lights a burner |
| **`map.scripts`** | **house-made vs bought-in** — which line you are accountable for making |
| **`map.produces`** | which container *is* "the stock", as opposed to where it sits |
| **source entry** | the fish, with its delivery docket |
| **library entry** | a mother sauce — judged on its own, plates no dish |
| **template** | a chain: one approved recipe, forty branches |
| **propagation** | the stock was made with milk that had turned |
| **integrity break** | someone took a portion out of the container |
| **the two queues** | what needs tasting, and what needs cooking |
| **specthis itself** | the logbook — not the chef, not the inspector |

**The label is the cache key.** A container marked only *gravy* is
useless: you cannot tell whether it is the *right* gravy. To reuse it
you must know it came from that stock by that recipe — which is why a
run claim pins its whole input table and not just what came out.

**The freezer belongs to the kitchen, not the inspector.** specthis
never reads a manager's cache. It reads what the manager reports.

**You hand over the prep list, not a task.** The kitchen decides what
actually gets cooked, given what is already in the freezer. specthis
hands over the whole pipeline for the same reason: whether a rerun
produces the identical thing is only knowable *after* running it.

---

## 5. Two images borrowed from a building site

**What a vouch really is: building control signs off the rebar.** The
certificate stands for the life of the building, and is void the moment
anyone alters the work it covered. Nothing states the expiry rule that
cleanly.

**Why a broken upstream is not your fault: the footings are not to
spec.** Nobody's workmanship above them is in question. Every
certificate for the second floor is now standing on ground that moved.
That is `upstream-unverified` — waiting, not broken.

---

## 6. Where it would mislead you

**A building site gates; specthis does not.** You cannot cover up work
before inspection — that is the point of building control. specthis went
the other way deliberately: an unvouched entry rebuilds while a mind
audits it, because judgment and computation are independent. The kitchen
has this right — tonight's batch does not wait for a recipe approved
last spring to be re-approved.

**One fitted closet feeds nothing.** Construction is assembly;
your pipeline is transformation, where an intermediate is a substance
that gets worked on again. That is why the kitchen leads here.

**A kitchen has no notary.** There is no counterpart to specthis itself
— the closest is the logbook the inspector reads. The analogy covers the
*materials*, not the tool.

**And no analogy carries the one hard fact:** specthis can verify
neither claim. It cannot taste the stock and it cannot watch the pot. It
records who claimed what, over which bytes, and reports when the content
those claims rest on has moved. Everything else is somebody else's job —
which is the argument `attestation-model.md` makes properly.
