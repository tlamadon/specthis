# Your project is a bakery

**Status: 2026-08-12.** Intuition, not specification. Read this first if
the formal argument in `attestation-model.md` feels abstract; read
`specification.md` when you need what is actually true.

---

Think of your research project as a bakery.

The **final goods** are cakes and pastries: your tables, your figures,
the paper that interprets them. The **raw materials** are flour, butter,
eggs — the data you did not produce, cannot certify, and can only
source.

Between the two is everything you actually build. Nobody goes from a
sack of flour to a finished gâteau in one movement. You make a **batter**,
a **choux paste**, a **crème pâtissière** — intermediate products, each
with a name, each held to a standard, each feeding several things
downstream.

As the team leader you lay out how to get from the flour to the cakes.
That is three separate documents, and keeping them separate is the whole
idea.

---

## 1. The three things you write

**The formula** — what each thing must be. *Choux: 100% water, 60%
butter, 120% flour, eggs to a ribbon that falls in a V. Should puff
hollow and hold its shape.* Notice it describes the paste without
reference to any particular batch. That is your **spec**.

**The method** — how it is actually made. Boil the water and butter,
shoot in the flour, dry it out over the heat, beat the eggs in one at a
time. That is your **code**.

**The production sheet** — which method, with which ingredients, into
which tray. *Choux by the standard method, flour lot 4471, piped onto
the lined tray.* That is your **pipeline**.

You write all three. Nobody derives the production sheet from the
formula, which is why specthis reads your pipeline and checks it against
your formulas rather than writing it for you.

---

## 2. The two things you sign, and they are not the same thing

**You approve the formula once.** Somebody makes the choux, you cut one
open, you see it is hollow and holds. Signed off. That approval covers
the next four hundred batches — and is void the instant the method
changes or you rewrite the standard.

**You label every batch.** *Crème pât — 12 Aug — batch 3 — milk lot
88, eggs lot 12.* One label per making. It survives nothing; tomorrow's
batch gets its own.

These answer different questions. The first says *this way of making it
is right.* The second says *this tub came from that way, using those
things.* Bakeries keep both and would never merge them, and neither does
specthis: one ledger for approvals, one for batches.

**And you cannot taste and adjust once it is in the oven.** Judgment
happens on the formula; the batch simply runs. That separation is the
model — a mind judges definitions, a machine makes bytes, and neither
waits for the other.

---

## 3. You are not the one baking

Your team bakes. The ovens bake. You laid out the plan and you sign the
paperwork.

specthis is the same: it is **the production log**, not the baker and
not the inspector. It never lights an oven. It hands the production
sheet to whoever is doing the work — your own kitchen, or a contract
bakery with more capacity — and records what comes back.

You hand over the **whole sheet**, not one task at a time. The bakery
decides what actually needs making today, because only they know what is
already in the freezer.

---

## 4. One intermediate, followed through

Take the **crème pâtissière**.

It has a formula: smooth, no skin, sets to a firm ribbon. It has a
method: temper the yolks, cook to the boil, sieve, chill fast. It is made
from milk and eggs you bought and sugar you bought.

And it is not "the output of step 4." It is *crème pât* — a thing with a
name, which goes into the éclairs, the tarts **and** tomorrow's
mille-feuille. Several consumers, one intermediate.

That is why every entry in your project produces something with a name
rather than a file at the end of an arrow. `wages-panel` is a crème
pâtissière.

---

## 5. The freezer

Before anyone sheets new laminated dough, you look in the freezer. You
sheeted some on Tuesday. If it is the *same* dough — same formula, same
flour lot — you use it and skip the work.

That is the cache, and looking in the freezer is the cheap check you do
first. Two things follow:

**The label has to say enough.** A tub marked only *dough* is useless —
you cannot tell whether it is the right dough. That is why a batch record
pins everything that went into it, not just what came out.

**The freezer is the bakery's, not yours.** specthis never rummages
through a workshop's store; it reads what the workshop reports.

---

## 6. The flour

You did not mill it. You cannot certify how it was made. What you have
is the miller's spec sheet — protein, ash, lot number — and your own
judgment that the sack is what it says.

So the claim you sign over raw data is **provenance**, not correctness:
*this is IPUMS extract #14, downloaded on this date.* Different in kind
from *this method makes good choux*, and specthis keeps them different.

---

## 7. Three things that go wrong, and what each needs

**The levain turned acetic.** Nothing anyone did downstream was careless.
Every loaf that used it is now of unknown quality anyway. Fix the levain
and they are fine again — nobody needs to re-approve a formula.

*That is a broken upstream: downstream is waiting, not wrong.*

**Somebody changed the choux method.** Now two things are true at once:
the formula needs re-approving, and everything made the old way is
suspect. Two different people have work to do, and neither blocks the
other.

*That is why there are two queues.*

**Somebody cut into a cake that was going out.** The kitchen cannot tell
— nothing about its ingredients changed. Only someone checking the tray
against the label finds it, and only they can ask for it to be remade.

*That is why specthis checks products against their records, and is the
one case where it asks for specific work.*

---

## 8. The warm room

Here is the failure no paperwork catches.

The dough proofed faster because the kitchen was warm that afternoon.
Nothing in the production sheet changed. The bread is different. Your
log is now **lying** — not through anyone's fault, but because something
that moved the result was never written down.

This is why every input that matters has to be a *file* — a config, a
parameter table, something with a name that can be recorded. A number
that lives in somebody's head, or in the room, is a number no claim can
pin.

It is the one risk specthis cannot cover for you.

---

## The whole thing, on one line

> **Formulas say what things must be. Methods say how. Production sheets
> say which, with what, into where. You approve formulas; the bakery
> labels batches; specthis keeps both pieces of paper and tells you which
> ones no longer hold.**
