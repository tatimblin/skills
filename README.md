# skills

[![skills.sh](https://skills.sh/b/tatimblin/skills)](https://skills.sh/tatimblin/skills)

Agent skills by [Tristan Timblin](https://github.com/tatimblin). Each one is a self-contained
directory under [`skills/`](skills/) — a `SKILL.md`, plus whatever reference docs and scripts
it needs. They work in Claude Code, Cursor, Codex, and ~20 other agents.

## Install

Via the [`skills`](https://skills.sh) CLI, into whichever agents you pick:

```bash
npx skills add tatimblin/skills                       # all of them
npx skills add tatimblin/skills --skill volo-sports   # just one
npx skills add tatimblin/skills --list                # see what's here first
```

Or as a Claude Code plugin, which adds version tracking and automatic updates:

```
/plugin marketplace add tatimblin/skills
/plugin install eero-sonos@tatimblin-skills
/plugin install volo-sports@tatimblin-skills
/plugin install local-routine@tatimblin-skills
/plugin install refresh-calendar@tatimblin-skills
```

**`local-routine` needs the plugin install to actually fire.** It ships a
`SessionStart` hook that surfaces due routines, and only the plugin rail
registers hooks automatically. The `npx skills add` rail copies its files —
the skill loads and is usable, but nothing it schedules will ever surface
until a hook is wired up by hand; see
[`skills/local-routine/references/hooks.md`](skills/local-routine/references/hooks.md)
for the manual `settings.json` entry if you install this way. This applies
only to `local-routine`; `refresh-calendar` depends on it for scheduling but
has no hook of its own, and the other skills here need no hook at all.

## Skills

| Skill | What it does |
|---|---|
| [`eero-sonos`](skills/eero-sonos/) | Diagnoses and fixes Sonos speakers misbehaving on an eero mesh network |
| [`volo-sports`](skills/volo-sports/) | Pulls your Volo Sports leagues, schedule and results out of their undocumented API |
| [`local-routine`](skills/local-routine/) | Runs a prompt on a cron schedule, surfacing it in your next session once it comes due |
| [`refresh-calendar`](skills/refresh-calendar/) | Spots a calendar series that will need renewing and schedules a local routine for after it ends |

---

## License

MIT — see [LICENSE](LICENSE).
