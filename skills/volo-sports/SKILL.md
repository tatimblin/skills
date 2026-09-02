---
name: volo-sports
description: Read a Volo Sports account's leagues, schedules, teammates and results through Volo's undocumented Hasura GraphQL API. Handles the login credential, refreshes tokens automatically, and navigates the live schema by introspection so queries are composed against what the API actually exposes rather than a stale guess. Use when someone wants their Volo schedule or game results pulled, upcoming games added to a calendar, a recurring or weekly check on scores and standings, or any question about what a Volo account is registered for; also use when asked how to authenticate against volosports.com or how to query the Volo API.
---

# Volo Sports data access

Volo publishes no API and no docs, but the player dashboard runs on an ordinary Hasura
GraphQL endpoint with introspection left on. This skill handles the credential and gives
you a way to explore the schema, so you can compose whatever query the task needs.

It deliberately ships no feature commands. There is no `sync-calendar` here - fetching the
data is the hard part, and what happens next is yours to decide with the tools you already
have.

## Ground rules

- **The user's own account, only.** Every credential here belongs to one person and
  authorises their data. Do not use it to enumerate other players, and do not accept a
  credential that is not the user's. Volo's terms specifically prohibit accessing another
  account and collecting other users' personal information without consent.
- **Rosters are other people's data.** Teammate names, emails and phone numbers come back
  attached to games and teams. Use what the task needs and no more; never bulk-collect or
  export a roster because it happened to be in the response.
- **Read-only unless asked.** The schema exposes mutations that RSVP, register, and pay.
  Never fire one as a side effect of a read. Confirm explicitly first.
- **Report what is missing rather than filling it in.** An empty schedule means the query
  found nothing, which is a finding - not "you have no games". Numeric scores may not be
  exposed at all; say so instead of reporting `0-0`.
- **The API is undocumented and unversioned.** Volo is mid-migration between frontends.
  When something does not match this documentation, trust `introspect` and say the docs
  drifted.

## Resolving script paths

Every command below runs a script out of `$SKILL_DIR`, the directory this `SKILL.md` was
read from. That is **not** the working directory - the shell starts in the user's project.
Resolve it once, before the first command, and reuse it verbatim:

```bash
SKILL_DIR=/absolute/path/to/volo-sports     # the directory containing this SKILL.md
```

Installed as a Claude Code plugin, that path is `"$CLAUDE_PLUGIN_ROOT"`. Invoking the
script by bare relative path works only if the shell happens to already be in the skill
directory; do not rely on it.

## Workflow

### 1. Explore before authenticating

Introspection needs no credentials, so schema questions can be answered before asking the
user for anything:

```bash
python3 "$SKILL_DIR"/scripts/volo.py introspect --search game
python3 "$SKILL_DIR"/scripts/volo.py introspect --type games
python3 "$SKILL_DIR"/scripts/volo.py introspect --operations
```

Public data is also readable anonymously - pass `--anon` to `query` for league and venue
browsing that does not involve anyone's account.

### 2. Check what is already stored

```bash
python3 "$SKILL_DIR"/scripts/volo.py auth status
```

If `access_token_valid` is true, go straight to querying. Look at `unattended_capable`
before promising anything scheduled: it is false when only a short-lived access token is
stored, and a weekly job will silently start failing within the day.

### 3. Authenticate, if needed

Volo has no password grant for SSO accounts and this skill never drives a browser, so the
user fetches one value by hand. Print the instructions rather than paraphrasing them:

```bash
python3 "$SKILL_DIR"/scripts/volo.py auth bootstrap --help-only
```

Then take the paste on stdin, so it stays out of shell history and out of the transcript:

```bash
python3 "$SKILL_DIR"/scripts/volo.py auth bootstrap --stdin
```

**What is obtainable depends on how the account signs in**, so establish that first
rather than promising unattended runs you cannot deliver:

- **Password account** - use `auth login --email ...` instead. It returns a ~90-day
  refresh token, so scheduled jobs work. The password is used once and never stored.
- **Google/Apple SSO** - ask whether they *also* know a Volo password before giving up on
  unattended runs. The two are not exclusive, and `auth login` works whenever a password
  exists regardless of how they usually sign in.
- **SSO with no password** - only a ~12-hour access token is reachable. Volo keeps the
  refresh token server-side in a sealed HttpOnly cookie, so it is genuinely not in the
  browser and no amount of devtools hunting will find it. Say so plainly instead of sending
  the user looking, and tell them scheduled runs need a daily re-paste.

Either way the command verifies the credential against the live API before storing it, and
refuses anything that does not work.

Confirm with `whoami`, which is the real end-to-end test:

```bash
python3 "$SKILL_DIR"/scripts/volo.py whoami
```

### 4. Compose queries

```bash
python3 "$SKILL_DIR"/scripts/volo.py query --var userId="$USER_ID" -q 'query ...'
python3 "$SKILL_DIR"/scripts/volo.py query --file schedule.graphql --var userId="$USER_ID"
```

`--var` is JSON-aware, so `--var limit=10` is a number and `--var name=Tuesday` is a
string. Token refresh is automatic; there is no need to check expiry first.

Start from `references/recipes.md` rather than writing from scratch - the useful chains
are already worked out there.

### 5. Re-introspect when something breaks

A query that used to work and now fails is the expected failure mode of an unversioned
API. Confirm against the live schema before assuming the data is gone:

```bash
python3 "$SKILL_DIR"/scripts/volo.py introspect --refresh --type games
```

The schema is cached for 24 hours; `--refresh` bypasses it.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/volo.py` | Credential storage, automatic token refresh, arbitrary GraphQL, and schema navigation. Stdlib only. |

Subcommands: `auth bootstrap` / `auth status` / `auth logout`, `whoami`, `query`,
`introspect`. Tokens are never printed by any of them.

## References

- **`references/graphql-api.md`** - the endpoint, Hasura conventions, the data model, and
  where games and results actually live. Read before composing any query by hand.
- **`references/auth.md`** - the two-token model, `webRefresh`, credential storage, and
  the Cloudflare and expiry traps. Read when auth misbehaves or before setting up
  anything scheduled.
- **`references/recipes.md`** - worked query chains for upcoming games, results, and
  registrations, plus notes on wiring them to a calendar. Read first for any
  schedule-shaped or scores-shaped request.

## Interpreting results

Traps worth knowing before you report anything:

- **The schema depends on who you are, and neither role is a superset.** `PLAYER` sees 420
  types to anonymous's 205, but anonymous sees a few fields `PLAYER` cannot
  (`venues.state`, `venues.zip`, `leagues.mongo_id`). A query developed anonymously can
  fail once authenticated. Develop against the role you will run as.
- **Scores are `PLAYER`-only.** `games.scores` -> `game_scores { score, forfeit, team }`
  is invisible to anonymous introspection, so do not conclude from an anonymous look that
  Volo hides point totals. `games.winner` / `teamByWinner` give the outcome directly.
- **An empty `scores` array is not a tie.** It means no result was recorded: not yet
  played, not yet scored, or postponed. Check `start_time` before interpreting.
- **`league` and `leagueByLeague` are different fields.** The bare name is a `uuid`; the
  `By` form is the joined object. Same for `venue`, `team`, `sport`, `user`.
- **Enums are bare words, not strings.** `status: {_eq: registration_open}`. Quoting it
  fails with *"expected an enum value ... but found a string"*.
- **`"now()"` works as a timestamptz literal**, so upcoming/past splits do not need a
  client-side timestamp.
- **Times are UTC; venues are not.** Convert with `venueByVenue.timezone` or
  `leagueByLeague.timezone`. Volo runs leagues in many cities and the machine's local zone
  is usually the wrong one.
- **RSVP-based queries are incomplete.** `currentUser { game_rsvps { ... } }` is one fast
  call but only returns games the user has responded to. For "what is on my schedule", go
  through `registrants` and team games instead.
- **A 403 is Cloudflare, not auth.** Real auth failures come back as HTTP 200 with a
  GraphQL `errors` array. A 403 means the User-Agent was rejected before Hasura saw it.
