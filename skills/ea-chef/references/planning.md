# Planning the week

## From words to nights

The user describes the week loosely: "We're making chili Monday, leftovers Tuesday, out
Wednesday, salmon Thursday." Turn that into one entry per night they mentioned:

| Said | Entry |
|---|---|
| A dish | Cook that recipe |
| "Leftovers" | Leftovers of the most recent cooked meal (say which) |
| "Out", "eating out", a restaurant name | Out - nothing to buy |
| Nothing for a night | Leave the night off; don't fill it |

Only cooked meals add to the shopping list, and only for what isn't already on hand in
`kitchen.md` - a meal can be fully stocked, or need just one or two things. If the user plans leftovers but the recipe
isn't marked `leftovers: true` and serves fewer than four, mention that it may not stretch.

## The plan file

`plans/YYYY-Www.md`, using the ISO week of the first planned night:

```markdown
---
type: meal-plan
week: 2026-W45
---

# Week of Mon Nov 2

| Night | Meal | Recipe |
| --- | --- | --- |
| Mon Nov 2 | Chili | [[recipes/chili]] |
| Tue Nov 3 | Leftovers (chili) | |
| Wed Nov 4 | Out | |
| Thu Nov 5 | Salmon and rice | [[recipes/salmon-rice]] |

## Shopping list

### Produce
- [ ] 3 onion
### Meat
- [ ] 1 lb ground beef
...
```

Checkboxes let the user tick items off in Obsidian at the store.

## Ledger rows

One row per cooked night in the state's `upcoming.md`:

| Field | Value |
|---|---|
| Date | The night, with the usual dinner time if the state knows it, else the date |
| What | "Chili (dinner)" |
| Kind | Planned meal |
| Next rung | The night before at 6pm if the recipe has `prep`, else morning-of |
| Source | Link to the plan file |
| Notes | The prep note, if any |

Leftovers and out nights get no rows.

## Changing the plan

When the user swaps nights or meals mid-week, update the plan file, regenerate the list
for what hasn't been bought (ask if unsure), and move or remove the ledger rows.
