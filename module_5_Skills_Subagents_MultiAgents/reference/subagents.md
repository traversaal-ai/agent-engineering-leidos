# Reference: Subagents

Deep dive on the module's subagent sections. Picks up exactly where the skills recap leaves off: a skill is knowledge you hand to your own session; a subagent is a worker you hand a task to, and it goes off and does it in a context window you never see.

## Building the system vs. proving the output

```
1. BUILD THE SYSTEM (the ingredients & tools you design and assemble)
   Skills          Subagents         Agent Teams        Guardrails         Context
   Reusable        Specialized       Multi-agent         Rules,             Knowledge,
   capabilities     agents with       collaboration       permissions        docs, and
   & workflows      clear roles                           and safety         data

                              |
                    Well-built system enables the agent
                    But quality is proven by the outputs
                              v

2. EVALUATE THE OUTPUT (the taste test that proves it's actually good)
   Evals           Benchmarks        Test Suites        Human Review       Success Metrics
   Automated       Compare against   Task collections    Expert judgment     Accuracy,
   tests of key     known standards   that matter          and feedback        reliability,
   behaviors                                                                    satisfaction

You need both dimensions: GREAT INGREDIENTS + GREAT TASTE TESTS = HIGH QUALITY AGENTS
```

Everything below sits in that first row — skills and subagents are ingredients. The second half of this module (see `agent-evaluation.md`) is the taste test that proves the ingredients were actually good.

## A subagent is a freelancer

```
HOW DELEGATION WORKS — STRICTLY VERTICAL

Your Prompt                     Main Claude
"Research top 3 competitors" -> Matches task -> description -> delegates
                                       |
                                       v
                            Research Subagent
                     Own context window. Searches, reads,
                     synthesizes. Subagents never see each other.
                                       |
                                       v
                            Summary Returned
                    Only the result. The search noise, file reads,
                          and logs stay in the subagent's window.
```

**Without a subagent:** your session fills with search results, intermediate steps, and noise. Claude loses focus on your actual goal.

**With a subagent:** all the messy work happens separately. Only a clean summary comes back. You stay focused and only pay for what matters.

Delegation is **strictly vertical**: your main session talks to a subagent, the subagent works alone, and the subagent hands back a result. Subagents never talk to each other — that lateral communication is exactly what separates a subagent from an agent team (see below).

**Where to place subagent files:** project-level at `.claude/agents/` (shared with your team via git, see `claude-folder-anatomy.md`) or user-level at `~/.claude/agents/` (available across all your projects). Or run `/agents` in Claude Code for an interactive setup wizard that writes the file for you.

## The six fields that matter

A subagent is one markdown file. Everything above the `---` closing line is frontmatter; everything below it is the system prompt.

```yaml
---
name: research-agent
description: Research competitor products, market trends, or background
  context. Use when asked to research, analyze competitors, or gather
  market data.
model: claude-opus-4-6
tools:
  - WebSearch
  - WebFetch
  - Read
memory: .claude/memory/research-agent
skills:
  - competitive-analysis-framework
---

You are a product research specialist.
When given a research task:
1. Search for the most recent information
2. Cross-reference at least 2 sources
3. Return a structured summary:
   - Key findings (3-5 bullets)
   - Source links
   - Gaps or uncertainties flagged

Be concise. Return findings only.
Do not explain your process.
```

| # | Field | What it controls |
|---|---|---|
| 1 | `name` | The unique identifier. Claude Code distinguishes agents through their names. |
| 2 | `description` | **The trigger.** Claude reads this to decide when to delegate. The single most important field. |
| 3 | `model` | Matches the task to the right tier. Opus for deep research. Sonnet for standard tasks. Haiku for fast, high-volume work. |
| 4 | `tools` | Gives only what's needed. Research gets web access. A reviewer gets read-only. Fewer tools = safer, faster, more predictable. |
| 5 | `memory` | Where the agent saves what it learns, so it starts smarter on the next run. |
| 6 | `skills` | Bakes domain knowledge directly into the agent at startup — no prompting required each time. |

## `description` is the trigger — write it as a condition

Claude delegates by matching your request to one field: `description`. Treat it as a condition, not a summary.

```
✗ vague — Claude won't fire it reliably
description: Helps with articles.

✓ specific — fires reliably
description: Draft a full SEO article from an outline.
  Use when asked to write or draft copy.
```

"Use when asked to..." — the more specific the condition, the more reliably the subagent fires. A vague description either never triggers, or triggers on the wrong requests, which is the single most common cause of "my subagent didn't run."

## Give each subagent only the tools its job needs

Fewer tools means a safer, faster, more predictable agent — and it also makes the agent's failure modes easier to reason about, because a tool it doesn't have is a mistake it cannot make.

| Subagent | Tools | Why | Model |
|---|---|---|---|
| `research-agent` | WebSearch, WebFetch, Read | Needs the open web to pull the SERP | Opus |
| `writer` | Read | Never touches the web — just drafts | Sonnet |
| `editor` | Read, Grep | Read-only: flags issues, can't rewrite or break the draft | Sonnet |

The `editor` case is the sharpest example: giving it write access would let it "fix" the draft it's supposed to be judging, collapsing the separation between writing and reviewing that the pipeline depends on.

## Skill vs. subagent — when to use which

| | Skill | Subagent |
|---|---|---|
| **Who triggers it** | You or Claude | Claude — by matching the `description` |
| **Where it runs** | Your context window | Its own fresh context |
| **What it is** | Knowledge: procedure, voice, templates | A worker: tools, model, memory |
| **What comes back** | Everything — all steps stay in your session | A clean summary; the mess stays behind |
| **Best at** | Repeatable know-how | Isolated, delegable work |

A skill is know-how you inject into whatever session is already running. A subagent is a worker with its own context, its own tools, and its own memory — you hand it a task and only see the result.

## Model selection: set a global default so you never overpay

```bash
# Set a global default for ALL sub-agents:
export CLAUDE_CODE_SUBAGENT_MODEL="claude-haiku-4-5-20251001"

# Add to ~/.zshrc or .env to make it permanent

# Override per-agent in its frontmatter:
model: claude-opus-4-6   # this agent always uses Opus
```

**Why this matters:** without a global default, every subagent inherits the same model as your main session — often Opus. One research run fanned out across 10 subagents at Opus rates costs 10x more than it needs to. Set the default once, override only where it counts.

**The model selection rule:**

- **Haiku — global default.** Copywriting, formatting, classification, short lookups. Fast and cheap.
- **Sonnet — balanced tasks.** Code review, PRD analysis, data interpretation. Good default for review agents.
- **Opus — override only.** Deep research, multi-source synthesis, complex reasoning. Worth the cost, but only here.

## Memory: a subagent that gets smarter every run

```yaml
---
name: codebase-scout
description: Explore and map codebase architecture.
  Use when asked to understand how the repo is structured or find a module.
model: claude-sonnet-4-6
tools: [Read, Glob, Grep]
memory: .claude/memory/codebase-scout
---

You are a codebase cartographer.
Update your memory as you discover codepaths, patterns, and key architectural decisions.
Write concise notes: what you found and where.
On each new run, check memory first before re-exploring paths you've already mapped.
```

**How memory accumulates:**

1. **Session 1** — the agent explores the repo cold. Writes a map of what it found to `.claude/memory/codebase-scout/`.
2. **Session 2** — the agent reads its own notes first. Skips already-mapped paths. Focuses on what's new.
3. **Session N** — the agent has a full mental model of your codebase. Answers architecture questions instantly.

**The compound effect:** a memory-enabled subagent doesn't just complete tasks — it becomes a specialist on your specific product. After a few sessions, it knows your schema, your naming conventions, your edge cases. No re-explaining.

## Five useful subagents to start with

| Subagent | What it does | Model |
|---|---|---|
| `research-agent` | Searches the web and synthesizes findings on competitors, market trends, or context. Returns a clean structured summary — the research noise stays out of your session. | Opus |
| `prd-reviewer` | Reads any PRD and flags missing criteria, edge cases, and scope creep — with severity ratings. Load your own PRD template as a skill so reviews align to your team's standards. | Sonnet |
| `code-reviewer` | Scans code changes and flags security issues, logic errors, and missing tests. Read-only access — safe for non-engineers to run as a first check before a human review. | Sonnet |
| `data-analyst` | Reads data exports and returns key stats, anomalies, and trends — without flooding your session with raw rows. Builds memory of your data schema over time. | Sonnet |
| `copy-writer` | Turns a feature description into in-app copy, email subject lines, or onboarding tooltips — in your brand voice. Inject your brand guidelines as a skill for consistent tone every time. | Haiku |

## Worked example: a writer + research + editor pipeline

Three subagents, three different design choices, each shaped by the job:

**`research-agent`** — the web noise never reaches your session. Opus for deep synthesis across many sources; memory so it learns your competitors over time; output locked to always 5 findings + gaps + links; keeps out SERP HTML, dead links, and dozens of raw search calls.

**`writer`** — hand your skill to a worker. Sonnet for strong drafting without Opus cost; a `brand-voice` skill bakes your tone in at startup; a `sample-articles/` folder of examples anchors voice and format; read-only, since it drafts and never touches the web.

*Watch out:* few-shot examples anchor voice and format — not policy. Don't add examples to fix a structural gap; fix the structural gap (the `description`, the tools, or the system prompt) directly.

**`editor`** — it judges the draft, it never touches it. Read-only, so it literally cannot damage the draft; findings, not fixes — the writer revises, the two jobs stay separate; a PASS/FAIL verdict feeds a downstream quality gate; Sonnet for judgment without Opus cost.

## Three subagent patterns for work that would overwhelm a single session

**Pattern 1 — Parallel exploration across many items.** You have 40+ items to document, analyze, or review. One subagent per item runs in parallel. Each returns a structured summary. No coordination needed — each task is independent. Result: hours of work in one session, clean output, no noise in your main context.

**Pattern 2 — Sequential pipeline (spec → review → build).** Three subagents in a chain: a spec agent turns a request into a working spec, a review agent validates it, a build-and-test agent implements and verifies. Each feeds the next. No direct communication between agents — just a clean, repeatable pipeline.

**Pattern 3 — Reusable specialist library.** Build a small catalog of subagents your whole team can use — research, PRD review, code review, copywriting. The community already has 100+ ready-to-customize definitions at subagents.app. Grab one, set the description for your product, and you're running in minutes.

## Real-world example: a blogger's subagent pipeline

Five stages, each a discrete subagent or skill call, feeding the next:

```
1. RESEARCH -> 2. PLAN -> 3. WRITE -> 4a. HUMANIZE #1 -> 4b. HUMANIZE #2 -> 5. PUBLISH
   Understand      Create the    Turn blueprint    Rewrite & remove   Self-audit &     Enrich & finalize
   the landscape    blueprint     into draft         AI tells           fix remaining     Images, meta
   serp_research()  refine_title()  write_content()   tells             description +
                    generate_outline() (2,500-3,500      humanize_pass_1()  humanize_pass_2()  slug, sources,
                    generate_key_        words)          _strip_em_dashes()                     generate_meta()
                    takeaways()                                                                  search_images()
                                                                                                   inject_images()
                                                                                                   wrap_with_branding()
```

Each box is Pattern 2, a sequential pipeline: research feeds plan, plan feeds write, write feeds two humanize passes, and the result feeds publish. Nothing here needs lateral communication — each stage's job is fully determined by what the previous stage produced.

## Real-world example: a procurement audit planning system

A larger, multi-stage system that combines all three patterns and both automation tiers (skills and subagents), plus a full agent team once human approval is granted.

**The problem:** planning a procurement audit is slow, manual, and mostly reading-based. Auditors read contract procedure rules, look through past audit reports, and select a small random sample of payments — without first analyzing the full spend data. It takes more time, can miss high-risk transactions, and makes audit planning less consistent and less data-driven.

**The simplified flow:**

```
Input Data (read-only): contract-rules.pdf, spend/*.xlsx (~15,000 payments),
                          contracts.csv, committee/*.pdf (past audit reports)
        |
        v
1. Extract Rules (SKILL)          — extract testable rules with clause references
2a. Analyse Spend (SUB-AGENT)     — find risk indicators: threshold clustering,
                                      split purchases, off-contract spend, duplicates
2b. Analyse Past Findings (SUB-AGENT) — summarize past audit coverage, open actions,
                                          registered risks
        |
        v (Orchestrator / Main Agent coordinates and combines results)
        v
3. Assess Risks (SUB-AGENT)       — apply likelihood x impact method, produce risk register
        |
        v
4. Human Review                   — auditor reviews and approves risks and scope
        |
        v
5. Audit Plan                     — generate audit program and planning memo from approved risks
```

**The full multi-agent system, step by step:**

1. **Rule Extraction (SKILL)** — `/extract-rules` extracts every testable rule with clause references and verbatim quotes from `contract-rules.pdf`, writing `rules.json`.
2. **Spend Analysis (SUB-AGENT)**, running in parallel with step 2b — analyzes the full spend population (runs Python scripts), identifies risk indicators, writes `analytics.json`.
3. **Past Findings Analysis (SUB-AGENT)**, running in parallel with step 2a — summarizes past audit coverage, open actions, and registered risks, with citations, writes `history.json`.
4. **Risk Assessment (SUB-AGENT)** — merges rules + analytics + history, applies a risk-assessment method (a SKILL: fixed likelihood x impact), rates risks with evidence and citations, produces `risk-register.md`.
5. **Human Auditor** reviews and approves risks and scope, or rejects back to step 3.
6. **Agent Team (after approval)** — three specialists that now *do* talk to each other:
   - **Planner Agent** uses an `audit-program` SKILL to create `planning-memo.md`, `risk-control-matrix.md`, `audit-program.md`.
   - **Challenger Agent** reviews and challenges — looks for weak spots, low rating with strong signal data, repeat findings out of scope — and messages the planner directly, producing `challenges.md`.
   - **QA Reviewer Agent** runs scripts/checks, verifies quotes, numbers, traces, and sampled transactions, blocking sign-off until all checks pass, producing `review.md`.
7. **Human Auditor** signs off the final pack.

**Why steps 1-4 are subagents and step 6 is a team:** steps 1-4 form a clean pipeline (Pattern 2) plus one instance of parallel exploration (Pattern 1, steps 2a/2b) — nothing in that stretch needs two workers to negotiate with each other mid-task. Step 6 is different: the Challenger's findings change what the Planner needs to revise, and waiting for a human to relay that message back and forth would waste real time and budget. That lateral need is exactly the fork this module opens with — see `study-material/lesson.md`, "the single fork in the road."

**Key outcomes:** a rule-based, evidence-backed risk register; a targeted, data-driven audit program; a consistent, transparent methodology; a fully traceable and auditable output — from rules, to risks, to a focused audit plan.

**Check:** In the procurement system above, name the one step where an agent team was used instead of subagents, and explain — using the single fork in the road — exactly what about that step required lateral communication that steps 1-4 didn't.
