# Volo authentication

How the token model works, how to get a credential out of a browser, and the traps.
Verified against the live API on 2026-08-29.

## Contents

- [The two tokens](#the-two-tokens)
- [Refreshing](#refreshing)
- [Getting the first credential](#getting-the-first-credential)
- [Where credentials are stored](#where-credentials-are-stored)
- [Request headers](#request-headers)
- [Traps](#traps)

## The two tokens

Volo issues two things when you log in. They have very different lifetimes and the
difference decides whether unattended use is possible at all.

| Token | Field | Lifetime | Good for |
|---|---|---|---|
| Access token | `token` | ~12 hours | a day of API calls |
| Refresh token | `web_auth_refresh_token` | ~90 days | minting new access tokens forever |

The access token is a Hasura JWT. Decode it (no verification needed) to read `exp` and the
`https://hasura.io/jwt/claims` block, which carries `x-hasura-user-id`,
`x-hasura-default-role`, and `x-hasura-allowed-roles`.

**A refresh token is what makes scheduled runs work.** With only an access token, anything
running on a timer breaks within the day and there is nothing stored to renew it.
`volo.py auth status` reports this as `unattended_capable`.

There is also a browser session cookie, `volo-app-session` - Iron-sealed (`Fe26.2**...`),
`HttpOnly`, `Max-Age=7776000` (90 days). It is encrypted with a server-side key, so it
cannot be unwrapped locally, and it is where the refresh token actually lives for SSO
accounts - see [Getting the first credential](#getting-the-first-credential).

## Refreshing

One plain GraphQL mutation against the ordinary endpoint. No cookies, no browser, no
server functions:

```graphql
mutation WebRefresh($t: String!) {
  webRefresh(actionsAuthWebRefreshInput: {webAuthRefreshToken: $t}) {
    _id
    email
    username
    token
    web_auth_refresh_token
  }
}
```

Introspected signature, confirmed live:

```
webRefresh(actionsAuthWebRefreshInput: ActionsAuthWebRefreshInput!) -> ActionsAuthLogin!
input ActionsAuthWebRefreshInput { webAuthRefreshToken: String }
type  ActionsAuthLogin { _id, email, external_id, roles, token, username, web_auth_refresh_token }
```

**Treat the refresh token as rotating.** The response carries a `web_auth_refresh_token`.
If it differs from the one you sent, persist the new one - `volo.py` does this
automatically. Dropping a rotated token strands the account until the user re-bootstraps.

A revoked or expired refresh token comes back as `{"message": "Session not found",
"extensions": {"code": "unexpected"}}`. That is the signal to ask the user to re-bootstrap,
not to retry.

## Getting the first credential

`webRefresh` solves renewal but not the cold start. **What you can get depends on how the
account signs in**, and this is the single most important operational fact in this file.

| Sign-in method | Obtainable credential | Unattended runs |
|---|---|---|
| Email + password | refresh token, ~90 days | yes |
| SSO with a password also set | refresh token, ~90 days | yes |
| Google / Apple SSO, no password | access token only, ~12 hours | **no** |

**Ask before assuming.** These are not mutually exclusive: an account can sign in with
Google *and* have a Volo password. Verified on a real account that habitually used Google
SSO but also had a password - `auth login` worked and yielded a refresh token. So when a
user says "I sign in with Google", ask whether they also know a Volo password before
concluding unattended runs are impossible. Only fall back to the access-token path once
`auth login` has actually failed with `Invalid Credentials.`

### Password accounts

`login` returns the refresh token directly to the caller, so no browser is involved:

```bash
volo.py auth login --email you@example.com
```

The password is prompted for (or read from `VOLO_PASSWORD`), used once, and never stored.
Only the returned refresh token is persisted.

### SSO accounts with no password: the refresh token is not reachable, at all

This was tested directly against a logged-in Chrome session on 2026-08-29, not inferred.
`web_auth_refresh_token` is absent from **all** of:

- `localStorage` (`auth-store` holds exactly `userId`, `roles`, `authToken`,
  `isAuthenticated` - no refresh token)
- `sessionStorage`
- every `window` global, searched one level deep
- the server-rendered HTML / `$_TSR` hydration payload
- the JS-visible cookie list

The reason is architectural rather than incidental. Volo's frontend keeps the refresh token
**server-side**, sealed inside the `volo-app-session` cookie with Iron (`Fe26.2**...`,
`HttpOnly`, 90-day `Max-Age`). The browser is handed only a short-lived access token. The
refresh happens in a TanStack server function, on the server, using the sealed cookie.

**No browser automation can extract it** - not Playwright, not a devtools console snippet,
not an extension. It is not in the browser to extract. Do not send users hunting for it.

So an SSO user pastes an access token roughly once a day:

```bash
volo.py auth bootstrap --stdin
```

Get it from DevTools -> Local Storage -> `auth-store` -> `authToken`, or with the console
one-liner `copy(JSON.parse(localStorage['auth-store']).state.authToken)`.

`volo.py auth bootstrap` accepts either credential type, works out which it got, and
**verifies it against the live API before storing anything**. A pasted JSON blob is fine -
it digs out the relevant field. A `Bearer ` prefix is stripped. When it stores an access
token it warns that unattended runs will not survive expiry.

### Why `login` is not the default path

```
login(email: String, password: String!, phone: String) -> ActionsAuthLogin
```

It is unusable for SSO accounts, which have no password. `resolveGoogleAuthAction` /
`resolveAppleAuthAction` do return a `webLoginPayload` containing a refresh token, but they
require a Google/Apple ID token, which means implementing a full OAuth client flow and
handling identity-provider credentials. That is far more machinery than this skill should
carry for a step run twice a year.

### Why the `/_serverFn/*` endpoints are not used

The current TanStack Start frontend calls build-hashed server functions
(`/_serverFn/<64-hex>`) for login, token refresh, and auth headers. They are a dead end, and this was
tested properly rather than assumed:

- Anonymous session: `403`. With an `Origin` header: `500`.
- **From inside a genuinely logged-in page**, via same-origin `fetch` with
  `credentials: "include"` so Chrome attached the real sealed cookie: still `500`. The
  body is `{"t":25,...,"c":"$TSR/Error"}` with the message `Seroval Error (step: 3)` -
  the handler expects a Seroval-serialized payload the framework client generates, not
  hand-built JSON.
- The `/app/*` dashboard issues **no** `_serverFn` calls at all; they belong only to the
  TanStack `/login` routes.

Matching that wire format would mean reimplementing a framework-internal serializer whose
function IDs are content hashes that rotate on every deploy. `webRefresh` does the same job
over a stable, introspectable GraphQL surface.

## Where credentials are stored

| Item | Location | Mode |
|---|---|---|
| Refresh token (macOS) | Keychain, service `volo-sports`, account `refresh-token` | - |
| Refresh token (elsewhere) | `~/.config/volo-sports/credentials.json` | `0600` |
| Access token + claims | `~/.config/volo-sports/session.json` | `0600` |
| Schema cache | `~/.config/volo-sports/schema-cache.json` | `0600` |

Override the directory with `VOLO_SPORTS_HOME`. For CI or cron, `VOLO_REFRESH_TOKEN` and
`VOLO_TOKEN` bypass storage entirely.

Off macOS the file fallback prints a warning, because a plaintext refresh token is a
90-day credential for the account. No token is ever written to stdout or stderr;
`auth status` reports expiry and identity but never the token itself.

`volo.py auth logout` clears the keychain item, the session, and the schema cache.

## Request headers

```
authorization: Bearer <access token>
x-hasura-role: PLAYER
content-type: application/json
user-agent: <a browser UA - see below>
```

`x-hasura-role` picks one role out of the JWT's allowed set. The ladder, highest first:
`EXECUTIVE_ADMIN`, `ORG_ADMIN`, `ORG_MANAGER`, `ORG_USER`, `STAFF`, `PLAYER`. Ordinary
players only ever have `PLAYER`.

## Traps

### Cloudflare blocks the default Python User-Agent

This one costs an hour if you hit it cold. `volosports.com` sits behind Cloudflare, which
rejects `Python-urllib/3.x` with a **403 before the request reaches Hasura**. The same
request with a browser `User-Agent` succeeds. `curl` works out of the box, which makes the
failure look like an auth problem when it is not.

`volo.py` always sends a browser UA; override with `VOLO_USER_AGENT`. If you hand-roll a
request in another language, set one.

### A 403 is not an auth failure

`403` means Cloudflare. Real auth failures arrive as HTTP `200` with a GraphQL `errors`
array containing `JWTExpired`, `invalid-jwt`, or `access-denied`.

### The app itself fires expired tokens

The web client is known to send a stale token on its first call, get `JWTExpired`, then
silently refresh and retry. If you are capturing headers from browser traffic to bootstrap,
take them from a request that actually succeeded, not the first one you see.

### Refresh proactively, not reactively

`volo.py` refreshes 120 seconds before `exp` and also retries once through a refresh if a
call fails mid-flight with a JWT error. Anything long-running should do the same rather
than assuming a token stays valid for the length of a job.
