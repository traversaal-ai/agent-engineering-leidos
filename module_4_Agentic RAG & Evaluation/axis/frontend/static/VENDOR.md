# Vendored client-side dependencies

Three files belong in this directory and are **not** committed: the Inter font in
three weights. Axis runs without them — it degrades visibly rather than silently,
and says so in the footer.

## Fonts

One family carries the whole design: Inter, at 400 for body text, 500 for the
tracked uppercase labels and all metadata, and 600 for headings. Inter is licensed
under the SIL Open Font License, so it is safe to commit and safe for anyone forking
this repository — the same licence reasoning that rules out an AGPL PDF parser.

| File | Family | Source |
|---|---|---|
| `fonts/Inter-Regular.woff2` | Inter 400 | <https://fonts.google.com/specimen/Inter> |
| `fonts/Inter-Medium.woff2` | Inter 500 | <https://fonts.google.com/specimen/Inter> |
| `fonts/Inter-SemiBold.woff2` | Inter 600 | <https://fonts.google.com/specimen/Inter> |

```bash
mkdir -p frontend/static/fonts
# Fetch the woff2 files from the source above and drop them in, keeping the
# filenames exactly as listed — fonts.css references them by name.
```

Total is around 100 KB. Nothing is downloaded for the monospace stack: it is
`ui-monospace, SFMono-Regular, …`, entirely system faces.

**Why Inter, and why one family.** The palette and type here are
`reference/module_3_Enterprise RAG/`'s, value for value — Axis is the second demo
this cohort meets, and a student moving between the two should recognise one system.
Module 3 is Inter throughout and distinguishes headings by weight and negative
tracking rather than by a second face; the display serif that used to live here
(Instrument Serif, with IBM Plex Mono for labels) was the single thing that made the
two look like different products at a glance. Dropping it also means one family
instead of two and no mono download at all.

Module 3 loads Inter from Google Fonts. Axis cannot — see below.

**The page is designed to work without these.** Every stack in `app.css` falls back
to a real system face (`-apple-system` / `Segoe UI` / `ui-sans-serif`), and the
footer reports their absence so it is a known gap rather than a silently
approximated design.

The `@font-face` rules live in `fonts.css`, which `base.html` links **only when the
woff2 files are on disk**. They were in `app.css` unconditionally at first, which
meant three 404s in the server log on every page load of every fresh checkout.
Nothing broke — `font-display: swap` painted the fallback immediately — but a log
full of red 404s is indistinguishable from a real fault, and "those three are
expected" is not something anyone should have to be told twice. A stylesheet that is
never linked makes no requests at all.

## Why vendored rather than a CDN `<link>` or `<script>`

PRD Section 5 has an instructor must-have: *"I want the whole system to run reliably
on a single machine so that a live demo doesn't depend on fragile network or cloud
infrastructure."* A CDN fetch on page load is precisely that dependency. Conference
wifi fails, corporate proxies block unpkg and `fonts.gstatic.com`, and the failure
mode is something on screen quietly not being what it should be in front of a class —
which looks like a bug in Axis, not a network problem.

Commit the files. They are small, they change rarely, and a pinned local copy means
a workshop run two terms from now behaves exactly like today's.

## What used to be here

`htmx.min.js` and `htmx-ext-sse.js`, removed at Milestone 2 — and worth recording,
because they are the reason this file exists in its current shape. They were gated
behind the same `_vendored()` check as the fonts, they were never actually
downloaded, so the branch was permanently false and **no JavaScript ever ran**. HTMX's
one use would have swapped a JSON response into the DOM. Everything the demo needs
(`EventSource`, `fetch`) is native, so it was replaced by one hand-written
`axis.js` — which is ours and committed, and therefore loaded unconditionally.

The lesson generalised: a vendoring gate whose files nobody fetches is a feature
that silently does not exist. Anything added to this file needs a test that fails
when the file is missing *and* the feature claims to work.
