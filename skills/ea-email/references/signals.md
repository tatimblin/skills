# Correction signals

Each signal compares what the assistant did with what the user did afterward. Report all
of them to the run loop before triage; it decides what becomes a rule
(`executive-assistant/references/learning.md`).

| Signal | How to find it | Strength |
|---|---|---|
| Wrong-marker | `label:EA-Wrong` | Explicit |
| Good-marker | `label:EA-Good` | Explicit |
| Moved back | Threads the last 7 days of logs list as filed out of the inbox, now carrying `INBOX` | Implicit |
| Label removed | Threads the logs list as labeled, now missing that label | Implicit |
| Flag ignored | Threads the last brief put under "Needs you" that are now archived with no reply from the user | Implicit |
| User archived | In the last snapshot's inbox, now out of it, and not moved by the assistant, a filter, or the expiry script (see below) | Implicit |
| User trashed | In the last snapshot, now carrying `TRASH` | Implicit, strong |
| User starred | In the last snapshot, now carrying `STARRED` | Implicit |
| User replied | A message from the user in the thread newer than the snapshot | Implicit |
| User labeled | Now carrying a user label it didn't have in the snapshot, added by no one else | Implicit, strong: the label is the answer |

For each, return:

```json
{"signal": "moved-back", "thread": "<viewUrl>", "from": "...", "subject": "...",
 "assistant_did": "paper-trail", "user_did": "returned to inbox", "run": "2026-11-01"}
```

## The user's own actions

What the user does with mail the assistant left alone is the best teacher: an archived
credit-score update says "this didn't need me," a reply says "this did." Gmail doesn't
record who archived a thread, so the assistant compares snapshots.

**The snapshot.** At the end of every process run, write `inbox.json` in the state:

```json
{"taken": "2026-11-01T08:20:00-08:00",
 "threads": {"<threadId>": {"from": "support@s.usa.experian.com", "subject": "...",
             "labels": ["CATEGORY_UPDATES", "UNREAD"], "bucket": "inbox (account alert)"}}}
```

Thread IDs, senders, subjects and label IDs only - never message bodies.

**The diff.** At the start of the next run, fetch each snapshot thread with
`get_thread` (`MINIMAL`) and compare:

1. Still in the inbox, unchanged: no signal.
2. Out of the inbox: rule out the other movers first. The assistant's own log for this
   window lists what it filed. The expiry script archives by age (`rules/inbox-expiry.gs`
   in the state: Feed 14 days, Feed/Events 10, Feed/GitHub CI 2, Promotions 7, everything
   else 30), so a thread past its age limit is the script's. Anything left was the user.
3. Record how: archived **unread** ("didn't need to open it") is stronger than archived
   after reading ("read it, done with it"); both say "doesn't need to stay in the inbox."

**What each teaches.** Generalize to the narrowest rule that covers the evidence - sender
plus kind of mail ("Experian score and usage updates"), not the whole sender if other
kinds from it are different (an Experian new-account alert is still a security alert).

| User did | Candidate rule |
|---|---|
| Archived, unread | Always-out (Paper Trail or the matching label); or marketing, if it's promotional |
| Archived after reading | Briefly visible, or always-out when it's a record |
| Trashed | Marketing with no keep value; propose an unsubscribe |
| Starred, replied | Keep in the inbox; mention in the brief |
| Labeled | File with that label from now on |

**The user is lazier than ideal storage, by design.** People archive bare, archive in
bulk, and leave things sitting. Read the signals that way:

- An archive answers "should this stay in the inbox?" - not "where should it be kept?"
  When the user archives a thread bare, the assistant still files it: add the label its
  bucket calls for (a reversible action), so it can be found later. Log it as tidied.
- Leaving something in the inbox is not a signal. Neither is not opening it.
- A bulk archive (10+ threads within a few minutes, or right after a long gap) is
  housekeeping, not judgment. Count it as one weak signal per sender, and never let it
  turn kept-in-inbox kinds (security, spend, people) into always-out.
- A label the user adds is worth more than anything else here, because it costs them
  effort.

The usual threshold applies: an implicit signal becomes a rule on its second consistent
occurrence, or the first when it agrees with an explicit answer the user already gave.
Never learn to file away security alerts, spend or billing alerts, or mail from anyone in
`people.md` from implicit signals alone - those need the user to say so.

## After learning

- Remove `EA/Wrong` and `EA/Good` once the loop has recorded the signal, so it isn't
  counted twice. Removing a label is reversible, so this is allowed in v1.
- For implicit signals, the log entry of this run is the record that the signal was seen;
  don't re-report a thread whose signal already appears in a log.
