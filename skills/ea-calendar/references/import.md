# Seeding the ledger

A new ledger is empty, so the brief has nothing to remind about until new confirmations
arrive. The import fixes that by reading what already exists - on the calendar **and in
the mailbox**. Run it interactively, when the user asks; never during an unattended run.

Both sources matter. Plenty of commitments live only as an email: an appointment booked at
the last visit, six months out, that never made it onto the calendar. Those are exactly the
ones a reminder ladder exists for.

## Window

Look **12 months ahead** on both sources. Appointments are routinely booked six months out,
and a shorter window drops them silently.

## Steps

1. **Read the calendar.** List events on the primary calendar from today through 12 months
   out. Page until the connector reports no more results.
2. **Read the mail.** Search the last 12 months for confirmation-shaped messages (see
   below) and keep only those whose commitment date is still in the future. When a booking
   has several emails (scheduled, reminder, rescheduled), the latest one wins; a
   cancellation removes it.
3. **Merge the two.** Match mail findings against calendar events with
   `references/matching.md`. A match is one commitment: link both the event and the email.
   A mail finding with no event is a commitment missing from the calendar - mark it so the
   summary can offer to add the event.
4. **Drop what isn't a commitment.**
   - Recurring events (weekly meetings, classes, routines)
   - Events the user declined
   - All-day holidays and birthdays from subscribed calendars
   - Work meetings with many attendees
   - Focus or hold blocks ("Busy", "Hold", "Focus")
5. **Classify the rest** into a kind from the state's `ladders.md`, using title, location
   and description: Appointment, Reservation, Ticketed event, Flight, Lodging, and so on.
   If one fits no kind, leave it out and list it in the summary instead of guessing.
6. **Compute the next rung** for each from `ladders.md`, relative to today. If every rung
   has passed except morning-of, that's the next rung.
7. **Show the batch before writing.** A table: date, what, kind, next rung, and whether it
   is on the calendar. Ask the user to confirm, drop or reclassify rows, and whether to add
   the missing ones to the calendar.
8. **Write once confirmed.** Add the rows to `upcoming.md`, soonest first, with links to
   the event and the email. Create calendar events for the missing ones the user approved,
   with the assistant marker. Commit with a message like
   `import: 7 commitments (5 calendar, 2 mail-only), next 12 months`.

## Finding confirmations in mail

Search by shape, not by sender - you don't know the user's providers yet:

```
newer_than:1y (subject:(appointment OR reservation OR booking OR confirmed OR confirmation
OR itinerary OR "your order" OR tickets) OR "appointment has been scheduled" OR
"see you on" OR "check-in")
```

Read only the plain-text body of likely hits, and only to extract the date, time, place,
provider and any reschedule or cancellation details. Skip receipts for things already
delivered or attended.

## What the summary says

- How many calendar events and emails were read, how many became rows, and how many were
  skipped and why ("31 recurring, 4 holidays").
- Which commitments exist only in mail, with the offer to add them to the calendar.
- Anything left unclassified, so the user can add a kind to `ladders.md` if it's common.

Existing calendar events are never modified by the import. It writes the ledger, and adds
calendar events only for mail-only commitments the user approved.
