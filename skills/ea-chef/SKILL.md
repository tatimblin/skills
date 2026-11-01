---
name: ea-chef
description: The meal-planning advisor for the executive-assistant skill - saves recipes with their ingredients, turns a week of meals described in plain words ("chili Monday, out Tuesday, salmon Wednesday") into a dated plan, builds the combined shopping list, and hands each meal to the assistant's ledger so the brief says what's for dinner and when to start prep. Use when the user shares or asks to save a recipe, plans their meals for the week, asks for a grocery or shopping list, or asks what's for dinner.
---

# Chef

People who shop by meal don't need a pantry tracker. They need three things: their recipes
in one place, a quick way to say what the week looks like, and the list that falls out of
it. This advisor does those, and lets the executive assistant handle timing - "chili
tonight" in the morning brief, "thaw the beef" the night before.

It follows the advisor contract in the executive-assistant skill
(`references/advisor-contract.md`): it never messages the user on its own; it writes to the
state folder and hands items to the ledger.

## Ground rules

- **Recipes and plans live in the state folder**, not in this skill: `recipes/` and
  `plans/`. Pull before writing and commit each change, per the state's `CLAUDE.md`.
- **The user's recipe wins.** Save what they gave you. Normalize the format, never
  "improve" the recipe, swap ingredients or rescale it unasked.
- **Ask, don't guess, about a missing recipe.** If a planned meal has no recipe note, ask
  for it or for its ingredients. Never invent an ingredient list for a dish the user cooks.
- **Store sections are a convenience.** Group the list by section for walking the store;
  when a section isn't known, use "Other" rather than guessing wildly.
- **Never order, buy or send anything.** Sending the list elsewhere (Notes, Reminders, a
  shared doc) is a separate, later step.

## Resolving script paths

`shopping_list.py` runs out of `$SKILL_DIR`, the directory this `SKILL.md` was read from.
That is not the working directory. Resolve it once:

```bash
SKILL_DIR=/absolute/path/to/ea-chef   # the directory containing this SKILL.md
```

Installed as a Claude Code plugin, that path is `"$CLAUDE_PLUGIN_ROOT"`.

## Workflows

### Save a recipe

The user pastes a recipe, gives a link, sends a photo, or just lists ingredients.

1. Extract the title, servings, ingredients (quantity, unit, item) and steps. For a link,
   fetch the page; for a photo, read it.
2. Assign each ingredient a store section from `references/recipe-format.md`.
3. Note whether it makes leftovers and whether it needs prep ahead (thawing, marinating,
   soaking) - ask if it isn't clear and it matters.
4. Write `recipes/<slug>.md` in the format in `references/recipe-format.md`. If a recipe
   with that name exists, show the difference and ask before replacing it.
5. Confirm in one line: name, servings, ingredient count, any flags.

### Plan the week

The user says what they're eating, in any order and any words. See
`references/planning.md` for the details; in short:

1. Get the current date with a clock tool, then map their words to dates. "Monday" means
   the next Monday unless they're planning the current week.
2. Match each meal to a recipe note (by name or close match). Unknown meals → ask.
3. Fill the gaps the user implied: a leftovers night after a recipe marked
   `leftovers: true` when they say so ("leftovers Tuesday") - never silently.
4. Check the calendar for those evenings. Mention a conflict ("you have softball
   Tuesday at 8"), don't resolve it.
5. Build the list:

   ```bash
   python3 "$SKILL_DIR"/scripts/shopping_list.py --recipes-dir <state>/recipes \
     chili salmon-rice tacos --staples <state>/recipes/README.md
   ```

   Use `name:2` for a recipe cooked twice. If a planned recipe has an `## Optional`
   section, ask once per recipe ("tomato this time?") and add any yeses to the list by hand. Review `unparsed` in the output and fix those
   lines in the recipe notes.
6. Write `plans/YYYY-Www.md` (ISO week) with the nights and the list, per
   `references/planning.md`.
7. Hand meals to the ledger: one row per cooked meal, kind "Planned meal", with the prep
   note when the recipe has one.
8. Show the plan and the list in the reply, list grouped by section, ready to copy.

### What's for dinner

Read this week's plan file and answer with tonight's meal and anything to start now.

## In the executive-assistant run

During a process run, the chef only:

- Adds ledger rows for a plan file that has meals not yet in the ledger.
- On the user's planning day (Sunday unless the state says otherwise), if next week has no
  plan file, adds a "Needs you" question: "What's for dinner this week?"

It never plans a week on its own.

## References

| File | Contents |
|---|---|
| `references/recipe-format.md` | The recipe note format, store sections, staples |
| `references/planning.md` | Turning a described week into a plan file and ledger rows |

## Scripts

| Script | Purpose |
|---|---|
| `scripts/shopping_list.py` | Combines recipe ingredients into one list: sums quantities with matching units, scales recipes cooked more than once, leaves off staples, groups by store section. Stdlib only. |

## Interpreting results

- **Quantities with different units stay separate lines** ("1 lb ground beef" and "8 oz
  ground beef"). Merge them in your reply only when the conversion is obvious.
- **Lines without a quantity** ("salt", "tortillas") appear once, unquantified.
- **`unparsed` lines are recipe formatting problems**, not list items. Fix the recipe.
