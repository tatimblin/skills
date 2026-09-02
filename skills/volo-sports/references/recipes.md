# Recipes

Worked query chains for the things people actually ask for. These are starting points to
adapt, not a fixed API - read `graphql-api.md` for the conventions and use
`volo.py introspect` to confirm fields against the live schema.

All examples assume `$SKILL_DIR` is resolved and a credential is stored.

## Contents

- [Upcoming games for the calendar](#upcoming-games-for-the-calendar)
- [Weekly results pull](#weekly-results-pull)
- [Everything the user is registered for](#everything-the-user-is-registered-for)
- [Composing with other tools](#composing-with-other-tools)

## Upcoming games for the calendar

Two steps. First get the user id, then pull the schedule off their teams.

```bash
USER_ID=$(python3 "$SKILL_DIR"/scripts/volo.py whoami | python3 -c 'import json,sys; print(json.load(sys.stdin)["currentUser"]["_id"])')
```

Then every future game on every team they are on:

```bash
python3 "$SKILL_DIR"/scripts/volo.py query --var userId="$USER_ID" -q '
query UpcomingGames($userId: uuid!) {
  games(
    where: {
      teams: {teamByTeam: {registrants: {userByUser: {_id: {_eq: $userId}}}}}
      start_time: {_gte: "now()"}
    }
    order_by: {start_time: asc}
  ) {
    _id
    start_time
    end_time
    field_name
    deep_link
    is_tournament
    leagueByLeague { name timezone sportBySport { name } }
    venueByVenue {
      shorthand_name formatted_address city state
      latitude longitude timezone venue_map_url
    }
    teams { teamByTeam { _id name color_name } }
    rsvps(where: {user: {_eq: $userId}}, limit: 1) { response }
  }
}'
```

Everything a calendar event needs is in that one response: start/end, a title from
`leagueByLeague.name` plus `sportBySport.name`, a location from
`venueByVenue.formatted_address`, a URL from `deep_link`, and the two team names for the
description.

**Convert the times.** `start_time` is UTC. Use `venueByVenue.timezone` (falling back to
`leagueByLeague.timezone`) rather than the local machine's zone - see
[Times and timezones](graphql-api.md#times-and-timezones).

If the `rsvps` sub-filter is rejected, the scalar `user` column is not visible to your
role; use `rsvps(where: {userByUser: {_id: {_eq: $userId}}}, limit: 1)` instead.

## Weekly results pull

Games that have already happened, with the score. **`scores` requires the `PLAYER` role** -
it is invisible to anonymous introspection.

```bash
python3 "$SKILL_DIR"/scripts/volo.py query --var userId="$USER_ID" -q '
query Results($userId: uuid!) {
  games(
    where: {
      teams: {teamByTeam: {registrants: {userByUser: {_id: {_eq: $userId}}}}}
      start_time: {_lt: "now()"}
    }
    order_by: {start_time: desc}
    limit: 25
  ) {
    _id
    start_time
    leagueByLeague { display_name timezone sportBySport { name } }
    teamByWinner { _id name }
    scores { score forfeit teamByTeam { _id name } }
  }
}'
```

`scores` has one row per team. Match `teamByTeam._id` against the user's own team ids
(from `MyRegistrations` below) to split for/against:

```python
mine  = next(x for x in g["scores"] if x["teamByTeam"]["_id"] in my_team_ids)
them  = next(x for x in g["scores"] if x is not mine)
result = "W" if mine["score"] > them["score"] else "L" if mine["score"] < them["score"] else "T"
```

`games.teamByWinner` gives the same verdict without the arithmetic, and `forfeit` on either
row flags a forfeit.

**An empty `scores` array is not a tie.** It means no result was recorded - not yet played,
not yet scored, or postponed. Check `start_time` and say "no result recorded" rather than
reporting `0-0`.

## Everything the user is registered for

Leagues, teams, and season status in one call - useful as an orientation step before
anything else:

```bash
python3 "$SKILL_DIR"/scripts/volo.py query --var userId="$USER_ID" -q '
query MyRegistrations($userId: uuid!) {
  registrants(where: {userByUser: {_id: {_eq: $userId}}}) {
    _id
    leagueByLeague {
      _id name display_name season status start_date timezone
      sportBySport { name }
      venueByVenue { shorthand_name city }
    }
    teams { _id name color_name }
    groupByGroup { _id name }
  }
}'
```

Drop-in and pickup games are registered separately from league play and will not show up
here. Look at `game_rsvps` with `is_drop_in: {_eq: true}`, or the `drop_in_slots` tables,
if the user plays pickup.

## Composing with other tools

This skill deliberately stops at returning JSON. Wiring it to a calendar, a spreadsheet,
or a notification is the agent's job, using whatever tools it already has.

**Calendar sync.** Run `UpcomingGames`, convert each `start_time` to the venue timezone,
then create events with whatever calendar tool is available. Use the game `_id` as a stable
key so re-runs update rather than duplicate - the same fixture keeps its id when a time
changes. Check for an existing event before creating one; a weekly job that blindly inserts
will pile up duplicates.

**Weekly digest.** Run `RecentResults` on a schedule and summarise. Re-run
`UpcomingGames` in the same pass so the digest covers both directions.

**Before scheduling anything unattended**, confirm `volo.py auth status` reports
`"unattended_capable": true`. If it is false, only a short-lived access token is stored and
the job will start failing within the day.

For a **Google/Apple SSO account that is permanently false** - the refresh token is held
server-side and cannot be obtained from the browser at all. Do not promise a weekly job to
an SSO user without saying it needs a daily re-paste. See
[Getting the first credential](auth.md#getting-the-first-credential).

Be a good client: these are ordinary sequential requests against someone's own account, so
run them on a human cadence. There is no documented rate limit, which is a reason for
restraint rather than a licence.
