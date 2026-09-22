# Module 5: Mastering Skills & Subagents

## Learning outcomes for Module 5

By the end of this module you can:

- Decide when a task should stay a skill, become a subagent, or eventually need an agent team
- Set up a specialist subagent — the six fields that matter: write the description as a trigger, scope its tools to least privilege, pick the right model tier, and give it persistent memory so it learns over time
- Understand how a subagent system works — break a large workflow into independent workers without creating unnecessary coordination

---

## Recap from Module 04

Before this module starts, you should be comfortable with:

- Naive RAG and its main pain points
- Introduction to Agentic RAG
- Key techniques: routing, query decomposition, and semantic caching
- Comparison of Naive RAG vs. Agentic RAG
- Introduction to RAG evaluations
- Retrieval evaluation
- Generation evaluation

If any of that feels shaky, go back through Module 4's `study-material/lesson.md` and `reference/` folder first. This module reuses the same underlying habit — build a system, then prove the output is good — just applied to two new kinds of system: skills and subagents.

## Where this fits in the course

```
WEEK 1              WEEK 2                  WEEK 3            WEEK 4              WEEK 5 (this module)   WEEK 6                 WEEK 7
Introduction to      Skills, Claude.md &     Enterprise RAG    Agentic RAG &       Multi-Agent             Guardrails,             Demo Day
AI Agents & Agent    Agent Operating         Systems            Evaluation           Orchestration           Evaluations &
Harness              System                                                                                     Reliability
```

Week 5's own course-overview slide describes itself this way: design multi-agent architectures; coordinate agents with shared state and tools; enable collaboration and handoffs; manage persistency, communication, and human-at-the-loop.

---

## Concept 1: Build the system, then prove the output

Everything in this module sits under one framing, worth holding onto before any of the mechanics:

```
1. BUILD THE SYSTEM (the ingredients & tools you design and assemble)
   Skills          Subagents         Agent Teams        Guardrails         Context

                              |
                    Well-built system enables the agent
                    But quality is proven by the outputs
                              v

2. EVALUATE THE OUTPUT (the taste test that proves it's actually good)
   Evals           Benchmarks        Test Suites        Human Review       Success Metrics

You need both dimensions: GREAT INGREDIENTS + GREAT TASTE TESTS = HIGH QUALITY AGENTS
```

Skills and subagents are ingredients. Building one well is only half the job — the second half of this module is the "taste test" that tells you whether it's actually good: evals, benchmarks, test suites, human review, success metrics.

## Concept 2: Anatomy of a `.claude/` folder

Skills and subagents both live inside `.claude/`, at one of three layers:

| Layer | Location | Who it affects | Example |
|---|---|---|---|
| **User** (personal, global) | `~/.claude/` | You, in every project | Your personal style preferences, your own skills |
| **Project** (shared) | `.claude/` + `CLAUDE.md` — committed to git | Everyone who clones the repo | Team conventions, shared commands |
| **Project** (personal) | `settings.local.json`, `CLAUDE.local.md` — gitignored | Just you, just this project | Your extra permissions, local API keys |

`CLAUDE.md` is core memory — read first, every time. `.claude/commands/` holds shortcuts for repeatable tasks. `.claude/agents/` and `.claude/skills/` are the two folders this module is actually about. Skills and subagents committed at the project level become *team* capabilities: everyone who clones the repo gets the same `research-agent`, the same `/write-prd`, the same review bar.

See `../reference/claude-folder-anatomy.md` for the full folder trees at all three layers.

## Concept 3: A skill is a saved prompt with superpowers

A skill turns a block of written instructions into a single slash command.

**Without a skill:** "Write a PRD for [feature]. Include: problem statement, 3-5 user stories in As a / I want / So that format, MVP vs. V2, success metrics, risks..."

**With a skill:** `/write-prd SSO for enterprise`

The skill stores the full instructions. You only type the name and the topic. Some example skills: `/write-prd` (full PRD from a feature name), `/standup` (Yesterday / Today / Blockers from git log), `/sprint-plan` (ordered backlog from a list of stories), `/exec-summary` (3-bullet exec summary from any doc), `/reverse-prd` (extract a PRD from an existing codebase).

**Why skills are the easiest thing to evaluate rigorously: they're deterministic.** A skill produces the same shape of output every time it's given the same kind of input, so you can write an exact golden output and hold every real output up against it. See Concept 10 below, and `../reference/agent-evaluation.md`, for the full skill eval loop.

**When you deploy a skill to a server**, it translates into three entities and nothing breaks: a route handler (parses input, auth), the Anthropic Agents SDK (agent definition — system prompt, tools, model; the built-in agent loop; stream/response back to the handler), which calls the Anthropic API, and a return to the client (stream chunks or final response).

## Concept 4: The single fork in the road

Before building anything, one question decides which tier of automation you actually need:

```
THE SINGLE FORK IN THE ROAD
Do your workers need to talk to each other?

NO — use Sub-Agents                              YES — use Agent Teams
Each task can be completed independently.        One team member's decision changes what
What one specialist finds doesn't change          another needs to do. They need to talk —
what another needs to do.                          and waiting for you to relay the message
Example: research 3 competitors, review a          wastes time and budget.
PRD, document 47 templates — each is               Example: building a feature where a change
self-contained.                                     on the back end immediately affects the
                                                     front end and the tests.
```

| | Subagent | Agent Team |
|---|---|---|
| **Communication** | You <-> Specialist only | Specialists can message each other directly |
| **Token cost vs. single session** | ~1-1.5x (summary returned) | 3-4x typical — 7x in plan mode |
| **Stability** | Stable (since July 2025) | Experimental (since Feb 2026) |

**The 9/10 rule:** subagents handle ~90% of real-world parallelization needs. Agent teams cover the 10% where lateral coordination genuinely changes the outcome. If you're unsure, start with subagents — you can always escalate when you hit the coordination wall.

## Concept 5: Three tiers of automation

```
TIER 1 — Skills (Slash Commands)
Saved workflows you trigger on demand.
/write-prd   /standup   /exec-summary   ->  Run Skill  ->  Result

TIER 2 — Sub-Agents
A specialist on call. Give it a task, it works independently.
research-agent   code-reviewer   prd-reviewer  -> Task -> Sub-Agent -> Result

TIER 3 — Agent Teams
Multiple specialists working together on complex tasks.
backend + frontend + QA   competing hypotheses debug
Orchestrator -> Backend, Frontend, QA (communicating) -> Completed
```

## Concept 6: A subagent is a freelancer

```
HOW DELEGATION WORKS — STRICTLY VERTICAL

Your Prompt "Research top 3 competitors"
        -> Main Claude (matches task -> description -> delegates)
                -> Research Subagent (own context window; searches, reads,
                    synthesizes; subagents never see each other)
                        -> Summary Returned (only the result; the search
                            noise, file reads, and logs stay in the
                            subagent's window)
```

**Without a subagent:** your session fills with search results, intermediate steps, and noise. Claude loses focus on your actual goal. **With a subagent:** all the messy work happens separately. Only a clean summary comes back. You stay focused and only pay for what matters.

Where to place subagent files: project-level at `.claude/agents/` (shared with your team via git) or user-level at `~/.claude/agents/` (available across all your projects). Or run `/agents` for an interactive setup wizard.

## Concept 7: The six fields that matter

A subagent is one markdown file. The `description` field is the trigger; everything else controls behavior.

```yaml
---
name: research-agent
description: Research competitor products, market trends, or background
  context. Use when asked to research, analyze competitors, or gather
  market data.
model: claude-opus-4-6
tools: [WebSearch, WebFetch, Read]
memory: .claude/memory/research-agent
skills: [competitive-analysis-framework]
---

You are a product research specialist. When given a research task:
1. Search for the most recent information
2. Cross-reference at least 2 sources
3. Return a structured summary: key findings (3-5 bullets), source links,
   gaps or uncertainties flagged

Be concise. Return findings only. Do not explain your process.
```

| # | Field | What it controls |
|---|---|---|
| 1 | `name` | The unique identifier |
| 2 | `description` | **The trigger.** Claude reads this to decide when to delegate. The most important field. |
| 3 | `model` | Match the task to the right tier — Opus for deep research, Sonnet for standard tasks, Haiku for fast, high-volume work |
| 4 | `tools` | Give only what's needed — fewer tools means safer, faster, more predictable output |
| 5 | `memory` | Learns across sessions |
| 6 | `skills` | Bakes in domain knowledge — loads conventions at startup, no prompting required |

**`description` is the trigger — write it as a condition.** "Helps with articles" is too vague to fire reliably. "Draft a full SEO article from an outline. Use when asked to write or draft copy." is specific enough to fire reliably. "Use when asked to..." — the more specific the condition, the more reliably it fires.

**Give each subagent only the tools its job needs.** A `research-agent` needs WebSearch/WebFetch/Read (Opus, since it needs the open web). A `writer` needs only Read (Sonnet, never touches the web — just drafts). An `editor` needs Read + Grep (Sonnet, read-only — it can flag issues but literally cannot rewrite or break the draft).

## Concept 8: Skill vs. subagent — when to use which

| | Skill | Sub-agent |
|---|---|---|
| **Who triggers it** | You or Claude | Claude — by matching the description |
| **Where it runs** | Your context window | Its own fresh context |
| **What it is** | Knowledge: procedure, voice, templates | A worker: tools, model, memory |
| **What comes back** | Everything — all steps in your session | A clean summary; the mess stays behind |
| **Best at** | Repeatable know-how | Isolated, delegable work |

Five starter subagents: `research-agent` (Opus — web search + synthesis, returns 5 findings + gaps + source links), `prd-reviewer` (Sonnet — flags missing criteria, edge cases, scope creep with severity ratings), `code-reviewer` (Sonnet, read-only — flags security issues, logic errors, missing tests), `data-analyst` (Sonnet — reads data exports, returns stats/anomalies/trends without flooding your session), `copy-writer` (Haiku — turns a feature description into in-app copy in your brand voice).

## Concept 9: Model selection and memory

**Set a global default so you never accidentally pay Opus rates for a Haiku-level task:**

```bash
export CLAUDE_CODE_SUBAGENT_MODEL="claude-haiku-4-5-20251001"
# model: claude-opus-4-6   <- override per-agent in its frontmatter where it counts
```

Without a global default, every subagent uses the same model as your main session — often Opus. One research run fanned out across 10 subagents at Opus rates costs 10x more than it needs to.

**The model selection rule:** Haiku — global default (copywriting, formatting, classification, short lookups). Sonnet — balanced tasks (code review, PRD analysis, data interpretation). Opus — override only (deep research, multi-source synthesis, complex reasoning).

**A subagent with memory builds a knowledge base over time.** Session 1: the agent explores cold, writes a map of what it found. Session 2: it reads its own notes first, skips already-mapped paths, focuses on what's new. Session N: it has a full mental model of your codebase and answers architecture questions instantly. The compound effect: a memory-enabled subagent doesn't just complete tasks — it becomes a specialist on your specific product. No re-explaining.

## Concept 10: Three subagent patterns for work that would overwhelm a single session

**Pattern 1 — Parallel exploration across many items.** 40+ items to document, analyze, or review. One subagent per item, in parallel. Each returns a structured summary. No coordination needed — each task is independent.

**Pattern 2 — Sequential pipeline (spec → review → build).** Three subagents in a chain: spec agent turns a request into a working spec, review agent validates it, build-and-test agent implements and verifies. No direct communication between agents — just a clean, repeatable pipeline.

**Pattern 3 — Reusable specialist library.** A small catalog of subagents your whole team can use — research, PRD review, code review, copywriting. The community has 100+ ready-to-customize definitions at subagents.app.

**Worked example (Pattern 2), a blogger's pipeline:** research (understand the landscape) → plan (create the blueprint) → write (turn blueprint into a 2,500-3,500-word draft) → humanize (rewrite and remove AI tells, then self-audit and fix remaining tells) → publish (images, meta description + slug, auto-extracted sources).

See `../reference/subagents.md` for the full worked example of a larger multi-agent system — a procurement audit planning pipeline that uses all three patterns, plus a human-approval gate before handing off to an agent team.

## Concept 11: Skills and subagents need different ground truth

**Skills are deterministic** — you can write exact-match ground truth. **Subagents are non-deterministic** — a subagent makes autonomous decisions about what to search, include, or skip, so its output varies. You can't exact-match it; you need a rubric instead.

**Ground truth types, in general:**

| Type | Best for | Pass condition |
|---|---|---|
| Exact Match | Structured outputs, one correct answer | Output matches exactly |
| Rubric-Based | Wording can vary | Meets minimum score on each criterion |
| Comparative | Quality is subjective | Human reviewers prefer it (e.g. ≥ 70% win rate) |

**The 4-step skill eval loop:** (1) write the golden output before you build, (2) run 5 input variations, (3) use Claude-as-judge anchored to your ground truth, (4) fix in `SKILL.md`, rerun until 5/5 pass. **Ship threshold: 5/5. Not 4. Not "mostly."**

**The 4 rubric dimensions for any subagent:** **Scope adherence** (did it do only what it was asked?), **Source citation** (every factual claim has a verifiable source), **Uncertainty flagging** (what it couldn't find is stated explicitly — confident silence is a fail), **Format compliance** (output matches the structure the description promised). Embed the rubric inside the agent's own system prompt so it self-checks before responding; still spot-check externally afterward.

See `../reference/agent-evaluation.md` for the full comparison, the copy-paste EVAL prompt template, and worked examples of both loops.

## Concept 12: The subagent eval loop, and common failure modes

**The 5-step eval loop:** (1) write 10 ground truth examples, (2) run the eval against each, (3) score and find the failure pattern, (4) fix in the system prompt, not the output, (5) don't ship below 8/10.

**The confidence scorecard:**

| Score | Decision | Action |
|---|---|---|
| 10/10 pass | Ship it | Add to eval suite, monitor in prod |
| 8-9/10 pass | Ship with caution | Document known edge cases, fix in next cycle |
| 5-7/10 pass | Fix first | Find the failure pattern, tighten system prompt |
| Under 5/10 pass | Rethink the design | The scope or prompt structure is broken, not just the constraints |

The eval suite is a living document — rerun all 10 examples every time you change the system prompt; add 3 new examples every time you add a feature.

**Common failure modes, across all three tiers:**

| Failure mode | Skills | Sub-agents | Agent teams |
|---|---|---|---|
| Wrong trigger | Fires when it shouldn't, or doesn't fire when it should | Used for tasks beyond its scope | Lead misassigns tasks, teammates overstep roles |
| Wrong process | Skips steps, misuses tools | Uses too many tools or violates its limited toolset | Teammates skip dependencies, race, or duplicate work |
| Wrong output format | Doesn't match expected schema or style | Returns verbose reasoning instead of a compressed result | Output is inconsistent, fragmented, misaligned |
| Efficiency issue | Redundant tool calls or long detours | Loops or over-explores, wasting tokens | Spends too much time negotiating or re-communicating |

**Watch out for these anti-patterns while building subagents:**

| Instead of... | Do this |
|---|---|
| "Use a bigger model" | Right model per agent |
| "Make the prompt longer" | A scoped subagent + a skill |
| "Swap models / add examples when routing fails" | Fix the description — it's the trigger |
| "Let workers message each other" | Everything routes through the main agent |
| "Assume the worker saw your chat" | Workers wake up empty — pack the task |
| "'Please be thorough' in the prompt" | Quality lives in hooks, the humanize gate |
| "Just summarize it down" | Its own memory folder, exact stats & URLs |

---

## Key Takeaways

1. **Build the system, then prove the output.** Skills, subagents, and agent teams are ingredients; evals, benchmarks, and human review are the taste test. You need both.
2. **One question decides subagent vs. agent team: do your workers need to talk to each other?** No -> subagents (~1-1.5x cost, stable). Yes -> agent teams (3-4x typical, up to 7x in plan mode, experimental). The 9/10 rule: start with subagents.
3. **A subagent's `description` field is its trigger, and the single most important field.** Write it as a condition — "Use when asked to..." — and the more specific it is, the more reliably the subagent fires.
4. **Give each subagent only the tools its job needs.** Least privilege isn't just safety — it's predictability. A tool the agent doesn't have is a mistake it cannot make.
5. **Skills are deterministic, subagents are not.** That single difference is why skills get exact-match ground truth (ship at 5/5) and subagents get rubric-based ground truth embedded in the agent itself (ship at 8/10 on four dimensions: scope, citations, uncertainty, format).
6. **Set a global default model, override only where it counts.** Without one, every subagent silently inherits your main session's often-expensive model.
7. **Subagent memory compounds.** A subagent that writes notes across sessions becomes a specialist on your specific product over time — no re-explaining.
8. **Three patterns cover most delegable work: parallel exploration, sequential pipeline, reusable specialist library.** Save lateral coordination (agent teams) for the ~10% of work that genuinely needs it.

---

## Appendix: Key terms to remember

- **The single fork in the road**: Do your workers need to talk to each other? No -> subagents. Yes -> agent teams.
- **`description` as trigger**: The field Claude reads to decide when to delegate to a subagent — write it as a condition.
- **Rubric-based ground truth**: The 4 dimensions used to evaluate a non-deterministic subagent: scope adherence, source citation, uncertainty flagging, format compliance.
- **Ship threshold, skills**: 5/5 input variations pass exact-match. **Ship threshold, subagents**: 8/10 ground truth examples pass rubric on all four dimensions.
- **The 9/10 rule**: Subagents cover ~90% of real parallelization needs; agent teams cover the 10% that genuinely needs lateral coordination.

## Summary

1. Skills and subagents both live in `.claude/`, at the user, project, or project-personal layer — and both are "ingredients" in the build-then-evaluate framing that runs through the whole module.
2. A skill is a saved, deterministic prompt you or Claude trigger, running in your own context. A subagent is a non-deterministic worker Claude delegates to via its `description` field, running in its own context, returning only a clean summary.
3. One question — do your workers need to talk to each other? — decides subagent vs. agent team. Subagents scale through parallelism and pipelines; agent teams add lateral communication at 3-4x the cost.
4. Because skills are deterministic and subagents are not, they need different ground truth: exact-match for skills (ship at 5/5), rubric-based for subagents (ship at 8/10, embedded in the agent itself so it self-checks).
5. The same four failure modes — wrong trigger, wrong process, wrong output format, efficiency issue — recur across skills, subagents, and agent teams, getting costlier to recover from as coordination increases.

## Where to next

Do `exercises.md` for hands-on practice designing subagent frontmatter, applying the rubric, and diagnosing failure modes — all on paper, no running app required this module. Or ask to be quizzed (`quiz.md`). For the fuller treatment of subagent design (all six fields, the worked writer/research/editor pipeline, and the full procurement audit multi-agent system), see `../reference/subagents.md`. For the full comparison of skill vs. subagent evaluation, the copy-paste EVAL prompt, and the confidence scorecard, see `../reference/agent-evaluation.md`. For where any of these files should live and who they should be shared with, see `../reference/claude-folder-anatomy.md`.
