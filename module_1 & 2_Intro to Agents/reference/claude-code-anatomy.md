# Reference: The Claude Code Ecosystem

Deep dive on Concepts 9 and 10 of the lesson. Background for understanding Claude Code as a harness, not a chatbot.

## The harness, layered

```
Harness
└── Context Management
    └── Agent Loop
        └── Tools · Memory · Permissions
            └── LLM (the brain)
```

**The model thinks. The harness does.** Everything outside the innermost box is deterministic scaffolding that turns a text predictor into a stateful, autonomous coding agent.

## The five constructs

1. **CLAUDE.md.** Project memory. A markdown file, committed to your project, read automatically at the start of every session. Without it, you re-explain your stack and conventions every time; with it, Claude already knows and you just describe the task.

   A CLAUDE.md can live in two places, and both get loaded automatically:
   - The **project root** (`CLAUDE.md`), for context shared with your whole team.
   - Inside **`.claude/CLAUDE.md`**, for personal preferences and overrides.

   A well-formed CLAUDE.md typically covers five things:
   - **Project overview:** what it does, who uses it, the tech stack.
   - **Common commands:** install, run, test, build, deploy. Claude runs these without asking once they're documented.
   - **Coding standards:** naming conventions, style rules, enforced automatically rather than re-explained.
   - **Architecture patterns:** where things live, what patterns to follow versus avoid.
   - **Constraints and guardrails:** what NOT to do. Deprecated libraries, security boundaries, scope limits.

   You can auto-generate a starting point by running `claude /init`: Claude analyzes your codebase and drafts a CLAUDE.md for you, which you then edit and refine.

2. **Skills.** Reusable instruction packs that extend what Claude can do. A skill is a directory containing a `SKILL.md` file with YAML frontmatter (a `name` and a `description`), plus optional supporting files like scripts, references, or assets.

   Claude uses a skill in two ways: automatically, when it judges the skill relevant to the current task (via the `description` field), or directly, when you invoke it with `/skill-name`.

   File location:
   ```
   your-project/
   └── .claude/
       └── skills/
           └── write-prd/
               └── SKILL.md   ← your skill lives here
   ```

   The value proposition: without a skill, you type a long prompt with all the context, steps, and format spelled out, every single time. With a skill, you type `/write-prd "SSO for enterprise customers"` and Claude does the whole thing, the same way, every time. Skills are markdown files. No code is required to create one.

   A SKILL.md's frontmatter matters:
   - `name`: the slash command you type to invoke it.
   - `description`: tells Claude Code when to *suggest* this skill on its own.
   - `allowed-tools` (optional): what it can access, files, web search, and so on.
   - `$ARGUMENTS`: whatever you type after the command becomes available to the skill's instructions. `/write-prd SSO` passes "SSO" in as the input.

3. **MCP servers (Model Context Protocol).** Connect Claude to external tools and data you already use: GitHub, Slack, Figma, a database. They let Claude take real actions, not just respond: fetch data, update records, trigger workflows.

   The mental model: **Claude is the client** (the brain that decides what to do), the **MCP server is the tool provider** (it exposes capabilities like "search this repo" or "post to this channel"), and the **protocol is the bridge** (the standard way Claude talks to the tool). Flow: Claude → MCP server → tool → result → back to Claude.

4. **Subagents.** Dedicated specialists for complex tasks, defined in `.claude/agents/`. Parallel delegates with fully isolated context.

   Each subagent is a markdown file with its own system prompt, its own tool access, and its own model preference. The `description` field is what triggers it; everything else in the file controls its behavior once triggered.

   Subagents scale two ways: **parallelism** (multiple subagents working on independent pieces at once) and **pipelines** (subagents chained so one's output feeds the next). The more genuinely independent your tasks are, the more leverage you get from splitting them across subagents rather than doing everything in one shared context.

5. **Hooks.** Deterministic control over Claude's behavior, guaranteeing rules are enforced consistently rather than merely suggested to the model.

   How hooks intercept tool calls:
   ```
   Tool Call (e.g. Bash, Edit)
       ↓
   PreToolUse Hook  → can BLOCK the call outright (exit code 2), no exceptions
       ↓ (if not blocked)
   Tool Executes
       ↓
   PostToolUse Hook → runs after, e.g. auto-format code, run tests, log the action
   ```

   Two flavors:
   - **Deterministic hooks:** plain shell scripts that guarantee an outcome (or a block) without depending on the LLM's judgment at all. Example: intercepting `rm -rf` before it runs.
   - **LLM-based hooks:** hooks that use a model to evaluate a condition or transform text, for example checking whether a task is genuinely complete before letting the agent report success.

   The rule that decides when you need one: **prompts suggest, at roughly 95% reliability. Hooks enforce, at 100%.** If a failure would cause real-world harm, build a hook rather than trusting a prompt to hold.

## Anatomy of a `.claude/` folder

```
your-project/
├── CLAUDE.md              ← project memory and instructions, read first, every time
└── .claude/               ← Claude configuration and context
    ├── commands/            custom slash commands (shortcuts for repeatable tasks)
    │   └── review.md          e.g. /review, review my changes
    ├── agents/               reusable AI agent definitions (subagents)
    │   └── code-researcher.md  role + tools for one specialist
    ├── skills/               reusable instruction packs
    │   └── debugging.md        step-by-step guidance for a specific task type
    ├── settings.json         Claude Code configuration (model, theme, etc.)
    └── hooks.json            event hooks and automations
```

Also commonly present at the project root: `docs/` (documentation Claude reads as context), `memory/` (longer-term project notes: decisions, timelines, lessons learned), and `scripts/` (helper tools Claude can invoke).

## Skills vs. subagents vs. the main agent, side by side

| | Context window | Role / responsibility | Scope |
|---|---|---|---|
| **Main agent** | Shared and monolithic, grows with the whole chat history | System orchestrator, interface manager, primary planner | Your interactive terminal session |
| **Subagent** | 100% isolated, spawned fresh, discarded on completion | Focused background execution specialist (deep search, complex debugging) | A process-specific sandbox |
| **Skill** | Injected on demand, directly into whatever window is active | Reusable domain knowledge injection (a recipe, a convention, a procedure) | Cross-platform utility, works wherever invoked |

## Claude Code among other harnesses

Claude Code is one harness among several, each with a different emphasis:

| | Claude Code | Lovable | Cursor | Replit Agent |
|---|---|---|---|---|
| **Purpose** | Real engineering: deep coding, complex projects, refactoring | Quick prototypes and MVPs | AI-first code editing inside your IDE | Build, run, and deploy directly in the browser |
| **Codebase awareness** | Yes, reads your files, understands context | No (cloud-based) | Yes | Yes |
| **Level of control** | Full, end to end: write, run, test, commit, ship, all from your terminal | Limited (mostly black-box builds) | High | High |
| **Data & privacy** | Runs locally, keeps code and data in your environment | Cloud-based | Varies by setup | Runs in the cloud |

The distinguishing claim for Claude Code specifically: it is built for real engineering work across the full lifecycle of a codebase, not just for generating a first draft.
