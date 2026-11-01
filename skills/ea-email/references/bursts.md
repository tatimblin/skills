# Bursts

Some services send several emails for one action. Set up a phone and Google sends a
new-sign-in alert, a "finish setting up" nudge and a data-sharing notice. Link a desktop
app and get three security alerts in ten seconds. Usually the whole burst was the user;
occasionally one message in it matters; rarely, the burst is an attack.

## Detecting a burst

Three or more messages from the same service (same sender domain, after stripping
per-message subaddresses like `no-reply-<random>@mail.example.com`) about the account
itself - sign-ins, devices, passkeys, passwords, app access, setup - within two hours.

## What to return

One entry for the whole burst, not one per message:

```json
{"burst": true, "service": "Claude", "window": "17:02-17:02", "count": 3,
 "summary": "2 new trusted devices and a passkey, all Electron on macOS",
 "outliers": [], "keep": [], "threads": ["<viewUrl>", "..."],
 "needs_you": "Was this you?"}
```

The brief shows it as one line under "Needs you".

## Outliers never get folded in

Pull these out of the burst and report each on its own, flagged:

- A sign-in from a new country, city or network the burst doesn't explain
- A password, recovery email or recovery phone change
- Failed sign-in attempts or a blocked sign-in
- Two-factor turned off, or backup codes generated
- Anything that asks the user to act urgently

A burst the user didn't cause looks like this, and it is exactly when these must be seen.

## Keep vs. file

- **Keep** (label `Paper Trail/Security`): third-party app access grants, account changes,
  backup or recovery information. These are records someone may need later - for example
  to know what to revoke.
- **File** (same label, nothing special): routine new-sign-in and new-device notices,
  setup nudges.

## Clearing a burst

Security mail is never filed on the model's judgment alone. One confirmation clears the
whole burst: the user answers "yes" to the brief line, or applies `EA/Good` to any one
message in it. Then file every message in the burst (in phases where filing is automatic)
and record the confirmation in the log.

## Learning noisy services

When the user confirms bursts from the same service repeatedly, add the service to the
state's list of known-noisy services in `domains/email.md`. Bursts from listed services
still need confirmation, but the brief line gets shorter and lower, below the day's real
items.
