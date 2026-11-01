#!/usr/bin/env python3
"""Build a combined shopping list from recipe notes.

Each recipe is a Markdown note with YAML frontmatter and an "## Ingredients"
section of lines like:

  - 1 lb ground beef — Meat
  - 1/2 cup sour cream — Dairy
  - 2 onions — Produce
  - salt — Pantry

The quantity and unit are optional; the store section after " — " (or " | ")
is optional too and falls back to "Other".

  shopping_list.py --recipes-dir recipes chili salmon-rice
  shopping_list.py --recipes-dir recipes chili:2 tacos      # chili cooked twice
  shopping_list.py --recipes-dir recipes chili --staples recipes/README.md

Recipes are named by file stem (recipes/chili.md -> "chili"). Lines under a
"## Staples" heading in the --staples file are left off the list.

Emits JSON on stdout: the list grouped by section, the recipes used, and any
ingredient lines that could not be parsed. Stdlib only. Exits 2 if a named
recipe does not exist.
"""

import argparse
import json
import re
import sys
from collections import OrderedDict
from fractions import Fraction
from pathlib import Path

UNITS = {
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "g": "g", "gram": "g", "grams": "g", "kg": "kg",
    "cup": "cup", "cups": "cup",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "can": "can", "cans": "can", "jar": "jar", "jars": "jar",
    "bag": "bag", "bags": "bag", "box": "box", "boxes": "box",
    "package": "package", "packages": "package", "pkg": "package",
    "bunch": "bunch", "bunches": "bunch", "head": "head", "heads": "head",
    "clove": "clove", "cloves": "clove", "slice": "slice", "slices": "slice",
    "pint": "pint", "pints": "pint", "quart": "quart", "quarts": "quart",
    "bottle": "bottle", "bottles": "bottle", "loaf": "loaf", "loaves": "loaf",
}

SECTION_ORDER = [
    "Produce", "Meat", "Seafood", "Dairy", "Cheese", "Bakery", "Frozen",
    "Canned", "Pantry", "Snacks", "Beverages", "Other",
]

QTY_RE = re.compile(r"^(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*")
SPLIT_RE = re.compile(r"\s+(?:—|–|\|)\s+")


def parse_qty(text):
    text = text.strip()
    if " " in text:
        whole, frac = text.split()
        return Fraction(whole) + Fraction(frac)
    return Fraction(text)


def singular(word):
    for suffix, repl in (("oes", "o"), ("ies", "y")):
        if word.endswith(suffix) and len(word) > 4:
            return word[: -len(suffix)] + repl
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def item_key(name):
    words = name.lower().strip().split()
    if words:
        words[-1] = singular(words[-1])
    return " ".join(words)


def parse_line(line):
    """Return (qty, unit, name, section) or None if the line is not an ingredient."""
    body = line.strip()
    if not body.startswith(("- ", "* ")):
        return None
    body = body[2:].strip()
    if not body:
        return None
    parts = SPLIT_RE.split(body, maxsplit=1)
    main = parts[0].strip()
    section = parts[1].strip().title() if len(parts) > 1 else "Other"
    qty, unit = None, None
    m = QTY_RE.match(main)
    if m:
        try:
            qty = parse_qty(m.group(1))
        except (ValueError, ZeroDivisionError):
            qty = None
        main = main[m.end():]
        first, _, rest = main.partition(" ")
        if first.lower().rstrip(".") in UNITS and rest:
            unit = UNITS[first.lower().rstrip(".")]
            main = rest
    name = main.strip().rstrip(",")
    if not name:
        return None
    return qty, unit, name, section


def ingredient_lines(text):
    """Yield the lines of the first '## Ingredients...' section."""
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            if in_section:
                return
            in_section = line[3:].strip().lower().startswith("ingredients")
            continue
        if in_section:
            yield line


def staples(path):
    if not path or not Path(path).exists():
        return set()
    found, in_section = set(), False
    for line in Path(path).read_text().splitlines():
        if line.startswith("## "):
            in_section = line[3:].strip().lower().startswith("staples")
            continue
        if in_section and line.strip().startswith(("- ", "* ")):
            entry = line.strip()[2:]
            found.add(item_key(SPLIT_RE.split(entry, maxsplit=1)[0]))
    return found


def fmt_qty(q):
    if q is None:
        return ""
    if q.denominator == 1:
        return str(q.numerator)
    whole, rem = divmod(q.numerator, q.denominator)
    frac = f"{rem}/{q.denominator}"
    return f"{whole} {frac}" if whole else frac


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipes", nargs="+", help="recipe file stems, optionally name:times")
    ap.add_argument("--recipes-dir", required=True)
    ap.add_argument("--staples", help="file with a '## Staples' list to leave off")
    args = ap.parse_args()

    rdir = Path(args.recipes_dir)
    skip = staples(args.staples)
    totals = OrderedDict()  # (key, unit) -> dict
    unparsed, used, missing = [], [], []

    for spec in args.recipes:
        stem, _, times = spec.partition(":")
        mult = Fraction(times) if times else Fraction(1)
        path = rdir / f"{stem}.md"
        if not path.exists():
            missing.append(stem)
            continue
        used.append({"recipe": stem, "times": fmt_qty(mult)})
        for line in ingredient_lines(path.read_text()):
            if not line.strip():
                continue
            parsed = parse_line(line)
            if parsed is None:
                if line.strip().startswith(("- ", "* ")):
                    unparsed.append({"recipe": stem, "line": line.strip()})
                continue
            qty, unit, name, section = parsed
            key = item_key(name)
            if key in skip:
                continue
            slot = totals.setdefault((key, unit), {
                "item": name, "unit": unit, "qty": Fraction(0), "counted": True,
                "section": section, "recipes": [],
            })
            if qty is None:
                slot["counted"] = False
            else:
                slot["qty"] += qty * mult
            if stem not in slot["recipes"]:
                slot["recipes"].append(stem)

    if missing:
        json.dump({"error": "recipe not found", "missing": missing,
                   "available": sorted(p.stem for p in rdir.glob("*.md") if p.stem.lower() != "readme")},
                  sys.stdout, indent=2)
        print()
        sys.exit(2)

    by_section = OrderedDict((s, []) for s in SECTION_ORDER)
    for slot in totals.values():
        q = fmt_qty(slot["qty"]) if slot["counted"] and slot["qty"] else ""
        text = " ".join(x for x in (q, slot["unit"] or "", slot["item"]) if x)
        by_section.setdefault(slot["section"], []).append({"text": text, "recipes": slot["recipes"]})

    out = {
        "recipes": used,
        "list": {s: sorted(items, key=lambda i: i["text"].lower()) for s, items in by_section.items() if items},
        "unparsed": unparsed,
        "skipped_staples": sorted(skip),
    }
    json.dump(out, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
