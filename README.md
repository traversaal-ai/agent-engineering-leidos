# Agent Engineering Bootcamp

A 7-week, hands-on course on building real AI agents: from a single ReAct loop built by hand, through sub-agents and multi-agent orchestration, RAG, voice interfaces, and production guardrails, ending in a demo day where you ship something real.

Every module in this repo works the same way: learn the concept, then build it, locally, with Claude Code as your build partner.

![Course Overview](images/course-overview.png)

## The 7 weeks

| Week | Focus | You'll be able to |
|---|---|---|
| **1** | Introduction to AI Agents & Agent Harness | Build ReAct reasoning + tool-use loops. Add memory, tracing, and structured outputs. Ship a debuggable agent harness. |
| **2** | Sub-Agents, Multi-Agent Foundations & Coordination | Use sub-agents for specialized tasks. Coordinate agents with shared state and tools. Design patterns for multi-agent collaboration. |
| **3** | Enterprise RAG Systems | Build retrieval, reranking, rewriting, and grounding. Let agents choose tools and knowledge sources. Evaluate faithfulness, coverage, and hallucinations. |
| **4** | Advanced Multi-Agent Systems & Orchestration | Use orchestrator-worker and specialist patterns. Handle dynamic routing, context passing, and failover. Optimize for scalability, observability, and cost. |
| **5** | Voice Agents & Conversational Interfaces | Build streaming STT -> LLM -> TTS pipelines. Handle turn-taking, silence, and interruptions. Optimize for low latency and natural dialogue. |
| **6** | Guardrails, Evaluations & Reliability | Add safety, compliance, and injection guardrails. Test accuracy, tool use, and failure cases. Monitor regressions with judges and human review. |
| **7** | Demo Day | Showcase. Learn. Celebrate. |

**What holds it together, week to week:**

- **Hands-on projects.** Build real systems, not toys.
- **Production focus.** Learn patterns that scale.
- **Reliability & safety.** Ship systems you can trust.
- **Career acceleration.** Stand out. Build the future.
- **Demo Day.** Showcase your work.

## Getting started

### Prerequisites

- **Claude Code**, installed and authenticated:
  ```bash
  npm install -g @anthropic-ai/claude-code
  claude --version
  ```
- **Node.js** (LTS) and **Python 3**, for running the tools inside each module.
- **Chrome or Edge**, needed for the PRD Builder's Save-to-folder feature in Module 1 (Safari and Firefox fall back to a slightly different save path).
- An **Anthropic API key**, from [console.anthropic.com](https://console.anthropic.com). Never commit it. Each module explains exactly where it's safe to put it.

### Clone the repo

```bash
git clone https://github.com/traversaal-ai/agent-engineering-leidos.git
cd agent-engineering-leidos
```

### Start with Module 1

```bash
cd "module_1_Intro to Agents"
```

Then open [`module_1_Intro to Agents/README.md`](module_1_Intro%20to%20Agents/README.md) and follow it: read the lesson, generate a PRD for an idea of your own with the PRD Builder, then hand it to Claude Code and build a real local app from it.

## How each module is meant to be used

1. **Read the study material first.** Every module's `study-material/lesson.md` teaches the concepts before you touch a tool.
2. **Do the hands-on part for real.** Nothing in this course is a toy exercise you copy-paste through. Module 1, for example, has you generate an actual PRD for an actual idea, then build an actual app from it.
3. **Use `reference/` when you want more depth** than the lesson gives, on things like agent architecture levels or the Claude Code construct anatomy.
4. **Keep it local first.** No deployment, no backend, no accounts required to complete any module's hands-on work, unless a specific module's content calls for it.

## Contributing / extending

Each new week gets its own `module_N_Name/` folder with the same shape: a `README.md`, a `CLAUDE.md`, `study-material/`, and `reference/`, plus whatever tools or code that week's lesson needs. Copy Module 1's structure as the starting template.
