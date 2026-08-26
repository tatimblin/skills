#!/usr/bin/env python3
"""eero cloud API client - read network settings and (with confirmation) change them.

eero hardware exposes no local management interface; everything lives behind
https://api-user.e2ro.com. Auth is phone/email OTP. The session token is cached
at ~/.config/eero-sonos/session.json (mode 0600) and never printed.

  python3 eero_client.py login  --id "+15551234567"   # triggers SMS/email code
  python3 eero_client.py verify --code 123456
  python3 eero_client.py fetch                        # full read-only dump -> JSON
  python3 eero_client.py apply --set band_steering=false --confirm
  python3 eero_client.py rollback <rollback-file.json> --confirm
  python3 eero_client.py logout

Non-production environments: pass --base to login, or set EERO_API_BASE. The host is
stored in the session file and reused by later commands.
"""
import argparse, json, os, pathlib, ssl, sys, time
import urllib.error, urllib.parse, urllib.request

DEFAULT_BASE = "https://api-user.e2ro.com"
VERSION = "2.2"
_BASE_OVERRIDE = None


def base_url():
    """Resolve the API host: --base flag > EERO_API_BASE env > cached session > production."""
    if _BASE_OVERRIDE:
        return _BASE_OVERRIDE.rstrip("/")
    env = os.environ.get("EERO_API_BASE")
    if env:
        return env.rstrip("/")
    return (load_session().get("base") or DEFAULT_BASE).rstrip("/")
CFG = pathlib.Path(os.environ.get("EERO_SONOS_HOME",
                                  pathlib.Path.home() / ".config" / "eero-sonos"))
SESSION = CFG / "session.json"
UA = "eero-sonos-skill/1.0"


def _log(m):
    print(m, file=sys.stderr)


def _die(m, code=1):
    _log(f"[error] {m}")
    sys.exit(code)


# --------------------------------------------------------------------------- session
def load_session():
    if not SESSION.exists():
        return {}
    try:
        return json.loads(SESSION.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_session(d):
    CFG.mkdir(parents=True, exist_ok=True)
    SESSION.write_text(json.dumps(d, indent=2))
    os.chmod(SESSION, 0o600)


class ApiError(Exception):
    def __init__(self, status, error, payload=None):
        super().__init__(f"HTTP {status}: {error}")
        self.status, self.error, self.payload = status, error, payload


def api(path, token=None, method="GET", body=None, version=VERSION):
    """Call the eero API. `path` is relative to /<version>/ (leading slash optional)."""
    url = f"{base_url()}/{version}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", UA)
    if token:
        req.add_header("Cookie", f"s={token}")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:400]}
        raise ApiError(e.code, (payload.get("meta") or {}).get("error", raw[:200]), payload)
    except urllib.error.URLError as e:
        raise ApiError(0, f"network error: {e.reason}")


def authed(path, method="GET", body=None, version=VERSION, _retry=True):
    """API call using the cached session, auto-refreshing once on session expiry."""
    s = load_session()
    tok = s.get("token")
    if not tok:
        _die("not logged in - run:  eero_client.py login --id <phone-or-email>")
    try:
        return api(path, tok, method, body, version)
    except ApiError as e:
        if e.status == 401 and e.error == "error.session.refresh" and _retry:
            _log("[*] session expired, refreshing...")
            r = api("login/refresh", tok, "POST")
            s["token"] = r["data"]["user_token"]
            save_session(s)
            return authed(path, method, body, version, _retry=False)
        if e.status == 401:
            _die(f"session invalid ({e.error}) - run login/verify again")
        raise


# --------------------------------------------------------------------------- helpers
def list_networks():
    acct = authed("account")
    nets = ((acct.get("data") or {}).get("networks") or {}).get("data") or []
    out = []
    for n in nets:
        url = n.get("url") or ""
        if "/networks/" in url:
            out.append({"path": url[url.index("/networks/"):].lstrip("/"),
                        "name": n.get("name")})
    return out


def _macs_on(net_path):
    try:
        devs = authed(f"{net_path}/devices").get("data") or []
    except ApiError:
        return set()
    return {(d.get("mac") or "").upper() for d in devs if d.get("mac")}


def network_path(match_macs=None):
    """Resolve the network to operate on.

    An account can hold several networks. Picking the first is wrong whenever the
    speakers live on another one, so when `match_macs` is supplied (the Sonos MACs
    from a scan) the network actually containing them wins.
    """
    s = load_session()
    if s.get("network_path"):
        return s["network_path"]
    nets = list_networks()
    if not nets:
        _die("no eero networks on this account")

    chosen = nets[0]
    if match_macs and len(nets) > 1:
        want = {m.upper() for m in match_macs}
        best, best_hits = None, 0
        for n in nets:
            hits = len(want & _macs_on(n["path"]))
            _log(f"[*] {n['name']}: {hits}/{len(want)} Sonos MACs present")
            if hits > best_hits:
                best, best_hits = n, hits
        if best:
            chosen = best
            _log(f"[*] selected '{chosen['name']}' - contains the Sonos devices")
        else:
            _log("[warn] no network contains the scanned Sonos MACs; "
                 f"falling back to '{chosen['name']}'")
    elif len(nets) > 1:
        _log(f"[warn] account has {len(nets)} networks; using '{chosen['name']}'. "
             "Pass --match-sonos <scan.json> to auto-select, or set network_path "
             "in session.json.")

    s["network_path"], s["network_name"] = chosen["path"], chosen["name"]
    save_session(s)
    return chosen["path"]


def _coerce(v):
    low = v.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none"):
        return None
    try:
        return json.loads(v)
    except json.JSONDecodeError:
        return v


# --------------------------------------------------------------------------- commands
def cmd_login(a):
    global _BASE_OVERRIDE
    if getattr(a, "base", None):
        _BASE_OVERRIDE = a.base
    r = api("login", body={"login": a.id}, method="POST")
    tok = (r.get("data") or {}).get("user_token")
    if not tok:
        _die(f"unexpected login response: {json.dumps(r)[:300]}")
    save_session({"token": tok, "login": a.id, "verified": False,
                  "base": base_url(),
                  "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    _log(f"[*] api host: {base_url()}")
    _log(f"[ok] login accepted for {a.id}")
    _log("     next:  eero_client.py verify --code <code>")
    _log("     note: eero returns a token even for an identifier with no account.")
    _log("     If no code arrives, the phone/email does not match an eero account.")


def cmd_verify(a):
    s = load_session()
    if not s.get("token"):
        _die("run login first")
    r = api("login/verify", s["token"], "POST", {"code": a.code})
    s["verified"] = True
    save_session(s)
    name = ((r.get("data") or {}).get("name")) or "(account)"
    _log(f"[ok] verified - logged in as {name}")
    _log(f"[ok] session cached at {SESSION} (mode 0600)")


def cmd_logout(a):
    if SESSION.exists():
        SESSION.unlink()
        _log(f"[ok] removed {SESSION}")
    else:
        _log("[ok] no cached session")


def cmd_fetch(a):
    macs = None
    if getattr(a, "match_sonos", None):
        scan = json.loads(pathlib.Path(a.match_sonos).read_text())
        macs = {d["mac"] for d in scan.get("devices", []) if d.get("mac")}
    net = network_path(macs)
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "network_path": net}

    def grab(key, path, version=VERSION):
        try:
            out[key] = authed(path, version=version).get("data")
        except ApiError as e:
            out[key] = {"_error": f"{e.status} {e.error}"}

    grab("network", net)
    grab("eeros", f"{net}/eeros")
    grab("devices", f"{net}/devices")
    grab("reservations", f"{net}/reservations")
    grab("forwards", f"{net}/forwards")
    grab("thread", f"{net}/thread")
    grab("guestnetwork", f"{net}/guestnetwork")
    print(json.dumps(out, indent=2))


def cmd_apply(a):
    updates = {}
    for pair in a.set:
        if "=" not in pair:
            _die(f"--set expects key=value, got {pair!r}")
        k, v = pair.split("=", 1)
        updates[k.strip()] = _coerce(v)
    if not updates:
        _die("nothing to apply")

    net = network_path()
    before = authed(net).get("data") or {}
    prior = {k: before.get(k) for k in updates}

    _log("[*] planned changes:")
    for k, v in updates.items():
        _log(f"      {k}: {json.dumps(prior.get(k))}  ->  {json.dumps(v)}")

    if not a.confirm:
        _log("[dry-run] re-run with --confirm to apply")
        print(json.dumps({"dry_run": True, "before": prior, "requested": updates}, indent=2))
        return

    CFG.mkdir(parents=True, exist_ok=True)
    rb = CFG / f"rollback-{time.strftime('%Y%m%d-%H%M%S')}.json"
    rb.write_text(json.dumps({"network_path": net, "restore": prior}, indent=2))
    _log(f"[*] rollback written to {rb}")

    authed(net, "PUT", updates)

    # Read back and verify each field actually took - the API accepts some PUTs silently.
    after_full = authed(net).get("data") or {}
    after = {k: after_full.get(k) for k in updates}
    applied, ignored = {}, {}
    for k, want in updates.items():
        (applied if after.get(k) == want else ignored)[k] = {
            "requested": want, "actual": after.get(k), "was": prior.get(k)}
    for k, v in applied.items():
        _log(f"[ok]   {k} = {json.dumps(v['actual'])}")
    for k, v in ignored.items():
        _log(f"[warn] {k} did NOT change (still {json.dumps(v['actual'])}) - "
             "eero returned 200 but ignored it. Known for band_steering; the field "
             "may be read-only via the API even when capabilities say otherwise. "
             "Change it in the eero app instead.")
    print(json.dumps({"applied": applied, "not_applied": ignored,
                      "rollback_file": str(rb)}, indent=2))


def cmd_rollback(a):
    doc = json.loads(pathlib.Path(a.file).read_text())
    net, restore = doc["network_path"], doc["restore"]
    _log("[*] restoring:")
    for k, v in restore.items():
        _log(f"      {k} -> {json.dumps(v)}")
    if not a.confirm:
        _log("[dry-run] re-run with --confirm")
        return
    authed(net, "PUT", restore)
    _log("[ok] restored")


def cmd_raw(a):
    body = json.loads(a.body) if a.body else None
    print(json.dumps(authed(a.path, a.method, body, a.api_version), indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("login"); p.add_argument("--id", required=True,
        help="phone (+15551234567) or email on the eero account")
    p.add_argument("--base", help="API host for non-production environments "
                                  "(or set EERO_API_BASE); persisted in the session")
    p.set_defaults(f=cmd_login)
    p = sub.add_parser("verify"); p.add_argument("--code", required=True); p.set_defaults(f=cmd_verify)
    sub.add_parser("logout").set_defaults(f=cmd_logout)
    p = sub.add_parser("fetch")
    p.add_argument("--match-sonos", metavar="SCAN.JSON",
                   help="sonos_scan.py output; selects the network containing those MACs")
    p.set_defaults(f=cmd_fetch)
    p = sub.add_parser("apply")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--confirm", action="store_true"); p.set_defaults(f=cmd_apply)
    p = sub.add_parser("rollback"); p.add_argument("file")
    p.add_argument("--confirm", action="store_true"); p.set_defaults(f=cmd_rollback)
    p = sub.add_parser("raw"); p.add_argument("path")
    p.add_argument("--method", default="GET"); p.add_argument("--body")
    p.add_argument("--api-version", default=VERSION); p.set_defaults(f=cmd_raw)

    a = ap.parse_args()
    try:
        a.f(a)
    except ApiError as e:
        _die(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
