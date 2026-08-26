# Check catalogue

Every finding produced by `scripts/diagnose.py` is listed here with what it detects, why
it matters, and how confident you should be in the fix.

## Provenance labels

Each finding carries a `source`. **Report it to the user** - it is the difference between
"the vendor says do this" and "the internet says try this".

| Label | Meaning |
|---|---|
| `official-sonos` | Stated in Sonos' *Recommended eero network configuration for Sonos* |
| `official-eero` | Stated in eero's *How do I fix Sonos connectivity issues on my eero network?* |
| `derived` | Computed from observed device state; not a vendor rule but a factual observation |
| `community` | Widely reported fix, **not** vendor-documented. Reversible, but present it as an experiment, not a rule. |

## What the vendors actually say

Condensed from the two support articles, so you do not need to re-fetch them:

**Sonos:**
- A fully **wireless** Sonos setup is the recommended configuration on eero.
- If wiring one player, any eero node is fine.
- If wiring **more than one** player, they must all connect to the **same eero node or
  the same switch**. Wiring players to different eero nodes causes problems.
- With two or more switches, uplink secondary switches back to the primary switch, not
  to a separate eero node.

**Sonos, in-app SonosNet setting:**
- SonosNet can be turned off **system-wide from the app**:
  Settings > Network > SonosNet > Disable SonosNet. It defaults to enabled.
- This is a single toggle. It does **not** require unplugging Ethernet - wired players
  stay wired and stop running their mesh radios. Recommend it in preference to the older
  "go fully wireless" phrasing.

**eero:**
- Connect Sonos via Ethernet **or** Wi-Fi, **not SonosNet**.
- Wi-Fi is recommended; Ethernet is worth it for larger systems (5+ players).
- Any Sonos on Ethernet should have its **Wi-Fi disabled**
  (Sonos app > Settings > System > *room* > *model* > Disable Wi-Fi).
- If problems started after installing eero, re-run Sonos' "connect to a new router" flow.
- eero explicitly notes: **if you are not having problems, change nothing.**

That last point is a real constraint on this skill. Do not push changes at a user whose
system works.

## Sonos-side checks (no authentication needed)

| id | Sev | Source | Detects |
|---|---|---|---|
| `no_players` | high | derived | Nothing reachable by SSDP or a `:1400` sweep |
| `multicast_blocked` | high | derived | Players answer on TCP 1400 but not on multicast - discovery traffic is being dropped |
| `multiple_households` | high | derived | Players belong to different Sonos systems and can never group |
| `subnet_split` | high | derived | Players on genuinely different IP networks (compared by mask) |
| `mixed_sonosnet_and_wifi` | high | official-eero | Both `SONOSNET_MODE` and `STATION_MODE` present |
| `sonosnet_in_use` | medium | official-eero | Whole system on SonosNet where Wi-Fi is recommended |
| `wired_player_radio_active` | medium | official-eero | Wired player still running its radio |
| `multiple_wired_players` | high | official-sonos | More than one wired player - must share one node/switch |
| `stp_blocking_links` | medium | derived | Spanning tree suppressing redundant Sonos links |
| `weak_mesh_uplink` | high | derived | A player reaching the network over a high-cost path, and what depends on it |
| `sonosnet_high_noise` | high | derived | A relaying player sitting in RF interference (noise floor worse than -85 dBm) |
| `sonosnet_radios_disabled` | info | official-eero | Wired players with Wi-Fi turned off - correct, not a fault |
| `ht_satellites` | info | derived | Home-theatre surrounds bonded to a soundbar |
| `firmware_skew` | low | derived | Players on different firmware builds |
| `legacy_24ghz_players` | info | community | 2.4 GHz-only models present (raises severity of WPA3/band steering) |
| `ipv6_on_players` | low | community | Players holding global IPv6 addresses |

### The mode string goes stale - do not trust it alone

A player whose Wi-Fi has been **disabled still reports `wifi_mode: SONOSNET_MODE`**. Judging
by mode alone produces two confident false positives: "running SonosNet and Wi-Fi at once"
and "wired players still have their radio up", on a system where every radio is already off.

Use these instead, both produced by `sonos_scan.py`:

- `sonosnet_radio_active` - `/status/proc/ath_rincon/status` returns an empty `<File/>` when
  the radio is off, and a full dump when it is on. This is the reliable signal.
- `mesh_links` - count of `ath*` ports in the bridge, i.e. live SonosNet links.

`on_sonosnet` already combines them. Note that pure Wi-Fi stations may also report nothing
from the driver endpoint, so only read `sonosnet_radio_active` for players in
`SONOSNET_MODE`.

`SONOSNET_SATELLITE_STATION_PRIMARY_MODE` is a **home-theatre bond** (surrounds/sub attached
to a soundbar), not the general mesh. Do not report it as a mode conflict.

### Notes on the tricky ones

**`subnet_split`** compares `ip/netmask` as networks. eero often issues a `/22`, so
`192.168.4.50` and `192.168.5.10` are usually the *same* subnet. Comparing third octets
produces a false positive - do not "fix" this without checking the mask.

**`multicast_blocked`** only fires when the sweep runs (`--sweep`, or automatically when
SSDP returns nothing). It is the single most explanatory finding when it appears.

**`multiple_wired_players`** cannot by itself prove the players are on *different* nodes -
that needs eero data. Without it, report the rule and ask the user which node/switch each
cable lands in. With eero data, `wired_players_split_across_nodes` answers it directly.

**`weak_mesh_uplink`** is the highest-value local check. Path cost is roughly inverse to
link rate: `0`/`10` wired, ~`150` a healthy hop, hundreds means marginal. Always name what
sits *behind* the weak player - a soundbar on a bad uplink drags its surrounds with it, and
that chain is what the user actually experiences as dropouts.

**`sonosnet_high_noise`** checks the noise floor reported per radio chain. Below about
-95 dBm is healthy; worse than -85 means real interference. The crucial point: **check both
ends of a weak link.** A player can have a pristine radio and still have a terrible link
because its partner sits in a noisy location. Interference is frequently self-inflicted -
several Sonos units in one closet or rack all share a single SonosNet channel and crowd each
other, so the fix is often to disable Wi-Fi on wired players nothing relays through, not to
move the distant speaker.

**`legacy_24ghz_players`** uses a heuristic model list (ZP80/90/100/120, ZPS1/3/5/9/11,
Boost). Unknown models are not flagged, so absence is not proof of a dual-band system.

**Band steering and WPA3 are conditional, not absolute.** They only reach players that
actually associate to eero Wi-Fi. A 2.4 GHz-only player that is wired or on SonosNet never
negotiates with eero, so flagging it is a false positive - these checks drop to `info` in
that case and escalate only when a legacy player is in `STATION_MODE`. Note the coupling:
disabling SonosNet moves every player onto eero Wi-Fi, so checks that were dormant become
live. Re-run the diagnostic after a mode change.

## eero-side checks (need authentication)

| id | Sev | Source | Auto-fixable | Detects |
|---|---|---|---|---|
| `wired_players_split_across_nodes` | high | official-sonos | no (physical) | Wired players on different eero nodes |
| `wired_players_same_node` | info | official-sonos | - | Confirms correct wiring |
| `sonos_on_guest` | high | derived | no | Players on the isolated guest SSID |
| `eero_wpa3` | high/low | community | attempt | WPA3 on (high only when a legacy player is on eero Wi-Fi) |
| `eero_band_steering` | medium/info | community | attempt | Band steering on (medium only when a legacy player is on eero Wi-Fi). One non-production network ignored the write - try it, let the read-back decide |
| `eero_sqm` | medium | community | yes | Smart Queue Management on |
| `eero_upnp_off` | medium | community | yes | UPnP disabled |
| `eero_thread` | low | community | yes | Thread radio on |
| `eero_ipv6` | low | community | yes | IPv6 enabled |
| `no_dhcp_reservations` | low | community | no (app) | No player has a fixed lease |

Only findings whose `fix.kind` is `eero_setting` can be applied by this skill. Everything
else is a guided manual or physical change.

## Reading the mesh before disabling SonosNet

`stp.path_cost` from `sonos_scan.py` is the cheapest read on how healthy the mesh is.
A wired player is `0` (root) or `10`. A direct wireless hop next to a wired player is
around `150`. Costs in the hundreds mean a player is several hops out, on weak links -
and any player hanging off *that* one inherits the weakness.

This matters for two reasons. First, a bonded home-theatre set whose soundbar sits at the
far end of a long mesh chain is the classic cause of surrounds dropping out and re-bonding.
Second, **before recommending SonosNet be disabled, check what depends on it** - a player
whose only uplink is a SonosNet hop will fall off the network entirely when the mesh stops.
Wire it, or confirm it has good eero Wi-Fi coverage, first.

## Ordering fixes

When several findings appear, apply them in this order - cheapest and most reversible
first, and re-measure between stages:

1. **eero settings** (`eero_setting` fixes). Instant, reversible, no speaker disruption.
2. **Sonos app changes** - disable Wi-Fi on wired players, or move players to Wi-Fi mode.
   Disruptive but reversible.
3. **Physical rewiring** - consolidating wired players onto one node or switch.

Re-run `sonos_scan.py` + `diagnose.py` after each stage. Mode changes take a minute or
two to settle and STP needs to reconverge, so allow time before re-scanning.

## SonosNet will not abandon a bad path on its own

Worth knowing before recommending anything: a player stays on SonosNet whenever a SonosNet
path exists, **even when that path is far worse than an eero node sitting in the same room**.
An unwired player will not fall back to eero Wi-Fi while any reachable Sonos relay remains.

So "there is a strong eero node right there, why is it not using it?" has a simple answer,
and it also gives a remedy that needs no cabling: disable Wi-Fi on the distant relaying
players, and the stranded player falls back to eero Wi-Fi and associates locally. Verify the
player has usable eero coverage first, and confirm nothing else depends on the relays being
disabled - otherwise those players go offline.

## Deliberate non-checks

- **SonosNet channel vs eero 2.4 GHz channel.** eero does not expose a fixed 2.4 GHz
  channel through the API (it manages channels dynamically), so a comparison would be
  guesswork. If a system stays on SonosNet, mention the Sonos-app channel setting as a
  manual tuning knob instead.
- **Speed tests / bandwidth.** Sonos problems on eero are almost never bandwidth.
- **Per-player packet counters.** `dropped:` counts in `ifconfig` are cumulative since
  boot and normal in the thousands on a busy mesh; they generate noise, not signal.
