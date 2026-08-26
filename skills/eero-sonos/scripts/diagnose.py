#!/usr/bin/env python3
"""Correlate Sonos player state with eero network settings and report misalignments.

  python3 diagnose.py --sonos sonos.json                  # local-only checks
  python3 diagnose.py --sonos sonos.json --eero eero.json  # full check set
  python3 diagnose.py --sonos sonos.json --json            # machine-readable

Each finding carries a `source`:
  official-sonos / official-eero  - stated in the vendor's own support article
  community                       - widely reported fix, NOT vendor-documented
Treat `community` fixes as opt-in experiments; they are reversible.
"""
import argparse, ipaddress, json, sys

SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
SEV_MARK = {"high": "!!", "medium": " !", "low": "  ", "info": "  "}

# Sonos models with 2.4 GHz-only radios. Band steering / WPA3 / 5 GHz-only SSIDs
# strand these. Heuristic list - unknown models are not flagged.
LEGACY_24_ONLY = {
    "ZP80", "ZP90", "ZP100", "ZP120", "ZPS1", "ZPS3", "ZPS5", "ZPS9",
    "ZPS11", "BR100", "ZB100",
}


def F(fid, sev, title, detail, evidence=None, source="community", fix=None):
    return {"id": fid, "severity": sev, "title": title, "detail": detail,
            "evidence": evidence or [], "source": source, "fix": fix or {}}


# --------------------------------------------------------------------------- sonos side
def check_sonos(s):
    out = []
    devs = [d for d in s.get("devices", []) if d.get("reachable")]
    if not devs:
        return [F("no_players", "high", "No Sonos players reachable",
                  "Neither SSDP discovery nor a :1400 sweep found a player. Confirm this "
                  "machine is on the same VLAN/SSID as the speakers.", source="derived")]

    disc = s.get("discovery", {})
    missed = disc.get("ssdp_missed") or []
    if missed:
        out.append(F(
            "multicast_blocked", "high", "Multicast discovery is being dropped",
            f"{len(missed)} player(s) answer on TCP :1400 but never replied to the SSDP "
            "multicast search. Sonos discovery, grouping and controller pairing all ride on "
            "multicast, so this alone explains 'speakers keep disappearing'.",
            evidence=missed, source="derived",
            fix={"kind": "manual", "steps": [
                "Confirm the controller and speakers are on the same SSID/VLAN (not Guest).",
                "In the eero app, ensure the client device is not on the Guest network.",
                "If you run a VPN or a mesh extender behind eero, take it out of the path and re-scan.",
            ]}))

    # households
    hh = {d.get("household") for d in devs if d.get("household")}
    if len(hh) > 1:
        out.append(F("multiple_households", "high", "Players split across Sonos households",
                     "Players belong to different Sonos systems, so they can never group. "
                     "Factory-reset the odd ones out and re-add them to the main system.",
                     evidence=sorted(hh), source="derived",
                     fix={"kind": "manual", "steps": [
                         "Identify the minority household below and factory reset those players.",
                         "Re-add them from the Sonos app so they join the main system."]}))

    # subnets - compare by network, not by third octet (eero often hands out a /22)
    nets = {}
    for d in devs:
        if d.get("cidr"):
            nets.setdefault(d["cidr"], []).append(d["ip"])
    if len(nets) > 1:
        out.append(F("subnet_split", "high", "Players are on different IP subnets",
                     "Sonos requires every player and controller on one subnet; discovery "
                     "traffic does not cross subnets.",
                     evidence=[f"{c}: {', '.join(ips)}" for c, ips in nets.items()],
                     source="derived",
                     fix={"kind": "manual", "steps": [
                         "Remove any secondary router doing its own NAT (double-NAT).",
                         "Put downstream routers/APs in bridge mode so eero owns DHCP."]}))

    # A player whose Wi-Fi has been disabled still reports SONOSNET_MODE, so trust the
    # radio driver and live mesh links rather than the mode string.
    sonosnet = [d for d in devs
                if d.get("on_sonosnet")
                or (d.get("wifi_mode") == "SONOSNET_MODE"
                    and "sonosnet_radio_active" not in d)]
    station = [d for d in devs if d.get("wifi_mode") == "STATION_MODE"]
    satellites = [d for d in devs if d.get("is_ht_satellite")]
    # Guard on key presence: scans taken before this field existed would otherwise look
    # like every radio was off.
    radios_off = [d for d in devs
                  if "sonosnet_radio_active" in d
                  and d.get("wifi_mode") == "SONOSNET_MODE"
                  and not d["sonosnet_radio_active"]]
    wired = [d for d in devs if d.get("wired")]

    # eero's article: use Ethernet or wifi, but not SonosNet - and do not mix.
    if sonosnet and station:
        out.append(F(
            "mixed_sonosnet_and_wifi", "high", "System is running SonosNet and Wi-Fi at once",
            f"{len(sonosnet)} player(s) are in SONOSNET_MODE (Sonos' own 2.4 GHz mesh) while "
            f"{len(station)} are joined to your eero Wi-Fi as normal clients. eero's support "
            "article asks you to pick one - mixing them creates two overlapping bridged paths "
            "between the same devices, which is the classic eero/Sonos dropout pattern.",
            evidence=[f"SonosNet: {', '.join(d['zone'] for d in sonosnet)}",
                      f"Wi-Fi:    {', '.join(d['zone'] for d in station)}"],
            source="official-eero",
            fix={"kind": "manual", "steps": [
                "Decide on one mode. Wi-Fi is eero's recommendation unless you have 5+ players.",
                "To leave SonosNet: Sonos app > Settings > Network > SonosNet > "
                "Disable SonosNet. This is a single system-wide toggle - you do NOT need "
                "to unplug anything. Wired players stay wired; their mesh radios go quiet.",
                "Before disabling, check nothing depends on SonosNet to reach the network "
                "(see the mesh path costs) - a player whose only uplink is SonosNet will "
                "drop off when it is turned off.",
                "To stay on SonosNet: wire players to ONE eero node or switch, and disable "
                "Wi-Fi on each wired player that nothing else relays through."]}))
    elif sonosnet and not station:
        out.append(F(
            "sonosnet_in_use", "medium", "Whole system is on SonosNet",
            "Every player is on Sonos' own mesh rather than your eero Wi-Fi. eero recommends "
            "Wi-Fi mode unless you have a large (5+) wired system. SonosNet occupies a fixed "
            "2.4 GHz channel and can beat against eero's own 2.4 GHz radio.",
            evidence=[d["zone"] for d in sonosnet], source="official-eero",
            fix={"kind": "manual", "steps": [
                "Sonos app > Settings > Network > SonosNet > Disable SonosNet "
                "(single system-wide toggle; no rewiring needed).",
                "First confirm no player depends on SonosNet as its only uplink.",
                "If you keep SonosNet, set its channel away from eero's 2.4 GHz channel: "
                "Sonos app > Settings > System > Network > SonosNet Channel."]}))

    # eero's article: a wired player should have its wifi disabled
    wired_with_radio = [d for d in wired
                        if d.get("on_sonosnet") and d.get("mesh_links", 0) > 0]
    if wired_with_radio:
        out.append(F(
            "wired_player_radio_active", "medium", "Wired players still have their radio up",
            "eero's article says any Sonos connected by Ethernet should have Wi-Fi disabled. "
            "These players are wired but still running the SonosNet radio, so each one is "
            "bridging your wired LAN into the Sonos mesh.",
            evidence=[f"{d['zone']} ({d['ip']}) link {', '.join(d.get('link_speeds') or [])}"
                      for d in wired_with_radio],
            source="official-eero",
            fix={"kind": "manual", "steps": [
                "Sonos app > Settings > System > <room> > <model name> > Disable Wi-Fi.",
                "Do this for every player that stays on Ethernet.",
                "Leave at least one wired player with its radio ON if other players rely on "
                "SonosNet to reach the network."]}))

    # Sonos' own article: multiple wired players must share one node or one switch
    if len(wired) > 1:
        out.append(F(
            "multiple_wired_players", "high", f"{len(wired)} players are wired",
            "Sonos' eero article requires that when more than one Sonos is wired, they all "
            "connect to the SAME eero node or the SAME switch. Wiring them to different eero "
            "nodes bridges the Sonos mesh across the eero backhaul and causes exactly the "
            "dropouts and stutter people report. Cross-check node attribution with eero data.",
            evidence=[f"{d['zone']} ({d['ip']}) mac {d.get('mac')}" for d in wired],
            source="official-sonos",
            fix={"kind": "physical", "steps": [
                "Move every wired Sonos onto one eero node, or onto one switch.",
                "If you use two switches, uplink the secondary switch to the primary switch, "
                "not to a separate eero node."]}))

    # STP blocking = redundant bridged paths that STP is actively suppressing
    blocked = []
    for d in devs:
        for p in (d.get("stp") or {}).get("ports", []):
            if p.get("state") == "blocking":
                blocked.append(f"{d['zone']}: {p['iface']} -> {p.get('tunnel_to') or 'wired'}")
    if blocked:
        out.append(F(
            "stp_blocking_links", "medium", "Spanning tree is blocking redundant Sonos links",
            "Sonos' bridge has put these links into 'blocking' because they would otherwise "
            "form a loop. The topology still works, but every STP recalculation (a player "
            "rebooting, an eero node dropping) briefly interrupts audio while paths converge.",
            evidence=blocked, source="derived",
            fix={"kind": "physical", "steps": [
                "Reduce redundant paths: consolidate wired players onto one node/switch, or "
                "disable Wi-Fi on wired players so they stop forming mesh tunnels."]}))

    noisy = [d for d in devs
             if d.get("sonosnet_radio_active") and d.get("worst_noise_floor") is not None
             and d["worst_noise_floor"] > -85]
    if noisy:
        out.append(F(
            "sonosnet_high_noise", "high", "A relaying player is sitting in RF interference",
            "Noise floor should be around -95 dBm or lower. These players are measurably "
            "worse, which caps the link rate for anything relaying through them. A player "
            "with a clean radio can still have a bad link if the far end is noisy - check "
            "both ends before blaming the distant speaker.",
            evidence=[f"{d['zone']}: worst {d['worst_noise_floor']} dBm on ch "
                      f"{d.get('radio_channel')} ({d.get('mesh_links')} mesh links)"
                      for d in noisy], source="derived",
            fix={"kind": "manual", "steps": [
                "Interference is often self-inflicted: co-located Sonos units all share one "
                "SonosNet channel and crowd each other. Disabling Wi-Fi on wired players "
                "that nothing relays through removes transmitters and lowers the floor.",
                "Keep at least one radio up if any player depends on SonosNet to reach the "
                "network - check mesh path costs first.",
                "If the floor stays high, move SonosNet to another channel: Sonos app > "
                "Settings > System > Network > SonosNet Channel."]}))

    weak = [d for d in devs if (d.get("stp") or {}).get("path_cost") is not None
            and d["stp"]["path_cost"] > 300]
    if weak:
        dependents = {}
        for d in devs:
            for p in (d.get("stp") or {}).get("ports", []):
                for w in weak:
                    rmac = (w.get("mac") or "").upper()
                    # only genuinely downstream players - a neighbour with a LOWER cost is
                    # upstream of this one, not depending on it
                    dcost = (d.get("stp") or {}).get("path_cost")
                    if (p.get("tunnel_to") and rmac
                            and p["tunnel_to"][:14] == rmac[:14]
                            and dcost is not None and dcost > w["stp"]["path_cost"]):
                        dependents.setdefault(w["zone"], []).append(d["zone"])
        out.append(F(
            "weak_mesh_uplink", "high", "A player is reaching the network over a weak path",
            "SonosNet path cost is roughly inverse to link rate: 0 or 10 means wired, ~150 is "
            "a healthy wireless hop. These are far worse, so audio to them - and to anything "
            "behind them - is riding a marginal link. A bonded home-theatre set on such a path "
            "is the classic cause of dropouts and surrounds losing their bond.",
            evidence=[f"{d['zone']}: cost {d['stp']['path_cost']}"
                      + (f" (relays for {', '.join(dependents[d['zone']])})"
                         if dependents.get(d["zone"]) else "")
                      for d in weak], source="derived",
            fix={"kind": "manual", "steps": [
                "Check whether an eero node sits nearer this player than its current relay - "
                "SonosNet will not use it while a SonosNet path exists, even a much worse one.",
                "Wire the player to that node if practical.",
                "Otherwise disable Wi-Fi on the distant relaying players so the stranded "
                "player falls back to eero Wi-Fi and associates locally.",
                "Check the noise floor at BOTH ends - a clean radio can still have a bad link "
                "if its partner is in a noisy spot."]}))

    # firmware skew
    if radios_off:
        out.append(F(
            "sonosnet_radios_disabled", "info", "Some players have their Wi-Fi radio off",
            "These report SONOSNET_MODE but their radio driver is idle with no mesh links - "
            "Wi-Fi has been disabled on them. That is eero's recommendation for wired "
            "players, and is not a fault.",
            evidence=[d["zone"] for d in radios_off], source="official-eero"))

    if satellites:
        out.append(F(
            "ht_satellites", "info", "Home-theatre satellites are bonded",
            "These are surround/sub units bonded to a soundbar, which hosts them directly. "
            "That is normal and separate from the general SonosNet mesh - do not treat it as "
            "a SonosNet/Wi-Fi mode conflict.",
            evidence=[f"{d['zone']} (cost {(d.get('stp') or {}).get('path_cost')})"
                      for d in satellites], source="derived"))

    versions = {}
    for d in devs:
        versions.setdefault(d.get("sw", "?"), []).append(d.get("zone", d["ip"]))
    if len(versions) > 1:
        out.append(F(
            "firmware_skew", "low", "Players are on different firmware builds",
            "Mixed builds usually mean some hardware has reached end of updates. It is worth "
            "confirming in the Sonos app that no update is pending.",
            evidence=[f"{v}: {', '.join(z)}" for v, z in sorted(versions.items())],
            source="derived",
            fix={"kind": "manual", "steps": ["Sonos app > Settings > System > System Updates."]}))

    legacy = [d for d in devs if (d.get("model_code") or "").upper() in LEGACY_24_ONLY]
    if legacy:
        wifi_legacy = [d for d in legacy if d.get("wifi_mode") == "STATION_MODE"]
        out.append(F(
            "legacy_24ghz_players", "info", "Some players are 2.4 GHz-only",
            "These models have no 5 GHz radio and predate WPA3. That only matters while they "
            "associate to eero Wi-Fi: "
            + (f"{len(wifi_legacy)} of them currently do."
               if wifi_legacy else
               "none currently do (all are wired or on SonosNet), so WPA3 and band steering "
               "are not affecting them today. It would change if you disable SonosNet."),
            evidence=[f"{d['zone']} ({d.get('model_code')}) - {d.get('wifi_mode')}"
                      for d in legacy], source="community"))

    v6 = [d for d in devs if d.get("ipv6_global")]
    if v6:
        out.append(F(
            "ipv6_on_players", "low", "Players hold global IPv6 addresses",
            "Sonos is IPv4-only for control traffic. IPv6 on the LAN is not itself a fault, "
            "but it is a commonly reported aggravator on eero and is cheap to turn off.",
            evidence=[f"{d['zone']}: {len(d['ipv6_global'])} global addr" for d in v6],
            source="community",
            fix={"kind": "eero_setting", "sets": {"ipv6_upstream": False,
                                                  "ipv6_downstream": False}}))
    return out


# --------------------------------------------------------------------------- eero side
def _first(d, *paths):
    """Fetch the first present value among dotted paths."""
    for p in paths:
        cur = d
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur is not None:
            return cur
    return None


def _truthy_setting(v):
    """eero returns bools, or objects like {'enabled': True} / {'mode': 'on'}."""
    if isinstance(v, bool):
        return v
    if isinstance(v, dict):
        for k in ("enabled", "enable", "on", "active"):
            if isinstance(v.get(k), bool):
                return v[k]
        if isinstance(v.get("mode"), str):
            return v["mode"].lower() not in ("off", "disabled", "none")
    if isinstance(v, str):
        return v.lower() not in ("off", "disabled", "none", "false")
    return None


def check_eero(e, s):
    out = []
    net = e.get("network") or {}
    if net.get("_error"):
        return [F("eero_unreadable", "info", "Could not read eero network settings",
                  str(net["_error"]), source="derived")]

    devs = [d for d in s.get("devices", []) if d.get("reachable")]
    # Band steering / WPA3 only reach players that actually associate to eero Wi-Fi.
    # A 2.4 GHz-only player that is wired, or on SonosNet, never negotiates with eero -
    # flagging those produces a false positive.
    on_eero_wifi = [d for d in devs if d.get("wifi_mode") == "STATION_MODE"]
    legacy_on_wifi = [d for d in on_eero_wifi
                      if (d.get("model_code") or "").upper() in LEGACY_24_ONLY]
    legacy_present = bool(legacy_on_wifi)
    legacy_anywhere = [d for d in devs
                       if (d.get("model_code") or "").upper() in LEGACY_24_ONLY]

    def setting(name, *alts):
        return _truthy_setting(_first(net, name, *alts))

    # --- knobs that are commonly reported to break Sonos on eero
    knobs = [
        ("band_steering", "eero_band_steering",
         "medium" if legacy_on_wifi else "info", "Band steering is on",
         ("Band steering influences which band a dual-band client picks. "
          + (f"{len(legacy_on_wifi)} 2.4 GHz-only player(s) are associating to eero Wi-Fi, "
             "where this can make association less reliable."
             if legacy_on_wifi else
             "No 2.4 GHz-only player is currently on eero Wi-Fi (they are wired or on "
             "SonosNet), so this does not affect Sonos today - it would matter if you "
             "moved them onto Wi-Fi.")),
         {"band_steering": False}),
        ("sqm", "eero_sqm", "medium", "Smart Queue Management (SQM) is on",
         "SQM shapes and reorders traffic. It is widely reported to add latency to Sonos' "
         "time-sensitive multi-room sync and is a common first thing to disable.",
         {"sqm": False}),
        ("wpa3", "eero_wpa3", "high" if legacy_present else "low", "WPA3 is enabled",
         "Older Sonos hardware cannot join WPA3 or WPA2/WPA3 transition-mode networks."
         + ("" if legacy_present else " No legacy player is on eero Wi-Fi right now, so "
            "this only bites if you move them onto Wi-Fi."),
         {"wpa3": False}),
        ("thread", "eero_thread", "low", "Thread radio is enabled",
         "Thread is 802.15.4 in the 2.4 GHz band. It shares spectrum with SonosNet and "
         "2.4 GHz-only players.",
         {"thread": False}),
    ]
    for field, fid, sev, title, detail, sets in knobs:
        val = setting(field)
        if val is True:
            out.append(F(fid, sev, title, detail,
                         evidence=[f"{field} = {json.dumps(net.get(field))}"],
                         source="community",
                         fix={"kind": "eero_setting", "sets": sets}))

    if setting("ipv6_upstream", "ipv6") is True:
        out.append(F("eero_ipv6", "low", "IPv6 is enabled on the eero network",
                     "Commonly reported to aggravate Sonos discovery on eero. Reversible.",
                     evidence=[f"ipv6_upstream = {json.dumps(net.get('ipv6_upstream'))}"],
                     source="community",
                     fix={"kind": "eero_setting",
                          "sets": {"ipv6_upstream": False, "ipv6_downstream": False}}))

    upnp = setting("upnp")
    if upnp is False:
        out.append(F("eero_upnp_off", "medium", "UPnP is disabled",
                     "Sonos uses UPnP for device description and control. Disabling it can "
                     "break discovery and some streaming services.",
                     evidence=["upnp = false"], source="community",
                     fix={"kind": "eero_setting", "sets": {"upnp": True}}))

    # --- the headline check: are wired players on the same eero node?
    node_of, wired_macs = {}, {}
    for d in devs:
        if d.get("wired") and d.get("mac"):
            wired_macs[d["mac"].upper()] = d.get("zone", d["ip"])
    edevs = e.get("devices")
    if isinstance(edevs, list) and wired_macs:
        for ed in edevs:
            mac = (ed.get("mac") or "").upper()
            if mac in wired_macs:
                node = _first(ed, "source.location", "source.display_name", "source.serial",
                              "connected_to", "location")
                if node:
                    node_of.setdefault(str(node), []).append(wired_macs[mac])
        if len(node_of) > 1:
            out.append(F(
                "wired_players_split_across_nodes", "high",
                "Wired Sonos players are spread across different eero nodes",
                "Sonos' own eero article says multiple wired players must share one eero node "
                "or one switch. They are currently split, which bridges the Sonos mesh across "
                "the eero wireless backhaul.",
                evidence=[f"{node}: {', '.join(z)}" for node, z in node_of.items()],
                source="official-sonos",
                fix={"kind": "physical", "steps": [
                    "Consolidate every wired Sonos onto a single eero node, or onto a single "
                    "switch that uplinks to one eero node."]}))
        elif len(node_of) == 1:
            out.append(F("wired_players_same_node", "info",
                         "Wired players share one eero node",
                         f"All wired players attach to {next(iter(node_of))} - this matches "
                         "Sonos' recommendation.",
                         evidence=[f"{n}: {', '.join(z)}" for n, z in node_of.items()],
                         source="official-sonos"))
        elif wired_macs:
            out.append(F("node_attribution_unavailable", "info",
                         "Could not tell which eero node each wired player uses",
                         "The eero device records did not expose a node/location field for the "
                         "Sonos MACs. Check physically which node or switch each wired player "
                         "plugs into.", source="derived"))

    # --- guest network
    if _truthy_setting(net.get("guest_network_enabled")) is True:
        gips = {d["ip"] for d in devs}
        on_guest = [ed for ed in (edevs or [])
                    if ed.get("is_guest") and (ed.get("ip") in gips)]
        if on_guest:
            out.append(F("sonos_on_guest", "high", "Sonos players are on the Guest network",
                         "eero's guest network isolates clients, which blocks Sonos discovery "
                         "and grouping.",
                         evidence=[ed.get("ip") for ed in on_guest], source="derived",
                         fix={"kind": "manual", "steps": [
                             "Re-run Sonos Wi-Fi setup against your main SSID, not the guest SSID."]}))

    # --- DHCP reservations keep controllers from chasing changing IPs
    res = e.get("reservations")
    if isinstance(res, (list, dict)):
        rl = res if isinstance(res, list) else (res.get("data") or [])
        reserved = {(r.get("mac") or "").upper() for r in rl if isinstance(r, dict)}
        missing = [d for d in devs if d.get("mac") and d["mac"].upper() not in reserved]
        if missing and len(missing) == len(devs):
            out.append(F("no_dhcp_reservations", "low",
                         "No DHCP reservations for any Sonos player",
                         "Not required, but pinning each player to a fixed lease removes a "
                         "whole class of 'player vanished after a reboot' problems.",
                         evidence=[f"{d['zone']} {d.get('mac')}" for d in missing[:8]],
                         source="community",
                         fix={"kind": "manual", "steps": [
                             "eero app > Settings > Network Settings > DHCP & NAT > "
                             "Reservations & Port Forwarding - add a reservation per player."]}))
    return out


# --------------------------------------------------------------------------- report
def render(findings, s, e):
    devs = [d for d in s.get("devices", []) if d.get("reachable")]
    L = []
    L.append("=" * 78)
    L.append("  eero <-> Sonos alignment report")
    L.append("=" * 78)
    L.append(f"  players discovered : {len(devs)}")
    L.append(f"  eero data          : {'yes' if e else 'no (local-only checks)'}")
    L.append("")
    L.append(f"  {'Room':<22}{'IP':<16}{'Mode':<15}{'Wired':<7}{'Firmware'}")
    L.append("  " + "-" * 70)
    for d in sorted(devs, key=lambda x: x.get("zone", "")):
        L.append(f"  {(d.get('zone') or '?')[:21]:<22}{d['ip']:<16}"
                 f"{d.get('wifi_mode', '?'):<15}"
                 f"{('yes' if d.get('wired') else 'no'):<7}{d.get('sw', '?')}")
    L.append("")

    if not findings:
        L.append("  No misalignments found.")
        return "\n".join(L)

    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    L.append("  " + ", ".join(f"{counts[k]} {k}" for k in
                              sorted(counts, key=lambda k: SEV_ORDER[k])))
    L.append("")
    for f in sorted(findings, key=lambda x: SEV_ORDER[x["severity"]]):
        L.append(f"{SEV_MARK[f['severity']]} [{f['severity'].upper()}] {f['title']}")
        L.append(f"     source: {f['source']}")
        for line in _wrap(f["detail"], 72):
            L.append(f"     {line}")
        for ev in f["evidence"]:
            L.append(f"       - {ev}")
        fix = f.get("fix") or {}
        if fix.get("kind") == "eero_setting":
            sets = " ".join(f"--set {k}={json.dumps(v)}" for k, v in fix["sets"].items())
            L.append(f"     FIX (automatic): eero_client.py apply {sets} --confirm")
        elif fix.get("steps"):
            L.append(f"     FIX ({fix.get('kind', 'manual')}):")
            for st in fix["steps"]:
                for i, line in enumerate(_wrap(st, 68)):
                    L.append(f"       {'- ' if i == 0 else '  '}{line}")
        L.append("")
    return "\n".join(L)


def _wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sonos", required=True, help="output of sonos_scan.py")
    ap.add_argument("--eero", help="output of eero_client.py fetch")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    s = json.loads(open(a.sonos).read())
    e = json.loads(open(a.eero).read()) if a.eero else None

    findings = check_sonos(s)
    if e:
        findings += check_eero(e, s)

    if a.json:
        auto = {}
        for f in findings:
            if (f.get("fix") or {}).get("kind") == "eero_setting":
                auto.update(f["fix"]["sets"])
        print(json.dumps({"findings": findings, "auto_fixable_eero_settings": auto},
                         indent=2))
    else:
        print(render(findings, s, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
