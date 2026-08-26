# skills

[![skills.sh](https://skills.sh/b/tatimblin/skills)](https://skills.sh/tatimblin/skills)

Agent skills by [Tristan Timblin](https://github.com/tatimblin). Each one is a self-contained
directory under [`skills/`](skills/) — a `SKILL.md`, plus whatever reference docs and scripts
it needs. They work in Claude Code, Cursor, Codex, and ~20 other agents.

## Install

Via the [`skills`](https://skills.sh) CLI, into whichever agents you pick:

```bash
npx skills add tatimblin/skills                       # all of them
npx skills add tatimblin/skills --skill eero-sonos    # just one
npx skills add tatimblin/skills --list                # see what's here first
```

Or as a Claude Code plugin, which adds version tracking and automatic updates:

```
/plugin marketplace add tatimblin/skills
/plugin install eero-sonos@tatimblin-skills
```

## Skills

| Skill | What it does |
|---|---|
| [`eero-sonos`](skills/eero-sonos/) | Diagnoses and fixes Sonos speakers misbehaving on an eero mesh network |

---

## `eero-sonos`

Sonos and eero conflict in specific, checkable ways. This skill measures the live system
instead of guessing: it discovers your real speakers over Sonos' local port-1400 API, reads
their SonosNet mesh topology and spanning-tree state, and reports exactly which settings
violate Sonos' and eero's own published guidance — then offers to apply the reversible fixes.

Use it when players drop out or vanish from the app, audio stutters, rooms won't group,
setup never finishes, or things went wrong right after an eero install.

Every finding carries a `source`, so you can tell vendor documentation (`official-sonos`,
`official-eero`) from widely-reported community findings, and it will tell you plainly when
your system looks healthy and should be left alone.

### What it touches

Worth knowing before you install something that ships 1,250 lines of Python:

- **Discovery and diagnosis need no credentials and write nothing.** `sonos_scan.py` and
  `diagnose.py` only read: SSDP multicast plus HTTP GETs against port 1400 on your own LAN.
  Run these, read the report, and stop there if you like — that catches most real problems.
- **Reading eero settings requires logging into your eero account.** eero ships no local
  API, so this goes through their **unofficial** cloud API, authenticating with a one-time
  code sent to your phone or email. You read the code off your own device and enter it; the
  skill never tries to obtain it. The session token is cached at
  `~/.config/eero-sonos/session.json` with mode `0600` and is never printed.
- **Nothing is written without explicit confirmation.** `apply` is a dry run that prints the
  before/after and changes nothing unless you pass `--confirm`. When you do, it writes a
  rollback file *first*, then reads every field back to verify the change actually took —
  eero's API can return `200` and silently ignore a write, and the skill reports that
  honestly rather than claiming success. Undo anything with `rollback`.
- **Nothing leaves your network except the eero API calls**, and only if you choose to
  authenticate.

### Requirements

Python 3, standard library only — nothing to `pip install`. Run it from a machine on the
same network as the speakers (the main SSID, not a guest network, and not over a VPN).

### Layout

```
skills/eero-sonos/
├── SKILL.md
├── references/
│   ├── checks.md              every check, its provenance, and the vendor guidance behind it
│   ├── sonos-local-api.md     the port-1400 endpoints and how to read them
│   └── eero-api.md            auth flow, endpoints, settings fields
└── scripts/
    ├── sonos_scan.py          SSDP + port-1400 discovery → JSON
    ├── eero_client.py         eero cloud auth, read-only fetch, verified apply, rollback
    └── diagnose.py            correlates both sides into findings with severity and fixes
```

The eero cloud API is unofficial and undocumented; it can change without notice. This
project is not affiliated with, endorsed by, or supported by Sonos or eero.

## License

MIT — see [LICENSE](LICENSE).
