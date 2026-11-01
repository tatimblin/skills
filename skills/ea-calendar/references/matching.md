# Matching, durations and timezones

## Is it already on the calendar?

Search the calendar from 3 hours before to 3 hours after the candidate's start. An event
matches if any of these hold:

- Same confirmation or booking number anywhere in its description.
- Same venue or address, starting within an hour of the candidate.
- Title shares the main noun with the candidate (the restaurant, the airline and flight
  number, the provider's name) and starts within an hour.

For flights, match on airline plus flight number alone - departure times shift.

When two events could match, treat it as a question for "Needs you", not a guess.

## Default durations

Use the confirmation's end time when it has one. Otherwise:

| Kind | Default |
|---|---|
| Restaurant reservation | 1.5 hours |
| Movie | Runtime if stated, else 2.5 hours |
| Show, concert, game | 3 hours |
| Appointment (dentist, doctor, haircut) | 1 hour |
| Flight | Scheduled departure to arrival, each in its own airport's timezone |
| Lodging | All-day events from check-in to check-out date |

## Timezones

- Use the timezone of the place: the venue's city, the departure airport, the hotel.
- A flight starts in the departure airport's zone and ends in the arrival airport's zone.
- If the confirmation gives only a time and the place's zone isn't clear, use the user's
  current timezone and say so in the ledger notes.

## Titles and descriptions

- Title: what and where, plainly. "Dinner at Flour + Water (2)", "Dentist", "UA 1234
  SFO→JFK".
- Location: the full address.
- Description: confirmation number, anything the user must bring or know (tickets, check-in
  time, cancellation window), then the marker line with the source link.

Never put payment details, account numbers or access codes in an event.
