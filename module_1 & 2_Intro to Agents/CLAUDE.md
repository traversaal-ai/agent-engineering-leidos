# Module 1 & 2: Intro to Agents

## What this module is

A template for one workflow: learn what an agent actually is, generate your own PRD from your own idea using the PRD Builder here, save it wherever you like, then hand that PRD to Claude Code and build a real local app from it. No deployment, no backend, no accounts required anywhere in this workflow.

This folder does not contain a finished app. It contains the tool that generates a PRD, and the study material to understand what happens next. The app is something you build, from your own PRD, in your own project folder.

## Folder map

```
.claude/skills/         the skills, available anywhere in this module
study-material/         the lesson content: what an agent is, the harness, the loop
  lesson.md               full teaching content, 11 concepts
  key-concepts.md         quick glossary for this module
  exercises.md            hands-on exercises, no coding, applied to whatever PRD/app you generate
  quiz.md                 10 questions with answers and hints
  recap-and-preview.md    a 15-minute pre-class warm-up
reference/              deep dives the study material points to
  agent-architectures.md   the three levels: automation, ReAct, multi-agent
  claude-code-anatomy.md   the five Claude Code constructs and the .claude/ folder anatomy
  glossary.md              the fuller source-of-truth term list
prd-generator/          the PRD Builder tool
  prd-generator.html      the tool, open in Chrome or Edge
  server.py               local server, needed for Save PRD to Folder
```

There are no coding examples or notebooks in this module by design. The teaching is conceptual, and the hands-on part is the workflow itself: generate a real PRD for a real idea of yours, then build it.

## The chain, and what becomes the source of truth

```
prd-generator/prd-generator.html  ->  your PRD (saved wherever you choose)  ->  your app
        (the tool)                          (the spec)                        (built by Claude Code)
```

Once you generate a PRD, it becomes the source of truth for whatever you build from it. Read it before adding or removing scope, and keep it next to the app it describes so Claude Code can find it.

## Skills

- `/prd-generator` ([`.claude/skills/prd-generator/SKILL.md`](.claude/skills/prd-generator/SKILL.md)) generates a structured PRD from a feature brief
- `/user-story-writer` ([`.claude/skills/user-story-writer/SKILL.md`](.claude/skills/user-story-writer/SKILL.md)) converts a feature idea into user stories with Given/When/Then criteria

Any new skill goes in `.claude/skills/<name>/SKILL.md`. Its `name` field in the frontmatter is what makes it typeable as `/<name>`, no separate commands wrapper needed.

## Running things

```bash
# The PRD Builder
cd prd-generator && python3 server.py   # http://localhost:4321/prd-generator.html
```

The PRD Builder needs Chrome or Edge for its folder picker. Safari and Firefox do not support it and fall back to saving into `prd-generator/`.

Once you have built an app from a generated PRD, run it the way that project's stack normally runs (for example `npm run dev` for a Next.js app). That command lives in whichever app folder you create, not in this module folder.

## API keys

Never put a real key in a `.md` file, a prompt, a chat, or any source file. Two safe ways to hold one:

- Paste it directly into the PRD Builder's "Anthropic API Key" field. It is saved only to that browser's `localStorage`, never written to a file.
- If your own app needs a key (for example, to call the Anthropic API from code you build), put it in that app's `.env.local`, and make sure `.gitignore` covers `.env*` before you commit anything.

## How to study this module

Start with `study-material/lesson.md`. Then use the PRD Builder to generate a real PRD for something you actually want to build, and do `study-material/exercises.md` against that PRD and the app you build from it, several exercises are written to be applied to whatever you generate, not to a fixed example. Use `study-material/quiz.md` to self-check, and `reference/` when you want more depth than the lesson gives on the agent-levels framework or the Claude Code constructs.

## Who I am

- I am a PM or non-engineer learning to ship with Claude Code, not a professional developer.
- Explain changes in plain English before making them. Do not assume I know framework internals.
- Everything must run locally. If something needs a backend or a deploy, flag it instead of building it.

## How to work with me

- Keep changes scoped to what I asked for. Do not add features I did not request.
- Verify in the browser before telling me something works.
- **Never use em dashes** in anything you write: chat replies, code comments, UI copy, docs. Use commas, colons, or separate sentences. This applies to prompts you write for other models too, so their output follows it as well.
- Say plainly when something is unverified, stale, or broken rather than glossing over it.
