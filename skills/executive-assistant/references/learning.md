# Learning from corrections

A model forgets everything between runs; its memory is whatever it reads at the start.
So the assistant learns by writing rules into the state and rereading them next run. The
loop has three parts: **correct, codify, verify.**

## Correct: the signals

Domain skills report signals since the last run. Common ones:

| Signal | Meaning |
|---|---|
| The user moved something the assistant filed back to where it came from | It mattered; don't do that again |
| The user undid an action (removed a label, deleted an event the assistant made) | Wrong action |
| An explicit wrong-marker (`EA/Wrong` in Gmail) | Look closer at this one |
| An explicit good-marker (`EA/Good`) | Confirmation - keep doing this |
| A reply to the brief, or a direct edit to the state | An instruction; direct edits are authoritative and need no codifying |
| A proposal ignored for 7+ days | Low value; drop it and soften the rule that produced it |

Confirmations count. Learning only from mistakes lets good habits drift.

## Codify: from signal to rule

For each signal, answer three questions before writing anything.

1. **Does it generalize?** "This one email was misfiled" does not. "Event invites I
   haven't registered for are not important" does. A signal that doesn't generalize still
   becomes an example (below), just not a rule.
2. **Where does it belong?** Exactly one place: `core.md` for behavior that spans domains,
   `domains/<name>.md` for one domain, `ladders.md` for reminder timing, `people.md` for a
   person. A rule in the wrong place is either ignored or applied too widely.
3. **What's the reason?** A rule without a why can't handle the case it didn't anticipate.

Then write the rule in the state's format:

```markdown
**Rule:** Luma invites for events I haven't registered for go to Feed.
**Why:** Registration confirmations matter; general invites are browsing material.
**Apply:** Check for "registration confirmed" or "you're going" before filing.
learned: 2026-11-02, EA/Wrong on "WorkOS meetup" invite
```

**Threshold.** An explicit correction (wrong-marker, reply, undo) is enough for a rule.
An implicit one (moved back, ignored) needs a second consistent signal first; until then,
record it only as an example.

**Contradictions.** If a new rule conflicts with an existing one, don't silently replace
it. Narrow the old rule if the two can coexist; otherwise put the conflict under "Needs
you" and change nothing.

## Examples

Every signal adds one line to `examples.jsonl`, whether or not it produced a rule:

```json
{"date":"2026-11-02","domain":"email","input":"From: Luma <...> Subject: You're invited: WorkOS meetup","decision":"feed","was":"inbox","signal":"EA/Wrong","rule":"domains/email.md#luma-invites"}
```

Keep `input` to sender and subject, or a short description. Never store message bodies,
account numbers or anything sensitive. These lines are the regression set: any change to
the skills can be replayed against them in dry-run mode.

## Verify

- Every rule learned in a run is listed in that day's brief under "What I learned", so the
  user can veto it by editing or reverting the commit.
- Commit each rule on its own, with a message that names the signal:
  `learn(email): Luma invites → Feed (EA/Wrong, 2026-11-02)`. A veto is then a single
  `git revert`.
- After applying a signal, remove the marker that carried it (for example the `EA/Wrong`
  label) so it isn't learned twice, and record the source id in the log.
