---
description: Drive both queues to a fixed point without stopping to ask — lint, build, hand every judgment to fresh critics, and repeat until nothing moves. Suspends the propose-and-wait rules for one bounded run; never the vouching pen.
---

The user ran `/specthis-yolo $ARGUMENTS` — an explicit, bounded grant of
autonomy. Normally `AGENTS.md` tells you to propose and wait: *"express
proposals as 'I could now implement X', not as actions taken. Wait for
explicit confirmation."* **That rule is suspended for this run.** So is
"stop and propose the vouch", and so is asking before spending compute.
Act. Do not report and wait. Do not ask permission for anything the
loop below covers.

Arguments, all optional: a duration (`3h`) or an iteration count (`60`)
overriding the defaults below. They are a budget, not a scope — yolo
always works the whole project, because a queue you excluded is a queue
that grows behind your back.

## What is *not* suspended

**You never run `specthis vouch`.** Not for entries you wrote, not for
entries you did not, not to "unblock" anything, not at the very end to
tidy up. A vouch is a claim that a non-author judged the code against
the contract, and `check` going green is the whole product — a
self-stamped vouch makes the ledger report `ready` while meaning
nothing, which is worse than leaving the entry unvouched. The pen goes
to a fresh `spec-critic` subagent, exactly as in `/specthis-vouch`.

This is not an obstacle to finishing. It is a loop: **doubt → author a
fix → hand it to a _new_ critic → re-judge.** A different session
judging revised code is a real vouch, and it converges.

Also unchanged: never hand-edit `vouches.toml` or `runs.toml`, and never
vouch under the human's name.

## Arm the loop

1. `git config user.name` — the commissioning human. If empty, ask for
   it now; this is the one question worth blocking on, because critics
   refuse to vouch anonymously and you would otherwise loop to nowhere.
2. Run `specthis check --json` and read `verdict`. If it is already
   `done`, say so and stop — there is nothing to drive.
3. Write `.specthis/auto.json` (create `.specthis/` if missing). The
   deadline is the wall-clock stop; compute it portably:

   ```bash
   python3 -c "from datetime import *; print((datetime.now(timezone.utc)+timedelta(hours=4)).isoformat(timespec='seconds'))"
   ```

   ```json
   { "active": true, "deadline": "<the above, or the argument>",
     "iterations_left": 40, "watching": [], "set_aside": [],
     "critic_rounds": {} }
   ```

   The Stop hook reads this file after every turn and refuses to let the
   session end while work remains. It is also what stops the run: when
   the queues drain, the budget runs out, the deadline passes, or three
   rounds go by with nothing moving, it disarms itself. You do not need
   to decide when to stop — but if the user interrupts, or you must
   abandon the run, set `"active": false` so the next session starts clean.
   One sizing note: a run stuck in `watching` consumes no iterations and
   trips no stall counter — it is bounded by the deadline alone, so size
   the deadline for the cluster, not the chat.

4. Tell the user, in two lines, what you are about to drive: the two
   queue depths and the budget. Then go quiet until it is over.

## The loop

Repeat until the hook disarms. **After every step, re-run
`specthis check --json`** — the queues grow as you drain them: a rebuilt
output makes its consumers stale, and a repaired definition expires its
own vouch. A single pass is never enough; that is the entire reason this
command exists.

1. **Specs must parse first.** If `lint.problems` is non-zero, run
   `specthis lint` and fix them. Act on the warnings too — an
   unmentioned reference or a dangling link is the cheap, mechanical
   form of exactly what burns critic budgets when it survives. Your
   pen covers `specs/*.md` and `specs/bindings.toml` and nothing else.
   Nothing below is trustworthy until this is clean.

2. **Read the specs before judging them.** Commission a `spec-reader`
   subagent over `specs/` (one agent for the whole directory; one per
   folder on a large project). It reads the text and nothing else and
   returns two lists: internal contradictions (claims that disagree
   within or across files, counts that do not match their lists,
   notation against a fixed convention) and open questions — facts an
   implementer would need that no spec states, forks the text leaves
   open. Fix every contradiction; answer the open questions you can
   answer in the spec text, and surface the rest to the user in the
   final report — an open question is the one finding the loop may
   not invent an answer to. Spec edits are mind-only and always safe,
   even while builds are in flight. Re-commission only over files
   that changed since its last pass, not every round. **Do not send
   an entry to a critic while the reader has an open finding against
   its file** — a critic judging a broken contract can only return
   doubt, at many times the price.

3. **Machine queue** — `specthis build`, or `specthis build <entry>
   --force` for the one repair case (an artefact edited on disk). Hand
   over the whole pipeline; specthis never selects steps, because only
   the manager knows what its cache already holds.

   **`build` cannot clear every machine-queue entry.** A source entry —
   a dataset whose bytes arrive from outside — has no pipeline step, so
   building does nothing and the queue never moves. If an entry stays
   queued after a build, check whether the pipeline has a step for it;
   if it does not, the verb is `specthis record <entry>` once the bytes
   are on disk (add `--where remote --cpu <seconds>` when they were made
   elsewhere). If the bytes are genuinely absent, no verb helps — set it
   aside and say so; only a human can fetch a dataset that does not
   exist yet.

   For work that goes to scripthut — anything `tier: intensive`, and
   anything you expect to outlast a turn:

   ```bash
   RUN_ID=$(scripthut workflow run <file> --source <name> --backend <b> --json | jq -r .id)
   ```

   Append `{"run_id": "...", "entries": [...]}` to `watching` in
   `.specthis/auto.json`, then launch **in the background**
   (`run_in_background: true`):

   ```bash
   scripthut run watch $RUN_ID --exit-status
   ```

   This is the piece that stops completions going missing. `run watch`
   blocks until the run is terminal and exits non-zero on failure, and a
   backgrounded command hands you its result the moment it finishes — so
   you are told, instead of having to remember to look. Never poll in a
   loop, and never sit in the foreground waiting.

   While it runs, **keep working the mind queue — knowing where the
   axes actually couple.** They are not independent, and pretending
   they are is how a loop loses builds:
   - Certification does not gate compute **except rejection** — a
     machine must never realize a definition a mind refused.
   - A **spec edit is mind-only**: it expires the vouch and enters no
     run signature. Safe at any time, including mid-build.
   - A **code edit hits both queues and kills in-flight adoptions**:
     adoption re-verifies every path the returning manifest names
     against the bytes on disk, so a script edited after submission no
     longer hashes to its manifest and the adopt correctly refuses.
     While an entry is in `watching`, defer its code repairs until the
     run lands — or make the edit knowing you have chosen a resubmit.
     Never treat the resulting refusal as a ledger problem to route
     around.

   Only when nothing else is actionable does the hook let the turn
   end, and the backgrounded watch then wakes you.

   On completion: `scripthut run manifest $RUN_ID <task_id>` → save it →
   `specthis adopt <entry> <file>` → remove the entry from `watching`.
   Adoption re-verifies every digest against the bytes on disk; if it
   refuses, the refusal is correct — never edit a ledger to get past it.

   On failure: `scripthut run logs $RUN_ID <task_id> --error --tail 200`,
   fix the cause, and submit a **new** run rather than rerunning the
   failed one. If the same step fails twice for the same reason, stop
   retrying it, move it to `set_aside`, and carry on elsewhere.

4. **Mind queue** — spawn a fresh `spec-critic` subagent **per entry, in
   parallel** (batch them in one message, ~4 in flight), each given the
   commissioning human's name, its single entry, and the project root.
   Do not summarize the code for them; they re-read from disk. Do not
   judge anything yourself.

5. **A doubt is not a stopping point.** When a critic reports a doubt,
   or an entry carries a standing rejection, read the reason and fix
   what it names — edit the spec if the contract is wrong, the code if
   the code is (checking `watching` first: a code edit kills that
   entry's in-flight run, see step 3). Then hand it to a **new**
   critic. Record the attempt in `.specthis/auto.json` first:
   `critic_rounds["<entry>"] = {"doubts": N, "last_reason": "..."}` —
   the count lives in the file, not in your head, so it survives a
   context compaction. At two doubts, append the entry to `set_aside`
   with the reason and move on. The hook stops counting set-aside
   entries as work on either axis, so the loop converges instead of
   grinding.

6. **Two things that look like breaks and are not.** Entries listed in
   `bytes_not_local` are `current` — the claim stands and the bytes live
   in the manager's store. Never rebuild one to fetch them. Entries under
   `waiting_on_upstream` need nothing: they heal when their upstream
   does. Rebuilding either is how a loop burns hours making no progress.

## Reporting

Stay quiet while it works. Surface only what the user would want woken
for: a step that failed twice, an entry set aside, compute that is
running longer than its recorded `duration_seconds` suggests, or the
run ending. Routine progress goes in the final report, not the transcript.

When the hook disarms, give one report: what was built, what was
vouched and by which critic, what was set aside and why, what remains
blocked, the wall/CPU cost from `specthis status`, and both queues fresh
from `specthis check`. Anything in `set_aside` or `blocked` is now the
human's queue — say so plainly, and say what you tried.
