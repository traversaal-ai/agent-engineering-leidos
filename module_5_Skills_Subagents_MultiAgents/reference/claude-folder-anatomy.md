# Reference: Anatomy of a `.claude/` Folder

Deep dive on the module's three `.claude/` anatomy slides. Skills and subagents both live inside this folder, so before either one makes sense, it helps to know exactly which layer a given file sits in, who it affects, and whether it travels with you or stays with the project.

## Three layers, one question each

| Layer | Location | Who it affects | Example |
|---|---|---|---|
| **User** (personal, global) | `~/.claude/` | You, in every project | Your personal style preferences, your own skills |
| **Project** (shared) | `.claude/` + `CLAUDE.md` — committed to git | Everyone who clones the repo | Team conventions, shared commands |
| **Project** (personal) | `settings.local.json`, `CLAUDE.local.md` — gitignored | Just you, just this project | Your extra permissions, local API keys |

The question each layer answers: *does this follow me everywhere, or does it belong to this one project? And if it belongs to the project, is it something the whole team should see, or just me?*

## Project level: `your-project/`

```
your-project/
├── CLAUDE.md              Project memory & instructions — read first, every time
├── .claude/
│   ├── commands/          Custom slash commands
│   │   └── review.md      /review — Review my changes
│   ├── agents/             Reusable AI agent definitions
│   │   └── code-researcher.md   Role: Code researcher. Use: deep dive into codebases.
│   ├── skills/             Reusable instruction packs
│   │   └── debugging.md    When stuck -> 1. Isolate 2. Approve -> 3. Verify
│   ├── settings.json       Claude Code settings — model, theme, permissions
│   ├── hooks.json          Event hooks & automations — e.g. notify on completion
│   └── docs/                Project documentation — README, architecture, guides
├── memory/                 Long-term project notes — decisions.md, timeline.md
├── scripts/                Helper scripts & tools — deploy.sh, test.sh, lint.sh
├── README.md               Project overview — what it does and how to use it
└── .gitignore              Git ignore rules — node_modules, .env, .DS_Store
```

`CLAUDE.md` is core memory: the file Claude reads first, every time, holding project rules like "be concise," "use TypeScript," "run tests before done." `.claude/commands/` holds shortcuts for repeatable tasks (`/plan`, `/test`, `/deploy`). `.claude/agents/` and `.claude/skills/` are the two folders this module is actually about — reusable agent definitions and reusable instruction packs, respectively. `settings.json` and `hooks.json` control behavior and automate actions (e.g. `{"autoApprove": false, "permissions": "ask"}` plus a hook that notifies on completion). Everything under `docs/`, `memory/`, and your own content becomes part of what Claude has in context.

## User level: `~/.claude/`

```
                                    YOU
                                     |
                                     v
                              ~/.claude/
                    CLAUDE.md    SKILLS    PREFERENCES
                    (follows you everywhere)
                    /        |         \
                   v         v          v
            PROJECT A   PROJECT B   PROJECT C
            PRD, design   PRD, design  PRD, design
            system,       system,      system,
            commands,     commands,    commands,
            skills,       skills,      skills,
            CLAUDE.md     CLAUDE.md    CLAUDE.md
            (project      (project     (project
             notes)        notes)       notes)
```

Your personal layer stays with you. Each project adds its own context on top. `~/.claude/CLAUDE.md`, `~/.claude/skills/`, and your preferences are the same across Project A, B, and C — they follow you into any repo you open. Each project then layers its own PRD, design system, commands, skills, and project-level `CLAUDE.md` on top of that shared personal base.

## Team level: shared repo + your personal layer on top

```
TEAM PROJECT (in git repo, shared)
team-project/
├── CLAUDE.md          COMMIT   The team contract: conventions, architecture,
│                                 "follow docs/design-principles.md for all UI"
├── docs/               COMMIT   Shared source of truth (PRD, user stories, design principles)
├── .mcp.json           COMMIT   Shared tools (Figma, browser, DB) work for all
└── .claude/
    ├── settings.json         COMMIT     Shared permissions & hooks (e.g. "run lint after every edit")
    ├── settings.local.json   GITIGNORE  Your personal overrides, secrets
    ├── commands/              COMMIT     /code-review, /new-component: same workflow, same quality bar
    ├── skills/                COMMIT     Shared expertise
    └── agents/                COMMIT     Shared subagents

YOU (personal layer, on your machine)
~/.claude/
CLAUDE.md   SKILLS   PREFERENCES   SECRETS   and more
```

The team layer provides the shared context — everything above the line is committed to git and applies to anyone who clones the repo. Your personal layer sits on top of it: `settings.local.json` and `CLAUDE.local.md` are gitignored, so your personal overrides and secrets never leak into the shared project.

**This is where `.claude/agents/` and `.claude/skills/` earn their place in the tree.** Skills and subagents committed at the project level become *team* capabilities — everyone who clones the repo gets the same `research-agent`, the same `/write-prd`, the same review bar. That's the payoff of building them as files rather than as one-off prompts typed into a chat.

## The practical rule

Ask two questions before you decide where a new `CLAUDE.md`, skill, or subagent file goes:

1. **Does this follow me everywhere, or belong to one project?** Personal style preferences and skills you use across every repo -> `~/.claude/`. Project-specific conventions, PRDs, and subagents -> the project's own `.claude/`.
2. **If it belongs to the project, should the team see it?** Team conventions, shared commands, shared subagents, shared skills -> commit them. Your own extra permissions or API keys -> `settings.local.json` / `CLAUDE.local.md`, gitignored.

**Check:** You've built a `code-reviewer` subagent that flags security issues using rules specific to your team's stack. A teammate wants their own local override that also checks for a personal style nit you don't want enforced project-wide. Which file holds the shared `code-reviewer.md`, and which file holds their personal addition, and why does only one of the two get committed?
