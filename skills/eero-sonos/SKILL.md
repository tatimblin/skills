---
name: eero-sonos
description: Diagnose and fix Sonos speakers misbehaving on an eero network - players dropping out, disappearing from the app, stuttering, failing to group, or never finishing setup.
---

# eero + Sonos alignment

Sonos and eero conflict in specific, checkable ways. Measure the live system, report what
conflicts with each vendor's guidance, and offer to fix what is safe to fix.

## Ground rules

- **Never change a working system.** eero's own article says to leave it alone if nothing
  is wrong. Ask what symptom the user sees first; if there is none, say the system looks
  healthy and stop.
- **Report the `source` of every finding.** `official-sonos` / `official-eero` are vendor
  rules; `community` findings are widely-reported experiments. Don't present them as equal.
- **Confirm before every write.** `apply` does nothing without `--confirm`, and writes a
  rollback file first. Show the exact before/after and get an explicit yes.
- **The eero API is unofficial.** It can accept a `PUT` and silently ignore it. The scripts
  read back and verify; report honestly when a change didn't take.

## Script paths

Every command below runs a script from `$SKILL_DIR`, the directory holding this `SKILL.md`.
That is **not** the working directory - the shell starts in the user's project. Set it once
before the first command:

```bash
SKILL_DIR=/absolute/path/to/eero-sonos     # the directory containing this SKILL.md
```

As a Claude Code plugin, that is `"$CLAUDE_PLUGIN_ROOT"`. Bare relative
paths work only if the shell is already in the skill directory - don't rely on it.

## Workflow

### 1. Ask what is broken

One question: *what does the problem look like, and when did it start?* Common shapes -
players vanish from the app, audio stutters or drops, rooms won't group, one speaker is
always the problem, setup never completes.

### 2. Scan the speakers (no credentials needed)

```bash
python3 "$SKILL_DIR"/scripts/sonos_scan.py --pretty > /tmp/sonos.json
```

Add `--sweep` to also TCP-scan port 1400 when players are disappearing: a player that
answers on 1400 but not on multicast proves discovery traffic is being dropped, which
explains most disappearing-speaker reports. The sweep runs automatically if SSDP finds
nothing.

Run this from any machine on the speakers' network. If it finds nothing, check the machine
is on the main SSID, not a guest network or VPN.

### 3. Diagnose locally first

```bash
python3 "$SKILL_DIR"/scripts/diagnose.py --sonos /tmp/sonos.json
```

This catches most real problems: SonosNet/Wi-Fi mixing, wired players with live radios,
multiple wired players, loop-prone bridging, split households and subnets. Show this report
before asking for any credentials.

### 4. Add eero data only if needed

The local scan can't see eero's settings, and can't tell **which eero node each wired
player is plugged into** - the thing Sonos' article constrains most tightly. Offer to
authenticate if the local report raises `multiple_wired_players`, or the user wants the
settings audited.

Explain the trade first: eero has no local API, so this means logging into their eero
account with a one-time SMS or email code. The session token is cached at
`~/.config/eero-sonos/session.json` (mode 0600) and never printed.

```bash
python3 "$SKILL_DIR"/scripts/eero_client.py login --id "+15551234567"   # or an email address
python3 "$SKILL_DIR"/scripts/eero_client.py verify --code 123456
python3 "$SKILL_DIR"/scripts/eero_client.py fetch --match-sonos /tmp/sonos.json > /tmp/eero.json
python3 "$SKILL_DIR"/scripts/diagnose.py --sonos /tmp/sonos.json --eero /tmp/eero.json
```

Ask the user to read the code off their phone; don't try to obtain it.

Pass `--match-sonos` whenever possible: accounts often hold several networks, and the first
one is frequently not the speakers'.

### 5. Offer fixes, in order

`diagnose.py --json` lists `auto_fixable_eero_settings`, the settings this skill can change
directly. Work in this order, re-scanning between stages:

1. **eero settings** - instant and reversible.
   ```bash
   python3 "$SKILL_DIR"/scripts/eero_client.py apply --set band_steering=false --set sqm=false   # dry run
   python3 "$SKILL_DIR"/scripts/eero_client.py apply --set band_steering=false --set sqm=false --confirm
   ```
   Without `--confirm` it prints the planned before/after and changes nothing. With it, it
   writes a rollback file, then reads back and verifies each field.

   Expect some fields to refuse: eero can return 200 and silently ignore a write - seen with
   `band_steering` on one non-production network even though `capabilities` claimed
   otherwise. Whether that holds on production is unverified, so attempt the write and let
   the read-back decide rather than predicting failure. Relay the result honestly, and point
   the user at the eero app for anything ignored.

2. **Sonos app changes** - there is **no local write API**, so walk the user through the app
   steps in the finding's `fix.steps`. Worth knowing by heart:
   **Settings > Network > SonosNet > Disable SonosNet** turns the mesh off system-wide
   without unplugging anything.

   First check `stp.path_cost` in the scan. Any player whose only uplink is a SonosNet hop
   will drop off the network when the mesh stops - wire it or confirm eero Wi-Fi coverage
   first. Disabling SonosNet also moves every player onto eero Wi-Fi, which makes band
   steering and WPA3 newly relevant.

3. **Physical rewiring** - consolidating wired players onto one eero node or switch.

Undo anything with:
```bash
python3 "$SKILL_DIR"/scripts/eero_client.py rollback ~/.config/eero-sonos/rollback-<stamp>.json --confirm
```

### 6. Re-measure

Re-run steps 2-3 after each stage. Mode changes and STP reconvergence take a minute or two,
so wait before re-scanning. Report what actually changed instead of assuming the fix worked.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/sonos_scan.py` | SSDP + port-1400 discovery, per-player state -> JSON. Stdlib only. |
| `scripts/eero_client.py` | eero cloud auth, read-only `fetch`, verified `apply`, `rollback`. |
| `scripts/diagnose.py` | Correlates both sides into findings with severity, evidence, provenance and fixes. |

`sonos_scan.py` and `diagnose.py` need no credentials and make no network writes.

## References

- **`references/checks.md`** - every check, what it detects, provenance, and the condensed
  vendor guidance. Read to explain *why* a finding matters, or before adding a check.
- **`references/sonos-local-api.md`** - the port-1400 endpoints, telling SonosNet from
  Wi-Fi, and reading the spanning-tree output. Read when interpreting raw scan data or
  extending the scanner.
- **`references/eero-api.md`** - auth flow, endpoints, settings fields, and the
  read-back-to-verify rule. Read before making any eero API call by hand.

## Interpreting results

- **eero commonly issues a `/22`.** `192.168.4.x` and `192.168.5.x` are usually the same
  subnet. Compare networks using the mask, never the third octet.
- **`100FD` link speed is normal.** Most Sonos players have 100 Mbps ports. Not a fault,
  not worth reporting.
- **A disabled radio still reports `SONOSNET_MODE`.** Judge by `sonosnet_radio_active` and
  `mesh_links`, never the mode string - otherwise you'll report SonosNet problems on a
  system whose radios are already off.
- **SonosNet never abandons a bad path by itself.** A player keeps relaying through a
  distant Sonos even when an eero node sits in the same room. That is why
  `weak_mesh_uplink` matters, and why disabling Wi-Fi on the distant relays is a valid
  no-cabling fix - the stranded player falls back to eero Wi-Fi and associates locally.
  First check it has coverage and that nothing else depends on those relays.
- **Check both ends of a weak link.** A player can have a pristine noise floor and a
  terrible link, because the player it relays through sits in interference.
- **eero cannot see SonosNet players' signal.** It reports them as
  `connection_type: "sonos"` with `signal: null`, so the eero app will never show a weak
  link for one. `stp.path_cost` in the Sonos scan is the only view: `0`/`10` is wired,
  ~`150` is a healthy wireless hop, hundreds means a weak multi-hop path. This is often the
  real root cause when a home-theatre set drops out.
