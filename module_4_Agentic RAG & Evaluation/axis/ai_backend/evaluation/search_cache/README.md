# Search cache — recorded web results for the class demo

`AXIS_SEARCH__PROVIDER=cached` reads every `*.json` file in this directory and replays
the results instead of calling a live search API.

## Why this exists

PRD Section 5 requires Axis run on a single machine without depending on fragile
network infrastructure. A live search API in front of a class is exactly that
dependency, and it fails in two ways that are hard to recover from mid-demo:

- **It can be unavailable.** The reference notebook
  (`reference/chapter_07_enterprise_rag/agentic_router.py`) is the cautionary example
  rather than a hypothetical — its two internet cells show
  `404 Client Error ... api-ares.traversaal.ai` in committed output, having been
  migrated to a new provider and never successfully re-run.
- **Results change.** An instructor cannot rehearse a demo whose answer differs
  between the rehearsal and the room, and "the web moved" is indistinguishable from
  "the router got it wrong" while a class watches.

## Format

One file per topic — a new demo query is a new file rather than a merge conflict.
Each file is a JSON object mapping a query to its results:

```json
{
  "which large language models were released this year": [
    {
      "title": "Model releases, 2026 so far",
      "url": "https://example.com/releases",
      "snippet": "The snippet text exactly as the search API returned it."
    }
  ]
}
```

Query keys are matched case-insensitively with whitespace collapsed, so a retyped
question still hits. They are **not** hashed, deliberately: this file is meant to be
read and edited by a person preparing a demo, and a file keyed by hex digests could
not be.

## Recording

Run the query once against the live provider and copy what came back:

```bash
AXIS_SEARCH__PROVIDER=serpapi AXIS_SEARCH__API_KEY=... python -m axis
```

Ask the question through the UI with Agentic RAG selected, open the trace, and copy
the `web_sources` attribute from the `search_web` step into a file here. The trace
records exactly the fields this cache needs, which is why no separate export tool
exists.

**Do not hand-write plausible-looking results.** The point of the cache is that the
class sees what a real search returned; invented snippets in a teaching tool are
indistinguishable from a model hallucinating, which is the one thing this platform
exists to make visible.

## An empty directory is an error, not a fallback

`CachedSearchProvider` refuses to construct when it finds no recordings. A cached
provider that returned nothing for every query would look configured, would be routed
to, and would fail silently in the room — which is the failure it exists to prevent.
Axis therefore fails during prep instead.
