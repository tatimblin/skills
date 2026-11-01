# Advisor contract

An advisor knows one source and one domain - meals, training, bills - and reports to the
executive assistant. It never addresses the user directly. That keeps the brief one voice
instead of a stack of reports, and lets the ledger and ladders decide timing for every
domain the same way.

## What every advisor declares

Each advisor keeps a note at `advisors/<name>.md` in the state with this table at the top:

| Field | Meaning |
|---|---|
| Signals it reads | Where its information comes from: a connector, an API, files in the state, or a question asked through the brief |
| Decisions it makes | The closed set of things it can conclude |
| Actions and limits | What it may do automatically vs. propose; always within `autonomy.md` |
| Hand-off to the brief | What it adds to `upcoming.md` (with a kind from `ladders.md`) or to "Needs you" |
| Graduation target | What, if anything, can become a deterministic rule; often "none" |

## How it plugs into the run

1. In step 3, the assistant runs each advisor whose note is present and whose skill (or
   instructions) is available.
2. The advisor returns ledger candidates and proposals, never actions taken.
3. Questions for the user (for example "What's for dinner this week?") go under "Needs
   you" in the brief; the user's reply is read on the next run.
4. Anything the advisor learns goes in its own note's "Notes" section, following
   `learning.md`.

## Example: chef

| Field | Chef |
|---|---|
| Signals it reads | The user's reply to a weekly question; recipe notes in the state; the calendar for nights out |
| Decisions it makes | Which meal on which night; leftover nights; the shopping list; prep reminders |
| Actions and limits | Write the plan and list to the state (automatic); add meal rows to the ledger |
| Hand-off to the brief | Weekly: the list. Morning-of: tonight's meal. Night before: prep, if the recipe needs it |
| Graduation target | None |

An advisor with no API at all - like the chef - is the best test of a new design. If the
contract fits a conversation and a folder of recipes as well as it fits an inbox, it will
fit anything.
