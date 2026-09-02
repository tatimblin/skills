# The Volo GraphQL API

Endpoint, conventions, and where the data actually lives. Everything marked *verified* was
confirmed by live introspection on 2026-08-29 against the **anonymous** role - see
[Role-scoped schema](#role-scoped-schema) before trusting a field list.

## Contents

- [Endpoint](#endpoint)
- [Role-scoped schema](#role-scoped-schema)
- [Hasura conventions](#hasura-conventions)
- [The data model](#the-data-model)
- [Finding a user's games](#finding-a-users-games)
- [Scores and standings](#scores-and-standings)
- [Public data, no auth needed](#public-data-no-auth-needed)
- [Times and timezones](#times-and-timezones)

## Endpoint

```
https://www.volosports.com/hapi/v1/graphql
```

Hasura (`queryType` is `query_root`; a bare `GET` returns `PersistedQueryNotSupported`).
Subscriptions exist over `wss://` at the same path. `hapi` stands for "hasura api".
Override with `VOLO_GRAPHQL_URL`.

**Introspection is enabled and works without credentials.** That is the single most useful
fact in this document: you never have to trust a stale field list, including this one.

```bash
python3 "$SKILL_DIR"/scripts/volo.py introspect --search score
python3 "$SKILL_DIR"/scripts/volo.py introspect --type games
```

`api.volosports.com` is a separate Go REST service scoped to checkout and payments. It has
nothing you want; ignore it.

## Role-scoped schema

Hasura filters both rows *and columns* by role, so **the schema you see depends on who you
are**, and the difference is enormous. Measured by diffing the two live schemas on
2026-08-29:

| | Anonymous | `PLAYER` |
|---|---|---|
| Types with fields | 205 | **420** |

`PLAYER` gains 222 types anonymous cannot see, including everything to do with scores,
check-ins, chat, notifications, player strikes, and most `_aggregate` roots.

**Neither role is a superset of the other.** This is the trap. Anonymous sees a handful of
fields `PLAYER` cannot - `venues.state`, `venues.zip`, `leagues.mongo_id` - across 7 types.
So a query developed anonymously can fail once authenticated, which is the opposite of what
you would expect: `venueByVenue { state }` works anonymously and fails under `PLAYER` with
*"field 'state' not found in type: 'venues'"*.

Practical consequences:

- Always `introspect` **authenticated** before concluding a field does not exist.
  `volo.py introspect` uses stored credentials automatically and labels its output
  `authenticated` or `anonymous`.
- If a filter is rejected, try the relationship form:
  `where: {userByUser: {_id: {_eq: $userId}}}` instead of `where: {user: {_eq: $userId}}`.
  Both work on `game_rsvps` under `PLAYER`; only the relationship form works on
  `registrants` anonymously.
- Develop against the role you will run as. A query built anonymously is not guaranteed to
  work authenticated.
- The schema cache (24h) records which role produced it and refetches if you were
  anonymous and now have credentials.

## Hasura conventions

Standard generated Hasura, so it navigates predictably:

- Primary keys are `_id` of type `uuid`. `mongo_id` and `external_id` are migration
  leftovers from an older backend.
- Every table gets `table`, `table_by_pk(_id:)`, and usually `table_aggregate`.
- Filters are `where: table_bool_exp` with `_eq`, `_neq`, `_in`, `_nin`, `_gt`, `_gte`,
  `_lt`, `_lte`, `_is_null`, `_like`, plus `_and` / `_or` / `_not`.
- Sorting is `order_by: [table_order_by!]` with `asc` / `desc` / `asc_nulls_last`.
- Paging is `limit` / `offset`.
- **Foreign keys are named `<field>By<Field>`**: `leagueByLeague`, `venueByVenue`,
  `teamByTeam`, `sportBySport`, `userByUser`, `organizationByOrganization`. The bare name
  (`league`, `venue`, `team`) is the raw `uuid` column; the `By` form is the joined object.
  This trips people up constantly - `league` gives you a uuid, `leagueByLeague` gives you
  the league.
- Enums are real GraphQL enums, so quote them as bare words, not strings.
  `status: {_eq: registration_open}`, never `status: {_eq: "registration_open"}` - the
  latter fails with *"expected an enum value for type 'program_status_enum', but found a
  string"*.

`volo.py introspect --search` hides Hasura's generated plumbing types (`_bool_exp`,
`_aggregate`, `_select_column`, ...) so results stay readable. Pass `--all` to see them.

## The data model

The shape that matters, verified anonymously:

```
users ──< registrants >── leagues ──< games
  │            │            │           │
  │            └── teams ───┘           ├── venueByVenue → venues
  │                 │                   ├── weekByWeek
  └──< game_rsvps >─┴──< game_teams >───┘
```

| Table | Key fields (anonymous view) |
|---|---|
| `users` | `_id`, `email`, `first_name`, `last_name`, `full_name`, `username`, `has_volo_pass`, `most_recent_sport`, `registrants`, `game_rsvps`, `teamsByCaptainUser` |
| `leagues` | `_id`, `name`, `display_name`, `season`, `status`, `start_date`, **`timezone`**, `sport`, `sportBySport`, `venueByVenue`, `teams`, `games`, `weeks`, `deep_link`, `num_weeks_estimate` |
| `teams` | `_id`, `name`, `color_name`, `color_hex`, `leagueByLeague`, `registrants`, `game_teams`, `game_rsvps`, `gamesByWinner`, `gamesByForfeitter`, `userByCaptainUser` |
| `games` | `_id`, `start_time`, `end_time`, `start_time_str`, `end_time_str`, `field_name`, `is_tournament`, `leagueByLeague`, `venueByVenue`, `weekByWeek`, `teams`, `rsvps`, **`teamByWinner`**, **`teamByForfeitter`**, `deep_link` |
| `game_teams` | `_id`, `game`, `team`, `gameByGame`, `teamByTeam`, `rsvps` - the join row for the two teams in a game |
| `game_rsvps` | `_id`, `user`, `response`, `is_drop_in`, `gameByGame`, `teamByTeam`, `userByUser`, `registrantByRegistrant` |
| `registrants` | `_id`, `leagueByLeague`, `teams`, `groupByGroup`, `userByUser`, `waiver` - one row per league the user signed up for |
| `venues` | `_id`, `shorthand_name`, `formatted_address`, `street_address`, `city`, `state`, `zip`, `latitude`, `longitude`, **`timezone`**, `venue_map_url` |

`rsvp_response_enum` is `YES` / `NO` / `MAYBE` (verified).

## Finding a user's games

Two routes. Prefer the first for completeness, the second for speed.

### Route A - via registrants (complete)

Registrations are the source of truth for which leagues someone is in.

```
currentUser { _id }
  → registrants(where: {userByUser: {_id: {_eq: $userId}}}) { leagueByLeague { _id } teams { _id } }
    → games(where: {teams: {team: {_eq: $teamId}}}, order_by: {start_time: asc})
```

This catches every game on the user's team schedule whether or not they have RSVP'd.

### Route B - via RSVPs (fast, but partial)

```graphql
query MyGames {
  currentUser {
    _id
    game_rsvps {
      response
      gameByGame {
        _id start_time end_time field_name deep_link
        venueByVenue { shorthand_name formatted_address latitude longitude timezone }
        leagueByLeague { name timezone sportBySport { name } }
      }
    }
  }
}
```

One call, no `$userId` needed. **It only returns games with an RSVP row**, so a user who
has not responded to a fixture will not see it. Do not use this as the basis of "you have
no games this week" - that conclusion needs Route A.

### Upcoming vs past

Filter on `start_time`, which is a `timestamptz`:

```graphql
games(where: {start_time: {_gte: "2026-08-29T00:00:00Z"}}, order_by: {start_time: asc})
```

Do **not** infer "not yet played" from a missing score - see below.

## Scores and standings

**Numeric scores exist, but only under `PLAYER`.** They are invisible to anonymous
introspection, which makes it easy to conclude wrongly that Volo does not expose them.
Verified live on 2026-08-29.

`games.scores` is a relationship to `game_scores`:

```
type game_scores {
  _id: uuid!
  game: uuid!
  team: uuid!
  score: Int!
  forfeit: Boolean!
  gameByGame: games!
  teamByTeam: teams!
}
```

One row per team per game, so a played game has two. `games` also carries `winner: uuid`
and `teamByWinner: teams` directly, plus `forfeitter` / `teamByForfeitter`, so you can get
the outcome without doing the arithmetic yourself.

A working results query:

```graphql
query Results($userId: uuid!) {
  games(
    where: {
      teams: {teamByTeam: {registrants: {userByUser: {_id: {_eq: $userId}}}}}
      start_time: {_lt: "now()"}
    }
    order_by: {start_time: desc}
    limit: 25
  ) {
    start_time
    leagueByLeague { display_name timezone }
    teamByWinner { _id name }
    scores { score forfeit teamByTeam { _id name } }
  }
}
```

Match `scores[].teamByTeam._id` against the user's own team ids to split for/against.

**An empty `scores` array means no result was recorded** - not yet played, not yet scored,
or postponed. Check `start_time` before calling it a tie, and report "no result recorded"
rather than inventing a `0-0`.

**`"now()"` works as a `timestamptz` literal** (verified) - Postgres parses it server-side,
so you do not have to stamp the current time into the query yourself.

**Not every table exposes an aggregate, and which ones do depends on the role.**
`games_aggregate` does not exist anonymously but does under `PLAYER`. Check with
`introspect --operations` before reaching for one; counting client-side always works.

There is still no `standings` root field or `team_standings` table under `PLAYER`. Derive a
record from `teamByWinner` across played games, or from `teams.gamesByWinner_aggregate`.

## Public data, no auth needed

These work anonymously and are useful for browsing what is on offer:

- `discover_daily` / `discover_daily_aggregate` - the daily pickup/drop-in feed
- `leagues`, `venues`, `sports`, `organizations`, `neighborhoods`
- `dropinPricingForRegistration`

Row-level permissions still apply; anonymous sees public programs, not anyone's
registrations.

## Times and timezones

`start_time` and `end_time` are `timestamptz` in UTC. `start_time_str` / `end_time_str`
are pre-rendered local strings.

For anything calendar-shaped, convert UTC using **`leagueByLeague.timezone`** or
**`venueByVenue.timezone`** (both IANA names like `America/New_York`). Volo runs leagues in
many cities, so the machine's local timezone is the wrong assumption - a Boston league read
from a laptop in San Francisco is off by three hours.

`games.deep_link` and `leagues.deep_link` give links back into the Volo app, which make
good calendar-event URLs.
