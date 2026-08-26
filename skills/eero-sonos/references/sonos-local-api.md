# Sonos local HTTP API (port 1400)

Every Sonos player runs an unauthenticated HTTP diagnostics server on **TCP 1400**.
No account, token, or cloud call is needed - only L3 reachability. All responses are
XML wrapped in `<ZPSupportInfo>`.

Verified against firmware **92.0-71170** and **86.2-70230** (Nov 2025 builds).

## Contents
- [Discovery](#discovery)
- [Endpoint index](#endpoint-index)
- [/status/zp - identity](#statuszp---identity)
- [/status/wireless - SonosNet vs Wi-Fi](#statuswireless---sonosnet-vs-wi-fi)
- [/status/enetports - wired detection](#statusenetports---wired-detection)
- [/status/showstp - mesh topology](#statusshowstp---mesh-topology)
- [/status/ifconfig - addressing](#statusifconfig---addressing)
- [What is NOT available locally](#what-is-not-available-locally)

## Discovery

SSDP `M-SEARCH` to `239.255.255.250:1900` with:

```
ST: urn:schemas-upnp-org:device:ZonePlayer:1
```

Useful response headers:

| Header | Meaning |
|---|---|
| `LOCATION` | `http://<ip>:1400/xml/device_description.xml` |
| `X-RINCON-HOUSEHOLD` | Sonos system id. **Differing values = separate systems that can never group.** |
| `X-RINCON-BOOTSEQ` | Increments on reboot; a fast-climbing value means the player keeps restarting |
| `SERVER` | `Linux UPnP/1.0 Sonos/92.0-71170 (ZPS16)` - the parenthesised code is the model |

**Diagnostic trick:** run SSDP discovery *and* a TCP sweep of `:1400`. A player that
answers on 1400 but never replies to multicast proves multicast/IGMP is being dropped
between the controller and that player - one of the highest-value findings available,
and the root cause behind most "speakers keep disappearing" reports.

## Endpoint index

`GET http://<ip>:1400/status` returns the live list. On current firmware:

```
/status/enetports                 ethernet port link state
/status/wireless                  radio mode
/status/zp                        identity, firmware, MAC
/status/VERSION                   build string
/status/proc/ath_rincon/status    SonosNet radio driver detail
/status/ifconfig                  interface addressing and counters
/status/showstp                   spanning tree - the mesh topology
```

`/status/topology`, `/status/perf` and `/status/netsettings` still resolve but return an
**empty** `<ZPSupportInfo/>` on current firmware. Do not rely on them.

### HTTP 200 proves nothing

Any path under `/status/` returns **HTTP 200 with an empty `<ZPSupportInfo></ZPSupportInfo>`**,
including paths that do not exist. `/status/thisdoesnotexist12345` answers 200 exactly like
`/status/wifictrl` does. Before concluding an endpoint exists, compare its body against a
deliberately bogus path - identical output means the endpoint is not real.

## /status/zp - identity

`<ZPInfo>` children worth reading:

| Field | Use |
|---|---|
| `ZoneName` | Room name shown in the app |
| `MACAddress` | Join key against eero's device list |
| `LocalUID` | `RINCON_<mac>01400` |
| `SoftwareVersion` | Firmware; differing values across players = update skew |
| `SeriesID` / `HardwareVersion` | Hardware generation |
| `HouseholdControlID` | `Sonos_xxxx.yyyy` - split on `.` for the household id |

Current firmware does **not** expose `WirelessMode`, `WifiEnabled` or `HasConfiguredSSID`
here, contrary to older documentation. Use `/status/wireless` instead.

## /status/wireless - SonosNet vs Wi-Fi

```xml
<Wireless><WirelessInfo Name='Wireless Info'>
  <WifiMode>0</WifiMode>
  <WifiModeString>SONOSNET_MODE</WifiModeString>
  <IdleState>0x00000004</IdleState>
  <BusyClients>LOCAL_SONOSNET, NO_PRIMARY</BusyClients>
</WirelessInfo></Wireless>
```

| `WifiMode` | `WifiModeString` | Meaning |
|---|---|---|
| `0` | `SONOSNET_MODE` | Player runs Sonos' own 2.4 GHz mesh (its radio is an AP) |
| `1` | `STATION_MODE` | Player is a normal client joined to your Wi-Fi SSID |

This single field decides most of the diagnosis. eero's support article asks you to run
**either** Ethernet **or** Wi-Fi, and explicitly not SonosNet - so a system reporting a
mix of `SONOSNET_MODE` and `STATION_MODE` is misaligned by the vendor's own guidance.

A player that is wired *and* reports `SONOSNET_MODE` still has its radio up and is
bridging your wired LAN into the Sonos mesh - eero's article says to disable Wi-Fi on
wired players.

### The mode string persists after the radio is disabled

`WifiModeString` still reads `SONOSNET_MODE` on a player whose Wi-Fi has been turned off in
the app. Confirm with `/status/proc/ath_rincon/status` (below) before concluding a radio is
active.

`SONOSNET_SATELLITE_STATION_PRIMARY_MODE` appears on home-theatre surrounds bonded to a
soundbar. That is an HT bond, not the general mesh.

## /status/proc/ath_rincon/status - radio truth

Not in the older documentation, and the only way to see RF conditions. When the radio is off
it returns an empty `<File name='/proc/ath_rincon/status'></File>`; when on it returns:

```
Mode: INFRA (sonosnet)
Operating on channel 2462
   IEEE channel: 11
Home channel is 2462
Noise Floor: -119 dBm (chain 0 ctl)
Node 5C:AA:FD:EF:EE:7F - FROM 25 : TO 22 : STP 03 : MODEL 17.3: KEY 6
```

- **Presence of `Mode:`** - the radio is up. An empty file means Wi-Fi is disabled.
- **`Operating on channel` / `Home channel`** - current vs SonosNet home channel. SonosNet
  uses **one channel system-wide**, so co-located players all crowd it.
- **`Noise Floor`** per chain - below about -95 dBm is healthy, worse than -85 is real
  interference. Observed in practice: -119 dBm on a player in an open room versus -75 dBm on
  one in a closet with three other Sonos units.
- **`Node <mac> - FROM n : TO n`** - per-neighbour link rates. Compare them: a healthy
  same-room link ran 83/75 while a through-the-wall link on the same system ran 22/25.

Reading both ends of a link is what distinguishes "the distant speaker is too far" from
"the speaker it relays through is sitting in interference" - which have completely
different fixes.

## /status/enetports - wired detection

```xml
<EnetPorts>
  <Port port='0'><Link>0</Link><Speed>0</Speed></Port>
  <Port port='1'><Link>1</Link><Speed>100FD</Speed></Port>
</EnetPorts>
```

`Link` of `1` means a cable is up. `Speed` is e.g. `100FD` (100 Mbps full duplex - normal
for Sonos, most players have 100 Mbps ports, so `100FD` is not a fault). An empty
`<EnetPorts></EnetPorts>` means the model has no Ethernet jack (e.g. Roam).

## /status/showstp - mesh topology

The highest-signal endpoint. Sonos bridges its interfaces in `br0` and runs spanning tree.

```
br0
 bridge id          9000.804af2aa2fa2
 designated root    9000.000e583fee34
 root port          1        path cost   10
eth0 (1)
 port id 8001       state   forwarding
ath0 (3) - tunnel to B8:E9:37:A8:4F:07 (remote STP state = blocking, direct = 1)
 port id 8003       state   blocking
```

How to read it:

- `bridge id == designated root` -> this player is the **STP root** of the Sonos mesh.
- `path cost` from each player to the root: `10` = one Ethernet hop (wired into your LAN);
  large values (hundreds) = reached over wireless SonosNet hops.
- `ath0 ... tunnel to <MAC>` lines are **SonosNet wireless links**. A player can list
  several, one per mesh neighbour.
- `state blocking` means STP is suppressing that link because it would otherwise form a
  **loop**. Blocking links are not broken, but each STP reconvergence (a player rebooting,
  an eero node dropping) briefly interrupts audio.
- `STP is disabled for this interface` appears on players in `STATION_MODE` - they are
  plain Wi-Fi clients and do not participate in the mesh.

Counting players whose `path cost` is `10` tells you how many are wired directly into the
LAN - which is what Sonos' "all wired players on one node/switch" rule constrains.

## /status/ifconfig - addressing

`br0` carries the player's IP. Parse `inet addr:` and `Mask:` together and compare
**networks, not octets** - eero commonly hands out a `/22`, so `192.168.4.x` and
`192.168.5.x` are frequently the *same* subnet. Treating them as split is a false positive.

Also exposes `inet6 addr: ... Scope:Global` (IPv6 presence) and `dropped:` counters.

## What is NOT available locally

There is **no local write API**. Verified on current firmware: no `wifictrl` or equivalent
control endpoint exists (see the HTTP 200 warning above - probing for one gives a false
positive if you only check the status code).

All of the following are **mobile-app only**, and must be presented as guided manual steps:

| Change | Where |
|---|---|
| Enable/disable SonosNet **system-wide** | Settings > Network > SonosNet > Disable SonosNet |
| Disable one player's Wi-Fi radio | Settings > System > *room* > *model* > Disable Wi-Fi |
| SonosNet channel | Settings > System > Network > SonosNet Channel |

The system-wide SonosNet toggle is the important one and is easy to miss: it is a single
switch that does **not** require unplugging Ethernet. Wired players stay wired and simply
stop running their mesh radios. Before recommending it, check the mesh path costs - any
player whose only uplink is SonosNet will drop off the network when it is disabled.

The legacy UPnP control endpoints (`/MediaRenderer/AVTransport/Control` etc.) still exist
for playback control but are irrelevant to network alignment.
