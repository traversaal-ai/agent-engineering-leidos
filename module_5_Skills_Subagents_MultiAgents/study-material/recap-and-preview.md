# Module 5: Recap & Preview (15-Minute Warm-Up)

## Recap from Module 04

Before this module starts, you should be comfortable with:

- Naive RAG and its main pain points
- Introduction to Agentic RAG
- Key techniques: routing, query decomposition, and semantic caching
- Comparison of Naive RAG vs. Agentic RAG
- Introduction to RAG evaluations, retrieval evaluation, generation evaluation

If any of that feels shaky, it's worth a quick pass back through Module 4's `study-material/lesson.md` and `reference/` folder before continuing. This module doesn't build on RAG directly — it takes the same underlying discipline Module 4 taught (build a system, then prove with evaluation that it actually works) and applies it to two new kinds of system: skills and subagents.

## Where this fits in the course

```
WEEK 1              WEEK 2                  WEEK 3            WEEK 4              WEEK 5 (this module)   WEEK 6                 WEEK 7
Introduction to      Skills, Claude.md &     Enterprise RAG    Agentic RAG &       Multi-Agent             Guardrails,             Demo Day
AI Agents & Agent    Agent Operating         Systems            Evaluation           Orchestration           Evaluations &
Harness              System                                                                                     Reliability
```

Week 5 sits between "you can build and evaluate a working Agentic RAG pipeline" (Week 4) and "you can add safety, compliance, and reliability guardrails" (Week 6). This week specifically adds: design multi-agent architectures; coordinate agents with shared state and tools; enable collaboration and handoffs; manage persistency, communication, and human-at-the-loop.

## Coming up (Module 5: Mastering Skills & Subagents)

What you'll be able to do after this session:

- Decide when a task should stay a skill, become a subagent, or eventually need an agent team
- Set up a specialist subagent using the six fields that matter — description as trigger, tools scoped to least privilege, the right model tier, and persistent memory
- Understand how a subagent system breaks a large workflow into independent workers without creating unnecessary coordination

**Watch for:** the single fork in the road — "do your workers need to talk to each other?" Nearly everything in this module's subagent-vs-team half comes back to that one question, and the cost difference (roughly 1-1.5x for subagents vs. 3-4x, up to 7x, for agent teams) is the reason it matters practically, not just architecturally.

## If you only remember one thing walking into class

> A subagent's `description` field is its trigger, and it's the single most important field in the whole file — write it as a condition ("Use when asked to..."), because a vague description either never fires or fires on the wrong requests. And once it's built, remember that skills and subagents need *different* proof: a skill is deterministic, so you exact-match it and ship at 5/5; a subagent is not, so you score it against a four-dimension rubric — scope, citations, uncertainty, format — embedded in the agent itself, and ship at 8/10.

## Not covered this module

Agent teams are introduced and compared against subagents, but this module doesn't build one out end-to-end — that experimental, higher-coordination tier is named for orientation (communication patterns, the 3-4x/7x cost, the procurement audit system's Planner/Challenger/QA Reviewer team after human approval) rather than taught as a from-scratch build the way subagents are. There's no running demo app this module (no `axis/`-equivalent) — every exercise and worked example is done against the lesson's own diagrams, frontmatter examples, and the procurement audit case study, all in `reference/subagents.md` and `reference/agent-evaluation.md`. Guardrails, safety/compliance rejection rules, and full production reliability monitoring are named on the course overview but belong to Module 6.
