---
name: eero-sonos
description: Diagnose and fix Sonos speakers misbehaving on an eero mesh network. Inspects the real speakers on the LAN over Sonos' local port-1400 API and, with the user's eero login, reads the eero cloud API, then reports exactly which settings violate Sonos' and eero's own published guidance and offers to apply the reversible fixes. Use when Sonos players drop out, disappear from the app, stutter, fail to group, will not finish setup, or are slow to respond on an eero network; when a user says Sonos and eero do not play nice or that problems started after installing eero; or when asked to audit or align an eero network for Sonos.
---

# eero + Sonos alignment

Sonos and eero conflict in specific, checkable ways. This skill measures the live system
instead of guessing, reports what is misaligned with each vendor's own guidance, and
offers to fix what can be fixed safely.

## Ground rules

- **Never change a working system.** eero's own article says: if you are not having
  problems, leave it alone. Ask what symptom the user actually sees before proposing
  changes. If nothing is wrong, say the system looks healthy and stop.
- **Always report the `source` of a finding.** `official-sonos` / `official-eero` are
  vendor rules; `community` findings are widely-reported experiments. Do not present
  them as equivalent.
- **Confirm before every write.** `apply` is a no-op without `--confirm`, and writes a
  rollback file first. Show the user the exact before/after and get an explicit yes.
- **The eero API is unofficial.** It can accept a `PUT` and silently ignore it. The
  scripts read back and verify; report honestly when a change did not take.

## Resolving script paths

Every command below runs a script out of `$SKILL_DIR`, the directory this `SKILL.md` was
read from. That is **not** the working directory - the shell starts in the user's project.
Resolve it once, before the first command, and reuse it verbatim:

```bash
SKILL_DIR=/absolute/path/to/eero-sonos     # the directory containing this SKILL.md
```

Installed as a Claude Code plugin, that path is `"$CLAUDE_PLUGIN_ROOT/skills/eero-sonos"`.
Invoking the scripts by bare relative path works only if the shell happens to already be in
the skill directory; do not rely on it.

## Workflow

### 1. Ask what is broken

One question, not a survey: *what does the problem look like, and when did it start?*
Common shapes - players vanish from the app, audio stutters or drops, rooms will not
group, a specific speaker is always the problem, setup never completes.

### 2. Scan the speakers (no credentials needed)

```bash
python3 "$SKILL_DIR"/scripts/sonos_scan.py --pretty > /tmp/sonos.json
```

Add `--sweep` to also TCP-scan port 1400. Do this when the user reports players
disappearing: a player that answers on 1400 but not on multicast proves discovery traffic
is being dropped, which explains most disappearing-speaker reports. The sweep runs
automatically if SSDP finds nothing.

This works from any machine on the same network as the speakers. If it finds nothing,
check that the machine is on the main SSID and not a guest network or VPN.

### 3. Diagnose locally first

```bash
python3 "$SKILL_DIR"/scripts/diagnose.py --sonos /tmp/sonos.json
```

This already catches most real problems: SonosNet/Wi-Fi mixing, wired players with live
radios, multiple wired players, loop-prone bridging, split households and subnets. Show
the user this report before asking for any credentials.

### 4. Add eero data only if it is needed

The local scan cannot see eero's settings, and cannot tell **which eero node each wired
player is plugged into** - which is the one thing Sonos' own article constrains most
tightly. If the local report raises `multiple_wired_players`, or the user wants the
settings audited, offer to authenticate.

Explain the trade first: eero has no local API, so this means logging into their eero
account via a one-time SMS or email code. The session token is cached at
`~/.config/eero-sonos/session.json` (mode 0600) and never printed.

```bash
python3 "$SKILL_DIR"/scripts/eero_client.py login --id "+15551234567"   # or an email address
python3 "$SKILL_DIR"/scripts/eero_client.py verify --code 123456
python3 "$SKILL_DIR"/scripts/eero_client.py fetch --match-sonos /tmp/sonos.json > /tmp/eero.json
python3 "$SKILL_DIR"/scripts/diagnose.py --sonos /tmp/sonos.json --eero /tmp/eero.json
```

The user must read the code off their phone - ask for it, do not attempt to obtain it.

Pass `--match-sonos` whenever possible: accounts often hold several networks, and the
first one is frequently not the one the speakers are on.

### 5. Offer fixes, in order

`diagnose.py --json` reports `auto_fixable_eero_settings`, the settings this skill can
change directly. Work in this order, re-scanning between stages:

1. **eero settings** - instant and reversible.
   ```bash
   python3 "$SKILL_DIR"/scripts/eero_client.py apply --set band_steering=false --set sqm=false   # dry run
   python3 "$SKILL_DIR"/scripts/eero_client.py apply --set band_steering=false --set sqm=false --confirm
   ```
   Without `--confirm` it prints the planned before/after and changes nothing. With it, a
   rollback file is written first, then each field is read back and verified.

   Expect some fields to refuse. eero can return 200 and silently ignore a write - seen with
   `band_steering` on one non-production network even though `capabilities` claimed
   otherwise. Whether that holds on production is unverified, so attempt the write and let
   the read-back decide rather than predicting failure. Relay the result honestly instead of
   claiming success, and point the user at the eero app for anything ignored.

2. **Sonos app changes** - there is **no local write API**; walk the user through the app
   steps in the finding's `fix.steps`. The one worth knowing by heart:
   **Settings > Network > SonosNet > Disable SonosNet** turns the mesh off system-wide
   without unplugging anything.

   Before recommending it, check `stp.path_cost` in the scan. Any player whose only
   uplink is a SonosNet hop will drop off the network when the mesh stops - wire it or
   confirm eero Wi-Fi coverage first. Disabling SonosNet also moves every player onto
   eero Wi-Fi, which makes band steering and WPA3 newly relevant.

3. **Physical rewiring** - consolidating wired players onto one eero node or switch.

Undo anything with:
```bash
python3 "$SKILL_DIR"/scripts/eero_client.py rollback ~/.config/eero-sonos/rollback-<stamp>.json --confirm
```

### 6. Re-measure

Re-run steps 2-3 after each stage. Mode changes and STP reconvergence take a minute or
two, so wait before re-scanning. Report what actually changed rather than assuming the
fix worked.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/sonos_scan.py` | SSDP + port-1400 discovery, per-player state -> JSON. Stdlib only. |
| `scripts/eero_client.py` | eero cloud auth, read-only `fetch`, verified `apply`, `rollback`. |
| `scripts/diagnose.py` | Correlates both sides into findings with severity, evidence, provenance and fixes. |

`sonos_scan.py` and `diagnose.py` need no credentials and no network writes.

## References

- **`references/checks.md`** - every check, what it detects, provenance, and the
  condensed vendor guidance. Read this to explain *why* a finding matters, or before
  adding a new check.
- **`references/sonos-local-api.md`** - the port-1400 endpoints, how to tell SonosNet
  from Wi-Fi, and how to read the spanning-tree output. Read when interpreting raw
  scan data or extending the scanner.
- **`references/eero-api.md`** - auth flow, endpoints, settings fields, and the
  read-back-to-verify rule. Read before making any eero API call by hand.

## Interpreting results

Two traps worth knowing up front:

- **eero commonly issues a `/22`.** `192.168.4.x` and `192.168.5.x` are usually the same
  subnet. Compare networks using the mask, never the third octet.
- **`100FD` link speed is normal.** Most Sonos players have 100 Mbps ports. It is not a
  fault and not worth reporting.
- **A disabled radio still reports `SONOSNET_MODE`.** Judge by `sonosnet_radio_active` and
  `mesh_links` from the scan, never by the mode string alone - otherwise you will report
  SonosNet problems on a system whose radios are all already off.
- **SonosNet never abandons a bad path by itself.** A player keeps relaying through a
  distant Sonos even when an eero node sits in the same room. That is why
  `weak_mesh_uplink` matters, and why disabling Wi-Fi on the distant relays is a valid
  no-cabling fix - the stranded player then falls back to eero Wi-Fi and associates
  locally. Check it has coverage, and that nothing else depends on those relays, first.
- **Check both ends of a weak link.** A player can have a pristine noise floor and still
  have a terrible link because the player it relays through sits in interference.
- **eero cannot see SonosNet players' signal.** It reports them as
  `connection_type: "sonos"` with `signal: null`, so the eero app will never show a weak
  link for one. `stp.path_cost` in the Sonos scan is the only view: `0`/`10` is wired,
  ~`150` is a healthy wireless hop, and hundreds means a weak multi-hop path. This is
  often the actual root cause when a home-theatre set drops out.
