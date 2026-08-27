# Module 1: Intro to Agents

## What this module is

A worked example of one repeatable workflow: take a problem, turn it into a PRD with a tool, then hand that PRD to an AI coding agent and end up with a running local app. No deployment, no accounts anywhere in it. Local-first by default: an app only gets a backend or an external API call if its own PRD and CLAUDE.md call for one, and that should be the exception, not the norm.

This pattern is meant to be reused for more than one app. Not every app that gets a PRD ends up built: some stay PRD-only, others go on to a full local app with its own CLAUDE.md.

## Folder map

```
.claude/skills/            the skills, available anywhere in this module
prd-generator/              the PRD Builder tool, and the PRDs it generated
  prd-generator.html          the tool, open in Chrome
  server.py                   local server, needed for Save PRD to Folder and for the default proxy URL
  <app-name>/prd.md            one PRD per app
<app-name>/                 an app, built from its PRD, with its own CLAUDE.md for app-level detail
```

When a new app gets built from a PRD, it gets its own top-level folder in this module, with its own CLAUDE.md, following the same shape as any other app already built here.

## The chain, and what is the source of truth

```
prd-generator/prd-generator.html  ->  prd-generator/<app-name>/prd.md  ->  <app-name>/
        (the tool)                          (the spec)                     (the app)
```

`prd-generator/<app-name>/prd.md` is **the source of truth for that app's scope**. Read it before changing the app or arguing about whether something belongs.

## Skills

- `/prd-generator` ([`.claude/skills/prd-generator/SKILL.md`](.claude/skills/prd-generator/SKILL.md)) generates a structured PRD from a feature brief

Any new skill goes in `.claude/skills/<name>/SKILL.md`, with an optional matching `.claude/commands/<name>.md` wrapper so it can be typed as `/<name>`.

## Running things

```bash
# Any built app
cd <app-name> && npm run dev            # http://localhost:3000

# The PRD Builder
cd prd-generator && python3 server.py   # http://localhost:4321/prd-generator.html
```

The PRD Builder needs Chrome or Edge for its folder picker. Safari and Firefox do not support it and fall back to saving into `prd-generator/`.

The **LLM Proxy URL** field decides which endpoint the page calls. This copy of the tool matches the module's copy in [`../prd-generator/`](../prd-generator/). The module [`CLAUDE.md`](../CLAUDE.md) documents the field, the `GET /config` route, and the two settings the server reads.

## API keys

If an app needs one, the key lives in that app's own `.env.local`, which is gitignored. Never put a real key in a `.md` file, a prompt, or any source file. If the app has a `test:key` script, use it to check a key works without printing it, e.g.:

```bash
cd <app-name> && npm run test:key
```

## Who I am

- I am a technical person or PM: comfortable with technical concepts, but not a developer. I am learning to ship with Claude Code.
- Explain changes in plain English before making them. Do not assume I know framework internals.
- Everything must run locally by default. If an app needs a backend, a deploy, or an external API call, flag it explicitly rather than adding it silently, and note it in that app's own CLAUDE.md scope guardrails.

## How to work with me

- Keep changes scoped to what I asked for. Do not add features I did not request.
- Verify in the browser before telling me something works.
- **Never use em dashes** in anything you write: chat replies, code comments, UI copy, docs. Use commas, colons, or separate sentences. This applies to prompts you write for other models too, so their output follows it as well.
- Say plainly when something is unverified, stale, or broken rather than glossing over it.
