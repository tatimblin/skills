# Graduating a rule to a Gmail filter

A judgment the model makes the same way every time should stop costing a model call. When
a rule is stable, propose a filter; the user imports it; the rule moves to the state's
`graduated.md`.

## When a rule qualifies

All of these:

- It's keyed on something a filter can match: sender, sender domain, recipient, or subject
  words. Rules that need the message body or judgment ("needs a reply") never graduate.
- It decided 10 or more threads, across at least 14 days, per the logs.
- No correction signal touched it in that window.
- No existing filter in `rules/mailFilters.xml` already covers it.

## The proposal

Write the filter as an importable file at `rules/proposed/YYYY-MM-DD.xml`. One file per
day, holding every filter proposed that day:

```xml
<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom' xmlns:apps='http://schemas.google.com/apps/2006'>
  <title>Mail Filters</title>
  <entry>
    <category term='filter'></category>
    <title>Mail Filter</title>
    <content></content>
    <apps:property name='from' value='example.com'/>
    <apps:property name='label' value='Paper Trail/Bills'/>
    <apps:property name='shouldMarkAsRead' value='true'/>
    <apps:property name='shouldArchive' value='true'/>
  </entry>
</feed>
```

Escape `&`, `<`, `>` and quotes inside values. Match the archive and mark-read choices to
the bucket: Paper Trail filters archive and mark read; Feed filters only label.

In the brief, under "Needs you": what the filter does, how many threads it would have
handled, and "Import rules/proposed/YYYY-MM-DD.xml in Gmail Settings → Filters".

## After import

When a later run sees mail from that sender arrive already labeled and out of the inbox,
the filter is live. Then:

1. Add the filter to `rules/mailFilters.xml` so the state mirrors Gmail.
2. Move the rule from `domains/email.md` to `graduated.md` with the date.
3. Delete the proposal file.
