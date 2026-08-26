# eero cloud API

eero hardware exposes **no local management interface**. Every setting lives behind
`https://api-user.e2ro.com`, the production host and the default. The API is undocumented
and unofficial; it is the same one the eero mobile app uses. Treat it as subject to change
without notice.

### Pointing at a different host

Some users have access to eero environments other than production. The host is resolved
once, in this order, and whatever wins is persisted into the session so the rest of the
commands need no extra flags:

```
login --base <url>   >   $EERO_API_BASE   >   cached session   >   production default
```

```bash
python3 "$SKILL_DIR"/scripts/eero_client.py login --base https://<host> --id "+15551234567"
# or, for a whole shell session:
export EERO_API_BASE=https://<host>
```

If you have such a host, you already know its name; this skill does not carry one. Two
rules when you use it: `logout` between environments so a stale session does not silently
retarget a later command, and **do not generalise findings from a non-production
environment to production** - the two do not always behave the same.

`scripts/eero_client.py` wraps everything below.

## Contents
- [Auth](#auth)
- [Request shape](#request-shape)
- [Read endpoints](#read-endpoints)
- [Settings fields](#settings-fields)
- [Writing settings](#writing-settings)
- [Errors](#errors)

## Auth

Phone/email one-time-code flow:

1. `POST /2.2/login` with `{"login": "+15551234567"}` -> `data.user_token`.
   eero sends an SMS or email code.
2. `POST /2.2/login/verify` with `{"code": "123456"}` and header `Cookie: s=<user_token>`.
   After this the same token is a valid **session** token.
3. All subsequent calls send `Cookie: s=<token>`.
4. On `401` with `error.session.refresh`, `POST /2.2/login/refresh` (with the current
   cookie) returns a fresh `data.user_token`.

**Important:** step 1 returns a token even for an identifier with no eero account. A
successful `login` call is therefore *not* proof the phone/email is correct - if no code
arrives, the identifier does not match an account.

The session token is long-lived. `eero_client.py` caches it at
`~/.config/eero-sonos/session.json` with mode `0600` and never prints it.

## Request shape

```
Base:    https://api-user.e2ro.com
Version: /2.2   (a few endpoints are /2.3)
Headers: Content-Type: application/json
         Cookie: s=<session token>
```

Responses are `{"meta": {"code": 200, ...}, "data": {...}}`.

## Read endpoints

| Path | Contents |
|---|---|
| `/2.2/account` | account, plus `data.networks.data[].url` -> `/2.2/networks/<id>` |
| `/2.2/networks/<id>` | the network object - **all the settings below live here** |
| `/2.2/networks/<id>/eeros` | the nodes: model, location name, gateway flag, wired/wireless backhaul |
| `/2.2/networks/<id>/devices` | connected clients: mac, ip, hostname, band, signal, and which node each is on |
| `/2.2/networks/<id>/reservations` | DHCP reservations and port forwards |
| `/2.2/networks/<id>/thread` | Thread (802.15.4) network status |
| `/2.2/networks/<id>/guestnetwork` | guest SSID state |

### Choosing the right network

An account can hold several networks (home, work, test). **Taking the first one is wrong**
whenever the speakers live on another. Pass `fetch --match-sonos <scan.json>` and the
client picks the network whose device list actually contains the scanned Sonos MACs.

### Node attribution has a catch

The `devices` list maps a Sonos MAC to the eero node it is attached to. Node
attribution has appeared under different keys across API revisions; `eero_client.py`
and `diagnose.py` try `source.location`, `source.display_name`, `source.serial`,
`connected_to`, then `location`, and degrade gracefully when none are present.

## Settings fields

Fields on the network object that matter for Sonos:

| Field | Sonos-relevant meaning |
|---|---|
| `band_steering` | Steers clients to 5 GHz. Strands 2.4 GHz-only Sonos models. |
| `sqm` | Smart Queue Management. Traffic shaping; widely reported to disturb Sonos sync. |
| `wpa3` | Older Sonos hardware cannot join WPA3 or WPA2/WPA3 transition mode. |
| `upnp` | Sonos relies on UPnP for description/control. |
| `thread` | 802.15.4 radio sharing the 2.4 GHz band with SonosNet. |
| `ipv6_upstream`, `ipv6_downstream` | Sonos control traffic is IPv4-only. |
| `dns`, `dns_caching`, `custom_dns` | Ad-blocking or custom DNS can break Sonos services. |
| `guest_network_enabled` | Guest clients are isolated; Sonos discovery fails across it. |

Values are **not** uniformly booleans. Depending on firmware and plan they may be
`true`/`false`, an object like `{"enabled": true}`, or `{"mode": "on"}`.
`diagnose.py` normalises all three shapes.

## Writing settings

`PUT /2.2/networks/<id>` with a partial body, e.g. `{"band_steering": false}`.

The API frequently accepts a `PUT` and returns 200 while silently ignoring a field -
because it is read-only, gated behind an eero Plus subscription, or only settable from
the app. **Always read the network object back and compare** rather than trusting the
response. `eero_client.py apply` does this automatically and reports any field that did
not change.

**Observed silently-ignored: `band_steering`** - on one non-production network, where
`capabilities.band_steering.capable` was `true`: `PUT` returned 200, echoed the *old* value
back, and a re-read confirmed no change.
Variants that also failed: API `2.3`, a `bandSteering` key,
`PUT /networks/<id>/band_steering` and `PUT /networks/<id>/settings` (last two 404). The
`resources.settings` URL the network object advertises 404s on both versions.

**This was one non-production network and may not hold on production.** Do not tell a user
a field is unwritable on this basis - run the write and let the read-back decide. If it is ignored,
the eero app is the fallback.

Do not treat `capabilities.<field>.capable == true` as evidence a field is writable via
the API - it is not the same thing.

`eero_client.py apply` also writes a rollback file containing the prior values before
any write; `eero_client.py rollback <file> --confirm` restores them.

## Errors

| Status | `meta.error` | Handling |
|---|---|---|
| 401 | `error.session.refresh` | call `login/refresh`, retry once |
| 401 | `error.session.invalid` | session dead, re-run login + verify |
| 400 | `error.form.errors` | `data` names the offending field |
| 429 | - | rate limited; back off |
