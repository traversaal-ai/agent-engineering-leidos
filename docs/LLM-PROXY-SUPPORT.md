# Why the tools in this repo need to support an LLM proxy

Written for the maintainers of this repo, from the Leidos cohort. It explains a problem we hit in Module 1 and 2, the change we made on the `llm-proxy-support` branch, and what we would like future modules to do differently.

## The short version

Two tools in Module 1 and 2 called `https://api.anthropic.com` and asked for the model `claude-sonnet-5`, both hardcoded in source. The students in our cohort do not hold keys for `api.anthropic.com`. They hold keys for the Leidos LiteLLM proxy, and that key is rejected at Anthropic's own endpoint. So neither tool could run, no matter what the student pasted into the API key field.

Both values are now configurable, and both default to what was hardcoded before, so they still work for you with api access to anthropic.com.

## Why a proxy is involved at all

This is a credentials problem, not a firewall problem. `api.anthropic.com` resolves and answers from a Leidos workstation. What a student lacks is a key that host will accept.

Leidos uses a LiteLLM proxy in front of AWS Bedrock. The proxy issues the keys, tracks spend per team, applies rate limits, holds the model allow-list, and logs usage. A key it issues is a proxy key: it authenticates against the proxy's hostname and nowhere else. An individual employee cannot sign up for a vendor account and expense it, so for most of the cohort the proxy key is the only credential they will ever have.

Practically, this means three things about the students in the cohort:

1. Their base URL is an internal hostname, not `api.anthropic.com`.
2. Their credential is a proxy key issued in LiteLLM, not a key from `console.anthropic.com`.
3. Their model names are whatever the proxy's config exposes, and those are internal names. The canonical public names may not resolve.

The proxy does implement Anthropic's `/v1/messages`, so the request body and the response shape are unchanged. Only the hostname and the model string differ. That is what makes this a small fix rather than a rewrite.

## Why the hardcoded values are a problem

**The error blames the key, so the student debugs the wrong thing.** A proxy key sent to `api.anthropic.com` comes back as a 401, and the PRD Builder surfaces Anthropic's own message for it, which is `invalid x-api-key`. The key is not invalid. It is valid at a hostname the tool never calls. A student reading that message re-pastes the key, checks it for stray whitespace, then asks for a new one. Nothing about the message points at the URL, because the URL is not on screen and is not mentioned in the module docs. Module 1 and 2 is aimed at PMs and non-engineers, by its own `CLAUDE.md`, so that audience has no reason to suspect a hardcoded endpoint.

**Fixing the URL alone is not enough.** The model name is a second hardcoded value, and a proxy validates it against its own config. A correct base URL with `claude-sonnet-5` returns a 400 that reads `Invalid model name passed in`. A student who guesses their way to the right hostname then hits a second wall that looks unrelated to the first.

**The root README sent students down a path that does not exist for them.** The prerequisites list told the reader to get an Anthropic API key from `console.anthropic.com`, which is a dead end for an enterprise cohort. A later bullet did mention "LLM endpoint access ... your specific cohort provides", but nothing connected the two, so the first read as the requirement and the second as an optional extra. No tool in the repo had a way to accept such an endpoint either. This branch rewrites that bullet, described below.

**The pattern repeats per tool.** We found the same two hardcoded values in the PRD Builder's HTML and in Recapp's `extract-actions` route and key-check script. Every new tool added to a later module inherits the bug unless the default is configurable from the start.

**It blocks the actual lesson.** Nothing in Module 1 or 2 teaches anything about API endpoints. The endpoint is plumbing in service of the real exercise, which is generating a PRD and building from it. Time spent on the plumbing is time taken from the material.

## Where the configuration already lives

This is the part worth borrowing. A student in this cohort has already configured Claude Code to work through the proxy, because the repo requires Claude Code before anything else. Those values sit in `~/.claude/settings.json`, and the same file works the same way on Windows, macOS, and Linux.

So we did not invent a config format. We read the two names Claude Code already uses:

| Name in `settings.json` | What the tools use it for | Fallback |
|---|---|---|
| `ANTHROPIC_BASE_URL` | the base URL, with `/v1/messages` appended by the caller | `https://api.anthropic.com` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | the `model` field in the request body | `claude-sonnet-5` |

A student copies nothing and configures nothing in the common case. Both tools read the values that are already there.

An invented example, with fake values, of the relevant part of such a file:

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "env": {
    "ANTHROPIC_BASE_URL": "https://llm-proxy.example.internal/",
    "ANTHROPIC_AUTH_TOKEN": "sk-fake-not-a-real-token",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-5-sonnet-example-proxy[1m]",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-5-opus-example-proxy[1m]"
  },
  "model": "opus",
  "modelOverrides": {
    "claude-opus-5": "claude-5-opus-example-proxy",
    "claude-sonnet-5": "claude-5-sonnet-example-proxy",
    "claude-haiku-4-5": "claude-haiku-4-5-example-proxy"
  }
}
```

Two details in that file are worth knowing about.

**The bracket suffix.** `[1m]` marks the 1M-context routing variant. It is a Claude Code hint, not part of the model name the endpoint knows. Claude Code accepts `your-model-name[1m]`; LiteLLM rejects that exact string on `/v1/messages` with a 400. Any code that reads a model name out of this file has to strip a trailing `[...]` before sending it. Both of our resolvers do (`strip_alias_suffix` in `server.py`, and the equivalent in `recapp/src/lib/anthropic.mjs`).

**`modelOverrides`.** This maps a canonical model id to the name the proxy knows. It is the other place a proxy model name can be recorded, so a reader comparing two students' files may see the name in either place.

## What the branch changed

Two commits, one per tool. Both keep the previously hardcoded values as fallbacks, so a student or teacher on a direct Anthropic key sees no difference. The branch also rewrites one bullet in the root README.

**PRD Builder** (commit "Route the PRD Builder through a configurable LLM proxy"). The page gets an **LLM Proxy URL** field and appends `/v1/messages` to whatever that field holds. A browser cannot read `~/.claude/settings.json`, so the local `server.py` resolves both defaults and serves them at `GET /config`. A URL the student types is saved in `localStorage` and wins over the served default. A page opened as a `file://` URL has no server to ask and uses both fallbacks. `read_config` returns the fallbacks for a missing file, unreadable file, malformed JSON, or a wrong shape such as `"env": "not-a-dict"`. Check it with `python3 server.py --selftest`.

**Recapp** (commit "Route Recapp's transcript extraction through a configurable LLM proxy"). The `extract-actions` route and the key-check script both read the same two environment names, resolved in one new `src/lib/anthropic.mjs`. It is `.mjs` rather than `.ts` so `scripts/` can import it with no build step. The README told the reader to copy a `.env.example` that did not exist, and the `.gitignore` rule for `.env*` would have excluded it; both are fixed. Check it with `npm run test:config`, which needs no key and makes no network call.

**Root README.** The prerequisites list held two disconnected bullets, one for a `console.anthropic.com` key and one for cohort-provided endpoint access. They are now one credential bullet with two named paths: a console key used with the default endpoint, or a proxy base URL plus a key issued for that proxy. The proxy path says outright that a proxy key is not valid at `api.anthropic.com`, so a reader learns why the endpoint has to change with the key. It also tells a student whose Claude Code already works through the gateway that nothing further needs configuring, and links here. A separate bullet keeps the note about any other credentials a cohort provides.

## What we would ask of future modules

1. Never hardcode a base URL or a model name in a tool a student runs. Read both from configuration, and default to the public Anthropic values.
2. Use these same two names, `ANTHROPIC_BASE_URL` and `ANTHROPIC_DEFAULT_SONNET_MODEL`. One pair of values should make every tool in the repo work.
3. Strip a trailing `[...]` from any model name read from configuration.
4. Ship a committed `.env.example` for any module with a server side, and confirm the `.gitignore` rule does not exclude it.
5. Keep the proxy path first-class in any module README that mentions credentials, rather than an aside. The root README now reads that way, and a module README that contradicts it puts the student back where they started.
