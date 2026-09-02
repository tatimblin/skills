#!/usr/bin/env python3
"""Authenticate against Volo Sports and run GraphQL against their Hasura API.

A thin client, not a feature tool: it handles auth and schema navigation so an
agent can compose whatever queries it needs.

  volo.py auth bootstrap --stdin      # store a credential read from stdin
  volo.py auth status                 # who am I, when does the token expire
  volo.py whoami                      # smoke test: identity from the live API
  volo.py introspect --search game    # find types and fields (works with no auth)
  volo.py introspect --type games     # fields and argument signatures
  volo.py query -q 'query { currentUser { _id email } }'
  volo.py query --file q.graphql --var userId=<uuid>

JSON goes to stdout, everything else to stderr, so output is safe to pipe.
Tokens are never printed.
"""

import argparse
import base64
import getpass
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------- constants

GRAPHQL_URL = os.environ.get(
    "VOLO_GRAPHQL_URL", "https://www.volosports.com/hapi/v1/graphql"
)

# Cloudflare fronts volosports.com and rejects the default Python-urllib
# User-Agent with a 403 before the request ever reaches Hasura. A browser-like
# UA is required, not cosmetic.
USER_AGENT = os.environ.get(
    "VOLO_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
)

HOME = pathlib.Path(
    os.environ.get("VOLO_SPORTS_HOME", pathlib.Path.home() / ".config" / "volo-sports")
)
SESSION = HOME / "session.json"
CREDS = HOME / "credentials.json"
SCHEMA_CACHE = HOME / "schema-cache.json"
SCHEMA_TTL = 24 * 3600

KEYCHAIN_SERVICE = "volo-sports"
KEYCHAIN_ACCOUNT = "refresh-token"

# Refresh this many seconds before the JWT actually expires.
EXPIRY_SKEW = 120

LOGIN_MUTATION = """
mutation Login($email: String!, $password: String!) {
  login(email: $email, password: $password) {
    _id
    email
    username
    token
    web_auth_refresh_token
  }
}
"""

REFRESH_MUTATION = """
mutation WebRefresh($t: String!) {
  webRefresh(actionsAuthWebRefreshInput: {webAuthRefreshToken: $t}) {
    _id
    email
    username
    token
    web_auth_refresh_token
  }
}
"""


def _log(m):
    print(m, file=sys.stderr)


def _die(m, code=1):
    print("[error] " + m, file=sys.stderr)
    sys.exit(code)


def _out(obj):
    json.dump(obj, sys.stdout, indent=2, sort_keys=False, default=str)
    sys.stdout.write("\n")


# --------------------------------------------------------------- transport


class GraphQLError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__(json.dumps(errors))

    def codes(self):
        out = set()
        for e in self.errors:
            ext = e.get("extensions") or {}
            if ext.get("code"):
                out.add(str(ext["code"]))
            msg = e.get("message") or ""
            for probe in ("JWTExpired", "invalid-jwt", "jwt", "Malformed"):
                if probe.lower() in msg.lower():
                    out.add(probe)
        return out

    def is_auth_error(self):
        blob = " ".join(self.codes()).lower() + " " + json.dumps(self.errors).lower()
        return any(
            k in blob
            for k in ("jwtexpired", "invalid-jwt", "access-denied", "unauthorized")
        )


def post(query, variables=None, token=None, role=None, timeout=30):
    """One GraphQL round trip. Raises GraphQLError on a GraphQL-level error."""
    body = {"query": query}
    if variables:
        body["variables"] = variables
    headers = {
        "content-type": "application/json",
        "accept": "application/json",
        "user-agent": USER_AGENT,
        "origin": "https://www.volosports.com",
        "referer": "https://www.volosports.com/app/dashboard",
    }
    if token:
        headers["authorization"] = "Bearer " + token
        headers["x-hasura-role"] = role or "PLAYER"

    req = urllib.request.Request(
        GRAPHQL_URL, data=json.dumps(body).encode("utf-8"), headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        if e.code == 403:
            _die(
                "HTTP 403 from Cloudflare. This is usually the User-Agent being "
                "blocked - set VOLO_USER_AGENT to a browser string. Body: " + detail
            )
        _die("HTTP %s from the API: %s" % (e.code, detail))
    except urllib.error.URLError as e:
        _die("Could not reach %s: %s" % (GRAPHQL_URL, e))

    if payload.get("errors"):
        raise GraphQLError(payload["errors"])
    return payload.get("data")


# --------------------------------------------------------------- jwt


def decode_jwt(token):
    """Decode a JWT payload without verifying. Returns {} if it is not a JWT."""
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg).decode("utf-8"))
    except Exception:
        return {}


def jwt_facts(token):
    """Pull the interesting bits out of a Hasura JWT."""
    claims = decode_jwt(token)
    hasura = {}
    for k, v in claims.items():
        if "hasura" in k.lower() and isinstance(v, dict):
            hasura = v
            break
    roles = hasura.get("x-hasura-allowed-roles") or []
    return {
        "exp": claims.get("exp"),
        "iat": claims.get("iat"),
        "user_id": hasura.get("x-hasura-user-id") or claims.get("sub"),
        "default_role": hasura.get("x-hasura-default-role"),
        "roles": roles,
    }


def best_role(roles):
    ladder = [
        "EXECUTIVE_ADMIN",
        "ORG_ADMIN",
        "ORG_MANAGER",
        "ORG_USER",
        "STAFF",
        "PLAYER",
    ]
    for r in ladder:
        if r in (roles or []):
            return r
    return (roles or ["PLAYER"])[0]


# --------------------------------------------------------------- storage


def _keychain_available():
    return sys.platform == "darwin" and bool(_which("security"))


def _which(name):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = pathlib.Path(d) / name
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    return None


def keychain_get():
    try:
        r = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                KEYCHAIN_ACCOUNT,
                "-w",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except Exception:
        pass
    return None


def keychain_set(value):
    r = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
            value,
            "-U",
            "-D",
            "Volo Sports refresh token",
            "-j",
            "Stored by the volo-sports skill",
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "keychain write failed")


def keychain_delete():
    subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
        ],
        capture_output=True,
        text=True,
    )


def _write_private(path, obj):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def save_refresh_token(value):
    """Keychain on macOS, 0600 file everywhere else."""
    if _keychain_available():
        try:
            keychain_set(value)
            return "keychain"
        except Exception as e:
            _log("[warn] keychain write failed (%s), falling back to a file" % e)
    _write_private(CREDS, {"web_auth_refresh_token": value})
    _log(
        "[warn] refresh token stored at %s (mode 0600), not in a keychain. "
        "Anyone who can read that file can act as you on Volo." % CREDS
    )
    return "file"


def load_refresh_token():
    env = os.environ.get("VOLO_REFRESH_TOKEN")
    if env:
        return env.strip(), "env"
    if _keychain_available():
        v = keychain_get()
        if v:
            return v, "keychain"
    c = _read_json(CREDS) or {}
    if c.get("web_auth_refresh_token"):
        return c["web_auth_refresh_token"], "file"
    return None, None


def save_session(token, identity=None, refresh_token=None):
    facts = jwt_facts(token)
    sess = {
        "token": token,
        "exp": facts["exp"],
        "user_id": facts["user_id"],
        "roles": facts["roles"],
        "default_role": facts["default_role"],
        "obtained": int(time.time()),
    }
    if identity:
        sess["identity"] = identity
    _write_private(SESSION, sess)
    if refresh_token:
        save_refresh_token(refresh_token)
    return sess


def load_session():
    return _read_json(SESSION)


# --------------------------------------------------------------- auth core


def session_is_fresh(sess):
    if not sess or not sess.get("token"):
        return False
    exp = sess.get("exp")
    if not exp:
        return False
    return time.time() < (exp - EXPIRY_SKEW)


def refresh_session(verbose=True):
    """Exchange the stored refresh token for a fresh JWT via webRefresh."""
    rt, source = load_refresh_token()
    if not rt:
        _die(
            "No stored credential. Run:  volo.py auth bootstrap --help-only\n"
            "        (or set VOLO_REFRESH_TOKEN / VOLO_TOKEN in the environment)"
        )
    if verbose:
        _log("[*] refreshing access token (credential from %s)" % source)
    try:
        data = post(REFRESH_MUTATION, {"t": rt})
    except GraphQLError as e:
        _die(
            "webRefresh failed: %s\n"
            "        The refresh token is probably expired or revoked. "
            "Re-run: volo.py auth bootstrap" % json.dumps(e.errors)
        )
    node = (data or {}).get("webRefresh") or {}
    token = node.get("token")
    if not token:
        _die("webRefresh returned no token. Payload: %s" % json.dumps(data))
    identity = {
        "_id": node.get("_id"),
        "email": node.get("email"),
        "username": node.get("username"),
    }
    # Volo may rotate the refresh token on every use; persist it if so.
    new_rt = node.get("web_auth_refresh_token")
    sess = save_session(
        token, identity=identity, refresh_token=new_rt if new_rt and new_rt != rt else None
    )
    if verbose:
        _log("[ok] token refreshed, valid for %s" % human_ttl(sess.get("exp")))
    return sess


def get_token(allow_refresh=True):
    """A valid JWT, refreshing if needed. Never returns an expired one."""
    env = os.environ.get("VOLO_TOKEN")
    if env:
        return env.strip(), ["PLAYER"]
    sess = load_session()
    if session_is_fresh(sess):
        return sess["token"], sess.get("roles") or ["PLAYER"]
    if not allow_refresh:
        return None, []
    sess = refresh_session()
    return sess["token"], sess.get("roles") or ["PLAYER"]


def authed_post(query, variables=None):
    """GraphQL with auth, retrying once through a refresh on a JWT error."""
    token, roles = get_token()
    try:
        return post(query, variables, token=token, role=best_role(roles))
    except GraphQLError as e:
        if not e.is_auth_error():
            raise
        _log("[*] token rejected mid-flight, refreshing and retrying once")
        sess = refresh_session()
        return post(
            query,
            variables,
            token=sess["token"],
            role=best_role(sess.get("roles") or []),
        )


def human_ttl(exp):
    if not exp:
        return "unknown"
    d = int(exp - time.time())
    if d <= 0:
        return "expired"
    if d < 3600:
        return "%dm" % (d // 60)
    if d < 86400:
        return "%dh %dm" % (d // 3600, (d % 3600) // 60)
    return "%dd" % (d // 86400)


# --------------------------------------------------------------- commands

BOOTSTRAP_HELP = """
How to get a Volo credential out of your browser
================================================

Which credential you can get depends on how you sign in.

  SSO (Google/Apple):  access token only. Lasts ~12 hours. Unattended runs
                       are NOT possible - see the note at the bottom.
  Email + password:    a 90-day refresh token is available. See below.

-- SSO accounts: the access token (~12 hours) --

  1. Sign in at https://www.volosports.com  in any browser
  2. Open DevTools:  Cmd-Opt-I (macOS)  /  F12 (Windows, Linux)
  3. Application tab (Chrome) or Storage tab (Firefox)
     -> Local Storage -> https://www.volosports.com -> "auth-store"
  4. Copy the "authToken" value. It starts with "eyJ".
     Or paste the whole auth-store blob - this command digs the field out.

  Console one-liner that copies it for you:

     copy(JSON.parse(localStorage['auth-store']).state.authToken)

-- Password accounts: the refresh token (~90 days) --

  Log in through the API instead of the browser, which returns the refresh
  token directly:

     volo.py auth login --email you@example.com

  (You will be prompted for the password; it is used once and never stored.)

-- Feed the credential in --

  Keep it out of your shell history by using stdin:

     volo.py auth bootstrap --stdin          # paste, then press Ctrl-D

  The value is verified against the live API before anything is stored.

-- Why SSO cannot do unattended runs --

Volo's web app keeps the refresh token SERVER-side, sealed inside the
HttpOnly "volo-app-session" cookie. The browser never receives it. Verified
directly against a logged-in session: it is absent from localStorage,
sessionStorage, every window global, the SSR payload, and the JS-visible
cookies. No browser automation can extract it, because it is not there.

So an SSO account re-pastes an access token about once a day. If you need a
scheduled job, either set a password on the Volo account and use
`auth login`, or accept re-pasting.

This script never opens a browser and never handles your Google or Apple
password.
"""


def cmd_auth_bootstrap(a):
    if a.help_only:
        _log(BOOTSTRAP_HELP)
        return
    raw = a.value
    if a.stdin or not raw:
        if sys.stdin.isatty():
            _log(BOOTSTRAP_HELP)
            _log("Paste the token, then press Ctrl-D:")
        raw = sys.stdin.read()
    raw = (raw or "").strip()
    if not raw:
        _die("Nothing supplied. See:  volo.py auth bootstrap --help-only")

    # Tolerate a pasted JSON blob, a "Bearer x" prefix, or surrounding quotes.
    raw = raw.strip().strip('"').strip("'")
    if raw.startswith("{"):
        try:
            blob = json.loads(raw)
            raw = (
                _deep_find(blob, "web_auth_refresh_token")
                or _deep_find(blob, "authToken")
                or _deep_find(blob, "token")
                or raw
            )
        except Exception:
            pass
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()

    looks_like_jwt = raw.count(".") == 2 and raw.startswith("ey")

    if looks_like_jwt:
        facts = jwt_facts(raw)
        if not facts.get("exp"):
            _die("That looks like a JWT but has no exp claim. Refusing to store it.")
        if facts["exp"] <= time.time():
            _die("That access token is already expired. Grab a fresh one.")
        _log("[*] verifying the access token against the live API")
        data = post(
            "query { currentUser { _id email username } }",
            token=raw,
            role=best_role(facts["roles"]),
        )
        who = (data or {}).get("currentUser") or {}
        save_session(raw, identity=who)
        _log(
            "[ok] access token accepted for %s - expires in %s"
            % (who.get("email") or "unknown", human_ttl(facts["exp"]))
        )
        _log(
            "[warn] this is a short-lived ACCESS token, not a refresh token. "
            "Scheduled runs will stop working when it expires and there is "
            "nothing stored to renew it. Re-run bootstrap with a refresh token "
            "for unattended use."
        )
        _out({"stored": "access-token", "identity": who, "expires_in": human_ttl(facts["exp"])})
        return

    # Otherwise treat it as a refresh token and prove it by refreshing.
    _log("[*] verifying the refresh token with a live webRefresh call")
    try:
        data = post(REFRESH_MUTATION, {"t": raw})
    except GraphQLError as e:
        _die(
            "That credential was rejected by webRefresh: %s\n"
            "        Double-check you copied a web_auth_refresh_token. "
            "See: volo.py auth bootstrap --help-only" % json.dumps(e.errors)
        )
    node = (data or {}).get("webRefresh") or {}
    if not node.get("token"):
        _die("webRefresh succeeded but returned no token: %s" % json.dumps(data))
    identity = {
        "_id": node.get("_id"),
        "email": node.get("email"),
        "username": node.get("username"),
    }
    stored_rt = node.get("web_auth_refresh_token") or raw
    backend = save_refresh_token(stored_rt)
    sess = save_session(node["token"], identity=identity)
    _log("[ok] refresh token verified and stored in the %s" % backend)
    _out(
        {
            "stored": "refresh-token",
            "backend": backend,
            "identity": identity,
            "access_token_expires_in": human_ttl(sess.get("exp")),
        }
    )


def _deep_find(obj, key):
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], str):
            return obj[key]
        for v in obj.values():
            r = _deep_find(v, key)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _deep_find(v, key)
            if r:
                return r
    elif isinstance(obj, str) and obj.startswith("{"):
        try:
            return _deep_find(json.loads(obj), key)
        except Exception:
            return None
    return None


def cmd_auth_login(a):
    """Password login. The only route to a refresh token; unavailable for SSO."""
    email = a.email
    password = os.environ.get("VOLO_PASSWORD")
    if not password:
        if not sys.stdin.isatty():
            _die(
                "No password. Set VOLO_PASSWORD, or run this in a terminal to be "
                "prompted. The password is used once and never stored."
            )
        password = getpass.getpass("Volo password for %s (not stored): " % email)
    if not password:
        _die("No password supplied.")

    _log("[*] logging in as %s" % email)
    try:
        data = post(LOGIN_MUTATION, {"email": email, "password": password})
    except GraphQLError as e:
        _die(
            "Login failed: %s\n"
            "        If this account signs in with Google or Apple it has no "
            "password, and no refresh token can be obtained - use an access token "
            "instead. See: volo.py auth bootstrap --help-only" % json.dumps(e.errors)
        )
    del password
    node = (data or {}).get("login") or {}
    if not node.get("token"):
        _die("login returned no token: %s" % json.dumps(data))

    identity = {
        "_id": node.get("_id"),
        "email": node.get("email"),
        "username": node.get("username"),
    }
    rt = node.get("web_auth_refresh_token")
    backend = save_refresh_token(rt) if rt else None
    sess = save_session(node["token"], identity=identity)
    if rt:
        _log("[ok] logged in and stored a refresh token in the %s" % backend)
    else:
        _log(
            "[warn] logged in, but no refresh token was returned - unattended runs "
            "will stop working when this access token expires."
        )
    _out(
        {
            "stored": "refresh-token" if rt else "access-token",
            "backend": backend,
            "identity": identity,
            "unattended_capable": bool(rt),
            "access_token_expires_in": human_ttl(sess.get("exp")),
        }
    )


def cmd_auth_status(a):
    rt, source = load_refresh_token()
    sess = load_session() or {}
    status = {
        "refresh_token_present": bool(rt),
        "refresh_token_source": source,
        "access_token_present": bool(sess.get("token")),
        "access_token_valid": session_is_fresh(sess),
        "access_token_expires_in": human_ttl(sess.get("exp")),
        "identity": sess.get("identity"),
        "user_id": sess.get("user_id"),
        "roles": sess.get("roles"),
        "default_role": sess.get("default_role"),
        "session_file": str(SESSION),
        "unattended_capable": bool(rt),
    }
    _out(status)
    if not rt and not sess.get("token"):
        _log("[warn] nothing stored. Run: volo.py auth bootstrap --help-only")
    elif not rt:
        _log(
            "[warn] no refresh token stored - this session cannot renew itself "
            "and will stop working when the access token expires."
        )


def cmd_auth_logout(a):
    removed = []
    if _keychain_available() and keychain_get():
        keychain_delete()
        removed.append("keychain")
    for p in (SESSION, CREDS, SCHEMA_CACHE):
        if p.exists():
            p.unlink()
            removed.append(str(p))
    _out({"removed": removed})
    _log("[ok] cleared %d item(s)" % len(removed))


def cmd_whoami(a):
    # Kept to scalars that exist under every role. `most_recent_sport` is a
    # scalar anonymously but an object relationship under PLAYER, so selecting
    # it here breaks the moment you authenticate.
    data = authed_post(
        """query WhoAmI {
  currentUser {
    _id
    email
    username
    first_name
    last_name
    full_name
  }
}"""
    )
    sess = load_session() or {}
    who = (data or {}).get("currentUser")
    if not who:
        _die(
            "currentUser came back null. The token authenticated but Volo did not "
            "resolve a user - the credential may belong to a different environment."
        )
    _out({"currentUser": who, "roles": sess.get("roles"), "user_id": sess.get("user_id")})


def _parse_vars(pairs, json_vars):
    out = {}
    if json_vars:
        out.update(json.loads(json_vars))
    for p in pairs or []:
        if "=" not in p:
            _die("--var expects key=value, got %r" % p)
        k, v = p.split("=", 1)
        try:
            out[k] = json.loads(v)  # numbers, booleans, arrays, objects
        except Exception:
            out[k] = v  # plain string
    return out


def cmd_query(a):
    if a.file:
        query = pathlib.Path(a.file).read_text()
    elif a.query and a.query != "-":
        query = a.query
    else:
        query = sys.stdin.read()
    query = query.strip()
    if not query:
        _die("No query supplied. Use -q, --file, or pipe one in on stdin.")
    variables = _parse_vars(a.var, a.vars_json)
    # GraphQLError propagates to main(), which renders it uniformly.
    data = post(query, variables) if a.anon else authed_post(query, variables)
    _out(data)


# --------------------------------------------------------------- introspect

INTROSPECTION_QUERY = """
query Introspect {
  __schema {
    queryType { name }
    mutationType { name }
    types {
      name
      kind
      description
      fields(includeDeprecated: false) {
        name
        description
        args { name type { ...Tref } }
        type { ...Tref }
      }
      inputFields { name type { ...Tref } }
      enumValues(includeDeprecated: false) { name }
    }
  }
}
fragment Tref on __Type {
  kind name
  ofType { kind name ofType { kind name ofType { kind name } } }
}
"""


def type_name(t):
    if not t:
        return "?"
    if t.get("kind") == "NON_NULL":
        return type_name(t.get("ofType")) + "!"
    if t.get("kind") == "LIST":
        return "[" + type_name(t.get("ofType")) + "]"
    return t.get("name") or type_name(t.get("ofType"))


def _have_creds():
    if os.environ.get("VOLO_TOKEN"):
        return True
    rt, _ = load_refresh_token()
    return bool(rt) or session_is_fresh(load_session())


def load_schema(force=False, anon=False):
    cached = _read_json(SCHEMA_CACHE)
    if cached and not force:
        fresh = time.time() - cached.get("fetched", 0) < SCHEMA_TTL
        # A cached anonymous schema is a subset; refetch if we now have creds.
        usable = fresh and (cached.get("authenticated") or anon or not _have_creds())
        if usable:
            return cached["schema"], (
                "authenticated (cached)" if cached.get("authenticated") else "anonymous (cached)"
            )

    token = None
    role = None
    if not anon:
        # Prefer an authenticated introspection: Hasura scopes the visible
        # schema by role, and the anonymous view is much smaller.
        try:
            token, roles = get_token(allow_refresh=True)
            role = best_role(roles)
        except SystemExit:
            token = None
    _log("[*] fetching schema (%s)" % ("authenticated" if token else "anonymous"))
    data = post(INTROSPECTION_QUERY, token=token, role=role)
    schema = data["__schema"]
    try:
        _write_private(
            SCHEMA_CACHE,
            {"fetched": int(time.time()), "authenticated": bool(token), "schema": schema},
        )
    except Exception as e:
        _log("[warn] could not cache the schema: %s" % e)
    return schema, ("authenticated" if token else "anonymous")


def _field_sig(f):
    args = f.get("args") or []
    if args:
        inner = ", ".join("%s: %s" % (a["name"], type_name(a["type"])) for a in args)
        return "%s(%s): %s" % (f["name"], inner, type_name(f["type"]))
    return "%s: %s" % (f["name"], type_name(f["type"]))


def cmd_introspect(a):
    schema, mode = load_schema(force=a.refresh, anon=a.anon)
    types = {t["name"]: t for t in schema["types"]}
    qroot = types.get((schema.get("queryType") or {}).get("name") or "query_root")
    mroot = types.get((schema.get("mutationType") or {}).get("name") or "mutation_root")

    if a.raw:
        _out(schema)
        return

    if a.operations:
        _out(
            {
                "source": mode,
                "queries": sorted(f["name"] for f in (qroot or {}).get("fields") or []),
                "mutations": sorted(f["name"] for f in (mroot or {}).get("fields") or []),
            }
        )
        return

    if a.type:
        t = types.get(a.type)
        if not t:
            near = sorted(
                n for n in types if a.type.lower() in n.lower()
            )[:15]
            _die(
                "No type named %r. Close matches: %s"
                % (a.type, ", ".join(near) or "none")
            )
        out = {
            "name": t["name"],
            "kind": t["kind"],
            "description": t.get("description"),
            "source": mode,
        }
        if t.get("fields"):
            out["fields"] = [_field_sig(f) for f in t["fields"]]
        if t.get("inputFields"):
            out["inputFields"] = [
                "%s: %s" % (f["name"], type_name(f["type"])) for f in t["inputFields"]
            ]
        if t.get("enumValues"):
            out["enumValues"] = [e["name"] for e in t["enumValues"]]
        _out(out)
        return

    if a.search:
        term = a.search.lower()
        def _keep(name):
            if name.startswith("__") or term not in name.lower():
                return False
            return a.all or not _is_noise(name)

        matching_types = sorted(t["name"] for t in schema["types"] if _keep(t["name"]))
        root_hits = {}
        for label, root in (("queries", qroot), ("mutations", mroot)):
            if not root:
                continue
            root_hits[label] = sorted(
                _field_sig(f) for f in root["fields"] if term in f["name"].lower()
            )
        field_hits = []
        for t in schema["types"]:
            if t["name"].startswith("__") or not t.get("fields"):
                continue
            if _is_noise(t["name"]) and not a.all:
                continue
            for f in t["fields"]:
                if term in f["name"].lower():
                    field_hits.append("%s.%s: %s" % (t["name"], f["name"], type_name(f["type"])))
        _out(
            {
                "source": mode,
                "term": a.search,
                "types": matching_types[:60],
                "root_fields": root_hits,
                "fields_on_types": sorted(field_hits)[:80],
                "note": "Hasura scopes the schema by role; run authenticated for the full view."
                if mode.startswith("anonymous")
                else None,
            }
        )
        return

    _out(
        {
            "source": mode,
            "types": len(schema["types"]),
            "queries": len((qroot or {}).get("fields") or []),
            "mutations": len((mroot or {}).get("fields") or []),
            "hint": "use --search TERM, --type NAME, --operations, or --raw",
        }
    )


def _is_noise(name):
    """Hasura generates a lot of plumbing types that drown out search results."""
    return bool(
        re.search(
            r"(_bool_exp|_order_by|_aggregate|_avg_|_sum_|_max_|_min_|_stddev|_var_|"
            r"_mutation_response|_on_conflict|_insert_input|_set_input|_inc_input|"
            r"_pk_columns_input|_select_column|_update_column|_constraint|_comparison_exp|"
            r"_stream_cursor|_fields$)",
            name,
        )
    )


# --------------------------------------------------------------- cli


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd")

    auth = sub.add_parser("auth", help="manage credentials")
    asub = auth.add_subparsers(dest="authcmd")

    b = asub.add_parser("bootstrap", help="store and verify a credential")
    b.add_argument("value", nargs="?", help="the token (prefer --stdin)")
    b.add_argument("--stdin", action="store_true", help="read the token from stdin")
    b.add_argument(
        "--help-only",
        dest="help_only",
        action="store_true",
        help="print the browser instructions and exit",
    )
    b.set_defaults(f=cmd_auth_bootstrap)

    li = asub.add_parser(
        "login", help="password login (password accounts only; yields a refresh token)"
    )
    li.add_argument("--email", required=True, help="the Volo account email")
    li.set_defaults(f=cmd_auth_login)

    s = asub.add_parser("status", help="show credential state (never prints tokens)")
    s.set_defaults(f=cmd_auth_status)

    lo = asub.add_parser("logout", help="remove stored credentials and caches")
    lo.set_defaults(f=cmd_auth_logout)

    w = sub.add_parser("whoami", help="identity smoke test against the live API")
    w.set_defaults(f=cmd_whoami)

    q = sub.add_parser("query", help="run an arbitrary GraphQL document")
    q.add_argument("-q", "--query", help="query text, or - for stdin")
    q.add_argument("--file", help="read the query from a file")
    q.add_argument("--var", action="append", help="key=value, repeatable; JSON-aware")
    q.add_argument("--vars-json", dest="vars_json", help="all variables as one JSON object")
    q.add_argument("--anon", action="store_true", help="send without credentials")
    q.set_defaults(f=cmd_query)

    i = sub.add_parser("introspect", help="navigate the live schema")
    i.add_argument("--search", help="find types and fields matching a term")
    i.add_argument("--type", help="show one type's fields and argument signatures")
    i.add_argument("--operations", action="store_true", help="list root query/mutation names")
    i.add_argument("--raw", action="store_true", help="dump the whole schema as JSON")
    i.add_argument("--all", action="store_true", help="include Hasura plumbing types")
    i.add_argument("--anon", action="store_true", help="introspect without credentials")
    i.add_argument("--refresh", action="store_true", help="bypass the 24h schema cache")
    i.set_defaults(f=cmd_introspect)

    a = p.parse_args()
    if not getattr(a, "f", None):
        if a.cmd == "auth":
            auth.print_help()
        else:
            p.print_help()
        sys.exit(1)
    try:
        a.f(a)
    except GraphQLError as e:
        _out({"errors": e.errors})
        _die(
            "GraphQL returned %d error(s) - see stdout. If a field was not found, "
            "the schema differs by role: run `introspect --refresh --type <name>` "
            "to see what your role actually exposes." % len(e.errors),
            code=2,
        )
    except KeyboardInterrupt:
        _die("interrupted", code=130)


if __name__ == "__main__":
    main()
