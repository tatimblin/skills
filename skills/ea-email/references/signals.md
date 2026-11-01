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

For each, return:

```json
{"signal": "moved-back", "thread": "<viewUrl>", "from": "...", "subject": "...",
 "assistant_did": "paper-trail", "user_did": "returned to inbox", "run": "2026-11-01"}
```

## After learning

- Remove `EA/Wrong` and `EA/Good` once the loop has recorded the signal, so it isn't
  counted twice. Removing a label is reversible, so this is allowed in v1.
- For implicit signals, the log entry of this run is the record that the signal was seen;
  don't re-report a thread whose signal already appears in a log.
