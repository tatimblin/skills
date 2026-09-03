---
name: refresh-calendar
description: Register a local routine that refreshes a calendar series after it ends, for series whose next occurrence cannot be known until the scheduled ones elapse - a semester of classes, a league season, a dentist appointment booked six months out. Computes the last occurrence, asks where the next schedule will come from, and hands the follow-up to the local-routine skill. Use when adding classes, a season schedule, recurring appointments or any dated series to a calendar, or when asked to re-check or refresh something after a series finishes.
---

# Refresh a calendar series after it ends

Some things on a calendar are the last you will hear about them until they run
out. A semester ends and next term's timetable appears. A league season finishes
and the next one opens. You leave the dentist with an appointment six months out
and nothing after it.

This skill spots that shape, works out when the series ends, and offers to put a
future agent run on the calendar's other side - so the next set gets picked up
instead of quietly lapsing.

## The test

**Will the next occurrence only become knowable after the scheduled ones
elapse?**

That is the whole judgement. Not "are there several events", not "is it
recurring". A single dentist appointment qualifies; forty standups do not.

| Qualifies | Why |
|---|---|
| A semester of classes | Next term's timetable is published later |
| A league season | Next season's schedule appears after this one |
| One dentist appointment 6 months out | The next is booked *at* that visit |
| A course, cohort, or therapy block | Renewed as a unit, on its own cadence |

| Does not qualify | Why |
|---|---|
| A concert, a flight, a birthday dinner | There is no next one to discover |
| An open-ended weekly standup | Already recurs indefinitely; nothing to find out |
| Unrelated events that happen to cluster | Coincidence, not a series |
| A series the user is clearly done with | Ask rather than assume it renews |

When it is genuinely ambiguous, ask in one sentence. Do not offer on every
calendar write - a follow-up offer after someone books a haircut is noise.

## Ground rules

- **This skill requires the `local-routine` skill.** The follow-up is registered
  through it, not written here. Use it at the agent level; do not reach into
  another skill's directory by path.
- **Offer, never schedule silently.** This arms an agent run that will act
  months from now. It always needs an explicit yes.
- **A follow-up with no source is theatre.** The future run starts with *zero*
  context. If you cannot say where the next schedule comes from, the run has
  nothing to do. Settle this before registering anything - see
  [Two kinds of follow-up](#two-kinds-of-follow-up).
- **A local routine fires in the first session opened on or after its due
  date**, not at an exact moment. If the user does not open Claude Code for a
  week, the follow-up surfaces a week late. Fine for "next semester's classes";
  slightly lossy for anything that has to land on the day.
- **Times are local wall-clock, not UTC.** `local-routine add --at` takes the
  user's local time. That is `terminus.py`'s `followup_at`, formatted exactly
  as `--at` wants it - pass it through unedited.
- **Check for an existing routine first, and amend rather than duplicate.**
  Re-running this after adding one more event (a new lab section, a moved
  class) must not leave two routines for the same series. `local-routine`'s
  `add` never deduplicates on its own; use `--replace <id>` once you have
  found the existing one with `list`. Two undeleted routines for one series
  both fire into the same future session, stale one first.
- **Say what will happen and when**, in the user's local time, before
  registering.

## Resolving script paths

`terminus.py` runs out of `$SKILL_DIR`, the directory this `SKILL.md` was read
from. That is **not** the working directory - the shell starts in the user's
project. Resolve it once and reuse it:

```bash
SKILL_DIR=/absolute/path/to/refresh-calendar   # the directory containing this SKILL.md
```

Installed as a Claude Code plugin, that path is `"$CLAUDE_PLUGIN_ROOT"`.

**Registering the routine needs `local-routine`'s directory too, which is a
different path.** Resolve it the same way, from wherever that skill's own
`SKILL.md` was loaded:

```bash
LOCAL_ROUTINE_SKILL_DIR=/absolute/path/to/local-routine
```

If `local-routine`'s `SKILL.md` has not been read yet, load it first - do not
guess this path from `refresh-calendar`'s own location. The two skills are
installed independently and are not guaranteed to sit next to each other.

## Workflow

### 1. Decide whether it applies

Apply the test above. If it does not, stop and say nothing - this skill should
be invisible for ordinary calendar work.

### 2. Find the last occurrence

Prefer **real occurrences** from the calendar over parsing a recurrence rule -
but only once the events exist. When the user is asking you to *create* a
recurring series right now, there is nothing on the calendar yet to read back,
so `--rrule` is the correct choice at that moment, not the fallback: expand it
first to know what you are about to create, create the events, then this step
is already answered. Reach for `--events`/`--dates` only when the series
already exists and you are computing its terminus after the fact - the
calendar server accounts for exceptions, cancellations and moved instances
that a hand-expanded rule cannot know about.

```bash
# Best: dates you already have, or from a list_events response
python3 "$SKILL_DIR"/scripts/terminus.py --events /tmp/events.json --tz America/Los_Angeles
python3 "$SKILL_DIR"/scripts/terminus.py --dates 2026-09-01T21:00:00-07:00 2026-09-08T21:00:00-07:00

# Fallback: only a rule is available
python3 "$SKILL_DIR"/scripts/terminus.py --rrule "FREQ=WEEKLY;BYDAY=TU;COUNT=14" \
  --dtstart 2026-09-01T18:00:00-07:00 --tz America/Los_Angeles
```

It returns `last_occurrence`, for showing the user, and `followup_at` - the
exact value to hand to `local-routine add --at` with no further editing.

**Always pass `--tz`.** Without it an RRULE is expanded against a fixed offset,
so every occurrence after a DST transition drifts by an hour. Autumn semesters
cross that boundary.

If the rule has neither `COUNT` nor `UNTIL` the series never ends, the script
exits 2, and there is nothing to follow up.

### 3. Establish where the next schedule comes from

Ask one question, and make it concrete: *when this ends, where does the next
one show up?* A registrar page, a league site, an email, or "I book it at the
appointment."

Their answer decides which kind of follow-up this is, and a vague answer is a
reason to keep asking rather than to guess. "The university website" is not
enough for a run that starts with no context; a URL is. If they genuinely do not
know, prefer a human-held follow-up that asks them, over a fetchable one aimed
at a guess.

### 4. Check for an existing routine, then register or amend

`local-routine`'s `add` never deduplicates, so list first:

```bash
python3 "$LOCAL_ROUTINE_SKILL_DIR"/scripts/local_routine.py list
```

If a routine already covers this series - same name, same prompt subject -
this is an amendment, not a new registration, because the terminus likely just
moved. Note its id.

Show the user the last occurrence, the follow-up moment in their local time,
and what the future run will do. On an explicit yes, register or amend through
the `local-routine` skill (its own `$SKILL_DIR`, not this skill's):

```bash
python3 "$LOCAL_ROUTINE_SKILL_DIR"/scripts/local_routine.py add \
  --at "2027-01-16T09:00" \
  --name "Refresh <series> after it ends" \
  --prompt "<the self-contained prompt>" \
  --tz America/Los_Angeles
```

Add `--replace <id>` to that same command when amending an existing routine
found above - it removes the old entry and adds the new one as one atomic
step, so there is never a moment with zero or two copies registered.

`--at` is `terminus.py`'s `followup_at` value, used exactly as returned - no
editing, no offset to strip. Write the prompt first - see
`references/composing.md` for what it has to contain.

### 5. Report back

Give the user the routine id that `local-routine` returned, and say plainly
that it surfaces in the first Claude Code session opened on or after that
date, not at a fixed hour on it.

**Do not report the follow-up as armed on the strength of `add` succeeding
alone.** `add` always returns a valid id and `next_due` whether or not
anything on this machine will ever run `check` - that depends on the
`local-routine` hook actually being registered, which is a separate fact.
If that has not already been confirmed this session, verify it per
`local-routine`'s own workflow step 1 before telling the user this is set.

## Two kinds of follow-up

The distinction changes what the future run's prompt should say.

**Fetchable** - the next schedule lives somewhere an agent can read: a registrar
page, a league site, an API. Capture the URL at scheduling time and bake it into
the prompt. The run can do the whole job: fetch, compare against the calendar,
add what is missing.

**Human-held** - the next date exists only in the user's head, or on a card in
their wallet, or in a phone call they have not made. The dentist case. The run
*cannot* fetch anything, so its prompt should ask rather than search: "You had a
cleaning on the 4th. Did you book the next one? Give me the date and I will add
it." Do not send an agent hunting for a URL that does not exist.

If it is human-held, say so when offering - the user should know they are
getting a smart reminder, not an automation.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/terminus.py` | Last occurrence of a series, and `followup_at` for the day after, ready to pass straight to `local-routine add --at`. Handles real occurrence lists and a common subset of RRULE. Stdlib only. |

## References

- **`references/composing.md`** - how to hand off to `local-routine`, and how to
  write a prompt that still works months later with no memory of this
  conversation. Read before registering anything.

## Interpreting results

- **The future run has no memory of this conversation.** Its prompt must be
  self-contained: which calendar, which search terms find the existing events,
  where the new schedule comes from, what to do when it is not there yet.
- **A follow-up months out will outlive some credentials.** OAuth connections
  and any API token the run depends on may have expired by then. Tell the run to
  report an auth failure loudly rather than exiting quietly, so a silent
  no-op is distinguishable from "nothing to do".
- **The new schedule may not be published on day one.** The day after a semester
  ends is a guess, not a guarantee. The prompt should say what to do when the
  source is empty - normally: tell the user, and suggest a date to retry.
- **The follow-up moment must be in the future.** The script reports
  `is_in_future`; a due date already past fires on the very next session, which
  is almost never what was meant.
- **Late is the normal failure mode, not missed.** A routine that came due while
  the user was away still fires, at the next session. Say "on or after", never
  "on".
