# Glossary (Source of Truth)

Master list of terms for this module. `study-material/key-concepts.md` repeats the subset most relevant to the lesson itself; this file is the fuller reference.

## The `.claude/` folder

- **`.claude/` folder**: The configuration and context folder Claude Code reads. Exists at three layers: user (`~/.claude/`, personal, follows you everywhere), project (`.claude/` + `CLAUDE.md`, committed to git, shared with the team), and project-personal (`settings.local.json`, `CLAUDE.local.md`, gitignored, just you).
- **`CLAUDE.md`**: Core memory. The file Claude reads first, every time — project rules, tech stack, coding standards, constraints.
- **`.claude/commands/`**: Custom slash commands — shortcuts for repeatable tasks (e.g. `/plan`, `/test`, `/deploy`).
- **`.claude/agents/`**: Reusable subagent definitions — one markdown file per subagent.
- **`.claude/skills/`**: Reusable instruction packs — step-by-step guidance for specific tasks.
- **`settings.json` / `hooks.json`**: Control behavior and automate actions (permissions, model defaults, event-triggered scripts).
- **User vs. team (project) layer**: User layer (`~/.claude/`) affects you in every project — personal style preferences, your own skills. Project layer (`.claude/`, committed) affects everyone who clones the repo — team conventions, shared commands. Project-personal layer (gitignored) affects just you, just this project — your extra permissions, local API keys.

## Skills

- **Skill**: A saved prompt with superpowers — turns a block of written instructions (e.g. 200 words) into a single slash command (e.g. `/write-prd SSO for enterprise`). Runs in your own context window.
- **Skills are deterministic**: A skill produces the same shape of output every time it's given the same kind of input, which is what makes exact-match ground truth possible.

## Automation tiers

- **The single fork in the road**: One question decides which tier of automation to reach for — *do your workers need to talk to each other?* No -> subagents. Yes -> agent teams.
- **Subagent**: A specialist you delegate a task to. Works alone, in its own fresh context window, and hands back a clean result. Communication is strictly vertical (you <-> the subagent); subagents never talk to each other. Token cost roughly 1-1.5x a single session. Stable since July 2025.
- **Agent team**: Multiple specialists that can message each other directly, not just report back to you. Needed when one team member's decision changes what another needs to do, and relaying that manually would waste time and budget. Token cost 3-4x typical, up to 7x in plan mode. Experimental since Feb 2026.
- **The 9/10 rule**: Subagents handle roughly 90% of real-world parallelization needs. Agent teams cover the 10% where lateral coordination genuinely changes the outcome. When unsure, start with subagents — you can always escalate when you hit the coordination wall.
- **Three tiers of automation**: (1) Skills / slash commands — saved workflows you trigger on demand. (2) Sub-agents — a specialist on call, given a task, works independently. (3) Agent teams — multiple specialists working together on complex tasks, with an orchestrator.

## Subagent design

- **The six fields that matter**: `name` (unique identifier), `description` (the trigger — the most important field), `model` (match the task to the right tier), `tools` (give only what's needed, least privilege), `memory` (learns across sessions), `skills` (bakes in domain knowledge at startup).
- **`description` as trigger**: Claude reads the `description` field to decide when to delegate to a subagent. Write it as a condition ("Use when asked to..."); a vague description either never fires or fires on the wrong requests.
- **Least-privilege tooling**: Give each subagent only the tools its job needs. Fewer tools = safer, faster, more predictable output, and a tool the agent doesn't have is a mistake it cannot make.
- **Model selection rule**: Haiku is the global default (copywriting, formatting, classification, short lookups — fast and cheap). Sonnet for balanced tasks (code review, PRD analysis, data interpretation). Opus is override-only (deep research, multi-source synthesis, complex reasoning).
- **`CLAUDE_CODE_SUBAGENT_MODEL`**: An environment variable that sets a global default model for all subagents, so you don't accidentally inherit your main session's (often Opus) model rate for every delegated task. Override per-agent in its own frontmatter where it counts.
- **Subagent memory**: A folder (e.g. `.claude/memory/research-agent`) where a subagent writes notes across sessions. Session 1: explores cold, writes a map. Session 2+: reads its own notes first, skips already-mapped ground, focuses on what's new. The compound effect: the agent becomes a specialist on your specific product over time.
- **Three subagent patterns**: (1) Parallel exploration — one subagent per item across 40+ independent items, no coordination needed. (2) Sequential pipeline — spec agent -> review agent -> build-and-test agent, each feeding the next, no direct communication. (3) Reusable specialist library — a small catalog of subagents (research, PRD review, code review, copywriting) the whole team can reuse.

## Evaluation

- **Ground truth**: The expected behavior you measure an agent against. Three types: **Exact Match** (one correct answer or format — best for structured outputs), **Rubric-Based** (score against clear criteria — best when wording can vary), **Comparative** (compare two outputs, human preference — best when quality is subjective).
- **Skill eval loop (4 steps)**: (1) Write the golden output before you build. (2) Run 5 input variations. (3) Use Claude-as-judge anchored to your ground truth. (4) Fix in `SKILL.md`, rerun until 5/5 pass.
- **Ship threshold, skills**: 5/5 input variations pass the exact-match ground-truth check. Not 4. Not "mostly." If one variation fails, the skill isn't ready — fix the constraint first.
- **Subagents are non-deterministic**: A subagent makes autonomous decisions about what to search, include, or skip, so its output varies run to run — you can't write one exact-match golden output for it, which is why it needs rubric-based ground truth instead.
- **The 4 rubric dimensions**: **Scope adherence** (did it do only what it was asked?), **Source citation** (every factual claim has a verifiable source), **Uncertainty flagging** (what it couldn't find is stated explicitly — confident silence is a fail), **Format compliance** (output matches the structure the description promised).
- **Embedded rubric**: The rubric written directly into the subagent's own system prompt, so the agent checks itself against all four dimensions before responding — turning the agent into its own first-pass QA layer. An external spot-check still follows.
- **Subagent eval loop (5 steps)**: (1) Write 10 ground truth examples. (2) Run the eval against each example. (3) Score and find the failure pattern. (4) Fix in the system prompt, not the output. (5) Don't ship below 8/10.
- **Confidence scorecard**: 10/10 pass -> ship it. 8-9/10 pass -> ship with caution, document edge cases. 5-7/10 pass -> fix first, find the failure pattern. Under 5/10 -> rethink the design, the structure itself is broken.
- **Common failure modes**: **Wrong trigger** (fires when it shouldn't / doesn't fire when it should, or is used beyond its scope), **Wrong process** (skips steps, misuses or oversteps its toolset), **Wrong output format** (doesn't match the expected schema or style), **Efficiency issue** (redundant calls, looping, wasted tokens or time). The same four failure modes recur across skills, subagents, and agent teams — but get more expensive to recover from as coordination increases.
