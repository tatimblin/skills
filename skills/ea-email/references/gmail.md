# Working with Gmail

Assumes a Gmail connector exposing thread search, thread reads, and label changes.

## Queries

| Need | Query |
|---|---|
| New in the inbox since the last run | `in:inbox after:YYYY/MM/DD` using the last run's date, then drop threads already in the log |
| Corrections | `label:EA-Wrong` and `label:EA-Good` (Gmail search writes `/` in label names as `-`) |
| A sender's recent mail | `from:example.com newer_than:30d` |
| Unread only | add `is:unread` |

`after:` is inclusive and evaluated at midnight, so it over-collects by part of a day.
That's intended; the log check removes repeats.

## Views

- Search with the summary view (latest message per thread, with sender, subject, snippet
  and link). That decides most threads.
- Read a full thread as plain text only when the decision needs the body.
- Use the `viewUrl` each result returns as the link in the log and brief. Don't build
  links by hand.

## Labels

- Use label names exactly as `domains/email.md` writes them. Look up label ids with the
  connector's list-labels tool before applying one.
- "File to a bucket" means apply the bucket's label and remove `INBOX` (archive). Feed and
  Promotions mail stays in the inbox; the expiry script archives it later.
- The correction labels are `EA/Wrong` and `EA/Good`. Create them if missing - that's a
  reversible action, allowed in v1 and proposed in v0.

## Things not to do

- Don't use trash, spam, send, forward, reply, or draft tools.
- Don't change category labels (`CATEGORY_*`) to move mail between tabs.
- Don't page through thousands of old threads. This skill handles what arrived since the
  last run.
