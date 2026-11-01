# Recipe notes

One Markdown note per recipe in the state's `recipes/` folder, named by a short slug:
`recipes/chili.md`, `recipes/salmon-rice.md`. The slug is how plans refer to it.

## Format

```markdown
---
type: recipe
serves: 4
leftovers: true          # optional: makes a second night's dinner
prep: "thaw the beef the night before"   # optional: becomes a night-before reminder
source: https://...      # optional: where it came from
tags: [weeknight]        # optional
---

# Chili

## Ingredients
- 1 lb ground beef — Meat
- 2 cans kidney beans — Canned
- 1 onion — Produce
- 1/2 cup sour cream — Dairy
- salt — Pantry

## Optional
- 1 tomato — Produce

## Steps
1. Brown the beef with the onion.
2. ...

## Notes
Anything the user said about it ("double the beans", "good with cornbread").
```

## Ingredient lines

`- <quantity> <unit> <item> — <section>`

- Quantity: `1`, `1/2`, `1 1/2`, `0.5`. Optional.
- Unit: lb, oz, g, kg, cup, tbsp, tsp, can, jar, bag, box, package, bunch, head, clove,
  slice, pint, quart, bottle, loaf. Optional; plural is fine.
- Item: what you'd look for in the store - "ground beef", not "85/15 ground beef, room
  temperature". Put preparation ("diced") in the steps.
- Section: after an em dash (`—`) or a pipe (`|`). Optional; defaults to Other.

Keep the item names consistent across recipes ("onion" everywhere, not "yellow onion" in
one and "onion" in another) so the list combines them.

## Optional ingredients

Things the user adds only sometimes go under `## Optional`, in the same line format. The
script reads only `## Ingredients`, so optional items stay off the list unless the user
asks for them that week.

## Choices

When a recipe takes one of several options each time (a grain, a side vegetable), list
them under a heading per choice:

```markdown
## Choose one: veggie
- 1 bunch asparagus — Produce
- 1 bag broccoli — Produce
```

Like Optional, the script ignores these sections. When planning, the chef asks which
option this week and adds it to the list.

## Store sections

Produce · Meat · Seafood · Dairy · Cheese · Bakery · Frozen · Canned · Pantry · Snacks ·
Beverages · Other

The list prints in that order, roughly the walk through a grocery store. If the user's
store is laid out differently, the order can be changed in the script's `SECTION_ORDER`.

## Staples

`recipes/README.md` has a `## Staples` list - things always in the kitchen (olive oil, salt,
pepper). Staples are left off the list. When the user says they're out of one, add it to
that week's list by hand and leave it in Staples.
