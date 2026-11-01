# The brief

The brief answers one question: **what does the user need to know today?** Not "what
arrived" and not "what the assistant did".

## Timing comes from ladders

When a commitment is learned (a booking confirmation, a planned meal, a bill), it is filed
silently and added to `upcoming.md` with a kind. The state's `ladders.md` maps each kind to
rungs - the points before the commitment when a reminder is useful. A row appears in the
brief only on the day one of its rungs comes due.

A dentist appointment booked six months out is invisible today. Fourteen days before, it
appears with what matters at that moment: "last easy chance to reschedule; their
cancellation window is 48 hours." The morning of, it appears again with the time.

Each rung says what is useful *at that rung*, not a repeat of the booking details.

## Sections

In this order. Omit any section with nothing in it.

1. **Today** - commitments happening today, with times. Meals, appointments, tickets.
2. **Coming up** - rows whose earlier rung came due today, each with the reason it is
   surfacing now ("in 14 days - reschedule window").
3. **Needs you** - proposals, questions, suspicious messages, run errors. Each with one
   link and the exact action being proposed.
4. **What I did** - one line: counts and a link to the log. In phase v0, "what I would
   have done", same format. Then "What I learned" if any rule changed, one line per rule.

## Style

- Lead with the answer. No greeting, no recap of the run.
- One line per item. Times in the user's local timezone, weekdays checked.
- Links on every item that has a source.
- On a quiet day: "Nothing on today. Nothing needs you." plus the one-line "What I did".

## Example

```
Today
- Movie, 7:15pm at AMC Metreon (tickets in Paper Trail)
- Chili tonight (thaw beef now if you haven't)

Coming up
- Dentist, Thu Nov 14 at 9am — 14 days out, last easy time to reschedule (48h cancellation)

Needs you
- Reply to the venue rental about Saturday's deposit? [thread]

Filed 23 · 1 calendar event · log
Learned: Luma invites you haven't registered for go to Feed (from your EA/Wrong on Oct 30)
```
