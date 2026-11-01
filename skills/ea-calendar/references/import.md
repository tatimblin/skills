# Seeding the ledger from the calendar

A new ledger is empty, so the brief has nothing to remind about until new confirmations
arrive. The import fixes that by reading what's already on the calendar. Run it
interactively, when the user asks; never during an unattended run.

## Steps

1. **Read the window.** List events on the primary calendar from today through 90 days
   out. Page until the connector reports no more results.
2. **Drop what isn't a commitment.**
   - Recurring events (weekly meetings, classes, routines)
   - Events the user declined
   - All-day holidays and birthdays from subscribed calendars
   - Work meetings with many attendees
   - Focus or hold blocks ("Busy", "Hold", "Focus")
3. **Classify the rest** into a kind from the state's `ladders.md`, using title, location
   and description: Appointment, Reservation, Ticketed event, Flight, Lodging, and so on.
   If an event fits no kind, leave it out and list it in the summary instead of guessing.
4. **Compute the next rung** for each from `ladders.md`, relative to today. If every rung
   has already passed except morning-of, that's the next rung.
5. **Show the batch before writing.** A table: date, what, kind, next rung. Ask the user to
   confirm, or to drop or reclassify rows.
6. **Write once confirmed.** Add the rows to `upcoming.md`, soonest first, with the event
   link in the Calendar column and "imported" in Source. Commit with a message like
   `import: 7 commitments from calendar (next 90 days)`.

## What the summary says

- How many events were read, how many became rows, and how many were skipped and why
  ("31 recurring, 4 holidays").
- Anything left unclassified, so the user can add a kind to `ladders.md` if it's common.

Existing calendar events are never modified by the import; it only writes the ledger.
