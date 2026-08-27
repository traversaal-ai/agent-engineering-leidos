# Module 1 & 2: Intro to AI Agents

A hands-on workflow: learn what an agent actually is, generate a PRD for your own idea, save it, then hand it to Claude Code and build a real local app from it.

This folder is a template. It does not contain a finished app, it contains the tool and the study material. The app is whatever you build, from whatever PRD you generate.

## The workflow, step by step

| Step | File / Folder | What happens |
|------|---------------|---------------|
| 0. Learn the concepts | [`study-material/lesson.md`](study-material/lesson.md) | What an agent is, the agent harness, the agent loop, and Claude Code's five constructs, before touching any tool |
| 1. Module context | [`CLAUDE.md`](CLAUDE.md) | Standing instructions for the coding agent: what this module is, the folder map, and how to work with you |
| 2. Install skills | [`.claude/skills/`](.claude/skills/) | `/prd-generator` and `/user-story-writer` are installed as Claude Code skills, available anywhere in this module |
| 3. Generate a PRD | [`prd-generator/prd-generator.html`](prd-generator/prd-generator.html) | The PRD Builder. Fill in 4 fields, watch an 8-section PRD stream in, then save it into a new subfolder inside `prd-generator/` |
| 4. Build the app | the prompt the tool gives you | Copy the **Start Building** prompt it shows you, open Claude Code inside that new subfolder, paste the prompt, and ask it to build |
| 5. Run locally | depends on the stack you build | Whatever "run this app" looks like for the app you built, no deployment needed |
| 6. Inspect, iterate | (no file) | Open the app, try it, then ask the coding agent for changes |

## Assignments

| Assignment | What you'll do |
|---|---|
| **1a: Set up your CLAUDE.md** | Write the project-level `CLAUDE.md` for the app you build in this module, covering the tech stack, common commands, coding standards, and constraints, so Claude Code has context every session without you re-explaining it. |
| **1b: Try your skills** | Run `/prd-generator` and `/user-story-writer` on a real feature idea. Read each `SKILL.md` in [`.claude/skills/`](.claude/skills/) to understand how it works. |
| **1c (Bonus): Idea to PRD to MVP** | Take a real product idea through the full workflow: generate a PRD with the PRD Builder, save it, then build the MVP with Claude Code. |

**Skills used:** [`/prd-generator`](.claude/skills/prd-generator/SKILL.md), [`/user-story-writer`](.claude/skills/user-story-writer/SKILL.md)

## 0. Study material

The concepts behind this whole workflow live in [`study-material/`](study-material/), with deeper background in [`reference/`](reference/). No coding examples or notebooks; the teaching is conceptual, and generating your own PRD and app is the hands-on part.

| File | What it is |
|------|------------|
| [`study-material/lesson.md`](study-material/lesson.md) | The main lesson: LLM vs. agent, the harness, the agent loop, Claude Code's five constructs |
| [`study-material/key-concepts.md`](study-material/key-concepts.md) | A quick glossary for fast review |
| [`study-material/exercises.md`](study-material/exercises.md) | Hands-on exercises, no coding, applied to whatever PRD and app you generate |
| [`study-material/quiz.md`](study-material/quiz.md) | 10 self-check questions with answers and hints |
| [`study-material/recap-and-preview.md`](study-material/recap-and-preview.md) | A 15-minute pre-class warm-up |
| [`reference/agent-architectures.md`](reference/agent-architectures.md) | Deep dive: the three levels of agent sophistication |
| [`reference/claude-code-anatomy.md`](reference/claude-code-anatomy.md) | Deep dive: Claude Code's five constructs and the `.claude/` folder anatomy |
| [`reference/glossary.md`](reference/glossary.md) | The fuller source-of-truth term list |

## 1. API keys: never commit them

The PRD Builder needs an Anthropic API key. Two ways to hold one:

- **In the browser tool itself:** paste it into the "Anthropic API Key" field. It is saved only to that browser's `localStorage` and is never written to a file.
- **In your own app**, once you build one: put it in that app's `.env.local`, and confirm `.gitignore` covers `.env*` before committing anything.

Never paste a real key into a `.md` file, a chat, or any source file. If a key is ever exposed, rotate it in the [Anthropic Console](https://console.anthropic.com/settings/keys).

## 2. Use the PRD Builder

Two columns: fill in the form on the left, watch the PRD stream in on the right.

```bash
cd prd-generator
python3 server.py
```

Then open **http://localhost:4321/prd-generator.html** in **Chrome or Edge**.

The **LLM Proxy URL** field at the top of the form controls where the request goes. It is pre-filled for you, so you can usually leave it alone. If your `~/.claude/settings.json` sets `ANTHROPIC_BASE_URL`, the field is pre-filled with that value, so the tool talks to the same proxy your Claude Code already uses. Otherwise it is pre-filled with `https://api.anthropic.com`. Either way the page appends `/v1/messages` itself, so enter only the base URL. If you paste the full endpoint by mistake, the page drops the trailing `/v1/messages` instead of sending it twice. Anything you type is remembered in that browser's `localStorage` and takes priority over the pre-filled default. Clear the field to go back to the default.

The model is picked up the same way, from `ANTHROPIC_DEFAULT_SONNET_MODEL` in the same file, falling back to `claude-sonnet-5`. It has no field in the form, because a proxy that needs a custom base URL may set its own model names too, and reading both from one place keeps them in step. When you start the server it prints both values, so you can confirm what it will use.

If your model name ends in a bracketed suffix, such as `your-model-name[1m]`, the server drops that suffix before the page uses it. Claude Code understands the bracketed form, but a proxy usually rejects it with a `400 Invalid model name passed in`. If you still get that error, the base name is wrong for your key. Ask your proxy administrator which model names your key can use.

Only the local server can read your settings file, so a page opened directly as a `file://` URL always falls back to `https://api.anthropic.com` and `claude-sonnet-5`.

- Paste your API key, then fill in feature name, problem, target users, and constraints
- Click **Generate PRD**. It streams an 8-section PRD live from Claude
- **Save PRD to Folder** opens your browser's folder picker. Navigate to and select this module's `prd-generator/` folder, approve the "Allow this site to edit files?" prompt, and it creates a new subfolder inside `prd-generator/`, named after your app, containing `prd.md`
- **Download as .md** is the usual browser download and works in any browser

After saving, a **Start Building** panel appears with:

- A ready-to-paste prompt for Claude Code, already filled in with your app's name and the PRD's filename, for example: *"I have a new project called `<your app>`. The PRD is in `prd.md`. Read it and help me plan what to build in the first sprint."*
- Two follow-up prompts for after the first build.

Copy that prompt. Open a terminal in the new subfolder Save PRD to Folder just created (inside `prd-generator/`), run `claude`, and paste it in. That's how you hand the PRD off and ask Claude Code to build the app.

Chrome and Edge are required for the folder picker. In Safari and Firefox, **Save PRD to Folder** falls back to writing directly into `prd-generator/` through the local server, and tells you it did so.

**Two different "PRD generator" things exist in this module, so do not mix them up:**

| | `prd-generator/prd-generator.html` | `/prd-generator` (Claude Code skill) |
|--|--|--|
| What it is | A browser page that calls the Anthropic API directly from JS | A skill file (`.claude/skills/prd-generator/SKILL.md`) that Claude Code reads and follows |
| Where you run it | Any browser, even with no code editor open | Inside a `claude` session, anywhere in this module |
| Needs an API key? | Yes, pasted into the page | No, it uses whatever Claude Code session you are already in |
| Why it exists | To show what PRD generation looks like end to end, including the raw API call | To mirror the real course workflow: install a skill, run `/prd-generator`, read its `SKILL.md` to see how it works |

## 3. Build your app

Once you've saved a PRD, you'll have a new subfolder inside `prd-generator/`, named after your app, with `prd.md` inside it. That subfolder is your new project.

1. Copy the **Start Building** prompt shown after saving.
2. Open a terminal in that subfolder: `cd prd-generator/<your-app-name>`
3. Run `claude`, and paste the prompt in.

Claude Code reads `prd.md`, plans the first sprint with you, and starts building, all inside that subfolder.

A few things worth doing as you build:

- Do assignment 1a: write a project-level `CLAUDE.md` for that app.
- Treat the PRD as the source of truth for scope. If you or Claude Code want to add something not in it, decide on purpose, not by accident.
- Keep it local first: no backend, no login, no deployment required to try it.
