#!/usr/bin/env python3
"""Discover Sonos players on the LAN and capture the state needed for eero checks.

Emits JSON on stdout. Uses only the Python standard library.

  python3 sonos_scan.py                # SSDP discovery + probe
  python3 sonos_scan.py --sweep        # also TCP-sweep :1400 across the local /24-/22
  python3 sonos_scan.py --pretty       # human-readable table on stderr as well
"""
import argparse, concurrent.futures as cf, ipaddress, json, re, socket, struct
import subprocess, sys, time, urllib.error, urllib.request
import xml.etree.ElementTree as ET

SSDP_ADDR, SSDP_PORT = "239.255.255.250", 1900
ST = "urn:schemas-upnp-org:device:ZonePlayer:1"
PORT = 1400


def _log(msg):
    print(msg, file=sys.stderr)


# --------------------------------------------------------------------------- local net
def local_networks():
    """Return [{'ip','prefixlen','cidr','iface'}] for real IPv4 LAN interfaces."""
    out = []
    try:
        if sys.platform == "darwin" or "bsd" in sys.platform:
            txt = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=10).stdout
            iface = None
            for line in txt.splitlines():
                m = re.match(r"^(\w+):", line)
                if m:
                    iface = m.group(1)
                m = re.search(r"inet (\d+\.\d+\.\d+\.\d+) netmask (0x[0-9a-fA-F]+)", line)
                if m and iface and not iface.startswith(("lo", "utun", "awdl", "llw")):
                    ip, mask = m.group(1), int(m.group(2), 16)
                    plen = bin(mask).count("1")
                    out.append({"iface": iface, "ip": ip, "prefixlen": plen})
        else:
            txt = subprocess.run(["ip", "-o", "-4", "addr", "show"],
                                 capture_output=True, text=True, timeout=10).stdout
            for line in txt.splitlines():
                m = re.search(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+)/(\d+)", line)
                if m and not m.group(1).startswith(("lo", "docker", "veth")):
                    out.append({"iface": m.group(1), "ip": m.group(2),
                                "prefixlen": int(m.group(3))})
    except Exception as e:  # pragma: no cover - platform dependent
        _log(f"[warn] could not enumerate interfaces: {e}")
    for n in out:
        n["cidr"] = str(ipaddress.ip_network(f"{n['ip']}/{n['prefixlen']}", strict=False))
    return out


def default_gateway():
    try:
        if sys.platform == "darwin" or "bsd" in sys.platform:
            txt = subprocess.run(["netstat", "-rn", "-f", "inet"],
                                 capture_output=True, text=True, timeout=10).stdout
            for line in txt.splitlines():
                f = line.split()
                if len(f) >= 2 and f[0] == "default" and re.match(r"^\d+\.", f[1]):
                    return f[1]
        else:
            txt = subprocess.run(["ip", "route", "show", "default"],
                                 capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"via (\d+\.\d+\.\d+\.\d+)", txt)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- discovery
def ssdp_discover(timeout=6.0, tries=3):
    """Multicast M-SEARCH for ZonePlayers. Returns {ip: {headers}}."""
    msg = ("M-SEARCH * HTTP/1.1\r\n"
           f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
           'MAN: "ssdp:discover"\r\n'
           "MX: 2\r\n"
           f"ST: {ST}\r\n\r\n").encode()
    found = {}
    socks = []
    for net in local_networks() or [{"ip": "0.0.0.0"}]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                             socket.inet_aton(net["ip"]))
            except OSError:
                pass
            s.settimeout(0.6)
            socks.append(s)
        except OSError:
            continue
    for _ in range(tries):
        for s in socks:
            try:
                s.sendto(msg, (SSDP_ADDR, SSDP_PORT))
            except OSError:
                pass
        time.sleep(0.2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        for s in socks:
            try:
                data, addr = s.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            txt = data.decode("utf-8", "replace")
            if "ZonePlayer" not in txt and "Sonos" not in txt:
                continue
            h = {}
            for line in txt.split("\r\n")[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    h[k.strip().upper()] = v.strip()
            found.setdefault(addr[0], h)
    for s in socks:
        s.close()
    return found


def _port_open(ip, port=PORT, timeout=0.4):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return ip
    except OSError:
        return None


def sweep_discover(max_hosts=2048):
    """TCP-connect sweep of :1400 across local subnets. Fallback when SSDP is blocked."""
    targets = []
    for net in local_networks():
        try:
            n = ipaddress.ip_network(net["cidr"])
        except ValueError:
            continue
        if n.is_loopback or n.num_addresses > max_hosts:
            continue
        targets += [str(h) for h in n.hosts()]
    targets = list(dict.fromkeys(targets))
    if not targets:
        return []
    hits = []
    with cf.ThreadPoolExecutor(min(256, len(targets))) as ex:
        for r in ex.map(_port_open, targets):
            if r:
                hits.append(r)
    return hits


# --------------------------------------------------------------------------- probing
def _get(ip, path, timeout=5):
    url = f"http://{ip}:{PORT}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def _xml(text):
    if not text:
        return None
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return None


def probe(ip):
    """Collect one player's alignment-relevant state."""
    d = {"ip": ip, "reachable": False}

    root = _xml(_get(ip, "/status/zp"))
    if root is None:
        return d
    d["reachable"] = True
    zpi = root.find("ZPInfo")
    info = {c.tag: (c.text or "") for c in (zpi if zpi is not None else [])}
    d.update({
        "zone": info.get("ZoneName", ""),
        "uid": info.get("LocalUID", ""),
        "mac": info.get("MACAddress", "").upper(),
        "serial": info.get("SerialNumber", ""),
        "sw": info.get("SoftwareVersion", ""),
        "hw": info.get("HardwareVersion", ""),
        "series_id": info.get("SeriesID", ""),
        "swgen": info.get("SWGen", ""),
        "household": info.get("HouseholdControlID", "").split(".")[0],
    })

    # --- wireless mode: WifiMode 0 = SonosNet (mesh/AP), 1 = station (joined your wifi)
    w = _xml(_get(ip, "/status/wireless"))
    wi = w.find("./Wireless/WirelessInfo") if w is not None else None
    if wi is not None:
        d["wifi_mode"] = (wi.findtext("WifiModeString") or "").strip()
        d["wifi_mode_num"] = (wi.findtext("WifiMode") or "").strip()
        d["wifi_flags"] = (wi.findtext("BusyClients") or "").strip()
        d["wifi_idle_state"] = (wi.findtext("IdleState") or "").strip()
    # --- ethernet ports
    e = _xml(_get(ip, "/status/enetports"))
    ports = []
    if e is not None:
        for p in e.findall("./EnetPorts/Port"):
            ports.append({"port": p.get("port"),
                          "link": (p.findtext("Link") or "0").strip() == "1",
                          "speed": (p.findtext("Speed") or "0").strip()})
    d["enet_ports"] = ports
    d["wired"] = any(p["link"] for p in ports)
    d["link_speeds"] = [p["speed"] for p in ports if p["link"]]

    # --- spanning tree: reveals SonosNet mesh shape and blocked (redundant) paths
    stp_txt = re.sub(r"<[^>]*>", " ", _get(ip, "/status/showstp") or "")
    stp = {"enabled": "STP is disabled" not in stp_txt, "ports": []}
    m = re.search(r"bridge id\s+(\S+)", stp_txt)
    stp["bridge_id"] = m.group(1) if m else None
    m = re.search(r"designated root\s+(\S+)", stp_txt)
    stp["root_id"] = m.group(1) if m else None
    m = re.search(r"root port\s+(\d+)\s+path cost\s+(\d+)", stp_txt)
    if m:
        stp["root_port"], stp["path_cost"] = int(m.group(1)), int(m.group(2))
    stp["is_root"] = bool(stp["bridge_id"] and stp["bridge_id"] == stp["root_id"])
    for pm in re.finditer(
            r"(\w+)\s+\((\d+)\)(?:\s*-\s*tunnel to\s+([0-9A-Fa-f:]+))?[^\n]*\n"
            r"\s*port id\s+\S+\s+state\s+(\w+)", stp_txt):
        stp["ports"].append({"iface": pm.group(1), "index": int(pm.group(2)),
                             "tunnel_to": (pm.group(3) or "").upper() or None,
                             "state": pm.group(4)})
    d["stp"] = stp

    # --- radio driver: the only reliable way to tell a disabled radio from an idle one.
    # A player whose Wi-Fi is switched off still reports wifi_mode SONOSNET_MODE, but this
    # endpoint returns an empty <File/>. Also carries noise floor and per-neighbour rates.
    ath = _get(ip, "/status/proc/ath_rincon/status") or ""
    # True when the SonosNet radio driver is reporting state. Pure Wi-Fi stations may
    # report nothing here, so only trust this for players in SONOSNET_MODE.
    d["sonosnet_radio_active"] = "Mode:" in ath
    nf = [int(x) for x in re.findall(r"Noise Floor:\s*(-?\d+) dBm", ath)]
    d["noise_floor"] = [n for n in nf if n < 0]  # 0 dBm is an unread chain, not a reading
    d["worst_noise_floor"] = max(d["noise_floor"]) if d["noise_floor"] else None
    m = re.search(r"Operating on channel \d+\s*\n\s*IEEE channel:\s*(\d+)", ath)
    d["radio_channel"] = int(m.group(1)) if m else None
    m = re.search(r"Home channel is \d+\s*\n\s*IEEE channel:\s*(\d+)", ath)
    d["sonosnet_home_channel"] = int(m.group(1)) if m else None
    d["neighbors"] = [{"mac": mm.group(1).upper(), "rate_from": int(mm.group(2)),
                       "rate_to": int(mm.group(3))}
                      for mm in re.finditer(
                          r"Node ([0-9A-Fa-f:]{17}) - FROM\s+(\d+)[^:]*: TO\s+(\d+)", ath)
                      if int(mm.group(2)) or int(mm.group(3))]

    # mesh participation: ath* ports in the bridge = live SonosNet links
    d["mesh_links"] = len([p for p in stp["ports"] if p["iface"].startswith("ath")])
    mode = d.get("wifi_mode") or ""
    d["is_ht_satellite"] = "SATELLITE" in mode
    # A player only counts as "on SonosNet" if its radio is actually up. Mode string alone
    # is stale on players whose Wi-Fi has been disabled.
    d["on_sonosnet"] = mode == "SONOSNET_MODE" and d["sonosnet_radio_active"]

    # --- addressing
    ifc = _get(ip, "/status/ifconfig") or ""
    m = re.search(r"br0.*?inet addr:(\S+)\s+Bcast:\S+\s+Mask:(\S+)", ifc, re.S)
    if m:
        d["ipv4"], d["netmask"] = m.group(1), m.group(2)
        try:
            d["cidr"] = str(ipaddress.ip_network(f"{m.group(1)}/{m.group(2)}", strict=False))
        except ValueError:
            pass
    d["ipv6_global"] = re.findall(r"inet6 addr: ([0-9a-f:]+)/\d+ Scope:Global", ifc)
    m = re.search(r"br0.*?RX packets:\d+ errors:\d+ dropped:(\d+)", ifc, re.S)
    d["rx_dropped"] = int(m.group(1)) if m else None
    return d


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep", action="store_true",
                    help="also TCP-sweep :1400 (finds players when multicast is blocked)")
    ap.add_argument("--timeout", type=float, default=6.0, help="SSDP listen seconds")
    ap.add_argument("--pretty", action="store_true", help="also print a table to stderr")
    a = ap.parse_args()

    nets = local_networks()
    _log(f"[*] local: {', '.join(n['cidr'] + ' on ' + n['iface'] for n in nets) or 'unknown'}")

    _log("[*] SSDP discovery...")
    ssdp = ssdp_discover(a.timeout)
    _log(f"[*] SSDP found {len(ssdp)} player(s)")

    ips = set(ssdp)
    swept = []
    if a.sweep or not ssdp:
        _log("[*] sweeping :1400 ...")
        swept = sweep_discover()
        _log(f"[*] sweep found {len(swept)}")
        ips |= set(swept)

    with cf.ThreadPoolExecutor(16) as ex:
        devices = [d for d in ex.map(probe, sorted(ips, key=lambda s: tuple(map(int, s.split(".")))))
                   if d.get("reachable")]

    for d in devices:
        h = ssdp.get(d["ip"], {})
        d["ssdp_household"] = h.get("X-RINCON-HOUSEHOLD")
        d["ssdp_seen"] = d["ip"] in ssdp
        m = re.search(r"Sonos/\S+\s+\(([^)]+)\)", h.get("SERVER", ""))
        d["model_code"] = m.group(1) if m else None

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "local_networks": nets,
        "gateway": default_gateway(),
        "discovery": {
            "ssdp_count": len(ssdp),
            "sweep_count": len(swept),
            "sweep_ran": bool(a.sweep or not ssdp),
            # players reachable on :1400 but silent on multicast => discovery is being dropped
            "ssdp_missed": sorted(d["ip"] for d in devices if not d["ssdp_seen"]),
        },
        "devices": devices,
    }
    print(json.dumps(result, indent=2))

    if a.pretty:
        _log("")
        _log(f"{'IP':<16}{'Zone':<22}{'Mode':<15}{'Wired':<7}{'Firmware':<12}")
        _log("-" * 72)
        for d in sorted(devices, key=lambda x: x.get("zone", "")):
            _log(f"{d['ip']:<16}{d.get('zone','')[:21]:<22}{d.get('wifi_mode','?'):<15}"
                 f"{('yes' if d.get('wired') else 'no'):<7}{d.get('sw','?'):<12}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
