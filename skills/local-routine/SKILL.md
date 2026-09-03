---
name: local-routine
description: Schedule a prompt against a cron expression and have it surface in the next Claude Code session on this machine, using a SessionStart hook and a local JSON store. Cron is evaluated in local wall-clock time and survives DST, and routines never expire. Use when someone wants a recurring or one-off reminder that needs the local machine - files, Keychain, the LAN, a local database - or asks why a `/schedule` routine cannot see their laptop, or wants something remembered further out than the seven days `CronCreate` allows.
---

# Local routines

`/schedule` runs routines in Anthropic's cloud. That environment has no access
to this machine: not the filesystem, not the Keychain, not the LAN, not any
local service. `CronCreate` does reach the local session but is session-scoped
and expires after seven days. Neither can answer "every June 11th, from this
laptop".

This skill fills that gap. A prompt is registered against a cron expression in a
JSON file, and a `SessionStart` hook checks that file every time a Claude Code
session starts here. When a routine has come due, its text is surfaced into the
session.

The tradeoff is honest and worth stating up front: nothing fires while no
session is running. A routine due at 08:57 surfaces in the first session started
at or after 08:57, which may be days later.

## Ground rules

- **`check` prints nothing unless a routine is due.** A `SessionStart` hook has
  its stdout injected verbatim into the context window. One stray newline or
  debug line becomes garbage in every session on this machine. Never add
  printing to `check`, and never route diagnostics anywhere but stderr.
- **Surface once, then clear.** State advances at inject time. There is no
  acknowledgement step, so if the session ends before the routine is acted on,
  it is gone. `local-routine log` is the only record that it fired.
- **The stored text is a note, not an order.** What `check` prints is a factual
  statement that a routine came due and what its text says. Treat it the way you
  would treat the user typing that text, and confirm before doing anything
  destructive or irreversible on the strength of it alone.
- **Cron is local time here.** `/schedule` interprets cron in UTC. This skill
  interprets it in the routine's own IANA zone, defaulting to the system zone.
  Never copy a cron expression between the two without re-checking the hour.
- **State lives in `~/.config/local-routine/`, never in the skill directory.**
  `${CLAUDE_PLUGIN_ROOT}` changes on every plugin update, so anything written
  there is lost. Point `LOCAL_ROUTINE_HOME` elsewhere only for testing.
- **Hook changes need `/reload-plugins`.** Edits to this `SKILL.md` take effect
  immediately; edits to `hooks/hooks.json` do not.

## Resolving script paths

Every command below runs a script out of `$SKILL_DIR`, the directory this
`SKILL.md` was read from. That is **not** the working directory - the shell
starts in the user's project. Resolve it once, before the first command, and
reuse it verbatim:

```bash
SKILL_DIR=/absolute/path/to/local-routine     # the directory containing this SKILL.md
```

Installed as a Claude Code plugin, that path is `"$CLAUDE_PLUGIN_ROOT"`.
Invoking the script by bare relative path works only if the shell happens to
already be in the skill directory; do not rely on it.

## Workflow

### 1. Confirm the hook is actually registered

Registering a routine is pointless if nothing runs `check`. **A missing settings
entry does not by itself mean "fine, plugin rail" - it looks identical to "not
installed at all".** Treat it as unconfirmed, not as reassurance, and check
positively rather than by absence.

```bash
claude plugin details local-routine 2>&1
```

If that reports the plugin installed, the hook is live via the plugin rail -
confirmed, move on. If it reports the plugin not found, check the other rail:

```bash
grep -A5 '"SessionStart"' ~/.claude/settings.json 2>/dev/null | grep -q local_routine \
  && echo "registered manually" || echo "NOT REGISTERED on either rail"
```

If **neither** check finds it, tell the user plainly before registering
anything: *"I cannot confirm the hook that fires these is installed, so nothing
will surface until it is"* - then read `references/hooks.md` and add the manual
entry. **Do not report a routine as armed on the strength of `add` succeeding
alone.** `add` always succeeds and always returns a valid `next_due`, whether or
not anything on this machine will ever call `check`.

### 2. Decide recurring or one-shot

A recurring routine takes `--cron` and re-arms itself after every firing. A
one-shot takes `--at` and deletes itself once surfaced. Ask which one the
request means when it is ambiguous: "remind me about the lease in March" is
almost always one-shot, and "check the backups on Mondays" is not.

### 3. Register it

```bash
python3 "$SKILL_DIR"/scripts/local_routine.py add \
  --cron "57 8 11 6 *" \
  --name Birthday \
  --prompt "Wish Tristan a happy birthday."

python3 "$SKILL_DIR"/scripts/local_routine.py add \
  --at "2027-06-11T08:57" \
  --prompt "Renew the domain before it lapses."
```

`--cron` and `--at` are mutually exclusive and exactly one is required. `--tz`
takes an IANA name and defaults to the system zone. `--at` takes a local
wall-clock time with no offset and refuses a time in the past.

**Write the prompt as the instruction the future session should read**, not as a
description of the schedule. "Wish Tristan a happy birthday" is useful when it
surfaces; "birthday reminder" is not.

**Read back the computed `next_due` to the user.** It is the single best check
that the cron expression means what they said, and it catches the local-time
versus UTC confusion immediately.

**Cron cannot express "every N weeks" or "every N days" - do not fake it with
`*/N` on day-of-month.** `*/14` does not mean every 14 days; it means the 1st,
15th and 29th of every month, which resets at each month boundary and produces
a 2-3 day gap instead of a clean interval. There is no field for a rolling
period in standard cron.

The honest fix is a chained one-shot: register `--at` for the next occurrence,
with a prompt that both does the task and asks the user whether to schedule the
one after that. State the tradeoff plainly when you do this: it is not a real
recurrence, it is a hand-relinked chain, and **it breaks permanently the first
time a fired link is missed** - a one-shot deletes itself on firing regardless
of whether anyone re-registered the next one. Prefer this only when the user
confirms an approximate interval is fine; if they need it exact, say cron
cannot do it and suggest a shorter true interval instead (weekly, checked by
the prompt itself for whether N weeks have passed).

**Amending an existing routine is `add --replace <id>`, not a second `add`.**
There is no separate update command, and `add` never deduplicates - registering
the same series twice leaves two routines in the store and both fire into the
same session, oldest and stalest first. If the request is "add one more thing
to the thing you already scheduled" rather than a genuinely new routine, find
its id with `list` and replace it:

```bash
python3 "$SKILL_DIR"/scripts/local_routine.py add --replace a1b2c3 \
  --at "2027-06-12T09:00" --name Birthday --prompt "..."
```

`--replace` removes the old id and adds the new entry as one atomic step, so
there is never a moment with zero or two copies registered.

### 4. Inspect and prune

```bash
python3 "$SKILL_DIR"/scripts/local_routine.py list
python3 "$SKILL_DIR"/scripts/local_routine.py log
python3 "$SKILL_DIR"/scripts/local_routine.py remove a1b2c3
```

`list` shows what is registered with each next-due time rendered in the
routine's own zone. `log` shows what has already fired, which is the only way to
discover a routine that surfaced into a session that ended before it was acted
on.

### 5. Prove it will actually fire, on request

A returned `next_due` proves the schedule is right; it proves nothing about
delivery. **A `check` against a fresh empty store proves nothing either** - an
empty store is silent by design, and silence there is not evidence of
anything. To demonstrate the real mechanism without touching the user's store:

```bash
export LOCAL_ROUTINE_HOME=$(mktemp -d)
python3 "$SKILL_DIR"/scripts/local_routine.py add \
  --at "2099-01-01T09:00" --prompt "This is a test fire." --name ProofTest
python3 -c "
import json, pathlib
p = pathlib.Path('$LOCAL_ROUTINE_HOME') / 'routines.json'
s = json.load(open(p))
s['routines'][0]['next_due'] = '2020-01-01T00:00:00-08:00'
json.dump(s, open(p, 'w'))
"
python3 "$SKILL_DIR"/scripts/local_routine.py check
unset LOCAL_ROUTINE_HOME
```

That prints the actual text a `SessionStart` hook would inject - fenced,
attributed to the local-routine skill, with its recurring-or-deleted fate
stated. Show the user this output, not just the registration's `next_due`, when
they ask "will this really work".

### 6. Leave `check` to the hook in real use

```bash
python3 "$SKILL_DIR"/scripts/local_routine.py check
```

Running this against the **real** store (no `LOCAL_ROUTINE_HOME` override) is a
legitimate way to test, but understand what it does: any due routine fires and
clears for real, exactly as if a session had started. Prefer step 5's
throwaway-store proof for demonstrations.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/local_routine.py` | The whole skill: cron evaluation, the routine store, and the hook entrypoint. Stdlib only. |

Subcommands: `add` (with `--replace <id>` to amend atomically), `list`,
`remove`, `check`, `log`. Only `check` is meant to be run by machine, and only
it ever prints anything other than JSON.

## References

- **`references/hooks.md`** - registering the hook on each install rail, the
  `settings.json` form for the skills.sh rail, the supported cron syntax
  including the day-of-month and day-of-week OR rule, and why the store lives in
  `~/.config/`. Read before installing, before editing `hooks/hooks.json`, and
  any time a routine did not surface when it should have.

## Interpreting results

Traps worth knowing before reporting anything to the user:

- **Silence from `check` is success, not failure.** It is the expected output on
  the overwhelming majority of session starts. Do not go looking for a problem
  because nothing printed.
- **A routine that did not surface is usually an unregistered hook**, not a bad
  cron expression. Check `list` first: if `next_due` is in the past, the
  schedule was computed fine and nothing ran `check`.
- **Day-of-month and day-of-week OR together when both are restricted.**
  `0 0 13 * 5` means the 13th **or** any Friday, not Friday the 13th. This is
  standard cron and it surprises almost everyone. Warn the user when their
  expression restricts both fields.
- **The next-due time is computed once, at registration.** Changing the system
  timezone afterwards does not retroactively move an existing routine, because
  each routine stores its own zone.
- **A wall-clock time is held across DST, so the UTC offset moves.** A
  routine at 08:57 stays at 08:57 through November and March; its stored offset changes
  from `-07:00` to `-08:00`. That is correct, not drift.
- **A one-shot disappears from `list` the moment it fires.** If the user asks
  where it went, `log` has it.
- **`last_fired` records when `check` surfaced it, not when it was due.** Those
  differ by however long the machine went without a Claude Code session.
- **A corrupt store is silent by design.** `check` prints nothing and exits 0,
  but `list` and `add` will refuse loudly rather than overwrite it. If `add`
  complains about the store, do not delete the file; move it aside so the
  routines in it can be recovered.
