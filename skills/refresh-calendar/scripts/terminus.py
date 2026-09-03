#!/usr/bin/env python3
"""Find the last occurrence of a calendar series and the follow-up moment after it.

Given the occurrence times of a series, report when the series ends and the
UTC timestamp to schedule a follow-up for.

  # Preferred: real occurrences, e.g. from Google Calendar list_events
  terminus.py --dates 2026-09-01T21:00:00-07:00 2026-09-08T21:00:00-07:00

  # From a JSON file or stdin: a list of ISO strings, or objects with a
  # "start"/"startTime"/"start.dateTime" field (list_events output works as-is)
  terminus.py --events events.json
  terminus.py --events -

  # Fallback: expand an RRULE when you only have the rule
  terminus.py --rrule "FREQ=WEEKLY;BYDAY=TU;COUNT=14" --dtstart 2026-09-01T21:00:00-07:00

Prefer real occurrences over --rrule. The calendar server is authoritative and
already handles exceptions, cancellations and moved instances; this expander
does not.

Emits JSON on stdout. Exits 2 if the series has no computable end.
"""

import argparse
import datetime
import json
import re
import sys
import zoneinfo

MAX_EXPAND = 2000  # refuse to expand unbounded rules forever

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _die(m, code=1):
    print("[error] " + m, file=sys.stderr)
    sys.exit(code)


def parse_dt(s):
    """Parse an ISO 8601 timestamp. Accepts a trailing Z."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        # Date-only (all-day events) - treat as midnight
        try:
            d = datetime.datetime.fromisoformat(s + "T00:00:00")
        except ValueError:
            return None
    return d


def _dig_start(obj):
    """Pull a start time out of a calendar-event-shaped dict."""
    if isinstance(obj, str):
        return parse_dt(obj)
    if not isinstance(obj, dict):
        return None
    for key in ("start", "startTime", "start_time", "dateTime", "date"):
        v = obj.get(key)
        if isinstance(v, str):
            d = parse_dt(v)
            if d:
                return d
        if isinstance(v, dict):
            for k2 in ("dateTime", "date"):
                if isinstance(v.get(k2), str):
                    d = parse_dt(v[k2])
                    if d:
                        return d
    return None


def collect_from_events(payload):
    """Accept a list of events, or an object with an events/items list."""
    if isinstance(payload, dict):
        for key in ("events", "items", "data"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        _die("--events needs a JSON list of events (or {events: [...]})")
    out = []
    for e in payload:
        d = _dig_start(e)
        if d:
            out.append(d)
    return out


def expand_rrule(rule, dtstart):
    """Expand the common subset of RFC 5545 RRULE. Deliberately limited."""
    parts = {}
    for chunk in rule.replace("RRULE:", "").split(";"):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.upper()] = v.upper()

    freq = parts.get("FREQ")
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        _die("unsupported FREQ=%r - pass real occurrences with --dates instead" % freq)

    interval = int(parts.get("INTERVAL", "1") or 1)
    count = int(parts["COUNT"]) if parts.get("COUNT") else None
    until = parse_dt(parts["UNTIL"]) if parts.get("UNTIL") else None
    if until is None and parts.get("UNTIL"):
        # UNTIL often arrives as a compact form like 20270515T000000Z
        m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})Z?)?$", parts["UNTIL"])
        if m:
            y, mo, d, hh, mm, ss = (int(x) if x else 0 for x in m.groups())
            until = datetime.datetime(y, mo, d, hh, mm, ss, tzinfo=datetime.timezone.utc)
    if count is None and until is None:
        _die(
            "the rule has neither COUNT nor UNTIL, so the series never ends - "
            "there is no last occurrence to follow up after",
            code=2,
        )

    bydays = [WEEKDAYS[d] for d in parts.get("BYDAY", "").split(",") if d in WEEKDAYS]

    out = []
    cur = dtstart
    guard = 0
    while guard < MAX_EXPAND:
        guard += 1
        if freq == "WEEKLY" and bydays:
            week_start = cur - datetime.timedelta(days=cur.weekday())
            for wd in sorted(bydays):
                occ = week_start + datetime.timedelta(days=wd)
                occ = occ.replace(
                    hour=dtstart.hour, minute=dtstart.minute, second=dtstart.second
                )
                if occ < dtstart:
                    continue
                out.append(occ)
            cur = cur + datetime.timedelta(weeks=interval)
        else:
            out.append(cur)
            if freq == "DAILY":
                cur = cur + datetime.timedelta(days=interval)
            elif freq == "WEEKLY":
                cur = cur + datetime.timedelta(weeks=interval)
            elif freq == "MONTHLY":
                y, m = cur.year, cur.month + interval
                y += (m - 1) // 12
                m = (m - 1) % 12 + 1
                day = min(cur.day, [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
                cur = cur.replace(year=y, month=m, day=day)
            else:  # YEARLY
                cur = cur.replace(year=cur.year + interval)

        out = sorted(set(out))
        if count and len(out) >= count:
            return out[:count]
        if until and out:
            # `until` is tz-aware; if we are expanding naive wall-clock times,
            # compare on naive terms so the two are commensurable.
            u = until.replace(tzinfo=None) if out[0].tzinfo is None else until
            if out[-1] > u:
                return [d for d in out if d <= u]
    _die("rule did not terminate within %d occurrences" % MAX_EXPAND, code=2)


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--dates", nargs="+", help="ISO occurrence times")
    p.add_argument("--events", help="JSON file of events, or - for stdin")
    p.add_argument("--rrule", help="RRULE string (fallback; prefer real occurrences)")
    p.add_argument("--dtstart", help="first occurrence, required with --rrule")
    p.add_argument(
        "--after-days",
        type=int,
        default=1,
        help="days after the last occurrence to schedule (default 1)",
    )
    p.add_argument("--at", default="09:00", help="local time of day, HH:MM (default 09:00)")
    p.add_argument("--tz", help="IANA timezone for the follow-up (default: the series' own offset)")
    a = p.parse_args()

    occurrences = []
    source = None
    if a.dates:
        occurrences = [d for d in (parse_dt(x) for x in a.dates) if d]
        source = "dates"
    elif a.events:
        raw = sys.stdin.read() if a.events == "-" else open(a.events).read()
        occurrences = collect_from_events(json.loads(raw))
        source = "events"
    elif a.rrule:
        if not a.dtstart:
            _die("--rrule needs --dtstart")
        ds = parse_dt(a.dtstart)
        if not ds:
            _die("could not parse --dtstart")
        if a.tz:
            # Expand against naive wall-clock time in the target zone, then
            # re-attach it. A 6pm class stays 6pm after a DST transition;
            # expanding against a fixed UTC offset would drift it by an hour.
            zone = zoneinfo.ZoneInfo(a.tz)
            local_naive = ds.astimezone(zone).replace(tzinfo=None)
            occurrences = [d.replace(tzinfo=zone) for d in expand_rrule(a.rrule, local_naive)]
        else:
            occurrences = expand_rrule(a.rrule, ds)
            print(
                "[warn] expanding an RRULE without --tz keeps the start offset "
                "fixed across a DST transition. This is not cosmetic: it can "
                "shift occurrences past a UTC-expressed UNTIL and silently drop "
                "them, which moves both the last occurrence and the follow-up "
                "date. Re-run with --tz America/Los_Angeles (or the series' "
                "zone) and compare occurrence_count before trusting the result.",
                file=sys.stderr,
            )
        source = "rrule"
    else:
        _die("supply one of --dates, --events, or --rrule")

    if not occurrences:
        _die("no occurrences found", code=2)

    occurrences = sorted(occurrences)
    last = occurrences[-1]

    if a.tz:
        try:
            tz = zoneinfo.ZoneInfo(a.tz)
        except Exception:
            _die("unknown timezone %r" % a.tz)
        last_local = last.astimezone(tz)
    elif last.tzinfo:
        tz = last.tzinfo
        last_local = last
    else:
        _die("occurrences have no timezone - pass --tz")

    try:
        hh, mm = (int(x) for x in a.at.split(":"))
    except Exception:
        _die("--at must be HH:MM")

    followup_local = (last_local + datetime.timedelta(days=a.after_days)).replace(
        hour=hh, minute=mm, second=0, microsecond=0
    )
    now = datetime.datetime.now(datetime.timezone.utc)

    json.dump(
        {
            "source": source,
            "occurrence_count": len(occurrences),
            "first_occurrence": occurrences[0].isoformat(),
            "last_occurrence": last_local.isoformat(),
            "followup_local": followup_local.isoformat(),
            # Exactly what local_routine.py's --at wants: no seconds, no UTC
            # offset. Pass this value verbatim - do not hand-edit it, and do
            # not use followup_local for --at, which will be rejected.
            "followup_at": followup_local.strftime("%Y-%m-%dT%H:%M"),
            "followup_tz": str(tz),
            "is_in_future": followup_local > now,
            "days_from_now": (followup_local - now).days,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    if followup_local <= now:
        print(
            "[warn] that follow-up time is already in the past - local-routine's "
            "--at will refuse it. Pick a later --after-days or --at time.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
